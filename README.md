# Gestão Solar

App do **proprietário de usina solar fotovoltaica**. É a camada simples por cima do
**meuWatt** (monitoramento de geração) e do **meuPlano** (gestão de manutenção).

O dono abre o app e responde cinco perguntas, nesta ordem:

1. Minha usina está gerando bem hoje / neste mês?
2. Tem algum equipamento parado? Há quanto tempo?
3. A manutenção que eu contratei está sendo feita?
4. Preciso do relatório do mês / da OS em PDF.
5. Minha mensalidade está em dia?

## O que é cada pasta

**Este repositório inteiro é um projeto só** — o Git fica aqui na raiz (`C:\Dev\Gestao
Solar`), não dentro das subpastas. Dentro dele moram três aplicações, e a confusão comum é
achar que "front" é uma coisa só: são **duas** frentes, para duas pessoas diferentes.

**Três aplicações independentes**, cada uma com seu ciclo de vida, seu deploy e sua
tecnologia. Não é um monolito dividido em pastas: são três coisas que se falam por HTTP.

| Pasta | O que é | Quem usa | Em desenvolvimento | Em produção |
|---|---|---|---|---|
| **`bff/`** | **BACK** — a API. FastAPI + Postgres. Fala com o meuWatt e o meuPlano, autoriza, guarda os dados. | o front e o app | `localhost:8100` | serviço no Railway |
| **`painel/`** | **FRONT** — o painel do gestor. React + Vite, servido por nginx. | o gestor (você) | `localhost:5180` | serviço no Railway |
| **`app/`** | **APP** — o aplicativo do dono da usina. Expo / React Native. | o dono da usina | Expo Go, no celular | lojas, via EAS |
| `docs/` | Arquitetura, contrato da API, telas | — | — | — |

Nada mais na raiz é código: `dev.ps1` sobe tudo, `CLAUDE.md` orienta assistentes de IA.

**Só o `bff/` fala com o mundo externo.** Nem o painel nem o app conhecem o endereço do
meuWatt ou do meuPlano — eles só conhecem a API, que autoriza cada pedido antes de repassar.

```
   ┌──────────────────┐        ┌──────────────────┐
   │  app/  (celular) │        │ painel/  (web)   │   nginx · estático
   │  dono da usina   │        │  o gestor        │   sabe onde a API está
   └────────┬─────────┘        └────────┬─────────┘   por API_URL, em runtime
            │                           │
            └───────────┬───────────────┘
                        │  HTTP · 1 token por pessoa
              ┌─────────▼──────────┐
              │  bff/  (FastAPI)   │  autoriza · agrega · gera PDF
              └──┬──────────────┬──┘  CORS restrito a GS_CORS_ORIGENS
                 │              │        ┌────────────────┐
        ┌────────▼─────┐ ┌──────▼──────┐ │  Postgres      │
        │   mw-api     │ │  meuPlano   │ │  (Supabase)    │
        │  (meuWatt)   │ │   backend   │ └────────────────┘
        └──────────────┘ └─────────────┘
```

## Como subir

Uma vez, para instalar tudo (venv, dependências, migrations):

```powershell
.\dev.ps1 -Instalar
```

Depois, no dia a dia:

```powershell
.\dev.ps1          # back + front
.\dev.ps1 -App     # back + front + aplicativo no celular
```

Cada parte abre na própria janela, com o nome no título. Para subir uma só, veja a seção
"Rodando à mão" abaixo.

| | Endereço |
|---|---|
| Back (API) | <http://localhost:8100> · Swagger em `/docs` |
| Front (painel) | <http://localhost:5180> |
| App | QR code na janela do Expo — o celular precisa estar na mesma rede |

Em desenvolvimento o painel chama a API por **proxy do Vite**, não por CORS: a origem é a
mesma, e o caminho exercitado (`/api/painel/...`) é o mesmo de produção. Em produção o
endereço da API vem da variável `API_URL`, resolvida quando o contêiner sobe.

## Como se entra

**Por apelido, não por e-mail.** A identidade de uma conta aqui é o apelido
(`renan.marquezini`); o e-mail é contato e serve para achar a conta da pessoa no meuWatt e
no meuPlano.

O motivo é concreto: a mesma pessoa pode ser o gestor do sistema **e** o dono de uma usina
atendida por ele. São dois papéis com poderes diferentes, logo duas contas — e com o
e-mail como chave a segunda seria recusada como duplicada. Detalhes em
[`bff/app/core/apelido.py`](bff/app/core/apelido.py).

A primeira conta nasce pela linha de comando; daí em diante, pela tela de Equipe:

```powershell
cd bff
$env:PYTHONPATH = "$PWD"
.\venv\Scripts\python.exe scripts\criar_gestor.py meu.apelido "Meu Nome"
```

## O caminho de um cliente novo

1. **Painel → Conexões** — cole o token pessoal do meuWatt e o do meuPlano. Cada um é
   gerado na conta de alguém, no próprio produto, e vale o que aquela conta vale.
2. **Painel → Rotas** — clique em *Sondar*. Ele chama uma a uma as rotas de que este
   sistema depende e mostra quais responderam. É a resposta para "está tudo funcionando?".
3. **Painel → Usinas** — concilie as usinas do meuWatt com as do meuPlano.
4. **Painel → Clientes → Novo** — cadastre, vincule as contas dele nos dois produtos,
   escolha as usinas e entregue o apelido com a senha provisória.
5. **Painel → Diagnóstico** — confira o que aquele cliente vai ver antes de ele abrir o app.
6. **Aplicativo** — ele entra com o apelido e a senha provisória, e troca a senha.

## Rodando à mão

**Backend** (a partir de `bff/`):

```powershell
$env:PYTHONPATH = "$PWD"
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8100
```

**Painel** (a partir de `painel/`): `npm run dev` · tipos com `npm run check`
**Aplicativo** (a partir de `app/`): `npm start` · tipos com `npx tsc --noEmit`
**Testes** (a partir de `bff/`): `.\venv\Scripts\python.exe -m pytest`

## Configuração

O `bff/.env` guarda a URL do banco e as duas chaves (assinatura de sessão e cifra dos
segredos). **Não é versionado** — o modelo está em `bff/.env.example`.

As credenciais dos produtos **não moram no `.env`**: são tokens colados em Painel →
Conexões e guardados cifrados no banco, para poderem ser trocados e testados sem redeploy.

## Deploy

Dois serviços no Railway, um por aplicação. Cada um tem seu `Dockerfile` e seu
`railway.json` dentro da própria pasta; no Railway, cada serviço aponta o **Root Directory**
para ela.

| Serviço | Root Directory | Variáveis |
|---|---|---|
| **back** | `bff` | `DATABASE_URL` · `GS_JWT_SECRET` · `GS_ENCRYPTION_KEY` · `GS_CORS_ORIGENS` · `ENVIRONMENT=production` |
| **front** | `painel` | `API_URL` (o endereço público do back) |

As duas metades se conhecem por variável, e só por variável: o front recebe `API_URL` e o
back recebe o endereço do front em `GS_CORS_ORIGENS`. Nenhum endereço fica compilado dentro
do bundle — promover de homologação para produção é trocar uma variável, não reconstruir.

Três recusas deliberadas de subir, que trocam uma falha silenciosa por uma clara:

- O back **não sobe** em produção sem `GS_JWT_SECRET`, `GS_ENCRYPTION_KEY` ou
  `GS_CORS_ORIGENS`. Sem a última, o painel abriria numa tela em branco com erro de CORS
  no console — e nada no servidor acusaria.
- O front **não sobe** sem `API_URL`. Sem ela, chamaria a si mesmo e receberia o próprio
  HTML no lugar do JSON.
- `GS_ENCRYPTION_KEY` precisa ser **a mesma** que cifrou os tokens no banco. Trocá-la torna
  ilegível o que está gravado, e as conexões precisam ser refeitas.

O back roda `alembic upgrade head` ao subir — idempotente, e no lugar onde há banco
alcançável e variáveis definidas.

O aplicativo não entra aqui: é publicado nas lojas pelo EAS.

## Documentação

- [**Arquitetura**](docs/ARQUITETURA.md) — desenho, autenticação, de onde vem cada dado
- [**Contrato da API**](docs/CONTRATO_API.md) — endpoints do BFF com request/response
- [**Telas**](docs/TELAS.md) — inventário de telas ↔ rotas ↔ endpoints
- [**Decisão de identidade**](docs/DECISAO_IDENTIDADE.md) — por que token pessoal, por que apelido
- [**CLAUDE.md**](CLAUDE.md) — guia para assistentes de IA
