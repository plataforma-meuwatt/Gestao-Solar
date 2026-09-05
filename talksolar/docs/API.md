# Talk Solar — contrato da API

> Este documento é **a fonte da verdade do contrato**. O servidor implementa o que está aqui;
> os sistemas integrados (meuPlano, meuWatt, Gestão Solar) implementam a contraparte. Se código
> e documento divergirem, alinhe o código — e corrija este arquivo no mesmo commit.
>
> ⚠ **Este arquivo já mentiu uma vez, e custou caro.** Até 04/09/2026 ele mandava usar os
> cabeçalhos `X-Conversa-Secret` / `X-Conversa-Evento` / `X-Conversa-Entrega` /
> `X-Conversa-Assinatura` e falava de uma tabela `cv_users` — nomes do projeto quando ele ainda
> se chamava "Conversa". O código nunca usou nenhum deles: são `X-Talk-*` e `ts_usuarios`. Quem
> integrasse seguindo este documento levaria **401 em todas as direções** e iria procurar o
> defeito no lugar errado, porque o `INTEGRACAO.md` estava certo e a divergência era invisível.
> Daí a regra desta revisão: **todo cabeçalho, nome de tabela e código de status citado abaixo
> aparece literalmente no código, com o arquivo e a linha ao lado.**

Base: `https://<host-do-servico>/v1`
Formato: JSON UTF-8. Datas em ISO-8601 UTC. Erros: `{"detail": "..."}` com o status HTTP.

Como conferir qualquer afirmação deste arquivo:

```bash
grep -rn "X-Talk-" server/app/          # cabeçalhos
grep -rn "__tablename__" server/app/models.py
grep -rn "HTTPException(" server/app/   # todos os status que o servidor levanta
```

---

## 0. O desenho em uma página

A Talk Solar **não tem cadastro de usuário, não tem senha e não conhece usina nem OS**. Ela é um
mensageiro puro. Tudo o que é do domínio de cada sistema fica no sistema — e a Talk Solar
pergunta quando precisa.

```
   meuPlano ────┐                       ┌──── (1) quem é o dono deste token?
   meuWatt  ────┼──►  TALK SOLAR  ──────┼──── (2) o que este usuário pode citar?
Gestão Solar ───┘   (banco próprio)     └──── (3) como se chama este alvo?

            ◄────────  webhooks: "houve mensagem", "citaram a OS 1016"
```

Por que assim, e não com um banco de usuários próprio: **três sistemas com login próprio não
podem virar quatro**. Duplicar identidade cria a pergunta "qual senha é a certa?" e o dia em que
alguém é desligado no meuPlano e continua conversando. A Talk Solar **empresta** a identidade de
quem a hospeda.

Cada sistema integrado implementa **três endpoints** (§5) e opcionalmente **recebe webhooks**
(§6). É todo o trabalho de integrar um sistema novo.

---

## 1. Isolamento: **um app da Talk Solar por EMPRESA** ⛔

A única fronteira que a Talk Solar garante sozinha é **entre apps**:

```python
# server/app/main.py:128 — _pode_ver
if c.app_id != u.app_id:
    return False                          # sistemas diferentes não se enxergam
```

E logo abaixo, na mesma função (`main.py:130`), está a outra metade da regra:

```python
if c.tipo == "publico":
    return True                           # todo canal público é do APP inteiro
```

O canal criado por `POST /v1/canais/do-alvo` nasce **público** (`main.py:376`) — de propósito: o
histórico do trabalho é patrimônio do time, não do grupinho. A consequência, porém, é direta:
**dentro de um mesmo app, qualquer pessoa lê a conversa de qualquer alvo.**

Isso obriga uma decisão de quem integra um sistema **multiempresa**. O meuPlano é um: a mesma
instalação atende a Splendor e a Marcheng, e a regra número um de lá é que uma empresa não pode
ver *nada* da outra. Se o meuPlano entrasse como **um app só**, a conversa da OS da Splendor
ficaria legível por gente da Marcheng — e ninguém perceberia, porque a tela do chat não parece
uma tela do meuPlano.

> **A regra: uma empresa = um app = um segredo.**
>
> ```bash
> python scripts/integrar_sistema.py meuplano-1 "meuPlano · Splendor" https://…/api/v1/talk
> python scripts/integrar_sistema.py meuplano-7 "meuPlano · Marcheng" https://…/api/v1/talk
> ```
>
> As duas linhas apontam para **as mesmas URLs**. O que muda é o segredo — e **é o segredo que
> diz de quem é a chamada**. O sistema hospedeiro guarda o mapa `slug → (segredo, empresa)` e,
> em cada uma das quatro rotas, recorta pela empresa daquele segredo:
>
> | Rota | O que a empresa do segredo decide |
> |---|---|
> | `/identidade` | recusa (401) o token de quem não tem vínculo com aquela empresa |
> | `/refs/buscar` | só devolve alvos daquela empresa |
> | `/refs/label` | idem — e é por isso que "conversar sobre isto" dá 404 num alvo de fora |
> | `/webhook` | recusa (404) o recado cujo alvo não é daquela empresa |

No meuPlano isso está implementado em `backend/app/api/v1/talk.py` (`_empresa_do_segredo`,
`_app_da_assinatura`, `_usinas_visiveis`, `_alvo_e_da_empresa`) e o mapa vem da variável de
ambiente `TALK_SECRETS`:

```jsonc
{"meuplano-1": {"segredo": "…", "empresa_id": 1},
 "meuplano-7": {"segredo": "…", "empresa_id": 7}}
```

**Sistema de empresa única** (um cliente por instalação) não precisa de nada disto: um app só, e
o `empresa_id` fica de fora. O que **não** existe é meio-termo — servir sem recorte com vários
apps configurados é o vazamento de volta.

> Nota para quem vai integrar o **Gestão Solar**: decida isto **antes** de rodar o
> `integrar_sistema.py`. Trocar de "um app" para "um app por empresa" depois que houver conversa
> significa migrar canais entre apps, e não existe rota para isso.

---

## 2. Autenticação

### 2.1 Abrir sessão — `POST /v1/sessao`

O cliente (app de PC, aba do navegador, celular) já está logado no sistema hospedeiro e tem o
token DELE. Ele troca esse token por uma sessão da Talk Solar.

```jsonc
// pedido
{ "app": "meuplano-1", "token": "<token do sistema hospedeiro>",
  "dispositivo": "Talk Solar · PC do Renan" }

// resposta 200
{ "token": "<jwt da Talk Solar, 12 h>",
  "refresh": "<token longo e revogável>",
  "usuario": { "id": 42, "nome": "Renan", "email": "…", "app": "meuplano-1",
               "externo_id": "179" } }
```

O servidor chama o **`identidade_url`** do app (§5.1) para saber de quem é o token. Token
inválido lá → `401` aqui. O usuário é criado/atualizado em **`ts_usuarios`**
(`server/app/models.py:68`) na primeira vez — espelho, não cadastro: nome e e-mail vêm do
sistema e são **reescritos a cada entrada** (`integracao.espelhar_usuario`).

`app` é o **slug do registro**, não o nome do produto. Num sistema multiempresa (§1) é o slug
daquela empresa, e o cliente descobre qual usar perguntando ao próprio sistema hospedeiro — não
o escreva no código do cliente.

### 2.2 Renovar — `POST /v1/sessao/refresh`

```jsonc
{ "refresh": "…" }  →  { "token": "…", "usuario": { "id": 42, "nome": "Renan" } }
```

O cliente chama isto no `401` e **repete a chamada, uma vez só**. O app fica aberto o dia
inteiro; sem renovação, todo mundo é deslogado no meio da tarde.

O refresh vale `TALK_SESSAO_DIAS` (90) **de inatividade** — parado mais que isso, ele é revogado
na hora do uso e a resposta é `401 "Sessão expirada por inatividade"` (`sessao.py:51-53`). Em PC
compartilhado, sessão esquecida é sessão de mais alguém.

> **Quem é multiempresa não deve usar o refresh longo.** Ele sobrevive ao desligamento da pessoa
> no sistema hospedeiro por até 90 dias. O cliente web do meuPlano recusa o refresh de propósito
> e **re-deriva** a sessão a partir do token do meuPlano quando toma 401: assim, desligar alguém
> lá o desliga da conversa dentro do TTL do token de lá (12 h), não em três meses.

### 2.3 Encerrar — `POST /v1/sessao/logout`

`{ "refresh": "…" }` → `204`. Revoga só aquele aparelho.

### 2.4 Usando

`Authorization: Bearer <jwt da Talk Solar>` em tudo. O WebSocket recebe o token na URL
(`?token=…`) porque a API de WebSocket do navegador não aceita cabeçalho — é limitação da
plataforma, não escolha (`sessao.usuario_do_ws`).

---

## 3. Conversa

| Método | Rota | O que faz |
|---|---|---|
| GET | `/v1/canais` | Canais do usuário + os públicos do app, com não lidas e prévia |
| POST | `/v1/canais` | Cria canal `{nome, tipo: publico\|privado, topico, membros[]}` |
| POST | `/v1/canais/dm` | Abre/retoma conversa direta `{usuarios: [id]}` |
| POST | `/v1/canais/do-alvo` | **Idempotente**: o canal daquela usina/OS `{tipo, id}` |
| POST | `/v1/canais/{id}/entrar` · `/sair` | Entrar/sair (os dois são POST, `204`) |
| POST | `/v1/canais/{id}/lido` | `{ultima_id}` — é daqui que sai o "não lido" |
| GET | `/v1/canais/{id}/mensagens?antes=&limite=&thread_de=` | Histórico (mais novo por último) |
| POST | `/v1/canais/{id}/mensagens` | Envia texto `{conteudo, responde_a, refs[], mencoes[]}` |
| POST | `/v1/canais/{id}/mensagens/anexos` | **multipart**: mensagem + arquivos num pedido só |
| PATCH/DELETE | `/v1/mensagens/{id}` | Editar / apagar (apagar MARCA, não some) |
| GET | `/v1/pessoas` | Quem existe para conversar (do mesmo app) |
| GET | `/v1/refs/buscar?q=` | Repassa a busca ao sistema (§5.2) |
| GET | `/v1/refs/{tipo}/{id}/mensagens` | "O que já se falou sobre isto" |
| POST | `/v1/webhooks/{app_slug}` | O sistema avisa a Talk Solar (§7) — sem sessão, com HMAC |
| GET | `/v1/admin/webhooks/entregas` | As tentativas de entrega deste app (§6) |
| WS | `/v1/ws?token=` | Tempo real (só saída; nada que chega é obedecido) |
| GET | `/saude` | Estado do serviço **e o que falta configurar** (sem sessão) |
| GET | `/arquivos/{caminho}` | Só no modo `TALK_STORAGE=local`; com Supabase a URL é assinada |

Três detalhes que costumam custar uma tarde a quem está integrando:

- **`tipo` do canal é `publico` / `privado`**, em português (`main.py:322`). `public`/`private`
  respondem `400`.
- **`/v1/canais/do-alvo` NÃO recebe `app`.** O corpo é só `{tipo, id}` (`AlvoIn`,
  `main.py:262`); o app sai da sessão. Mandar `app` não quebra, mas é ignorado — e sugere um
  poder que o cliente não tem: **não** existe citar alvo de outro sistema.
- **`mencoes` são ids da Talk Solar** (os de `/v1/pessoas`), não `externo_id`. É o webhook que
  traduz para `externo_id` na saída (§6).

### 3.1 O anexo nasce com dono

`POST /v1/canais/{id}/mensagens/anexos` é **multipart** e cria a mensagem E os arquivos na MESMA
requisição (`arquivos[]`, `conteudo`, `responde_a`, `refs`). Não existe "sobe o arquivo e depois
liga": no caminho de dois passos, uma falha no meio deixa arquivo órfão no storage ou mensagem
vazia na conversa — e as duas coisas só aparecem para alguém já incomodado.

Todos os arquivos são **lidos e validados antes do primeiro byte gravado** (`main.py:496-505`):
recusar o oitavo depois de subir sete deixaria no storage sete arquivos que ninguém mais liga a
coisa nenhuma.

O `conteudo` **pode ser vazio**: mandar só a foto é o gesto mais comum de quem está em campo.

### 3.2 Mensagem (resposta)

```jsonc
{ "id": 91, "canal_id": 7, "autor": { "id": 42, "nome": "Renan" },
  "conteudo": "olha o inversor 3", "responde_a": null, "respostas": 0,
  "do_sistema": false,
  "editada": false, "apagada": false, "criada_em": "2026-09-04T13:20:11Z",
  "anexos": [ { "id": 3, "nome": "campo.png", "tipo": "image/png", "bytes": 812345,
                "imagem": true, "largura": 900, "altura": 600,
                "url": "<assinada, expira em 1 h>", "thumb_url": "<assinada, expira>" } ],
  "refs": [ { "tipo": "os", "id": "1016",
              "label": "OS 1016 · Manutenção preventiva",
              "url": "https://meuplano…/os-list?os=1016" } ] }
```

- `do_sistema: true` = mensagem escrita pelo **webhook de volta** (§7), não por gente. Ela não
  tem autor (`autor.id: null`) — mostre-a diferente do resto.
- Mensagem apagada volta com `apagada: true`, **`conteudo: ""`, `anexos: []` e `refs: []`**
  (`_msg_out`, `main.py:187-189`): apagar é marcar o buraco, não devolver o conteúdo.
- `label` e `url` das citações são **congelados no momento da citação**. A conversa de ontem
  mostra o nome que a coisa tinha ontem, e a citação sobrevive ao registro apagado.

---

## 4. Erros

Esta tabela lista **só o que o servidor levanta de fato**. Confira com
`grep -rn "HTTPException(" server/app/`.

| Status | Quando |
|---|---|
| 400 | Pedido malformado: mensagem vazia, nenhum arquivo, acima de 10 arquivos, **arquivo grande demais ou de tipo não suportado**, `tipo` de canal fora de `publico\|privado`, corpo do webhook sem `alvo`/`texto` |
| 401 | Sem `Bearer`, token vencido, sessão revogada, conta inativa, o sistema hospedeiro recusou a identidade, ou **assinatura de webhook inválida** |
| 403 | Autenticado, mas a ação não é sua (editar/apagar mensagem de outro) ou o app foi **desativado** no registro |
| 404 | Não existe **ou não é seu** — canal alheio, mensagem inexistente, slug de app não integrado, ou o sistema de origem não confirmou o alvo |
| 502 | O sistema hospedeiro não respondeu, respondeu ≥400 ou **respondeu sem `externo_id`** — a Talk Solar diz de quem é a culpa |

**404 e não 403 para o que é alheio**: quem não pode ver não deve nem descobrir que existe.

> **Não existem 409 nem 413.** As duas linhas estavam nesta tabela e nunca foram verdade:
> entrar num canal em que já se está é **no-op silencioso** (`main.py:400`), e arquivo acima do
> teto responde **400** com o nome do arquivo no texto (`main.py:504`), não 413. Um cliente que
> tratasse 413 como "arquivo grande" e 400 como "erro de programação" mostraria a mensagem
> errada para o técnico em campo.

O **502 é o pedaço mais útil desta tabela** e vale ler o texto que vem nele: ele nomeia o
sistema e o motivo (`"meuPlano não respondeu (ConnectTimeout)"`). Foi escrito assim de propósito
— um 500 genérico vira meia hora de gente olhando o log errado.

---

## 5. O que CADA SISTEMA precisa implementar

São três endpoints. Eles são chamados **servidor-a-servidor**, autenticados por um segredo
compartilhado no cabeçalho **`X-Talk-Secret`** (o mesmo `secret` do registro do app).

> Verificação: `server/app/integracao.py`, linhas **48**, **101** e **128** — os três `headers={"X-Talk-Secret": app.secret}`.

### 5.1 Identidade — obrigatório

```
POST {identidade_url}
X-Talk-Secret: <segredo do app>
{ "token": "<token do usuário no sistema>" }

200 { "externo_id": "179", "nome": "Renan Marchesini",
      "email": "renan@…", "avatar_url": null, "ativo": true }
401 { "detail": "token inválido" }
```

É o **único** endpoint obrigatório. Sem ele o sistema não integra.

O que a Talk Solar faz com a resposta (`integracao.resolver_identidade`):

| Resposta sua | O que o usuário vê |
|---|---|
| `401` | `401 "O <sistema> não reconheceu este login."` |
| qualquer outro `≥400` | `502 "<sistema> respondeu <status> ao confirmar a identidade."` |
| `200` sem `externo_id` | `502 "… respondeu sem externo_id — contrato quebrado"` |
| `200` com `"ativo": false` | `401 "Sua conta está inativa neste sistema."` |
| não respondeu em 8 s | `502 "<sistema> não respondeu (…)"` |

> `externo_id` é string de propósito: um sistema usa int, outro usa UUID. A chave da Talk Solar é
> o par `(app, externo_id)` — `UniqueConstraint("app_id", "externo_id")`, `models.py:69`.

**Num sistema multiempresa (§1), é aqui que o isolamento se decide**: recuse com `401` o token
de quem não pertence à empresa daquele segredo. Depois disso a Talk Solar cuida sozinha, porque
apps não se enxergam.

### 5.2 Buscar alvos citáveis — opcional (sem ele, não há citação)

```
POST {refs_busca_url}
X-Talk-Secret: …
{ "externo_id": "179", "q": "porto", "limite": 6 }

200 { "itens": [
        { "tipo": "usina", "id": "238", "label": "UFV Porto Ferreira",
          "url": "https://meuplano…/usinas/238" },
        { "tipo": "os", "id": "1016", "label": "OS 1016 · Preventiva",
          "url": "https://meuplano…/os-list?os=1016" } ] }
```

**O recorte de visibilidade é do SISTEMA, não da Talk Solar.** Ele recebe o `externo_id` e
devolve só o que aquela pessoa pode ver. Se isso for esquecido, o chat vira a porta dos fundos
para descobrir o nome das usinas dos outros.

`tipo` é livre (cada sistema tem os seus) e só precisa ser estável — ele volta nas citações e nos
webhooks. Timeout de 5 s; **falha aqui nunca derruba a conversa**: a busca volta vazia e a tela
diz que este sistema ainda não permite citar (`integracao.buscar_alvos`).

### 5.3 Rótulo de um alvo — opcional (fortemente recomendado)

```
POST {refs_label_url}
X-Talk-Secret: …
{ "externo_id": "179", "alvos": [ { "tipo": "os", "id": "1016" } ] }
200 { "itens": [ { "tipo": "os", "id": "1016", "label": "…", "url": "…" } ] }
```

Usado ao **criar o canal de um alvo** e ao validar cada citação. Devolva **só o que aquela
pessoa (e, se for o caso, aquela empresa) pode ver** — o que não volta é recusado em silêncio.

Duas consequências que valem saber antes de registrar o sistema:

- **Registrado o `refs_label_url`, ele passa a mandar.** `POST /v1/canais/do-alvo` responde
  `404 "Este item não existe (ou não é seu) no sistema de origem."` quando ele não confirma o
  alvo (`main.py:369-370`). É a proteção funcionando — mas um sistema que registra a URL e não a
  implementa fica com o "conversar sobre isto" quebrado em 100% dos casos, porque
  `rotular_alvos` devolve vazio em erro e em 404 igualmente.
- **Sem `refs_label_url`, o rótulo do cliente é aceito** — e o cliente pode mentir. É uma
  concessão consciente, dita no docstring de `integracao.rotular_alvos`, não um projeto.

> O `scripts/integrar_sistema.py` grava **sempre** os três caminhos (`--identidade`, `--busca`,
> `--label`, com os defaults `/identidade`, `/refs/buscar`, `/refs/label`). Se o seu sistema não
> vai implementar a §5.3, apague a coluna depois de registrar
> (`update ts_apps set refs_label_url = null where slug = '…'`) — senão o canal-de-alvo nasce
> sempre em 404.

---

## 6. Webhooks — a Talk Solar AVISA o sistema

Cada app registra uma `webhook_url` e os eventos que quer (`ts_apps.webhook_eventos`; nulo =
todos). A entrega é `POST` JSON com:

```
X-Talk-Evento: mensagem.criada
X-Talk-Entrega: <uuid da tentativa>
X-Talk-Assinatura: sha256=<HMAC hex do corpo cru, com o secret do app>
```

> Verificação: `server/app/integracao.py:166-172` (os três cabeçalhos, em `entregar`) e
> `assinar()` na linha 29 — `"sha256=" + hmac.new(secret, corpo, sha256).hexdigest()`.

**Confira a assinatura antes de ler o corpo.** Sem isso, qualquer um que descubra a URL escreve
no seu sistema.

| Evento | Quando | Para que serve |
|---|---|---|
| `mensagem.criada` | Toda mensagem enviada em qualquer canal daquele app — **ver o aviso abaixo** | Postar no feed da OS/usina que houve conversa |
| `mencao.criada` | Alguém foi citado por `@` (a mensagem trazia `mencoes`) | Disparar a notificação do próprio sistema |
| `canal.criado` | Canal novo ligado a um alvo | Mostrar o botão "conversar" na tela do alvo |

```jsonc
// corpo de mensagem.criada
{ "evento": "mensagem.criada", "em": "2026-09-04T13:20:11Z",
  "canal": { "id": 7, "nome": "UFV Porto Ferreira",
             "alvo": { "app": "meuplano-1", "tipo": "usina", "id": "238" } },
  "mensagem": { "id": 91, "conteudo": "olha o inversor 3",
                "autor": { "externo_id": "179", "nome": "Renan" },
                "anexos": 1,
                "refs": [ { "tipo": "os", "id": "1016" } ] } }

// mencao.criada acrescenta os externo_id de quem foi chamado
{ "evento": "mencao.criada", "em": "…", "mencionados": ["179", "204"],
  "canal": { … }, "mensagem": { … } }
```

### ⚠ 6.1 O que HOJE sai, e o que vai passar a sair (defeito conhecido — item DEP-1)

Esta seção descreve o **código de hoje**, não a intenção. Leia antes de decidir o que o seu
receptor registra e o que ele loga.

1. **`mensagem.criada` sai para TODO canal, inclusive conversa direta.** `_avisar` é chamado sem
   condição em `enviar` (`main.py:466`) e em `enviar_com_anexos` (`main.py:519`); quando o canal
   não tem alvo, o corpo vai com `"alvo": null` — **mas com `conteudo` e autor do mesmo jeito**.
   Ou seja: o texto de uma DM sai do mensageiro e cai no receptor e nos logs do sistema
   hospedeiro. **Enquanto DEP-1 não pousar: ignore o evento cujo `canal.alvo` é `null` logo na
   primeira linha do seu receptor, e não registre esse corpo em log nenhum.**
2. **`mencionados` pode conter `externo_id` de usuário de outro app.** A consulta que os resolve
   (`main.py:243`) não filtra por `app_id`. **Resolva os ids contra o seu banco e ignore o que
   não for seu** — é o que o receptor do meuPlano faz (`_alvos_da_mencao`).
3. **`GET /v1/admin/webhooks/entregas` não tem gate de administrador.** Exige só sessão e filtra
   por app (`main.py:690`): qualquer pessoa do sistema integrado lê o estado, o status HTTP e os
   200 primeiros caracteres da **resposta do seu sistema** a cada webhook. **Não devolva no corpo
   do seu receptor nada que você não queira que todo o time leia** (esta é a razão de o receptor
   do meuPlano responder só `{ok, postado, avisados}`).

Os três estão endereçados no item **DEP-1** do plano. Quando ele pousar, esta seção vira: só
canal com alvo dispara `mensagem.criada`; `mencao.criada` continua valendo em canal sem alvo mas
**sem o conteúdo da DM**; `mencionados` sai filtrado por app; e a rota de entregas passa a exigir
dono/admin do app.

### 6.2 Entrega e reenvio

A entrega é **assíncrona por desenho** (`integracao.enfileirar` grava em `ts_entregas`; o worker
de `webhooks.py` entrega depois): se o seu sistema estiver fora do ar, quem mandou a mensagem
não pode esperar 10 s por isso.

- A primeira tentativa sai no próximo giro do worker (**≤ 5 s**), seguida de reenvios em
  **30 s, 2 min, 10 min e 1 h** (`config.REENVIOS_SEG`).
- Resposta `2xx` = ok; qualquer outra coisa, ou timeout de **10 s**, conta como falha.
- Depois da última tentativa a entrega fica registrada como `falhou`, com o **corpo da sua
  resposta** (500 primeiros caracteres), e aparece em `GET /v1/admin/webhooks/entregas`.

**Seja idempotente**: reenvio acontece. Use o **`X-Talk-Entrega`** (uuid único por entrega,
`ts_entregas.ref`, com `UNIQUE`) para não postar o mesmo recado duas vezes no seu feed. Se algum
proxy no caminho comer cabeçalhos personalizados, o `sha256` do corpo cru serve de chave: o
payload é gravado uma vez aqui e reenviado idêntico.

> **A ordem importa.** Grave a marca de idempotência e o efeito (o comentário, o aviso) na
> **MESMA transação**. Marcar antes de aplicar perde o recado para sempre se a aplicação falhar:
> o reenvio bate na marca e desiste de algo que nunca entrou. É o defeito que o gate
> `validate_talk_webhook.py` do meuPlano existe para impedir de voltar.

---

## 7. Webhook de VOLTA — o sistema avisa a Talk Solar

```
POST /v1/webhooks/{app_slug}
X-Talk-Assinatura: sha256=<HMAC do corpo cru com o secret do app>

{ "evento": "alvo.mudou",
  "alvo": { "tipo": "os", "id": "1016" },
  "texto": "OS fechada por Renan em 04/09",
  "silencioso": false }
```

A Talk Solar posta isso como **mensagem de sistema** (`do_sistema: true`, sem autor) no canal
daquele alvo. É como a OS conta, na própria conversa, que foi fechada — sem ninguém digitar.

- `alvo.tipo`, `alvo.id` e `texto` são **obrigatórios** (`400` sem eles). `evento` é livre e hoje
  serve só de rótulo para quem lê o log.
- O texto é cortado em **2000 caracteres**.
- `silencioso: true` grava sem empurrar pelo WebSocket (evento de rotina que não merece piscar a
  tela de todo mundo).
- **Sem canal daquele alvo, nada acontece** — e a resposta é `200
  {"ok": true, "postado": false, "motivo": "ainda não há conversa sobre este item"}`. Não é erro:
  criar um canal por evento encheria a lista de conversas vazias. Trate `postado: false` como
  "ninguém estava conversando sobre isso ainda", não como falha, e **não reenvie**.
- Assinatura errada → `401`, conferida **antes** de o corpo ser lido (`main.py:614`).

Não há sessão nesta rota: quem assina é o segredo do app.

---

## 8. Trocar o segredo de um app (rotação)

O segredo faz as duas pontas — autentica a Talk Solar quando ela chama o seu sistema
(`X-Talk-Secret`) e assina os webhooks que ela envia. Trocá-lo derruba as duas ao mesmo tempo, e
o sintoma é `401` em todas as direções. Por isso o `integrar_sistema.py` **nunca troca sozinho**:
rodar de novo com a mesma slug atualiza as URLs e **preserva** o segredo.

Quando trocar for necessário (vazamento, desligamento de quem tinha acesso), a ordem é:

```bash
# 1. gere o novo segredo — a integração cai NESTE instante
cd server
python scripts/integrar_sistema.py meuplano-1 "meuPlano · Splendor" \
    https://<host-vivo>/api/v1/talk \
    --webhook https://<host-vivo>/api/v1/talk/webhook \
    --novo-segredo
# o comando imprime TALK_SECRET=<novo>

# 2. atualize o sistema hospedeiro com o novo valor e reinicie o serviço dele
#    (no meuPlano: a chave daquele slug dentro de TALK_SECRETS, no Railway)

# 3. confirme que voltou
curl -X POST https://<host-vivo>/api/v1/talk/identidade \
     -H "X-Talk-Secret: <novo>" -H "Content-Type: application/json" \
     -d '{"token":"<um token válido>"}'
# espere 200 com externo_id — 401 aqui significa que o passo 2 não pegou
```

Entre o passo 1 e o passo 2 **ninguém abre sessão** e os webhooks pendentes falham (e são
reenviados por até 1 h, então a janela curta se resolve sozinha). Faça fora do horário de campo.

Três regras que valem escrever na parede:

- **Um segredo por app.** Vazar o do meuWatt não pode dar acesso ao meuPlano — e, num sistema
  multiempresa (§1), vazar o de uma empresa não pode dar acesso à outra.
- **O segredo nunca entra no git.** Ele vive como variável de ambiente dos dois lados.
- **Não há endpoint nem tela** para administrar apps. O único caminho é o script, rodado contra o
  banco onde o serviço roda de verdade.

---

## 9. Limites

| | | Onde |
|---|---|---|
| Arquivos por mensagem | 10 | `TALK_MAX_ARQUIVOS` |
| Tamanho por arquivo | 25 MB | `TALK_MAX_ARQUIVO_MB` |
| Tipos aceitos | jpeg, png, webp, gif, pdf, txt, csv, doc, docx, xls, xlsx, zip | `arquivos.TIPOS_OK` |
| Citações por mensagem | 10 | `TALK_MAX_CITACOES` |
| Mensagens por página | 50 (máx. 200) | `limite` de `/mensagens` |
| "O que se falou sobre isto" | 30 (máx. 100) | `limite` de `/refs/{tipo}/{id}/mensagens` |
| Busca de alvos | mínimo 2 caracteres | `Query(..., min_length=2)` |
| Validade do JWT | 12 h | `TALK_JWT_HORAS` |
| Inatividade que mata o refresh | 90 dias | `TALK_SESSAO_DIAS` |
| Timeout ao chamar o sistema | 8 s (identidade) · 5 s (busca e rótulo) | `TALK_TIMEOUT_*` |
| Timeout do webhook de saída | 10 s | `TALK_TIMEOUT_WEBHOOK` |
| Validade da URL assinada do anexo | 1 h | `arquivos.url` |

---

## 10. O que a Talk Solar NÃO faz — e não deve passar a fazer

- **Não guarda senha** e não tem tela de cadastro: identidade é sempre emprestada.
- **Não conhece o domínio** de nenhum sistema (não sabe o que é uma usina). Tudo por `tipo`+`id`
  opacos, com rótulo e URL vindos do sistema.
- **Não decide quem vê o quê no seu sistema**: o recorte de visibilidade dos alvos é seu (§5.2),
  e o recorte por empresa é seu (§1).
- **Não é fonte da verdade de nada além da conversa.** Se a OS fechou, quem sabe é o sistema.
