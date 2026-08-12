# Prompts fatiados para o designer

O [`PROMPT_DESIGNER.md`](../PROMPT_DESIGNER.md) é a especificação completa. Esta pasta tem
a mesma coisa **fatiada por rodada**, cada arquivo autocontido (contexto + princípios +
identidade + navegação + as telas daquela rodada), pronto para colar sem precisar de mais
nada.

## Ordem

| Rodada | Arquivo | Telas | Situação |
|---|---|---|---|
| 1 | [`01-entrada-inicio.md`](01-entrada-inicio.md) | 1.1–1.3, 2.1–2.3 | **Entregue e implementado.** O designer foi além e trouxe junto 3.1–3.6 (usinas e geração), 3.8–3.9 (equipamentos e inversor) |
| 2 | [`02-documentos-financeiro.md`](02-documentos-financeiro.md) | 4.1–4.5, 5.1–5.2 | Documentos e Financeiro |
| 3 | a escrever | 6.1–6.4, 7.1–7.4 | Assistente (com o card de credencial revelável) e as telas de sistema |
| 4 | a escrever | 3.7, 3.10–3.13 | Mapa da planta e os detalhes de estação solarimétrica e relés |
| 5 | a escrever | 3.14–3.17 | Cronograma, item do cronograma e OS |

**O que ficou para trás:** a rodada 1 pulou à frente e cobriu as telas de geração, mas o
**mapa da planta** (3.7) e o bloco de **manutenção** (3.14–3.17) continuam sem desenho. O
mapa é a tela mais difícil do produto e merece uma rodada só dele; a manutenção depende de
decidir como a matriz de 12 meses cabe em 390 pt sem virar planilha.

O primeiro arquivo é autocontido (contexto + princípios + identidade + navegação). A partir
do segundo, os prompts são de **continuidade**: presumem que o designer está no mesmo
projeto, com os componentes da rodada 1 já criados, e mandam reusá-los. Isso é o que
mantém a coerência entre rodadas — e é bem mais curto de ler.

Mandar os 7 grupos de uma vez produz resultado raso: o designer não tem espaço para pensar
em 35 telas ao mesmo tempo, e a linguagem visual sai inconsistente entre elas.

## Ao receber o resultado de uma rodada

Antes de pedir a próxima, confira:

- As cores usadas são só as da paleta? (o desvio mais comum é inventar um sétimo tom de
  status ou um cinza fora da lista)
- Os números estão em mono com largura fixa, e em formato pt-BR?
- O cabeçalho tem os dois estados desenhados?
- Nenhuma escolha de opção virou fileira de chips?

O que passar sem correção nesta rodada vira dívida em todas as seguintes, porque a rodada
seguinte herda os componentes desta.
