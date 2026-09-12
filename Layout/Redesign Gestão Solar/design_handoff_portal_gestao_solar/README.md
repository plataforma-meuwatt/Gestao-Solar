# Handoff: redesenho do portal do Gestão Solar

## Visão geral

O portal do Gestão Solar (`portal/`) ganha identidade visual própria e uma hierarquia de leitura
nova. O produto não muda de escopo: as mesmas telas, as mesmas leituras do BFF, os mesmos seis
tons de status. O que muda é **o que aparece primeiro, com que tamanho, e quantas vezes**.

Duas decisões já foram tomadas pelo dono do produto e não estão em aberto:

| Decisão | Escolha |
|---|---|
| Navegação | **Trilho lateral** (a estrutura que já existe em `shell/Layout.tsx`) — não a barra superior por assunto |
| Marca | **Selo cheio**: quadrado âmbar de raio 14 com o monograma `GS` vazado. O anel fica como marca de documento (PDF), a cápsula foi descartada |

## Sobre os arquivos de design

`Gestão Solar — Redesign.dc.html` é **referência de design em HTML** — um protótipo que mostra a
aparência e a hierarquia pretendidas. Não é código para copiar. A implementação é em
**React + TypeScript + Tailwind**, dentro de `portal/src/`, usando os componentes que já existem em
`portal/src/components/base.tsx` e os tokens de `portal/tailwind.config.js`.

Abra o arquivo num navegador. Ele tem treze blocos em dois turnos, cada um com um selo de
identificação no canto. **O turno 2 está no topo.**

Turno 2 — as telas restantes, já no sistema decidido:

- **2a** — Paradas
- **2b** — Baixar dados
- **2c** — Comparar usinas · Geração
- **2d** — Comparar usinas · Manutenção
- **2e** — Entrar (login)
- **2f** — Minha conta · Conexões

Turno 1 — o sistema e as quatro primeiras telas:

- **1p** — premissas, tokens e o mapa de qual componente do `base.tsx` cada peça toca
- **1a** — as três construções da marca GS e as aplicações (favicon, PDF, ao lado dos filhos)
- **1b** — **a referência de estrutura**: Visão geral com trilho lateral
- **1c** — variante de navegação **descartada**; o ranking com régua dela foi reaproveitado em **2c**
- **1d** — Painel da usina (geração de energia, aba Mês)
- **1e** — Manutenção (fita dos meses, ordens, pendências)
- **1f** — Relatórios

## Fidelidade

**Alta fidelidade.** Cores, tipografia, espaçamento e escala são finais e estão listados abaixo em
hexadecimal e pixel. Reproduza fielmente. Os dados são os de setembro/2026 dos prints — são
exemplo, não conteúdo.

## Regras do produto que o redesenho respeita — e que não podem ser violadas na implementação

Estas regras já estão escritas nos comentários do código. Elas guiaram o desenho e são a parte
mais fácil de quebrar sem perceber:

1. **A régua de cor mora no servidor.** `tom` e `situacao` vêm prontos do BFF. Nenhuma tela compara
   percentual com limiar. Não reintroduza `pct < 70 ? 'vermelho' : ...`.
2. **Desvio não é pintado.** O servidor não classifica desvio. Em "Desvios do período" e em toda
   frase de desvio, o número é `text-forte` com o sinal — nunca verde ou vermelho. Um limiar
   inventado acusa de vermelho uma usina que o contrato considera em dia.
3. **Mês futuro não tem cor.** Em `FitaDosMeses`, `futuro` e `sem-previsao` usam `border-borda
   bg-superficie` e a barra `bg-superficie-destacada`. Mês que ainda não venceu não é falha.
4. **Cor nunca é a única legenda.** Cada bloco da fita imprime a palavra do estado e a contagem com
   denominador (`17 de 17`). O quadro é lido em reunião e projetado.
5. **Nada de zero onde faltou dado.** Todo número passa por `lib/format`, que escreve `—` para nulo.
6. **Nunca use o modificador de opacidade do Tailwind (`/NN`) sobre um token declarado como
   `rgba(...)`** — ele substitui o alfa em vez de multiplicar. `scripts/regra0.mjs` recusa isso.
7. **Todo número é `IBM Plex Mono` com `tabular-nums`** — a classe `.mono` do `index.css`, ou o
   componente `<Num>`.

## Tokens

### Nada de cor nova

Todos os hexadecimais do design saem de `portal/tailwind.config.js`. Não adicione nenhum. Para
referência na leitura do HTML:

| Token | Valor | Uso no redesenho |
|---|---|---|
| `fundo` | `#02061A` | fundo da aplicação |
| `superficie` | `rgba(255,255,255,0.04)` | todo cartão |
| `borda` | `rgba(255,255,255,0.08)` | toda borda de cartão e separador |
| `borda-fraca` | `rgba(255,255,255,0.06)` | linha entre linhas de tabela |
| `afundado` | `rgba(0,0,0,0.25)` | seletor de usina, grupos segmentados |
| `ambar` | `#FFC315` | marca, barra de medido, botão primário |
| `ambar-texto` | `#FFD75E` | número medido, percentual do mês |
| `forte` | `#F5FDFF` | título, nome de usina, número neutro |
| `corpo` | `#DDE2F6` | texto corrido |
| `rotulo` | `#D6C4AC` | rótulo de seção em caixa alta |
| `fraco` | `#94A3B8` | legenda, unidade, texto de apoio |
| `tom-parado` | `#F87171` | parada em aberto, prazo vencido |
| `tom-alerta` | `#FBBF24` | abaixo do esperado, mês em andamento |
| `tom-ok` | `#34D399` | cumprido, disponibilidade boa |
| `tom-tempoRuim` | `#7DD3FC` | previsto pela irradiação medida |
| `tom-semDados` | `#94A3B8` | usina sem leitura |

A barra de medido usa um degradê de dois passos do próprio âmbar:
`linear-gradient(180deg, #FFC315, #E8A20F)` na vertical, `90deg` na horizontal. `#E8A20F` é o único
valor que não está no config — se preferir não adicioná-lo, use `bg-ambar` chapado; o degradê é
refinamento, não estrutura.

**Fora desse único caso, o design não introduz cor.** A regra está no cabeçalho do próprio
`tailwind.config.js` — *"Fonte única de cor do portal: nenhum hexadecimal fora deste arquivo"* — e o
protótipo a segue. Duas consequências práticas:

- **Todo `—` de dado ausente, toda legenda e todo texto inerte usam `fraco` / `tom-semDados`
  (`#94A3B8`).** Não existe um segundo cinza mais escuro. Dois cinzas para o mesmo significado é o
  erro que o `lib/tons.ts` existe para impedir, e qualquer cinza mais escuro que `#94A3B8` sobre o
  fundo `#02061A` fica abaixo de 3:1 — e essas células carregam conteúdo, não decoração.
- **Controle desabilitado é opacidade, não cor.** O `›` do mês futuro nos seletores de período é
  `text-fraco` com `opacity:.45`.

### Tipografia

`Figtree` (400/500/600/700) e `IBM Plex Mono` (500/600), servidas de `public/fontes/` — já
configuradas. Escala do redesenho:

| Papel | Tamanho / peso | Família |
|---|---|---|
| Veredito (número do mês) | 64px / 600, `letter-spacing:-.03em` | Mono |
| Título de página | 32px / 600, `-.025em` | Figtree |
| Número de KPI grande | 26px / 600 | Mono |
| Número de KPI normal | 22px / 600 | Mono |
| Subtítulo de veredito | 15px / 600 | Figtree |
| Texto corrido | 14,5px / 400, `line-height:1.6` | Figtree |
| Célula de tabela | 14px / 500 (nome), 13,5px (número) | Figtree / Mono |
| Legenda | 12–12,5px / 400 | Figtree |
| Rótulo de seção | 10,5px / 500, `letter-spacing:.12em`, caixa alta | Mono |

O rótulo de seção passou de Figtree para **Mono em caixa alta com tracking .12em**. É a mudança
tipográfica que mais distingue o GS do meuWatt. Aplica-se à classe `.rotulo-secao` do `index.css`.

### Raio e espaçamento

Raios continuam os do config: `card 16px`, `campo 12px`, `chip 12px`, `barra 3px`. Densidade
confortável: linha de tabela ~52px de altura (`py-3.5`), respiro de 16px entre cartões, 20–32px de
padding interno, no máximo **seis colunas por tabela** — o que não cabe vira segunda linha da célula.

## A marca

### Construção do selo cheio

- Quadrado de `56×56` (topo) ou `32×32` (contexto), raio `14px` / `8px`
- Fundo `#FFC315` chapado
- `GS` em Figtree **700**, `letter-spacing:-.04em`, cor `#02061A`
- Corpo do glifo ≈ 42% da altura do quadrado (25px num selo de 60px, 14px num de 32px)

### Lockup

Selo + `Gestão Solar` em Figtree 600, 21px, `-.02em`, `#F5FDFF`, com 14px de gap. Descritor opcional
abaixo: `carteira · geração · manutenção` em Mono 10,5px, tracking `.14em`, caixa alta, `#D6C4AC`.

### Variantes a produzir

| Onde | O quê |
|---|---|
| Favicon | 32px e 16px, selo âmbar com `GS` vazado; no 16px o glifo vai a 7,5px |
| PDF / fundo claro | selo invertido: fundo `#02061A`, `GS` em `#FFC315` |
| Documento | **anel**: círculo de 72px, borda 2,5px `rgba(255,195,21,.5)`, `GS` em Figtree 600 26px `#FFD75E` — é o mesmo desenho da `Rosca` do fechamento |

O `Layout.tsx` hoje renderiza só o texto `Gestão Solar`. Substitua por selo + texto. Os botões
`meuWatt` / `meuPlano` de `AbrirProduto.tsx` perdem a borda e ficam em texto `fraco` com a seta —
o pai tem marca, os filhos aparecem como destino. A marca do meuWatt, para referência, é um raio
**violeta `#863bff`** com brilho azul (`Claude Designer/referencias/marca-meuwatt.svg`); não há
colisão com o âmbar.

## Mudanças por componente

Nenhum componente novo. Todas as mudanças são no `portal/src/components/base.tsx`, exceto onde
indicado.

### `Kpi`

Ganha uma terceira medida: `tamanho="veredito"`. Número a 64px em Mono 600, rótulo acima em Mono
caixa alta, e um slot para a régua abaixo. As medidas `normal` (22px) e `grande` (26px) continuam.

### `Selo`

Sem mudança de API. Os seis tons de `lib/tons.ts` intactos. Visual: altura 24px, raio 12px, padding
`0 10px`, fundo `tom/10`, borda `tom/30`, texto `tom`, Mono 11px.

### `FaixaAtencao`

**A mudança de maior impacto.** Hoje a Visão geral empilha uma faixa por usina — sete faixas
idênticas dizendo "Bem abaixo do esperado" ocupam a primeira tela inteira. Sete alertas iguais é
zero alerta.

Passe a **agrupar por título**: faixas com o mesmo `titulo` e `tom` viram uma linha só, com a
contagem e a lista das usinas no detalhe. Só o que é excepcional ganha faixa própria — no exemplo de
setembro, duas: `Tiete tem 2 paradas em aberto` (tom `parado`) e `4 pendências com prazo vencido`
(tom `alerta`). As seis "abaixo do esperado" saem das faixas e viram uma frase no veredito.

Visual da faixa: raio 14px, padding `18px 20px`, fundo `tom/6`, borda `tom/30`, um contador em
quadrado de 38px à esquerda (`tom/16`, raio 10px, Mono 17px 600) e o botão de ação à direita.

### `Tabela`

Mesma API (`alinhar`, `semPadding`, `aoClicar`, `chave`). Três mudanças visuais:

1. **Barra de tom na borda esquerda de cada linha** — coluna de 3px, altura 34px, raio 2px, cor
   `bg-tom-${tom}`. É o que faz o estado ser lido antes do texto, e é emprestado do meuWatt.
2. **Máximo de seis colunas.** Na Visão geral, `Atrasados`, `OS em andamento` e `Pendências abertas`
   viram **uma** coluna `Manutenção`, com o texto `0 atrasados · 1 OS · 6 pend.` em Mono 12,5px,
   alinhada à direita, com a parte vencida em `tom-parado`. Isso resolve o corte horizontal — o
   `max-w-[17rem]` que hoje segura a coluna de usina existe por causa desse aperto.
3. **A coluna de energia vira comparador**: `<Barra>` de 8px com o percentual do esperado, e abaixo
   `47,6 de 79,8 MWh` em Mono 11,5px. Substitui as colunas separadas de medido e `% do esperado`.

### `Barra`

Sem mudança de API (`pct`, `tom`). Altura 8px, raio 4px, trilho `rgba(255,255,255,.07)`. Entra
dentro da célula de tabela e dentro do KPI de veredito.

### `GraficoBarras` (`PontoBarra = { rotulo, valor, esperado }`)

Séries inalteradas. O desenho passa a ser **par lado a lado**: medido em âmbar (26px de largura) e
esperado em `rgba(255,255,255,.13)` (26px), com 5px de gap, sobre um eixo de base de 1px
`rgba(255,255,255,.12)`. O valor medido é rotulado acima da coluna em Mono 11,5px `ambar-texto`.
Legenda explícita no cabeçalho: `medido` / `projeto`. Ponto sem leitura não vira barra — vira um
traço de 1px e a palavra `sem leitura` em `fraco` (a regra já existe no componente).

### `BarrasDoPeriodo` (`{ chave, rotulo, medido, projeto, futuro }`)

Barras medidas em âmbar, 18px de largura, 5px de gap. Duas adições:

- **A linha do projeto por dia** entra como `1px dashed rgba(148,163,184,.6)` na altura do
  `projeto_kwh` médio, com o rótulo `32,6 MWh/dia previstos` em Mono 10px à direita.
- Os dias com `futuro: true` **não viram barras individuais**. Viram uma região única hachurada
  (`repeating-linear-gradient(135deg, rgba(255,255,255,.035) 0 6px, transparent 6px 12px)`) com a
  frase `dias 12 a 30 · ainda não aconteceram` em Mono 11px. Trinta placeholders vazios são ruído;
  uma região nomeada é informação.

Eixo de dia: rótulo só a cada 3 dias (`1, 4, 7, 10, …`), Mono 10px `fraco`.

### `BarrasPr`

Sem mudança estrutural. Mantenha a linha de referência `PR do mês (82,2%)` e o estado `descartado`.

### `Rosca`

`conic-gradient(#FFC315 0% <pct>%, rgba(255,255,255,.09) <pct>% 100%)` em 118px, com um disco
interno de 88px na cor `fundo`. Centro: percentual em Mono 23px 600 `forte`, e abaixo
`até o dia 11` em Mono 9px caixa alta `fraco`. Uma casa decimal, como já está no `Mes.tsx`.

### `FitaDosMeses`

Reescrita visual, modelo idêntico. Bloco: raio 12px, padding `10px 11px 11px`. De cima para baixo:
competência em Mono 10px caixa alta `rotulo`; barra de estado de 3px com 7px de margem; contagem
`17 de 17` em Mono 13px `corpo`; palavra do estado em 11px na cor do tom. `futuro` e `sem-previsao`
usam `border-borda bg-superficie`, barra `superficie-destacada`, contagem `—` e a palavra em
`fraco`. Legenda das quatro cores no cabeçalho, e a nota de procedência abaixo (`a contagem vem do
recorte de vigência do meuPlano; as atrasadas vêm da matriz`).

### `CabecalhoCard` e `.rotulo-secao`

Rótulo em Mono 10,5px, tracking `.12em`, caixa alta, `rotulo`. A `direita` continua em Figtree 12px
`fraco`.

## Telas

### Visão geral — `features/visao-geral/Pagina.tsx` (bloco 1b)

A ordem passa a ser: **cabeçalho → veredito → exceções → gráfico → tabela → manutenção/pendências**.
Hoje as faixas vêm antes de tudo e o veredito não existe.

**Cabeçalho.** Rótulo `A carteira · 7 usinas · 21,3 MWp` em Mono caixa alta, título `Visão geral` a
32px, e à direita `atualizado 21:48` em Mono 11px + o `SeletorPeriodo` de mês (altura 38px, raio
10px, `‹` / `set/2026` / `›` com separadores de 1px; o `›` de futuro em `#4A5570`).

**Cartão de veredito.** Grid `minmax(0,1fr) 1px 340px`, padding `28px 30px`.

- Esquerda: rótulo `O combinado × o entregue · setembro`; `63,2%` a 64px em `tom-alerta` (a cor vem
  do `tom` do servidor) com o `%` a 34px; ao lado, `Bem abaixo do esperado` (a `situacao` do
  servidor) a 15px 600 e `faltam 380,3 MWh para a meta do mês` a 13,5px `fraco`.
- **A régua**: trilho de 10px raio 5px; preenchimento âmbar em degradê até `pct_do_esperado`; abaixo,
  três marcas em Mono 11px — `0` à esquerda, `654,4 MWh medidos` centrado no fim do preenchimento,
  `alvo 1.034,7` à direita.
- Frase de leitura, 13,5px, máx. 560px: as seis abaixo da meta, e a atribuição do desvio de sol
  **nomeando a usina** (só Porto Ferreira tem estação solarimétrica; nas outras não há irradiação
  medida para afirmar o mesmo).
- Direita: três leituras empilhadas com separador de 1px — `Potência agora`, `Perdas por paradas`,
  `Leitura da carteira` (`6 de 7 usinas` + o aviso do servidor em `tom-alerta`).

**Exceções.** Duas `FaixaAtencao` agrupadas, lado a lado num grid de duas colunas.

**Gráfico.** `GraficoBarras` em cartão próprio, altura de plotagem 170px, com cabeçalho
`Medido × projeto, por usina` e a pergunta `Quem puxou a carteira para baixo, em MWh`.

**Tabela.** Seis colunas: barra de tom (3px) · Usina (250px) · Situação (150px) · Medido contra o
projeto (`1fr`, com a `Barra`) · Paradas (150px, direita) · Manutenção (190px, direita). A linha
inteira continua abrindo a usina.

**Rodapé.** Os dois cartões da 2ª onda (Manutenção e Pendências), três KPIs de 28px cada, mais uma
frase de contexto: `6 de 7 contratos ainda não publicaram o cronograma — sem ele não há atraso a
cobrar`. O ponto pulsante de `DaSegundaOnda` continua como está.

### Painel da usina — `features/energia/Mes.tsx` + `Pagina.tsx` (bloco 1d)

**Faixa de contexto** de 52px acima do conteúdo: selo GS de 26px + trilha
`Gestão Solar / Porto Ferreira / Geração de energia / Painel` em Mono 12px, e à direita o `Selo` da
situação da usina.

**Cartão de topo** — grid `300px 1px minmax(0,1fr)`:

- Esquerda: a `Rosca` de 65,8% + a frase de tendência (`No ritmo atual o mês fecha em 643,2 MWh,
  contra o alvo de 977,0` — sem cor de desvio).
- Direita: **as quatro leituras na mesma escala**, em vez de quatro KPIs soltos. Uma linha por
  medida, grid `190px minmax(0,1fr) 116px`: rótulo, barra de 20px, valor em Mono 13,5px.
  `Medido (inversores)` em âmbar; `Medido na fronteira` em `rgba(255,195,21,.45)`;
  `Previsto (irradiação medida)` em `tom-tempoRuim` a 70%; `Projeto até o dia 11` em
  `rgba(255,255,255,.16)` chapado, sem preenchimento — é o trilho, é o alvo.
  Abaixo, a nota dos dois denominadores: a meta do contrato é o mês inteiro (977,0), mas o medido é
  comparado com o proporcional até o dia de corte. Preserve as regras de `Mes.tsx`: cartão de
  fronteira não existe quando `medido_fronteira_kwh` é nulo, e `fronteira_parcial` imprime o aviso
  de que a diferença **não é perda**.

**Geração dia a dia** e **Como a usina rendeu** / **Desvios** num grid `1.45fr 1fr`.
Em "Como rendeu", quatro KPIs de 22px em grid 2×2, e o `Selo` de
`24 paradas ainda sem causa classificada` como linha de rodapé com um ponto de 7px.
Em "Desvios", três linhas rótulo/valor, valores em `forte` com sinal, e a nota explícita de que
desvio não é pintado.

### Manutenção — `features/cronograma/`, `ordens/`, `pendencias/` (bloco 1e)

A proposta é **uma tela de manutenção da usina** em vez de três seções irmãs. Se isso for mudança
grande demais para a primeira entrega, implemente os três blocos separados com o mesmo desenho —
eles são independentes.

- **Cabeçalho**: o veredito em texto (`Das 18 atividades previstas para setembro, 17 ainda estão no
  prazo e nenhuma venceu`), e à direita `Abrir no meuPlano ↗` e `Cobrar pendência`.
- **A fita dos doze meses**, no desenho descrito acima.
- **Ordens**: a OS em andamento como cartão destacado com borda `tom-ok/30` e a barra de progresso
  de tarefas (`17 de 17`), e as concluídas numa tabela de quatro colunas.
- **Pendências**: uma linha por usina, grid `120px minmax(0,1fr) 56px`, com a barra dividida em duas
  partes — vencidas em `tom-parado`, no prazo em `tom-alerta/55`. Abaixo, os três totais.
- **Rodapé**: a faixa `tom-alerta` sobre os seis contratos sem cronograma publicado, com a ressalva
  de que `0 atrasados` ali não significa manutenção em dia.

### Relatórios — `features/relatorios/Pagina.tsx` (bloco 1f)

Três cartões de documento em grid de três colunas. Cada um tem uma capa de 132px com o **anel GS**
centrado (âmbar no relatório de geração, `tom-parado` no anexo de paradas, tracejado e `#4A5570` no
não publicado), o tipo em Mono caixa alta no canto, e abaixo título 16px 600, competência em Mono
12px `fraco`, uma frase de 13px dizendo o que o documento contém, e os botões.

Documento não publicado **não desaparece e não fica cinza-morto**: capa tracejada com hachura,
a frase que explica o que ele seria, e a ação `Solicitar publicação`. É a peça que a diretoria lê.

Abaixo, a tabela de fechamentos anteriores com o cumprimento da meta como `Barra` (a cor vem do
`tom`, não de limiar calculado na tela), e o cartão que aponta para `Baixar dados`.

### Paradas — `features/paradas/Pagina.tsx` (bloco 2a)

Hoje a tela mostra 24 linhas de "19 min · 0,1 kWh · Resolvida" quase idênticas. São a mesma
ocorrência vista por inversor — uma parede que esconde o único número acionável: **24 de 24 sem
causa classificada**.

**Cartão de topo** — grid `minmax(0,1fr) 1px 300px`. À esquerda, o custo: `5 h 29 min` a 46px em
Mono (as unidades a 24px em `fraco`) e `20,6 kWh` a 26px ao lado, mais a frase que os põe em escala
(`0,009% do que a usina gerou no mês`). À direita, em `tom-alerta`, o que precisa de ação:
`24 de 24` a 40px, a explicação de que parada sem causa não entra na disponibilidade contratual, e o
botão `Classificar no meuWatt ↗`.

**Quando aconteceram** — uma barra por dia do mês, altura = minutos parados, em `bg-tom-alerta`
chapado. Dia sem parada é um traço de 1px, não uma barra de altura zero. Os dias
futuros usam a mesma região hachurada de `BarrasDoPeriodo`. Torna visível o que a tabela esconde:
as 24 paradas caem em três dias.

**Cada parada, agrupada por janela.** Seis colunas: barra de tom · Janela (`10/09 14:18 → 14:37` em
Mono, com `18 paradas nesta janela` abaixo) · Duração · Energia perdida · Alcance (`Usina inteira —
18 inversores`, com o skid abaixo) · Causa · situação (dois selos empilhados: `a classificar` em
`tom-alerta`, `encerrada` em `tom-ok` 11px). Abrir um grupo mostra as paradas individuais como estão
hoje — o agrupamento é camada de leitura, não perda de dado.

A nota de procedimento fica no pé: lido do histórico de alertas, perda estimada, e parada que
atravessa dias tem a perda distribuída proporcional à luz de cada dia.

### Baixar dados — `features/dados/Pagina.tsx` (bloco 2b)

Os quatro passos numerados da tela atual são bons e ficam. O que falta é **ver o arquivo antes de
baixar**: hoje se configuram 22 colunas no escuro e só o Excel revela o resultado.

Layout `minmax(0,1fr) 380px`. À esquerda, três cartões numerados (o marcador é um quadrado de 24px,
raio 7px, `ambar/14` com borda `ambar/30`, Mono 11,5px):

1. **Comece de um pronto** — os atalhos como três cartões escolhíveis, o ativo com borda `ambar/35`
   e fundo `ambar/7`. Substitui o `<select>` de "Preencher os blocos com um começo pronto".
2. **De quando a quando, e com que detalhe** — os passos 2, 3 e 4 de hoje numa única linha de
   controles: recorte segmentado, seletor de mês, granularidade, faixa de hora. A nota de
   `12/03/2026` (antes disso só o total por dia) em `tom-alerta`.
3. **O que entra no arquivo** — as quatro fontes em grid 2×2. Fonte ligada: borda `ambar/32`, fundo
   `ambar/5`, interruptor âmbar de 38×22. Fonte desligada: borda `borda`, `opacity:.65`. Substitui o
   par de botões `Não entra` / `Entra no arquivo`, que ocupa espaço e não mostra estado.

À direita, o **trilho do arquivo**, fixo: borda `ambar/28`, fundo `ambar/4`. `264 linhas` e
`22 colunas` a 34px, a **prévia das primeiras colunas** como uma minitabela de três colunas
(`instante`, `inv 01 kWh`, `inv 02 kWh`) com três linhas de exemplo, a legenda
`Vazio = sem leitura. 0 = zero medido.` — que é a regra do produto e hoje aparece como texto solto
no pé —, e o botão `Baixar planilha` em largura total com `XLSX · ~180 KB` abaixo.

### Comparar usinas · Geração — `features/comparar/Energia.tsx` (bloco 2c)

**É aqui que o ranking com régua de 1c foi usado.** Quatro KPIs da carteira em linha
(`639,0 MWh`, `30,0 kWh/kWp`, `21.328 kWp`, `18,8 MWh`), cada um a 30px com a nota de procedência
abaixo em 12,5px `fraco`.

A tabela de ranking tem sete colunas: posição (26px) · Usina (190px, com cidade e kWp abaixo) ·
**Produtividade como barra** (`1fr`) · Energia · PR · Disponibilidade · Irradiação. A barra é de
22px, escalada pelo primeiro colocado; o 1º tem o valor **dentro** da barra em `#02061A` 600, os
demais **fora**, à direita da ponta, em `ambar-texto`. Disponibilidade e irradiação são células de
duas linhas (valor + contratual / GHI), com as paradas sem classificação em `tom-alerta`.

Duas notas no pé, em duas colunas: `Fora deste ranking (N)` com o motivo por usina, e
`A janela desta comparação`. Acrescente à janela a ressalva que hoje não está escrita: **só duas das
sete usinas têm estação solarimétrica**, então só elas têm PR e irradiação — e a produtividade das
outras quatro não pode ser lida como eficiência.

### Comparar usinas · Manutenção — `features/comparar/Manutencao.tsx` (bloco 2d)

A tela atual lidera com `0 atividades atrasadas` e esconde o achado real num bloco de rodapé
chamado `FORA DESTE RANKING (6)`. O redesenho **inverte isso**.

**O cartão de topo é `tom-alerta`** (borda `/30`, fundo `/5`) e diz `1 de 7` a 52px:
contratos com cronograma publicado. Ao lado, a explicação de que sem cronograma não há previsto e
sem previsto não existe atraso a cobrar, e por que as seis aparecem com `—` e não com zero. À
direita, três leituras menores: atrasadas, OS em andamento, pendências (com as vencidas em
`tom-parado`).

A tabela tem seis colunas: barra de tom · Usina · contrato · Atrasadas · **Cumprimento do previsto**
· OS · Pendências. A linha que publicou cronograma usa `Barra` + `1 de 18 · 17 ainda no prazo, fora
da conta` e recebe um fundo `ambar/4`; as seis sem cronograma **usam a célula de cumprimento para o
aviso do servidor** em `tom-alerta`, em vez de deixarem quatro traços enfileirados. O bloco
`FORA DESTE RANKING` desaparece: o motivo passou a viver na linha da usina, que é onde se olha.

### Entrar — `features/entrar/Pagina.tsx` (bloco 2e)

Duas colunas, `minmax(0,1.05fr) 520px`, altura mínima 640px.

Esquerda: lockup da marca no alto; no meio, a frase do produto a 40px 600 (`Uma conta, uma lista de
usinas, os dois produtos por baixo`) e o parágrafo que explica a conexão por token revogável; embaixo,
a assinatura. Fundo:
`radial-gradient(120% 90% at 12% 0%, rgba(255,195,21,.08), transparent 62%)` — **o halo passa a ser
âmbar e canto superior esquerdo**, no lugar do halo azul central de `rgba(64,110,255,.20)` herdado
do rebrand do meuWatt. É a única mudança de fundo do sistema, e vale só nesta tela.

Direita: o formulário. **O primeiro campo é `Apelido`, não e-mail** — a identidade da conta é o
apelido (`core/apelido.py`), e o e-mail é contato opcional. A dica abaixo do campo repete o formato:
minúsculas, sem acento, um separador por vez. Campos de 44px, raio 12px, fundo `afundado`, borda
`borda`; o campo em foco usa `border-ambar/50`. Botão `Entrar` de 46px em `bg-ambar` com texto
`fundo`. No pé, as duas frases de recuperação: senha provisória entregue com o apelido, e falar com
o gestor de conta — não há autoatendimento de senha.

### Minha conta · Conexões — `features/conta/Pagina.tsx` (bloco 2f)

Três abas no cabeçalho (`Conexões`, `Dados da conta`, `Senha`), e o rótulo de contexto diz
`renanmarquezini · Splendor O&M · gestor` — apelido, não e-mail.

**As duas pontes** em grid de duas colunas. Cartão saudável: borda `tom-ok/30`, fundo `/5`, selo
`funcionando` com um ponto de 6px. Quatro linhas rótulo/valor: **Token de** (o dono — mostrar o dono
não é enfeite: o token da pessoa errada deixa o cartão verde com o escopo menor), **Alcance**
(quantas usinas), **Conectado em**, e o token mascarado (`mw_pat_•••••4kR2` — só prefixo e quatro
últimos). Ações: `Trocar token` neutro e `Desconectar` com borda `tom-parado/40`.

Cartão recusado: borda `tom-parado/32`, e a frase que **separa as duas causas de um 401 idêntico** —
`O produto respondeu 401 desde quinta, 10/09 às 14:02. O histórico da ponte diz que o token foi
trocado nesse dia — não é o meuPlano que saiu do ar.` Dentro dele, a caixa de colar o token novo,
com a nota de que o prefixo é conferido localmente e um `mw_pat_` colado ali é recusado sem gastar
chamada de rede.

**As três camadas de gravação** como três cartões numerados (Formato, Identidade, Alcance), com a
regra escrita acima deles: se qualquer uma falhar, nada é gravado e a conexão anterior continua de
pé. No pé, com um ponto `tom-alerta`: **Desconectar não é revogar** — remover o token aqui só faz o
Gestão Solar parar de usá-lo; ele continua válido no produto de origem.

**Histórico das pontes** (`gs_integracao_eventos`) numa coluna de 400px, como linha do tempo: borda
esquerda de 1px, ponto de 7px na cor do tom, e por evento a hora em Mono 11,5px, o título a 13px e o
detalhe a 12,5px. A nota final é a razão de a lista existir: o estado diz se funciona agora; o
histórico diz desde quando parou.

## Comportamento e estados

Nada muda no comportamento. Preserve:

- Os **quatro estados** de `Tela4Estados` (esqueleto, erro, vazio, conteúdo). O `.esqueleto` pulsante
  continua sendo a forma do que vai aparecer.
- A **segunda onda** da Visão geral (`useResumoManutencao`) correndo em paralelo, com o ponto
  pulsante de `DaSegundaOnda` nas células de manutenção — nunca `—` antes da resposta.
- O `LimiteDeErro` por rota, com a navegação de pé.
- As **três larguras** do `Layout.tsx`: barra com rótulo ≥1024px, trilho de ícones 768–1024px,
  gaveta <768px. O selo GS aparece nas três; o texto `Gestão Solar`, só nas duas maiores.
- `:focus-visible` com `ring-2 ring-ambar ring-offset-2 ring-offset-fundo`.
- Estado de hover de linha de tabela e de item de menu como já estão.

## Estado

Nenhuma variável de estado nova. O agrupamento de `FaixaAtencao` é derivação do array `atencao` que
o BFF já manda — agrupe por `titulo` + `tom` no render, sem estado.

## Assets

- **Marca GS**: a criar. Não existe no repositório hoje. Entregável: SVG do selo, SVG do anel,
  favicon 32/16, versão invertida para PDF. O protótipo desenha o selo com CSS (quadrado + texto),
  o que é suficiente para a interface; para o favicon e o PDF é melhor um SVG com o glifo em
  contorno, para não depender da Figtree estar carregada.
- **Marca do meuWatt**: `marca-meuwatt.svg`, incluída neste pacote, copiada de
  `Claude Designer/referencias/marca-meuwatt.svg`. É o arquivo real, e é ele que aparece no cartão de
  conexão (2f) e na tela de entrada (2e) — num cartão de conexão a marca identifica de qual produto
  é o token, e um quadrado colorido no lugar dela seria adivinhação.
- **Marca do meuPlano**: **não existe neste repositório**. Onde ela apareceria, o protótipo mostra um
  quadrado tracejado com `mP` — placeholder declarado, com o motivo no `title`. Traga o SVG do
  repositório do meuPlano antes de implementar.
- **Fontes**: já em `public/fontes/`. Nada a acrescentar.
- **Ícones**: `lucide-react`, já em uso. O protótipo usa caracteres no lugar dos ícones (`⇄`, `◔`,
  `▦`); na implementação use os ícones que `shell/menu.ts` já declara — `ArrowLeftRight`, `Gauge`,
  `AlertTriangle`, `Download`, `Scale`, `CalendarDays`, `ClipboardList`, `ListChecks`, `FileText`,
  `LayoutGrid`, e os cabeçalhos `Zap` e `Wrench`.

## Ordem de implementação sugerida

1. Marca: SVG do selo + `Layout.tsx` (topo) + favicon. Muda a cara do produto em uma hora.
2. `.rotulo-secao` em Mono caixa alta + `CabecalhoCard`. Vale para todas as telas de uma vez.
3. `Kpi tamanho="veredito"` + a régua, e o cartão de veredito da Visão geral.
4. Agrupamento da `FaixaAtencao`. É a mudança que devolve a primeira tela ao cliente.
5. `Tabela` com barra de tom, seis colunas e a `Barra` na célula de energia.
6. `GraficoBarras` e `BarrasDoPeriodo` (rótulo de valor, par medido/projeto, região do futuro).
7. `FitaDosMeses` e o resto da Manutenção.
8. Relatórios com o anel.
9. O cartão de topo de `comparar/manutencao` — inverter a hierarquia é código pouco e muda o que a
   tela diz.
10. Paradas agrupadas, Baixar dados com prévia, Entrar e Conexões.

## O que ficou em aberto

- **A tela de Manutenção unificada** é proposta, não decisão. Se as três seções continuarem
  separadas no menu, o desenho de cada bloco continua valendo.
- **As abas irmãs do painel** — `Dia`, `Ano`, `Unidades` e `Relatório` (`features/energia/Dia.tsx`,
  `Ano.tsx`, `Unidades.tsx`, `Relatorio.tsx`) — não foram desenhadas. Elas herdam tudo deste
  documento; `Ano` é a que mais ganharia com o tratamento de régua, porque é a comparação mês a mês.
- **A ficha de uma tarefa e a de uma ordem** (`features/tarefa/`, `features/ordem/`) também não
  foram desenhadas, incluindo o fluxo de fotos.
- **1c (barra superior de navegação)** foi descartada como estrutura. O ranking horizontal com
  régua que apareceu nela foi aproveitado em **2c**, que é onde a pergunta de ranking existe.
- `features/energia/graficos.tsx` (50 KB) não foi lido integralmente. As séries citadas aqui
  (`medido`, `projeto`, `futuro`, `pr`, `descartado`, `poa`) vêm de `Mes.tsx` e do contrato de
  `Painel`. Confirme as assinaturas antes de mexer nos componentes de gráfico.
- O **agrupamento de paradas por janela** (2a) é regra nova de apresentação e precisa de uma
  decisão de produto: qual tolerância de minutos junta duas paradas na mesma janela. O desenho supõe
  "mesmo fim, início dentro de poucos minutos", que é o padrão visível nos dados de setembro.

## Arquivos deste pacote

- `Gestão Solar — Redesign.dc.html` — o protótipo. Abra num navegador; os blocos estão identificados
  por selo (2a–2f no topo, 1p–1f abaixo).
- `marca-meuwatt.svg` — a marca real do meuWatt, usada nas telas 1a, 2e e 2f.
- `README.md` — este documento.

## Repositório de destino

`plataforma-meuwatt/Gestao-Solar`, branch `main`, escopo `portal/`.
