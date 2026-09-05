# Arquitetura — Gestão Solar

> **Estado deste documento (04/09/2026).** As seções de **desenho**, **de onde vem cada
> informação** e **motor de PDF** descrevem o código de hoje. A de **autenticação** foi
> reescrita nesta data: o desenho que constava aqui — cada cliente conectando as contas
> dele, numa tabela `gs_conexoes` — **nunca foi construído**. O que existe é uma ponte por
> produto, configurada pelo gestor. O desenho antigo e o porquê da troca continuam em
> [DECISAO_IDENTIDADE.md](DECISAO_IDENTIDADE.md) §§ 1–2; o que foi feito está na § 2b.

## O problema que este app resolve

O proprietário de uma usina solar não tem para onde olhar. O **meuWatt** monitora geração,
mas é ferramenta de operador — ~50 telas densas, feitas para o time de O&M. O **meuPlano**
gerencia a manutenção e tem app de campo, feito para o técnico. Nenhum dos dois fala com o
cliente final.

O Gestão Solar é a camada fina por cima dos dois, mostrando ao dono só o que interessa a
ele: quanto gerou, se os equipamentos estão de pé, se a manutenção contratada está sendo
cumprida, os documentos em PDF, e se as mensalidades estão em dia.

## Desenho

```
  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
  │  app/  (Expo)    │  │ portal/  (web)   │  │ painel/  (web)   │
  │  dono da usina   │  │  dono da usina   │  │     o gestor     │
  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
           │                     │                     │
           └─────────────────────┼─────────────────────┘
                                 │  HTTPS · 1 token por pessoa
                  ┌──────────────▼──────────────┐
                  │  BFF Gestão Solar (FastAPI) │  autoriza, agrega, cacheia, gera PDF
                  │  + Postgres próprio         │  usuários, vínculo de usinas, assinaturas
                  │  + Chromium headless        │  roda o motor vetorial do mw-fe
                  └───────┬─────────────┬───────┘
                          │             │  token pessoal por produto, server-to-server
                  ┌───────▼──────┐ ┌────▼─────────┐        (ver DECISAO_IDENTIDADE § 2b)
                  │   mw-api     │ │  meuPlano    │
                  │  (meuWatt)   │ │   backend    │
                  └──────────────┘ └──────────────┘
```

**São três consumidores do mesmo BFF, não dois.** O app e o portal servem a mesma pessoa —
o dono da usina, no celular e no navegador — e usam a mesma conta e o mesmo login. O painel
serve o time interno e tem porta própria (`/api/painel/...`, sessão marcada com
`escopo: "painel"`, que o BFF recusa nas rotas de cliente).

**O `talksolar/` não aparece neste desenho de propósito.** É um produto à parte que mora no
mesmo repositório: servidor próprio, banco próprio (tabelas `ts_*`), sessão própria, e
nenhuma linha do `bff/` importada. Ele conversa com o meuPlano por HTTP como qualquer
sistema de fora, e não participa do caminho de dados do dono da usina. Documentação em
`talksolar/docs/`.

### Por que um BFF e não chamada direta às duas APIs

Sem ele, o cliente precisaria de dois logins e dois tokens, cruzar as usinas dos dois
sistemas no próprio aparelho, e o financeiro de mensalidades não teria onde morar (não
existe em nenhum dos dois). Com o BFF, o app tem um só endereço, um só token, e a regra de
"o que o dono pode ver" fica num lugar só.

CORS **é** problema — mas só para os dois fronts web. O app nativo não é browser e o BFF
fala com os upstreams server-to-server (nada a mudar no `CORS_ORIGINS` do mw-api); já o
painel e o portal chamam de outra origem, e por isso o BFF mantém `GS_CORS_ORIGENS` com a
lista explícita de quem pode. **Front que sobe sem a origem dele nessa lista abre em tela
branca**, com o erro só no console do navegador.

## Autenticação — uma ponte por produto, configurada pelo gestor

> Decisão detalhada em [DECISAO_IDENTIDADE.md](DECISAO_IDENTIDADE.md) § 2b. **Esta seção
> foi reescrita em 04/09/2026** para descrever o que o código faz. O desenho anterior —
> cada cliente conectando as contas dele pelo app, em `gs_conexoes` — não foi construído.

**A conta é do Gestão Solar, e quem entra é o apelido.** `gs_users.apelido` é único; o
e-mail é contato, opcional e não único, e serve para achar a conta da pessoa nos dois
produtos. O motivo está no `bff/app/core/apelido.py`: a mesma pessoa pode ter duas contas
aqui, com poderes diferentes (`renanmarquezini`, gestor; `renan.marquezini`, dono de
usina) — com o e-mail como chave, a segunda seria recusada como duplicada.

**A ponte com cada produto é uma só, e é do sistema, não do cliente.** Alguém gera um
**token pessoal** na própria conta do meuWatt e do meuPlano e cola em **Painel → Conexões**.
São duas linhas no banco, no máximo — `produto` é único:

```
gs_integracoes         produto (meuwatt|meuplano, ÚNICO), base_url, ativa,
                       token_cifrado, token_prefixo, token_dono_nome/_email,
                       estado + testada_em + detalhe_teste  ← o último teste
                       usuario_servico / senha_cifrada       ← caminho ANTIGO, ainda lido

gs_users               apelido (ÚNICO), email, nome, senha_hash, trocar_senha,
                       perfil: cliente | atendimento | administrador
                       nivel_acesso (espelho do meuPlano), ativo
gs_vinculos_produto    gs_user_id, produto, usuario_remoto_id/_email/_nome
gs_user_plant_access   user_id, plant_link_id       ← o escopo, dado pelo gestor
gs_senhas_provisorias  registro de que o acesso foi entregue — nunca a senha
```

Isso mora no banco, e não no `.env`, por um motivo prático: quem configura é o gestor, pela
tela, e ele precisa **testar** — digitar, ver se responde, corrigir. Segredo em variável de
ambiente exigiria um redeploy por tentativa.

**O token vale exatamente o que a conta de quem o gerou vale.** Se aquela pessoa não enxerga
uma usina no produto de origem, o Gestão Solar também não. É o teto de tudo o que o sistema
consegue ler.

**O recorte do cliente é outro, e é do gestor.** Dentro daquele teto, quem decide o que cada
cliente vê é `gs_user_plant_access`, concedida em Painel → Clientes. Duas camadas, nesta
ordem: o token limita o sistema; a concessão limita a pessoa. Nunca confie num `plant_id`
que veio do cliente sem checar contra o escopo dele.

Três coisas a respeitar:

- **O formato do token é acordo de três repositórios** (`bff/app/core/tokens_produto.py` e
  os dois produtos). Mudá-lo de um lado exige mudar dos outros; os testes ficam vermelhos
  se divergir, e é para isso que existem.
- **Verificar antes de gravar.** `integracoes.salvar_token` só persiste depois de o token
  passar por formato, identidade e alcance — senão o gestor ficaria com a conexão nova
  quebrada *e* a antiga perdida.
- **Desconectar não é revogar.** Remover o token aqui só faz o BFF parar de usá-lo; ele
  continua válido no produto de origem, e é lá que a porta se fecha.

O caminho **antigo** — conta de serviço com senha (`usuario_servico`/`senha_cifrada`) —
segue funcionando para o que já está gravado, mas a tela não oferece mais criar assim, e
conectar por token apaga a senha guardada.

### O que continua valendo do desenho antigo

O fluxo de autorização pelo navegador (o cliente conectando as contas dele, sem gestor no
meio) continua sendo o caminho certo para quando o **cliente** conectar sozinho — e a
máquina de tokens construída agora é a base dele. O meuPlano já tem a peça
(`app_login.py`, feito para o Analisador de Instrumentos); o meuWatt tem device flow sem
token renovável.

### Papéis que já existem e são reaproveitados

| Sistema | Como o dono aparece |
|---|---|
| meuWatt | role `plant_owner` no `AuthContext` |
| meuPlano | organização `Owner.kind = 'PROPRIETARIA'`, catálogo `_PROPRIETARIA_BASE` |

Não se inventa autorização do zero — o BFF confia nesses papéis e apenas os traduz.

## Vínculo entre as usinas dos dois sistemas

Os dois sistemas nunca se falaram. O `Usina.plant_code` do meuPlano existe "p/ reconciliação
futura" mas está vazio.

**Quem casa as usinas é o gestor, em Painel → Usinas** (`services/conciliacao.montar`). O
sistema não decide sozinho: ele mostra os dois inventários lado a lado, aponta o par
provável (`par_provavel_*`) e oferece o botão que confirma. O vínculo mora no BFF, em
`gs_plant_links`:

| coluna | conteúdo |
|---|---|
| `id` | identificador da usina no Gestão Solar |
| `mw_plant_slug` | slug no meuWatt (ex.: `porto-ferreira`) |
| `mp_usina_id` | `usinas.id` (int) no meuPlano |
| `ativo` | o interruptor do gestor: só usina ligada pode ser concedida a um cliente |
| `nome`, `cidade`, `uf`, `kwp` | denormalizado, para a lista carregar rápido |

Três regras que não devem ser "simplificadas":

- **Existir num produto ≠ estar no aplicativo.** `ativo` é do gestor. Desligar preserva
  vínculos e concessões; apagar é recusado enquanto houver cliente com aquela usina.
- **Usina não casada aparece duas vezes, uma em cada grupo.** O sistema não *sabe* que são
  a mesma; esconder uma delas seria decidir no lugar de quem decide.
- **Os três formatos aparecem:** nos dois produtos, só no meuWatt, e **só no meuPlano**. O
  terceiro é comum — manutenção contratada sem monitoramento — e a primeira versão da tela
  o omitia por percorrer só o meuWatt procurando par: onze das dezessete usinas reais eram
  invisíveis.

**Vínculo que aponta para upstream inexistente é fantasma:** a usina aparece na lista e
todas as telas dela vêm vazias. Ter só um dos dois lados é legítimo (o app esconde a aba
correspondente); ter nenhum, não.

## De onde vem cada informação

### meuWatt (mw-api) — geração e equipamentos

| Assunto | Endpoint upstream |
|---|---|
| Lista de usinas | `GET /plants` · `GET /plants/{slug}` |
| Diário | `GET /plants/{slug}/generation/daily?date=` |
| Mensal / Anual | `GET /plants/{slug}/generation/range?start=&end=` (máx. 366 dias) |
| Potência agora, estação, relés | `GET /plants/{slug}/monitoring/current` |
| Curvas intradiárias | `GET /plants/{slug}/charts/intraday/{strings,temperature}` · `/charts/hourly` |
| UCs (= transformadores) | `GET /plants/{slug}/utility-bills` + agregação do `range` |
| Paradas / tempo parado | `GET /plants/{slug}/alerts` · `GET /plants/{slug}/breakdowns/range` |
| Equipamento e histórico | `GET /plants/{slug}/slots` · `/slots/{slot_id}` (assignments) |
| Trip de relé de proteção | `GET /plants/{slug}/relays/{relay_id}/trip-events` |
| PR e perdas | `GET /plants/{slug}/losses?start=&end=` |
| Relatórios publicados | `GET /reports/portal` · `GET /reports/{id}/files/{kind}` |

> "UC" no meuWatt é o **transformador** — `src/utility_bills/router.py` é explícito sobre
> isso. Não existe endpoint `/equipment/{id}/history` genérico: o tempo parado por
> equipamento sai de `plant_breakdowns` (`stopped_at`, `resolved_at`, `off_time_minutes`),
> e o BFF monta a visão do equipamento cruzando `slots` + `breakdowns`.

### meuPlano — manutenção

| Assunto | Endpoint upstream |
|---|---|
| Cronograma anual | `GET /api/v1/maintenance/usinas/{id}/cronograma` |
| Cores de conformidade | do próprio cronograma (`asset_compliance.cell_statuses_from_assets`) |
| Cronograma → OS | `Task.contract_month` + `Task.cronograma_id` → `Task.os_id` |
| Lista de OS | `GET /api/v1/meuacesso/service-orders` |
| Detalhe da OS | `GET /api/v1/meuacesso/service-orders/{id}` (+ `/tasks`, `/feed`) |
| PDF da OS | `POST /service-orders/{id}/pdf` → `GET /pdf-basket/{id}/download` |
| PDF do cronograma | `GET /usinas/{id}/cronograma/pdf` · `GET /usinas/{id}/plan/pdf` |
| Assistente IA | `POST /api/v1/meuacesso/assistant/chat` → polling `GET /assistant/runs/{id}` |
| Notificações | `GET /api/v1/meuacesso/me/notifications` · `/unread-count` · `POST /me/push-token` |

> A conformidade do cronograma **não se mede contando OS**. O meuPlano calcula comparando o
> que o ativo deve receber (declarado no plano, com tolerância) com o que foi executado
> (histórico do próprio ativo). As cores das células já vêm prontas do upstream: verde
> (cumprido) · azul (no prazo) · laranja (venceu há ≤15 dias) · vermelho (vencido).

### BFF — financeiro (nasce aqui)

Não existe cobrança de mensalidade em nenhum dos dois sistemas. O `/api/v1/financeiro` do
meuPlano é contas a pagar interno; o `/api/v1/client/financeiro` cobra contrato de O&M, não
assinatura de produto. Modelo próprio:

- `gs_subscription` — `owner_id`, `produto` (`meuwatt` | `meuplano`), `valor_mensal`,
  `dia_vencimento`, `inicio`, `fim`, `ativo`.
- `gs_invoice` — `subscription_id`, `competencia` (YYYY-MM), `valor`, `vencimento`,
  `pago_em`, `comprovante_url`, `observacao`.

Situação derivada em tempo de leitura (`pago` · `vencido` · `a_vencer` · `em_aberto`), no
mesmo padrão de `meuPlano/backend/app/api/v1/client/financeiro_cliente.py::_situacao()`.

## Motor de PDF — três caminhos, nenhum reescrito

**1. OS, cronograma e planejamento** → proxy puro do meuPlano. Já é ReportLab server-side
(`os_pdf.py`, `plan_pdf.py`, `commissioning_pdf.py`, orquestrados por `pdf_basket.py` com
versionamento por fingerprint). Nada a fazer além de repassar bytes.

**2. Relatórios de fechamento já publicados** → proxy do meuWatt (`GET /reports/portal` +
`GET /reports/{id}/files/{kind}`). São os PDFs que já passam pelo fluxo de revisão →
liberação → envio.

**3. Dashboards sob demanda (diário, mensal, anual, UCs)** → `bff/app/services/pdf_render.py`:
o BFF sobe **Playwright + Chromium headless**, abre a rota de impressão do mw-fe autenticada
com a credencial de serviço, espera o relatório montar e chama `captureReportPdfVector(root)`
— o motor vetorial que já existe em `mw-fe/src/lib/pdf/` (13 módulos, validado por
`npm run pdf:validate` contra referências do Chrome).

Por que não reimplementar em ReportLab: o motor tem 8 verificações de regressão amarradas a
defeitos reais ("não tem capa", "faltam gráficos", "a letra está errada"). Refazer seria
jogar isso fora e criar duas versões do relatório que divergem. O custo é Chromium no
container (~400 MB) e alguns segundos por documento — o motor em si gasta 0,4 s; o resto é
a página montar.

No app, o PDF é sempre exibido pelo `PdfViewer` (pdf.js em WebView) com "Enviar cópia" via
share sheet nativo. Nunca entregar o arquivo a app externo direto — no Android isso dá tela
preta silenciosa.

## Assistente de IA e o nível L2

O app chama `POST /assistant/chat` do meuPlano. A audiência `CLIENTE` já é detectada sozinha
(`audiencia_do_usuario`) e já tem allowlist de ~20 ferramentas de leitura, incluindo
`consultar_acessos_equipamentos`.

Para o dono chegar a **L2** (senhas de equipamento, cadeados), é preciso alterar
`meuPlano/backend/app/services/meuacesso/assistant/tools_consulta.py`: o teto hoje é fixo em
`_TETO_NIVEL_CLIENTE = 1`. Trocar por `min(user.nivel_acesso, 2)` faz o L2 ser concedido
**por usuário**, no cadastro (`POST /owners/{id}/users`, campo `nivel_acesso`), em vez de
liberado para toda a categoria cliente de uma vez.

Toda revelação continua auditada em `AccessRevealLog`.

## Dependências fora deste repositório

| Onde | O quê | Estado |
|---|---|---|
| `mw-api` | Token pessoal para o BFF (`/auth/tokens`, migration 131) | **feito e no ar** (13/08/2026) |
| `meuPlano` | Token pessoal equivalente (migration `jt00pat11ok0`) | **feito e no ar** (13/08/2026) |
| `mw-fe` | Rota de impressão headless + `window.__gsCapturePdf()` | pendente — bloqueia o PDF sob demanda |
| `mw-api` | `GET /plants/{slug}/breakdowns/range` responde **500** em qualquer intervalo | pendente — bloqueia Paradas e o histórico do equipamento |
| `meuPlano` | `_TETO_NIVEL_CLIENTE` respeitar `nivel_acesso` (teto 2) | pendente — bloqueia L2 no assistente |
| `meuPlano` | Cadastrar os proprietários com `nivel_acesso = 2` | pendente — bloqueia L2 no assistente |

As duas linhas de "conta de serviço" que constavam aqui saíram: foram **substituídas pelo
token pessoal**, que está feito e testado contra produção (`api.meuwatt.com.br` e
`meuplano.up.railway.app`).

Nenhuma pendência bloqueia começar: o BFF sobe com dados de leitura e as telas de PDF sob
demanda entram depois.
