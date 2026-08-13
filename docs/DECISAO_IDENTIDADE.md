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

---

## 2b. O que foi construído — TOKEN PESSOAL (13/08/2026)

> Feito. Esta seção descreve o que existe hoje; as seções acima registram o desenho que
> levou até aqui.

O caminho escolhido não foi o fluxo de autorização pelo navegador, e sim o **token pessoal
colado à mão** — mais simples e suficiente enquanto quem conecta é o gestor, não o cliente
final. A pessoa gera um token na própria conta de cada produto, copia, e cola em
**Painel → Conexões**. O fluxo de autorização pelo navegador continua sendo o caminho certo
para quando o CLIENTE conectar as contas dele pelo app; a máquina de tokens construída
agora é a base dos dois.

### O formato, e por que ele não é opaco

```
mw_pat_<32 caracteres de sorteio><6 de verificação>     meuWatt
mp_pat_<32 caracteres de sorteio><6 de verificação>     meuPlano
```

O valor viaja pela área de transferência de um humano que tem **dois** tokens parecidos e
**duas** caixas parecidas na tela. Trocá-los de lugar é o erro provável, e o mais caro de
diagnosticar: o servidor responde 401, exatamente como responderia a um token revogado,
expirado, ou de conta desativada.

Por isso o valor se descreve:

- o **prefixo** diz de qual produto ele é — quem recebe responde "este é um token do
  meuPlano, e o campo é do meuWatt" em vez de "credencial recusada";
- o **dígito verificador** (CRC-32 do sorteio, em base62) pega a cópia truncada.

As duas conferências são locais. O painel recusa o engano **sem gastar uma chamada de
rede**, e com a frase que resolve.

### Onde cada peça vive

| Peça | meuWatt | meuPlano |
|---|---|---|
| Formato e regra | `src/api_tokens/token_format.py` · `service.py` | `app/services/meuacesso/api_tokens.py` |
| Tabelas | `user_api_tokens` + `user_api_token_events` (migration 131) | `app_api_tokens` + `app_api_token_events` (migration `jt00pat11ok0`) |
| Rotas | `POST/GET/DELETE /auth/tokens` | `POST/GET/DELETE /api/v1/meuacesso/auth/tokens` |
| Entra na autenticação | `src/auth/dependencies.py::get_current_user` | `services/meuacesso/auth.py::get_current_principal` |
| Tela de geração | menu do usuário → Tokens de acesso | Minha conta → Tokens de acesso |

O formato é **implementado três vezes** (os dois produtos e `bff/app/core/tokens_produto.py`),
de propósito: são repositórios que sobem separados, e importar um do outro criaria um
acoplamento de deploy para economizar quarenta linhas. O que segura a divergência são os
testes — `tests/test_api_tokens.py` nos dois produtos e `tests/test_conexao_por_token.py`
no BFF carregam o formato esperado e falham em vermelho se um lado mudar sozinho.

### As três garantias que sustentam o desenho

1. **O valor em claro existe uma vez.** O banco guarda SHA-256; nenhum endpoint relê o
   token. Quem perde, revoga e emite outro — é o único comportamento possível, e o certo.
2. **Token não emite token.** Emitir e revogar exigem sessão de verdade. Sem essa trava, um
   token vazado emitiria outro antes de você cortar o primeiro, e revogar não significaria
   nada.
3. **Token não herda o modo de desenvolvimento.** No meuPlano, com
   `MEUACESSO_AUTH_ENABLED` desligada uma sessão comum vira `admin_sistema` com todas as
   permissões. O token resolve o principal **real** do dono em qualquer configuração —
   senão o Gestão Solar teria acesso total por causa de uma variável de ambiente.

### O que o painel faz com isso

Gravar exige passar por três camadas, da mais barata para a mais cara: **formato** (local),
**identidade** (`/auth/me` — de quem é o token) e **alcance** (quantas usinas ele enxerga).
Se qualquer uma falhar, **nada é gravado** e a conexão anterior continua de pé — gravar
primeiro e testar depois deixaria o gestor com as duas quebradas e nenhum caminho de volta.

Mostrar o **dono** não é enfeite: colar o token da pessoa errada deixa o cartão verde com o
escopo menor, e a falta só aparece semanas depois como usina sumida na tela de um cliente.

`gs_integracao_eventos` guarda o histórico por ponte. O estado diz se funciona agora; o
histórico diz desde quando parou — que é o que separa "trocaram o token na quinta" de "o
produto saiu do ar", dois cartões vermelhos idênticos.

### Desconectar ≠ revogar

Remover o token no painel só faz o Gestão Solar parar de usá-lo. Ele **continua válido** no
produto de origem, e é lá que precisa ser revogado de verdade — por quem o emitiu. A tela
diz isso, porque a diferença é a que importa quando alguém desconfia de um vazamento.

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

| Ordem | O quê | Onde | Estado |
|---|---|---|---|
| 1 | Corrigir a escalação de privilégio | mw-api | **pendente** — segurança ativa, independe de tudo |
| 2 | Remover a senha mestra de desenvolvimento | meuPlano | **pendente** — idem |
| 3 | CNPJ + UC nos dois cadastros, preenchidos à mão | os dois | pendente — uma tarde de trabalho; muda o que a conciliação precisa adivinhar |
| 4 | `gs_users` + login próprio | BFF | feito |
| 5 | Token pessoal no meuPlano | meuPlano | **feito** (13/08/2026) — ver seção 2b |
| 6 | Token pessoal no meuWatt | mw-api | **feito** (13/08/2026) — ver seção 2b |
| 7 | Conexão pelo caminho B (provisionar conta) | BFF + os dois | pendente — depende de decidir como organização/usinas são atribuídas |
| 8 | Tela de conexões (gestor) + conciliação de usinas | painel + BFF | conexões **feito**; conciliação feita |
| 9 | Conexão pelo CLIENTE, no app | app + os dois | pendente — reusa a máquina de tokens do item 5/6 |

Os itens 1 e 2 continuam sendo os mais urgentes do documento e **não foram tocados** pelo
trabalho de tokens. Vale reler a seção 4: os dois são falhas ativas, não dívidas de estilo.

O item 3 vem antes da conciliação de propósito: com CNPJ e UC preenchidos, a tela sugere
com confiança em vez de adivinhar por nome.

O item 9 é o que fecha o desenho original desta decisão — hoje quem conecta é o gestor,
colando o token pelo painel; o cliente conectar as próprias contas pelo app é o passo
seguinte, e a emissão/validação/revogação de que ele precisa já existe.
