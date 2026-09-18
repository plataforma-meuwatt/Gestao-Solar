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

O **Talk Solar** (o mensageiro da equipe) morou aqui entre 04 e 11/09/2026 e **voltou para o repositório do meuPlano**, que é de quem ele é: a ferramenta é do corpo técnico, aparece em Ferramentas → Talk Solar, e a integração inteira já vivia lá. Ver `meuPlano/talksolar/`.

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

A primeira conta nasce pela linha de comando; daí em diante, pela tela de Usuários do
sistema:

```powershell
cd bff
$env:PYTHONPATH = "$PWD"
.\venv\Scripts\python.exe scripts\criar_gestor.py meu.apelido "Meu Nome"
```

**O perfil diz se a conta entra no painel; as áreas dizem o que ela abre lá dentro.**
Administrador abre todas as telas e é o único que mexe em Usuários do sistema. Quem é
atendimento abre só o que estiver marcado ali — dá para ter alguém que cuida de clientes e
não enxerga o WhatsApp da empresa nem os tokens dos produtos. Catálogo em
[`bff/app/services/areas_painel.py`](bff/app/services/areas_painel.py).

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

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8110
```

⚠ Os testes de lá exigem o **`PYTHONPATH` vazio**. Os dois projetos têm um pacote chamado
## Configuração

O `bff/.env` guarda a URL do banco e as duas chaves (assinatura de sessão e cifra dos
segredos). **Não é versionado** — o modelo está em `bff/.env.example`.

As credenciais dos produtos **não moram no `.env`**: são tokens colados em Painel →
Conexões e guardados cifrados no banco, para poderem ser trocados e testados sem redeploy.

## Deploy

Um serviço no Railway por aplicação. Cada um tem seu `Dockerfile` e seu `railway.json`
dentro da própria pasta; no Railway, o serviço aponta o **Root Directory** para ela.

| Serviço no Railway | Root Directory | `railwayConfigFile` | Variáveis | Deploy | Estado |
|---|---|---|---|---|---|
| **back** (`Gestao-Solar`) | `bff` | `bff/railway.json` | `DATABASE_URL` · `GS_JWT_SECRET` · `GS_ENCRYPTION_KEY` · `GS_CORS_ORIGENS` · `ENVIRONMENT=production` | no push | no ar |
| **painel** (`front`) | `painel` | `painel/railway.json` | `API_URL` (o endereço público do back) | no push | no ar |
| **portal** (`appgestao`) | `portal` | `portal/railway.json` | `API_URL` | ⛔ **à mão** | no ar |
| **gateway** (`whatsapp`) | `whatsapp` | ⛔ não aceito mais | `DATABASE_URL` (6543) · `DATABASE_URL_MIGRACAO` (5432) · `GATEWAY_ENCRYPTION_KEY` · `WHATSAPP_CHAVE_INTERNA` · `BFF_URL` · `ENVIRONMENT=production` | ⛔ **à mão** | no ar |

O **gateway** (`whatsapp/`) nasceu em 16/09/2026 e é o dono da conversa com a Meta. Três
coisas dele fogem do padrão dos irmãos, e as três já custaram um deploy vermelho:

- **`railwayConfigFile` não é mais aceito pela API.** Config as Code (`railway.json`) está
  deprecado e a mutation `serviceInstanceUpdate` recusa o campo com todas as letras. A
  configuração deste serviço (Root Directory, `dockerfilePath`, healthcheck, política de
  reinício) mora no painel do Railway, gravada pela API. O `whatsapp/railway.json` continua
  no repositório porque arquivos existentes seguem valendo **até 2026-12-01** — depois disso
  ele é só documentação da intenção.
- **O builder aparece como `RAILPACK` e mesmo assim o Dockerfile é usado**, porque
  `dockerfilePath` está preenchido. O enum `Builder` da API não tem mais `DOCKERFILE`.
- **As credenciais da Meta NÃO são variáveis de ambiente.** Token, número, segredo do app e
  token de verificação são cadastrados em Painel → WhatsApp e vivem cifrados no banco. O que
  está na tabela acima é só o que o serviço precisa para subir.

⛔ **O `appgestao` não está ligado ao GitHub, e o `railway up` dele tem armadilha.** Um push
que mexe só em `portal/` não muda nada em produção, e a falha é silenciosa: o site continua
respondendo 200, com o código antigo. Pior, o CLI 5.45.7 passou a subir o **repositório
inteiro** em vez da pasta atual, então o `cd portal && railway up` que funcionava morre no
Railpack em ~25 s — o `Dockerfile` do portal não fica na raiz do contexto, e o *Root
Directory* da tabela acima **não salva**: ele vale para build vindo do GitHub, não para
upload do CLI, em que o arquivo enviado É o contexto. O passo a passo que funciona (montar o
contexto fora do repositório) está em [`CLAUDE.md`](CLAUDE.md) §6, junto com a prova por
arquivo novo — o SPA devolve 200 em qualquer caminho, então status não prova deploy.

**O que ainda não existe no repositório, para não parecer que está pronto:** o
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

A documentação do Talk Solar foi com ele: `meuPlano/talksolar/README.md` e
`meuPlano/talksolar/docs/`.
