# Plano — o WhatsApp Business de cada técnico, ligado ao help-desk do meuPlano

> Escrito em 07/10/2026, antes de qualquer linha de código. Retoma o item 3 de
> [`MULTIEMPRESA.md` §7](MULTIEMPRESA.md#7-o-que-está-feito-e-o-que-falta) ("WhatsApp
> coexistence") com o refinamento do dono. Tudo marcado ✅ foi conferido no código ou na
> documentação oficial da Meta; tudo marcado ⚠ **ainda não foi verificado** e não deve
> virar código antes de ser.

## 1. O pedido, nas palavras do dono

> *"fizemos a estrutura de gerente da empresa de O&M que dá acessos aos usuários no GS;
> os usuários são clientes, que não precisarão entrar no GS adm, e os técnicos, que irão
> entrar no GS adm para configurar suas contas WhatsApp Business, que ficarão linkadas com
> os helpers do meuPlano."*

> *"eu criei um acesso na Meta [...] achando que era da Splendor, empresa prestadora de
> O&M, mas o certo é ser DO sistema, esse sistema ser parceiro Meta, e os conectores, os
> usuários, terem uma forma de acesso mais simples."*

> Transporte: *"O gateway do GS transporta."*

Três decisões, então:

| Tema | Decisão |
|---|---|
| Quem conecta | **o técnico**, cada um o número dele. O cliente não entra no painel |
| De quem é o app da Meta | **da plataforma** (Gestão Solar), parceira Meta como **Tech Provider** |
| Como o técnico conecta | **Embedded Signup**: um botão, a janela da Meta, pronto. Sem colar token |
| Quem fala com a Meta | **o gateway do GS** (`whatsapp/`), para o GS e para o meuPlano |

Isto **reabre** a frente "Atendimento humano", que o
[`PLANO_WHATSAPP_NOTIFICACOES.md`](PLANO_WHATSAPP_NOTIFICACOES.md) registrava como
*descartada*. Não do zero: o atendimento já existe — é o help-desk do meuPlano. O que muda
é por qual número ele fala.

A régua do `MULTIEMPRESA.md` §2 continua valendo e fica mais fina:

> **O que fala com a Meta é da PLATAFORMA. O número é do TÉCNICO. A conversa é do TICKET,
> e o ticket é da EMPRESA.**

## 2. O que existe hoje (conferido no código em 07/10/2026)

| Onde | Estado |
|---|---|
| GS `whatsapp/` (gateway, no ar) | ✅ **uma** credencial (`wa_credenciais`, `escopo` UNIQUE = `padrao`), cadastrada à mão em Painel → WhatsApp, cifrada com Fernet. Envia template, recebe webhook com HMAC, avisa o BFF |
| GS inbound | ✅ gravado em `wa_mensagens` e **para aí** — ninguém responde |
| GS perfis | ✅ `cliente`, `atendimento`, `administrador`, `gestor_empresa`. **Não há técnico.** O gerente só cria `cliente` ou `gestor_empresa` (`empresa.py`, `if body.perfil not in (...)`) |
| GS vínculo com o meuPlano | ✅ `gs_vinculos_produto.usuario_remoto_id` — a conta daqui sabe quem ela é lá, provado por token |
| GS empresa ↔ tenant | ✅ `gs_empresas.mp_tenant_id` |
| MP help-desk | ✅ casca única em `garantia_helpdesk.py`, kinds em `helpdesk_kinds.py` (garantia, pendência), timeline, "de quem é a bola", prazo em dias úteis |
| MP WhatsApp | ✅ `whatsapp_numeros` (janela de 24 h **por número do contato**), `whatsapp_conversas` (número ↔ ticket), `whatsapp_soltas` (inbound sem destino certo) |
| MP credencial da Meta | ✅ **variável de ambiente, global** (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_WABA_ID`, `WHATSAPP_APP_SECRET`) |
| MP webhook | ✅ próprio, com `WHATSAPP_FORWARD_URLS` repassando cópia ao GS |

## 3. O que a Meta exige (documentação oficial, conferida em 07/10/2026)

**Para a plataforma virar Tech Provider** ([fonte][tp]):

1. ✅ **Verificar o negócio** — nome, endereço, telefone, e-mail, site, documentos.
2. ✅ App com ícone, política de privacidade e categoria.
3. ✅ **Dois vídeos**: uma mensagem criada no app e recebida no WhatsApp; a criação de um template.
4. ✅ **App Review** pedindo *Advanced access* a `whatsapp_business_messaging` e
   `whatsapp_business_management`.
5. ✅ Limite: **10 clientes novos por 7 dias**; com verificação + App Review + Access
   Verification, sobe para 200 ([fonte][es]).

**O Embedded Signup** ([fonte][impl], [fonte][onb]):

- ✅ Configuração em *Facebook Login for Business → Configurations*, variação
  *WhatsApp Embedded Signup* → gera o `config_id`.
- ✅ No navegador: `FB.login(cb, {config_id, response_type: 'code',
  override_default_response_type: true, extras: {setup: {}}})`. O evento de mensagem
  devolve `waba_id`, `phone_number_id`, `business_id` e `event` (`FINISH` · `FINISH_ONLY_WABA` · `ERROR`).
- ✅ O `code` vive **30 segundos** — o front entrega ao BFF na hora, e o BFF troca em
  `GET /oauth/access_token?client_id&client_secret&code`.
- ✅ Depois: `POST /<WABA_ID>/subscribed_apps` com o token do cliente, e
  `POST /<PHONE_NUMBER_ID>/register` com `messaging_product: "whatsapp"` e `pin` de 6 dígitos.
- ✅ Webhook `account_update` obrigatório.

**Coexistência — o técnico continua usando o app no celular** ([fonte][coex]):

- ✅ O Embedded Signup oferece conectar um número **que já está no WhatsApp Business app**.
  As mensagens do celular e as da API ficam sincronizadas. É o que torna isto viável: o
  técnico não troca de aplicativo nem perde o número.
- ✅ App do WhatsApp Business **2.24.17 ou superior**.
- ✅ Sincroniza contatos e **6 meses** de conversas (sem grupos), e só se o sync acontecer
  em **24 h** — senão o técnico precisa sair e refazer.
- ✅ Webhooks a assinar: `history`, `smb_app_state_sync`, **`smb_message_echoes`** (o que o
  técnico manda **pelo celular** — sem isso a timeline do ticket fica com buraco).
- ✅ Deixam de funcionar no número: mensagem temporária, visualização única, localização
  ao vivo e lista de transmissão. Grupos não sincronizam. Vazão fixa de 20 msg/s.
- ✅ **Celular parado ~14 dias desconecta** o número da API.
- ⚠ **Não confirmado se o Brasil é elegível.** A página não lista países.
- ⚠ Não confirmado se na coexistência se chama o `/register` (com PIN) — acredito que
  não, porque o número continua no app, mas está para verificar.
- ⚠ Não confirmado se o token do cliente expira.
- ⚠ Não confirmado se o Embedded Signup roda **antes** da aprovação do App Review, com os
  administradores do próprio app. É o que decide se dá para testar enquanto a Meta analisa.

## 4. ⚠ A questão da cobrança, que muda o desenho

A documentação de Tech Provider diz que **cada cliente conectado precisa cadastrar um
cartão** na própria conta de mensagens ([fonte][es]). E na coexistência a Meta **não cria
conta nova**: ela converte a conta do número existente — ou seja, **cada técnico tem a sua
WABA, com a sua cobrança**.

O que isso significa na prática, e que precisa ser confirmado antes de construir:

- **Mensagem dentro da janela de 24 h** (o técnico respondendo o fabricante que escreveu) —
  ⚠ pela tabela atual da Meta, não é cobrada. Se for assim, o cartão quase nunca é usado.
- **Template** (abrir conversa fria, ou cobrar o fabricante depois de 24 h) — é cobrado,
  **no cartão do técnico**, não da empresa.

Se isso for inaceitável, a alternativa é **um número por empresa** (a WABA da empresa com o
cartão dela) e os técnicos atendendo por ele — que é o que o `MULTIEMPRESA.md` previa. Mas
aí não há coexistência por técnico: o número da empresa sai do celular de alguém.

**O desenho abaixo guarda a conta por NÚMERO** (com o técnico como dono), e isso serve aos
dois casos: se um dia for "número da empresa", ele é um número cujo dono é o gerente.

## 5. O desenho

```
                  ┌─────────────── Meta ───────────────┐
                  │  app da PLATAFORMA (Tech Provider) │
                  │   ├─ WABA do técnico A  (nº A)     │
                  │   └─ WABA do técnico B  (nº B)     │
                  └──────────────┬─────────────────────┘
                     uma callback│ só, roteada por phone_number_id
                                 ▼
   painel (técnico) ──► BFF ──► gateway GS ──────────► meuPlano (help-desk)
   "Conectar WhatsApp"   code     guarda a conta do nº      timeline do ticket
                         ↓ 30 s   envia em nome do nº  ◄──  composer manda pelo gateway
                                  recebe e repassa     ──►  roteia ao ticket
```

### 5.1 Perfil `tecnico` (BFF)

- Novo valor em `Perfil` — a coluna é `native_enum=False`, então **não há migration de tipo**.
- Lado **empresa**: tem `empresa_id`, é criado pelo **gerente** em Usuários.
- Entra pela porta única (`/api/painel/entrar`). ⚠ Portão: **não pode** usar o
  `gestor_empresa_atual` — o técnico não administra a empresa. Recomendação: o mesmo token
  de escopo `empresa`, com a guarda nova `tecnico_atual` e rotas próprias
  (`/api/empresa/eu/whatsapp*`) que só falam da conta da sessão. Nenhuma rota recebe id de
  técnico — o técnico é quem está logado.
- O menu do painel mostra a ele **só "Meu WhatsApp"**.
- Vínculo com o meuPlano: o mesmo `gs_vinculos_produto` (token do técnico no meuPlano →
  `usuario_remoto_id`). É o que diz ao meuPlano "este número é do usuário 42 de lá".

### 5.2 Conta por número (gateway)

`wa_contas` — uma linha por número conectado:

| coluna | |
|---|---|
| `phone_number_id` UNIQUE | a chave do roteamento do webhook |
| `waba_id`, `business_id`, `numero_exibicao` | em claro |
| `token_cifrado`, `token_prefixo` | o token do cliente, cifrado como o de hoje |
| `gs_user_id`, `empresa_id` | dono e inquilino — o recorte |
| `coexistencia` | o número continua no app do celular |
| `estado`, `detalhe`, `conectada_em`, `desconectada_em` | |

O `app_secret` e o `verify_token` **não** vão por número: são do app da plataforma, um só.
A linha `padrao` de hoje continua sendo o número de **notificações** da plataforma.

### 5.3 Conectar (BFF + painel)

1. Painel carrega o SDK da Meta (`connect.facebook.net`) e chama `FB.login` com o
   `config_id` — `app_id` e `config_id` vêm do BFF, não do bundle.
2. O evento devolve `waba_id` + `phone_number_id`; o callback devolve o `code`.
3. Painel → `POST /api/empresa/eu/whatsapp/conectar {code, waba_id, phone_number_id}`
   **na hora** (30 s).
4. BFF → gateway: troca o code, `subscribed_apps`, (⚠ `register` se não for coexistência),
   grava a conta com o técnico da sessão como dono.
5. Tela: número, estado, "desconectar", e o aviso dos 14 dias.

### 5.4 Webhook roteado (gateway)

- Uma callback só (a de hoje), conferida pelo `app_secret` da plataforma.
- `value.metadata.phone_number_id` → `wa_contas` → técnico e empresa.
- Número desconhecido → grava e não repassa.
- `messages` (contato → técnico), `smb_message_echoes` (técnico, pelo celular → contato),
  `statuses`, `history`, `account_update` (desconexão vira estado na tela).

### 5.5 meuPlano: o help-desk fala pelo gateway

- **Envio:** o composer do ticket deixa de chamar a Graph e chama o gateway com **o
  número do técnico que está agindo** (o usuário logado no meuPlano, achado pelo
  `usuario_remoto_id`). Técnico sem número conectado → o composer diz isso, não cai num
  número global.
- **Recebimento:** o gateway repassa ao meuPlano por rota interna autenticada, no lugar do
  webhook próprio e do `WHATSAPP_FORWARD_URLS`.
- ⚠ **A janela de 24 h passa a ser por PAR** (nosso número, número do contato).
  `whatsapp_numeros.ultimo_inbound_em` é por contato — com vários técnicos, o fabricante
  que respondeu ao técnico A **não** abriu a janela do técnico B. Migration no meuPlano.
- `whatsapp_conversas` ganha o número do técnico: o roteamento do inbound passa a ser
  (nosso número, número deles) → ticket. As `soltas` continuam para o ambíguo.
- `smb_message_echoes` entra na timeline como **enviado**, com a marca "pelo celular".

## 6. Fases (cada uma termina validada)

| # | Onde | Entrega | Depende de |
|---|---|---|---|
| **M** | **Meta — com o dono** | portfólio da **plataforma**, verificação, app nele, config do Embedded Signup, vídeos, App Review | — |
| T1 | GS `bff/` + `painel/` | perfil `tecnico`, criado pelo gerente, menu só com "Meu WhatsApp", vínculo com o meuPlano | nada |
| T2 | GS `whatsapp/` | `wa_contas`, troca do code, `subscribed_apps`, webhook roteado por número | nada (Graph simulada nos testes) |
| T3 | GS `painel/` | botão "Conectar WhatsApp" com o SDK, estado, desconectar | `config_id` (fase M) para o teste real |
| T4 | MP `backend/` + front | envio pelo gateway, recebimento do gateway, janela por par, echoes na timeline | T2 |
| T5 | ponta a ponta | um técnico real conecta o número dele e conversa com um ticket | M aprovada |

T1 e T2 não dependem da Meta e podem andar já. T3 pode ser escrita, mas só se prova com o
`config_id` real.

## 7. O que é do dono, e não do código

1. **Portfólio de negócios da PLATAFORMA na Meta**, não o da Splendor. O app de teste de
   hoje (App `1088684893680434`, Business `1991828342203971`) ⚠ precisa ser conferido: se
   estiver no portfólio da Splendor, o caminho é criar o portfólio da plataforma e um app
   novo nele — mover app entre portfólios ⚠ não foi verificado.
2. **Verificação do negócio** com os documentos da empresa dona da plataforma.
3. **Os dois vídeos e o App Review** — os vídeos podem ser gravados com o envio que já
   funciona no gateway (Painel → WhatsApp → enviar teste).
4. **A decisão da cobrança** (§4): cartão por técnico, ou número por empresa.

[tp]: https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers
[es]: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/
[impl]: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation/
[onb]: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider/
[coex]: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/
