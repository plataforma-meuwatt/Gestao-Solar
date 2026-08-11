# Gestão Solar

App do **proprietário de usina solar fotovoltaica**. É a camada simples por cima do
**meuWatt** (monitoramento de geração) e do **meuPlano** (gestão de manutenção).

O dono abre o app e responde cinco perguntas, nesta ordem:

1. Minha usina está gerando bem hoje / neste mês?
2. Tem algum equipamento parado? Há quanto tempo?
3. A manutenção que eu contratei está sendo feita?
4. Preciso do relatório do mês / da OS em PDF.
5. Minha mensalidade está em dia?

## Desenho

```
   ┌─────────────────────────────┐
   │  App Gestão Solar (Expo)    │   iOS + Android
   └──────────────┬──────────────┘
                  │  1 token só
   ┌──────────────▼──────────────┐
   │  BFF Gestão Solar (FastAPI) │   autoriza, agrega, gera PDF
   └───────┬─────────────┬───────┘
   ┌───────▼──────┐ ┌────▼─────────┐
   │   mw-api     │ │  meuPlano    │
   │  (meuWatt)   │ │   backend    │
   └──────────────┘ └──────────────┘
```

## Estrutura

| Pasta | O que é |
|---|---|
| `app/` | Expo / React Native — o app |
| `bff/` | FastAPI — agrega os dois upstreams, gera PDF, hospeda as mensalidades |
| `docs/` | Arquitetura, contrato da API, inventário de telas, prompt do designer |

## Documentação

- [**Arquitetura**](docs/ARQUITETURA.md) — desenho, autenticação, de onde vem cada dado
- [**Contrato da API**](docs/CONTRATO_API.md) — endpoints do BFF com request/response
- [**Telas**](docs/TELAS.md) — inventário de telas ↔ rotas ↔ endpoints
- [**Prompt do designer**](docs/PROMPT_DESIGNER.md) — especificação visual completa
- [**CLAUDE.md**](CLAUDE.md) — guia para assistentes de IA

## Rodando

**BFF** (a partir de `bff/`):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8100
```

**App** (a partir de `app/`):

```powershell
npm install
npm start
```

## Estado

Fase 0 — fundação. Estrutura, documentação e esqueletos. As fases seguintes estão no plano
de implementação (login e usinas → geração → equipamentos e mapa → manutenção → documentos
e PDF → financeiro → assistente → publicação).
