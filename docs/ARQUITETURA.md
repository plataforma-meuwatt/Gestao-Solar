# Arquitetura — Gestão Solar

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
   ┌─────────────────────────────┐
   │  App Gestão Solar (Expo)    │   1 base de código, iOS + Android
   └──────────────┬──────────────┘
                  │  HTTPS, 1 token só
   ┌──────────────▼──────────────┐
   │  BFF Gestão Solar (FastAPI) │   autoriza, agrega, cacheia, gera PDF
   │  + Postgres próprio         │   usuários, vínculo de usinas, assinaturas
   │  + Chromium headless        │   roda o motor vetorial do mw-fe
   └───────┬─────────────┬───────┘
           │             │  credencial de serviço, server-to-server
   ┌───────▼──────┐ ┌────▼─────────┐
   │   mw-api     │ │  meuPlano    │
   │  (meuWatt)   │ │   backend    │
   └──────────────┘ └──────────────┘
```

### Por que um BFF e não chamada direta às duas APIs

Sem ele, o app precisaria de dois logins e dois tokens, cruzar as usinas dos dois sistemas
no cliente, e o financeiro de mensalidades não teria onde morar (não existe em nenhum dos
dois). Com o BFF, o app tem um só endereço, um só token, e a regra de "o que o dono pode
ver" fica num lugar só.

CORS não é problema: app nativo não é browser, e o BFF fala com os upstreams
server-to-server. Nada a mudar no `CORS_ORIGINS` do mw-api.

## Autenticação

**Login** (`POST /api/v1/auth/login`): recebe e-mail + senha e tenta autenticar nos dois
upstreams — `POST /auth/login` do mw-api e `POST /api/v1/meuacesso/auth/login` do meuPlano.
Basta um aceitar. O que aceitou define a identidade; se os dois aceitarem, os dois vínculos
são gravados no `gs_user`.

**A senha só autentica.** Para as chamadas de dados, o BFF usa **credenciais de serviço**
(uma conta técnica em cada sistema) e aplica a autorização por conta própria. O JWT do
usuário expira (24 h no mw-api) e guardar senha de usuário para renovar seria inaceitável.

**O escopo é capturado no login**, enquanto o BFF ainda tem o token do usuário: chama
`GET /plants` (mw-api) e o escopo de usinas do meuPlano, e grava em `gs_user_plant_access`.
Revalidação a cada login e a cada 24 h. Se o dono perder acesso a uma usina lá, perde aqui
no próximo ciclo.

### Papéis que já existem e são reaproveitados

| Sistema | Como o dono aparece |
|---|---|
| meuWatt | role `plant_owner` no `AuthContext` |
| meuPlano | organização `Owner.kind = 'PROPRIETARIA'`, catálogo `_PROPRIETARIA_BASE` |

Não se inventa autorização do zero — o BFF confia nesses papéis e apenas os traduz.

## Vínculo entre as usinas dos dois sistemas

Os dois sistemas nunca se falaram. O `Usina.plant_code` do meuPlano existe "p/ reconciliação
futura" mas está vazio. O vínculo mora no BFF, em `gs_plant_link`:

| coluna | conteúdo |
|---|---|
| `id` | identificador da usina no Gestão Solar |
| `mw_plant_slug` | slug no meuWatt (ex.: `porto-ferreira`) |
| `mp_usina_id` | `usinas.id` (int) no meuPlano |
| `nome`, `cidade`, `uf`, `kwp` | denormalizado, para a lista carregar rápido |

Preenchido por seed ou tela de admin. Uma usina pode existir só de um lado — o app esconde
a aba correspondente.

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

| Onde | O quê | Bloqueia |
|---|---|---|
| `mw-fe` | Rota de impressão headless + `window.__gsCapturePdf()` | PDF sob demanda |
| `mw-api` | Conta de serviço para o BFF | Tudo do meuWatt |
| `meuPlano` | Conta de serviço equivalente | Tudo do meuPlano |
| `meuPlano` | `_TETO_NIVEL_CLIENTE` respeitar `nivel_acesso` (teto 2) | L2 no assistente |
| `meuPlano` | Cadastrar os proprietários com `nivel_acesso = 2` | L2 no assistente |

Nenhuma bloqueia começar: o BFF sobe com dados de leitura e as telas de PDF sob demanda
entram depois.
