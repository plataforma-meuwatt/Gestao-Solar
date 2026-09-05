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
Solar`), não dentro das subpastas. Dentro dele moram cinco aplicações, e a confusão comum é
achar que "front" é uma coisa só: são **três** frentes, para três públicos — o gestor no
painel, o cliente no navegador, o dono da usina no celular.

**Aplicações independentes**, cada uma com seu ciclo de vida, seu deploy e sua tecnologia.
Não é um monolito dividido em pastas: são coisas que se falam por HTTP.

| Pasta | O que é | Quem usa | Em desenvolvimento | Em produção |
|---|---|---|---|---|
| **`bff/`** | **BACK** — a API. FastAPI + Postgres. Fala com o meuWatt e o meuPlano, autoriza, guarda os dados. | os fronts e o app | `localhost:8100` | serviço no Railway |
| **`painel/`** | **FRONT** — o painel do gestor. React + Vite, servido por nginx. | o gestor (você) | `localhost:5180` | serviço no Railway |
| **`portal/`** | **FRONT** — o portal do cliente, no navegador. React + Vite, servido por nginx. | o dono da usina | `localhost:5181` | **serviço ainda a criar** |
| **`app/`** | **APP** — o aplicativo do dono da usina. Expo / React Native. | o dono da usina | Expo Go, no celular | lojas, via EAS |
| **`talksolar/`** | **PRODUTO À PARTE** — o mensageiro da equipe. Servidor, banco e app de PC próprios; não é do Gestão Solar, só mora aqui. | a equipe | `localhost:8110` | **serviço ainda a criar** |
| `docs/` | Arquitetura, contrato da API, telas | — | — | — |

Nada mais na raiz é código: `dev.ps1` sobe tudo, `CLAUDE.md` orienta assistentes de IA.

**Só o `bff/` fala com o mundo externo.** Nem os fronts nem o app conhecem o endereço do
meuWatt ou do meuPlano — eles só conhecem a API, que autoriza cada pedido antes de repassar.

```
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │  app/  (celular) │  │ portal/   (web)  │  │ painel/   (web)  │
   │  dono da usina   │  │  dono da usina   │  │    o gestor      │
   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
            │                     │                     │  nginx · estático
            └─────────────────────┼─────────────────────┘  sabe onde a API está
                                  │                        por API_URL, em runtime
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

O **`talksolar/` fica fora deste desenho de propósito**: banco próprio (tabelas `ts_*`),
sessão própria, e nenhuma linha do `bff/` importada. Ele conversa com o meuPlano por HTTP,
como faria qualquer sistema de fora. Ver [`talksolar/README.md`](talksolar/README.md).

## Como subir

Uma vez, para instalar tudo (venv, dependências, migrations):

```powershell
.\dev.ps1 -Instalar
```

Depois, no dia a dia:

```powershell
.\dev.ps1          # back + painel + portal
.\dev.ps1 -App     # + aplicativo no celular
.\dev.ps1 -Talk    # + servidor do Talk Solar
```

Cada parte abre na própria janela, com o nome no título. Para subir uma só, veja a seção
"Rodando à mão" abaixo.

| | Endereço | Sobe quando |
|---|---|---|
| Back (API) | <http://localhost:8100> · Swagger em `/docs` | sempre |
| Painel (gestor) | <http://localhost:5180> | sempre |
| Portal (cliente) | <http://localhost:5181> | sempre |
| App | QR code na janela do Expo — o celular precisa estar na mesma rede | `-App` |
| Talk Solar | <http://localhost:8110> · `/saude` | `-Talk` |

O Talk Solar é opt-in porque tem **banco e `.env` próprios**: subi-lo sem eles daria erro na
largada, todo dia, para quem só quer mexer no Gestão Solar. As outras portas estão tomadas
(8100, 5180, 5181, e a 8081 do Metro) — a 8110 é dele, e a escolha está registrada no
[`CLAUDE.md`](CLAUDE.md#3-como-rodar).

Em desenvolvimento os fronts chamam a API por **proxy do Vite**, não por CORS: a origem é a
mesma, e o caminho exercitado é o mesmo de produção. Em produção o endereço da API vem da
variável `API_URL`, resolvida quando o contêiner sobe.

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
**Portal** (a partir de `portal/`): `npm run dev` · `npm run check` (tipos + regra 0) · `npm test`
**Aplicativo** (a partir de `app/`): `npm start` · tipos com `npx tsc --noEmit`
**Testes** (a partir de `bff/`): `.\venv\Scripts\python.exe -m pytest`

**Talk Solar** (a partir de `talksolar/server/`, com venv e `.env` próprios):

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8110
```

⚠ Os testes de lá exigem o **`PYTHONPATH` vazio**. Os dois projetos têm um pacote chamado
`app`; com o `PYTHONPATH` do BFF exportado, `talksolar/server/testes/test_contrato.py`
morre em `ImportError: cannot import name 'webhooks' from 'app'` — que parece defeito do
projeto e não é.

## Configuração

O `bff/.env` guarda a URL do banco e as duas chaves (assinatura de sessão e cifra dos
segredos). **Não é versionado** — o modelo está em `bff/.env.example`.

As credenciais dos produtos **não moram no `.env`**: são tokens colados em Painel →
Conexões e guardados cifrados no banco, para poderem ser trocados e testados sem redeploy.

## Deploy

Um serviço no Railway por aplicação. Cada um tem seu `Dockerfile` e seu `railway.json`
dentro da própria pasta; no Railway, o serviço aponta o **Root Directory** para ela.

| Serviço | Root Directory | `railwayConfigFile` | Variáveis | Estado |
|---|---|---|---|---|
| **back** | `bff` | `bff/railway.json` | `DATABASE_URL` · `GS_JWT_SECRET` · `GS_ENCRYPTION_KEY` · `GS_CORS_ORIGENS` · `ENVIRONMENT=production` | no ar |
| **painel** | `painel` | `painel/railway.json` | `API_URL` (o endereço público do back) | no ar |
| **portal** | `portal` | `portal/railway.json` | `API_URL` | **a criar** |
| **talksolar** | `talksolar/server` | `talksolar/server/railway.json` | `DATABASE_URL` (banco PRÓPRIO) · `TALK_JWT_SECRET` · `TALK_STORAGE=supabase` · `SUPABASE_URL` · `SUPABASE_SERVICE_KEY` · `TALK_BUCKET=talksolar` · `TALK_CORS` | **a criar** |
| **talksolar-updates** | `talksolar/updates` | — | `RELEASES_TOKEN` · volume em `/data` | **a criar** — serve o instalador do app de PC |

**O que ainda não existe no repositório, para não parecer que está pronto:** o
`talksolar/server` tem `railway.json`, mas **não tem `Dockerfile`** — o que está lá usa
`NIXPACKS` com `startCommand` **sem `exec`**, o que deixa o shell como PID 1 e mata o
uvicorn sem encerrar as requisições em voo (é a armadilha que o `bff/Dockerfile` documenta
e resolve). E a pasta `talksolar/updates` **ainda não existe**: ela é o servidor de
releases do app de PC, que precisa ser próprio — publicar aquele instalador no servidor de
releases do meuPlano sobrescreveria o `latest.yml` de lá e faria todo PC com o app de campo
instalado baixar o mensageiro.

**`railwayConfigFile` é ajuste do painel do Railway, não do repositório**, e o caminho é
relativo à **raiz** — não ao Root Directory. Sem ele, o builder cai no Railpack, **ignora o
`Dockerfile`** e o `entrypoint.sh` nunca escreve o `config.js`: o front sobe sem
`window.__GS_API__`, chama a si mesmo, recebe o próprio HTML e o console diz
`Unexpected token '<'` — longe da causa.

As metades se conhecem por variável, e só por variável: o front recebe `API_URL` e o back
recebe o endereço de **cada** front em `GS_CORS_ORIGENS`. Nenhum endereço fica compilado
dentro do bundle — promover de homologação para produção é trocar uma variável, não
reconstruir.

⚠ **Front novo exige duas mudanças, não uma:** criar o serviço **e** acrescentar a origem
pública dele a `GS_CORS_ORIGENS` no serviço do back. Sem a segunda, ele abre em tela branca
com erro de CORS no console e nada no servidor acusa. Em produção não há rede de segurança:
`ENVIRONMENT=production` desliga o regex de localhost.

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

**O healthcheck do painel mente; o do portal não.** O do painel é `/`, que devolve o
`index.html` mesmo com o bundle quebrado — o Railway declara saudável um painel que não
abre. O portal corrigiu com `location = /saude { return 200 "ok"; }` no nginx e
`healthcheckPath: "/saude"`. **Front novo copia o `portal/`**, não o `painel/`.

O aplicativo não entra aqui: é publicado nas lojas pelo EAS.

## Documentação

- [**Arquitetura**](docs/ARQUITETURA.md) — desenho, autenticação, de onde vem cada dado
- [**Contrato da API**](docs/CONTRATO_API.md) — endpoints do BFF com request/response
- [**Telas**](docs/TELAS.md) — inventário de telas ↔ rotas ↔ endpoints (app, portal e painel)
- [**Decisão de identidade**](docs/DECISAO_IDENTIDADE.md) — por que token pessoal, por que apelido
- [**CLAUDE.md**](CLAUDE.md) — guia para assistentes de IA

O Talk Solar tem documentação própria, que não se mistura com esta:
[`talksolar/README.md`](talksolar/README.md) e `talksolar/docs/` (contrato da API, como
plugar um sistema, o que falta entregar).
