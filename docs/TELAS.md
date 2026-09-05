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
(tabs)/relatorios.tsx            3. Relatórios — acervo (lista + filtros)
documentos.tsx                     ponte permanente → /relatorios
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
  `cronograma/[usinaId]`, `pendencias/index`, `relatorio/[id]` e `tarefa/[id]`.
  `documento/[id]` continua existindo, mas só como ponte (redireciona, preservando os
  parâmetros, para `relatorio/[id]`).
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
| 4.1 | Relatórios — acervo | `(tabs)/relatorios` | `GET /api/v1/documents` (ETag/304) | mw-api `reports/portal`, recortado por `mw_plant_slug` |
| 4.2 | Relatórios — o ano, mês a mês | `relatorios/ano` | `GET /api/v1/relatorios/ano?ano=` | composição no BFF: `documents` × `manutencao/cronograma` |
| 4.3 | Leitor de PDF | `relatorio/[id]` | `GET /api/v1/documents/{id}/file?tipo=` | proxy de bytes |
| — | ~~Gerar relatório~~ | — | — | **não existe**: não há fila, job nem endpoint de progresso — a folha com "etapa 2 de 3" era animação encenando trabalho que ninguém fazia |
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

**Relatórios (4.x) — o que mudou de nome, e o que NÃO mudou.** A aba "Documentos" virou
**Relatórios**: "documento" é o que o portal chama de anexo de pendência
(`manutencao/pendencias/{cid}/documentos/{did}`), e a aba nunca teve anexo nenhum.
Quatro coisas para quem for mexer:

- **Rota é arquivo.** `(tabs)/documentos.tsx` → `(tabs)/relatorios.tsx`, com o `name=` do
  `<Tabs.Screen>` no MESMO commit: `name` que não casa com arquivo faz a aba sumir da barra
  e as outras quatro se embaralharem, porque a ordem é a da lista do layout. Ficam duas
  **pontes permanentes** (`documentos.tsx` e `documento/[id].tsx`, esta preservando os
  parâmetros): nada no repositório gera esses endereços — não há listener de push,
  conferido —, mas o esquema `gestaosolar` os torna válidos por construção, e o expo-router
  não redireciona sozinho.
- **A chave de cache continua `'documents'`.** Ela é o caminho do BFF sem `/api/v1/` e vira
  nome de arquivo em disco (`u2__documents.json`); trocá-la para acompanhar o rótulo órfã o
  cache de todo celular já instalado, na tela de quem está no campo.
- **O mês sai da competência, nunca da publicação.** Medido em 05/09/2026: os fechamentos
  35 e 36 cobrem agosto e foram publicados em 05/09 — a lista vem ordenada por
  `publicado_em`, e agrupar pelo mesmo campo poria agosto na gaveta de setembro. A régua é
  do servidor (`DocumentoOut.competencia`, derivada de `de`); no cliente o corte é fatia de
  string, porque `new Date('2026-08-01')` é meia-noite UTC e responde julho no Brasil.
- **Filtro é no cliente**, sobre o array já baixado: funciona offline, e um filtro no
  servidor criaria um arquivo de cache por combinação, com a primeira escolha sempre fria.
  As opções saem dos PRÓPRIOS relatórios (medido: 7 usinas na conta, 5 com fechamento), e o
  período é contado dentro da usina escolhida — senão duas escolhas válidas sozinhas
  ("Porto Ferreira" + "maio") produziriam uma tela vazia sem explicação.

E a ausência tem **três** caras, com três textos: nada publicado · a ponte caída (aqui o
título não pode afirmar "nenhum relatório publicado" — com o monitoramento fora do ar não
se sabe) · fechamento sem peça, que hoje é o caso de quatro dos seis fechamentos e nem
passa pelo estado vazio, porque a lista não está vazia.

**PDF** — sempre pelo `PdfViewer` (pdf.js em WebView). Nunca entregar o arquivo a um app
externo direto: no Android isso dá tela preta silenciosa.

**Baixar dados (P.10) — exceção de paridade DECLARADA.** A tela de exportação existe no
portal e **não** no app, e o motivo é medido, não preguiça.

A rota da mw-api é **síncrona**: o `POST` devolve o `FileResponse` depois de gerar o
arquivo inteiro — não há job, id nem endpoint de andamento. Medido contra produção, o
cabeçalho chega em **34,3 s** no pior pedido permitido. No celular isso não é uma espera
longa, é uma promessa que o app não cumpre: bloquear a tela **suspende o `fetch`**, e a
rede é móvel. Um download que só existe em primeiro plano e morre quando a tela apaga é a
mesma classe de problema que fez o `pdf.ts` abandonar o `downloadFileAsync`. E oferecer a
tela sabendo disso seria pior do que não tê-la: o cliente sai do app com um arquivo pela
metade e a impressão de que o produto perdeu o dado.

Fazer o trabalho virar job **no BFF** também não: seria remontar em vez de repassar — o
erro que [`pacotes.py`](../bff/app/api/v1/pacotes.py) recusou por escrito, e o BFF passaria
a guardar arquivo de outro sistema.

> **Gatilho para revisitar** — quando a mw-api tiver `POST /exports/raw/start` +
> `GET /exports/raw/{id}`, o app ganha a tela no desenho de **três atos** do
> `PacoteDeFichas` (inventariar · preparar · baixar), que é o único que sobrevive a sair da
> tela: o preparo corre no servidor, o app pergunta como está quando volta, e o download é
> um GET curto de um arquivo que já existe. Até lá, quem precisa da planilha no celular
> abre o portal no navegador — o login é o mesmo.

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
| P.10 | Baixar dados | `/usinas/:id/energia/dados` | `energia/dados/opcoes?usina_id=` · `POST energia/dados/arquivo?usina_id=` | mw-api `plants/{slug}/exports/raw*` |

Rota desconhecida cai em `/` (`<Navigate to="/" replace />`).

### P.10 — Baixar dados: por que mora na Geração, e não em Relatórios

Quarta entrada da família **Geração de energia** (`fim: '/energia/dados'`, rótulo com um
**verbo** porque as três irmãs são leituras — "Painel", "Paradas", "Comparar" — e o verbo
já avisa que dali se sai com um arquivo).

**Não fica em Relatórios**, embora seja lá que muita gente vá procurar. Relatórios é a
única entrada de família `geral` justamente porque guarda as duas famílias, e o contrato de
exportação do meuWatt não tem uma linha de manutenção: inversores, estação, fronteira, PR.
Pôr algo mono-família dentro do único lugar que promete as duas desfaria, na prática, a
separação que o `menu.ts` defende em prosa. E as naturezas são opostas: Relatórios guarda
PDFs **publicados pela equipe**; aqui nada foi publicado — o cliente é quem monta. Juntas,
"nenhum fechamento publicado" e "sem dados brutos" pareceriam o mesmo problema.

Também não é entrada de carteira: a rota do meuWatt existe **por usina**
(`/plants/{slug}/exports/raw`), e um item solto no rodapé prometeria uma exportação da
carteira inteira que não existe.

Como procurar em Relatórios é o instinto certo, fica de lá uma **ponte declarada** (uma
`LinhaNavegacao` no pé da aba Energia) em vez de uma segunda tela: **diz onde mora**, que é
a regra da casa aplicada à navegação.

O formulário do meuWatt não é copiado. São **três perguntas com resposta já preenchida** —
o quê (pacotes nomeados por finalidade, não variáveis), de quando a quando (a MESMA peça do
Painel e de Paradas), com que detalhe (o teto viajando junto de cada opção) — mais uma
gaveta **Avançado** para quem quer escolher coluna por coluna. As chaves de série
(`slot:12`, `inv:7`) nunca aparecem: são transporte. **Zero chip**, aqui inclusive contra o
exemplo do meuWatt, que usa chips: toda escolha é `Combobox` pesquisável ou `Segmentado`.

Os três limites têm três naturezas e três tratamentos, e isso está no
[`CONTRATO_API.md`](CONTRATO_API.md#baixar-dados--a-planilha-da-usina): teto de dias por
passo **impede antes** (é aritmética nossa e certa, e a frase faz a conta e nomeia a
saída); retenção **pertence ao seletor de período** (não é limite do arquivo, é ausência de
dado — e a saída é o passo de 1 dia, que não tem prazo); orçamento de células é
**estimativa**, então deixa pedir — no limiar o benefício da dúvida é do cliente.

**Prova:** `bff/scripts/conferir_exportacao.py` sobe o BFF local, pede pelo caminho do
portal e **abre o XLSX**. Medido em 05/09/2026 (Porto Ferreira, agosto a 15 min): abas
`['Leia-me', 'Inversores']`, 2.977 linhas (2.976 instantes + cabeçalho), 22 colunas,
184.220 bytes, 11,5 s; e 92 dias a 5 min recusado em 2,4 s com
`motivo: passo_excede_limite`.

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
