Siga para a parte 2: Documentos e Financeiro.

Reuse o que você já construiu na rodada 1 — cabeçalho colapsável, card, KPI,
chip de status, segmentado, item de lista e a barra de abas. Nada de
componente novo onde um existente serve; a barra de abas só muda qual item
está aceso.

Mesma paleta, mesma tipografia, mesmos princípios. Mesmo frame 390 × 844.

## COERÊNCIA COM O QUE JÁ EXISTE

Os dados destas telas têm de bater com os da rodada 1:

- As usinas são Porto Ferreira, Ribeirão Bonito e Araraquara.
- Hoje é 12 de agosto de 2026. Agosto é o mês corrente, então o último
  fechamento publicado é o de **julho de 2026**.
- O card Financeiro do Início diz: próximo vencimento **15/08**, mensalidade
  **R$ 4.180,00**, situação **Em dia**. A aba Financeiro precisa contar a
  mesma história — e explicar de onde vêm esses R$ 4.180,00.
- O INV-03 de Porto Ferreira está parado desde 11:20; se aparecer uma OS
  nos documentos, que seja coerente com isso.

## GRUPO 4 — DOCUMENTOS (aba 3)

**4.1 Documentos** — cabeçalho colapsável "Documentos". Segmentado de três:
**Relatórios · Ordens de serviço · Cronograma**. Abaixo, um seletor de lista
suspensa para filtrar por usina (nunca chips).

Cada item da lista traz: ícone de PDF, título, o período a que se refere,
data de emissão e tamanho do arquivo. Itens já baixados ganham um selo
discreto "disponível offline".

Três coisas importam nesta tela:
- Um relatório de fechamento tem **duas peças** — "Relatório de Geração" e
  "Anexo de Paradas". Mostre que andam juntos, sem virar dois itens soltos.
- Ordem de serviço e cronograma vêm de outro sistema (o meuPlano) e são
  gerados na hora; relatório de geração já vem publicado. Essa diferença
  pode aparecer de forma sutil, não precisa de aviso.
- Botão "+" para gerar um relatório novo, que abre a 4.2.

**4.2 Gerar relatório** — folha que sobe de baixo. Escolher tipo (Diário ·
Mensal · Anual · UCs), usina e período. Botão âmbar "Gerar PDF".
Desenhe também o **estado de geração**: barra de progresso com o texto da
etapa ("Montando o relatório…"). Esse PDF leva alguns segundos para sair —
o usuário precisa entender que está trabalhando, não travado.

**4.3 Visualizador de PDF** — barra superior fina com voltar, título,
número da página ("3 de 13") e "Compartilhar". O documento ocupa todo o
resto da tela, rolagem vertical contínua, pinçar para zoom. Nada de chrome
de aplicação sobre o papel.

**4.4 Documentos — vazio** — quando não há nada naquele filtro.

**4.5 Falha ao gerar** — o PDF não saiu. Explique em linguagem de gente o
que fazer, com botão "Tentar de novo".

## GRUPO 5 — FINANCEIRO (aba 4)

**5.1 Financeiro** — cabeçalho colapsável "Financeiro".

- No topo, um card de situação geral: verde "Tudo em dia" ou vermelho
  "1 mensalidade vencida". Desenhe as duas versões.
- Depois, um bloco por produto assinado — **meuWatt** e **meuPlano** — com
  valor mensal, dia de vencimento e a situação da competência atual. Os dois
  somados dão os R$ 4.180,00 que o Início anuncia.
- Abaixo, "Histórico": competências em ordem decrescente, cada linha com
  mês, produto, valor e chip de situação (Pago · A vencer · Em aberto ·
  Vencido). Mostre pelo menos uma de cada situação.

Uma coisa a resolver no desenho: o dono assina dois produtos mas recebe uma
conta só. A tela precisa deixar claro o total e, ao mesmo tempo, permitir
ver o que cada produto custa.

**5.2 Fatura — detalhe** — folha que sobe: produto, competência, valor,
vencimento, data de pagamento, observação, e o comprovante quando houver
(abre no visualizador de PDF da 4.3).

Não há pagamento pelo app nesta versão: as mensalidades são baixadas
manualmente por quem administra. A tela informa, não cobra — nada de botão
"Pagar agora".

## O QUE ENTREGAR

Mockup de cada tela em alta fidelidade, 390 × 844, tema escuro. Estados
alternativos lado a lado. Não precisa repetir a prancha de sistema — só
acrescente a ela se esta rodada criar alguma peça nova (a folha que sobe,
por exemplo, e a barra do visualizador de PDF).

Se alguma tela precisar de um dado que não foi especificado aqui, marque
com um comentário em vez de inventar.
