# A porta dos sistemas da família (Plano Casa GS, 24/11/2026)

O meuWatt, o meuPlano, o meuGuarda e o TermoVision falam com o GS pelo **servidor**, em nome de quem está com a tela
aberta. Código: `bff/app/api/v1/interno_sistemas.py` (e `interno_termovision.py`, o mapa do TermoVision). Testes:
`tests/test_interno_sistemas.py`, `tests/test_dados_da_usina.py`, `tests/test_interno_termovision.py`.

## Quem chama e por quem

| Cabeçalho | O quê |
|---|---|
| `X-Sistema` | `meuwatt`, `meuplano`, `meuguarda` ou `termovision` |
| `X-Chave-Interna` | a chave DAQUELE sistema (`<SISTEMA>_CHAVE_INTERNA` no GS; uma por sistema, nunca repetida) |
| `X-Usuario-GS` | o `sub` do passe (o número da conta no GS) |
| `X-Empresa-GS` | o `empresa_id` do passe (opcional; sem ele, a empresa de origem da pessoa) |
| `X-Sessao-GS` | o `sessao_gs` do passe: a sessão da pessoa NAQUELE sistema |
| `X-Usuario-IP` | o IP da pessoa (obrigatório no passe do TermoVision) |

- Sem a chave certa: **401** "Chave inválida." (nada diz qual chave está configurada).
- A chave sozinha não fala por ninguém. A pessoa tem de estar ativa, com aquele sistema liberado no GS, a empresa ativa
  e a sessão do passe valendo. **Encerrar as sessões dela no GS encerra a do sistema também.**
- **Transição:** sem `X-Sessao-GS`, vale quem entrou pelo GS (no GS ou naquele sistema, ela mesma, com o IP dela) nos
  últimos 60 dias. Mandem o `X-Sessao-GS` (vem em todo passe novo, no campo `sessao_gs`): a transição acaba quando os
  quatro mandarem.
- Pessoa, usina ou empresa que não serve: **404** "Pessoa ou usina não encontrada." (a mesma frase sempre). Na
  renovação, 404 = a sessão acaba lá.
- Cada leitura entra no Registro de acessos do GS (uma linha por pessoa, sistema e hora).

## O passe (a asserção da entrada pelo GS)

Além do de sempre (apelido, perfil, portão, empresa, o que o gerente liberou), o passe v2 leva:
- `sessao_gs`: a sessão da pessoa NAQUELE sistema (60 dias). Guardem e mandem como `X-Sessao-GS`.
- `usinas`: `[{gs, id}]`, o `id` no sistema que recebe. A O&M leva todas as usinas da empresa da sessão, também as fora
  do aplicativo (a régua do `GET /usinas`); o dono leva as concedidas e ligadas. Ou `todas_as_usinas` (a plataforma), ou
  `usinas_fora` (o GS não conseguiu montar a lista, ou ela passou do teto do passe: não é "nenhuma"; leiam o `GET
  /usinas-da-pessoa`).
- `proprietaria`: `{id, nome, meuplano: {id}}` do dono de usina, quando há.

## As rotas (prefixo `/api/v1/interno`)

| Rota | O quê |
|---|---|
| `GET /usinas-da-pessoa` | A **renovação**: `{gs, apelido, nome, email, perfil, empresa_id, sistemas, proprietaria, usinas \| todas_as_usinas \| usinas_fora, lido_em, sessao_gs}`. As usinas vêm como no passe v2 (`[{gs, id}]`, o `id` no sistema que pergunta), a lista inteira (sem o teto do passe). Com `X-Sessao-GS`, volta um `sessao_gs` novo, da MESMA sessão, valendo 60 dias a contar de agora: guardem no lugar do outro (quem usa todo dia não sai no 60º dia). Sugestão: reler de 10 em 10 min e encerrar a sessão no 404 com a frase "Pessoa ou usina não encontrada." (ela não muda sem aviso). |
| `GET /usinas[?ids=&alteradas_desde=]` | As usinas que a pessoa vê. A plataforma vê todas, a O&M as da empresa (também as fora do aplicativo, com `ativo` falso), o dono as concedidas. Cada usina: `{gs, codigo: "GS-0006", nome, empresa, empresa_id, meuwatt: {slug}, meuplano: {id}, termovision: {codigo}, cidade, uf, kwp, endereco, latitude, longitude, ativo, atualizado_em, proprietaria: {id, nome, meuplano: {id}}}`. O cabeçalho `X-GS-Lido-Em` é o relógio do GS: mande-o (menos 1 min) no próximo `alteradas_desde`. Sem fuso, `alteradas_desde` é de Brasília. |
| `GET /usinas/{gs}` | Uma usina. |
| `PATCH /usinas/{gs}` | Muda os dados básicos (`nome`, `endereco`, `cidade`, `uf`, `latitude` + `longitude` juntas, `kwp`). Quem pode: a O&M da usina e o administrador da plataforma, que entraram no sistema pelo GS nos últimos 30 dias. Resposta: `{usina, alterados}`. Cada campo mudado vai ao histórico com quem, de qual sistema, o antes e o depois. |
| `POST /usinas` | **Registra a usina criada no sistema** (`{nome, referencia, cidade?, uf?, endereco?, latitude?, longitude?, kwp?}`; a `referencia` é o slug no meuWatt, o número no meuPlano ou o código no TermoVision; o meuGuarda usa as do GS e recebe 403). Respostas: **201** `criada` (nenhuma parecida; a que só existe no TermoVision nasce fora do aplicativo); **202** `a_confirmar` + `parecidas` (o gerente decide no oem-gs › Usinas); **200** `ligada` (devolve a usina do GS) ou `descartada`; **409** a usina já é de outra empresa. Pedir de novo é idempotente e é como o sistema sabe o que o gerente decidiu. |
| `GET /usinas/{gs}/mapa/objetos` | O mapa do GS (o do meuWatt) para o "Importar do GS" do TermoVision. |
| `GET /usinas/{gs}/mapa/itens` | **Os itens do mapa** para o TermoVision (fase 2 do mapa novo, 25/11/2026): tudo o que existe na usina, no mapa ou não. `{pode_editar, lido_em, itens: [{ref, tipo, nome, pai, detalhe, geometria, meuwatt: {objeto, slot_id | string_number | transformer_id | relay_id}, alterado_por, alterado_em}]}`. Refs estáveis: `trafo:<id>`, `inv:<slot_id>` (pai: o trafo), `str:<slot_id>:<n>` (pai: o inversor), `rele:<relay_id>` (pai: o trafo; o Geral sem pai), `novo:<uuid>` (a subestação criada pela tela) e `obj:<id>` (desenhado sem equipamento ligado). Tipos e formas: subestação Polygon; relé, trafo e inversor Point; string Polygon ou LineString. Lê quem vê a usina na lista do GS, pela sessão do passe (`X-Sessao-GS`); `pode_editar` só para a O&M e a plataforma. Sem a leitura do meuWatt, 502. |
| `PUT /usinas/{gs}/mapa/itens/{ref}` · `DELETE …/{ref}` | Põe, move (`{geometria, antes}`) e tira (`{antes}`) o item, como a pessoa (o token DELA no meuWatt). O `antes` é a geometria que a tela viu (nula = fora do mapa): o meuWatt confere numa transação e, se outra pessoa mexeu depois, **409** `{detail, item}` com o item como está. A mesma geometria de novo é 200 sem mudar, e tirar o que já saiu é 200: o pedido repetido é inofensivo. A subestação nova vem com `novo:<uuid>`, `tipo: "subestacao"` e `nome`; o ref fica para sempre (no `origem` do objeto, `gs-item:novo:<uuid>`), e mandar de novo não cria outra. Respostas: 200 `{item}` (o tirado volta sem geometria; a subestação tirada, `item: null`), 403 para quem não é da O&M ou sem a conexão própria com o meuWatt, 404 para o ref que não existe. |
| `POST /usinas/{gs}/mapa` · `DELETE /usinas/{gs}/mapa?termovision=` | Liga e desliga o mapa do TermoVision (só o TermoVision; a O&M com entrada pelo GS nas últimas 12 h). |
| `POST /passe/termovision` | O passe do TermoVision para o mapa embutido no meuWatt e no meuPlano: `{assertion, expira_em}`. Só para quem tem o TermoVision liberado e entrou no sistema que pede pelo GS, ela mesma, nas últimas 12 h. |

## "Parecida"

O nome igual depois de tirar acento, "UFV" e pontuação, um contido no outro, a mesma palavra marcante com o mesmo
número, ou o difflib ≥ 0,85; ou a menos de 1,5 km. Número diferente dos dois lados separa ("Monte Sião 6" e "7").
Quem decide se é a mesma é sempre o gerente (`services/dados_da_usina.parecidas`).
