# CLAUDE.md — Gestão Solar

Guia para qualquer assistente de IA que trabalhe neste repositório. Descreve o que existe
**de fato no código**, não o que está planejado. Quando código e este arquivo divergirem, o
código vence — e este arquivo deve ser atualizado.

> ⚠️ **O projeto ainda não está em produção.** Não há usuários reais nem dados reais. Pode
> fazer mudanças grandes (migração, reescrita de tela, dropar tabela) sem medo de quebrar
> produção. Continue validando tecnicamente: `tsc --noEmit`, lint, a migration aplica.

---

## 1. O que é

App mobile para o **proprietário de usina solar fotovoltaica**. É a camada simples por cima
de dois produtos que já existem e são de outros repositórios:

- **meuWatt** (`C:\dev\meuWatt` — `mw-api` + `mw-fe`) — monitoramento de geração.
- **meuPlano** (`C:\dev\meuPlano`) — gestão de manutenção (O&M).

Idioma do produto e da UI: **português do Brasil**.

**Glossário (não confundir):**

- **Gestão Solar** — este repositório. O app do dono da usina.
- **meuWatt** — plataforma de monitoramento. Consumida via API, não é este projeto.
- **meuPlano** — plataforma de manutenção. Consumida via API, não é este projeto.
- **BFF** — o backend deste projeto (`bff/`). Agrega os dois upstreams e hospeda o
  financeiro de mensalidades, que não existe em nenhum dos dois.

---

## 2. Estrutura

Monorepo com dois aplicativos:

```
Gestao Solar/
├── app/          Expo / React Native — o app do dono
├── bff/          FastAPI — agrega mw-api + meuPlano, gera PDF, hospeda mensalidades
└── docs/         ARQUITETURA · CONTRATO_API · TELAS · PROMPT_DESIGNER
```

Leia [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) antes de mexer em qualquer coisa — é lá
que está o desenho, o modelo de autenticação e o mapa de qual dado vem de onde.

---

## 3. Como rodar

**BFF** (a partir de `bff/`):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # preencher as credenciais de serviço
alembic upgrade head
uvicorn app.main:app --reload --port 8100
```

API em `http://localhost:8100`, Swagger em `/docs`.

**App** (a partir de `app/`):

```powershell
npm install
npm start                   # Expo dev server
npx tsc --noEmit            # checagem de tipos
```

---

## 4. Stack

**BFF:** Python 3.12 · FastAPI · SQLAlchemy 2 · Pydantic v2 · Alembic · httpx (clientes dos
upstreams) · Playwright (Chromium headless para PDF) · PostgreSQL.

**App:** Expo SDK 57 · React Native 0.86 · expo-router · zustand · TanStack Query 5 · axios ·
expo-secure-store · expo-notifications · react-native-webview · expo-updates.

---

## 5. Regras de trabalho

### O dado vem dos upstreams, a regra mora no BFF

O app **nunca** fala direto com a mw-api nem com o meuPlano. Tudo passa pelo BFF, que
autoriza, agrega e traduz. Se uma tela precisa de um dado novo, o caminho é: endpoint no
BFF → cliente do upstream em `bff/app/clients/` → tela.

### Autorização é do BFF, não do app

O BFF usa credenciais de serviço nos upstreams e filtra pelo escopo capturado no login
(`gs_user_plant_access`). Nunca confie num `plant_id` que veio do cliente sem checar contra
o escopo do usuário.

### Nada de "chips" para selecionar opção

Regra herdada do meuPlano e válida aqui: filtro, tipo, categoria, status — tudo é lista
suspensa pesquisável ou controle segmentado. Nunca uma fileira de botõezinhos pill.
Exceções: tags informativas read-only e botões de ação.

### Números em pt-BR

Ponto de milhar, vírgula decimal (`13.800`, `29,87`). Use os helpers de
`app/src/lib/format.ts`. Não exiba número cru.

### Offline primeiro nas leituras

Usina tem sinal ruim. Toda tela de leitura passa por `fetchWithCache`: mostra o cache
imediatamente e atualiza quando a rede responde. `401`/`403` nunca é mascarado pelo cache.

### PDF é sempre in-app

Exiba pelo `PdfViewer` (pdf.js em WebView), com "Enviar cópia" no share sheet nativo. Nunca
entregue o arquivo a um app externo direto — no Android isso dá tela preta silenciosa.

### Cor só significa estado

Seis tons, definidos em `app/src/theme/tokens.ts`. Não invente cor de status nova.

### Toda tela desenha os quatro estados

Carregando (skeleton, nunca spinner solto), vazio, erro, offline com selo de horário.

---

## 6. Pendências conhecidas

**`react-native-screens` duplicado.** O `expo-doctor` aponta duas versões na árvore: a
direta (`~4.26.0`, que o SDK 57 valida) e a `4.27.0` que o `expo-router` traz aninhada.
Existe um `overrides` no `package.json` que resolve numa instalação limpa. Não afeta o
Expo Go — lá os módulos nativos vêm do próprio app — mas **precisa estar resolvido antes
do primeiro build nativo** (Fase 8), porque um build só admite uma versão de cada módulo
nativo.

**Expo Go exige a build do SDK 57.** Cada build do Expo Go embute uma única versão de SDK.
A da loja pode estar atrás; a build certa sai de [expo.dev/go](https://expo.dev/go).

---

## 7. O que NÃO existe (não invente)

- Não há gateway de pagamento. As mensalidades são cadastradas à mão no BFF.
- Não há endpoint `/equipment/{id}/history` no mw-api. A visão de histórico do equipamento
  é montada pelo BFF cruzando `slots` + `breakdowns`.
- Não há vínculo automático entre a usina do meuWatt e a do meuPlano. O vínculo é a tabela
  `gs_plant_link`, preenchida à mão.
- O motor de PDF vetorial **não roda em React Native** — depende de DOM. Roda no Chromium
  headless do BFF.

---

## 7. Dependências fora deste repositório

Trabalho que precisa acontecer no meuWatt e no meuPlano:

| Onde | O quê | Bloqueia |
|---|---|---|
| `mw-fe` | Rota de impressão headless + `window.__gsCapturePdf()` | PDF sob demanda |
| `mw-api` | Conta de serviço para o BFF | Tudo do meuWatt |
| `meuPlano` | Conta de serviço equivalente | Tudo do meuPlano |
| `meuPlano` | `_TETO_NIVEL_CLIENTE` respeitar `nivel_acesso` (teto 2) | L2 no assistente |

---

## 8. Git

Trabalhar em `main`. Repositório: `https://github.com/plataforma-meuwatt/Gestao-Solar`.
