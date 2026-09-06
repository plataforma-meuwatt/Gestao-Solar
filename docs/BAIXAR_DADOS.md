# Baixar dados — a planilha bruta da usina

> A aba **Downloads** que nasceu no meuWatt, atravessada para o Gestão Solar. O cliente
> escolhe período, horário, passo e o que quer em cada um dos quatro blocos, e leva um
> `.xlsx` para o Excel.
>
> Tela: `/usinas/:id/energia/dados` · rótulo **"Baixar dados"** · família `geracao`.
> Rotas: `bff/app/api/v1/exportacao.py` · cliente: `bff/app/clients/meuwatt.py`.
> Conferência: `bff/scripts/conferir_exportacao.py`.

Este documento é curto de propósito nas partes que o código já explica, e longo nas que
custaram medição. **Todo número aqui foi medido**, e cada bloco diz quando e contra o quê.

---

## 1. As duas rotas

| | |
|---|---|
| `GET /api/v1/energia/dados/opcoes?usina_id=` | o que ESTA usina tem: skids/inversores, estação coluna a coluna, leitores, sistema, retenção e os tetos |
| `POST /api/v1/energia/dados/arquivo?usina_id=` | o `.xlsx` da seleção, **em fluxo** |

Do outro lado são `GET /plants/{slug}/exports/raw/options` e `POST /plants/{slug}/exports/raw`
(`mw-api/src/exports/`). **O XLSX não é remontado aqui**: nasce no meuWatt — que é quem tem as
séries e a aba *Leia-me* com unidades, fontes e avisos — e os bytes só atravessam.

**O `slug` nunca vem do navegador.** O cliente manda `usina_id` (o id do nosso `PlantLink`);
`_usina_no_escopo` resolve o vínculo dentro do escopo dele e `_slug_do_upstream` tira o slug do
**nosso banco**, conferindo-o contra `^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$` antes de virar URL. É
a lição de `documents.py`, onde um `../../../admin/users` normalizava e devolvia bytes com
credencial de admin.

**`POST` que só LÊ.** O método é por TAMANHO DA SELEÇÃO — quinhentas chaves de série não cabem
numa query string —, nunca por efeito: nada é criado, alterado ou apagado, nem aqui nem lá (a
rota de lá é `resolve_plant_access`, sem escrita). Fica dito para o dia em que entrar auditoria
por método e este verbo mentir sozinho.

---

## 2. O contrato do pedido

```jsonc
{
  "inicio": "2026-08-05", "fim": "2026-09-04",   // datas em BRT
  "hora_inicio": "00:00", "hora_fim": "23:59",   // do 1º e do último dia; fim INCLUSIVO do
                                                 // minuto; ignorados quando o passo é "1d"
  "passo": "native | 5m | 15m | 1h | 1d",

  // os quatro blocos são OPCIONAIS — bloco ausente não entra no arquivo
  "inversores": { "variaveis": ["geracao","potencia","status","paradas"],
                  "agrupamento": "lista | skid",
                  "series": ["slot:170", "inv:7"] },   // null = todas (ver abaixo)
  "estacao":    { "variaveis": ["poa","ghi","temp_modulo","temp_ambiente","vento",
                                "temp_ambiente_rele"] },
  "fronteira":  { "variaveis": ["energia"], "agrupamento": "leitor | usina" },
  "sistema":    { "variaveis": ["pr","produtividade"], "agrupamento": "skid | usina" }
}
```

**`series: null` ≠ lista com todas as séries de hoje.** Nulo quer dizer *"não mexi"*: o inversor
comissionado no meio do período entra sozinho. Uma lista explícita congela o conjunto no que a
tela viu. Por isso o campo é opcional e nunca ganha um default de lista vazia — que o upstream
leria como "nenhuma série", um arquivo sem colunas.

Duas variáveis dependem do passo, e o servidor recusa o pedido inteiro (400) quando não bate:

- **`status`** só existe no passo **nativo** (é um texto por leitura);
- **`paradas`** é descartada no nativo (ela precisa de um balde para somar minutos);
- o bloco **`sistema`** inteiro não existe no nativo (PR e produtividade precisam de intervalo).

---

## 3. Os cinco tetos e as duas retenções

Vêm do servidor, em `opcoes.limites` e `opcoes.retencao` — **nunca de uma constante nossa**: dois
números para a mesma pergunta divergiriam no primeiro ajuste feito do outro lado.

| Passo | Teto de dias por arquivo |
|---|---|
| `native` | 7 |
| `5m` | 31 |
| `15m` | 92 |
| `1h` | 366 |
| `1d` | 366 |

Mais o **orçamento de células: 2 000 000** (`max_celulas`), estimado como baldes × colunas.

**Retenção — que não é limite do arquivo, é ausência de dado** (medido em Porto Ferreira,
05/09/2026):

| Fonte | Alcance | Desde |
|---|---|---|
| snapshots (inversores, estação, sistema) | 183 dias | `2026-03-06` |
| SSU (medidor de fronteira) | 730 dias | `2024-09-05` |

⚠ **A checagem de retenção inteira mora dentro de `if step != "1d"`**: o **total por dia não tem
prazo**. É a saída que a tela oferece quando o período pedido é antigo demais para o passo fino.

> **A premissa dos "366 dias × 1 h com tudo" não existe.** O teto do passo de 1 h é 366 dias, mas
> a retenção de snapshots é de 183 — o pedido volta `fora_da_retencao` em 2,2 s. 366 dias em passo
> sub-diário só é alcançável **com o bloco fronteira sozinho** (SSU retém 730 dias), e aí o
> arquivo é pequeno.
>
> ⚠ **Não há UM pior caso: há um platô.** Medido em 05/09/2026, **92 dias × 15 min com todos os
> blocos custa o mesmo** que 31 dias × 5 min — 31,7 s de cabeçalho contra 29,7 s, e 1,71 MiB
> contra 1,96 MiB. É a conta de baldes × colunas que empata (8 928 × 64 contra 8 832 × 64), e
> não coincidência. O passo **nativo** de 7 dias é o terceiro do platô (28,0 s). Quem medir só o
> de 5 min está medindo o platô inteiro, mas não sabe disso — daí a nota.

---

## 4. O balde de pedidos — por IP, não por token

`mw-api/src/shared/rate_limit.py` é o arquivo inteiro:

```python
limiter = Limiter(key_func=get_remote_address)
```

`@limiter.limit("10/minute")` está **só no POST**. Consequências que valem para o produto:

1. **`GET /opcoes` não é limitado** — a tela pode abrir e reabrir à vontade.
2. **São 10 exportações por minuto para TODOS os clientes somados**, porque todo o portal sai
   pelo mesmo egress do Railway. O décimo primeiro cliente do minuto levaria um 429 que ele não
   provocou. É o que o semáforo `_VAGAS = asyncio.Semaphore(2)` existe para conter, junto com a
   recusa antecipada feita na tela a partir de `limites`/`retencao`.
3. **Pedido inválido também queima vaga** (levantado em 05/09/2026): dez pedidos com a data
   invertida — 400 imediato, sem gerar arquivo nenhum — esgotam o balde, e o 11º, válido, leva
   429. O semáforo **não** protege contra isso: recusas atravessam depressa e devolvem a vaga na
   hora. Por isso a tela impedir o pedido impossível deixou de ser cortesia e virou defesa.
4. O 429 de lá vem como `{"error": …}`, **sem `Retry-After`** — e `detalhe_do_upstream` lê
   `detail`/`message`/`erro`, não `error`. Daí `_espere()` escrever a própria frase e pôr o
   `Retry-After: 60` (o teto da janela, não o tempo exato de espera).

> ⚠ **Achado para reportar ao meuWatt, não para usar:** o balde muda com `X-Forwarded-For`, então
> o limite é contornável forjando o cabeçalho (provado em 05/09 com o mesmo PAT: o 429 vira 200).
> Explorar seria abuso de parceiro e quebraria no dia em que consertarem.

---

## 5. Os números medidos

Todos de **Porto Ferreira** (7,4 MWp · 20 inversores em 5 skids · 5 leitores · estação com POA e
GHI · relé de temperatura), período **2026-08-05 → 2026-09-04** (31 dias) a cada **5 min**, pela
**rota do BFF com sessão de cliente**, em **05/09/2026**. Reproduzível com
`python scripts/conferir_exportacao.py`.

### 5.1 Tempo e tamanho

| Pedido | Cabeçalho | Corpo | Total | Bytes |
|---|---|---|---|---|
| **pesado** — 4 blocos, 20 inversores em lista | 29,7–41,2 s | 0,5–1,6 s | **~31 s** | 2 054 395 – 2 068 560 (**~1,96 MiB**) |
| **92 d × 15 min**, 4 blocos (o platô, medido em 05/09) | 31,7 s | 1,5 s | ~33 s | 1 714 525 (1,63 MiB) |
| **dois pesados AO MESMO TEMPO** (a mw-api tem 1 worker) | 57,5 e 57,8 s | 0,5–0,7 s | **58,5 s os dois** | 2 054 395 cada |
| **por skid** — 2 de 5 skids, só geração | 11,2–13,7 s | 0,0–0,6 s | ~13 s | 175 133 (0,17 MiB) |
| 92 dias × 5 min (acima do teto) | — | — | **1,4–2,5 s** | 400 `passo_excede_limite` |
| `GET /opcoes` | — | — | 1,2–5,0 s | 3 178 |

> ⚠ **A faixa é ampla e instável de propósito na tabela acima: 29,7 s a 41,2 s no MESMO pedido**,
> em oito corridas de dois dias diferentes. Quem tomar o menor número como "o tempo" vai
> dimensionar errado — foi o que aconteceu com `_ESPERA_MAX_SEG`, que nasceu 45 s por contar UMA
> geração à frente na fila. **Quem espera na fila tem DUAS pela frente** (as duas vagas), e elas
> **não correm juntas**: o `render.yaml` da mw-api fixa `workers=1`, e dois pedidos pesados
> disparados juntos terminaram em 57,5 s e 57,8 s contra 29,7 s do mesmo pedido sozinho. Com
> 45 s, o terceiro cliente esperava e era recusado ~13 s antes de a vaga voltar: o pior dos dois
> mundos. Corrigido para **75 s**, e a fila ganhou teto de GENTE (`FILA_MAX`) — quem chega com
> ela cheia leva a recusa **na hora**, em vez de pagar 75 s para ouvir a mesma frase.

**A espera está toda no cabeçalho**, e isso é um fato do desenho de lá: a mw-api faz
`to_thread(write_xlsx)` e só então responde um `FileResponse` de um temporário
(`Content-Length` presente, `Transfer-Encoding: None`). O corpo transfere em pouco mais de um
segundo depois de trinta parado. **Não existe progresso para medir — existe espera**, e é por
isso que a tela usa barra indeterminada com tempo decorrido à mostra, e não porcentagem.

O prazo do cliente é **explícito** (`connect=5, read=120, write=30`) porque o padrão REPROVA:
`integracoes.cliente_meuwatt` constrói o `MeuWattClient` sem `timeout` e cai nos 30 s da
assinatura, contra ~33 s medidos. Orçamento do BFF: 45 s de fila + 120 s de leitura ≈ 165 s,
dentro dos 180 s que o portal espera.

### 5.2 Memória — o fluxo é fluxo, provado na balança

| | |
|---|---|
| RSS do worker em repouso | ~121 MiB |
| **Pico durante o download de 1,97 MiB** | **+532 a +560 KiB (26–28% do arquivo)** |
| Pico durante o download de 0,17 MiB | +48 a +60 KiB |

Se houvesse buffer, o pico subiria ≥ 100% do arquivo (o corpo residente, mais uma segunda cópia
ao montar a resposta do Starlette). Subiu pouco mais de meio MiB — o tamanho dos pedaços em
trânsito. O contraste importa: `documents.py` **bufferiza** (`arquivo_relatorio() -> bytes` +
`Response(content=…)`), e está certo lá (PDF unitário) e estaria errado aqui.

> ⚠ **Medir a árvore, não o pid.** No Windows o `python.exe` do venv é um redirecionador:
> `python -m uvicorn` cria um processo de 4 MiB que só re-executa o interpretador num FILHO, e é
> o filho (~107 MiB) que serve. A primeira versão desta medição observava só o pai e imprimia
> **"+0 KiB = 0% do arquivo"** — um número que parece a prova perfeita do fluxo e não mede nada.
> O script agora soma a árvore e imprime quais pids observou.

### 5.3 As abas

**pesado** (`agrupamento: lista`):

| Aba | Linhas de dado | Colunas |
|---|---|---|
| Leia-me | 63 | 2 |
| Inversores | **8 928** | **64** |
| Paradas | 7 | 14 |
| Estação | 8 928 | 11 |
| Fronteira | 8 928 | 8 |
| Sistema | 8 928 | 6 |

8 928 = 31 dias × 288 baldes de 5 min. 64 = 20 inversores × 3 (energia, potência, minutos
desligados) + 3 totais da usina + a coluna do instante.

**por skid** (`agrupamento: skid`, 2 de 5 skids, só `geracao`):

| Aba | Linhas de dado | Colunas |
|---|---|---|
| Leia-me | 47 | 2 |
| **Skids** | 8 928 | 4 |

⚠ **Agrupar por skid muda o NOME da aba.** `sheet_inversores` termina em
`Sheet("Inversores" if agr == "lista" else "Skids", …)`. Quem agrupa por skid recebe uma aba
chamada **Skids** — nunca escreva "baixe a aba Inversores" numa tela que oferece os dois
agrupamentos.

### 5.4 A seleção parcial chega do outro lado e muda a soma

É a prova que o dono pediu, e a única que um arquivo bem-formado não dá sozinho: um BFF que
deixasse `series` cair produziria um arquivo com os cinco skids que **abre, tem as abas certas e
parece certo**.

| | |
|---|---|
| Colunas de skid no arquivo | exatamente 2: `SKID-01 · Energia (kWh)`, `SKID-02 · Energia (kWh)` |
| Total da usina **naquele arquivo** | 413 886,509 kWh |
| Soma das duas colunas de skid | 413 886,510 kWh (diferença 0,001 — arredondamento por célula) |
| Total da usina no arquivo **pesado** (20 inversores) | **1 036 780 kWh** |

Ou seja: **"Usina" no arquivo por skid quer dizer "a soma do que você marcou"**, e não a usina
inteira. É o que obriga a tela a dizer, com todas as letras, que *o que você desmarcar também sai
da soma do skid*.

### 5.5 REGRA 0 dentro do arquivo — e o que ela não é

A conferência ingênua ("a linha da meia-noite vem toda vazia") **reprova contra a planilha real**:
21 células preenchidas, todas `Potência média (kW) = 0`. Investigado antes de mexer no teste, e o
resultado é uma distinção que a tela e o suporte precisam conhecer:

| Coluna, à meia-noite | Vem | Porque |
|---|---|---|
| `Energia (kWh)` | **vazia** | o odômetro não anda; a subconsulta `en` filtra `gen > 0` e não produz linha |
| `Potência média (kW)` | **0** | o inversor continua comunicando e **reporta 0 W**; é `AVG(active_power_w)` de leituras que existem |

O zero de potência é **medido**, não coalescido — e a prova é que a coluna também sabe ficar
vazia. Contagem de um único dia (2026-09-03, 288 baldes × 20 inversores):

| Coluna | Vazias | Zeros | Positivos |
|---|---|---|---|
| Potência | 1 138 | 1 743 | 2 879 |
| Energia | 2 806 | 79 | 2 875 |

Se a ausência tivesse virado zero, a coluna de potência **nunca** ficaria vazia — e somá-la no
Excel passaria a contar como "0 kW medido" cada balde em que o inversor simplesmente não falou. O
script guarda os dois lados separadamente, para que a falha diga qual dos dois quebrou.

---

## 6. O escopo — quatro sondas, medidas pela rota

| Quem pergunta | `usina_id` | Resposta |
|---|---|---|
| dono (usuário 2) | 4 · Porto Ferreira | **200** |
| dono | 8 · UFV Leme (sem vínculo com o meuWatt) | **404** `Esta usina não está ligada ao monitoramento.` |
| outra pessoa (usuário 1) | 4 · existe, não é dela | **404** `Usina não encontrada.` |
| outra pessoa | 9999 · não existe | **404** `Usina não encontrada.` |

As duas últimas são **byte a byte idênticas** — conferido no corpo cru, não com dois
`assert status == 404`. É a propriedade que importa: responder "proibido" para a que existe e
"não encontrada" para a que não existe transformaria a rota num oráculo, e um cliente varreria os
ids para saber quantas usinas o sistema tem.

⚠ **"Fora do escopo" não é uma usina especial: é a mesma usina, perguntada por outra pessoa.** No
banco de hoje o dono enxerga as 7 usinas que existem, então esse caminho **só** se exercita com um
segundo usuário. Inventar um id "fora do escopo" para o dono seria montar um cenário que não é o
do sistema, e o verde não valeria nada.

`_usina_no_escopo` (de `plants.py`) e **não** `_link_do_escopo` (de `manutencao.py`): o segundo
exige `mp_usina_id` e recusaria com "esta usina não tem manutenção contratada" — frase e regra de
outro produto. Isto é geração; usina monitorada sem contrato de manutenção tem direito aos
próprios números. Hoje as seis monitoradas também têm meuPlano, o que faria o defeito passar
despercebido por muito tempo.

### O que NÃO sai por esta porta

A resposta do meuWatt traz, em cada leitor, `wh_per_pulse`, `rtc` e `rtp` — a constante de pulso e
as relações de transformação com que se converte pulso em kWh faturado — além do `slug` e do
`name` da usina no sistema deles. **Nada disso atravessa**: `LeitorOut` tem só `id` e `nome`, e
`UsinaOut` sai com o id e o nome DESTE sistema.

Conferido varrendo o **texto cru** dos 3 178 bytes da resposta (e não o objeto já tipado — um
campo extra que escapasse por `model_extra`, ou por um dicionário aberto como `estacao.colunas`,
não apareceria numa checagem de atributos): **zero ocorrências** de `wh_per_pulse`, `rtc`, `rtp`,
do valor do slug e da chave `"slug"`.

---

## 7. A recusa, traduzida

Recusa de regra do meuWatt vira `{"detail": "…", "motivo": "…"}` **achatado**, e não
`HTTPException` (que embrulharia tudo dentro de `detail`): a tela precisa do `motivo` no primeiro
nível para escolher entre `Erro` (com "Tentar de novo") e `Aviso` (sem) — repetir um
`muito_grande` dá exatamente o mesmo resultado, e oferecer o botão seria crueldade.

Vocabulário que atravessa: `periodo_invalido`, `passo_excede_limite`, `fora_da_retencao`,
`bloco_indisponivel`, `sem_blocos`, `muito_grande` — e `muitos_pedidos`, que é nosso (a fila cheia
deste processo e o balde de lá dão a mesma frase, porque para quem pediu é a mesma situação).
Motivo desconhecido chega como `null`: uma palavra crua que a tela não sabe traduzir é pior que
nenhuma.

**O `message` do upstream NÃO é ecoado.** Ele fala em balde, snapshots e SSU — foi escrito para o
operador da mw-api. Quem escreve para o cliente é o portal. Conferido: o 400 de 92 dias volta
`{"detail": "O monitoramento recusou este pedido.", "motivo": "passo_excede_limite"}`.

---

## 8. Produção — o item que estava aberto, e fechou

O dossiê desta leva registrou, com razão, que **o teto do proxy do Railway contra um pedido de
mais de 30 s não tinha sido medido**, porque as rotas não estavam deployadas.

**Medido em 05/09/2026, e o item fecha:**

| | |
|---|---|
| `GET /health` | 200 |
| `GET /openapi.json` | **404** — e isto **não** quer dizer que a rota não existe (ver abaixo) |
| `GET /opcoes` sem credencial | **401** `Não autenticado` → a rota **está montada** |
| `GET /opcoes` com sessão de cliente | **200** em 2,3 s |
| **`POST /arquivo`, pedido pesado (31 d × 5 min, 4 blocos)** | **200 · cabeçalho em 32,3 s · corpo em 0,9 s · 2 068 559 bytes íntegros** |
| `POST /arquivo`, por skid | 200 · 11,2 s |
| as 4 sondas de escopo | idênticas ao local, com os dois 404 byte a byte |

**O edge do Railway (`x-railway-edge: mia1`, `Server: railway-hikari`) aguentou 32,3 s de espera
sem responder e entregou o arquivo inteiro.** O `Content-Length` bateu com o corpo recebido, o que
descarta recodificação no caminho.

**O que continua aberto, com precisão:** sabe-se que **≥ 33 s passa**; o teto exato do edge não
foi encontrado, porque não há como pedir mais tempo sem uma usina maior que Porto Ferreira. Uma
usina que produza um pedido de 60 s ou mais é território não medido.

> ⚠ **Sem `/openapi.json` ≠ sem rota.** `main.py` põe `openapi_url=None if settings.producao`, e a
> primeira versão do script concluiu daí que "a rota não está montada" — sobre uma rota que estava
> no ar. Diagnóstico errado é pior que nenhum: manda consertar o que não está quebrado. O script
> agora, sem catálogo, **sonda** os caminhos conhecidos (404 = ausência; 401 = presente e
> protegida) e diz por qual dos dois caminhos descobriu.

---

## 9. A conferência

```bash
cd bff
PYTHONPATH=. venv/Scripts/python.exe scripts/conferir_exportacao.py            # local
PYTHONPATH=. venv/Scripts/python.exe scripts/conferir_exportacao.py --url https://…  # produção
PYTHONPATH=. venv/Scripts/python.exe scripts/conferir_exportacao.py --provar   # sem rede
```

Sobe um uvicorn próprio em porta livre e fala com ele **por HTTP de verdade** — não
`ASGITransport`: o que se quer provar é o `StreamingResponse` saindo por um socket, com os
cabeçalhos que o navegador vai ler. E é por rodar num processo separado que dá para medir a
memória do worker enquanto os megabytes atravessam.

Baixa **dois** arquivos, abre os dois com `openpyxl` e confere abas, linhas, colunas e somas.
**47 conferências**, todas passando em 05/09/2026 (46 contra produção — a do fluxo é pulada, com o
motivo dito, porque o worker é de outra máquina).

`--provar` não fala com ninguém: alimenta as **mesmas** funções de conferência com oito defeitos
plantados (o slug vazando, o Leia-me faltando, a energia da meia-noite virando zero, a potência
coalescendo a ausência, a seleção de skids caindo, o fluxo virando buffer, os dois 404 divergindo,
as somas ficando iguais) e exige que cada uma **reprove**. Um gate que nunca se viu reprovar é
decoração; este se vê — e as duas mutações da REGRA 0 disparam **uma checagem cada**, o que
significa que a falha diz qual dos dois lados quebrou.

`openpyxl` e `psutil` não estão no `requirements.txt` porque o BFF não lê planilha nem se mede:
ele repassa bytes. São ferramenta de conferência.

---

## 10. Resumo dos achados desta leva

1. **A premissa "366 dias × 1 h com tudo" não é um pedido possível** — a retenção de 183 dias a
   recusa em 2,2 s. E não há UM pior caso: **31 d × 5 min, 92 d × 15 min e 7 d nativo custam o
   mesmo** (29,7 · 31,7 · 28,0 s), porque a conta que empata é baldes × colunas.
2. **Pedido recusado também queima vaga do balde** — 10 inválidos trancam o 11º, válido. O
   semáforo não protege contra isso; a tela impedir o impossível é defesa, não cortesia.
3. **O edge do Railway aguenta 32,3 s** e entrega 1,97 MiB íntegros. O item aberto fechou; o teto
   exato continua desconhecido acima disso.
4. **Agrupar por skid renomeia a aba** para `Skids`.
5. **Zero de potência é medido; vazio de energia é ausência** — e as duas coisas convivem na mesma
   linha, à meia-noite.
6. **`python -m uvicorn` no Windows serve de um processo filho**; medir só o pai dá "+0 KiB" e uma
   falsa prova de fluxo.
7. **`/openapi.json` 404 em produção é configuração, não ausência de rota.**
8. O limite do meuWatt é **contornável forjando `X-Forwarded-For`** — reportar a eles; não usar.

### 10.1 O que os juízes acharam, e o que foi feito (05/09/2026)

9. ⛔ **A exportação podia derrubar o PORTAL INTEIRO, e não só a si mesma.** `Depends(get_db)` só
   devolve a sessão ao pool quando a resposta termina — aqui, depois de até 75 s de fila mais
   ~40 s de geração. Com pool de 15 (5 + 10) e o pooler do Supabase em *session mode* com o
   mesmo teto, um punhado de cliques simultâneos em "Baixar planilha" esgotava as conexões e
   levava junto o painel, as ordens e as pendências. **Corrigido:** `db.close()` explícito antes
   da fila, com o nome do arquivo extraído do `link` enquanto a sessão ainda vive (`close()`
   desanexa a instância). Guardado por `test_a_conexao_de_banco_sai_antes_da_fila`, que observa
   `in_transaction()` no momento em que o pedido entra no semáforo.
10. ⛔ **A fila cobrava do cliente pela recusa.** Sem teto de gente, quem chegava com as duas
    vagas ocupadas esperava `_ESPERA_MAX_SEG` inteiros para ouvir "tente em um minuto" — os
    juízes mediram 48 s, num arquivo que sozinho leva 5,4 s. **Corrigido em duas frentes:**
    `FILA_MAX = 2` recusa **na hora** quem chega com a fila cheia, e `_ESPERA_MAX_SEG` subiu de
    45 s para **75 s**, que é o número que cobre as duas gerações medidas (58,0 s) — o antigo
    recusava ~13 s antes de a vaga voltar. A mutação que desfaz o teto de gente faz a suíte levar
    **85 s em vez de 10**: o defeito é literalmente o tempo.
11. ⚠ **A vaga NÃO volta quando o cliente fecha a aba durante a geração — e isso está certo.**
    Medido: dois soquetes fechados aos 2,0 s e o pedido seguinte ainda esperou ~46 s. Fechar a
    nossa aba não faz a mw-api parar: ela monta o XLSX inteiro num `to_thread` e só então
    responde. Soltar a vaga cedo deixaria um terceiro pedido pilhar um servidor de um worker só
    que ainda está ocupado com o arquivo abandonado — **a vaga mede o trabalho DE LÁ, não a
    atenção de quem pediu**. O que o abandono não pode causar é o próximo esperar em vão, e disso
    cuidam os dois tetos acima. A contradição documental que os juízes apontaram (o docstring de
    `_soltar_vaga` prometia o que não entregava) foi corrigida no lugar certo: lá.
12. ⛔ **A conta de colunas da tela era a do ORÇAMENTO, e por isso mentia.** Três erros ao mesmo
    tempo, todos medidos abrindo o arquivo com `openpyxl`: faltava a coluna `Início (BRT)` de
    toda aba (a tela dizia 3 onde o arquivo tem 4, e o Leia-me da própria planilha a desmentia);
    faltava `Leitores com leitura` na fronteira (6 onde há 8); e o agrupamento da fronteira era
    ignorado (6 onde por usina há 3). **E o pior não era nenhum dos três: era somar tudo num
    número só** — "37 colunas" não era a largura de aba nenhuma de um caderno cuja aba mais larga
    tinha 22. **Corrigido:** `estimativa` devolve `abas[]` com nome, linhas e colunas de cada uma,
    refeita contra `sheet_*` do escritor de lá; o orçamento do servidor virou função própria
    (`celulasDoOrcamento`, cópia fiel de `validate_request`), porque é ele quem decide
    `muito_grande`. Onde o número não fecha, ele não é inventado: a aba **Paradas** não tem
    linhas para dar ("uma linha por parada no período") e a **Estação** com relé diz "mais 1
    coluna por sensor do relé", porque quantos sensores a usina tem **não vem nas opções** —
    Porto Ferreira tem cinco. Nove mutações plantadas, nove acusadas.
13. ⛔ **O 422 do Pydantic oferecia "Tentar de novo" para um erro permanente.** Ele sai cru, sem o
    `motivo` do vocabulário fechado, e o mesmo corpo dará o mesmo 422 para sempre — repetir gasta
    uma das dez vagas por minuto que o IP inteiro do portal divide. Agora o botão só aparece em
    5xx e em falha de transporte.
