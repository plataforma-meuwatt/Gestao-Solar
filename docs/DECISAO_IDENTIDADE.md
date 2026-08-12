# Contas conectadas e conciliação de usinas

> Decisão de arquitetura. Escrita em 2026-08-12, revisada no mesmo dia após discussão.
> Cobre duas perguntas que aparecem juntas mas são separadas: **como o usuário entra** e
> **qual usina é qual**.

---

## 1. A decisão: o Gestão Solar conecta, não substitui

**Cada produto mantém o login que já tem.** O meuWatt continua com o dele, o meuPlano com o
dele. Nada muda para quem já usa.

O Gestão Solar tem uma **conta própria**. Dentro dele, o cliente **conecta** as contas dos
outros produtos — uma vez cada. Depois disso, entra só com a conta do Gestão Solar.

```
   ┌──────────────────────────────────────────┐
   │           Conta Gestão Solar             │
   │        (e-mail + senha próprios)         │
   └────────────┬──────────────┬──────────────┘
                │              │
        conectado a      conectado a
                │              │
      ┌─────────▼──────┐  ┌────▼───────────┐
      │ conta meuWatt  │  │ conta meuPlano │   ← continuam existindo
      │ (login próprio)│  │ (login próprio)│      e funcionando sozinhas
      └────────────────┘  └────────────────┘
```

Produto novo no futuro: ganha o mesmo mecanismo de conexão e entra sem tocar nos dois
primeiros.

### Por que este desenho, e não um login único

Foram consideradas três opções:

| Opção | Por que foi descartada / escolhida |
|---|---|
| **Login único obrigatório**, os produtos viram módulos | Exige migrar todo mundo, e cria um ponto único de falha: provedor fora do ar = ninguém entra em lugar nenhum |
| **meuWatt como provedor** dos três | Herdaria as dívidas dele (ver seção 4) e faria o produto de monitoramento mandar no login da manutenção |
| **Contas conectadas** ✔ | Ninguém fica refém, não há migração, e o terceiro produto entra sem tocar nos outros |

Ganho não previsto: **a conexão resolve boa parte da conciliação de usinas** (seção 3).

---

## 2. Como a conexão funciona

O problema a evitar: depois de conectar, o Gestão Solar precisa continuar lendo dados sem
guardar a senha do cliente. Guardar senha de terceiro é inaceitável — se o banco do BFF
vazar, vazam as contas dos dois outros sistemas junto.

A solução é um **token de aplicativo**: longo, revogável, específico para o Gestão Solar, e
que o cliente pode cancelar a qualquer momento sem trocar a senha dele.

### O meuPlano já tem isso pronto

`backend/app/services/meuacesso/app_login.py` + `api/v1/meuacesso/auth.py:598-704` — fluxo
construído para o Analisador de Instrumentos (appSlendor):

| Passo | Endpoint | O que faz |
|---|---|---|
| 1 | `POST /app/authorize` | o usuário, já logado, autoriza o aplicativo; gera um código de 5 min contra um desafio |
| 2 | `POST /app/token` | o aplicativo troca código + segredo por um JWT curto **e** um `device_token` longo, guardado como hash (`AppDeviceToken`) |
| 3 | `POST /app/refresh` | renova o JWT sem incomodar o usuário |
| 4 | `GET /me/devices` · `DELETE /me/devices/{id}` | o usuário vê e revoga o que está conectado |

É exatamente o "conectar" descrito acima, já em uso. **O Gestão Solar vira mais um
aplicativo autorizado.**

### O meuWatt precisa do equivalente

Ele tem um device flow (`src/auth/device_flow.py`, para o app de campo `mw-modbus-helper`),
mas com duas limitações para este uso:

- **Sem token renovável** — emite um JWT comum, que expira e obriga a reconectar
- **Estado em memória de processo** (dict + lock), não em banco: um redeploy descarta
  autorizações pendentes

O trabalho é adaptar, não inventar: o desenho do meuPlano serve de referência direta.

### O que o BFF guarda

```
gs_users
  id, email, senha (própria do Gestão Solar), nome

gs_conexoes
  gs_user_id      → a conta do Gestão Solar
  produto         → 'meuwatt' | 'meuplano'
  usuario_remoto  → o id da conta lá
  token_cifrado   → o device_token, cifrado em repouso
  conectado_em, ultima_renovacao, revogado_em
```

Nunca a senha. O token é cifrado no banco e revogável dos dois lados — pelo cliente, na
tela de conexões do Gestão Solar, ou por quem administra o produto de origem.

### Dois caminhos para conectar, um resultado só

**Caminho A — o cliente já tem conta no produto.** Ele autoriza uma vez pela tela do próprio
produto, e o hub guarda o token.

**Caminho B — o cliente não tem conta.** O hub cria a conta lá **com uma senha aleatória de
40 caracteres que ele mesmo gera e guarda cifrada**. O cliente nunca vê nem precisa dessa
senha: ele sempre entra pelo hub. Logo após criar, o hub obtém o token de aplicativo e a
senha deixa de importar.

> Se um dia o cliente quiser entrar direto no meuWatt, usa "esqueci minha senha" e define
> uma. Isso **não quebra a conexão**, porque o hub acessa por token, não por senha.

Os dois caminhos terminam igual: uma linha em `gs_conexoes` com um token revogável. O resto
do sistema não distingue.

### Os três problemas do caminho B

| Problema | Solução |
|---|---|
| **O e-mail já existe lá** — o cliente acha que não tem conta, mas tem | Consultar antes de criar; se existir, cair no caminho A ("encontramos uma conta sua — conecte-a") |
| **Criar usuário exige decisão que o hub não toma** — no meuPlano nasce dentro de uma organização, com papel e nível de cofre; no meuWatt, com acesso a plantas específicas | Se o cliente **já foi cadastrado comercialmente** do lado de lá, o vínculo existe e o provisionamento é automático. Se não, vira **solicitação** que alguém do time aprova, definindo organização e usinas — uma vez por cliente |
| **Conta órfã** — cliente cancela o hub e ficam contas que ele não sabe que tem | Desconectar revoga o token; a conta lá segue existindo mas inerte, o que é correto: o contrato daquele produto pode continuar |

### O primeiro acesso, na tela

1. Criar a conta do Gestão Solar (e-mail, senha, nome)
2. **Conectar o meuWatt** — caminho A ou B, conforme o e-mail já exista lá ou não
3. **Conectar o meuPlano** — idem
4. Confirmar quais usinas de um lado correspondem às do outro (seção 3)

Passos 2 e 3 são independentes: quem contratou só monitoramento conecta só o meuWatt, e o
app esconde a aba de manutenção.

Depois, em Perfil → Conexões, o cliente vê o que está conectado, quando foi, e desconecta
quando quiser.

### O caminho inverso, para depois

"Associar conta Gestão Solar" dentro do meuWatt ou do meuPlano é o mesmo fluxo começando do
outro lado — o usuário já logado lá autoriza dali. Não vale construir agora: enquanto o hub
não estiver no ar, não há o que associar.

### O que o cliente vê no fim

- **uma conta** — o e-mail e a senha do Gestão Solar
- **uma tela de entrada**
- **uma lista de usinas**, vindas dos dois lados sem ele saber de onde
- **um lugar** para ver o que está conectado e desconectar

Por baixo são três contas coladas por token, e ele nunca encosta nisso. É unificação na
casca — 95% do benefício de uma conta única, sem migração e sem ninguém ficar refém.

Se um dia todo cliente novo nascer pelo hub, os logins diretos ficam vestigiais por conta
própria. A porta para uma unificação real continua aberta, sem nunca ter sido forçada.

---

## 3. Conciliação de usinas

### O problema

Nenhum dos dois sistemas tem chave para casar a mesma usina:

| | meuWatt (`plants`) | meuPlano (`usinas`) |
|---|---|---|
| Identidade | `id`, `name` (único), `slug` | `id`, `name` |
| CNPJ da usina | não existe | não existe |
| Número de UC | não existe | não existe |
| Código externo | `fusionsolar_station_code` (só plantas Huawei) | `plant_code` — **nullable, não único, nunca preenchido** |
| Coordenadas | `latitude`, `longitude` | `latitude`, `longitude` |

Casar automaticamente por nome ou coordenada é armadilha: "Porto Ferreira", "UFV Porto
Ferreira" e "Porto Ferreira I" saem de pessoas diferentes; duas usinas do mesmo cliente
ficam a 200 m uma da outra. Um casamento errado silencioso mistura a geração de uma usina
com a manutenção de outra, e ninguém percebe até alguém questionar um relatório.

### O que a conexão resolve sozinha

Quando o cliente conecta as duas contas, o sistema passa a saber **de quem** é cada usina
dos dois lados. O casamento deixa de ser "todas as usinas contra todas" e vira "as poucas
deste cliente contra as poucas deste cliente" — tipicamente 3 contra 2.

Nesse recorte, a confirmação manual é trivial e segura. É o passo 4 do primeiro acesso: as
duas listas lado a lado, com sugestão por nome, distância e potência, e o próprio cliente
confirmando. Ele sabe quais são as usinas dele melhor que qualquer algoritmo.

Uma usina pode ficar deliberadamente sem par — é o caso de quem contratou só um dos
produtos.

### O passo que resolve de vez

Introduzir uma **chave natural** nos dois cadastros: **CNPJ da SPE** e **número da UC na
distribuidora**. São menos de 20 usinas hoje; preencher à mão é trabalho de uma tarde, e
todas as futuras nascem casáveis — inclusive as que entrarem por importação.

Com isso, `gs_plant_links` passa a ser derivado: mesmo CNPJ + UC dos dois lados = vínculo
sugerido com confiança alta. Sem isso, cai na confirmação manual do cliente.

---

## 4. Dívidas dos dois sistemas (independentes desta decisão)

Levantadas na investigação. Nenhuma bloqueia o desenho de contas conectadas — mas duas são
urgentes por si só.

### Urgente: escalação de privilégio no mw-api

Três peças encadeadas:

| # | Onde | O quê |
|---|---|---|
| 1 | `src/enterprises/router.py:171` | `POST /enterprises` exige só `get_current_user` — qualquer JWT válido cria empresa |
| 2 | `src/enterprises/router.py:66-93` | `_require_enterprise_admin` é `return` vazio, com TODO admitindo "TEMPORARILY PERMISSIVE" |
| 3 | `src/admin/router.py:62` | `require_admin` aceita `primary_role == "system_admin"` de **qualquer** empresa |

Juntas, permitem que qualquer conta autenticada vire admin de plataforma e alcance
`/admin/*` (CRUD de plantas, rotação do token de ingestão, `user_plants`, backfill),
`/internal-board`, `/admin/collectors`, `modbus-probes`, `logger-credentials` e
`weather-import`. A correção está no próprio arquivo, comentada.

### Urgente: senha mestra no meuPlano

`dev_master_login_ok` (`services/meuacesso/auth.py:66-75`) entra em qualquer conta ativa com
uma senha fixa (default `"urulua"`). Está neutralizada pela flag `MEUACESSO_AUTH_ENABLED`,
mas o código continua no repositório, a um erro de variável de ambiente de distância. O
próprio comentário pede remoção antes de produção.

### Não urgentes, mas registradas

**meuWatt:** sem revogação de JWT (token vazado vale até 30 dias); `is_active` existe mas
nenhum endpoint o escreve — não há como desativar uma conta; sem recuperação de senha
self-service; sem auditoria de login; Google OAuth cria conta no primeiro acesso, sem
allowlist de domínio; papéis em string livre, sem enum, cada módulo declarando o seu.

**meuPlano:** sem segundo fator; sem bloqueio por tentativas; `impersonate` sem registro em
tabela (só um claim no JWT); rota não mapeada em `route_permissions.py` fica liberada a
qualquer usuário autenticado.

**Onde cada um é forte** — vale registrar, porque a intuição costuma errar:

- **meuWatt autentica melhor**: PBKDF2 com 600 mil iterações, TOTP com anti-replay atômico e
  códigos de recuperação, Google OAuth, rate limit no login, anti-enumeração.
- **meuPlano autoriza incomparavelmente melhor**: 151 permissões granulares, ~600 regras
  rota→permissão, papéis editáveis por organização com teto delegado, e tenancy por usina em
  quatro eixos (quem comanda, quem paga, quem executa, com que escopo).

Nenhuma dessas camadas se move nesta decisão. Cada produto continua autenticando e
autorizando do seu jeito; o Gestão Solar apenas se conecta aos dois.

---

## 5. Ordem de execução

| Ordem | O quê | Onde | Por quê |
|---|---|---|---|
| 1 | Corrigir a escalação de privilégio | mw-api | Segurança ativa, independe de tudo |
| 2 | Remover a senha mestra de desenvolvimento | meuPlano | Idem |
| 3 | CNPJ + UC nos dois cadastros, preenchidos à mão | os dois | Uma tarde de trabalho; muda o que a tela de conciliação precisa adivinhar |
| 4 | `gs_users` + `gs_conexoes` + login próprio | BFF | Base do Gestão Solar |
| 5 | Conexão pelo caminho A (conta existente) | BFF + meuPlano | O fluxo do meuPlano já existe; é registrar mais um aplicativo |
| 6 | Fluxo equivalente no meuWatt | mw-api | Adaptar o device flow para emitir token renovável |
| 7 | Conexão pelo caminho B (provisionar conta) | BFF + os dois | Depende de decidir como a organização/usinas são atribuídas |
| 8 | Tela de conexões + conciliação de usinas | app + BFF | Fecha o primeiro acesso |

Os itens 1 e 2 são independentes e podem ser feitos hoje. O item 3 vem antes da tela de
conciliação de propósito: com CNPJ e UC preenchidos, a tela sugere com confiança em vez de
adivinhar por nome.

O caminho A (item 5) entrega o produto funcionando; o caminho B (item 7) é conforto para
cliente novo e pode esperar.
