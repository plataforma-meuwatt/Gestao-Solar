# CLAUDE.md — Gestão Solar

Guia para qualquer assistente de IA que trabalhe neste repositório. Descreve o que existe
**de fato no código**, não o que está planejado. Quando código e este arquivo divergirem, o
código vence — e este arquivo deve ser atualizado.

> ⚠️ **O projeto ainda não está em produção.** Não há usuários reais nem dados reais. Pode
> fazer mudanças grandes (migração, reescrita de tela, dropar tabela) sem medo de quebrar
> produção. Continue validando tecnicamente: `tsc --noEmit`, lint, a migration aplica.

---

## REGRA 0 — todo dado vem da API ou do banco. Sem exceção.

**É explicitamente PROIBIDO** exibir qualquer dado que não tenha vindo (a) de uma resposta
da API — meuWatt ou meuPlano, via BFF — ou (b) do banco do Gestão Solar, que é a fonte das
partes que só existem aqui, como o financeiro.

Está proibido, e não há caso de uso que justifique:

- array de exemplo, fixture, seed ou `MOCK_*` alimentando tela;
- valor literal de negócio no JSX (nome de usina, potência, tensão, coordenada, percentual
  de referência, tarifa, contagem de equipamento);
- série, curva ou barra gerada em código (`Math.random`, senoide, LCG, "distribuir o total");
- número derivado de outro e apresentado como medição independente (`medido × 0,98x`
  rotulado como leitura de medidor);
- default de configuração exibido como se fosse propriedade do equipamento;
- **`?? 0` / `|| 0` num campo que vai à tela.**

**Ausência não é zero.** Zero é medição — usina parada gerou 0 kWh, e isso é verdade. Campo
que a API não devolveu é `null`, e a tela mostra **"—"** ou **"sem dados"**. Trocar um pelo
outro faz o dono da usina ler "não medimos" como "não gerou", que é o erro mais caro que
este app pode cometer.

**Ponto sem leitura não vira barra rasteira.** Ele não entra na série; o espaço fica vazio.

**Corolário do dado morto:** linha no banco que aponta para upstream inexistente é fantasma
— a usina aparece na lista e todas as telas dela vêm vazias. Vínculo em `gs_plant_links`
tem de casar com uma usina real (`mw_plant_slug` no meuWatt, `mp_usina_id` no meuPlano); ter
só um dos dois é legítimo, ter nenhum não é.

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

Monorepo com três aplicativos:

```
Gestao Solar/            ← o repositório Git é aqui, na raiz
├── bff/          BACK  — FastAPI. A API, e só a API. Agrega mw-api + meuPlano, gera PDF
├── painel/       FRONT — React + Vite servido por nginx. O gestor (time interno)
├── app/          APP   — Expo / React Native. O dono da usina
├── dev.ps1       sobe as três
└── docs/         ARQUITETURA · CONTRATO_API · TELAS · DECISAO_IDENTIDADE · PROMPT_DESIGNER
```

**São três aplicações independentes, não um monolito em pastas.** Cada uma tem seu deploy:
back e front são dois serviços separados no Railway (`Dockerfile` + `railway.json` dentro
de cada pasta, Root Directory apontando para ela); o app vai para as lojas via EAS.

Consequências que o código carrega, e que não devem ser "simplificadas" de volta:

- **A API não serve tela.** Já serviu o painel em `/painel`; não serve mais. Um deploy de
  tela não reinicia o processo que atende o aplicativo de ninguém.
- **Toda chamada do painel é origem cruzada.** Daí `GS_CORS_ORIGENS`, com lista explícita
  — nunca `*`, porque as respostas carregam sessão de gestor.
- **O endereço da API não é compilado no bundle.** Vem de `API_URL` em tempo de execução
  (`painel/entrypoint.sh` escreve `config.js`), para o mesmo artefato servir qualquer
  ambiente.
- **As fontes moram no front** (`painel/public/fontes/`), que é quem as usa.

O `bff/` continua sendo o único que fala com o mundo externo.

**O painel é onde o cliente nasce.** Cadastrar, vincular as contas dele no meuWatt e no
meuPlano, conceder usinas, entregar a senha provisória e conferir no diagnóstico que o dado
chega dos dois lados. Sem ele, o app não tem a quem servir.

Leia [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) antes de mexer em qualquer coisa — é lá
que está o desenho, o modelo de autenticação e o mapa de qual dado vem de onde.

---

## 3. Como rodar

O caminho normal é o `dev.ps1` da raiz, que sobe backend e painel em janelas separadas:

```powershell
.\dev.ps1 -Instalar    # primeira vez: venv, dependências, migrations
.\dev.ps1              # backend + painel
.\dev.ps1 -App         # backend + painel + aplicativo (Expo)
```

Back em `http://localhost:8100` (Swagger em `/docs`), front em `http://localhost:5180`.

Em desenvolvimento o front chama a API por **proxy do Vite**, não por CORS — a origem fica
a mesma e o caminho exercitado (`/api/painel/...`) é o mesmo de produção. Para reproduzir
produção de verdade, `docker build` nas duas pastas e rodar com `API_URL` e
`GS_CORS_ORIGENS`.

À mão, se precisar de uma parte só:

```powershell
# bff/ — o PYTHONPATH é obrigatório: os módulos são importados como `app.*`
$env:PYTHONPATH = "$PWD"
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8100
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m alembic upgrade head

# painel/ e app/
npm run dev  ·  npm start  ·  npx tsc --noEmit
```

O banco é o Postgres do Supabase, configurado em `bff/.env` (não versionado; modelo em
`.env.example`). Duas armadilhas já resolvidas, que voltariam se alguém refizer a
configuração do zero:

- A senha vai **url-encoded** na `DATABASE_URL` (`#` → `%23`), senão chega truncada.
- A porta é a **5432** (session pooler), não a 6543: o transaction pooler não mantém a
  sessão entre comandos e o Alembic precisa disso.

---

## 4. Stack

**BFF:** Python 3.12+ · FastAPI · SQLAlchemy 2 · Pydantic v2 · Alembic · httpx (clientes dos
upstreams) · Playwright (Chromium headless para PDF) · PostgreSQL (Supabase).

**App:** Expo SDK 57 · React Native 0.86 · expo-router · zustand · TanStack Query 5 · axios ·
expo-secure-store · expo-notifications · react-native-webview · expo-updates.

---

## 5. Regras de trabalho

### O dado vem dos upstreams, a regra mora no BFF

O app **nunca** fala direto com a mw-api nem com o meuPlano. Tudo passa pelo BFF, que
autoriza, agrega e traduz. Se uma tela precisa de um dado novo, o caminho é: endpoint no
BFF → cliente do upstream em `bff/app/clients/` → tela.

### Quem entra é o apelido, não o e-mail

A identidade de uma conta é o `apelido` (`gs_users.apelido`, único). O e-mail é contato —
opcional, não único — e serve para achar a conta da pessoa no meuWatt e no meuPlano.

O motivo é concreto e não deve ser desfeito por parecer estranho: **a mesma pessoa pode
ter duas contas aqui**, com poderes diferentes. `renanmarquezini` é o gestor do sistema;
`renan.marquezini` é o dono de usina que ele atende. Mesmo humano, mesmo e-mail, dois
papéis. Com o e-mail como chave, a segunda conta seria recusada como duplicada.

Três consequências:

- Validação e normalização em `bff/app/core/apelido.py`, num lugar só. O front sugere
  (`sugerirApelido` em `painel/…/Novo.tsx`), o servidor decide.
- `svc.criar` recusa e-mail repetido **entre clientes** — dois clientes com o mesmo e-mail
  são quase sempre o mesmo cadastrado duas vezes. Cliente e gestor podem dividi-lo.
- A senha provisória é entregue com o apelido, nunca com o e-mail: mandar o e-mail junto
  convida o cliente a tentar entrar com ele, que é exatamente o que não funciona.

### Toda rota de upstream entra no catálogo da sonda

`bff/app/services/sonda.py` lista as rotas do meuWatt e do meuPlano de que este sistema
depende, e o painel (Rotas → *Sondar*) exercita uma a uma com o token gravado.

Ao adicionar uma chamada em `bff/app/clients/`, **adicione a rota ao catálogo**. Sem isso
ela vira ponto cego: quebra num deploy do produto de origem e ninguém sabe até um cliente
reclamar de tela vazia. Há um teste que compara o catálogo com o código dos clientes.

Duas regras do catálogo:

- **A sonda só lê.** Rota com efeito colateral (gerar PDF, abrir conversa no assistente)
  entra com `sonda=False` e o motivo escrito — declarada e não chamada. Omitir daria a
  impressão de que a lista está completa.
- **Ordem é funcional.** As rotas que capturam parâmetro (`/plants` devolve o slug) vêm
  antes das que o consomem. Quem depende de um parâmetro que não apareceu é reportada
  como *pulada*, jamais como falha — ela não falhou, não foi chamada.

### Autorização é do BFF, não do app

O BFF lê os upstreams com um **token pessoal** por produto — alguém gera um token na
própria conta do meuWatt/meuPlano e cola em Painel → Conexões — e filtra pelo escopo
capturado no login (`gs_user_plant_access`). Nunca confie num `plant_id` que veio do
cliente sem checar contra o escopo do usuário.

O token vale exatamente o que a conta de quem o gerou vale: se aquela pessoa não enxerga
uma usina no produto de origem, o Gestão Solar também não. Detalhe do desenho — formato,
validação, revogação — em [`docs/DECISAO_IDENTIDADE.md`](docs/DECISAO_IDENTIDADE.md) § 2b;
contrato das rotas em [`docs/CONTRATO_API.md`](docs/CONTRATO_API.md).

Três coisas a respeitar ao mexer nisso:

- **O formato é acordo de três repositórios** (`bff/app/core/tokens_produto.py` e os dois
  produtos). Mudá-lo em um lado exige mudar nos outros — os testes falham em vermelho se
  divergir, e é para isso que existem.
- **Verificar antes de gravar.** `integracoes.salvar_token` só persiste depois de o token
  passar por formato, identidade e alcance. Gravar primeiro e testar depois deixaria o
  gestor com a conexão nova quebrada *e* a antiga perdida.
- **Desconectar não é revogar.** Remover o token no painel só faz o BFF parar de usá-lo;
  ele continua válido no produto de origem, e é lá que a porta se fecha.

A conta de serviço com senha (`usuario_servico`/`senha_cifrada`) é o caminho **antigo**:
segue funcionando para o que já está gravado, mas a tela não oferece mais criar assim, e
conectar por token apaga a senha guardada.

### Usina existe em três formatos, e os três aparecem

O inventário de usinas (`services/conciliacao.montar` + Painel → Usinas) trata igualmente:
nos dois produtos, só no meuWatt, e **só no meuPlano**. O terceiro caso é comum —
manutenção contratada sem monitoramento — e a primeira versão da tela o omitia por
percorrer apenas o meuWatt procurando par. Onze das dezessete usinas reais eram invisíveis.

Duas regras que não devem ser "simplificadas":

- **Existir num produto ≠ estar no aplicativo.** `PlantLink.ativo` é o interruptor, e ele
  é do gestor. Só uma usina ligada pode ser concedida a um cliente. Desligar preserva
  vínculos e concessões; apagar é recusado enquanto houver cliente com ela.
- **Usina não casada aparece duas vezes, uma em cada grupo.** O sistema não *sabe* que são
  a mesma; esconder uma delas seria decidir no lugar de quem decide. O que se oferece é o
  apontamento (`par_provavel_*`) e o botão que casa as duas.

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

**Expo Go exige a build do SDK 57.** Cada build do Expo Go embute uma única versão de SDK.
A da loja pode estar atrás; a build certa sai de [expo.dev/go](https://expo.dev/go).

**O endereço de produção é o do Railway, não o domínio próprio.** O que está no ar é
`https://gestao-solar-production.up.railway.app` (API) e `https://gestaosolar.up.railway.app`
(painel). O `api-gestaosolar.meuwatt.com.br` que o `eas.json` trazia responde **404** — é um
domínio que nunca foi apontado, e apontá-lo é trabalho pendente no DNS.

Duas armadilhas do deploy pelo CLI, ambas já pagas:

- **`railway up` roda da raiz do repositório**, nunca de dentro de `bff/`. O serviço tem
  *Root Directory* em `bff/`, então subir de lá faz o Railway procurar `bff/bff/Dockerfile`
  e o deploy falha — sem derrubar o que está no ar, o que torna a falha fácil de não notar:
  o `/health` continua respondendo 200 pela versão antiga.
- **O token do `.env.txt` é de projeto, não de conta.** Vai em `RAILWAY_TOKEN`; com
  `RAILWAY_API_TOKEN` ou em `railway whoami` responde `Unauthorized`.

**Testar contra o BFF local a partir do celular não funciona sem preparo.** O firewall do
Windows não tem regra para a porta 8100 — o `python.exe` do venv não é o `node.exe`, que já
tem permissão e por isso o Metro na 8081 funciona —, e o Android recusa HTTP em claro num
build release.

**O aplicativo é quase todo maquete.** Uma tela lê do BFF — a lista de Usinas
(`GET /api/v1/plants`) — e o login. As outras dez (Início, Financeiro, Documentos,
Assistente, Notificações, Perfil, Fatura, Equipamentos, detalhe da Usina) desenham
`src/features/exemplo.ts`, e os endpoints correspondentes não existem no servidor. Ao
ligar uma delas, o caminho é o da §5: endpoint no BFF → cliente do upstream → tela.

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

## 8. Dependências fora deste repositório

Trabalho que precisa acontecer no meuWatt e no meuPlano:

| Onde | O quê | Estado |
|---|---|---|
| `mw-fe` | Rota de impressão headless + `window.__gsCapturePdf()` | pendente — bloqueia o PDF sob demanda |
| `mw-api` | Token pessoal para o BFF (`/auth/tokens`, migration 131) | **feito e no ar** (13/08/2026) |
| `meuPlano` | Token pessoal equivalente (migration `jt00pat11ok0`) | **feito e no ar** (13/08/2026) |
| `mw-api` | `GET /plants/{slug}/breakdowns/range` responde **500** em qualquer intervalo | pendente — achado pela sonda em 13/08/2026 |
| `meuPlano` | `_TETO_NIVEL_CLIENTE` respeitar `nivel_acesso` (teto 2) | pendente — bloqueia L2 no assistente |

As duas pontes estão conectadas e testadas contra produção: `api.meuwatt.com.br` e
`meuplano.up.railway.app`.

**O 500 do `breakdowns/range`** é do lado do mw-api — reproduz com qualquer par de datas,
inclusive um único dia. Bloqueia a tela de Paradas e o histórico do equipamento, que é
montado cruzando `slots` + `breakdowns`. É a única rota vermelha na sonda.

---

## 9. Git e deploy

Trabalhar em `main`. Repositório: `https://github.com/plataforma-meuwatt/Gestao-Solar`.

**Sempre commitar, sempre publicar, sempre mandar o OTA.** Não deixar trabalho parado no
working tree. Um push que muda o `app/` sem OTA correspondente não chegou em ninguém.

### As credenciais já estão na máquina — não peça login

`C:\dev\Gestao Solar\.env.txt` (fora do git, coberto por `.env.*` no `.gitignore`) guarda o
**token do Expo** e o **token do Railway**. Não existe motivo para pedir `eas login` ao Renan,
e `eas whoami` dizendo "Not logged in" **não** significa que falta credencial: significa que
faltou exportar a variável.

Carregar sem estampar o valor no terminal:

```bash
export EXPO_TOKEN=$(sed -n 's/^Expo:[[:space:]]*//p' "/c/dev/Gestao Solar/.env.txt" | tr -d '\r')
```

O arquivo é `.txt` e mora na raiz — é por isso que uma busca por `.env` não acha, e é por isso
que o `rg`/Grep passa batido: sendo ignorado pelo git, ele fica invisível na busca padrão.

### BFF e painel → Railway, no push

Não há CLI no caminho normal: **o push para `main` já dispara o deploy** dos dois serviços
(cada um com seu Root Directory). Leva ~1–2 min.

Confirme por probe, nunca pelo push. `/openapi.json` **não serve** — docs está desabilitado em
produção e a resposta vem vazia. Use o par rota-nova × caminho-irmão-inexistente:

```bash
B=https://gestao-solar-production.up.railway.app
curl -s -o /dev/null -w "%{http_code}\n" $B/api/v1/plants/1/xyz-inexistente   # 404 = controle
curl -s -o /dev/null -w "%{http_code}\n" $B/api/v1/plants/1/<sua-rota-nova>   # 401 = está no ar
```

401 é a resposta certa e desejada: a rota existe e exigiu token. Se vier 404, o deploy não
landou — o controle ao lado prova que 404 é mesmo "não existe", e não erro de autenticação.

### app/ → OTA pelo EAS, no canal `preview`

> ⚠️ **O canal é `preview`, não `production`.** O aparelho do Renan roda o APK do perfil
> `preview` (`distribution: internal`) — **nunca houve build do perfil `production`**.
> Publicar em `production` sobe um update que existe no servidor e não alcança ninguém:
> o app responde **"Tudo em dia"**, porque para o canal dele isso é verdade. Confira com
> `eas build:list` antes de escolher o canal; a coluna `Channel` é a resposta.

```bash
cd "C:\dev\Gestao Solar\app"
export EXPO_TOKEN=$(sed -n 's/^Expo:[[:space:]]*//p' "/c/dev/Gestao Solar/.env.txt" | tr -d '\r')
npx eas-cli@latest update --channel preview --environment preview \
    --message "<o que mudou>" --non-interactive
```

`--environment` é **obrigatório** junto com `--non-interactive`; sem ele o comando falha
reclamando da flag, e não da credencial.

O dia em que sair build de loja pelo perfil `production`, aí sim o OTA passa a ser duplo —
um por canal — e este aviso muda.

Detalhes que já custaram tempo:

- **O endereço da API mora em `app.json` (`extra.apiUrl`), não em variável de ambiente.**
  `eas update` não injeta `EXPO_PUBLIC_API_URL` — quem depende só da env var publica OTA
  apontando para `localhost`, ou seja, para o próprio celular.
- **`runtimeVersion` é `appVersion`.** O update só alcança builds instalados com a mesma
  `version` do `app.json`. Subiu a `version`? Então precisa de build novo, não de OTA.
- OTA cobre **só JS e assets**. Código nativo, permissão nova ou bump de SDK exigem
  `eas build --profile production`.
- **⛔ MÓDULO NATIVO NÃO SE IMPORTA NO TOPO DE UM ARQUIVO QUE UMA ROTA CARREGA.** Corolário
  da regra acima, e custou caro em 04/09/2026: `expo-screen-orientation` entrou junto com o
  gráfico em tela cheia, a `version` do `app.json` seguiu em `0.1.0` — então todo OTA
  publicado depois continuou alcançando APKs anteriores à biblioteca. `requireNativeModule`
  lança na AVALIAÇÃO do módulo, antes de qualquer render: como `grafico-cheio.tsx` é
  importado pelas três telas atrás do clique numa usina, o sintoma foi cirúrgico — as abas
  abriam, a usina não, e o relato que chegou foi *"clico na usina e o app fecha ou trava"*.
  Carregue por `lib/nativo.ts` (`moduloNativo`), use quando `!= null` e tenha um
  comportamento honesto para a ausência: a função perdida degrada, a tela vive. E declare a
  peça em `PECAS_NATIVAS` (`components/Atualizacao.tsx`), para o aparelho **dizer** que está
  com pacote anterior em vez de a gente descobrir por dedução.
- **"Tudo em dia" não prova que o OTA foi publicado.** Prova só que não há update *para o
  canal e a runtime daquele aparelho*. Canal errado, `runtimeVersion` diferente e "nada novo
  mesmo" produzem a mesma frase. Por isso a tela do avatar mostra canal, runtime, ID e data
  do update rodando — sem isso o diagnóstico é adivinhação.
- Para conferir no aparelho, **feche o app de verdade** (fora da lista de recentes) e reabra.
  O `fallbackToCacheTimeout: 12000` do `app.json` faz ele esperar o conteúdo novo antes de
  desenhar; com o padrão (`0`) seriam duas aberturas até aparecer.

### Ordem quando a mudança atravessa BFF e app

BFF primeiro, OTA depois. O caminho inverso entrega ao celular uma tela que chama rota que
ainda não existe — e o usuário lê isso como "sem dados", que é exatamente a mensagem que a
REGRA 0 reserva para ausência real.
