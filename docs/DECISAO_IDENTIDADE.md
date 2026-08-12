# Identidade e conciliação de usinas entre os três produtos

> Decisão de arquitetura. Escrita em 2026-08-12, a partir de levantamento do código dos
> dois sistemas. Cobre duas perguntas que aparecem juntas mas são separadas: **quem é o
> usuário** (login unificado) e **qual usina é qual** (conciliação de cadastro).

---

## 0. Bloqueador: corrigir antes de qualquer unificação

Existe uma escalação de privilégio ativa no mw-api. Três peças encadeadas:

| # | Onde | O quê |
|---|---|---|
| 1 | `src/enterprises/router.py:171` | `POST /enterprises` exige só `get_current_user` — qualquer JWT válido cria empresa |
| 2 | `src/enterprises/router.py:66-93` | `_require_enterprise_admin` é `return` vazio, com TODO admitindo "TEMPORARILY PERMISSIVE" |
| 3 | `src/admin/router.py:62` | `require_admin` aceita `primary_role == "system_admin"` de **qualquer** empresa |

Encadeadas, permitem que qualquer conta autenticada se torne admin de plataforma e alcance
`/admin/*` (CRUD de plantas, rotação do token de ingestão, `user_plants`, backfill),
`/internal-board`, `/admin/collectors`, `modbus-probes`, `logger-credentials` e
`weather-import`. `/admin/control*` escapa por ter gate de root separado.

**Por que bloqueia a unificação:** o Gestão Solar traz donos de usina — confiança muito
menor que funcionários — para o mesmo pool de login. Hoje o estrago fica dentro de casa;
depois, cada cliente novo herda o caminho.

A correção está no próprio arquivo, comentada: restaurar a consulta a
`enterprise_employees` em `_require_enterprise_admin` e proteger `create_enterprise`.

---

## 1. Quem é mais robusto: depende da camada

A intuição de que "o login do meuWatt é mais parrudo" está certa — **para autenticação**.
Para autorização é o oposto, e por uma margem larga. São duas camadas diferentes e a
decisão precisa tratá-las separadamente.

### Autenticação — provar quem é a pessoa

| | meuWatt | meuPlano |
|---|---|---|
| Hash de senha | PBKDF2-SHA256, **600.000 iterações** (OWASP 2023), comparação constante-tempo | bcrypt com custo padrão |
| Segundo fator | **TOTP RFC 6238**, anti-replay atômico por `(user_id, period)`, 10 códigos de recuperação hasheados, segredo em AES-GCM | nenhum |
| Login social | Google OAuth com validação de assinatura e audience | nenhum |
| Login de dispositivo | Device flow tipo RFC 8628 (app de campo) | PKCE + `device_token` revogável (app desktop) — **melhor que o do meuWatt: tem refresh** |
| Rate limit no login | 10/min por IP (slowapi) | nenhum |
| Anti-enumeração | sim, mensagem única para usuário inexistente e senha errada | parcial |
| Recuperação de senha | **não existe self-service** — depende de admin humano | código de 6 dígitos por e-mail, 20 min, uso único |

**Fraquezas que os dois compartilham:** sem refresh token no fluxo web, sem revogação de
JWT (nem `jti` nem blacklist), sem bloqueio por tentativas, sem auditoria de login.

**Fraquezas só do meuWatt:** não existe endpoint que desative uma conta (`is_active` existe
no schema, nada escreve nele); Google OAuth sem allowlist de domínio, com criação implícita
de conta no primeiro acesso; JWT de até 30 dias sem kill-switch.

**Fraqueza só do meuPlano:** `dev_master_login_ok` — senha mestra de desenvolvimento
(default `"urulua"`) que entra em qualquer conta ativa. Está neutralizada pela flag
`MEUACESSO_AUTH_ENABLED`, mas o código continua no repositório, a um erro de env var de
distância. O próprio comentário pede remoção antes de produção, e isso não foi feito.

### Autorização — decidir o que a pessoa pode

Aqui a diferença é estrutural, não de grau.

**meuPlano** tem um sistema de controle de acesso que é, em si, um produto:

- **151 permissões granulares** no formato `{modulo}.{recurso}.{acao}`
- **~600 regras** mapeando rota → permissão, com dependency global aplicando em toda requisição
- **RBAC por organização**: cada cliente/prestadora tem papéis próprios e editáveis, com teto
  de permissões definido por quem administra (`Owner.permission_ceiling`) — administração delegada
- **Tenancy por usina** (`tenancy.py`): três papéis (`GESTORA` / `PRESTADORA` / `PROPRIETARIA`)
  em quatro eixos ortogonais — quem comanda, quem paga, quem executa, com que escopo. Resolve
  casos reais do negócio ("a Eldorado paga, a Splendor opera"). Isso não é RBAC, é ABAC sobre
  o recurso usina.
- **Nível de cofre L0–L5**, ortogonal ao resto, para revelação de credenciais

**meuWatt** tem RBAC grosso: cinco papéis (`admin`, `system_admin`, `plant_owner`,
`operator`, `field_employee`) sem enum no banco, cada módulo declarando seu próprio conjunto
aceito, sem fonte única de verdade. Granularidade por ação só existe em `/control/*`.

---

## 2. Decisão: identidade no meuWatt, autorização onde já está

> **O meuWatt vira o provedor de identidade dos três produtos. Cada produto continua dono
> da sua própria autorização.**

O erro a evitar é tratar isso como "migrar o login do meuPlano". As 151 permissões, o RBAC
por organização e a tenancy por usina **não têm equivalente em provedor de identidade
nenhum** — nem no meuWatt, nem em Auth0, Keycloak ou SSO corporativo. Eles não sabem o que
é "usina", "organização gestora" ou "nível de cofre". Essa camada fica onde está.

O que migra é só a faixa fina de **autenticação**: provar que quem chegou é o Renan.

### A ponte já existe no código

`AppUser.external_id` (`meuPlano/backend/app/models/meuacesso.py:2258`) foi criado com o
comentário *"guardará o id do Supabase Auth quando o login for ligado"* — e **nunca foi
usado**, porque o login acabou implementado localmente. É exatamente o campo que faltava.

### Fluxo

```
    Usuário toca "Entrar com meuWatt" no meuPlano
                    │
                    ▼
    meuWatt autentica (senha + TOTP, ou Google)
                    │  devolve JWT do meuWatt
                    ▼
    meuPlano valida o JWT contra a chave pública/segredo do meuWatt
                    │
                    ▼
    Resolve AppUser por external_id = users.id do meuWatt
       ├─ achou      → segue
       ├─ não achou, mas e-mail bate → vincula (grava external_id) e segue
       └─ não achou nada → recusa (sem criação implícita — ver abaixo)
                    │
                    ▼
    Emite o JWT PRÓPRIO do meuPlano, com as 151 permissões
    resolvidas pelo RBAC e pela tenancy de lá
```

O meuPlano continua emitindo o próprio token. As `Depends(...)` internas, o
`enforce_permissions`, o `usina_scope` — nada disso muda. Só a porta de entrada muda.

**Sem criação implícita de conta.** No meuWatt, o Google OAuth cria conta no primeiro login.
Isso não pode se propagar: um usuário só existe no meuPlano se alguém o cadastrou lá, com
organização e papel. O vínculo por e-mail resolve o caso comum (a pessoa já existe nos dois);
o resto é convite explícito.

### O que o meuWatt precisa ganhar antes de virar provedor

Nenhum é grande, mas nenhum é opcional para um sistema do qual três produtos dependem:

| Falta | Por quê |
|---|---|
| **Corrigir a escalação de privilégio** (seção 0) | um provedor comprometido compromete os três |
| **Revogação de sessão** (`jti` + blacklist, ou TTL curto + refresh) | hoje um token vazado vale até 30 dias, sem kill-switch |
| **Desativar conta de fato** | o campo `is_active` existe e nada escreve nele — não há como cortar um ex-funcionário |
| **Recuperação de senha self-service** | hoje depende de admin humano; não escala para clientes finais |
| **Auditoria de login** | nenhum registro de login, falha ou emissão de token existe hoje |
| **Allowlist de domínio no Google** | ou pelo menos separar "autenticou" de "tem acesso a algo" |

---

## 3. Conciliação de usinas

### O problema

Nenhum dos dois sistemas tem chave para casar a mesma usina:

| | meuWatt (`plants`) | meuPlano (`usinas`) |
|---|---|---|
| Identidade | `id`, `name` (único), `slug` | `id`, `name` |
| CNPJ da usina | não existe | não existe |
| Número de UC | não existe | não existe |
| Código externo | `fusionsolar_station_code` (só para plantas Huawei) | `plant_code` — **nullable, não único, nunca preenchido** |
| Coordenadas | `latitude`, `longitude` | `latitude`, `longitude` |
| Empresa com CNPJ | `companies.cnpj` (sem CRUD, `company_name` hardcoded como `None`) e `enterprises.cnpj` | `Owner.document` (texto livre, não único) |

O `plant_code` do meuPlano foi criado "p/ reconciliação futura" e está vazio. É a única
pista, e é fraca.

### O que NÃO fazer

**Casar automaticamente por nome, coordenada ou potência.** "Porto Ferreira", "UFV Porto
Ferreira" e "Porto Ferreira I" são digitados por pessoas diferentes em momentos diferentes.
Duas usinas do mesmo cliente ficam a 200 m uma da outra. Um casamento errado silencioso
mistura a geração de uma usina com a manutenção de outra — e ninguém percebe até alguém
questionar um relatório.

### A decisão, dado o cenário real

São **menos de 20 usinas**, e a origem varia: às vezes nasce no meuWatt, às vezes no
meuPlano. Nesse cenário, automação de casamento é resolver o problema errado.

**O vínculo é explícito, humano e mora no BFF do Gestão Solar** (`gs_plant_links`, já
criado). O Gestão Solar é o produto que enxerga os dois lados — é o lugar natural do
cadastro que os une.

A tela de conciliação mostra as duas listas lado a lado e **sugere** pares por proximidade
de nome, distância geográfica e potência declarada. A sugestão é uma dica visual; quem
confirma é uma pessoa. Uma usina pode ficar deliberadamente sem par — é o caso do cliente
que só contratou monitoramento.

### O passo que resolve para sempre

Introduzir uma **chave natural** nos dois cadastros: **CNPJ da SPE** e **número da UC na
distribuidora**. Com menos de 20 usinas, preencher isso à mão é trabalho de uma tarde, e
elimina o problema para todas as usinas futuras — inclusive as que entrarem por importação.

Ordem sugerida:

1. Adicionar `cnpj` e `uc_numero` em `plants` (mw-api) e em `usinas` (meuPlano), ambos
   opcionais no schema mas obrigatórios no formulário de cadastro novo.
2. Preencher as usinas existentes à mão.
3. `gs_plant_links` passa a ser derivado: quando os dois lados têm o mesmo CNPJ + UC, o
   vínculo é sugerido com confiança alta; sem isso, cai no casamento manual.

---

## 4. Ordem de execução

| Ordem | O quê | Onde | Por quê primeiro |
|---|---|---|---|
| 1 | Corrigir a escalação de privilégio | mw-api | Segurança ativa. Independe de tudo. |
| 2 | Preencher CNPJ + UC nas usinas existentes | os dois | Uma tarde de trabalho que destrava a conciliação |
| 3 | `gs_plant_links` + tela de conciliação | BFF | Destrava a Fase 1 do Gestão Solar |
| 4 | Revogação, desativação, auditoria de login | mw-api | Pré-requisito para o meuWatt virar provedor |
| 5 | "Entrar com meuWatt" no meuPlano, via `external_id` | meuPlano | O login unificado propriamente dito |
| 6 | Gestão Solar passa a autenticar só pelo meuWatt | BFF | Simplifica o BFF: cai a tentativa dupla de login |

O Gestão Solar **não precisa esperar** pelos itens 4-6: o BFF já foi desenhado para tentar
os dois upstreams e guardar os dois vínculos. Quando a unificação acontecer, ele passa a
tentar um só — é simplificação, não reescrita.
