# A porta dos sistemas da família (Plano Casa GS, 24/11/2026)

O meuWatt, o meuPlano, o meuGuarda e o TermoVision falam com o GS pelo **servidor**, em nome de quem está com a tela
aberta. Código: `bff/app/api/v1/interno_sistemas.py` (e `interno_termovision.py`, o mapa do TermoVision). Testes:
`tests/test_interno_sistemas.py`, `tests/test_interno_maquina.py`, `tests/test_dados_da_usina.py`,
`tests/test_interno_termovision.py`. O índice de dispositivos: `interno_dispositivos.py`, `services/dispositivos.py`,
`tests/test_interno_dispositivos.py`.

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
  e a sessão do passe valendo. **Encerrar as sessões dela no GS encerra a do sistema também.** As únicas rotas que a
  chave abre sozinha são as da porta da máquina (abaixo), que não leem nada de pessoa: a leitura das usinas ligadas ao
  sistema e o índice de dispositivos, que é a única ESCRITA que a chave faz sozinha (só as referências de dispositivo
  do próprio sistema, só nas usinas ligadas a ele).
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
| `PATCH /usinas/{gs}` | Muda os dados básicos (`nome`, `endereco`, `cidade`, `uf`, `latitude` + `longitude` juntas, `kwp`). Quem pode: a O&M da usina e o administrador da plataforma, que entraram no sistema pelo GS nos últimos 30 dias. Resposta: `{usina, alterados}`. Cada campo mudado vai ao histórico com quem, de qual sistema, o antes e o depois. O `kwp` da usina ligada ao meuWatt não muda por aqui (abaixo): outro número é **400** e nada do pedido é gravado. |
| `POST /usinas` | **Registra a usina criada no sistema** (`{nome, referencia, cidade?, uf?, endereco?, latitude?, longitude?, kwp?}`; a `referencia` é o slug no meuWatt, o número no meuPlano ou o código no TermoVision; o meuGuarda usa as do GS e recebe 403). Respostas: **201** `criada` (nenhuma parecida; a que só existe no TermoVision nasce fora do aplicativo); **202** `a_confirmar` + `parecidas` (o gerente decide no oem-gs › Usinas); **200** `ligada` (devolve a usina do GS) ou `descartada`; **409** a usina já é de outra empresa. Pedir de novo é idempotente e é como o sistema sabe o que o gerente decidiu. |
| `GET /usinas/{gs}/mapa/objetos` | O mapa do GS (o do meuWatt) para o "Importar do GS" do TermoVision. |
| `GET /usinas/{gs}/mapa/itens` | **Os itens do mapa** para o TermoVision (fase 2 do mapa novo, 25/11/2026): tudo o que existe na usina, no mapa ou não. `{pode_editar, lido_em, itens: [{ref, tipo, nome, pai, detalhe, geometria, meuwatt: {objeto, slot_id | string_number | transformer_id | relay_id}, alterado_por, alterado_em}]}`. Refs estáveis: `trafo:<id>`, `inv:<slot_id>` (pai: o trafo), `str:<slot_id>:<n>` (pai: o inversor), `rele:<relay_id>` (pai: o trafo; o Geral sem pai), `novo:<uuid>` (a subestação criada pela tela) e `obj:<id>` (desenhado sem equipamento ligado). Tipos e formas: subestação Polygon; relé, trafo e inversor Point; string Polygon ou LineString. Lê quem vê a usina na lista do GS, pela sessão do passe (`X-Sessao-GS`); `pode_editar` só para a O&M e a plataforma. Sem a leitura do meuWatt, 502. |
| `PUT /usinas/{gs}/mapa/itens/{ref}` · `DELETE …/{ref}` | Põe, move (`{geometria, antes}`) e tira (`{antes}`) o item, como a pessoa (o token DELA no meuWatt). O `antes` é a geometria que a tela viu (nula = fora do mapa): o meuWatt confere numa transação e, se outra pessoa mexeu depois, **409** `{detail, item}` com o item como está. A mesma geometria de novo é 200 sem mudar, e tirar o que já saiu é 200: o pedido repetido é inofensivo. A subestação nova vem com `novo:<uuid>`, `tipo: "subestacao"` e `nome`; o ref fica para sempre (no `origem` do objeto, `gs-item:novo:<uuid>`), e mandar de novo não cria outra. Respostas: 200 `{item}` (o tirado volta sem geometria; a subestação tirada, `item: null`), 403 para quem não é da O&M ou sem a conexão própria com o meuWatt, 404 para o ref que não existe. |
| `GET /usinas/{gs}/mapa/cabos` · `PUT …` | **Os cabos das strings** (26/11/2026), só o TermoVision. GET (quem vê a usina): o `{strings: [{slot_id, string_number, mais_m, menos_m, total_m, secao_mm2, gerado_em, origem}]}` do meuWatt. PUT (a O&M, com o token DELA no meuWatt): `{gerado_em (com fuso, senão 400), secao_mm2 \| null, strings: [{slot_id, string_number, mais_m, menos_m}]}` → `{gravadas, novas, trocadas}`; tudo ou nada, a string fora do cadastro volta **422** com a frase de lá; o mesmo de novo não duplica. Sem resposta do meuWatt, 502 ("PODEM ter sido gravados"). |
| `POST /usinas/{gs}/mapa` · `DELETE /usinas/{gs}/mapa?termovision=` | Liga e desliga o mapa do TermoVision (só o TermoVision; a O&M com entrada pelo GS nas últimas 12 h). |
| `POST /passe/termovision` | O passe do TermoVision para o mapa embutido no meuWatt e no meuPlano: `{assertion, expira_em}`. Só para quem tem o TermoVision liberado e entrou no sistema que pede pelo GS, ela mesma, nas últimas 12 h. |

## O kWp da usina ligada ao meuWatt vem do meuWatt (26/11/2026)

No meuWatt a potência da usina é a soma das strings cadastradas, e é ela que entra na taxa de desempenho. Por isso,
na usina com `meuwatt: {slug}`:

- O GS **guarda** o número de lá em `kwp` (não lê na hora). Quem grava é a conferência diária
  (`services/conferencia.py`, no motor, 1×/dia e a cada deploy): quando o `total_capacity_kwp` do meuWatt é um número
  positivo e difere do guardado em mais de 0,01, ele entra, com `atualizado_em` novo e uma linha no histórico em nome
  do meuWatt, sem pessoa. meuWatt fora do ar, sem número ou com zero: o guardado fica. A usina recém-ligada recebe o
  número na conferência seguinte.
- `PATCH /usinas/{gs}` (e a tela Dados do oem-gs) **recusa** o `kwp` diferente do guardado: **400** "O kWp desta usina
  vem do meuWatt, calculado pelas strings cadastradas lá: mude as strings no meuWatt. Nada foi alterado." O pedido
  inteiro é recusado (os outros campos que vieram junto não são gravados). O mesmo número de novo passa. Só o
  próprio meuWatt (`X-Sistema: meuwatt`) o manda por esta rota.
- `GET /usinas` e a porta da máquina continuam devolvendo o `kwp` guardado, que agora é o do meuWatt: o meuWatt o
  recebe de volta igual.
- A usina que não está no meuWatt segue como antes: `kwp` opcional, editável no GS e pelos sistemas.

## A porta da máquina (só a chave, sem pessoa)

`GET /api/v1/interno/maquina/usinas[?alteradas_desde=]`. Para a rotina do servidor do sistema, sem ninguém na tela,
manter a cópia dele do vínculo (o meuWatt preencher e conferir o número do GS de cada usina, por exemplo).

- **Quem chama:** o servidor do meuWatt, do meuPlano ou do TermoVision, só com `X-Sistema` + `X-Chave-Interna`. Os
  cabeçalhos de pessoa não são lidos (mandar não muda nada). Sem a chave certa, o mesmo **401** "Chave inválida.". O
  meuGuarda usa o número do GS e não tem usina ligada a ele: **403**.
- **O que volta:** `{usinas: [...], desligadas: [...]}`. Em `usinas`, todas as usinas do índice ligadas AO SISTEMA QUE
  CHAMA, de qualquer empresa, também as desligadas no aplicativo (`ativo` falso): `{gs, codigo: "GS-0006", nome,
  meuwatt: {slug} | meuplano: {id} | termovision: {codigo}, cidade, uf, kwp, endereco, latitude, longitude, ativo,
  atualizado_em}`. Das três referências vem só a de quem chama.
- **O que não volta, de propósito:** a empresa, a proprietária, a mesma usina nos outros sistemas (nem como nulo) e
  qualquer coisa de pessoa. A chave continua sem falar por ninguém: ela só lê as linhas do índice que são dela.
- **Reler só o que mudou:** `alteradas_desde` e `X-GS-Lido-Em` são os do `GET /usinas` (mande o `X-GS-Lido-Em`, menos
  1 min, no próximo `alteradas_desde`; sem fuso, é de Brasília). A usina volta quando qualquer dado da linha dela mudou,
  também o que esta rota não mostra (o vínculo com outro sistema, a proprietária): pode voltar igual.
- **O vínculo que saiu:** com `alteradas_desde`, `desligadas` traz `{gs, codigo, meuwatt: {slug} (a referência que
  saiu), desligada_em}` para cada referência do sistema que deixou aquela usina do GS de lá para cá (do histórico por
  campo). Apliquem as `desligadas` antes das `usinas`: a referência que mudou de usina sai de uma e vem na outra. Na
  leitura inteira (sem `alteradas_desde`) `desligadas` vem vazia: o que não veio em `usinas` não está ligado.
- **O limite:** as `desligadas` valem o que o histórico guarda. A usina apagada do GS leva o histórico junto, e um
  vínculo mudado direto no banco não deixa linha. Por isso, além de reler o que mudou, façam uma **leitura inteira de
  tempos em tempos** (uma vez por dia basta) e tirem o que não veio.
- **O registro:** uma linha por sistema e hora no Registro de acessos, sem pessoa ("Servidor do meuWatt (sem pessoa)"),
  que só a plataforma vê.

## O índice de dispositivos (porta da máquina, 26/11/2026)

O índice de usinas um andar abaixo (`gs_device_links`): o GS dá um número a cada POSIÇÃO de equipamento da usina (o
lugar: "transformador 1", "inversor da posição 3"; não o aparelho, que pode ser trocado), e cada sistema guarda esse
número ao lado do registro dele. Nesta fase: transformadores e inversores, vindos do meuWatt.

- **O número:** `gd` (inteiro), mostrado como `GD-000017` (seis dígitos; o da usina é `GS-0006`). É para sempre: o
  dispositivo que some e volta tem o mesmo.
- **A grafia padrão da referência do meuWatt** é a que as rotas do mapa já usam: `trafo:<transformers.id>` e
  `inv:<inverter_slots.id>` e, desde 27/11/2026, `str:<inverter_slots.id>:<n>` (a string; abaixo),
  `rele:<relays.id>`, `est:<weather_stations.id>` e `ssu:<ssu_readers.id>` (abaixo). Esta é A grafia: em
  minúsculas, sem espaço, com o número de lá. Os tipos: `transformador` e `inversor` agora; reservados `string`,
  `rele`, `estacao`, `medidor`, `stringbox` e `gateway`.
- **Quem chama:** o servidor do sistema, com `X-Sistema` + `X-Chave-Interna` (sem pessoa). A LISTA (`PUT
  …/dispositivos`) é só do **meuWatt**; os NÓS (`PUT …/dispositivos/nos`, abaixo) são só do **meuPlano**; os dois leem
  (`GET`). Chave errada: **401** "Chave inválida.". meuGuarda: **403**. Quem não entra naquela rota: **403** ("…ainda
  não recebe do meuPlano…" na lista; "Quem liga nós aos dispositivos é o meuPlano…" nos nós; o TermoVision ainda não
  entra em nenhuma). Usina que não existe ou que não está ligada ao sistema que chama: **404** "Pessoa ou usina não
  encontrada." (a mesma frase).
- **É uma escrita só com a chave, e é estreita:** o sistema grava só a coluna DELE no dispositivo (o meuWatt a
  referência dele, o meuPlano o nó dele), só nas usinas ligadas a ele; nunca um dado da usina (nem o `atualizado_em`
  dela), nunca a referência de outro sistema. O meuPlano não cria dispositivo nem muda nome, tipo ou pai.

### `PUT /api/v1/interno/maquina/usinas/{gs}/dispositivos`

A lista INTEIRA das posições daquela usina no sistema que chama (até 5000):

```json
{"dispositivos": [
  {"ref": "trafo:41", "tipo": "transformador", "nome": "TR-01", "pai": null},
  {"ref": "inv:99", "tipo": "inversor", "nome": "INV12", "pai": "trafo:41"}
]}
```

`pai` é a `ref` de outro dispositivo da MESMA lista (em qualquer ordem), ou nulo (pode faltar). Tudo numa transação:

- `ref` nova: nasce, com um `gd` novo. `ref` conhecida nesta usina: o `nome`, o `tipo` e o `pai` são atualizados se
  mudaram; a que estava ausente volta. O `atualizado_em` só anda no que mudou: a mesma lista de novo não muda nada.
- **Ausente:** o dispositivo desta usina que NÃO veio na lista nunca é apagado: fica `ativo: false`, com a data da
  primeira lista em que faltou (`ausente_desde`, no banco). A lista vazia põe todos como ausentes.
- **409:** uma `ref` que já é de OUTRA usina do GS (ativa ou ausente lá) recusa o pedido inteiro, e o `detail` diz
  quais ("Já em outra usina do GS: inv:99. Um dispositivo não muda de usina sozinho: nada foi gravado."). Também 409
  quando dois pedidos gravam a mesma `ref` ao mesmo tempo ("…mande de novo.").
- **A string é uma POSIÇÃO** (27/11/2026): a do inversor mais o número da ENTRADA CC em que ela está ligada. O
  número tem buracos (não é a ordem numa lista). `{"ref": "str:111:7", "tipo": "string", "nome": "String 7",
  "pai": "inv:111"}`: o `pai` é obrigatório e é o inversor DELA (a mesma vaga da `ref`), na mesma lista. A string que
  sai da entrada fica ausente, como qualquer dispositivo; a mesma entrada de novo volta com o mesmo `gd`.
- **O relé, a estação e o medidor da fronteira** (27/11/2026), na mesma lista inteira, com as mesmas garantias (um
  `gd` para sempre, ausente quando não vem, nunca apagado):

  | `tipo` | `ref` | `pai` |
  |---|---|---|
  | `rele` | `rele:<relays.id>` | o `trafo:<id>` dele, na mesma lista, ou nulo (o relé da usina) |
  | `estacao` | `est:<weather_stations.id>` | o `trafo:<id>` dela, na mesma lista, ou nulo |
  | `medidor_ssu` | `ssu:<ssu_readers.id>` | sempre nulo (é da usina) |
  | `gateway` | `gw:<gateways.id>` | sempre nulo (28/11/2026: o gateway serve a usina; vários transformadores pendem de um) |

  A lista SEM nenhum deles segue valendo como antes. Quando eles já existem no GS e a lista vem sem eles, ficam
  ausentes, como qualquer dispositivo que não veio. O `medidor` (sem `_ssu`) segue reservado para o medidor de energia.
- **422:** a `ref` fora da grafia (`^(trafo|inv|rele|est|ssu|gw):\d+$` ou `^str:\d+:\d+$`; qualquer outro prefixo), o
  `tipo` que não é o da `ref`, a `ref` repetida, o `pai` que não está na lista (ou é o próprio), a string cujo `pai`
  não é o `inv:` da vaga dela, o relé ou a estação cujo `pai` não é um `trafo:`, o medidor da fronteira ou o gateway com `pai`;
  nesses o `detail` é uma frase. O corpo fora do formato (campo a mais, `nome`
  vazio, mais de 5000) é o 422 do FastAPI, com `detail` em lista.

Resposta **200**:

```json
{"dispositivos": [
   {"gd": 17, "codigo": "GD-000017", "tipo": "transformador", "nome": "TR-01", "pai": null, "ativo": true,
    "meuwatt": {"ref": "trafo:41"}},
   {"gd": 18, "codigo": "GD-000018", "tipo": "inversor", "nome": "INV12", "pai": 17, "ativo": true,
    "meuwatt": {"ref": "inv:99"}}],
 "criados": 2, "alterados": 0, "ausentes": 0}
```

`pai` na resposta é o `gd` do pai. A lista traz todos os dispositivos da usina com referência do sistema que chama,
também os ausentes (`ativo: false`), na ordem do `gd`. Os contadores dizem o que ESTE pedido fez: `criados` (ganharam
número), `alterados` (os que já existiam e mudaram de nome, tipo ou pai, ou voltaram) e `ausentes` (ficaram ausentes
agora; os que já estavam não contam).

### `GET /api/v1/interno/maquina/usinas/{gs}/dispositivos`

A mesma lista (`{"dispositivos": [...]}`), sem os contadores. Mesmas recusas (401, 403, 404). Para o **meuWatt**, como
acima (só os dispositivos com referência dele, só o bloco `meuwatt`). Para o **meuPlano**, na usina ligada a ele
(`meuplano: {id}`), TODOS os dispositivos da usina, com os dois blocos, como na resposta dos nós (abaixo).

### `PUT /api/v1/interno/maquina/usinas/{gs}/dispositivos/nos` (o meuPlano liga os nós dele, 27/11/2026)

O meuPlano não cria dispositivo: ele diz "o meu nó N é a posição que vocês conhecem como `inv:99`", e o GS guarda o nó
naquela linha. Os pares vêm já casados por uma pessoa na tela do meuPlano (não há fila de confirmação aqui). Só o
meuPlano chama, na usina ligada a ele. Até 5000 pares:

```json
{"nos": [{"ref": "inv:99", "node_id": 555}, {"ref": "trafo:41", "node_id": 500}]}
```

`ref` é a do meuWatt na grafia PADRÃO (`trafo:<n>`, `inv:<n>` e, desde 27/11/2026, `str:<vaga>:<n>`, `rele:<n>`,
`est:<n>`, `ssu:<n>` e `gw:<n>`; quem chama
traduz a dele). **As strings são ligadas AUTOMATICAMENTE** (o dono, 27/11/2026): quem casa a string com o nó é a rotina
do meuPlano, que conhece a árvore dele, e manda os pares por esta rota (num pedido só de strings, uns 400 por usina);
ninguém confirma uma a uma, e a tela do gerente só mostra a conta por inversor. As regras são as mesmas de qualquer
dispositivo. `node_id` é o `nodes.id` do
meuPlano (inteiro ≥ 1) ou nulo; o campo é obrigatório. Tudo numa transação, e o mesmo pedido de novo não muda nada:

- O dispositivo DESTA usina com aquela `ref` (ativo ou ausente) ganha o nó; o `atualizado_em` só anda se mudou.
- **A `ref` sem dispositivo nesta usina não é erro:** volta em `sem_dispositivo` e nada é gravado para ela.
- **Um nó é uma posição só.** O nó que já está em OUTRO dispositivo (de qualquer usina) recusa o pedido inteiro:
  **409** "O nó 555 já está no dispositivo GD-000021. Um nó é uma posição só: desligue-o de lá no mesmo pedido. Nada
  foi gravado." A não ser que o MESMO pedido tire aquele dispositivo do nó (dando-lhe outro nó ou nulo): é a troca, e
  passa. Também 409 quando dois pedidos ligam o mesmo nó ao mesmo tempo ("…mande de novo.").
- **Não vir não é desligar.** O dispositivo com nó que NÃO veio no pedido fica como está (o vínculo é com a posição e
  atravessa a troca do aparelho no meuPlano); a lista vazia não muda nada. Desligar é explícito:
  `{"ref": "inv:99", "node_id": null}`.
- **422:** a mesma `ref` duas vezes, o mesmo `node_id` duas vezes (dois nulos não contam), a `ref` fora da grafia
  padrão; nesses o `detail` é uma frase. O corpo fora do formato (campo a mais, `node_id` ausente, zero ou não
  inteiro, mais de 5000) é o 422 do FastAPI, com `detail` em lista.
- A lista do meuWatt (`PUT …/dispositivos`) não mexe no nó: o dispositivo que fica ausente lá guarda o nó dele.

Resposta **200**:

```json
{"dispositivos": [
   {"gd": 19, "codigo": "GD-000019", "tipo": "transformador", "nome": "TR-01", "pai": null, "ativo": true,
    "meuwatt": {"ref": "trafo:41"}, "meuplano": {"node_id": 500}},
   {"gd": 21, "codigo": "GD-000021", "tipo": "inversor", "nome": "INV12", "pai": 19, "ativo": true,
    "meuwatt": {"ref": "inv:99"}, "meuplano": {"node_id": 555}},
   {"gd": 22, "codigo": "GD-000022", "tipo": "inversor", "nome": "INV13", "pai": 19, "ativo": true,
    "meuwatt": {"ref": "inv:100"}, "meuplano": null}],
 "ligados": 2, "desligados": 0, "sem_dispositivo": ["inv:777"]}
```

`dispositivos` são TODOS os da usina (para o meuPlano guardar o `gd` em cada nó e ver o que ainda está sem nó), também
os ausentes, na ordem do `gd`. `meuplano` é nulo quando a posição não tem nó; `meuwatt` seria nulo num dispositivo que
o meuWatt não conhece (hoje não existe). Os contadores dizem o que ESTE pedido fez: `ligados` (ganharam nó ou trocaram
de nó), `desligados` (perderam o nó); o que já estava assim não conta.

**O registro:** uma linha por sistema, usina e hora no Registro de acessos, sem pessoa ("Servidor do meuWatt (sem
pessoa)"): `leitura` para o GET, `gravacao` para os dois PUT.

### Quem casa o nó com o dispositivo (27/11/2026)

O meuPlano não tem os inversores nem os transformadores casados com o meuWatt (os vínculos de lá são só de rede),
então a rota dos nós acima não liga nada sozinha. Quem diz qual nó é qual dispositivo é o **gerente da O&M**, no
oem-gs › Usinas › Equipamentos (`GET /api/empresa/usinas/{id}/dispositivos` e `PUT …/dispositivos/nos`, com a sessão
dele; não é rota dos sistemas). O GS lê os nós da usina no meuPlano com a conta da empresa
(`GET /api/v1/meuacesso/usinas/{usina_id}/nodes`), mostra como candidatos só os `transformador_potencia` e os
`inversor`, e propõe o par (pelo número; senão pela ordem; o inversor só dentro do transformador cujo nó se sabe). O
relé, a estação e o medidor da fronteira também são ligados ali pela pessoa, sem sugestão (candidatos: `rele_protecao`
e `rele_temperatura`; `estação solarimétrica`, `piranometro` e `datalogger`; `medidor_energia`), e o gateway
(candidato: `gateway`). A string, não. A
sugestão nunca é gravada sem o Salvar da pessoa. O que ela salva cai na mesma coluna (`mp_node_id`), com a mesma
regra (um nó é uma posição só), e o meuPlano o recebe na leitura dele (`GET …/dispositivos`, o bloco `meuplano`).

## "Parecida"

O nome igual depois de tirar acento, "UFV" e pontuação, um contido no outro, a mesma palavra marcante com o mesmo
número, ou o difflib ≥ 0,85; ou a menos de 1,5 km. Número diferente dos dois lados separa ("Monte Sião 6" e "7").
Quem decide se é a mesma é sempre o gerente (`services/dados_da_usina.parecidas`).
