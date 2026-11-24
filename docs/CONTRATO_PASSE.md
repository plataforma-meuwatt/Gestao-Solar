# Contrato do passe do GS (login único)

24/11/2026, "Plano Casa GS" (o doc do Renan: https://claude.ai/artifact/A2gFXPrRHDWze9JLRp3FZg). O GS é o pai e o
único autenticador: meuWatt, meuPlano, meuGuarda e TermoVision recebem a pessoa por um **passe** assinado pelo GS.
Quem muda este contrato avisa os outros terminais antes. O GS guarda o registro de cada passe entregue
(`gs_acessos`, a auditoria dos acessos); o que a pessoa faz dentro de cada sistema fica no registro de lá.

## O passe

JWT RS256, assinado com a chave privada do GS (`GS_SSO_PRIVATE_KEY`); cada sistema confere com a pública, que já está
configurada em todos, cada um na sua variável: `MW_GS_PUBLIC_KEY` (meuWatt), `MP_GS_PUBLIC_KEY` (meuPlano),
`GS_SSO_PUBLIC_KEY` (meuGuarda), `TV_GS_SSO_PUBLIC_KEY` (TermoVision). Vale **2 minutos** e **uma vez** (`jti`).

| Campo | O que é | Desde |
| --- | --- | --- |
| `iss` | `gestao-solar` | v1 |
| `aud` | o sistema: `meuwatt`, `meuplano`, `meuguarda`, `termovision`. O de um não vale no outro | v1 |
| `sub` | o número da conta no GS (texto). É a identidade; nunca o e-mail | v1 |
| `jti`, `iat`, `exp` | uso único e validade | v1 |
| `email`, `name` | o que o cadastro do GS diz | v1 |
| `v` | `2` | v2 |
| `apelido` | o login no GS | v2 (já ia no meuGuarda e no TermoVision) |
| `perfil` | `administrador`, `atendimento`, `gestor_empresa`, `tecnico`, `cliente` | v2 |
| `empresa_id` | a empresa de O&M em que a pessoa está operando (nulo = plataforma) | v2 |
| `usinas` | as usinas que a pessoa vê, `[{"gs": 12, "id": <no sistema>}]`: no meuWatt o `id` é o slug, no meuPlano o id da usina, no meuGuarda e no TermoVision o número do GS. Para a O&M, só as da empresa da sessão (`empresa_id`); para o dono, as concedidas. Lista vazia = nenhuma | v2 |
| `todas_as_usinas` | `true` para a plataforma (administrador, atendimento): vê todas, e o passe não leva a lista | v2 |
| `usinas_fora` | `true` quando a lista não veio (o GS não conseguiu ler agora, ou ela passaria do teto de tamanho): NÃO é "nenhuma"; o sistema segue com a regra dele | v2 |
| `portao` | `cliente`, `empresa`, `tecnico`, `painel` | meuGuarda e TermoVision |
| `meuguarda` / `termovision` | se o gerente liberou o acesso (falso = recusar) | meuGuarda e TermoVision |
| `meuplano_id` | o id da pessoa no meuPlano | TermoVision |

Os campos v2 vão em TODOS os passes; quem ainda não os usa segue com o que já lia. A regra de quem vê qual usina passa
a ser do GS (decisão D1): o sistema que adotar `usinas` lê esta lista, nunca uma cópia.

## Como a pessoa chega com o passe

### 1. A janelinha (o botão "Entrar com o GS" de cada sistema)

1. O sistema abre uma janela pequena:
   `window.open('https://gestao.solar/entrar/<sistema>?janela=1&volta=' + encodeURIComponent(<endereço da página>), 'gs', 'width=480,height=640')`.
   A `volta` tem de ser de um dos endereços do sistema (lista abaixo): outra é recusada.
2. Na janela, quem já entrou no GS só passa (não digita nada); quem não entrou digita o login (ou o e-mail) e a senha
   do GS.
3. A janela manda à página que a abriu
   `postMessage({tipo: 'gs-passe', produto: '<sistema>', assercao: '<jwt>'}, <origem da volta>)` e fecha.
4. O sistema escuta `message`, **confere `event.origin`** (só `https://gestao.solar`, `https://app.gestao.solar`,
   `https://oem.gestao.solar` e `https://adm.gestao.solar`) e `data.tipo === 'gs-passe'`, e troca o passe pela sessão
   dele na rota de sempre (abaixo).

Janela bloqueada pelo navegador: abrir o mesmo endereço sem `janela=1` na própria aba; a pessoa volta para a `volta`
com `#assercao=<jwt>` no fragmento (o caminho 2).

### 2. Pela navegação (os botões do GS, a janela bloqueada)

O GS manda o navegador para a entrada do sistema com `#assercao=<jwt>` no **fragmento** (não vai a servidor nem a log).
Os botões no alto do GS (portal, oem, adm) usam este caminho, em aba nova, para os sistemas liberados à pessoa
(`GET /api/sessao/produtos`).

### 3. Servidor a servidor (a tela de entrar do próprio sistema, enquanto existir)

`POST https://api.gestao.solar/api/v1/auth/produtos/<sistema>/assercao {"apelido": "<login ou e-mail>", "senha": "…"}`
→ `{"assertion": "<jwt>", "nome": "…"}`. Senha errada: 401 `Login ou senha inválidos` (o e-mail de duas contas com a
mesma senha: 401 pedindo o login). Empresa desativada: 403.

**Limites de senha errada** (valem em toda porta do GS que confere senha):

- 10 erros em 15 min do mesmo login vindo do mesmo IP: 429 para esse par por 15 min (de outro lugar, a pessoa entra).
- 30 erros em 15 min do mesmo IP: 429 para esse IP em todas as portas.
- **Repasse pelo servidor** (o meuGuarda e o TermoVision repassam o login e a senha das pessoas de lá): o sistema se
  identifica com `X-Sistema: meuguarda|termovision` e `X-Chave-Interna: <a chave dele>` (a do meuGuarda é a
  `MEUGUARDA_CHAVE_INTERNA` que ele já usa com o GS; a do TermoVision, `TERMOVISION_CHAVE_INTERNA`, no cofre) e manda o
  IP da pessoa em `X-Usuario-IP` (obrigatório com a chave: sem ele, 400). Com a chave, os dois limites e o registro de
  acessos valem para o IP da pessoa, e o total de erros de cada login vindo daquele sistema tem teto de 30 em 15 min
  (um IP inventado a cada tentativa não fura o limite). Sem a chave, na TRANSIÇÃO, o endereço da KingHost fica só com o
  limite por login e lugar (como era antes): um teto por IP ali deixaria estranhos pela tela do meuGuarda trancarem
  todo mundo de lá. A KingHost roda outros projetos, e endereço não é confiança: quando os dois sistemas mandarem a
  chave, o GS liga o teto de 30 também para o endereço da KingHost sem chave (`TETO_IP_CASA_SEM_CHAVE=30`).
- O alvo é a janelinha, que vem do navegador da pessoa e não passa pelo servidor do sistema.

O passe e o seu tamanho: com a lista de usinas sem nome, cabe folgado nos 8.000 caracteres que o meuGuarda e o
TermoVision aceitam; acima de 4.000 caracteres de lista o GS manda `usinas_fora` no lugar.

## Onde cada sistema troca o passe pela sessão (já existe)

| Sistema | Rota | Endereços aceitos como `volta` |
| --- | --- | --- |
| meuWatt | `POST /auth/gestao-solar` (mw-api) | `app.meuwatt.com.br` |
| meuPlano | `POST /api/v1/meuacesso/auth/external/gestao-solar` | `app.meuplano.solar` |
| meuGuarda | `POST /api/entrar/gs` | `meuguarda.gestao.solar` |
| TermoVision | `POST /api/conta/gs` | `termovision.gestao.solar`, `app.termovision.tech` |

## O que muda em cada sistema (fase 1)

- **Todos:** o botão "Entrar com o GS" abre a janelinha (caminho 1). A sessão de cada sistema passa a ser curta e se
  renova pelo GS (fase 1, depois do botão).
- **meuPlano e TermoVision:** só o GS. O login próprio fica no código, desligado, quando todos tiverem entrado pelo GS.
  O app do celular (meuPlano) e o app do PC (TermoVision) também.
- **meuWatt:** guarda o login próprio e ganha o botão.
- **meuGuarda:** já é só o GS; ganha a janelinha.

## A volta conferida ao abrir

A página `gestao.solar/entrar/<sistema>` chama `GET /api/sessao/<sistema>/volta?volta=<endereço>` ao abrir: com um
endereço que não é do sistema (204 = é; 400 = não é), ela mostra só o erro, sem o formulário. Só o 400 barra: a
rede que falhou não tranca ninguém. O painel (oem-gs, adm-gs) faz o mesmo antes de mandar ao login. A conferência que vale
continua sendo a da entrega do passe (as rotas que emitem o passe recusam a volta estranha antes de olhar a senha).

## O mapa do TermoVision e as usinas do GS ("Enviar ao GS", servidor a servidor)

O mapa mora no TermoVision; o GS guarda só o vínculo (`gs_plant_links.tv_codigo`, um código por usina e uma usina por
código). Ainda nenhuma tela do GS lê o mapa do TermoVision: isso vem com o `/embutir` (fase 3 do plano).

Quem chama é o servidor do TermoVision, com `X-Sistema: termovision` e `X-Chave-Interna` (a mesma chave do repasse do
login; sem ela configurada no GS, 503), em nome de quem está com a tela aberta: `X-Usuario-GS` (o `sub` do passe dela)
e `X-Empresa-GS` (o `empresa_id` do passe; sem ele, vale a empresa de origem da pessoa). A chave sozinha não basta:
- a pessoa tem de ter entrado no TermoVision pelo GS nas últimas 12 h, ela mesma (pela janelinha, pelo botão ou pela
  tela de vocês): a entrada que o bot e o conector do GS fazem por ela não conta. Sem isso, 403 "entre de novo pelo GS";
- só a equipe da O&M (gerente e técnico) usa estas rotas, inclusive o GET; o dono e a plataforma recebem 403;
- `X-Empresa-GS` tem de ser uma empresa ativa da pessoa (o GS confere contra as empresas dela, não contra o passe).

Pessoa (inexistente, desativada, sem o TermoVision), empresa ou usina que não serve: 404 com a mesma frase. A lista e o
ligar valem para as usinas ativas; o desligar vale também para a usina desativada no GS (o mapa não fica preso).

- `GET /api/v1/interno/usinas[?ids=12,15]` → `[{gs, nome, empresa, meuwatt: {slug} | null, meuplano: {id} | null,
  termovision: {codigo} | null, cidade, uf, endereco, latitude, longitude}]`. `ids` sem nenhum número válido = `[]`.
- `POST /api/v1/interno/usinas/<gs>/mapa {termovision: <código>}` → a usina, como no GET. O código tem de 1 a 40
  letras, números, `-` ou `_`. Idempotente pelo valor (o mesmo código de novo responde o mesmo; `X-Pedido` não é
  necessário). O mesmo mapa já ligado a outra usina, ou outro mapa já ligado a esta, é 409 (o nome da outra usina só
  quando é da mesma empresa). Dois pedidos ao mesmo tempo: um grava, o outro recebe 409. Campos a mais no corpo
  (`voo`, `camadas`) são ignorados: o GS não os guarda.
- `DELETE /api/v1/interno/usinas/<gs>/mapa?termovision=<código>` → desliga (o "Desligar do GS"). Já desligada,
  responde a usina (repetir não é erro); ligada a OUTRO código, 409.
