# Talk Solar — entrega

**Para:** o programador que vai continuar
**De:** a construção feita dentro do repositório do meuPlano, já transplantada para cá
(04/09/2026)
**Em uma frase:** o mensageiro está de pé e testado e já mora aqui; falta subir num serviço
próprio com o banco do Gestão Solar e plugar o meuWatt e o Gestão Solar — o meuPlano já está
plugado e serve de molde.

---

## 1. O que é isto

**Talk Solar, by Gestão Solar** — o mensageiro da equipe de O&M: conversa em tempo real, com
foto e arquivo, **ligada às usinas, OSs e tarefas** dos sistemas que a empresa já usa.

Nasceu dentro do repositório do meuPlano porque foi ali que se descobriu o que faltava (o
mensageiro antigo existia e tinha **zero mensagens** — não subia imagem e não falava do
trabalho). Mas **não é parte do meuPlano**: nenhuma linha daqui importa nada de lá.

### A decisão que define tudo

> A Talk Solar **não tem cadastro de usuário, não tem senha e não sabe o que é uma usina.**

Ela **empresta** a identidade e o vocabulário de cada sistema integrado, por HTTP:

```
   meuPlano ────┐                          ┌── (1) de quem é este token?
   meuWatt  ────┼──►  TALK SOLAR  ─────────┼── (2) o que este usuário pode citar?
Gestão Solar ───┘   (banco próprio)        └── (3) como se chama este alvo?

             ◄──────── webhooks assinados: "houve conversa na OS 1016"
```

Três sistemas com login próprio **não podem virar quatro**: duplicar identidade cria a pergunta
"qual senha é a certa?" e o dia em que alguém desligado no meuPlano continua conversando.

---

## 2. O que está PRONTO

| | |
|---|---|
| **Contrato da API** | `docs/API.md` — escrito e implementado |
| **Servidor** | FastAPI, banco próprio, 9 tabelas `ts_*`, migration única (`alembic upgrade head`) |
| Sessão emprestada (JWT + refresh revogável) | ✅ o app fica aberto o dia inteiro sem pedir senha |
| Canais, DM, canal-de-um-alvo (idempotente) | ✅ |
| Mensagens, threads, editar, apagar (marcando) | ✅ |
| **Anexos** (imagem com miniatura, arquivo) | ✅ mensagem e arquivo na MESMA requisição |
| **Citação** de usina/OS/tarefa + pergunta inversa | ✅ rótulo congelado |
| **Tempo real** (WebSocket) | ✅ com a limitação de 1 instância documentada em `app/hub.py` |
| **Webhooks** saída (HMAC + 4 reenvios) e entrada | ✅ |
| **Teste de contrato** ponta a ponta | ✅ **32/32**, com um sistema falso — não depende de nada no ar |
| **Integração de referência (meuPlano)** | ✅ `integracoes/meuplano/talk.py.exemplo` — receptor **corrigido** (INT-1), copiável |
| **App de PC** (Electron) | ✅ bandeja, notificação nativa, colar imagem, citar — `npm test` **12/12** |
| Railway | ⚠ `railway.json` + `Procfile` existem, mas fora do padrão do repositório — ver §3.2 |

### Rodar agora, na sua máquina

```bash
cd talksolar/server
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH= python testes/test_contrato.py     # 32 OK / 0 falhas — sem banco e sem rede

cd ../desktop
npm test                                        # 12 OK / 0 falhas
```

> ⚠ **`PYTHONPATH` VAZIO no teste do servidor.** Quem trabalha nos dois repositórios na mesma
> máquina costuma ter `PYTHONPATH=…\meuPlano\backend` no ambiente; com ele, o teste morre em
> `ImportError: cannot import name 'webhooks' from 'app'`. É colisão do pacote `app` — parece
> defeito do projeto e não é.

O teste sobe um **sistema falso** que implementa o contrato. É o melhor lugar para entender o
desenho em 10 minutos.

---

## 3. O que FALTA — a sua parte

### 3.1 Tirar daqui e levar para o repositório do Gestão Solar — ✅ FEITO

A pasta saiu do meuPlano e está em `<Gestão Solar>/talksolar/` (minúsculo: lá a pasta é o nome
do serviço). Nada quebrou — não havia import cruzado —, e os gates foram re-executados **no
destino**, que é a única prova de que a cópia é funcional e não só numericamente igual.

O que veio junto:

- `server/` — o serviço;
- `desktop/` — o app de PC;
- `docs/` — este arquivo, o contrato e a receita de integração;
- `integracoes/meuplano/talk.py.exemplo` — o molde (mantenha: é a referência para os outros
  dois). É uma cópia **datada** (meuPlano, 04/09/2026, sobre o commit `0f2007d9`), não um gêmeo:
  com os dois em repositórios diferentes, nenhum gate consegue mais conferir esse par, e cópia
  que se acredita sincronizada sem nada a verificar é pior que cópia declaradamente velha. Quem
  mexer na integração mexe na **fonte viva** — meuPlano, `backend/app/api/v1/talk.py` — e regera
  esta, trocando o carimbo do cabeçalho.

Do lado do meuPlano, o que fica é só o router de integração
(`backend/app/api/v1/talk.py`) — ele é do meuPlano, não da Talk Solar.

### 3.2 Criar o serviço no Railway

Serviço **novo**, separado (sobe e cai sem afetar nada). Root Directory = `talksolar/server`.

O `railway.json` que veio do meuPlano manda:

```
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

> ⚠ **Três coisas nele fogem do padrão deste repositório**, e vale acertar antes de subir:
>
> 1. `builder: NIXPACKS` — os outros três serviços (`bff`, `painel`, `portal`) usam
>    **Dockerfile**.
> 2. o `startCommand` **não tem `exec`** antes do `uvicorn`: sem ele o shell continua sendo o
>    PID 1 e o uvicorn é morto sem encerrar as requisições em voo. O `bff/Dockerfile` documenta
>    essa mesma armadilha e a resolve com `exec` — copie de lá.
> 3. `healthcheckPath: "/saude"` — os outros usam `/health`. Alinhe um dos dois lados.
>
> E o ajuste que **não** mora em arquivo nenhum: no painel do Railway, além do Root Directory,
> defina **`railwayConfigFile = talksolar/server/railway.json`** (esse caminho é relativo à raiz
> do repositório, ao contrário do `dockerfilePath`). Sem ele o builder cai no Railpack e ignora
> a configuração — e a falha não é um deploy vermelho, é um serviço que sobe errado.

Variáveis (o modelo está em `server/.env.exemplo`):

| Variável | O quê |
|---|---|
| `DATABASE_URL` | O Postgres do **Supabase do Gestão Solar** — use o pooler `:6543` |
| `TALK_JWT_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `TALK_STORAGE` | `supabase` |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | do projeto do Gestão Solar |
| `TALK_BUCKET` | `talksolar` (**crie o bucket**) |
| `TALK_CORS` | os domínios que abrem a Talk Solar pelo navegador |

> ⚠ **Não deixe `TALK_STORAGE=local` no Railway**: o disco do contêiner é efêmero e os anexos
> somem a cada deploy. O `/saude` avisa isso — abra depois de subir.

`GET /saude` responde o que ainda falta configurar. Um `/saude` que só diz "ok" serve para o
balanceador e para mais ninguém.

### 3.3 Banco

As tabelas têm prefixo `ts_` e **convivem** com as do Gestão Solar no mesmo banco. Uma migration
só (`0001_base`) cria as nove. Rodar `alembic upgrade head` num banco que já tem as tabelas do
Gestão Solar é seguro — ela não toca em nada que não seja `ts_*`.

### 3.4 Integrar o meuWatt e o Gestão Solar

Receita em **[INTEGRACAO.md](INTEGRACAO.md)**: copiar `integracoes/meuplano/talk.py.exemplo`, trocar
três coisas (como valida token, o que é citável, onde o recado aparece) e rodar
`scripts/integrar_sistema.py`. Meio dia por sistema.

**Duas partes exigem atenção**, e as duas estão marcadas no código com ⛔:

1. **O recorte de visibilidade dos alvos citáveis é do sistema**, não da Talk Solar. Esquecer
   isso faz o chat virar a porta dos fundos para os dados dos outros.
2. **Sistema multiempresa precisa de um app POR EMPRESA** — canal de alvo nasce público e todo
   canal público é do app inteiro. O porquê, com o vazamento concreto, está em
   [API.md §1](API.md); a decisão tem de ser tomada **antes** do `integrar_sistema.py`, porque
   depois significa migrar canais entre apps e não existe rota para isso.

E um detalhe de dedo que já mordeu: **confirme o host com `curl` antes de registrar**. A URL vai
para `ts_apps` no banco de produção. O host vivo do meuPlano é `meuplano.up.railway.app`;
`meuplano-production.up.railway.app`, que aparecia escrito em vários lugares, responde 404 da
borda do Railway.

### 3.5 Pendências menores (declaradas, não escondidas)

| | |
|---|---|
| **Ícone do app de PC** | **não existe** — `Assets/icone.ico` está declarado em quatro lugares do `desktop/package.json` e a pasta não existe. `npm run dist` FALHA hoje (o `npm test` não depende dele e passa 12/12) |
| **Servidor de atualização** | o app publica em `…/talksolar` (`desktop/package.json`) e o comentário de `electron/main.js` fala em `…/conversa`; **os dois respondem 404** hoje. A decisão tomada é um **servidor de releases próprio** (`talksolar-updates`, volume próprio), e não uma subpasta no do "meuPlano Ferramentas": lá o diretório é plano e o `latest.yml` é único — publicar na raiz faria todo PC com o app de campo instalado baixar o mensageiro. Fixe o mesmo caminho nos dois lugares e crie o serviço |
| **Histórico infinito** | a tela carrega as últimas 50 mensagens; rolar para trás usa `?antes=` (o servidor já aceita), falta a tela chamar |
| **Uma instância só** | o WebSocket e o worker de webhook guardam estado em memória. Está escrito em `app/hub.py` e `app/webhooks.py` **o que fazer no dia em que houver duas** (Redis/`LISTEN NOTIFY`, e `FOR UPDATE SKIP LOCKED`) |
| **Reações e busca** | existiam no protótipo dentro do meuPlano e não foram trazidas — decisão consciente para o contrato nascer pequeno |

---

## 4. Coisas que eu decidiria de novo do mesmo jeito (e por quê)

Estão espalhadas em comentário no código, mas as cinco que mais importam:

1. **Identidade emprestada.** Nenhuma senha aqui dentro. É o que permite desligar alguém em UM
   lugar.
2. **`tipo`+`id` opacos.** A Talk Solar não sabe o que é uma usina — e por isso integrar o
   quarto sistema não mexe no schema.
3. **Rótulo e URL CONGELADOS na citação.** A conversa de ontem mostra o nome de ontem, e a
   citação sobrevive ao registro apagado.
4. **Anexo e mensagem na mesma requisição.** No caminho de dois passos, a falha no meio deixa
   arquivo órfão no storage ou mensagem vazia na conversa.
5. **404 e não 403 para o que é alheio.** Quem não pode ver não deve nem descobrir que existe.

E uma que **não** é uma decisão de arquitetura, mas de honestidade: o `/saude` e o `ENTREGA.md`
dizem o que está mal configurado e o que falta. Software entregue com pendência escondida custa
o dobro no mês seguinte.

---

## 5. Ordem sugerida

1. `PYTHONPATH= python testes/test_contrato.py` — entender o desenho (10 min).
2. ~~Mover a pasta para o repositório do Gestão Solar~~ — **feito** (§3.1).
3. Subir o serviço no Railway com o banco do Gestão Solar; conferir `/saude` (§3.2).
4. Rodar `integrar_sistema.py` — **uma vez por empresa**, se o sistema for multiempresa (§3.4) —
   e provar a ponta a ponta com o app de PC.
5. Integrar o Gestão Solar (o sistema que você conhece melhor) — meio dia.
6. Integrar o meuWatt.
7. Só então: ícone (sem ele não há instalador), servidor de releases, histórico infinito, reações.

Qualquer decisão que parecer estranha provavelmente tem um comentário no código dizendo por que
ela é assim. Se não tiver, é bug de documentação — e vale corrigir no mesmo commit.
