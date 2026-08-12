# O que enviar ao Claude Designer

Esta pasta é o pacote da **rodada 1** (telas de entrada + aba Início). Envie o conteúdo
inteiro: o prompt sozinho funciona, mas as imagens evitam os dois erros mais comuns —
inventar cor fora da paleta e desenhar o cabeçalho num estado só.

## O pacote

| Arquivo | O que é | Enviar? |
|---|---|---|
| `PROMPT.md` | O prompt. Autocontido — contexto, princípios, paleta, tipografia, navegação e as 6 telas da rodada. | **Sim, é o principal** |
| `referencias/paleta.png` | As cores juntas, com os hex e a receita do chip de status. | **Sim** |
| `referencias/estrutura.png` | O frame 390 × 844 com o cabeçalho nos dois estados, avatar, safe area e barra de abas. | **Sim** |
| `referencias/foto-usina-aerea.webp` | Foto aérea de usina que o meuWatt usa hoje na tela de login. | Sim, se quiser que o login siga a mesma linha |
| `referencias/marca-meuwatt.svg` | Marca do meuWatt. | Sim, como referência de família visual |
| `referencias/fontes/` | As seis faces reais: Figtree 400/500/600/700 e IBM Plex Mono 500/600. | Só se o designer for produzir HTML/código |

## Por que as duas imagens importam

**A paleta** — "superfície = branco a 4% sobre #02061A" é impossível de imaginar por
escrito. Vendo os seis degraus lado a lado, fica claro que a profundidade do app vem de
variações sutis, não de contraste forte. Sem isso o designer tende a exagerar a separação
entre superfícies e o app perde o ar de vidro.

**A estrutura** — o cabeçalho colapsável é o comportamento que amarra todas as telas do
app, e é o que mais se perde na tradução para mockup estático. A imagem mostra os dois
extremos (108 pt e 52 pt) com o mesmo conteúdo, para o designer entender que é *uma* peça
que encolhe, não duas telas diferentes.

## Não existe ainda

**Logo do Gestão Solar.** O produto é novo e não tem marca própria. Duas saídas:

1. Peça ao designer para propor uma, dizendo que ela precisa conviver com a marca do
   meuWatt (mande `marca-meuwatt.svg` junto).
2. Use o nome em Figtree Bold sobre o fundo, sem símbolo, e resolva a marca depois.

A segunda é mais segura para esta rodada: marca mal resolvida contamina todas as telas
seguintes, e a rodada 1 é sobre estrutura, não sobre identidade.

**Screenshots do meuWatt atual.** Não estão no repositório. Se você tiver capturas do
dashboard (diário/mensal) no celular, mandar junto ajuda o designer a entender o que este
app está *simplificando* — mas não é obrigatório, porque o objetivo aqui é justamente não
parecer com aquilo.

## Ao receber o resultado

Antes de pedir a rodada 2, confira — o que passar aqui vira dívida em todas as próximas,
porque elas herdam estes componentes:

- [ ] Usou só as cores da paleta? O desvio mais comum é inventar um sétimo tom de status
      ou um cinza que não está na lista.
- [ ] Os números estão em fonte mono, com largura fixa, e em formato pt-BR
      (`13.800` / `29,87`)?
- [ ] O cabeçalho tem os dois estados desenhados?
- [ ] Nenhuma escolha de opção virou fileira de chips? (o segmentado Tudo/Ação/Sistema em
      Notificações é permitido; chip de seleção não)
- [ ] Os quatro estados da tela Início existem: normal, carregando, erro e offline?
- [ ] A prancha de sistema veio com card, KPI, chip, botão, campo, segmentado, item de
      lista, barra de abas e cabeçalho?

## Próximas rodadas

A ordem e o conteúdo de cada uma estão em [`../docs/prompts/README.md`](../docs/prompts/README.md).
A especificação completa das ~35 telas está em
[`../docs/PROMPT_DESIGNER.md`](../docs/PROMPT_DESIGNER.md).
