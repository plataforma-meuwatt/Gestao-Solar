# Telas — inventário e origem dos dados

Cada tela, a rota que a implementa, o endpoint do BFF que a alimenta e de onde o BFF tira o
dado. O desenho está em [PROMPT_DESIGNER.md](PROMPT_DESIGNER.md).

São **três frentes**, para três públicos:

| Frente | Pasta | Quem usa | Onde |
|---|---|---|---|
| Aplicativo | `app/` | o dono da usina, no celular | [§ 1](#1-aplicativo-app) |
| Portal | `portal/` | o dono da usina, no navegador | [§ 2](#2-portal-portal) |
| Painel | `painel/` | o gestor (time interno) | [§ 3](#3-painel-painel) |

O `talksolar/` **não entra nesta contagem**: é produto à parte, com telas e servidor
próprios. A [§ 4](#4-talk-solar-talksolar) diz o mínimo para ninguém procurá-lo aqui.

---

## 1. Aplicativo (`app/`)

### Estrutura de rotas

```
_layout.tsx                      Stack raiz + hosts globais + indicador de rede
login.tsx                        Login
(tabs)/_layout.tsx               Tab bar de 5 abas
(tabs)/index.tsx                 1. Início
(tabs)/usinas.tsx                2. Usinas — lista
(tabs)/documentos.tsx            3. Documentos
(tabs)/financeiro.tsx            4. Financeiro
(tabs)/assistente.tsx            5. Assistente
usina/[id]/_layout.tsx           Abas internas da usina
usina/[id]/index.tsx               Visão geral
usina/[id]/geracao.tsx             Geração (segmentado: Diário/Mensal/Anual/UCs)
usina/[id]/mapa.tsx                Mapa da planta
usina/[id]/equipamentos.tsx        Lista de equipamentos
usina/[id]/manutencao.tsx          Cronograma + OS
equipamento/[id].tsx             Detalhe do equipamento
paradas/[usinaId].tsx            Histórico de paradas
os/[id].tsx                      Detalhe da OS
fatura/[id].tsx                  Detalhe da mensalidade
notificacoes.tsx                 Notificações
perfil.tsx  config.tsx           Avatar do topo
pdf.tsx                          Visualizador de PDF
```

### Tabela

⚠ **Esta seção está atrás do código, e o mapeamento abaixo é o alvo, não o inventário.**
Conferido em 04/09/2026, sem reauditar tela a tela:

- **A árvore de rotas acima não bate mais.** Não existem `(tabs)/financeiro`,
  `usina/[id]/geracao`, `usina/[id]/mapa`, `usina/[id]/manutencao`, `paradas/[usinaId]`,
  `pdf.tsx` nem `config.tsx`; existem, e não estão listadas, `(tabs)/manutencao`,
  `cronograma/[usinaId]`, `documento/[id]` e `tarefa/[id]`.
- **Mas o app não é mais "quase todo maquete".** Os módulos de `app/src/features/` leem do
  BFF de verdade, por `fetchWithCache` (`app/src/lib/cache.ts` — o `lib/offline.ts` que
  esta página citava não existe):
  `home`, `plants`, `plants/{id}`, `billing`, `documents`, `notifications`, `manutencao`,
  `manutencao/cronograma-{id}`, `manutencao/ordem-{id}`, `me/permissoes`.

Reescrever esta seção contra as rotas reais é trabalho declarado e ainda não feito —
preferimos a lacuna anotada a uma tabela que parece conferida e não foi.

| # | Tela | Rota | Endpoint do BFF | Origem |
|---|---|---|---|---|
| 1.2 | Login | `login` | `POST /api/v1/auth/login` | mw-api `/auth/login` + meuPlano `/meuacesso/auth/login` |
| 2.1 | Início | `(tabs)/index` | `GET /api/v1/home` | agrega `monitoring/current` de todas as usinas + cronograma + faturas |
| 2.2 | Notificações | `notificacoes` | `GET /api/v1/notifications` | meuPlano `/me/notifications` |
| 3.1 | Lista de usinas | `(tabs)/usinas` | `GET /api/v1/plants` | mw-api `/plants` ∩ `gs_plant_links` |
| 3.2 | Usina — geral | `usina/[id]/index` | `GET /api/v1/plants/{id}/overview` | `monitoring/current` + `generation/daily` + cronograma |
| 3.3 | Geração diária | `usina/[id]/geracao` | `GET /api/v1/plants/{id}/generation/daily?date=` | mw-api `generation/daily` |
| 3.4 | Geração mensal | idem | `GET /api/v1/plants/{id}/generation/range?start=&end=` | mw-api `generation/range` |
| 3.5 | Geração anual | idem | idem, range de 12 meses | mw-api `generation/range` |
| 3.6 | UCs | idem | `GET /api/v1/plants/{id}/ucs?start=&end=` | `generation/range` + `utility-bills` |
| 3.7 | Mapa da planta | `usina/[id]/mapa` | `GET /api/v1/plants/{id}/map` | `monitoring/current` + `slots` |
| 3.8 | Equipamentos | `usina/[id]/equipamentos` | `GET /api/v1/plants/{id}/equipment` | `slots` + `monitoring/current` |
| 3.9 | Inversor | `equipamento/[id]` | `GET /api/v1/equipment/{id}` | `slots/{id}` + `breakdowns/range` + `charts/intraday` |
| 3.10 | Estação solarimétrica | `equipamento/[id]` | idem | `monitoring/current` + `charts/intraday/temperature` |
| 3.11 | Relé de proteção | `equipamento/[id]` | idem | `relays/{id}/trip-events` |
| 3.12 | Relé de temperatura | `equipamento/[id]` | idem | `monitoring/current` |
| 3.13 | Histórico de paradas | `paradas/[usinaId]` | `GET /api/v1/plants/{id}/breakdowns?start=&end=` | mw-api `breakdowns/range` |
| 3.14 | Cronograma | `usina/[id]/manutencao` | `GET /api/v1/plants/{id}/schedule` | meuPlano `usinas/{id}/cronograma` |
| 3.15 | Item do cronograma | sheet | `GET /api/v1/plants/{id}/schedule/{itemId}` | `Task` por `contract_month` + `cronograma_id` |
| 3.16 | Lista de OS | `usina/[id]/manutencao` | `GET /api/v1/plants/{id}/service-orders` | meuPlano `service-orders` |
| 3.17 | OS — detalhe | `os/[id]` | `GET /api/v1/service-orders/{id}` | meuPlano `service-orders/{id}` |
| 4.1 | Documentos | `(tabs)/documentos` | `GET /api/v1/documents` | `reports/portal` + cesta de PDFs do meuPlano |
| 4.2 | Gerar relatório | sheet | `POST /api/v1/documents/generate` | Playwright + `captureReportPdfVector` |
| 4.3 | Visualizador de PDF | `pdf` | `GET /api/v1/documents/{id}/file` | proxy de bytes |
| 5.1 | Financeiro | `(tabs)/financeiro` | `GET /api/v1/billing` | `gs_subscription` + `gs_invoice` (BFF) |
| 5.2 | Fatura | `fatura/[id]` | `GET /api/v1/billing/invoices/{id}` | `gs_invoice` |
| 6.1 | Assistente | `(tabs)/assistente` | `POST /api/v1/assistant/chat` → `GET /api/v1/assistant/runs/{id}` | meuPlano `/assistant/*` |
| 7.1 | Perfil | `perfil` | `GET /api/v1/me` | `gs_user` |

### Notas de implementação

**Gráficos** — o mw-fe usa Recharts, que não existe em React Native. Decidir na Fase 2 entre
`victory-native` e `react-native-svg` direto. A especificação visual dos gráficos está no
prompt do designer; a biblioteca é escolha de implementação.

**Cache** — toda tela de leitura passa por `fetchWithCache` (`app/src/lib/cache.ts`).
Usina tem sinal ruim; a tela mostra o cache imediatamente e atualiza quando a rede responde.

**PDF** — sempre pelo `PdfViewer` (pdf.js em WebView). Nunca entregar o arquivo a um app
externo direto: no Android isso dá tela preta silenciosa.

---

## 2. Portal (`portal/`)

O mesmo dono de usina do aplicativo, no navegador — **mesma conta e mesmo login**
(`POST /api/v1/auth/login`, com `apelido` e `senha`). O BFF recusa a sessão de painel nestas
rotas, porque ela carrega `escopo: "painel"`; e a sessão fica sob a chave
`gs_portal_sessao` no `localStorage`, separada da `gs_painel_sessao`, para as duas
conviverem no mesmo navegador.

**A chave da leitura é o caminho no BFF sem `/api/v1/`** — a mesma string serve de nome no
cache (`useLeitura`, em `portal/src/lib/leitura.ts`). É por isso que a coluna do meio abaixo
aparece ora com o prefixo, ora sem.

| # | Tela | Rota | Chave / endpoint | Origem |
|---|---|---|---|---|
| P.0 | Entrar | `/entrar` | `POST /api/v1/auth/login` · `/auth/eu` · `/auth/renovar` | `gs_users` |
| P.1 | Visão geral | `/` | `resumo?referencia=&blocos=energia` · `…&blocos=manutencao` · `plants` | agrega os dois upstreams |
| P.2 | Usina | `/usinas/:id` | `plants/{id}` · `plants/{id}/geracao` · `plants/{id}/curva?dia=` · `plants/{id}/historico?meses=` | mw-api `generation/*` e `charts/*` |
| P.3 | Paradas | `/usinas/:id/paradas` | `plants/{id}/paradas?recorte=` | mw-api `breakdowns/range` |
| P.4 | Cronograma | `/usinas/:id/cronograma` | `manutencao/contratos` · `manutencao/cronograma` · tarefas do mês · `…/cronograma/pdf` | meuPlano `usinas/{id}/cronograma` |
| P.5 | Ordens | `/usinas/:id/ordens` | `manutencao/ordens?usina_id=` | meuPlano `service-orders` |
| P.6 | Ordem | `/usinas/:id/ordens/:osId` | `manutencao/ordem-{id}` · `…/pdf` · `…/tarefas/{id}/pdf` | meuPlano `service-orders/{id}` |
| P.7 | Pendências | `/usinas/:id/pendencias[/:cid]` | `manutencao/pendencias?usina_id=` · `manutencao/pendencias/{cid}` | meuPlano `pipelines` |
| P.8 | Relatórios | `/usinas/:id/relatorios` | `manutencao/relatorio` · `…/relatorio/pdf` · `documents` · `documents/{id}/file` | meuPlano + mw-api `reports/portal` |
| P.9 | Conta | `/conta` | `GET /api/v1/auth/eu` · `POST /api/v1/auth/trocar-senha` | `gs_users` |

Rota desconhecida cai em `/` (`<Navigate to="/" replace />`).

### O que o portal tem e o painel não

- **`npm run check` dentro do `build`** — `tsc --noEmit && node scripts/regra0.mjs`. O
  `regra0.mjs` varre `src/**/*.{ts,tsx}` e reprova, com arquivo e linha, `?? 0` / `|| 0`,
  `Math.random`, `MOCK_`/`fixture`, `window.confirm|alert|prompt` e `.toFixed(`. A saída é
  um comentário `// regra0: <motivo>` na linha. **Como não há CI, este é o único gate
  automático do repositório** — e ele roda dentro do `docker build`.
- **Healthcheck que não mente** — `/saude` no nginx, em vez de `/` (ver o
  [`README.md`](../README.md#deploy)).

---

## 3. Painel (`painel/`)

O time interno. Porta própria no BFF (`/api/painel/...`) e sessão marcada com
`escopo: "painel"`, curta, que o BFF **recusa** nas rotas de cliente.

O caminho de um cliente novo passa por cinco destas telas, nesta ordem — está descrito no
[`README.md`](../README.md#o-caminho-de-um-cliente-novo): **Conexões** (colar os dois tokens
pessoais) → **Rotas** (*Sondar*: exercita uma a uma as rotas de upstream do catálogo de
`bff/app/services/sonda.py`) → **Usinas** (conciliar meuWatt × meuPlano) → **Clientes**
(cadastrar, vincular as contas, conceder usinas, entregar o apelido com a senha provisória)
→ **Diagnóstico** (conferir o que aquele cliente verá antes de ele abrir o app).

> Inventário tela a tela do painel: **ainda não escrito**. Preferimos a lacuna declarada a
> uma tabela adivinhada — quem for preenchê-la tem a lista de páginas em `painel/src/`.

---

## 4. Talk Solar (`talksolar/`)

**Não é do Gestão Solar** — é o mensageiro da equipe, produto à parte que mora neste
repositório desde 04/09/2026. Não usa o BFF, não usa o banco do Gestão Solar e não responde
à REGRA 0 (lá o dado é a mensagem que alguém digitou).

- **Cliente:** app de PC (Electron), duas telas — entrar e conversar
  (`talksolar/desktop/app/index.html`).
- **Servidor:** 23 rotas sob `/v1`, mais `/saude`, num serviço próprio com banco próprio
  (tabelas `ts_*`).
- **Contrato e telas:** `talksolar/docs/` (`API.md`, `INTEGRACAO.md`, `ENTREGA.md`).
