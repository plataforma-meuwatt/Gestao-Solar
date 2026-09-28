# Multiempresa — a empresa de O&M como inquilino

> Estado: **fundação implementada em 28/09/2026** (banco, escopo, portão e telas). O que
> falta está no fim, em §7. Escrito antes de qualquer linha de código, a pedido do dono,
> porque a fundação errada aqui não dá erro: dá conversa de um cliente aparecendo para outro.

## 1. O problema, medido no banco de hoje

O Gestão Solar é, hoje, de **um inquilino só**: a sua operação.

| O que | Como está | Por que trava |
|---|---|---|
| `gs_users.empresa` | `String(255)`, **texto livre** | "Splendor O&M" e "Splendor OM" são uma empresa ou duas? O banco não tem opinião, então nada pode ser filtrado por ela |
| `gs_plant_links` | sem dono | a usina não pertence a ninguém; quem a opera é implícito |
| `gs_integracoes` | **uma linha por produto**, global | o token do meuWatt é da plataforma inteira |
| `Perfil` | `cliente`, `atendimento`, `administrador` | não existe "gerente da empresa de O&M" |
| Rotas | `/api/v1/*` (cliente) e `/api/painel/*` (staff) | dois portões, e o segundo mistura "a plataforma" com "a operação" |

Enquanto isso for verdade, conectar o WhatsApp de vários integradores joga **todas as
conversas num balaio comum**, e qualquer um com acesso ao helpdesk lê as dos outros.

## 2. O eixo que falta

```
PLATAFORMA (você)
  └── EMPRESA de O&M ................ o inquilino
        ├── gerente da empresa ...... quem opera: conecta WhatsApp, liga usina, cadastra cliente
        ├── usinas da empresa
        └── clientes (donos de usina) ... o app e o portal
```

Três camadas, e a régua que resolve a confusão do WhatsApp:

> **O que fala com a Meta é da PLATAFORMA. O número e a conversa são da EMPRESA.**
> Uma credencial de aplicativo; muitas contas conectadas por baixo dela.

## 3. Decisões

### 3.1 Um usuário pertence a UMA empresa

Não N:N. O caso "a mesma pessoa trabalha em duas O&M" se resolve com **duas contas**, que
é exatamente o precedente que este projeto já teve e documentou: `renanmarquezini` (gestor
do sistema) e `renan.marquezini` (dono de usina) eram o mesmo humano, o mesmo e-mail, dois
papéis — par desfeito em 28/09/2026, quando o dono preferiu uma conta só — e é por isso que quem autentica é o **apelido**, não o e-mail
(ver [DECISAO_IDENTIDADE.md](DECISAO_IDENTIDADE.md)).

Uma tabela de vínculo N:N custaria um `join` em toda consulta e um seletor de "empresa
atual" em toda tela, para servir um caso que ainda não existe. Quando existir, o vínculo
se acrescenta sem quebrar nada — o contrário (tirar N:N depois) é que não dá.

### 3.2 `empresa_id` nulo = conta da PLATAFORMA

O staff (`administrador`, `atendimento`) não pertence a empresa nenhuma. O nulo não é
"todas": quem decide o alcance é o **perfil**, e o nulo só diz que a conta não é de inquilino.

Para o nulo nunca ser lido como "sem filtro" por engano, **nenhuma consulta lê `empresa_id`
direto**. Todas passam por uma função só:

```python
def escopo_de_empresa(conta: User) -> int | TODAS:
    """A ÚNICA fonte do alcance. Plataforma vê tudo; o resto vê a empresa dele."""
```

É o mesmo desenho de `usinas_do_usuario`, que já protege o escopo de usina hoje. Um lugar
para conferir, um lugar para auditar, um lugar para consertar.

### 3.3 Os perfis, em dois eixos

O que hoje é uma lista vira **lado + papel**, e é essa separação que acaba com a confusão:

| Lado | Perfil | O que abre |
|---|---|---|
| Plataforma | `administrador` | tudo, inclusive credenciais e a lista de empresas |
| Plataforma | `atendimento` | operação e diagnóstico, sem credencial |
| **Empresa** | **`gestor_empresa`** | **tudo da empresa dele, e só dela** |
| Cliente | `cliente` | o app e o portal — as usinas concedidas a ele |

**Não existe "operador da empresa" agora.** O dono disse que quem mexe é o gerente da O&M,
e um segundo papel sem ninguém para ocupá-lo é código que envelhece sem uso. Quando a O&M
pedir um perfil de leitura, ele nasce como uma linha no catálogo — não como uma migração.

### 3.4 Uma porta de login, três portões de rota

Autenticar é uma coisa só; autorizar é que tem três portões. A porta é
`POST /api/painel/entrar` — a mesma que o painel já usava — e o que mudou é o token que
sai dela: quem tem perfil `gestor_empresa` recebe uma sessão de `escopo=empresa`, e a
resposta traz `escopo` e `empresa` para a tela montar o menu e fixar o nome no alto.

A alternativa — uma rota de login por portão — seria a mesma regra escrita duas vezes
(conta ativa, senha, empresa ativa, `ultimo_login`), e a segunda cópia é sempre a que
esquece uma das quatro. O front também não ganharia nada: ele teria de adivinhar qual
tentar primeiro, ou perguntar à pessoa quem ela é, que é uma pergunta que o servidor
responde melhor.

### 3.5 Três portões, três prefixos

O prefixo **diz de quem é a rota**, e é a primeira coisa que se lê num arquivo:

| Prefixo | Quem entra | Sessão |
|---|---|---|
| `/api/painel/*` | plataforma | JWT com `escopo=painel` |
| **`/api/empresa/*`** | **gerente da O&M** | **JWT com `escopo=empresa`** (novo) |
| `/api/v1/*` | dono de usina (app e portal) | JWT sem `escopo` |
| `/api/v1/interno/*` | máquina (agendador, gateway) | segredo em cabeçalho |

O mecanismo já existe e já é restritivo: `usuario_atual` recusa **qualquer** token que traga
a claim `escopo` — um portão novo nasce recusado nos outros, que é o padrão certo. Vale a
pena repetir o que o código já diz: a claim é testada por **presença**, não por valor.

Duas regras que não devem ser "simplificadas":

- **`/api/empresa/*` nunca aceita `empresa_id` vindo do cliente.** O alcance sai da sessão.
  Um parâmetro de empresa numa rota de empresa é a definição de vazamento.
- **Só a plataforma pode pedir outra empresa** (`?empresa=` nas rotas de painel), e isso é
  conferido no servidor, como `exige_area` já faz.

### 3.5 O front é o MESMO painel, com o menu montado pelo perfil

Não nasce um quarto front. O `CLAUDE.md` já registra que painel, portal e app repetem a
camada de API sem lugar comum, e que **as divergências já começaram** — uma quarta cópia
seria a quarta chance de corrigir defeito em três lugares e esquecer o quarto.

A distinção absoluta que o dono pediu mora no **servidor** (prefixo + escopo + filtro único),
não no bundle. No front ela aparece como:

- o **nome da empresa fixo no topo**, sempre visível, enquanto a sessão for de empresa;
- o menu com os itens daquele lado, e nada mais;
- quando a plataforma estiver olhando uma empresa, uma **faixa dizendo isso** — ver §6.

### 3.5b A empresa daqui é o VÍNCULO, não um terceiro cadastro

Os dois produtos já têm empresa, e **os dois cadastros são independentes de propósito**:

| | entidade | o que pende dela |
|---|---|---|
| meuWatt | `enterprises` | `plants.enterprise_id`, `enterprise_employees` (4 empresas cadastradas; a SplendorOEM com 6 usinas e 20 funcionários — medido em 28/09/2026) |
| meuPlano | `tenants` | `app_users.tenant_id`, e a empresa dona no financeiro |
| Gestão Solar | `gs_empresas` | o inquilino: login do gerente, escopo, WhatsApp |

Alguém pode contratar **só a manutenção** e nunca existir no monitoramento. Nenhum dos dois
é "o certo", e nenhum sabe do outro. O que faltava é quem diga que aquela empresa de lá e
aquela de lá **são a mesma, e é esta aqui** — e é isso que `gs_empresas` faz, com
`mw_enterprise_id` e `mp_tenant_id`.

É o mesmo papel de `gs_plant_links` para usina, com os mesmos três casos: nos dois
produtos, só no meuWatt, só no meuPlano. E o mesmo **corolário do dado morto**: empresa sem
nenhum dos dois vínculos é fantasma — aparece na lista e todas as telas dela vêm vazias,
porque não há upstream de onde ler. A tela diz isso em vermelho, na própria linha.

### 3.6 Cada empresa tem a conta DELA no meuWatt e no meuPlano

Decisão do dono, 28/09/2026. O que isso significa no código é menos do que parece, porque
metade já era assim:

- **O token com que se lê os dados de um cliente já é do próprio cliente** (`gs_user_product_links`,
  via `vinculos.cliente_*`). Nada muda aí: a conciliação e as telas já leem com a régua que
  cada produto aplica no site dele.
- **O que era da plataforma é a credencial de SERVIÇO** (`gs_integracoes`): o catálogo de
  micro usinas, a sonda, o motor de paradas. É ela que passa a ter dono.

Três consequências, e a terceira é a que protege:

1. `gs_integracoes` ganhou `empresa_id`, e a unicidade virou **dois índices parciais** —
   um por (produto, empresa) e um por produto entre as linhas de plataforma. Um
   `UNIQUE (produto, empresa_id)` sozinho não serviria: no Postgres dois `NULL` não
   colidem, então ele deixaria passar duas credenciais de plataforma para o mesmo produto
   e o sistema escolheria uma por ordem de `id`, em silêncio.
2. O gerente conecta a conta dele em **Conexões**, no portão da empresa. O token vale o que
   aquela conta vale lá — a resposta diz quantas usinas ele alcançou, porque credencial
   aceita que não enxerga nada abre a plataforma vazia sem erro nenhum.
3. **A trava que se arma sozinha.** Enquanto a empresa não tiver a conta dela, a leitura
   cai na credencial da plataforma — é o que permite migrar sem parar nada. No dia em que
   existir **mais de uma empresa ativa**, esse atalho passa a ser recusado com uma frase
   que diz o que fazer. Com uma empresa, a credencial da plataforma é a dela e o atalho é
   correto; com duas, ela é de uma das duas, e usá-la para a outra devolveria usinas,
   ordens e faturas do concorrente. A conta é feita na hora, e não depende de alguém
   lembrar de configurar a segunda empresa antes de cadastrá-la.

### 3.7 A mesma pessoa em vários papéis

Pedido do dono: fazer parte da O&M **e** instalar o app para ver as usinas como cliente.

Isso já era possível — contas separadas, uma por papel, que é o motivo de o login ser por
apelido e não por e-mail. O que faltava era o conforto: sair, lembrar do outro apelido,
entrar de novo.

`gs_pessoas` agrupa as contas de um humano, e `/api/sessao/trocar` emite a sessão do outro
papel. **Por fora é uma identidade; por dentro continuam contas por papel** — e isso não é
meio-termo, é o que preserva tudo o que está acima: cada sessão vale para um portão só, a
faixa consegue dizer em qual você está, e nenhuma guarda precisou mudar.

**A regra que não pode ser afrouxada: descer é livre, subir pede senha.** Trocar para uma
conta de empresa ou de cliente é um clique; trocar para uma conta da PLATAFORMA exige a
senha dela, sempre. Sem isso, o roubo de uma sessão do aplicativo — celular emprestado,
token copiado de um cache — viraria uma sessão de administrador sem que o ladrão
precisasse saber nenhuma senha. O conforto de não redigitar não vale transformar a conta
mais fraca na chave da mais forte.

Agrupar é de **administrador** (Usuários do sistema → *Mesma pessoa*): abrir um caminho de
troca entre contas é o tipo de poder que, concedido, deixa alguém juntar a própria conta à
de quem tem mais.

## 4. O que muda no banco

```
gs_pessoas             (id, nome)  ← agrupa as contas de um humano (§3.7)
gs_users.pessoa_id     → FK nullable
gs_empresas            (id, nome, documento?, ativa, criada_em,
                        mw_enterprise_id?, mp_tenant_id?)  ← o vínculo (§3.5b)
gs_users.empresa_id    → FK nullable. NULL = plataforma
gs_plant_links.empresa_id  → de quem é a usina
gs_integracoes.empresa_id  → FK nullable. NULL = credencial da plataforma
                           + dois índices parciais no lugar do único por produto
gs_whatsapp_contas     (id, empresa_id, phone_number_id, waba_id, token cifrado, estado, sincronizado_em)
```

`gs_integracoes.empresa_id` foi respondido no mesmo dia: **cada O&M usa a conta dela**. Ver
§3.6 — a coluna existe, a unicidade mudou (migration `c2f8a3b91e47`) e a tela de Conexões do
gerente grava a credencial da empresa sem tocar na da plataforma.

`gs_whatsapp_contas.phone_number_id` é a **chave de roteamento** do webhook da Meta: é por
ele que se descobre de qual empresa é a mensagem que chegou. Nunca pelo
`display_phone_number`, que é texto formatado e muda.

### Migração, em ordem

1. Criar `gs_empresas` e inserir as empresas a partir do que houver em `gs_users.empresa`
   (hoje: 7 usuários, uma operação só — é uma linha).
2. Acrescentar `empresa_id` nas quatro tabelas, **nulo**.
3. Preencher: staff fica nulo; clientes e usinas recebem a empresa inicial.
4. Só então tornar obrigatório o que tem de ser (`gs_users` de perfil não-plataforma).
5. Apagar `gs_users.empresa` (o texto livre) **depois** de a coluna nova estar em uso — é a
   única forma de a migração ser reversível enquanto se confere.

## 5. O que o gerente da O&M vê — e o que não vê

**Vê e opera** (dentro da empresa dele, sempre): usinas da empresa · clientes da empresa
(cadastrar, conceder usina, senha provisória) · **conexões de WhatsApp da empresa**
(conectar, estado da sincronização, desconectar) · os usuários da empresa dele.

**Não vê, nunca:**

- **outra empresa** — usuário, usina, cliente, conversa, fatura. Nada;
- as **credenciais da plataforma**: app da Meta, `app_secret`, verify token, e os tokens de
  serviço do meuWatt e do meuPlano;
- **Rotas/sonda e Diagnóstico da plataforma**;
- a **lista de empresas** — ele não sabe quantas existem nem quais são.

## 6. O perigo que este desenho nomeia

**"Ver como" é irresistível e é onde o vazamento mora.** A plataforma vai precisar olhar a
tela de uma empresa para dar suporte. Duas regras:

- a sessão continua sendo **de painel**, com a empresa escolhida por parâmetro conferido no
  servidor — nunca um token de empresa emitido para o staff;
- a tela **diz, o tempo todo**, que está olhando a empresa X. Sem a faixa, alguém cadastra o
  cliente da empresa errada e ninguém descobre no mesmo dia.

**O balaio silencioso.** Toda consulta nova que toca dado de empresa e não passa por
`escopo_de_empresa` funciona perfeitamente em desenvolvimento — onde só existe uma empresa —
e vaza em produção no dia em que entra a segunda. Por isso o escopo é uma função única e
não uma cláusula copiada: uma cópia esquecida não dá erro, dá dado do vizinho.

## 7. O que está feito, e o que falta

**Feito** (28/09/2026):

- `gs_empresas`, e `empresa_id` em `gs_users`, `gs_plant_links` e `gs_integracoes`
  (migration `b1e7c9a24d03`, colunas nulas — nada preenchido);
- `services/empresas.no_escopo` — o recorte único, com 11 testes que guardam os dois
  defeitos caros: consulta sem recorte e recorte escolhido por quem chama;
- perfil `gestor_empresa`, portão `/api/empresa/*` (`eu`, `usinas`, `clientes`,
  `usuarios`) e a guarda `gestor_empresa_atual`, que recusa conta sem empresa;
- login único emitindo o token do portão certo (§3.4);
- credencial de serviço por empresa, com a trava de §3.6 (migration `c2f8a3b91e47`);
- painel: **Empresas de O&M** para a plataforma (cadastrar, desligar, religar e atribuir
  usinas e clientes) e quatro telas do gerente — Usinas, Clientes, Usuários e **Conexões** —,
  com o menu montado por escopo e o nome da empresa fixo no alto.

**Falta, e nesta ordem:**

1. **Ligar os dados de hoje a uma empresa.** A migração dos §4 passos 3 a 5 — criar a
   empresa real, apontar clientes e usinas, e só então apagar `gs_users.empresa`. É
   decisão de quem opera, não de quem migra: por isso a migration não preencheu nada.
2. **Cadastrar cliente e conceder usina pelo lado da empresa.** Hoje o gerente vê as duas
   listas; quem cria continua sendo a plataforma. É o próximo passo natural, e ele reusa
   `services/clientes` com o recorte — não nasce uma segunda cópia da regra.
3. **WhatsApp coexistence.** `gs_whatsapp_contas` com `empresa_id`, o webhook roteando por
   `phone_number_id` e a tela de conectar. **Bloqueado por terceiro**: depende do status de
   Tech Provider na Meta, que leva semanas. É o pedido original, e vem por último de
   propósito — ligado antes da fundação, ele é exatamente o balaio descrito acima.
