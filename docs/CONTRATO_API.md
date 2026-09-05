# Contrato da API do BFF

Base: `/api/v1`. Todo endpoint exige `Authorization: Bearer <jwt do Gestão Solar>`, exceto
`/auth/login` e `/health`.

Formato de erro: `{"detail": "mensagem em português"}` — o app exibe `detail` direto.

---

## Autenticação

### `POST /auth/login`

```json
{ "apelido": "renan.marquezini", "senha": "..." }
```

Entra-se pelo **apelido**, não pelo e-mail — a conta é do Gestão Solar, criada pelo gestor
no painel, e não a mesma do meuWatt ou do meuPlano. O porquê está em
[`DECISAO_IDENTIDADE.md`](DECISAO_IDENTIDADE.md) e em `bff/app/core/apelido.py`.

```json
{
  "token": "eyJ...",
  "expira_em": "2026-09-12T14:30:00Z",
  "usuario": {
    "id": 12,
    "nome": "Renan Marquezini",
    "apelido": "renan.marquezini",
    "email": "renan@splendoroem.com.br",
    "empresa": "Solar Ltda",
    "tem_meuwatt": true,
    "tem_meuplano": true,
    "nivel_acesso": 2,
    "usinas": 3,
    "trocar_senha": false
  }
}
```

`401` — com a mesma frase para conta inexistente, senha errada e conta desativada: quem
tenta adivinhar não aprende qual das três aconteceu.

`tem_meuwatt` / `tem_meuplano` decidem quais abas o app mostra; `usinas` distingue "ainda
não concederam nenhuma" de "erro ao carregar", que na tela seriam a mesma lista vazia.

### `GET /auth/eu`

O mesmo objeto `usuario`, atualizado. O app chama ao abrir: o token dura 30 dias e, nesse
intervalo, o gestor pode ter concedido uma usina ou vinculado um produto.

### `POST /auth/trocar-senha`

```json
{ "senha_atual": "...", "senha_nova": "..." }
```

`204`. Fecha o ciclo da senha provisória. Exige a senha atual mesmo com a sessão
autenticada — um celular desbloqueado esquecido na mesa não deve bastar para trocar a
senha e trancar o dono para fora.

---

## Início

### `GET /home`

Tudo que a tela inicial precisa, numa chamada só.

```json
{
  "potencia_agora_kw": 4820.5,
  "capacidade_total_kwp": 6200.0,
  "energia_hoje_mwh": 28.4,
  "atencao": [
    { "severidade": "parado", "texto": "2 inversores parados em Porto Ferreira",
      "usina_id": 3, "equipamento_id": "slot-14" }
  ],
  "meuwatt": {
    "geracao_mes_mwh": 612.3, "meta_mes_mwh": 680.0, "pr_pct": 81.4
  },
  "meuplano": {
    "servicos_mes_concluidos": 3, "servicos_mes_total": 4,
    "meses": ["verde","verde","azul","laranja",null,null,null,null,null,null,null,null]
  },
  "financeiro": { "situacao": "em_dia", "proximo_vencimento": "2026-09-05" },
  "notificacoes": [ { "id": 88, "titulo": "...", "resumo": "...", "quando": "2026-08-11T09:12:00Z", "lida": false } ]
}
```

---

## Usinas

### `GET /plants`  — *no ar*

```json
{
  "usinas": [
    { "id": 3, "nome": "Porto Ferreira", "cidade": "Porto Ferreira", "uf": "SP",
      "capacidade_kwp": 2400.0,
      "potencia_kw": 1980.0, "energia_hoje_kwh": 12800.0,
      "disponibilidade_pct": 98.2, "pct_capacidade": 82,
      "tom": "ok", "situacao": "Gerando",
      "tem_meuwatt": true, "tem_meuplano": true, "aviso": null }
  ],
  "total_kwp": 2400.0,
  "potencia_agora_kw": 1980.0,
  "energia_hoje_kwh": 12800.0,
  "atualizado_em": "2026-08-13T14:32:00Z",
  "aviso": null
}
```

Envelope, e não lista crua: os totais são somados no servidor sobre as usinas que
responderam, e `atualizado_em` é o que a tela carimba no selo de horário do modo offline.

`tom` é sempre uma **chave de `tons`** em `app/src/theme/tokens.ts` — `parado` · `alerta` ·
`multiplos` · `tempoRuim` · `ok` · `semDados`, em camelCase. A tela faz `tons[tom]`; nome
que não existe lá não pinta cor errada, não pinta cor nenhuma. `situacao` é a frase que
acompanha a cor, já em português.

Nulo é "não sabemos", e a tela mostra travessão: `potencia_kw: null` é usina sem
comunicação, que é diferente de `0` (não gerou — de noite, o esperado). Vale para os
totais também.

`aviso` explica o que faltou, por usina e no topo. Uma ponte fora do ar não derruba a
resposta: vem o que deu para buscar, com o motivo escrito.

### `GET /plants/{id}`  — *no ar*

Mesma usina do envelope acima, mais o que veio do meuPlano:

```json
{ "id": 3, "nome": "Porto Ferreira", "tom": "ok", "situacao": "Gerando",
  "ordens_abertas": 2, "ordens_recentes": ["Limpeza trimestral", "Troca de string box"] }
```

`ordens_abertas: null` é "não foi possível consultar", não "nenhuma ordem".

Usina fora do escopo do usuário responde **404**, nunca 403 — responder "proibido"
confirmaria que aquela usina existe.

### `GET /plants/{id}/overview`

KPIs do dia, curva de potência + irradiância, resumo de equipamentos, situação da
manutenção e clima. Alimenta a aba "Geral" da usina.

### `GET /plants/{id}/generation/daily?date=YYYY-MM-DD`

Espelha `DailyGenerationReport` do mw-api, reduzido ao que a tela usa: KPIs, curva,
lista por UC, eventos do dia.

### `GET /plants/{id}/generation/range?start=&end=`

Mensal e anual usam o mesmo endpoint, mudando só o intervalo. Máximo de 366 dias (limite
do upstream).

### `GET /plants/{id}/ucs?start=&end=`

Ranking por UC (= transformador), série diária e conta de energia quando houver.

### `GET /plants/{id}/map`

Árvore esquemática para a tela de Mapa da Planta:

```json
{
  "resumo": { "potencia_agora_kw": 1980.0, "energia_hoje_mwh": 12.8,
              "pr_pct": 81.4, "equipamentos_ok": 18, "equipamentos_total": 20 },
  "protecao_geral": { "id": "relay-1", "nome": "Relé Geral", "status": "ok" },
  "transformadores": [
    { "id": "trafo-1", "nome": "Skid 1", "kva": 1500,
      "inversores": [
        { "id": "slot-1", "nome": "INV 01", "potencia_kw": 118.4, "status": "ok" }
      ] }
  ],
  "estacoes": [ { "id": "ws-1", "nome": "Solarimétrica", "irradiancia_wm2": 812.0,
                  "temp_modulo_c": 48.2, "status": "ok" } ],
  "reles_temperatura": []
}
```

### `GET /plants/{id}/equipment`

Lista agrupada por tipo, com leitura principal e status de cada item.

### `GET /equipment/{id}`

Detalhe do equipamento. O formato varia por tipo (`tipo`: `inversor` |
`estacao_solarimetrica` | `rele_protecao` | `rele_temperatura` | `transformador`), sempre
com `kpis[]`, `status`, `serie_dia[]` e, para inversor, `paradas[]` com início, fim,
duração em minutos, causa e perda estimada.

### `GET /plants/{id}/breakdowns?start=&end=`

Histórico de paradas, agrupado por dia.

---

## Manutenção

A aba responde três perguntas do dono, nesta ordem: **está sendo feita?** (a OS de agora),
**o que foi feito?** (as tarefas dentro dela) e **o contrato está sendo cumprido?** (o
cronograma). Tudo vem do meuPlano; o BFF autoriza, traduz o status e não recalcula nada.

### `GET /manutencao` — *no ar*

Histórico: só as OS já encerradas, de todas as usinas da pessoa, mais recentes primeiro.
"Atendida" é `closed_at` preenchido, não status textual.

### `GET /manutencao/ordens?usina_id=&limite=` — *no ar*

Todas as OS, abertas e encerradas. `usina_id` é o `id` do vínculo **neste** sistema, não o
do meuPlano; omitido, vale todas as usinas concedidas.

```json
{
  "total": 6,
  "em_andamento": {
    "id": 1016, "usina": "Porto Ferreira", "usina_id": 4, "contrato_numero": 665,
    "objetivo": "Manunteção preventiva do mês de agosto.",
    "classificacao": "Preventiva",
    "classificacao_codigo": "PREVENTIVA",
    "classificacao_tom": "ok",
    "status": "EM_EXECUCAO",
    "situacao": "Executada · aguardando verificação",
    "tom": "tempoRuim",
    "tecnico": "Paulo Renan Nunes Marquezini",
    "tarefas": 17, "tarefas_feitas": 17,
    "agendada_para": "2026-08-21", "concluida_em": null,
    "fechada_em": null, "aprovada_em": null,
    "execucao_min": 480, "resumo": null, "itens": null
  },
  "ordens": ["…as 6, a mesma forma…"],
  "usinas_com_manutencao": 6,
  "aviso": null
}
```

**A OS se identifica pelo `id`** — ela não tem número próprio no meuPlano. `contrato_numero`
é o número do CONTRATO que a rege, e chamava-se `numero`: com esse nome, o drawer da
pendência imprimia "OS #665" (o contrato) enquanto a lista chamava a mesma ordem de
"OS 1016", e toda OS daquele contrato virava "OS #665". `classificacao` é o rótulo PRONTO
("Serviços adicionais"), com o código cru ao lado em `classificacao_codigo` — a tela de
Ordens traduzia por conta própria e a de Relatórios imprimia "SERVICOS_ADICIONAIS" com
underscore, para a MESMA ordem.

`status` é o código cru do meuPlano (`ServiceOrderStatus`), preservado para auditoria.
`situacao` é a frase que a tela mostra, e **não** é tradução palavra a palavra:

| status | situacao | tom |
|---|---|---|
| `ABERTA` | Em preparação | `semDados` |
| `PROGRAMADA` | Agendada | `tempoRuim` |
| `EM_EXECUCAO` | Em execução | `alerta` |
| `FECHADA` | Em verificação | `tempoRuim` |
| `APROVADA` | Concluída | `ok` |
| `CANCELADA` | Cancelada | `semDados` |

Duas razões para traduzir em vez de repassar. `FECHADA` não quer dizer "encerrada" para
quem é dono — quer dizer que o técnico concluiu e o gestor ainda não conferiu; a própria UI
do meuPlano a rotula "Em verificação". E o status sozinho engana no caso mais comum: a OS
1016 está `EM_EXECUCAO` com as **17 tarefas executadas**, então "Em execução" faria o dono
entender que o técnico ainda está na usina. Quando todas as tarefas estão cumpridas e a OS
não foi encerrada, `situacao` passa a ser **"Executada · aguardando verificação"** — número
do próprio meuPlano (`task_count` × `task_realized_count`), não estimativa. Só vale com
`tarefas > 0`: OS de zero tarefa cairia em `0 == 0` e sairia "executada" sem nada feito.

`tom` é sempre chave de `tons` em `app/src/theme/tokens.ts`, como em `GET /plants`.

`em_andamento` é a OS não encerrada mais recente, já escolhida pelo servidor — sem ela a
tela teria de reproduzir a regra de "qual é a atual", e a regra passaria a existir em dois
lugares. `null` quando não há nenhuma em curso.

`itens` é sempre `null` aqui: a lista não busca tarefas, seriam N+1 chamadas ao upstream
para uma tela que mostra a contagem.

### `GET /manutencao/ordens/{id}` — *no ar*

A mesma forma de `OrdemOut`, com `itens` preenchido: as tarefas agrupadas por seção.

```json
{
  "id": 1016, "usina": "Porto Ferreira", "usina_id": 4,
  "situacao": "Executada · aguardando verificação", "tom": "tempoRuim",
  "tarefas": 17, "tarefas_feitas": 17,
  "itens": [
    { "id": 8841, "nome": "Inspeção externa de transformador - Todos",
      "grupo": "Transformador",
      "equipamento": "Skid 04 > Trafo Skid 4 > Transformador a seco",
      "status": "REALIZADA", "situacao": "Executada", "feita": true,
      "natureza": "INSPECAO", "parecer": "Aprovado com ressalva",
      "mes_contratual": "2026-08", "executada_em": "2026-08-21" }
  ]
}
```

`feita` é `status ∈ {REALIZADA, APROVADA}` — verificada é mais que executada, não menos.
`parecer` só aparece quando existe ficha respondida (`SessionVerdict`): tarefa de serviço
não tem parecer, e forjar um seria inventar. `itens: null` no detalhe significa "não deu
para buscar as tarefas" — diferente de `[]`, que afirmaria que a OS não tem nenhuma; a OS
abre de qualquer forma, porque o cabeçalho já responde a pergunta principal.

O `id` chega do cliente, então a OS é buscada e o `plant_id` dela conferido contra as
usinas concedidas. Fora do escopo responde **404, não 403**: "proibido" confirmaria que a
OS existe a quem só trocou um dígito na URL.

### `GET /manutencao/ordens/{id}/pdf` — *no ar*

`application/pdf`, `Content-Disposition: inline`. Dois passos no upstream: `POST .../pdf`
põe na cesta (reaproveitando a versão quando nada mudou, por fingerprint) e
`GET /pdf-basket/{item}/download` traz os bytes. `inline` porque o destino é o `PdfViewer`
embutido — entregar a um app externo dá tela preta silenciosa no Android.

### `GET /manutencao/cronograma?usina_id=` — *no ar*

A matriz do contrato. **12 meses a partir da âncora do contrato**, não do ano civil.

```json
{
  "usina": "Porto Ferreira", "usina_id": 4,
  "status": "CONSOLIDATED", "versao": 1,
  "meses": ["2026-08","2026-09","2026-10","2026-11","2026-12","2027-01",
            "2027-02","2027-03","2027-04","2027-05","2027-06","2027-07"],
  "linhas": [
    { "nome": "Limpeza e alinhamento dos sensores",
      "categoria": "Serviço", "categoria_codigo": "servico",
      "periodicidade": "Mensal", "grupo": "Estação solarimétrica",
      "previsto_ano": 12, "feitos": 1,
      "meses": [
        { "mes": "2026-08", "previsto": 1, "estado": "verde",
          "feito": true, "dispensado": false, "atrasado": false }
      ] }
  ],
  "previsto_ano": 148, "feitos_ano": 1, "pdf_disponivel": true, "aviso": null
}
```

`categoria` e `periodicidade` saem **traduzidas**: o meuPlano manda `INSPECAO`/`ensaio`
(duas caixas) e `6/MONTH`, e isso chegava à tela de um cliente corporativo brasileiro. Os
códigos crus ficam em `categoria_codigo` e nos campos de origem, para auditoria.

`grupo` diz sob que bloco a tela recolhe a linha. O cronograma real tem 94 linhas de ensaio
("Medição do TTR", "Isolação CC", "Curva IV") — a análise de equipamento que o dono disse que
o cliente não quer ver. Agrupadas e recolhidas, o que fica à mostra é a resposta que ele quer.

`pdf_disponivel` diz se a rota irmã do PDF tem o que gerar. Sem versão consolidada este JSON
responde 200 com matriz vazia e a frase, mas o PDF responde 404 — um arquivo não tem como
avisar por dentro. O campo é o que impede a tela de oferecer um botão que só sabe errar.

`estado` é o `cell_status` do meuPlano, **repassado como vem**: `verde` · `azul` ·
`laranja` · `vermelho` · `verde_ressalva` · `null`. Aquela cor é conformidade calculada
contra o histórico do **ativo**, não contra tarefas — é regra máxima do meuPlano
(`asset_compliance.cell_statuses_from_assets`). Recalcular aqui produziria uma segunda
resposta para a mesma pergunta, e o dono veria números diferentes nos dois produtos sem
saber em qual acreditar.

Os três booleanos existem para a tela não ter de conhecer os nomes das cores. E `feito` é
só `verde`: `verde_ressalva` é **dispensa** — decisão registrada com motivo —, e apagar a
diferença entre FEITO e DISPENSADO era exatamente o risco que o meuPlano recusou correr.
Já `feitos` da linha conta os dois: o dispensado saiu da conta daquele mês por decisão, e
cobrá-lo como pendência seria errado. Quem precisa da diferença a tem por célula.

`status: "DRAFT"` vem com `aviso` — rascunho de negociação não é o combinado com o cliente.

### `GET /manutencao/cronograma/pdf?usina_id=` — *no ar*

O cronograma anual em PDF, com a letra do estado em cada célula (`D` para dispensado).

---

## Documentos

### `GET /documents?tipo=&plant_id=`

`tipo`: `relatorio` | `os` | `cronograma`.

```json
[
  { "id": "mw-report-1841", "tipo": "relatorio", "titulo": "Relatório de Geração",
    "periodo": "Julho 2026", "emitido_em": "2026-08-03", "tamanho_bytes": 2841022,
    "plant_id": 3 }
]
```

### `POST /documents/generate`

```json
{ "tipo": "mensal", "plant_id": 3, "competencia": "2026-07" }
```

Dispara o Chromium headless. Responde `202` com `{"job_id": "..."}`;
`GET /documents/jobs/{job_id}` devolve `{"estado": "processando|pronto|erro", "documento_id": "..."}`.

### `GET /documents/{id}/file`

Bytes do PDF, `Content-Type: application/pdf`.

---

## Financeiro

### `GET /billing`

```json
{
  "situacao": "em_dia",
  "assinaturas": [
    { "id": 1, "produto": "meuwatt", "valor_mensal": 1200.00, "dia_vencimento": 5,
      "competencia_atual": { "id": 55, "competencia": "2026-08", "situacao": "a_vencer",
                             "vencimento": "2026-09-05", "valor": 1200.00 } }
  ],
  "historico": [
    { "id": 54, "produto": "meuwatt", "competencia": "2026-07", "valor": 1200.00,
      "vencimento": "2026-08-05", "pago_em": "2026-08-04", "situacao": "pago" }
  ]
}
```

`situacao` da fatura: `pago` · `a_vencer` · `em_aberto` · `vencido`.

### `GET /billing/invoices/{id}`

Detalhe, com `comprovante_url` quando houver.

---

## Assistente

### `POST /assistant/chat`

```json
{ "mensagem": "Quando foi a última manutenção do inversor 3?", "plant_id": 3 }
```

Responde `{"run_id": "..."}`. A execução é assíncrona no meuPlano.

### `GET /assistant/runs/{run_id}`

```json
{ "estado": "processando|pronto|erro",
  "etapa": "consultando as usinas…",
  "resposta": "...",
  "credenciais": [ { "nome": "Portal CPFL", "usuario": "solar@...", "acesso_id": 92 } ] }
```

Credencial nunca vem com o valor. Revelar exige chamada explícita.

### `POST /assistant/reveal`

```json
{ "acesso_id": 92 }
```

Devolve o valor e registra em `AccessRevealLog` no meuPlano. `403` se o nível do usuário
não alcança o nível do acesso.

---

## Notificações

### `GET /notifications?grupo=&nao_lidas=`

### `GET /notifications/unread-count`

### `POST /notifications/{id}/read` · `POST /notifications/read-all`

### `POST /me/push-token`

```json
{ "token": "ExponentPushToken[...]" }
```

---

## Conexões, vistas de dentro do aplicativo

### `GET /conexoes`  — *no ar*

Não confundir com `/api/painel/integracoes`: aqui não há token, endereço nem nome de quem
o gerou. Isso é assunto do gestor. Esta rota responde à pergunta que o **dono da usina**
faz quando uma aba aparece vazia — "está quebrado ou eu não contratei isso?" —, porque as
duas situações se parecem na tela e só uma delas justifica ligar reclamando.

```json
{
  "plataformas": [
    { "produto": "meuwatt", "nome": "meuWatt",
      "fornece": "Geração, inversores e disponibilidade",
      "tom": "ok", "situacao": "Conectado", "detalhe": null,
      "minhas_usinas": 4, "verificado_em": "2026-08-13T12:50:00Z" }
  ],
  "todas_ok": true,
  "resumo": "Tudo certo. 4 usina(s) recebendo dados."
}
```

`minhas_usinas` conta as usinas **desta pessoa** que vêm de cada plataforma — o total que a
credencial enxerga é número do painel. Quando a ponte falha, `detalhe` diz que a equipe já
enxerga a falha; a frase técnica do upstream fica no painel, não aqui.

---

## Painel do gestor — conexões

> Base **`/api/painel`**, não `/api/v1`: é o time interno, com sessão própria e curta
> (`gs_painel_sessao_horas`). Tudo aqui exige perfil de administrador.

A ponte com cada produto se estabelece por **token pessoal**: alguém gera um token na
própria conta do meuWatt/meuPlano e cola no painel. Formato e motivos em
[`DECISAO_IDENTIDADE.md`](DECISAO_IDENTIDADE.md) § 2b.

### `GET /integracoes`

Uma linha por produto, configurada ou não.

```json
[
  { "produto": "meuwatt", "configurada": true, "base_url": "https://api.meuwatt.com.br",
    "estado": "ok", "detalhe": "Conectado como Fulano da Silva. 12 usina(s) visíveis.",
    "testada_em": "2026-08-13T12:50:00Z", "usinas_visiveis": 12,
    "por_token": true, "token_prefixo": "mw_pat_kOdt",
    "token_dono_nome": "Fulano da Silva", "token_dono_email": "fulano@meuwatt.com.br",
    "token_gravado_em": "2026-08-13T12:49:00Z", "usuario_servico": null }
]
```

`estado`: `nunca` · `ok` · `falhou`. `por_token: false` = conexão antiga, ainda por conta de
serviço com senha — a tela mostra o aviso de migração em cima dela.

### `PUT /integracoes/{produto}/token`

```json
{ "base_url": "https://api.meuwatt.com.br", "token": "mw_pat_…" }
```

Valida o formato (local), identifica o dono e conta as usinas — **só grava se as três
passarem**. Responde com o resultado do teste, não com a integração: o que interessa neste
instante é se funcionou e como quem.

```json
{ "ok": true, "detalhe": "Conectado como Fulano da Silva. 12 usina(s) visíveis.",
  "usinas_visiveis": 12, "dono_nome": "Fulano da Silva",
  "dono_email": "fulano@meuwatt.com.br" }
```

Quando `ok: false`, **nada foi gravado** e a conexão anterior continua de pé. O `detalhe`
distingue os casos, porque cada um pede uma correção diferente: token do produto errado,
cópia truncada, token revogado ou expirado (a frase vem do próprio produto), endereço
errado, servidor fora, e "aceito mas não enxerga usina nenhuma".

### `POST /integracoes/{produto}/testar`

Mesmo corpo de resposta. Exercita a credencial gravada.

### `DELETE /integracoes/{produto}/token`

Para de usar o token deste lado e devolve a integração limpa. **Não revoga** nada no
produto de origem — só quem emitiu pode, e é lá que a porta se fecha de verdade.

### `GET /integracoes/{produto}/eventos`

Histórico da ponte, mais recente primeiro. Responde "desde quando parou?", que o estado
atual sozinho não responde.

```json
[ { "evento": "teste_falhou", "ocorrido_em": "2026-08-13T13:02:00Z",
    "ator_email": "admin@gestaosolar.local", "token_prefixo": "mw_pat_kOdt",
    "detalhe": "Token revogado. Emita um novo no meuWatt.", "usinas_visiveis": null } ]
```

`evento`: `token_gravado` · `token_removido` · `teste_ok` · `teste_falhou` ·
`senha_gravada` · `sonda_ok` · `sonda_falhou`. O valor do token nunca aparece — só o
prefixo.

---

## Painel do gestor — inventário de usinas

Duas decisões independentes moram aqui: **qual usina é qual** (casar meuWatt com meuPlano)
e **quais entram no aplicativo**.

Uma usina pode existir nos dois produtos, só no meuWatt ou **só no meuPlano** — manutenção
sem monitoramento é um caso normal de negócio. A versão anterior destas rotas percorria
apenas o meuWatt procurando par, e por isso omitia inteiramente o terceiro caso.

### `GET /conciliacao`

```json
{
  "meuwatt": [ { "id": "porto-ferreira", "nome": "Porto Ferreira", "cidade": "…", "uf": "SP", "kwp": 1200 } ],
  "meuplano": [ { "id": "19", "nome": "UFV PORTO FERREIRA", "cidade": "…", "uf": "SP", "kwp": 1200 } ],
  "linhas": [
    { "chave": "link:3", "nome": "Porto Ferreira", "plant_link_id": 3,
      "mw_slug": "porto-ferreira", "mw_nome": "Porto Ferreira",
      "mp_usina_id": 19, "mp_nome": "UFV PORTO FERREIRA",
      "cidade": "Porto Ferreira", "uf": "SP", "kwp": 1200,
      "origem": "ambos", "no_app": true, "candidatos": [],
      "par_provavel_mw": null, "par_provavel_nome": null, "par_provavel_motivos": [] }
  ],
  "aviso": null
}
```

`plant_link_id` **nulo** = a usina existe num produto e ainda não foi trazida para cá. É o
estado inicial de tudo, e é o que distingue "não está no app" de "não existe".

`origem` é `ambos` · `meuwatt` · `meuplano`. `candidatos` sugere o par do meuPlano para
uma linha do meuWatt; `par_provavel_*` faz o caminho inverso, para uma linha do meuPlano.

Uma usina que existe nos dois produtos e **ainda não foi casada** aparece em **duas
linhas**, uma em cada grupo. É deliberado: o sistema não sabe que são a mesma, e esconder
uma delas seria decidir no lugar do gestor. O `par_provavel_*` é o que evita que ele tenha
de cruzar os dois grupos a olho. Ao casar, as duas viram uma.

### `PUT /conciliacao/usina`

```json
{ "plant_link_id": null, "mw_slug": null, "mp_usina_id": 20,
  "nome": "Bady Bassit 2", "cidade": null, "uf": null, "kwp": null, "no_app": true }
```

Casar, descasar e ligar/desligar no aplicativo são a **mesma** operação: gravar o estado
desejado daquela usina. Rotas separadas obrigariam a tela a encadear duas chamadas para
"trazer a usina do meuPlano para o app", com a segunda podendo falhar sozinha.

`400` se os dois identificadores vierem nulos — seria uma usina que não existe em lugar
nenhum. `409` se o identificador já pertencer a outra linha, com o nome de quem o tem:
dois vínculos apontando para a mesma usina de um produto misturariam dados de duas plantas.

Desligar (`no_app: false`) preserva vínculos e concessões — o gestor religa sem refazer nada.

### `DELETE /conciliacao/usina/{plant_link_id}`

`204`. Tira a usina do Gestão Solar de vez. `409` enquanto algum cliente a tiver
concedida, com os nomes: apagar levaria o acesso dele junto por cascata, e o sintoma seria
uma usina sumindo do app sem ninguém ter mexido naquele cliente.

---

## Painel do gestor — sonda de rotas

O teste da conexão responde *"o token vale?"*. A sonda responde outra pergunta: **quais das
rotas de que dependemos ainda respondem, e com que forma?** Um token válido convive com
uma rota que mudou de lugar num deploy do produto de origem, e o sintoma disso é uma aba
vazia no aplicativo de um cliente, semanas depois.

O catálogo vive em `bff/app/services/sonda.py`. Toda chamada nova em `bff/app/clients/`
deve entrar nele — há um teste que compara os dois.

### `GET /integracoes/{produto}/rotas`

O catálogo, sem chamar nada. Abre instantâneo e vale mesmo com a ponte fora do ar. Exige
sessão de painel.

### `POST /integracoes/{produto}/rotas/sondar`

Exercita o catálogo inteiro com o token gravado. **Só administrador**: é uma dúzia de
requisições ao produto de terceiro usando a credencial de serviço, não uma tela de consulta.

```json
{
  "produto": "meuwatt",
  "base_url": "https://api.meuwatt.com.br",
  "ok": true,
  "detalhe": "As 12 rotas exercitadas responderam.",
  "executada_em": "2026-08-13T20:45:00Z",
  "rotas": [
    { "chave": "mw.slots", "metodo": "GET",
      "caminho": "/plants/porto-ferreira/slots",
      "alimenta": "Inversores da tela de Equipamentos",
      "essencial": true, "situacao": "ok", "status": 200, "ms": 180,
      "detalhe": null, "itens": 4,
      "campos": ["id", "position", "serial", "status"] }
  ]
}
```

`situacao` tem quatro valores, e a diferença entre eles é o ponto da tela:

| | o que significa | o que fazer |
|---|---|---|
| `ok` | respondeu | nada |
| `falhou` | respondeu erro, ou não respondeu | investigar; `detalhe` traz a frase do produto |
| `pulada` | não foi chamada — faltou um parâmetro que a rota anterior devia ter dado | olhar a rota anterior, não esta |
| `nao_sondada` | decisão nossa de não chamar (efeito colateral), com o motivo | nada |

`ok` no nível da varredura ignora falhas em rotas `essencial: false` — recurso a menos não
é ponte quebrada. `campos` traz a forma da resposta, nunca o conteúdo: é por ali que uma
mudança de formato aparece antes de virar tela quebrada no celular do cliente.

---

## Os tokens, do lado de cada produto

Rotas dos produtos, não do BFF. Documentadas aqui porque é o painel que manda o gestor
até elas.

| | meuWatt | meuPlano |
|---|---|---|
| Emitir | `POST /auth/tokens` | `POST /api/v1/meuacesso/auth/tokens` |
| Listar | `GET /auth/tokens` | `GET /api/v1/meuacesso/auth/tokens` |
| Revogar | `DELETE /auth/tokens/{id}` | `DELETE /api/v1/meuacesso/auth/tokens/{id}` |
| Corpo da emissão | `{"name": "...", "expires_in_days": 365}` | `{"nome": "...", "validade_dias": 365}` |

`expires_in_days` / `validade_dias` nulo = sem prazo, que é o certo para integração de
servidor. A emissão devolve o valor em claro **uma única vez**; listar nunca o devolve.
Emitir e revogar exigem sessão — um token não gerencia tokens.
