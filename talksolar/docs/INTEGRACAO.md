# Integrar um sistema ao Talk Solar

> Receita completa para plugar o **meuWatt** e o **Gestão Solar**. O **meuPlano** já está feito
> e serve de molde: o código dele está em `integracoes/meuplano/talk.py.exemplo` — copie, troque
> três coisas (como valida token, o que é citável, onde o recado aparece) e acabou. Sistema que
> atende várias empresas na mesma instalação tem uma quarta decisão a tomar antes: §Passo 2d.

Tempo estimado por sistema: **meio dia**, sendo a maior parte decidir o que é "citável" nele.

---

## O que você vai construir

Do lado do SEU sistema, um router com **três endpoints e um receptor de webhook**:

```
POST /api/v1/talk/identidade     ← obrigatório
POST /api/v1/talk/refs/buscar    ← opcional (sem ele, não há citação)
POST /api/v1/talk/refs/label     ← opcional (recomendado)
POST /api/v1/talk/webhook        ← opcional (recebe "houve conversa")
```

Todos protegidos pelo **mesmo segredo compartilhado**, no cabeçalho `X-Talk-Secret`. O contrato
detalhado (corpos, códigos, limites) está em **[API.md](API.md)**.

> ⛔ **Antes de escrever a primeira linha, responda uma pergunta:** o seu sistema atende **uma
> empresa por instalação** ou **várias na mesma**? Se forem várias, você precisa de **um app da
> Talk Solar por empresa** — e isso muda o registro (§Passo 3) e as quatro rotas. O porquê, com o
> vazamento concreto que o motiva, está em **[API.md §1](API.md)**. Decidir depois que já houver
> conversa significa migrar canais entre apps, e não existe rota para isso.

---

## Passo 1 — copiar o molde

```bash
cp talksolar/integracoes/meuplano/talk.py.exemplo  <seu-backend>/app/api/v1/talk.py
```

> ℹ O `.exemplo` é uma **referência datada** (meuPlano, 04/09/2026, sobre o commit `0f2007d9`),
> não código vivo: depois que a Talk Solar virou repositório próprio, nenhum gate consegue mais
> provar que ela acompanha a fonte. A fonte VIVA é o meuPlano, `backend/app/api/v1/talk.py` —
> compare com ela antes de copiar.
>
> **O receptor deste instantâneo está correto e pode ser copiado.** Até a versão anterior deste
> arquivo ele não podia: `_postar_no_feed` usava `service_order_id`/`texto`/`autor` quando as
> colunas reais são `os_id`/`content`/`author`, o `except` engolia o `TypeError` e o recado sumia
> sem log — e a idempotência do `X-Talk-Entrega` estava só ilustrada. Os dois foram corrigidos, e
> há gate provando (`backend/scripts/validate_talk_webhook.py`, no meuPlano, 19/19). O cabeçalho
> do arquivo conta a história inteira.

E montar no seu `main.py`:

```python
from app.api.v1 import talk
app.include_router(talk.router)
```

## Passo 2 — trocar as três coisas que são suas

### a) Como o seu sistema valida um token — `/identidade`

É o único endpoint obrigatório. No meuPlano são 6 linhas porque ele reusa o próprio
decodificador:

```python
dados = _decode_token(payload.token)      # ← TROQUE por como o SEU sistema valida
u = db.get(AppUser, int(dados["sub"]))
return {"externo_id": str(u.id), "nome": u.name, "email": u.email, "ativo": bool(u.active)}
```

> `externo_id` é **string**. Se o seu sistema usa UUID, mande o UUID — a Talk Solar não tem
> opinião sobre isso.

### b) O que é "citável" no seu sistema — `/refs/buscar` e `/refs/label`

No meuPlano: usina, OS, tarefa, equipamento e pendência. No meuWatt provavelmente serão planta,
alarme e relatório; no Gestão Solar, cliente, proposta e contrato. **Os `tipo` são livres** —
só precisam ser estáveis, porque voltam nas citações e nos webhooks.

> ### ⛔ O recorte de visibilidade é SEU
>
> ```python
> ids = _usinas_visiveis(db, u)      # e, na dúvida, devolve NADA — nunca "tudo"
> ```
>
> A Talk Solar manda o `externo_id` e confia na sua resposta. Se isto for esquecido, o chat
> vira a porta dos fundos para descobrir os dados dos outros — e ninguém percebe, porque a tela
> do chat não parece uma tela do seu sistema.

### c) Onde o recado aparece — `/webhook`

No meuPlano, `mensagem.criada` vira comentário no feed da OS ou da pendência (marcado
`system=True`: é registro do sistema, não conversa de gente — não é editável nem apagável por
quem abre a OS). No seu sistema pode ser outra coisa (uma notificação, um contador). A função a
trocar é `_postar_no_feed`.

**Quatro regras do receptor**, e as quatro já estão no molde:

1. **Confira a assinatura ANTES de ler o corpo** — sem isso, quem descobrir a URL escreve no
   seu sistema.
2. **Seja idempotente** — reenvio acontece por desenho (30 s, 2 min, 10 min, 1 h). Use o
   `X-Talk-Entrega`.
3. **Grave a marca e o efeito na MESMA transação.** Marcar antes de aplicar perde o recado para
   sempre se a aplicação falhar: o reenvio bate na marca e desiste de algo que nunca entrou.
4. **Responda rápido e 2xx quando entendeu** — receptor lento vira falha, e falha vira reenvio,
   e o recado aparece três vezes.

> ⚠ **Leia [API.md §6.1](API.md) antes de decidir o que o seu receptor registra.** Hoje o evento
> `mensagem.criada` sai também para **conversa direta**, com o conteúdo dentro (o canal vem com
> `"alvo": null`) — ignore esses logo na primeira linha e não os coloque em log nenhum. E o
> `mencionados` pode trazer id de usuário de outro sistema: resolva contra o seu banco e ignore
> o que não for seu.

### d) De quem é a chamada — só para sistema multiempresa

Se o seu sistema atende várias empresas, o segredo apresentado é quem diz de qual delas é a
chamada ([API.md §1](API.md)). No molde isso é o `TalkApp` + o mapa `TALK_SECRETS`, e ele
aparece nas quatro rotas: a identidade recusa quem não é da empresa, as duas de citação cortam o
que não é dela, e o webhook recusa alvo de fora. **Sistema de um cliente por instalação apaga
tudo isso**: registre um app só, não declare `empresa_id`, e o molde já se comporta como se o
aparato não existisse.

## Passo 3 — cadastrar o sistema na Talk Solar

```bash
cd talksolar/server
python scripts/integrar_sistema.py meuwatt "meuWatt" \
    https://api.meuwatt.com.br/api/v1/talk \
    --webhook https://api.meuwatt.com.br/api/v1/talk/webhook
```

O comando imprime o **`TALK_SECRET`**. Guarde-o como variável de ambiente no seu sistema —
**nunca no git**. Rodar o comando de novo com a mesma slug **atualiza as URLs sem trocar o
segredo** (trocar por engano derrubaria a integração em silêncio); `--novo-segredo` força a
troca, e a ordem segura para isso está em [API.md §8](API.md).

Três coisas que só se descobrem rodando:

- **O `base` é a raiz**, e o script cola `/identidade`, `/refs/buscar` e `/refs/label` nela.
  Confirme o host com um `curl` **antes**: a URL vai para `ts_apps` no banco de produção, e host
  errado gravado lá é caro de trocar. (O do meuPlano é `meuplano.up.railway.app`;
  `meuplano-production.up.railway.app` responde 404 da borda do Railway.)
- **Ele grava SEMPRE o `refs_label_url`**, mesmo que você não vá implementá-lo — e aí todo
  "conversar sobre isto" responde 404, porque a Talk Solar exige a confirmação do alvo quando a
  URL existe. Se não vai implementar, limpe a coluna depois:
  `update ts_apps set refs_label_url = null where slug = 'meuwatt';`
- **Multiempresa: uma linha por empresa**, todas apontando para as mesmas URLs. O que muda é o
  segredo.

## Passo 4 — provar que funciona

O teste de contrato do servidor (`server/testes/test_contrato.py`) levanta um **sistema falso**
que implementa os três endpoints. Use-o como espelho: se o seu sistema responde como aquele
`class Sistema` responde, a integração funciona.

```bash
cd talksolar/server
PYTHONPATH= python testes/test_contrato.py      # 32 OK / 0 falhas
```

> ⚠ **O `PYTHONPATH` precisa estar VAZIO.** Com o do meuPlano ativo (o caso de quem trabalha nos
> dois repositórios na mesma máquina), o teste morre em
> `ImportError: cannot import name 'webhooks' from 'app'` — é colisão do pacote `app`, não
> defeito do projeto. Perder meia hora com isso é o que este aviso existe para evitar.

Roteiro manual, do mais barato ao mais caro:

```bash
# 1. o seu endpoint responde?
curl -X POST https://seu-sistema/api/v1/talk/identidade \
     -H "X-Talk-Secret: $TALK_SECRET" -H "Content-Type: application/json" \
     -d '{"token":"<um token válido do seu sistema>"}'
# espere: {"externo_id":"...","nome":"...","ativo":true}

# 2. a Talk Solar abre sessão com ele?
curl -X POST https://talk-solar/v1/sessao -H "Content-Type: application/json" \
     -d '{"app":"meuwatt","token":"<o mesmo token>"}'
# espere: {"token":"...","refresh":"...","usuario":{...}}

# 3. o webhook chega?  (mande uma mensagem e depois:)
curl https://talk-solar/v1/admin/webhooks/entregas -H "Authorization: Bearer <token>"
# espere: estado "entregue". Se estiver "pendente" ou "falhou", a `resposta` diz por quê.
```

---

## Erros que valem conhecer antes

| Sintoma | Quase sempre é |
|---|---|
| `502 … não respondeu` ao abrir sessão | O endpoint `/identidade` está fora do ar, atrás de VPN, ou demorou mais de 8 s |
| `401 O <sistema> não reconheceu este login` | O token é de outro ambiente (produção × homologação) |
| `502 … respondeu sem externo_id` | O JSON de resposta está fora do contrato (API.md §5.1) |
| Citação nunca aparece | `refs_busca_url` vazio, ou a busca devolve `itens` fora do formato |
| Citação some ao enviar | `/refs/label` não confirmou o alvo — e alvo não confirmado é recusado de propósito |
| **"Conversar sobre isto" dá 404 em TUDO** | `refs_label_url` está registrado e o endpoint não existe (ou responde erro). Implemente-o ou apague a coluna — ver Passo 3 |
| `400 tipo deve ser 'publico' ou 'privado'` | O cliente mandou `public`/`private`: o vocabulário é português |
| Webhook `falhou` com 401 | O receptor está conferindo a assinatura com o segredo errado |
| Webhook chega repetido | O receptor não é idempotente (ou está demorando e a Talk Solar reenvia) |
| Recado nunca aparece no feed, e a entrega diz `entregue` | O receptor respondeu 2xx e engoliu o erro. Foi exatamente o defeito do meuPlano até 04/09/2026 — logue a falha **sem** perder o 2xx |

---

## O que a Talk Solar **nunca** vai pedir a você

- senha, hash de senha ou qualquer credencial de usuário;
- acesso ao seu banco;
- que você conheça o esquema dela.

Se alguma integração precisar disso, o desenho está errado — e é o momento de conversar antes
de escrever o código.
