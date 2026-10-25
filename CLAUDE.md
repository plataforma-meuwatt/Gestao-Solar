> # REGRA ZERO — NUNCA CHUTE NADA
>
> Endereço, porta, nome de campo, nome de tabela, versão, caminho de arquivo,
> parâmetro de API, comando de terceiro: **verifique antes de usar**. Ler o
> código, consultar o banco, bater na URL e ver o que responde custa segundos;
> um chute custa o tempo de quem depende do resultado, e o erro chega disfarçado
> de "quase certo".
>
> O que já aconteceu por chute, neste conjunto de projetos:
>
> * `api.meuplano.solar` — inventado. Não existe. O login do TermoVision morria
>   em `getaddrinfo failed` DEPOIS de a pessoa já ter autorizado no site. O
>   endereço real (`meuplano.up.railway.app`) estava escrito no repositório.
> * O comando do RealityScan, escrito de memória: faltava um argumento
>   obrigatório, e a falha só aparecia no fim, após horas de reconstrução.
> * "0 erros de tipo" repetido a tarde inteira rodando um comando que não
>   checava arquivo nenhum. O certo era `npm run typecheck`.
>
> Não sabendo, a resposta é **"vou verificar"** — nunca a versão plausível.
> Verificado, diga como verificou.

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

Monorepo com cinco aplicações:

```
Gestao Solar/            ← o repositório Git é aqui, na raiz
├── bff/          BACK  — FastAPI. A API, e só a API. Agrega mw-api + meuPlano, gera PDF
├── painel/       FRONT — React + Vite servido por nginx. O gestor (time interno)
├── portal/       FRONT — React + Vite servido por nginx. O cliente, no navegador
├── app/          APP   — Expo / React Native. O dono da usina, no celular
├── whatsapp/     BACK  — FastAPI. Gateway do WhatsApp: recebe da Meta e envia pela Meta.
│                 O pacote Python chama-se `gateway`, NUNCA `app` (ver §6)
│                 próprios. Chegou do repositório do meuPlano em 04/09/2026
├── dev.ps1       sobe back + painel + portal (e, sob demanda, o aplicativo)
└── docs/         ARQUITETURA · CONTRATO_API · TELAS · DECISAO_IDENTIDADE · PROMPT_DESIGNER
```

**São aplicações independentes, não um monolito em pastas.** Cada uma tem seu deploy: no
Railway são serviços separados, um por pasta (`Dockerfile` + `railway.json` dentro dela,
Root Directory apontando para ela); o app vai para as lojas via EAS. A tabela de serviços —
Root Directory, `railwayConfigFile` e variáveis de cada um — está no
[`README.md`](README.md#deploy).

O **Talk Solar** (o mensageiro da equipe) morou aqui entre 04 e 11/09/2026 e **voltou para o repositório do meuPlano**, que é de quem ele é: a ferramenta é do corpo técnico, aparece em Ferramentas → Talk Solar, e a integração inteira já vivia lá. Ver `meuPlano/talksolar/`.

Consequências que o código carrega, e que não devem ser "simplificadas" de volta:

- **A API não serve tela.** Já serviu o painel em `/painel`; não serve mais. Um deploy de
  tela não reinicia o processo que atende o aplicativo de ninguém.
- **Toda chamada do painel e do portal é origem cruzada.** Daí `GS_CORS_ORIGENS`, com lista
  explícita — nunca `*`, porque as respostas carregam sessão. **Front que sobe sem a origem
  dele nessa lista abre em tela branca**: o erro fica no console do navegador e nada no
  servidor acusa. Em produção, `ENVIRONMENT=production` desliga o regex de localhost, que é
  a rede de segurança do desenvolvimento — não há a que recorrer.
- **O endereço da API não é compilado no bundle.** Vem de `API_URL` em tempo de execução (o
  `entrypoint.sh` de cada front escreve `config.js`), para o mesmo artefato servir qualquer
  ambiente.
- **As fontes moram no front** (`painel/public/fontes/`, `portal/public/fontes/`), que é
  quem as usa.

O `bff/` continua sendo o único que fala com os upstreams **em nome do app e do portal**:
nenhum dos dois conhece o endereço do meuWatt ou do meuPlano.

**Painel, portal e app repetem a mesma camada, e não há lugar compartilhado.** Não existe
workspace nem pacote comum: `portal/src/lib/api.ts` é uma reescrita do
`painel/src/lib/api.ts` (o cabeçalho de lá lista as diferenças deliberadas) e as fontes
estão duplicadas byte a byte. As divergências já começaram — o portal roda a regra 0 dentro
do `build` e o painel não. Ao corrigir defeito nessa camada, procure os irmãos antes de dar
o trabalho por encerrado.

**O painel são duas portas (o mesmo bundle, `PORTAO`), no modelo do dono (23/10/2026):**

- **adm-gs (plataforma)** — os clientes da plataforma são as EMPRESAS de O&M, e as empresas
  têm USUÁRIOS. Menu: **Empresas** (entrada; ao abrir uma, os usuários dela — gerentes,
  técnicos e donos —, as usinas e as últimas mensagens do bot), **Usuários** (o inverso:
  todo mundo, com a(s) empresa(s) de cada um, a equipe da plataforma marcada), **Usinas**
  (inventário por empresa, só leitura), **Log do bot**, e em Sistema WhatsApp, Rotas e
  Diagnóstico. ⛔ **O adm não tem token** (regra do dono): não há tela de conexão da
  plataforma nem de token de cliente aqui; da pessoa só se vê SE ela tem o token dela. O
  cliente nasce DENTRO da empresa (não existe mais "Novo cliente" solto, que criava órfão).
- **oem-gs (gerente da O&M)** — vê um passo abaixo: só os usuários e as usinas da empresa
  dele. Menu: Usinas, Usuários (cadastro puxado do meuPlano, token de cada pessoa, usinas,
  senha), **Bot do WhatsApp** (por pessoa: celular, token dela e as partes meuWatt/meuPlano/
  helper), Conexões (a conta DA EMPRESA nos produtos) e Vínculos.

**Um usuário em mais de uma empresa** (`gs_usuario_empresas`, como o `enterprise_employees`
do meuWatt): a conta tem a empresa de ORIGEM (`gs_users.empresa_id`, quem cuida de senha,
celular, tokens e bot) e pode ser também de outras, com o mesmo papel. As duas empresas a
listam (`services/empresas.contas_da_empresa`); a outra só concede as usinas DELA
(`clientes.definir_usinas(..., empresa_id=)`, que não toca nas da origem). O gerente de duas
empresas troca no oem-gs (`POST /api/sessao/empresa` → token com a claim `empresa`, conferida
a cada requisição por `gestor_empresa_atual`; `empresas.empresa_exigida` lê a empresa da
SESSÃO). Limite conhecido: o dono em duas empresas SEM token próprio lê, no aplicativo, com a
conta da empresa de origem — a usina da outra só tem dado com o token dele.

**O portal é o mesmo cliente, no navegador.** Mesma conta e mesmo login do app
(`POST /api/v1/auth/login`, com `apelido` e `senha`) — o BFF é que recusa a sessão de
painel nas rotas de cliente, porque ela carrega `escopo: "painel"`. Cada front guarda a
sessão sob a sua própria chave no `localStorage` (`gs_painel_sessao`, `gs_portal_sessao`),
para as duas conviverem no mesmo navegador sem uma derrubar a outra.

Leia [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) antes de mexer em qualquer coisa — é lá
que está o desenho, o modelo de autenticação e o mapa de qual dado vem de onde.

---

## 3. Como rodar

O caminho normal é o `dev.ps1` da raiz, que sobe cada parte na própria janela:

```powershell
.\dev.ps1 -Instalar    # primeira vez: venv, dependências, migrations
.\dev.ps1              # back + painel + portal
.\dev.ps1 -App         # + aplicativo (Expo)
.\dev.ps1 -Talk        # + servidor do Talk Solar
```

**Cada porta é de um dono, e nenhuma se repete.** Porta ocupada não dá erro claro: o
segundo servidor recusa subir, ou — pior — quem chama encontra o programa errado atendendo
no endereço certo.

| Porta | Quem | Onde está escrito |
|---|---|---|
| **8100** | back (API) · Swagger em `/docs` | `dev.ps1`, `Dockerfile` |
| **5180** | painel (gestor) | `painel/vite.config.ts` |
| **5181** | portal (cliente) | `portal/vite.config.ts` |
| **8081** | Metro, do Expo | padrão do Expo |

O 8110 é escolha registrada aqui: deixa a faixa `810x` livre para o back e não colide com
nenhuma das quatro acima. O Talk Solar veio do repositório do meuPlano documentado na
**8100** — lá ela estava livre, aqui é a do back —, e o `README.md` de lá foi corrigido
junto com esta tabela.

Em desenvolvimento os fronts chamam a API por **proxy do Vite**, não por CORS — a origem
fica a mesma e o caminho exercitado é o mesmo de produção (`/api/painel/...` no painel,
`/api/v1/...` no portal). Para reproduzir produção de verdade, `docker build` na pasta e
rodar com `API_URL` e `GS_CORS_ORIGENS`.

À mão, se precisar de uma parte só:

```powershell
# bff/ — o PYTHONPATH é obrigatório: os módulos são importados como `app.*`
$env:PYTHONPATH = "$PWD"
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8100
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m alembic upgrade head

# painel/ · portal/ · app/
npm run dev  ·  npm start  ·  npm run check  ·  npx tsc --noEmit

⚠ **O Talk Solar tem `PYTHONPATH` próprio, e o do BFF o quebra.** Os dois têm um pacote
chamado `app`: com o `PYTHONPATH` do BFF exportado, os testes de lá morrem em
`ImportError: cannot import name 'webhooks' from 'app'` — que parece defeito do projeto e
O banco é o Postgres do Supabase, configurado em `bff/.env` (não versionado; modelo em
`.env.example`). Duas armadilhas já resolvidas, que voltariam se alguém refizer a
configuração do zero:

- A senha vai **url-encoded** na `DATABASE_URL` (`#` → `%23`), senão chega truncada.
- A porta é a **5432** (session pooler), não a 6543: o transaction pooler não mantém a
  sessão entre comandos e o Alembic precisa disso.

O Talk Solar tem **banco próprio** (nove tabelas `ts_*`), com a sua `DATABASE_URL` em
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

### O vocabulário é traduzido UMA vez, no BFF — e cada coisa tem UM nome

Duas telas que traduzem por conta própria acabam discordando, e o cliente vê duas verdades
sobre o mesmo fato. Foi o que aconteceu na integração do portal (04/09/2026):

- **a mesma OS com três identidades.** `OrdemOut.numero` vinha de `container_numero`, que é o
  número do **contrato** — o drawer da pendência imprimia "OS #665", a lista chamava a mesma
  ordem de "OS 1016" e o cabeçalho do relatório escrevia "CONTRATO #665". O campo passou a se
  chamar `contrato_numero`, e a OS se identifica pelo `id`, que é o único número que ela tem
  no meuPlano;
- **código de banco na tela.** A aba Ordens traduzia a classificação com uma função própria e
  a de Relatórios imprimia `SERVICOS_ADICIONAIS`, com underscore. O cronograma mostrava
  `INSPECAO`, `ensaio` e `6/MONTH`. A tradução desceu para `manutencao.py`, onde já moram
  `SITUACAO` e `PARECER`, e sai pronta em `classificacao`, `categoria` e `periodicidade` —
  com o código cru ao lado (`*_codigo`) para auditoria, no mesmo par de `situacao`/`status`.

Regra: **rótulo que o cliente lê é dado da API.** A tela nunca monta o texto a partir do
código, e um mapa de tradução no front é dívida a mover para cá.

### Quem entra é o apelido, não o e-mail

A identidade de uma conta é o `apelido` (`gs_users.apelido`, único). O e-mail é contato —
opcional, não único — e serve para achar a conta da pessoa no meuWatt e no meuPlano.

O motivo é concreto e não deve ser desfeito por parecer estranho: **a mesma pessoa pode
ter duas contas aqui**, com poderes diferentes — foi assim que `renanmarquezini` (gestor
do sistema) e `renan.marquezini` (dono de usina) conviveram até 28/09/2026, quando o dono
juntou tudo numa conta só. A regra não caiu com o exemplo: dois clientes DIFERENTES podem
compartilhar o mesmo e-mail (sócios, casal, o contador de dois), e com o e-mail como chave
o segundo seria recusado como duplicado. Quem precisa de papéis separados hoje tem o
agrupamento de `gs_pessoas` — ver [`docs/MULTIEMPRESA.md`](docs/MULTIEMPRESA.md) §3.7.

Três consequências:

- Validação e normalização em `bff/app/core/apelido.py`, num lugar só. O front sugere
  (`sugerirApelido` em `painel/…/Novo.tsx`), o servidor decide.
- `svc.criar` recusa e-mail repetido **entre clientes** — dois clientes com o mesmo e-mail
  são quase sempre o mesmo cadastrado duas vezes. Cliente e gestor podem dividi-lo.
- A senha provisória é entregue com o apelido, nunca com o e-mail: mandar o e-mail junto
  convida o cliente a tentar entrar com ele, que é exatamente o que não funciona.

### Tela nova do painel nasce com uma ÁREA, nos dois lados

Quem do staff abre qual tela é `gs_painel_acessos`, uma linha por par (pessoa, área). O
catálogo mora em `bff/app/services/areas_painel.py`, a guarda é `exige_area` em
`core/security.py`, e quem concede é adm-gs → **Usuários** (só administrador).

Ao criar tela de painel, três lugares mudam juntos, e faltar um é silencioso:

- a **área no catálogo** do BFF — sem ela, `exige_area` estoura na importação, que é
  deliberado: uma área digitada errada seria uma porta que nem o administrador abre;
- a **guarda em cada rota** daquela tela (`Depends(EXIGE_X)`), no lugar de `gestor_atual`;
- o **item do menu** com a mesma chave, em `painel/src/shell/Layout.tsx`, e o `SoArea` na
  rota do `App.tsx`. Área no servidor sem item no menu é acesso concedido que não aparece.

Duas regras do desenho, que não devem ser "simplificadas":

- **Administrador abre tudo por perfil, e não tem linha gravada.** Se ele dependesse de
  concessão, um clique errado trancaria o painel para todo mundo e a saída seria linha de
  comando.
- **Usuários não é uma área concedível.** Continua em `administrador_atual`.
  Conceder "mexer em quem administra" a quem não administra é conceder tudo: a pessoa se
  promove a administrador no primeiro clique.

O front é conforto — esconde o que a conta não abre e explica o que falta. Quem decide é o
servidor, que confere a área a cada requisição.

### Toda rota de upstream entra no catálogo da sonda

`bff/app/services/sonda.py` lista as rotas do meuWatt e do meuPlano de que este sistema
depende, e o adm-gs (Rotas → *Sondar*) exercita uma a uma com a conexão da EMPRESA escolhida
(a plataforma não tem token).

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

O BFF lê os upstreams com um **token pessoal** por produto — o gerente cola o da EMPRESA em
oem-gs → Conexões e o de cada PESSOA em oem-gs → Usuários/Bot — e filtra pelo escopo
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

**E a micro usina, que não é um quarto formato.** `PlantLink.mw_micro_plant_id` casa uma
usina daqui (que existe no meuWatt e/ou no meuPlano) com uma micro usina do MICRO do
meuWatt — usinas dos portais dos fabricantes (Solis, Canadian, TSUN). Serve a UMA coisa: o
motor avisar **usina parada** dela (`motor._coletar_parada_micro`, tipo `parada`). É a
segunda leitura com credencial de serviço, e pelo mesmo motivo do catálogo: o MICRO só é
legível por administrador no meuWatt, nenhum token de cliente o enxerga. Se a conta de
serviço não for admin lá, a sonda pinta `mw.micro_*` de vermelho e o aviso cala.

### A empresa de O&M é o inquilino, e o recorte tem UM dono

Desde 28/09/2026 o sistema é multiempresa. O desenho inteiro — camadas, portões, migração
e os perigos — está em [`docs/MULTIEMPRESA.md`](docs/MULTIEMPRESA.md); o que não pode ser
esquecido ao mexer em qualquer consulta é isto:

- **Toda consulta que toca dado de empresa passa por `services/empresas.no_escopo`.** Uma
  que esqueça funciona perfeitamente em desenvolvimento, onde só existe uma empresa, e
  entrega o dado do vizinho no dia em que entra a segunda. Não dá erro, não dá log.
- **`empresa_id` nulo é conta da PLATAFORMA, nunca "todas as empresas".** Quem decide o
  alcance é o perfil, e o nulo é lido num lugar só — o mesmo módulo.
- **O prefixo diz de quem é a rota:** `/api/painel/*` é da plataforma, `/api/empresa/*` é
  do gerente da O&M, `/api/v1/*` é do dono de usina. O token de um portão é recusado nos
  outros, e a claim `escopo` é testada por PRESENÇA — portão novo nasce recusado.
- **Nenhuma rota de `/api/empresa/*` aceita `empresa_id` de quem chama.** O recorte sai da
  sessão. Parâmetro de empresa numa rota de empresa é a definição de vazamento.
- **Autenticar é uma coisa só:** `POST /api/painel/entrar` emite o token do portão certo
  conforme o perfil. Não nasce uma segunda porta de login.
- **Uma conta é um PAPEL; a pessoa é o agrupamento.** `gs_pessoas` junta as contas do mesmo
  humano (gestor da plataforma, gerente da O&M, dono de usina) só para a troca de papel
  sem sair e entrar — ela **não carrega poder**, e nenhuma guarda a consulta. A sessão
  continua sendo de uma conta, com um perfil e um escopo. **Descer é livre; subir para a
  plataforma pede a senha**: sem isso, uma sessão de app roubada viraria sessão de
  administrador sem ninguém saber nenhuma senha (`services/pessoas.py`).
- **A empresa daqui não é um terceiro cadastro: é o VÍNCULO.** O meuWatt tem
  `enterprises` e o meuPlano tem `tenants`, independentes um do outro — dá para contratar
  só a manutenção. `gs_empresas.mw_enterprise_id` e `.mp_tenant_id` dizem que as duas são
  a mesma, como `gs_plant_links` faz com usina. Empresa sem nenhum dos dois é fantasma.
- **Quem CASA a empresa com a do meuWatt/meuPlano é o gerente dela, não a plataforma.** A
  plataforma cadastra empresa e usuário e **vê tudo**, mas não tem token nos produtos —
  montar a lista com a credencial de serviço mostraria a carteira de quem a gerou. Por isso
  `/api/empresa/vinculos*`, com a empresa saindo da SESSÃO.
- **O cliente NÃO precisa de conta nos produtos.** O dono de usina costuma não ter, e
  exigir um token dele tornaria impossível cadastrar quem só existe aqui. `token_do_cliente`
  usa o dele quando houver e cai no da EMPRESA que o atende; nunca no da plataforma. O que
  ele vê continua sendo o concedido (`gs_user_plant_access`) — o token só diz com que
  credencial a leitura acontece, nunca o que ela devolve.
- **Cada empresa tem a conta DELA no meuWatt e no meuPlano, e a plataforma não tem
  nenhuma** (regra do dono, 23/10/2026: "adm não tem token"). `integracoes.obter` devolve
  só a linha da empresa — sem ela, não há leitura (o atalho para a credencial da plataforma
  acabou junto com a credencial; a migração `a8e4f2c61b90` limpou o token da linha sem
  empresa). O endereço dos produtos vem da configuração (`MEUWATT_API_URL`,
  `MEUPLANO_API_URL`). O MICRO (só admin lê no meuWatt) é lido com a conta da empresa dona
  da usina (`integracoes.micro_alertas_das_usinas`). O token de cada CLIENTE é dele.

#### O que a revisão de 30/09/2026 corrigiu, e não pode voltar

Cinco leituras independentes do código (becos, invariantes, isolamento, contrato
front×back e adversarial de autorização) acharam os mesmos pontos por caminhos diferentes.
Os testes de `tests/test_escalada_e_isolamento.py` são um por achado.

- ⛔ **Conta da PLATAFORMA não se administra pelo portão da empresa.** Conferir
  `empresa_id` não basta: `PUT /api/painel/empresas/{id}/carteira` gravava empresa em
  qualquer conta marcada, inclusive administrador — e aí `PATCH /api/empresa/usuarios/{id}`
  trocava a senha dele e o gerente entrava no painel da plataforma. Toda rota de
  `/api/empresa/*` que recebe id de conta passa por `_conta_da_empresa`, que recusa
  `pessoas.DA_PLATAFORMA` com **404 sem nome**. Em 24/10/2026 a `carteira` (e o
  `PUT /gerente/{apelido}`, o `POST /gerente` e o `/contas-livres`) SAÍRAM: nenhuma tela as
  usava, e elas furavam a trava do último gerente. Gente entra na empresa só pelas rotas de
  `/usuarios`; há um teste que falha se alguma delas voltar.
- ⛔ **Desativar a empresa PARA a leitura, em todos os portões.** A conferência de
  `Empresa.ativa` mora em `core/security.py` (`_empresa_ativa`), chamada por
  `usuario_atual` e `gestor_empresa_atual` — ali passam todas as requisições
  autenticadas, inclusive as de token emitido antes da desativação. Antes só
  `painel.entrar` conferia, e `auth.login` emitia token de app de 30 dias para a mesma
  conta: desativar escondia o botão e não parava nada.
- **Usina SEM dono deixou de existir** (migration `a1b4e7c20d36`). A herdada que uma
  empresa já concede é ADOTADA por ela ao salvar; a que ninguém dela recebe continua 404
  sem nome. A frase "Esta usina ainda não é da sua empresa" foi apagada do código: ela
  aparecia no clique mais comum da tela e mandava "trazer em Usinas", onde a usina não
  estava — o catálogo sai do upstream, e uma herdada só do meuPlano não tem `mw_slug`.
- **Concessão a GERENTE foi apagada e é recusada.** Ele vê a carteira da empresa por ser
  gerente; a concessão era o caminho por onde a herdada chegava à tela dele.
- **Identificador do corpo é conferido contra o SEU token** (`_o_seu_token_enxerga`), e só
  quando ENTRA — renomear, ligar e desligar não pagam ida ao upstream, e um produto fora
  do ar não trava o gerente. Sem isso, um `mw_slug` digitado à mão ocupava o identificador
  da usina de outra empresa, que passava a receber "já pertence a outra empresa" ao trazer
  a própria.
- **`integracoes.listar` recebe a empresa.** Era `select(Integracao)` inteiro chaveado por
  produto: a última linha vencia por acaso, e o aplicativo de um cliente da empresa A lia
  o estado da ponte da B. Numa listagem, a trava do atalho vira "não configurada" em vez
  de derrubar a tela.
- **A tela de Conexões não entrega QUEM gerou a credencial da plataforma** — nome, e-mail
  e prefixo são identidade de outra conta. O estado, sim: é o que a empresa precisa saber.
- **Modal de concessão: UM só.** A tela de Clientes tinha uma segunda cópia que abria com
  tudo desmarcado e gravava a lista vazia — a gravação é substituição total, então o
  primeiro "Salvar" revogava todas as usinas do cliente. Agora as duas telas usam
  `UsinasDoUsuario`, que carrega o que a pessoa já recebe antes de desenhar.
- **Cliente criado pelo painel da plataforma nasce com a empresa que o atende.** Sem ela a
  conta é órfã: nenhum gerente a enxerga e as telas dela vêm vazias para sempre.

### Nada de "chips" para selecionar opção

Regra herdada do meuPlano e válida aqui: filtro, tipo, categoria, status — tudo é lista
suspensa pesquisável ou controle segmentado. Nunca uma fileira de botõezinhos pill.
Exceções: tags informativas read-only e botões de ação.

### Números em pt-BR

Ponto de milhar, vírgula decimal (`13.800`, `29,87`). Use os helpers de
`app/src/lib/format.ts`. Não exiba número cru.

### Offline primeiro nas leituras — e a tela sempre diz de quando é o número

Usina tem sinal ruim. Toda tela de leitura passa por `fetchWithCache`: mostra o cache
imediatamente e atualiza quando a rede responde. `401`/`403` nunca é mascarado pelo cache.

**Cache na tela sem carimbo é o mesmo defeito da REGRA 0, com outra roupa.** O carimbo de
horário só aparecia quando a rede FALHAVA; no caminho comum — rede lenta, que é o da
usina — a tela desenhava o número antigo sem marca nenhuma e o trocava quando a resposta
chegava. Quem abria o app lia potência de dez minutos atrás como a de agora e via o valor
saltar sozinho três segundos depois. Medido em 19/09/2026: `GET /api/v1/home` leva 2–3 s
contra a produção, e o piso é o `monitoring/current` do meuWatt (1,4–2,5 s por usina, já
em paralelo). Não existe versão disso que abra instantânea com dado fresco — o que dá
para fazer é não mentir no intervalo.

Três peças, e as três moram em `app/src/lib/cache.ts` e `components/base.tsx`:

- **`frescor`** sai de toda leitura e vai para `Tela` — `origem` (rede · cache · vazio),
  `hora`, `idadeMs`, `vencido`, `atualizando`, `offline`;
- **`FaixaFrescor`** desenha a faixa fina do alto: "Dados de 16:17 · atualizando…",
  "Sem conexão — mostrando dados de 16:17" ou "Atualizado agora", que dura dois segundos.
  O terceiro estado existe para a troca ter causa visível;
- **`vencido` esconde o número perecível.** Passado `validadeMs` (15 min por padrão), a
  potência de agora e a energia de hoje viram esqueleto: carimbar não basta quando o
  número descreve outro dia, porque quem abre com pressa lê o valor e não a faixa. O que
  é registro — fatura, OS, cronograma, relatório — passa `validadeMs: Infinity` e nunca
  some.

Tela de leitura nova nasce passando `frescor={frescor}` para a `Tela`. Sem isso ela volta
a apresentar cache como se fosse leitura ao vivo, que é exatamente o defeito acima.

### PDF é sempre in-app

Exiba pelo `PdfViewer` (pdf.js em WebView), com "Enviar cópia" no share sheet nativo. Nunca
entregue o arquivo a um app externo direto — no Android isso dá tela preta silenciosa.

### Cor só significa estado

Seis tons, definidos em `app/src/theme/tokens.ts`. Não invente cor de status nova.

### Toda tela desenha os quatro estados

Carregando (skeleton, nunca spinner solto), vazio, erro, e a faixa de frescor dizendo de
quando é o que está na tela — ver acima.

---

## 6. Pendências conhecidas

**Expo Go exige a build do SDK 57.** Cada build do Expo Go embute uma única versão de SDK.
A da loja pode estar atrás; a build certa sai de [expo.dev/go](https://expo.dev/go).

**O endereço de produção é o do Railway, não o domínio próprio.** Conferido por probe em
04/09/2026:

| | Endereço | Estado |
|---|---|---|
| back (API) | `https://gestao-solar-production.up.railway.app` | **no ar** — `/health` → 200 |
| painel | `https://gestaosolar.up.railway.app` | **no ar** — 200 |
| portal (cliente) | `https://appgestao-production-15cb.up.railway.app` | **no ar** — 200, servindo `config.js` |
| Talk Solar | — | serviço ainda não criado |

O `api-gestaosolar.meuwatt.com.br` que o `eas.json` trazia responde **404** — é um domínio
que nunca foi apontado, e apontá-lo é trabalho pendente no DNS.

✅ **O portal do cliente foi publicado em 04/09/2026** e é o **terceiro serviço** do projeto
(`appgestao`), separado do painel de gestão por decisão do dono: gestão vai para
`adm.gestao.solar` e o cliente para `app.gestao.solar` (os dois domínios ainda a comprar e
apontar). O endereço que o código declarava (`appgestao.up.railway.app`) nunca existiu — o
domínio real que o Railway gerou é `appgestao-production-15cb.up.railway.app`.

⚠ **O serviço `appgestao` não está ligado ao GitHub**, então **não há deploy automático no
push**: cada mudança do portal exige um `railway up` à mão. Quem tiver acesso de conta deve
conectar o repositório e apagar este aviso. Enquanto isso, **um push que mexe só em `portal/`
não muda nada em produção** — e a armadilha não dá erro: o site continua no ar, com o código
antigo. Pior, o BFF SOBE no push (é o único serviço ligado ao GitHub), então numa mudança que
atravessa os dois o servidor anda e a tela não.

**Publicar o portal, em 12/09/2026 — três armadilhas, nesta ordem:**

1. **NÃO exporte `RAILWAY_TOKEN`.** A máquina já tem login de conta
   (`railway whoami` → `Paulo Renan Marquezini`), e é ele que enxerga os quatro serviços do
   projeto. O token do `.env.txt` é de escopo menor: com ele exportado, `railway status`
   mostra só `Gestao-Solar` e `gs-teste-permissao` — o `front` (painel) e o `appgestao`
   (portal) **somem da lista**, e `railway list`/`railway whoami` respondem `Unauthorized`.
   Isso parece "o portal está em outro projeto" e não está: está no mesmo, escondido pelo
   escopo do token.

2. **O `railway up` novo (CLI 5.45.7) sobe o REPOSITÓRIO INTEIRO, não a pasta atual.** Era
   assim que o portal ia ao ar (`cd portal && railway up`), e deixou de funcionar: o contexto
   passa a ter a raiz no topo, o `Dockerfile` do portal não está lá, o builder cai no
   **Railpack** e o deploy morre em ~25 s com `railpack prepare exited with an error` — o log
   mostra o builder listando `bff/`, `painel/`, `docs/`… O `Root Directory` do serviço não
   salva: ele vale para build vindo do GitHub, não para upload do CLI, em que o arquivo
   enviado É o contexto. Passar a pasta como argumento também não resolve
   (`railway up portal` → `prefix not found`).

   O que funciona: **montar o contexto fora do repositório** e subir de lá —

   ```bash
   CTX=/tmp/ctx-portal && rm -rf $CTX && mkdir -p $CTX
   cd "/c/Dev/Gestao Solar/portal"
   tar --exclude=node_modules --exclude=dist -cf - . | (cd $CTX && tar -xf -)
   cd $CTX && railway up --project ae0386b7-5b51-44fe-bb74-d41ac885903a \
       --service appgestao --environment production --detach
   ```

   Fora de um repositório git, o CLI sobe a pasta e o `Dockerfile` volta a ficar na raiz do
   contexto — que é o que o cabeçalho do `portal/Dockerfile` sempre disse que ele precisa.

3. **Confirme por ARQUIVO NOVO, nunca por status.** O SPA devolve 200 em qualquer caminho, e
   o deploy falho deixa a versão antiga no ar respondendo tudo. A prova é um arquivo que só
   existe na versão nova, conferido pelo tipo e pelo tamanho, com um caminho inexistente ao
   lado como controle:

   ```bash
   P=https://appgestao-production-15cb.up.railway.app
   curl -s -o /dev/null -w '%{http_code} %{content_type} %{size_download}
' $P/favicon.svg
   #   200 image/svg+xml 1966   ← o arquivo
   curl -s -o /dev/null -w '%{http_code} %{content_type} %{size_download}
' $P/marca/nao-existe.svg
   #   200 text/html 1602       ← o controle: 200 aqui é só o index.html
   ```

**Como provar o portal AO VIVO, sem a senha do dono.** Uma tela do portal só responde com
sessão: sem ela toda rota devolve 401, e o SPA devolve 200 em qualquer caminho — o que faz um
`curl` na rota parecer prova quando não é (200 ali é só o `index.html`). O caminho que funciona:

```python
# de dentro de bff/, com PYTHONPATH=.
from app.core.security import criar_token
token, expira = criar_token(2)          # usuário 2 = a conta do dono, cliente, 7 usinas
```

Para a API, `Authorization: Bearer <token>`. Para a TELA, Playwright (o chromium já está no venv
do bff) com a sessão gravada **antes do primeiro render** — o store a lê de forma síncrona, então
injetar depois do `goto` da rota final não adianta:

```python
pag.goto(f'{PORTAL}/entrar', wait_until='domcontentloaded')
pag.evaluate("([k,v]) => localStorage.setItem(k,v)",
             ['gs_portal_sessao', json.dumps({'token': token, 'expira_em': expira.isoformat(),
                                              'usuario': <GET /api/v1/auth/eu>})])
```

O valor do token nunca é impresso: ele nasce e morre dentro do processo. Sem esse caminho, a
conferência de uma entrega no portal para na porta — foi o que aconteceu numa leva de 04/09/2026,
em que os gates automatizados passaram e ninguém tinha aberto a tela.

Três armadilhas do deploy, todas já pagas:

- **`railway up` roda da raiz do repositório**, nunca de dentro de `bff/`. O serviço tem
  *Root Directory* em `bff/`, então subir de lá faz o Railway procurar `bff/bff/Dockerfile`
  e o deploy falha — sem derrubar o que está no ar, o que torna a falha fácil de não notar:
  o `/health` continua respondendo 200 pela versão antiga.
- **`railwayConfigFile` é ajuste de painel do Railway, invisível no repositório**, e o
  caminho dele é relativo à **raiz** (`portal/railway.json`), não ao Root Directory. Sem
  ele, o builder cai no Railpack, **ignora o `Dockerfile`** e o `entrypoint.sh` nunca
  escreve o `config.js`: o front sobe sem `window.__GS_API__`, chama a si mesmo, recebe o
  próprio HTML e o console diz `Unexpected token '<'` — longe da causa. A tabela de deploy
  do [`README.md`](README.md#deploy) traz o valor de cada serviço.
- ⛔ **NÃO exporte o token do Railway para publicar.** Esta linha já disse o contrário, e
  custou uma investigação inteira em 12/09/2026. O `.env.txt` traz um token de escopo
  estreito: exportado em `RAILWAY_TOKEN`, ele **esconde metade do projeto** — `railway
  status` passa a listar só `Gestao-Solar` e `gs-teste-permissao`, o `front` (painel) e o
  `appgestao` (portal) somem, e `railway list`/`railway whoami` respondem `Unauthorized`.
  O sintoma engana com perfeição: parece que os dois serviços estão em OUTRO projeto e que
  a máquina não tem credencial para eles. Estão no mesmo projeto, e ela tem.

  **A máquina já está logada na conta** (`railway whoami` → `Paulo Renan Marquezini`), e é
  esse login que enxerga os quatro serviços. Então, para qualquer coisa de Railway:
  `unset RAILWAY_TOKEN` primeiro, e só use o token do `.env.txt` se algum comando pedir
  explicitamente um escopo de projeto. Ver o passo a passo de publicação em §6.

**A carteira depende de duas ondas para não abrir em cinza.** `GET /api/v1/resumo` compõe
energia, paradas, cronograma, ordens e pendências de TODAS as usinas: contra os upstreams
reais isso levava 22 s, e a Visão geral tem um esqueleto só — a primeira tela do portal
ficava perto de meio minuto cinza, enquanto as outras respondiam entre 1 e 8 s. A rota
passou a aceitar `?blocos=energia|manutencao|tudo` e a tela faz as duas leituras em
paralelo, desenhando com a energia. **Ausente = tudo**, então qualquer chamador antigo
continua funcionando. Se uma onda nova precisar entrar, ela entra em `TODOS_OS_BLOCOS` —
bloco desconhecido é 400 com a frase, nunca coluna vazia sem explicação.

**A lentidão do relatório de manutenção era o pooler, não a consulta.** O gate
`validate_relatorio_manutencao.py` mede o tempo numa usina real: com o pooler do Supabase
saturado (teto de 15 clientes em modo sessão), cada uma das 12 idas custava ~1,5 s e o
relatório levava 18–23 s; com o pooler livre, as MESMAS 12 idas custam ~200 ms e o total é
2,4 s. Antes de investigar consulta lenta, confira quantas sessões estão abertas contra o
banco — o erro `EMAXCONNSESSION` aparece nos logs quando o teto estoura.

**Não há CI: nada roda os gates além de quem desenvolve.** Não existe `.github/` neste
repositório. Os únicos automáticos são os que moram dentro do `docker build`, e eles não
cobrem todo mundo: o `build` do portal é `tsc --noEmit && node scripts/regra0.mjs && vite
build`, o do painel é só `tsc -b && vite build` — o painel não passa pela regra 0. Um push
com tipo quebrado não é barrado em lugar nenhum: vira um deploy que falha no build e deixa
a versão antiga no ar, em silêncio. Front novo nasce com o `regra0.mjs` no `build`, ou
nasce sem gate.

**O healthcheck do painel mente, e o do portal não.** `painel/railway.json` aponta para
`/`, que devolve o `index.html` mesmo com o bundle quebrado — o Railway declara saudável um
painel que não abre. O portal corrigiu isso com `location = /saude { return 200 "ok"; }` no
nginx e `healthcheckPath: "/saude"`. Ao criar serviço de front novo, copie o **portal**;
copiar o painel (que é o que está no ar, e por isso o modelo natural) reintroduz o defeito.

**Testar contra o BFF local a partir do celular não funciona sem preparo.** O firewall do
Windows não tem regra para a porta 8100 — o `python.exe` do venv não é o `node.exe`, que já
tem permissão e por isso o Metro na 8081 funciona —, e o Android recusa HTTP em claro num
build release.

**O aplicativo deixou de ser maquete — e o `docs/TELAS.md` ainda não acompanhou.** O texto
que estava aqui dizia que só o login e a lista de Usinas liam do BFF, e que as demais telas
desenhavam `src/features/exemplo.ts`: **esse arquivo não existe.** Conferido em 04/09/2026,
os módulos de `app/src/features/` leem do BFF por `fetchWithCache` (`app/src/lib/cache.ts`,
e não o `lib/offline.ts` que a documentação citava), nas chaves `home`, `plants`,
`plants/{id}`, `billing`, `documents`, `notifications`, `manutencao`,
`manutencao/cronograma-{id}`, `manutencao/ordem-{id}` e `me/permissoes`.

O que **de fato** está desatualizado é o inventário de telas: a árvore de rotas do
`docs/TELAS.md` lista sete que não existem (`(tabs)/financeiro`, `usina/[id]/geracao`,
`usina/[id]/mapa`, `usina/[id]/manutencao`, `paradas/[usinaId]`, `pdf`, `config`) e não
lista quatro que existem (`(tabs)/manutencao`, `cronograma/[usinaId]`, `documento/[id]`,
`tarefa/[id]`). Reescrevê-lo contra as rotas reais é trabalho pendente, anotado lá.

---

## 7. O que NÃO existe (não invente)

- Não há gateway de pagamento. As mensalidades são cadastradas à mão no BFF.
- Não há endpoint `/equipment/{id}/history` no mw-api. O histórico de paradas do
  equipamento, quando for montado, sai do detector novo (`/shadow-breakdowns/queue`, linhas
  pelo `slot_id`) — nunca do coletor antigo (`breakdowns/range`).
- Não há vínculo automático entre a usina do meuWatt e a do meuPlano. O vínculo é a tabela
  `gs_plant_links`, preenchida à mão.
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
| `meuPlano` | `_TETO_NIVEL_CLIENTE` respeitar `nivel_acesso` (teto 2) | pendente — bloqueia L2 no assistente |

As duas pontes estão conectadas e testadas contra produção: `api.meuwatt.com.br` e
`meuplano.up.railway.app`.

**Paradas vêm do detector NOVO do meuWatt** (`GET /shadow-breakdowns/queue?plantId=`, o da
tela de Paradas de lá), desde 24/10/2026 — `bff/app/api/v1/paradas.py`. O coletor antigo
(`/plants/{slug}/breakdowns/range`, que respondia 500 em todas as usinas) saiu do cliente e
da sonda; regra da casa: não volta. O detector pede o id NUMÉRICO da usina (vem de
`GET /plants/{slug}`); só a linha `material` é parada; e a `run` da resposta diz que período
ele analisou — "não analisado" sai nulo, nunca "nenhuma parada". A régua é UMA
(`paradas.ler_do_detector`): a tela e o bot do WhatsApp (`assistente_geracao.paradas`) contam a
mesma parada, a mesma perda (nula onde o detector não fez a conta) e o mesmo "não analisado".

---

## 9. Git e deploy

Trabalhar em `main`. Repositório: `https://github.com/plataforma-meuwatt/Gestao-Solar`.

**Sempre commitar, sempre publicar, sempre mandar o OTA.** Não deixar trabalho parado no
working tree. Um push que muda o `app/` sem OTA correspondente não chegou em ninguém.

### ⛔ Desde 22/10/2026 a produção é o COOLIFY da KingHost, não o Railway

Tudo o que este arquivo diz sobre Railway abaixo é HISTÓRICO (o projeto do Railway vai ser
apagado). Projeto "Gestão Solar" no Coolify (`https://coolify.squeezefit.com.br`), quatro
apps com Dockerfile, e **push na `main` publica os quatro sozinho** (webhook do GitHub,
`watch_paths` por pasta — acabou o `railway up` à mão do portal e do painel):

| App | Pasta | Endereço |
|---|---|---|
| `gestaosolar-api` | `bff/` | `https://api-gs.meuplano.solar` |
| `gestaosolar-portal` | `portal/` | `https://gs.meuplano.solar` — o CLIENTE (dono de usina) |
| `gestaosolar-painel` | `painel/`, `PORTAO=plataforma` | `https://adm-gs.meuplano.solar` — SÓ a administração da plataforma |
| `gestaosolar-adm-oem` | `painel/`, `PORTAO=empresa` | `https://oem-gs.meuplano.solar` — SÓ o gerente (e o técnico) da O&M |
| `gestaosolar-whatsapp` | `whatsapp/` | `https://xkbj6oglr7ge4ggl9wptuoai.177.153.20.214.sslip.io` (callback da Meta: `/webhook`) |

Status do deploy: API do Coolify (`/root/bin/coolify-api.sh GET /deployments/<uuid>` na VM
srvclaude). Variáveis: `/root/bin/coolify-envs.py`. O banco continua o Supabase de antes.
**O assistente do WhatsApp é do Gestão Solar (o guardião)** — `bff/app/services/assistente.py`.
O número casa com UMA conta daqui (`gs_users.telefone`); sem conta, não há conversa. Um
orquestrador (DeepSeek, `DEEPSEEK_API_KEY`) usa as ferramentas de GERAÇÃO
(`assistente_geracao.py`: API do meuWatt, só usinas concedidas) e a de MANUTENÇÃO (o assistente
do meuPlano, falando como a pessoa). ⛔ **Regra do dono (23/10/2026): cada um usa o bot com o
SEU token** (`gs_vinculos_produto`, `so_proprio=True`) — nunca o da empresa nem o da plataforma.
O administrador da plataforma não usa o bot (não tem token); o do Renan responde à conta de
gerente dele (`renan.marquezini`). Liberar uma parte exige o token dela (`cadastro.liberar_bot`),
e liberada sem token fica parada (`User.bot_ativo`). **O helper** (`assistente_helper.py`,
porta `/api/bot/*` do mw-modbus-helper pelo túnel `HELPER_BOT_URL`, chave `HELPER_BOT_CHAVE`):
leitura volta na hora; AÇÃO vira proposta e só executa com a **SENHA DE ATUAÇÃO** da pessoa
(pedido do dono, 24/10/2026: "o bot peça senha para qualquer ação que envolva atuação —
desligar, ligar, gravar; ler não precisa"). `gs_users.senha_atuacao_hash`: 6 a 8 números,
definida pelo gerente em oem-gs → Bot do WhatsApp, nunca a de login. Conferida antes do modelo
(`assistente_helper.confirmar_por_mensagem`: a IA não vê a senha nem tem ferramenta de
confirmar), uma vez; 5 erros com ação esperando bloqueiam por 15 min, e sem ação esperando a
resposta é a mesma com senha certa ou errada (não vira oráculo). A mensagem da senha sai do log,
do histórico e do gateway (`POST /interno/mensagens/{id}/ocultar`, que limpa também a entrega
crua da Meta). Ao helper vai `confirmado_por: "pin"` (o contrato dele: quem pede a senha é o
chamador). O ajuste em massa do helper (2.26.0) volta item por item com a conferência da
leitura final; a confirmação espera até 190 s, e sem resposta é "PODE ter chegado", nunca
"falhou"; comando único volta com o MOTIVO da falha e a releitura do equipamento. A ferramenta
`usina_helper` tem `metodo` (GET é leitura no helper: `/api/devices`, `/api/healthcheck/state?id=`
— POST ali virava "escrita", pedia senha e dava 404) e respeita o recorte de usinas do GS
(`usinas_do_usuario`), inclusive filtrando o `/api/registry/plants`. Com ação esperando, a senha
escrita numa frase também é tentativa. **Desde a 8ª avaliação: SÓ a mensagem que é APENAS a
senha executa** ("482913", "senha 482-913" — espaço, ponto e hífen entre dígitos são juntados
antes). Toda outra mensagem DESARMA a ação esperando, antes de "limpar" e de áudio/imagem
(o bloco promete "qualquer outra mensagem cancela", e "não faça! senha 482913" executava).
Numa FRASE, o que pode ser a senha é conferido e SÓ a senha some ("[senha oculta]", com aviso à
pessoa e à IA): UC, protocolo e IP seguem legíveis (avaliação 9). Um leitor
só de números (`assistente_helper.NUMERO`, avaliações 10 e 11) acha a senha escrita de qualquer
jeito: colada em pontuação ("Senha:482913", "senha/482913"), em grupos com espaço (inclusive o
não separável) ou UMA pontuação ("482 913", "482/913", "482 9 13"), soletrada ("4 8 2 9 1 3",
"4, 8, 2, 9, 1, 3" — o ditado por voz), por extenso ("quatro oito dois…") e em dígitos de
largura cheia. Data, IP e o que a senha não pode ser (repetido, em sequência) nem são
conferidos; "vírgula + espaço" separa itens de lista, não grupos. Sozinha, qualquer dessas
formas é tentativa. Até 3 números distintos por mensagem (os de depois de "senha" primeiro) e
20 por pessoa por hora; o que passa disso vira "[número oculto]" sem conferir. Frase nunca conta erro nem bloqueia; passado o
teto da hora, todo candidato vira "[número oculto]" sem conferir (o oráculo para ali). O
gateway guarda a frase SEM a senha (não a mensagem inteira). A tentativa (a mensagem que é só o
número, com até 3 grupos separados por espaço, ponto, vírgula, hífen ou sublinhado) é conferida
com `to_thread`; cada erro conta; 5 em 15 min bloqueiam. O número que ganha conta leva para ela
as mensagens que mandou antes (`cadastro.adotar_mensagens`, quando o celular MUDA — dentro da
gravação de quem chama; as que já estavam soltas passaram uma vez na migração `c6d8e0f2a4b6`). O log mascara "senha … é/:/= X",
"senha … para X", "PIN 1234" e o NÚMERO inteiro (3 dígitos ou mais) depois de senha/pin, com
qualquer pontuação ou "do cadeado" no meio ("senha,482913", "pin 482 913", "senha do cadeado
3262"; "código" e "combinação" só de portão/porta/cadeado/cofre — "código de erro 2043",
"PIN 3 do conector" e "combinação de strings 12" ficam). Os marcadores do bot ("[senha oculta]")
nunca são mascarados. Na hora da senha, a parte do bot da ação é conferida de novo. O
bloco diz a hora-limite ("até as 14:32"). **A senha só vale DEPOIS de o resumo chegar**
(avaliação 10: "desliga o 13" e a senha logo atrás executavam um resumo que a pessoa nunca
leu): `_atender` marca a saída do bloco (`assistente_helper.mostrada`, só se o gateway disse
`ok`; se não saiu, a ação é desarmada) na hora do BANCO (`_agora_do_banco` — o relógio da
KingHost anda ~17 s atrás e a senha é comparada com a hora da Meta), e a senha que entrou na
fila do número antes disso — ou cuja hora da Meta é anterior — recebe "não vale, mande outra
vez" e a ação continua esperando. Senha depois do prazo recebe "venceu às HH:MM" (a mesma frase
certa ou errada). **O gateway avisa o BFF na HORA** em que grava a mensagem (antes, só a
varredura de 60 s avisava: até um minuto de espera); a varredura ficou como rede de segurança,
com uma trava para os dois não avisarem a mesma mensagem, e o BFF ignora a entrega repetida
(`assistente._ATENDIDAS`). Reação (👍 no resumo), figurinha e avisos do WhatsApp são ignorados:
não respondem nem cancelam a ação. **Áudio:** a nota de voz é baixada pelo gateway
(`GET /interno/mensagens/{id}/midia`, a coluna `wa_mensagens.midia` guarda o id da Meta) e
transcrita pelo meuPlano (`/assistant/transcribe`, o Whisper do app de campo) com o token do
meuPlano DA PESSOA; o bot devolve "🎙️ _o que entendeu_" e segue como texto — a senha dita em voz
alta vale e nunca volta em claro. Arquivo e imagem ainda não são lidos (a resposta diz o nome).
Pedido ao meuPlano que fale em ASSINATURA/certificado digital vira ação (SIM) ANTES de sair
(lá a ferramenta de PDF assina dentro de uma leitura, sem proposta). A pergunta sobre o ESTADO
("a OS 1638 já foi assinada?") é leitura; o pedido com "?" ("pode assinar a OS?", "me manda o
PDF assinado?") continua pedindo o SIM — na dúvida, é pedido (`_pede_assinatura`). Pedido ao helper com IP/host de equipamento (SmartLogger, ABS, datalogger) tem de
trazer a usina junto: sem ela, o helper confere o IP contra TODAS as usinas do token. O recorte de usinas do bot é `usinas_do_bot`: o do
aplicativo e, para o TÉCNICO, a carteira da empresa (é ele quem vai a campo); leitura que não
nomeia a usina é filtrada por ele (`_CAMPOS_DE_USINA`: `api_slug`, `slug`, `plant_id` e `plant` —
o da trilha `/api/audit/list`, que passava inteira; avaliação 15). Qualquer outra
mensagem DESARMA a ação (menos a afirmativa ambígua com o SIM esperando, abaixo): "não", "cancela", "não quero" SOZINHOS respondem "Cancelado" pelo
sistema — no passo 2 de um pedido, dizendo o que os passos de antes JÁ fizeram (`_o_que_ficou`;
"Nada foi feito" escondia a OS 1843, avaliação 15); "Não, o técnico é o Diogo" é correção — a
ação cai e a frase vai à IA (`so_cancela`; avaliação 12: a correção se perdia), que ouve, só
naquela mensagem, que a ação «…» foi cancelada por ela: não diz que vai fazê-la, propõe de novo
(`CANCELADA_PARA_A_IA`; avaliação 16: respondia "vou fechar" com "(foi cancelada)" embaixo). UMA ação por
mensagem (a 2ª chamada ouve "esperando o Sim" na do meuPlano — "a senha" só na do helper),
e o texto que a pessoa confirma é do SISTEMA (`bloco_da_proposta`, ao pé da resposta; a prévia do meuPlano vai até 15 linhas e, passando disso, "… e mais N — veja a lista inteira no meuPlano antes de confirmar" — avaliação 20: num APAGAR de 20 itens, 5 sumiam calados). O log
mascara "senha/PIN/código … X" que o meuPlano revelar. Selo "Helper alcançável" no adm e no oem:
`ferramentas` (só a chave do chamador) + `POST /api/bot/rede`, respondida pelo filtro do túnel no
srvclaude com a idade do contato do wg0 (exige a mesma chave de chamador) — VPN parada há mais
de 5 min deixa o selo vermelho; a causa curta vem da API (`helper_rotulo`: "VPN das usinas parada",
"VPN das usinas não conferida" ou "Helper fora do ar"), no selo e na linha de cada pessoa do Bot do WhatsApp — "helper fora do ar"
quando era a VPN mandava procurar no lugar errado (avaliação 17). Gateway e helper são conferidos ao
mesmo tempo. **A ação do meuPlano confirma com SIM, não com a senha** (dono, 24/10/2026:
o bot cobrava a senha de atuação para concluir uma OS — senha é para EQUIPAMENTO, "desligar,
ligar, gravar"): a proposta do assistente de lá (criar/concluir OS, lançar o dia, lembrete)
espera o SIM da pessoa (`Pendente.confirmacao = "sim"`, conferido pelo sistema, valendo só
depois de o resumo sair). O resumo vai com os botões **Sim / Não** (`botoes_sim_nao`; gateway
sem botões → texto), cada um com o CÓDIGO do resumo no id ("sim:<código>", `Pendente.codigo`): o
toque num resumo antigo — o WhatsApp mantém os botões — recebe "Esse botão é de um resumo antigo
— nada foi feito" e não mexe na ação de agora; sem ação esperando (venceu, ou o deploy apagou a
memória), "Essa confirmação não vale mais…"; e o Não de um resumo vencido ouve que venceu, como o
Sim (`helper.resposta_ao_botao`; o gateway guarda o id em `wa_mensagens.botao`, migração
`e2b4d6f8a0c1`); o toque de novo num resumo JÁ confirmado ouve "Essa ação já foi confirmada e não
roda de novo. O que houve: …" (`_CONFIRMADAS`; avaliação 15: ouvia "Nada foi feito — peça de
novo" logo abaixo do ✅); e o toque no Sim/Não do resumo que a PRÓPRIA mensagem da pessoa derrubou
diz isso, com o trecho dela já sem a senha (`_CANCELADAS`; avaliação 16: ouvia "o pedido venceu ou
o bot foi atualizado"). Só a mensagem de CIÊNCIA ("valeu", "obrigado", "ok, aguardo", 👍 — lista
fechada `_CIENCIA`) que saiu do celular ANTES de o resumo chegar não derruba a ação
(`helper.mandada_antes_do_resumo`); "cancela", "não" e a correção ("não, é o 12") derrubam como
qualquer mensagem (avaliação 15: a senha seguinte desligava o 13). Confirma o toque, "sim" ou uma afirmativa curta
("Sim, pode criar", "Pode sim", "De acordo", "tá certo", "Tudo certo", "Ótimo", "Opa, pode",
"Valeu, pode fazer", "Simm", "👍", "👍🏽") — pergunta nunca confirma, "Sim, mas troque o técnico" é
correção. Depois da afirmativa, só palavra neutra ou do RESUMO ("Sim, pode criar a OS de
Ibitinga"), e NÚMERO só o do resumo: "Pode fechar a 1640" não confirma "Fechar a OS 1638"
(avaliação 15). Palavra de parar, negar, esperar ou restringir (`_PARAR`: "para", "não", "mas",
"espera", "só", "sem"…) nunca confirma, nem quando está no resumo ("Mover a OS 1638 PARA
concluída"; e "Pode, só a 1638" fecharia a 1640 de "Fechar só a OS 1638 e a 1640"); a de TROCAR
("trocar", "mudar", "outro" — `_TROCA`) só quando está no próprio resumo ("Pode trocar" para
"Trocar o equipamento…"); e nenhuma entra nas listas de neutras e de ciência — há teste ("Ok, para
tudo!" executava — avaliação 14). A afirmativa de mais de uma palavra ("Sim, com certeza", "Sem
problema", "Sem dúvida", "Claro que sim", "Sim senhor", "Por favor") é lista FECHADA e vale para
qualquer resumo (`_EXPRESSOES_SIM`; avaliação 16: cancelavam, e "com certeza" só confirmava resumo
com "com"; avaliação 17: também "Não tem problema", "Vai em frente", "Sim, só isso", "Top",
"Boa", "Massa", "Yes"; avaliação 18: "Concordo", "Vamos lá", "Por mim pode", "Manda brasa"). Só o
PRÓPRIO VERBO da ação confirma ("Fecha", "Feche aí", "Confirmo o fechamento" para "Fechar a OS
1638…"): os verbos das ações do meuPlano (o primeiro de cada resumo, conferidos nas prévias de lá),
com sinônimos e substantivos, lista fechada (`_FAMILIAS` → `_VERBOS`; "abrir a OS" é criá-la), casados
só com o PRIMEIRO verbo do resumo. Verbo de OUTRA ação NUNCA confirma — nem é palavra neutra: "Pode
criar" confirmava "APAGAR 3 itens" e "Pode abrir a OS" fechava a 1638 (avaliação 18); agora o sistema
pergunta de novo, e um teste falha se um verbo de ação entrar nas listas neutras. Na ação de VÁRIOS
alvos (uma contagem de 2 ou mais no resumo: "APAGAR 3 item(ns)", "Apagar 2 ligação(ões)") ou
destrutiva (apagar, remover, desinstalar, transferir), alvo citado só confirma se cobre TODOS os
itens (as linhas da prévia vão em `itens`; cada linha precisa de uma palavra que só ela tem —
`_cobre_todos`): "Apaga o 3" para INV-1, INV-2 e INV-3, "Pode editar em Ibitinga" com nós em duas
usinas e "Sim, o Michel" para "…por Michel…, Diogo…" são dúvida, nunca SIM, mesmo a palavra estando
no resumo (avaliação 20: a contagem e a usina contavam como citação inteira). "Todos", "os três"/"os
3" (a contagem, ou o número de pessoas listadas) e o plural do item ("os inversores") confirmam; palavra
neutra e o "s" de "dia(s)" não contam como citação parcial (avaliação 20: "Sim, é isso", "Aprovado" e
"s" viravam dúvida na proposta real). "Bem...", "Bom...", "Hmm" e 🙏 sozinhos também são dúvida
(avaliação 19: confirmavam). A CURTA (até 4 palavras) que começa como
afirmativa sem negação nem correção e SEM assunto novo, mas não é um SIM limpo ("Sim, pode deixar",
"Ok, vou ver" — `_SEM_ASSUNTO`), não confirma nem derruba: o SISTEMA pergunta de novo, com os botões,
sem ir à IA (`pergunta_de_novo`); com assunto novo ("Ok, e Pereiras", "Pode mandar o PDF") ou mais
longa, é outro pedido — derruba e vai à IA, que fica sabendo, em vez de o pedido ser engolido
(avaliação 17). Limite: o sim com outro pedido junto ("sim, pode fechar e me manda o PDF") derruba — o bloco diz "um não, uma correção ou outro assunto cancela; na dúvida,
pergunto de novo" (`_resposta_ao_resumo`, `e_sim`/`responde_sim`). Com o SIM esperando, o NÚMERO sozinho é conversa (a
UC, o protocolo), para quem tem senha e para quem não tem (`e_tentativa`, decidida antes de a ação
cair): não conta erro nem bloqueia, e se for a senha some como numa frase, com o limite por hora —
a senha não confirma ação do meuPlano. E confirmada o BFF chama o
`/assistant/apply` de lá com o token da pessoa (10 min); a conversa vai junto ao meuPlano, que
é sem estado. Lá é uma proposta por vez: depois de cada SIM o bot SEGUE sozinho para o próximo
passo do mesmo pedido — se o meuPlano responder esse passo em TEXTO ("aqui está a proposta… confirmando
os dois, eu fecho a 1638"), o bot pede de novo, uma vez, a ação pela ferramenta (ou a pergunta do dado
que falta); vindo texto de novo, diz que o passo não ficou pronto, que nada espera o Sim e o que já foi
feito, e repassa o texto de lá INTEIRO — como pergunta, sem ⚠️, quando é pergunta ("qual a data de
término?"); senão com ⚠️ e o log em erro (uso real de 24/10/2026, avaliação 19: o texto era repassado e a
1638 ficou sem fechar). "Pronto", "Não há mais passos", "Tudo feito", "Nada mais" são o fim
(`_FIM_DO_PEDIDO`), e o passo feito proposto de novo DEPOIS do pedido de novo vira "O meuPlano não
trouxe outro passo depois deste… Se faltava algo, peça de novo" (avaliação 20: sumia calado) (`_seguir_no_meuplano` — "crie a OS e conclua a 1638" são dois SIM, e o
pedido inteiro da pessoa vai junto: a IA pode ter mandado só uma parte, e o resto sumia calado —
avaliação 15; a proposta seguinte com a MESMA ação e os mesmos argumentos da que acabou de rodar
não é oferecida, é o fim do pedido — `Pendente.acao`, avaliação 16), com o
"digitando…" de volta logo depois do ✅ (o próximo passo leva de 20 a 65 s lá). **O resultado de
uma ação confirmada sempre chega:** falhar ao gravar a conversa não derruba o turno (`_guardar`), e
erro depois de a ação rodar nunca vira "Tente de novo" (repetir criaria a OS em dobro) — vai o
desfecho dela, ou "PODE ter sido feita — confira" se a execução estourou no meio
(`Pendente.desfecho`, avaliação 15). A proposta guarda o
pedido nas palavras da PESSOA e o que dele já foi feito (`Pendente.pedido`/`feitos`): passo que falha
diz "Do seu pedido «…», antes disso já foi feito: …. O resto não foi feito" — nunca a instrução que o bot mandou
ao meuPlano —, e próximo passo que não vem (erro ou demora de lá) vira "⚠️ Não consegui pedir ao
meuPlano o resto do seu pedido…", com o log em erro (avaliação 13). O
assistente de lá diz se as tarefas da OS estão feitas e a FECHA quando estão (`situacao_os`,
`fechar_os`, meuPlano 93a19ea1; com tarefa pendente, a ficha se conclui por
`registrar_execucao_tarefa` antes). **Lá, toda ferramenta do assistente confere o escopo de quem
pede** (meuPlano 689768da, avaliação 14: uma pessoa de escopo restrito criava OS e relato numa
usina de outra empresa): `escopo.assert_args_no_escopo` antes de toda ferramenta do chat e no
apply, que também re-roda a prévia (a recusa sai em frase de gente); listar OS e pessoas não
atravessam empresas. **O meuPlano sabe QUEM pergunta pelo token** (meuPlano
0e06a465): o assistente de lá resolvia o solicitante só por JWT, o `mp_pat_` virava anônimo e
anônimo enxerga TODAS as usinas de todas as empresas; agora valem o escopo, o nível e a
audiência da pessoa, como na web (inclusive revelar senha de equipamento a quem tem nível para
isso). Ensaiado em 24/10/2026 contra o código real do meuPlano numa cópia local do banco, sem
rede: criar a OS → SIM → fechar a 1638 (recusa com o que falta) → concluir a ficha → fechar. **Erro 5xx do apply não é "nada foi feito":** lá a rota grava
antes do passo que quebra (a OS 1843 ficou criada e vazia, 24/10/2026), então a resposta é
"PODE ter sido gravada em parte — confira", o resto do pedido é lembrado e o log marca erro; o
texto da exceção não vai à pessoa. 4xx continua "recusou… Nada foi feito". **Empresa
desligada (ou conta sem empresa) cala o bot**, como os outros portões; **meuWatt fora só tira a
geração** (a lista de usinas dele fica 5 min em memória). **O token é da pessoa:** a mesma pessoa de
lá não serve a duas contas, e o token de outra pessoa não troca a ligação em silêncio
(`vinculos.conectar`); a tela mostra de quem é cada token. O aplicativo continua
caindo no token da empresa; o bot, não. **Cada mensagem vira uma linha em `gs_bot_registros`**
(quem, empresa, resultado, pergunta, resposta, ferramentas, duração, erro — inclusive número
sem cadastro): adm-gs → Log do bot, e o recorte da empresa no oem-gs → Bot do WhatsApp. A
conversa é da CONTA: se o número muda de conta, o histórico anterior não entra. **"Bot ouvindo"**
(`GET /interno/saude` do gateway → `/api/painel/whatsapp/saude` e `/api/empresa/bot/saude`):
entregas da Meta paradas há mais de 2 min e mensagens que o BFF não recebeu — em 10/2026 a
configuração estava toda verde e o bot surdo havia um dia. Mensagem com mais de 2 h fica no log
como `atrasada`, sem resposta. ⛔ **A suíte do BFF não pode abrir o `.env`:** ele aponta para a
produção, e o `conftest.py` troca o `DATABASE_URL` antes de importar o app (um teste deixava
um "oi" falso no Log do bot a cada rodada) e gera a `GS_ENCRYPTION_KEY` da suíte (três testes do
bot só passavam com a de produção — avaliação 15). Responde, manda PDF e gráfico
pelo gateway (`/interno/conteudo`, `/interno/digitando`) — **pela rede interna do Docker**
(`WHATSAPP_GATEWAY_URL=http://gestaosolar-whatsapp:8120`; e o gateway chama a API em
`BFF_URL=http://gestaosolar-api:8100`), por apelido fixo de rede no Coolify
(`custom_network_aliases`). Antes ia pelo DNS público do sslip.io, que falhou em 24/10 e
calou o bot por minutos; o envio também tenta de novo quando a conexão nem abre. O `ENCAMINHAR_URLS` do gateway (cópia
crua da entrega para outro sistema) existe, mas está VAZIO: dois bots no mesmo número
responderiam em dobro.

### As credenciais já estão na máquina — não peça login

`C:\dev\Gestao Solar\.env.txt` (fora do git, coberto por `.env.*` no `.gitignore`) guarda o
**token do Expo** e o **token do Railway**. Não existe motivo para pedir `eas login` ao Renan,
e `eas whoami` dizendo "Not logged in" **não** significa que falta credencial: significa que
faltou exportar a variável.

⚠ **Isso vale para o Expo. Para o Railway, é o contrário: NÃO exporte o token.** A máquina
está logada na conta, e o token do `.env.txt` tem escopo menor — exportá-lo faz dois dos
quatro serviços desaparecerem da listagem e produz um `Unauthorized` que parece falta de
permissão da conta. Ver a armadilha inteira em §6.

Carregar sem estampar o valor no terminal:

```bash
export EXPO_TOKEN=$(sed -n 's/^Expo:[[:space:]]*//p' "/c/dev/Gestao Solar/.env.txt" | tr -d '\r')
```

O arquivo é `.txt` e mora na raiz — é por isso que uma busca por `.env` não acha, e é por isso
que o `rg`/Grep passa batido: sendo ignorado pelo git, ele fica invisível na busca padrão.

### BFF, painel e portal → Railway, no push

**O push para `main` dispara o deploy — mas só do que está ligado ao GitHub**, e hoje isso é
o **back**, com o Root Directory dele. Leva ~1–2 min.

⛔ **O PAINEL TAMBÉM NÃO SOBE NO PUSH.** Conferido em 16/09/2026: o commit `430f99a` mexeu em
`painel/src/` e o serviço `front` não moveu um dedo — a lista de deploys dele parava em
**11/09**, e a produção seguia servindo o bundle antigo. A falha é silenciosa do mesmo jeito
do portal: o site continua no ar, com o código de semanas atrás, e o healthcheck (`/`, que
devolve o `index.html`) declara tudo saudável. Publicar é um comando à mão:

```bash
railway redeploy --service front --environment production \
    --project ae0386b7-5b51-44fe-bb74-d41ac885903a --from-source -y
```

`--from-source` é o que importa: sem ele o comando reimplanta a MESMA imagem, e o bundle
antigo volta ao ar parecendo deploy novo. Conferir depois pelo ARQUIVO, nunca pelo status —
`curl -s <painel>/ | grep -o '/assets/[^"]*\.js'` e procurar no bundle uma string que só
existe na versão nova.

⛔ **O GATEWAY DO WHATSAPP TAMBÉM NÃO SOBE NO PUSH.** O serviço `whatsapp` foi criado pela
API em 16/09/2026 apontando para este repositório, mas **sem gatilho de push** — a API de
projeto não cria o gatilho, e a mutation que o criaria exige token de conta. Mesma armadilha
silenciosa do portal: um push que mexe só em `whatsapp/` deixa a produção com o código
antigo, e o `/health` responde 200 o tempo todo. Publicar é à mão:

```bash
railway redeploy --service whatsapp --environment production \
    --project ae0386b7-5b51-44fe-bb74-d41ac885903a --from-source -y
```

E conferir por PROBE, nunca pelo status: `curl <gateway>/health` deve trazer
`{"status":"ok","ambiente":"production"}`, e `GET /interno/credenciais` sem cabeçalho deve
dar **401** — se der 200, a porta interna está aberta e isso é grave.

⛔ **DOIS SERVIÇOS NO MESMO BANCO PRECISAM DE `version_table` PRÓPRIA.** O gateway divide o
Supabase com o BFF, e o Alembic grava a revisão atual em `alembic_version` — uma tabela só,
no schema `public`. O primeiro deploy do gateway morreu em `Can't locate revision identified
by 'c41d9b6e7a05'`, e a mensagem engana: parece migration corrompida, e é a cadeia do BFF
que ele encontrou lá. Se tivesse conseguido escrever, o próximo `alembic upgrade` do BFF
veria a revisão DELE como desconhecida — e aí quem para de subir é o serviço que atende o
aplicativo. O gateway usa `alembic_version_gateway` (`whatsapp/alembic/env.py`); serviço
novo neste banco nasce com a sua.

⛔ **O portal NÃO entra nesse caminho.** O serviço `appgestao` existe e está no ar, e não está
conectado ao repositório: um push que mexe só em `portal/` **não muda nada em produção**, e a
falha é silenciosa — o site continua respondendo 200, com o código antigo. Publicar o portal é
um `railway up` à mão, e ele tem três armadilhas próprias: estão em §6, com o comando pronto.

E a ordem inverte sozinha aqui: numa mudança que atravessa BFF e portal, **o servidor sobe no
push e a tela não sobe nenhuma vez** até alguém rodar o `railway up`. Como o BFF só ganha
campo e nunca tira, o portal antigo não quebra — mas a tela nova fica esperando um deploy que
ninguém deu.

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
