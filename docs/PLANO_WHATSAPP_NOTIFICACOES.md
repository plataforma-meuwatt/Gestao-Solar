# Plano — WhatsApp do Gestão Solar: notificações (frente 1) e IA (frente 2)

> Arquivo autossuficiente: a conversa que o gerou não estará disponível. Tudo que está aqui
> foi verificado por **leitura de código** dos três repositórios (nada executado), exceto o
> que está marcado ⚠. Repositórios: `C:\Dev\Gestao Solar` (GS), `C:\Dev\meuPlano` (MP),
> `C:\Dev\meuWatt\mw-api` (MW).

## Contexto

A comunicação com o cliente final é do **Gestão Solar**. A conta Meta (Cloud API) está pronta:
- WABA ativa e empresa verificada;
- número de **teste** (Phone Number ID `1352387357947608`, WABA `1050499467726264`, App `1088684893680434`, Business `1991828342203971`);
- token **temporário**;
- Graph API v25.0.

Três frentes, na ordem de prioridade do dono:

1. **Notificações do sistema.** É o foco agora.
2. **IA.** O cliente pede algo, a IA do GS entende e as IAs do MP e do MW respondem. Vem depois da frente 1.
3. **Atendimento humano.** **Descartado.** Se um dia for preciso, contrata-se serviço pronto.

Antes de tudo entra a **Entrega 0**, uma falha de segurança grave achada no caminho.

---

## Decisões do dono

| Tema | Decisão |
|---|---|
| Dono do WhatsApp | GS. O gateway assume a callback da Meta; o bot/webhook do MP (`/api/whatsapp/webhook`) é aposentado. |
| Quem recebe | Só usuário cadastrado no GS (`gs_users`), com telefone e aceite. Número desconhecido não recebe nem é atendido. |
| Funil | Parte da **pessoa**; depois as **usinas dela** que ela escolheu (pode ter 10 e querer só 2). |
| Padrão | **Tudo desligado** até o gestor marcar. |
| Aceite (opt-in Meta) | **Cláusula no contrato.** Na central, o gestor marca "aceite no contrato" com data. Sem essa marca, nada é enviado. |
| Parada | Uma mensagem **por usina**, listando o que parou. Só após **15 min** parado. Se algo novo parar enquanto a usina ainda tem parada, **nova mensagem** com tudo o que está parado. |
| Início de manutenção | Técnico inicia a OS: cronômetro Iniciar, "Iniciar execução" ou play na tarefa. **Uma mensagem por OS**, no primeiro que acontecer. |
| Fim de operação | Botão **Finalizar** do cronômetro **ou** Fechar/Concluir OS, **o que vier primeiro**. Uma mensagem por OS. Pausar não conta. |
| Energia do dia | No fim do ciclo solar. |
| Energia da semana | No sábado, no fim do ciclo solar; cobre de domingo a sábado. |
| Energia do mês | No fim do ciclo solar do último dia do mês. |
| Energia — regra comum | Só sai com o **"ok" do meuWatt** de que o dia fechou. |
| Dia com lacuna de dados | **Não envia.** A semana e o mês que incluírem esse dia também não saem. |
| Banco | Mesmo Supabase do BFF. O gateway roda em **modo transação (porta 6543)**; o Alembic migra em modo sessão (5432). |
| IA (frente 2) | O GS orquestra com **DeepSeek** e delega às IAs do MP e do MW **com o PAT do próprio cliente**. Não copia skills; lê as capacidades de cada motor para escolher. |

**Pooler.** 200 é o máximo de *clientes* do Supavisor; 15 é o *pool size*. Em modo sessão, cada
cliente segura uma conexão real, então o teto efetivo é 15. É esse limite que aparece como
`EMAXCONNSESSION` no CLAUDE.md §6 do GS. Em modo transação, a conexão volta ao pool a cada
transação. Fontes: Supabase "Supavisor FAQ" e discussion supabase#37571. Corrigir o CLAUDE.md §6 com isso.

**Decisões técnicas tomadas por mim (revisáveis):**
- **Push.** O push do app (`notificacao/usina_parada`) fica como está; a central nova controla só o WhatsApp.
- **Motor.** Mora no **BFF**, porque é lá que estão os PATs dos clientes, o escopo e o catálogo.
  O gateway só envia e recebe.

---

## Entrega 0 — Vazamento do PAT no assistente do meuPlano

Caminhos relativos a `C:\Dev\meuPlano\backend`.

**Defeito.** `app/api/v1/meuacesso/assistant.py:192-211` (`_resolve_requester`) só decodifica JWT.
Com PAT (`mp_pat_…`), a exceção é engolida e a função devolve `None, False, None, None, EQUIPE`.
Com auth desligada, o retorno ainda vira `is_admin=True`. O efeito, passo a passo:
- **Ferramentas:** a audiência EQUIPE libera as ~106 ferramentas, ~60 delas de ação.
- **Usinas:** com `user_id=None`, `tenancy.usinas_visiveis_para` devolve `None` (`tenancy.py:69-75`),
  o que vira `UsinaScope(all=True)`: todas as usinas.
- **Empresa:** `X-Empresa-Id` não é validado (`assistant.py:184-185`).
- **Porta de entrada:** o middleware (`app/services/meuacesso/auth.py:436-441`) aceita o PAT. Basta que o dono do
  token tenha `meuacesso.assistant.acessar`.

**Raio:**
- `POST /assistant/chat` (`:226`) e `/assistant/apply` (`:296`). O apply aceita `action`/`args` do corpo e só confere a audiência (`engine.py:423`).
- `GET /assistant/runs/{id}` (`:271-291`) não confere dono. `AssistantRun` (`models/meuacesso.py:1320-1338`) não guarda usuário e os ids são sequenciais.
- `app/services/meuacesso/ownership.py:15-24`: com PAT, a regra "só o criador apaga" é pulada. Isso vale para `DELETE` de OS (`service_orders.py:1473-1484`) e de tarefa (`tasks.py:1832-1836`).
- `POST /assistant/lessons` e `/feedback` (`assistant.py:303-333`) não checam usuário, e as lições entram no prompt de todos (`engine.py:73-91`).
- `middleware/observability.py:30-46`: chamada via PAT fica sem identidade no log.
- Modelo correto já existente: `api/v1/talk.py:199-210` e `auth.py:452-505`.

**Correção:**
1. `_resolve_requester` passa a usar `auth_svc.get_current_app_user`. Sem usuário, com auth ligada, responde 401. `X-Empresa-Id` é sempre validado.
2. Migration `assistant_runs.app_user_id` + `audiencia`. O requester é resolvido **antes** de criar o run (hoje o run é criado na linha 218 e o requester só na 226). `GET runs/{id}` devolve 404 para quem não é dono (admin passa); `/resumo` também resolve o requester.
3. `/apply` só executa proposta pendente gravada no servidor, como o `whatsapp_bot` já faz com `pending_action`.
4. `ownership.py` resolve o PAT e, sem usuário, bloqueia.
5. `lessons` e `feedback` exigem usuário; `lessons` só para admin do sistema.
6. `observability.py` identifica o usuário do PAT.
7. Gates: o existente `scripts/validate_ia_cliente.py` e um novo, `scripts/validate_assistente_pat.py`, cobrindo:
   - PAT de cliente → audiência CLIENTE e só as usinas dele;
   - run alheio → 404;
   - `/apply` sem proposta → recusado;
   - sem credencial → 401.

⚠ **Conferir no Railway se `MEUACESSO_AUTH_ENABLED=true`.** O padrão no código é "false" (`auth.py:47-48`); o CLAUDE.md do MP diz que está ON (linha ~602).

---

## Frente 1 — Central de notificações

### O alicerce que já existe no GS

**Funil de push de parada** (`bff/app/services/avisos.py`):
- `paradas_por_usuario` lê cada usina **uma vez**, com o PAT de alguém que a enxerga, e filtra pessoa a pessoa.
- O filtro combina permissão, escopo (`usinas_do_usuario`) e aparelho.
- A rota que dispara é `POST /api/v1/interno/avisos/paradas` (`bff/app/api/v1/avisos.py`): usa `AVISOS_TOKEN` com `hmac.compare_digest`, falha fechada e aceita `simular=true`.
- A trava contra repetição é `gs_avisos_enviados` (`bff/app/models/permissao.py:85-111`).
- **O motor novo generaliza esse desenho.**

**Catálogo em código** (`bff/app/services/permissoes.py`): permissão é presença de linha em `gs_user_permissions`. A tela de concessão fica em `painel/src/features/clientes/Detalhe.tsx`.

**Clientes HTTP:**
- `bff/app/clients/meuwatt.py`: `monitoramento_atual`, `geracao_diaria`, `geracao_periodo`.
- `bff/app/clients/meuplano.py`: `ordens_servico`, `ordem_servico`.
- PAT do cliente: `bff/app/services/vinculos.py::cliente_meuwatt/cliente_meuplano` (`gs_vinculos_produto.token_cifrado`, Fernet em `bff/app/core/cripto.py`).

**Regras que continuam valendo:**
- Toda rota nova de upstream entra no catálogo da sonda (`bff/app/services/sonda.py`, com teste em `bff/tests/test_sonda.py`).
- Rota nova precisa estar montada no `main.py` (`bff/tests/test_rotas_montadas.py`).

⚠ **Nenhum repositório chama `/interno/avisos/paradas`.** Ou existe agendador fora do código, ou o push de parada nunca disparou. Conferir no Railway.

### Modelo de dados (BFF)

| Tabela / coluna | Conteúdo |
|---|---|
| `gs_users.telefone` | E.164, anulável. Normalização em `bff/app/core/telefone.py`, com testes: com/sem 55, com/sem 9, fixo, máscara, lixo. |
| `gs_users.whatsapp_aceite_em`, `whatsapp_aceite_por` | Aceite por contrato, marcado pelo gestor. |
| `gs_notificacao_preferencias` | `user_id`, `tipo`, `plant_link_id`, UNIQUE nos três. A linha existe = a pessoa recebe. Só aceita usina do escopo (`gs_user_plant_access`); revogar o acesso à usina apaga as preferências. |
| `gs_notificacoes_enviadas` | `user_id`, `tipo`, `chave` (UNIQUE com `user_id`), `plant_link_id`, `wamid`, `status` (pendente/enviada/entregue/lida/falhou), `erro`, `enviada_em`. |
| `gs_notificacao_cursores` | `produto`, `leitor_user_id`, `ultimo_id`. É o cursor dos eventos de OS do MP. |

Catálogo (em código): `parada`, `os_iniciada`, `os_finalizada`, `energia_dia`, `energia_semana`, `energia_mes`.

### Motor (BFF), por tipo, a cada execução

1. **Pessoas elegíveis:** ativas, com telefone, com aceite e com preferência daquele tipo.
2. **Usinas-alvo:** a união das usinas marcadas. Cada usina é lida **uma vez**, com o PAT de uma pessoa que a enxerga.
3. **Gatilho por usina,** na fonte do produto (abaixo).
4. **Distribuição:** o evento da usina vai para cada pessoa que marcou aquela usina naquele tipo.
5. **Trava:** a `chave` é gravada **antes** do envio (INSERT com conflito = já foi); o resultado é atualizado depois.
6. **Envio:** template via gateway.

Falha de leitura gera silêncio, nunca "parou" (mesma regra do `avisos.py`). Cada rota interna aceita `simular=true`.

Rotas internas: `POST /api/v1/interno/notificacoes/{tipo}`, protegidas por `NOTIFICACOES_TOKEN`, no padrão de `avisos.py`.

| Tipo | Chave |
|---|---|
| parada | `parada:{usina}:{ids ordenados de equipamento@down_since}`. Só gera mensagem quando surge item novo no conjunto. |
| os_iniciada / os_finalizada | `mp:evento:{id do evento}` |
| energia_dia | `energia_dia:{usina}:{AAAA-MM-DD}` |
| energia_semana | `energia_semana:{usina}:{domingo AAAA-MM-DD}` |
| energia_mes | `energia_mes:{usina}:{AAAA-MM}` |

### Fonte: parada → `GET /plants/{slug}/monitoring/current` (MW, existe)

**O que a resposta traz:**
- Por inversor (`src/monitoring/schemas.py:31-73`): `id` (`slot-N`), `name`, `down`/`down_since`/`down_cause`, `ignored` e `meter_name` (trafo).
- `down` pode ser `true`, `false` ou `null`; `null` significa "não sei" (`schemas.py:59-65`).
- No nível da usina: `breakdown_signal{state, usable, covers_until, age_minutes}` (`schemas.py:231-258`).
- Cache de 55 s. O detector roda a cada 300 s (`settings.py:277`). O PAT de um `plant_owner` lê essa rota.

**Regra do GS:**
- Só avalia a usina com `breakdown_signal.usable = true`.
- Um item conta se `down is True`, não está `ignored` e `agora − down_since ≥ 15 min`.
- `down null` fica fora.
- **Diferença deliberada do `avisos.py::_parados`,** que também aceita `status == "fault"`: aqui só vale `down is True`, a régua material do detector.
- Usina sem comunicação não é parada. Não há campo próprio para isso, então não gera mensagem nesta fase. Relés ficam fora da v1.

**Achado lateral:** o 500 de `GET /plants/{slug}/breakdowns/range` (pendência no CLAUDE.md §8 do GS) tem causa aparente.
- `src/alerts/router.py:98` passa `start.isoformat()` como texto para `stopped_at::date BETWEEN :start AND :end` (`src/alerts/service.py:310`).
- O asyncpg recusa texto em DATE, e o próprio repositório documenta isso em `src/generation/pvsyst_service.py:114-116`.
- Correção: passar objetos `date`.

### Fonte: "ok" da energia → **modelo novo no MW** (`plant_day_closures`)

**O que existe hoje:**
- **"Dia fechado": não existe** (nenhuma flag, tabela ou rota).
- **Relatório diário do mw-core:** chega por `POST /ingestion/plants/{slug}/report` (`src/ingestion/router.py:102-115`). Não tem marca de "final".
- ⚠ **Armadilha:** `refresh_daily_report_loss` grava uma linha placeholder `'NO_REPORT'` antes de o relatório chegar (`src/breakdowns/loss_service.py:921-927`). Existir linha no dia não prova que o relatório chegou.
- **Janela solar:** `src/shared/solar_window.py:141-200` tenta, nesta ordem, a tabela `solar_windows`, depois o cálculo NOAA por latitude e longitude, depois o horário fixo de 5h a 21h. O fuso é America/Sao_Paulo (`src/shared/timezone.py:4`).
- **Lacuna de dados:** o detector registra `cause="no_data"` com `materiality="data_gap"`, só com sol e a partir de 30 min (`src/shadow_breakdowns/detector.py:530-565`).
- **Jobs:** são laços `asyncio.create_task` no `lifespan` (`src/main.py:723-763`), com o padrão `_stagger` (`mw-api/CLAUDE.md:91-97`).
- **Relatórios de fechamento** (`dashboard_reports`): são manuais e não servem de "ok".

| coluna | conteúdo |
|---|---|
| `plant_id`, `date` | PK |
| `status` | `aberto` · `fechado` · `fechado_com_lacuna` |
| `closed_at` | quando fechou |
| `solar_end_utc`, `solar_fonte` | o fim do ciclo usado no julgamento e de onde ele veio |
| `report_received_at` | a chegada **real** do relatório (não o placeholder) |
| `gap_minutes` | minutos de `data_gap` com sol |
| `generation_kwh` | total congelado no fechamento |

**Como fecha:**
- Um job a cada 15 min, com stagger, fecha a usina quando `solar_end_utc + margem < agora` **e** o relatório do dia chegou.
- Se houver lacuna, o status é `fechado_com_lacuna`.
- Rota nova: `GET /plants/{slug}/generation/closures?from=&to=`, legível por plant_owner via PAT.

**Uso no GS:**
- **energia_dia:** só com o dia `fechado`.
- **energia_semana:** quando o sábado fecha e os 7 dias estão `fechado`.
- **energia_mes:** quando o último dia fecha e todos os dias do mês estão `fechado`.
- **`fechado_com_lacuna`:** não envia nada.
- **Valor enviado:** o `generation_kwh` congelado, ou a soma dos dias fechados.

### Fonte: eventos de OS → **modelo novo no MP** (`service_order_eventos`)

Caminhos relativos a `C:\Dev\meuPlano\backend\app`; [SO] = `api/v1/meuacesso/service_orders.py`.

**Hoje:**
- A OS não tem `started_at`, `finished_at` nem `updated_at`. O enum de status está em `models/tasks.py:66-72`.
- **Iniciar** tem três caminhos:
  - START do cronômetro, `POST /{id}/time-logs` ([SO]:2099-2170), que grava `service_order_time_logs`;
  - `POST /{id}/start` ([SO]:1313-1323), que só troca o status e **não registra nada**;
  - play numa tarefa (`tasks.py:1989-2020`).
- **Finalizar** tem dois caminhos:
  - FINISH do cronômetro, uma vez por OS, que **não muda o status**;
  - `POST /{id}/close` ([SO]:1346-1389), que vai para FECHADA e grava `closed_at`. Esse campo é zerado pelo `/regress` e corrigível pelo gestor, então não serve de chave.
- A listagem ([SO]:671-721) não tem filtro de data nem paginação.
- `GET /{id}/time-logs` **grava** um PAUSE de sistema em `sanear_os` (`services/meuacesso/cronometro_tarefa.py:83-104`). Por isso não se faz polling OS a OS.
- Nada notifica ao iniciar ou finalizar. O `/close` já roda ganchos depois do commit ([SO]:1371-1387), e esse é o padrão a seguir.
- Com o PAT do cliente, a listagem já vem filtrada pelas usinas dele ([SO]:700-701).
- ⚠ **Sem `manutencao.ordens.ver_todas`, a lista vem vazia** ([SO]:686-699). Os papéis PROPRIETARIA têm essa permissão (`services/meuacesso/permissions.py:446-455`); o papel legado `cliente` não tem.

| coluna | conteúdo |
|---|---|
| `id` | serial = cursor |
| `os_id`, `plant_id` | índices |
| `tipo` | `os_iniciada` · `os_finalizada` |
| `at`, `by`, `origem` | `cronometro_start`, `start`, `play_tarefa`, `finish`, `close` |
| UNIQUE `(os_id, tipo)` | `ON CONFLICT DO NOTHING`: o primeiro vale, e isso também resolve a corrida de dois START |

**Como registrar e expor:**
- Helper `registrar_evento_os(db, so, tipo, origem, by)`, chamado depois do commit em `/start`, time-log START, `_ligar_os_junto`, time-log FINISH e `/close`.
- Rota `GET /api/v1/meuacesso/service-orders/eventos?desde={id}&limit=`, filtrada pelo `usina_scope`. Resposta: `[{id, os_id, plant_id, tipo, at, classification}]`.
- Todas as classificações contam como manutenção.
- O texto usa as traduções do BFF (`bff/app/api/v1/manutencao.py:320-329`, `SITUACAO`, e `CLASSIFICACAO` em `:745-751`).

**Achado lateral:** `bff/app/api/v1/painel_clientes.py:541` lê `titulo`/`numero`, campos que não existem em `ServiceOrderOut`, e o diagnóstico sai com `None`.

### Templates Meta (categoria utilidade)

**Rascunho.** Todas as variáveis vêm de dado da API. Variável de template não aceita quebra de linha, então listas vão separadas por vírgula.

| Template | Texto |
|---|---|
| `gs_parada` | "⚠️ {{1 usina}}: equipamento parado há mais de 15 minutos — {{2 lista: inversor (trafo)}}." |
| `gs_os_iniciada` | "🔧 {{1 usina}}: a ordem de serviço nº {{2}} ({{3 classificação}}) foi iniciada às {{4 hora}}." |
| `gs_os_finalizada` | "✅ {{1 usina}}: a ordem de serviço nº {{2}} ({{3 classificação}}) foi finalizada às {{4 hora}}." |
| `gs_energia_dia` | "☀️ {{1 usina}} gerou {{2 kWh}} kWh em {{3 data}}." |
| `gs_energia_semana` | "📊 {{1 usina}} gerou {{2 kWh}} kWh na semana de {{3}} a {{4}}." |
| `gs_energia_mes` | "📅 {{1 usina}} gerou {{2 kWh}} kWh em {{3 mês/ano}}." |

Os números saem formatados em pt-BR (`13.800,5`). A Meta cobra por mensagem entregue.

### Gateway (`Gestao Solar/whatsapp/`, pacote Python `gateway`)

O pacote **não** pode se chamar `app`: com o `PYTHONPATH` do BFF, dois pacotes `app` se atropelam (lição registrada no CLAUDE.md do GS).
- **Envio de template:** grava `pendente`, chama a Graph API e depois grava `wamid` + `enviada` ou `falhou`.
- **Webhook:**
  - GET faz a verificação com `WHATSAPP_VERIFY_TOKEN`;
  - POST valida o HMAC `X-Hub-Signature-256` sobre os **bytes crus**;
  - grava em `wa_webhook_eventos` e só então responde 200;
  - `BackgroundTasks` processa em seguida, e uma varredura na subida e periódica pega o que ficou pendente.
- **Status:** o status por `wamid` só avança (enviada < entregue < lida; `falhou` grava código e detalhe) e é repassado ao BFF, que atualiza `gs_notificacoes_enviadas`.
- **Mensagem recebida:** é gravada e fica para a frente 2. Nesta fase ninguém responde.
- **Produção:** o boot falha sem `META_APP_SECRET`. O MP aceita tudo sem o segredo (`api/v1/meuacesso/whatsapp.py:75-76`); não copiar.
- **Tabelas `wa_`:**
  - `wa_webhook_eventos` (id, recebido_em, corpo jsonb, processado_em, tentativas, erro);
  - `wa_mensagens` (id, wamid UNIQUE, direcao, wa_id, tipo, template, texto, ocorrida_em, status, status_em, erro_codigo, erro_detalhe, origem, criado_em).
- **API interna** (header `X-Chave-Interna`, `hmac.compare_digest`):
  - `POST /interno/templates` com `{telefone, template, idioma, parametros}`, que devolve `{id, wamid|erro}`;
  - `GET /interno/mensagens/{id}`.
- **Env:** `WHATSAPP_ACCESS_TOKEN`, `META_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `GRAPH_API_VERSION=v25.0`, `DATABASE_URL` (6543), `DATABASE_URL_MIGRACAO` (5432), `WHATSAPP_CHAVE_INTERNA`, `BFF_URL`.
  - Os nomes diferem dos do MP (`WHATSAPP_TOKEN` e outros) de propósito; registrar isso.
- **Deploy:** Dockerfile, `railway.json` com `/health` e serviço **ligado ao GitHub**. O portal `appgestao` não está ligado, e a lição é essa.

### Agendador

Hoje não existe nenhum no código. Proposta: um relógio único que chama as rotas internas do BFF a cada 5 min (parada e eventos de OS) e a cada 15 min (energia).
- ⚠ **Verificar na fase** se o cron do Railway atende a esse intervalo.
- **Não usar GitHub Actions cron:** atrasa e não serve para os 15 min da parada.

### Painel (admin do GS)

Na ficha do cliente (`painel/src/features/clientes/Detalhe.tsx`), com `gestor_atual`:
- telefone;
- aceite no contrato, com data;
- matriz **tipo × usinas dele** (lista suspensa pesquisável, nunca chips; todos os tipos começam desligados);
- histórico dos envios, com status.

**Peças a portar do portal:**
- `Esqueleto` de `portal/src/components/base.tsx:350`;
- `lib/format.ts` (`dataHora` e outros).

O painel não tem skeleton nem helpers de data.

---

## Fases (cada uma termina validada)

| # | Onde | Entrega | Validação |
|---|---|---|---|
| 0 | MP | Correção do PAT no assistente | gates `validate_ia_cliente.py` + `validate_assistente_pat.py`; probe em produção com PAT de cliente |
| 1 | Meta | Token permanente (System User), 6 templates submetidos, destinatários de teste | envio manual de template aprovado |
| 2 ✅ | GS `whatsapp/` | Gateway: envio de template, webhook, status | **feito em 16/09/2026** — ver abaixo |
| 3 | MW | `plant_day_closures` + job + `GET generation/closures`; correção do 500 de `breakdowns/range` | pytest no mw-api; conferir fechamento de uma usina real após o pôr do sol |
| 4 | MP | `service_order_eventos` + helper + `GET service-orders/eventos` | pytest: START, /start, play, FINISH e close geram no máximo 1 por tipo; escopo por PAT |
| 5 | GS `bff/` | Modelo, catálogo, telefone, motor, rotas internas com `simular`, clientes das rotas novas **no catálogo da sonda** | pytest: pessoa sem aceite, sem telefone ou sem preferência não recebe; usina fora do escopo nunca entra; `down null` e `usable=false` → silêncio; chave repetida → no-op; dia com lacuna → nada |
| 6 ✅ | GS `painel/` | Central na ficha do cliente | **feita e publicada em 16/09/2026**, conferida na tela |
| 7 | Railway | Relógio ligado com `simular=true` primeiro, depois real, com o número de teste | contagens de `simular`; mensagem real de cada tipo no celular de teste |
| 8 | Docs | CLAUDE.md do GS (pooler, central, pacote `gateway`), README com a tabela de deploy, ARQUITETURA; CLAUDE.md do MP (PAT, eventos) e do MW (closures) | leitura |

Ordem de deploy: MP (0) → ~~gateway~~ → MW e MP (3, 4) → BFF → painel → relógio. Troca para
o número real só depois da fase 7.

### O que a fase 2 entregou, e no que ela saiu do plano

No ar em `https://whatsapp-production-2201.up.railway.app` (serviço `whatsapp`, Root
Directory `whatsapp`). Provado por probe: `/health` responde
`{"status":"ok","ambiente":"production"}`, `/interno/credenciais` dá **401** sem a chave e
200 com ela, e o webhook responde **503 com a frase** enquanto não houver credencial. 51
testes no gateway, 11 no BFF, 965 na suíte do BFF.

**A diferença que vale registrar: as credenciais da Meta NÃO ficaram em variável de
ambiente.** O plano previa `WHATSAPP_ACCESS_TOKEN`, `META_APP_SECRET` e
`WHATSAPP_VERIFY_TOKEN` no Railway; elas passaram a ser cadastradas em **Painel → WhatsApp**
(só administrador) e vivem cifradas com Fernet no banco do gateway, pelo mesmo motivo que
tirou as pontes do meuWatt e do meuPlano do `.env`: quem configura é o gestor, e ele precisa
testar — digitar, ver se responde, corrigir. Com segredo em ambiente, cada tentativa custa
um redeploy. Gravar testa contra a Graph antes de persistir, e a credencial anterior
sobrevive à recusa.

Peças novas que o plano não tinha: `bff/app/clients/whatsapp.py`,
`/api/painel/whatsapp/*` (estado, gravar, testar, remover, histórico),
`/api/v1/interno/whatsapp/evento` (o gateway avisa que chegou mensagem; o BFF só registra
nesta fase) e a tela `painel/src/features/whatsapp/Whatsapp.tsx`.

**O que ficou pendente da fase 2:**

- **O serviço não sobe no push** — a API de projeto não cria o gatilho ("Bad Access"; exige
  token de conta). Publicar é `railway redeploy --service whatsapp … --from-source -y`.
  Ligar o repositório no dashboard apaga esta pendência.
- **Template real no celular** depende da fase 1: ainda não há token permanente nem template
  aprovado. O caminho de envio está pronto e testado contra a Graph simulada.

## Verificação ponta a ponta (fim da fase 7)

1. Cliente de teste com telefone cadastrado, aceite marcado e as 6 notificações ligadas para 1 usina.
2. `simular=true` em cada rota interna: a contagem de candidatos bate com o esperado.
3. **Parada:** usina com inversor `down` há 15 min ou mais → 1 mensagem. Outro inversor para → nova mensagem com os dois. Repetir a chamada → nada.
4. **OS:** técnico dá play no app → "iniciada"; o técnico pausa → nada; "Finalizar" → "finalizada"; depois "Fechar" → nada.
5. **Energia:** após o fechamento do dia no MW → 1 mensagem com o kWh congelado. Dia com lacuna → nada.
6. **Contraprova de escopo:** um segundo cliente sem acesso àquela usina não recebe nada.

## Frente 2 — IA (depois da frente 1; desenho, não fases)

**Fluxo:**
1. Chega mensagem de número cadastrado.
2. O orquestrador do GS (DeepSeek) lê as capacidades dos motores.
3. Delega a `POST /assistant/chat` (`{messages:[{role,content}]}`) do MP ou do MW, usando o **PAT do cliente**. Com a Entrega 0 feita, isso roda como audiência CLIENTE e só com as usinas dele.
4. Responde dentro da janela de 24 h.

**Pré-requisitos:**
- Entrega 0.
- `GET /assistant/capacidades` nos produtos, montado a partir de `registry.tool_defs(aud)` no MP.
- O motor do MW, que o dono vai criar seguindo o mesmo contrato. O `src/ai_analysis/deepseek_client.py::chat_json` já existe.
- Corrigir `bff/app/clients/meuplano.py:665-675`: ele manda `{message, usina_id}`, e o contrato real é `{messages}`, então a chamada daria 422.

**Regras:**
- **Número desconhecido:** não é atendido.
- **Proposta de ação vinda do motor:** não é executada.
- **Número na resposta:** o orquestrador não gera número próprio; todo número vem do motor (REGRA 0).
