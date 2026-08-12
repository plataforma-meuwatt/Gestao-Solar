Você vai desenhar o **Gestão Solar**, app mobile nativo (iOS + Android) para o
proprietário de usina solar fotovoltaica no Brasil. Ele é o cliente final de duas
plataformas que já existem: o meuWatt (monitoramento de geração) e o meuPlano
(gestão de manutenção). O Gestão Solar é a camada simples por cima das duas.

Nesta rodada, desenhe apenas os GRUPOS 1 e 2 (entrada e aba Início).

## QUEM USA

Dono de usina de médio porte (1 a 10 MWp). Não é engenheiro. Não abre o app todo
dia — abre quando quer saber "está tudo bem?" ou quando precisa de um documento.
Frequentemente está no celular, com uma mão, em local com sinal ruim.

O que ele quer responder, nesta ordem:
1. Minha usina está gerando bem hoje / neste mês?
2. Tem algum equipamento parado? Há quanto tempo?
3. A manutenção que eu contratei está sendo feita?
4. Preciso do relatório do mês / da OS em PDF.
5. Minha mensalidade está em dia?

Idioma: português do Brasil em toda a interface.

## PRINCÍPIOS (inegociáveis)

1. Simplicidade acima de completude. Cada tela responde UMA pergunta. Se um dado
   não ajuda a responder a pergunta da tela, ele não entra.
2. Números grandes, contexto pequeno. O KPI principal domina; unidade,
   comparação e período são secundários e menores.
3. Cor só significa estado. Nunca decorativa. Seis tons de status, nenhum a mais.
4. Seta de voltar em toda tela que não seja aba raiz, sempre no canto superior
   esquerdo.
5. Cabeçalho grande que colapsa ao rolar. Expandido: título grande + subtítulo.
   Ao rolar, encolhe para uma faixa fina com só o título e a seta. Transição
   contínua acompanhando o scroll, nunca em degrau.
6. Nada de "chips" para selecionar opção. Filtros e escolhas usam lista suspensa
   pesquisável ou controle segmentado. Tags informativas read-only podem ficar.
7. Números em pt-BR: ponto de milhar, vírgula decimal (13.800 / 29,87).
8. Todo estado desenhado: carregando (skeleton, nunca spinner solto), vazio,
   erro, e offline com dado em cache (selo "atualizado às HH:MM").
9. Área de toque mínima 44 pt. Nada atrás da barra de gestos do Android.

## IDENTIDADE VISUAL

Tema escuro "glass". Estes valores são exatos — não substitua nem aproxime.

Cores:
- Fundo da aplicação: #02061A, com halo radial azul sutil no topo
- Superfície (card): branco a 4% de opacidade sobre o fundo
- Superfície elevada: branco a 8%
- Superfície destacada: branco a 12%
- Afundado (campo, trilho de segmentado): preto a 25%
- Painel flutuante (modal, sheet): #090E26 a 97%
- Âmbar da marca: #FFC315
- Texto sobre âmbar: #02061A
- Texto âmbar: #FFD75E
- Texto forte (título, KPI): #F5FDFF
- Texto corpo: #DDE2F6
- Texto rótulo: #D6C4AC

Tons de status — seis, e apenas estes:
- Parado / falha: #F87171
- Alerta: #FBBF24
- Múltiplos problemas: #FB923C
- Tempo ruim (perda climática): #7DD3FC
- Normal / ok: #34D399
- Sem dados: #94A3B8

Receita do chip de status: fundo = cor a 10% de opacidade, borda = cor a 33%,
texto = cor cheia.

Tipografia:
- Figtree — toda a interface. Pesos 400 / 500 / 600 / 700.
- IBM Plex Mono — todo número, hora e número de série, com tabular-nums.
  Obrigatório em KPI, tabela e timestamp: com fonte proporcional os dígitos
  mudam de largura e o número treme a cada atualização.

Forma:
- Raio: 12 pt (chip, campo), 16 pt (card), 20 pt (sheet e modal)
- Espaçamento em múltiplos de 4; respiro padrão entre blocos, 16
- Cards com borda de 1 pt em branco 8% — a separação vem da borda, não de
  sombra (sombra sobre fundo quase preto não aparece)

## NAVEGAÇÃO

Barra inferior fixa com 5 abas, rótulo sempre visível sob o ícone, aba ativa em
âmbar: Início · Usinas · Documentos · Financeiro · Assistente.

Avatar circular com iniciais no canto superior ESQUERDO, presente em todas as
abas raiz (estilo Nubank) — toque abre o perfil deslizando da esquerda. Ponto
âmbar sobre o avatar quando há notificação não lida.

Geração e manutenção NÃO são abas: vivem dentro da usina. A barra responde
"que assunto?", não "que tela?".

## AS TELAS DESTA RODADA

### GRUPO 1 — ENTRADA

**1.1 Splash** — logo Gestão Solar centralizado sobre o fundo com halo. Sem texto.

**1.2 Login** — logo no terço superior; campos E-mail e Senha; botão âmbar
"Entrar"; link "Entrar com Google"; ao pé, "Esqueci minha senha". Texto de apoio
discreto abaixo do botão: "Use o mesmo login do meuWatt ou do meuPlano." (essa
linha é necessária: sem ela o dono não sabe qual senha digitar).
Estado de erro: faixa vermelha acima dos campos, com os campos preservando o que
foi digitado — refazer o e-mail por causa de erro de senha é atrito que faz
desistir.

**1.3 Login — carregando** — o botão vira barra de progresso indeterminada,
campos travados.

### GRUPO 2 — INÍCIO (aba 1)

**2.1 Início** — cabeçalho colapsável: "Bom dia, Renan" + data por extenso.
Conteúdo, nesta ordem:

- Card "Agora" — potência instantânea somada de todas as usinas em número
  grande (kW), barra fina mostrando % da capacidade instalada e, abaixo,
  "energia hoje" em MWh. Se houver uma só usina, o card leva o nome dela.
- Faixa de atenção (só aparece quando há problema) — ex.: "2 inversores parados
  em Porto Ferreira", cor conforme a severidade, toque leva ao detalhe.
- Card meuWatt — geração do mês, meta do mês, e uma barra de progresso
  comparando as duas. Um número de PR (performance ratio) abaixo, discreto.
- Card meuPlano — situação da manutenção: "3 de 4 serviços do mês concluídos",
  com micro-indicador de 12 células (os 12 meses) pintadas com as cores de
  conformidade (verde cumprido, azul no prazo, laranja venceu há pouco, vermelho
  vencido, vazio não se aplica).
- Card Financeiro — próximo vencimento, ou "tudo em dia" em verde.
- Notificações recentes — até 3 itens; rodapé "Ver todas".

**2.2 Notificações** — cabeçalho colapsável "Notificações". Controle segmentado:
Tudo · Ação · Sistema. Itens com ícone por tipo, título, resumo de uma linha,
tempo relativo ("há 2 h"); não lidos com barra âmbar de 3 pt à esquerda. Puxar
para atualizar.

**2.3 Notificações — vazio** — ilustração leve, "Nenhuma notificação por aqui".

### ESTADOS OBRIGATÓRIOS DESTA RODADA

Além das telas acima, desenhe para a 2.1 Início:
- skeleton de carregamento (cards em esqueleto, sem spinner)
- erro de conexão com botão "Tentar de novo"
- faixa de offline no topo: "Sem conexão — mostrando dados de 14:30"

## O QUE ENTREGAR

Mockup em alta fidelidade de cada tela, 390 × 844 pt (iPhone 14), tema escuro.
Estados relevantes lado a lado.

Ao final desta rodada, uma prancha de sistema com os componentes que as próximas
rodadas vão herdar: card, KPI, chip de status, botão, campo de texto, controle
segmentado, item de lista, barra de abas, e o cabeçalho nos dois estados
(expandido e colapsado).

Não invente cores fora da paleta, telas fora desta lista, nem dados fora do
domínio. Se uma tela precisar de um dado que não foi especificado, marque com um
comentário em vez de inventar.
