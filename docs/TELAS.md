# Telas — inventário e origem dos dados

Cada tela do app, a rota do expo-router que a implementa, o endpoint do BFF que a alimenta e
de onde o BFF tira o dado. O desenho de cada uma está em [PROMPT_DESIGNER.md](PROMPT_DESIGNER.md).

## Estrutura de rotas

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

## Tabela

| # | Tela | Rota | Endpoint do BFF | Origem |
|---|---|---|---|---|
| 1.2 | Login | `login` | `POST /api/v1/auth/login` | mw-api `/auth/login` + meuPlano `/meuacesso/auth/login` |
| 2.1 | Início | `(tabs)/index` | `GET /api/v1/home` | agrega `monitoring/current` de todas as usinas + cronograma + faturas |
| 2.2 | Notificações | `notificacoes` | `GET /api/v1/notifications` | meuPlano `/me/notifications` |
| 3.1 | Lista de usinas | `(tabs)/usinas` | `GET /api/v1/plants` | mw-api `/plants` ∩ `gs_plant_link` |
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

## Notas de implementação

**Gráficos** — o mw-fe usa Recharts, que não existe em React Native. Decidir na Fase 2 entre
`victory-native` e `react-native-svg` direto. A especificação visual dos gráficos está no
prompt do designer; a biblioteca é escolha de implementação.

**Cache** — toda tela de leitura passa por `fetchWithCache` (`app/src/lib/offline.ts`).
Usina tem sinal ruim; a tela mostra o cache imediatamente e atualiza quando a rede responde.

**PDF** — sempre pelo `PdfViewer` (pdf.js em WebView). Nunca entregar o arquivo a um app
externo direto: no Android isso dá tela preta silenciosa.
