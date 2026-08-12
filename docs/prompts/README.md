# Prompts fatiados para o designer

O [`PROMPT_DESIGNER.md`](../PROMPT_DESIGNER.md) é a especificação completa. Esta pasta tem
a mesma coisa **fatiada por rodada**, cada arquivo autocontido (contexto + princípios +
identidade + navegação + as telas daquela rodada), pronto para colar sem precisar de mais
nada.

Mandar os 7 grupos de uma vez produz resultado raso — o designer não tem espaço para
pensar em 35 telas ao mesmo tempo, e a linguagem visual sai inconsistente entre elas.

## Ordem

| Rodada | Arquivo | Telas | Por quê nesta ordem |
|---|---|---|---|
| 1 | [`01-entrada-inicio.md`](01-entrada-inicio.md) | 1.1–1.3, 2.1–2.3 | Fixa card, KPI, faixa de atenção e cabeçalho colapsável — todo o resto herda |
| 2 | `02-usinas-geracao.md` | 3.1–3.6 | Lista, visão geral e as quatro visões de geração |
| 3 | `03-mapa-equipamentos.md` | 3.7–3.13 | Mapa da planta e os detalhes por tipo de equipamento |
| 4 | `04-manutencao.md` | 3.14–3.17 | Cronograma, item e OS |
| 5 | `05-documentos.md` | 4.1–4.5 | Central de PDF e visualizador |
| 6 | `06-financeiro.md` | 5.1–5.2 | Mensalidades |
| 7 | `07-assistente-sistema.md` | 6.1–6.4, 7.1–7.4 | Chat, credencial revelável, perfil e estados transversais |

Os arquivos das rodadas 2 a 7 são gerados a partir do `PROMPT_DESIGNER.md` no momento de
usar — o cabeçalho (contexto, princípios, identidade, navegação) é o mesmo em todos, muda
só a seção "AS TELAS DESTA RODADA" e a prancha pedida ao final.

## Ao receber o resultado de uma rodada

Antes de pedir a próxima, confira:

- As cores usadas são só as da paleta? (o desvio mais comum é inventar um sétimo tom de
  status ou um cinza fora da lista)
- Os números estão em mono com largura fixa, e em formato pt-BR?
- O cabeçalho tem os dois estados desenhados?
- Nenhuma escolha de opção virou fileira de chips?

O que passar sem correção nesta rodada vira dívida em todas as seguintes, porque a rodada
seguinte herda os componentes desta.
