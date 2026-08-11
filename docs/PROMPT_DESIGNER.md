# Prompt para o Claude Designer — Gestão Solar

> Copie deste ponto até o fim do arquivo e entregue ao designer (Claude com a skill de
> design, ou Stitch). **Entregue por lotes de telas**, um grupo por vez — mandar os 7
> grupos de uma vez produz resultado raso.
>
> Ordem sugerida: Grupo 2 (Início) → Grupo 3 (Usinas) → Grupo 1 (Entrada) →
> Grupo 4 (Documentos) → Grupo 5 (Financeiro) → Grupo 6 (Assistente) → Grupo 7 (Sistema).
> Comece pelo Início porque é ele que fixa a linguagem visual de card, KPI e cabeçalho —
> todo o resto herda dessas decisões.

---

## CONTEXTO DO PRODUTO

Você vai desenhar o **Gestão Solar**, app mobile nativo (iOS + Android) para o
**proprietário de usina solar fotovoltaica** no Brasil. Ele é o cliente final de duas
plataformas que já existem: o **meuWatt** (monitoramento de geração) e o **meuPlano**
(gestão de manutenção). O Gestão Solar é a camada simples por cima das duas.

**Quem usa:** dono de usina de médio porte (1 a 10 MWp). Não é engenheiro. Não abre o app
todo dia — abre quando quer saber "está tudo bem?" ou quando precisa de um documento.
Frequentemente está no celular, com uma mão, em local com sinal ruim.

**O que ele quer responder, nesta ordem:**

1. Minha usina está gerando bem hoje / neste mês?
2. Tem algum equipamento parado? Há quanto tempo?
3. A manutenção que eu contratei está sendo feita?
4. Preciso do relatório do mês / da OS em PDF.
5. Minha mensalidade está em dia?

**Idioma:** português do Brasil em toda a interface.

---

## PRINCÍPIOS DE DESIGN (inegociáveis)

1. **Simplicidade acima de completude.** Cada tela responde UMA pergunta. Se um dado não
   ajuda a responder a pergunta da tela, ele não entra. O erro a evitar é a densidade das
   telas de operador do meuWatt — este app é o oposto delas.
2. **Números grandes, contexto pequeno.** O KPI principal domina; unidade, comparação e
   período são secundários e menores.
3. **Cor só significa estado.** Nunca decorativa. Seis tons de status, nenhum a mais.
4. **Seta de voltar em toda tela que não seja aba raiz.** Sempre no mesmo lugar, canto
   superior esquerdo.
5. **Cabeçalho grande que colapsa ao rolar.** Estado expandido: título grande + subtítulo
   + KPI de contexto. Ao rolar, encolhe para uma faixa fina com só o título e a seta,
   liberando o conteúdo. Transição contínua acompanhando o scroll, não em degrau.
6. **Nada de "chips" para selecionar opção.** Filtros e escolhas usam lista suspensa
   pesquisável ou controle segmentado. É regra do time, vale aqui. (Tags informativas
   read-only não são chips de seleção e podem ficar.)
7. **Números em formato pt-BR:** ponto de milhar, vírgula decimal (`13.800`, `29,87`).
8. **Todo estado desenhado:** carregando (skeleton, nunca spinner solto), vazio, erro,
   offline com dado em cache (com selo "atualizado às HH:MM").
9. **Área de toque mínima 44 pt.** Nada atrás da barra de gestos do Android.

---

## IDENTIDADE VISUAL

Herdada do rebrand 2026-08 do meuWatt — tema escuro "glass". Estes valores são exatos.

### Cores

| Papel | Valor |
|---|---|
| Fundo da aplicação | `#02061A`, com halo radial azul sutil no topo |
| Superfície (card) | branco a 4% de opacidade sobre o fundo |
| Superfície elevada | branco a 8% |
| Superfície destacada | branco a 12% |
| Afundado (campo, trilho de segmentado) | preto a 25% |
| Painel flutuante (modal, sheet) | `#090E26` a 97% |
| Âmbar da marca | `#FFC315` |
| Texto sobre âmbar | `#02061A` |
| Texto âmbar | `#FFD75E` |
| Texto forte (título, KPI) | `#F5FDFF` |
| Texto corpo | `#DDE2F6` |
| Texto rótulo | `#D6C4AC` |

### Tons de status — seis, e apenas estes

| Estado | Cor |
|---|---|
| Parado / falha | `#F87171` |
| Alerta | `#FBBF24` |
| Múltiplos problemas | `#FB923C` |
| Tempo ruim (perda climática) | `#7DD3FC` |
| Normal / ok | `#34D399` |
| Sem dados | `#94A3B8` |

Receita de chip de status: fundo = cor a 10% de opacidade; borda = cor a 33%; texto = cor.

### Tipografia

- **Figtree** — toda a interface. Pesos 400 / 500 / 600 / 700.
- **IBM Plex Mono** — todo número, hora e número de série, com `tabular-nums` (para os
  dígitos não dançarem quando o valor atualiza). Obrigatório em: KPI, tabela, timestamp,
  série de equipamento.

### Forma

- Raio: 12 pt (chip, campo), 16 pt (card), 20 pt (sheet e modal).
- Espaçamento em múltiplos de 4; respiro padrão entre blocos, 16.
- Cards com borda de 1 pt em branco 8% — a separação vem da borda, não de sombra.

---

## NAVEGAÇÃO

**Barra inferior fixa, 5 abas.** Rótulo sempre visível sob o ícone. Aba ativa em âmbar.

```
┌──────────────────────────────────────┐
│ 👤                     Gestão Solar  │  ← avatar sempre no topo esquerdo
│                                      │     (estilo Nubank: toque abre perfil)
│         [ conteúdo da aba ]          │
│                                      │
├──────────────────────────────────────┤
│  🏠      ☀️      📄     💳      ✨   │
│ Início  Usinas  Docs  Financ.   IA   │
└──────────────────────────────────────┘
```

**Avatar superior** — círculo com iniciais ou foto, canto superior esquerdo, presente em
todas as abas raiz. Toque abre a tela de perfil deslizando da esquerda.

**Badge de notificação** — ponto âmbar sobre o avatar quando há item não lido.

**Empilhamento** — telas de detalhe entram deslizando da direita; sheets sobem de baixo.

---

## AS TELAS

Desenhe todas. Onde diz "colapsável", aplicar o comportamento do princípio 5.

---

### GRUPO 1 — ENTRADA

**1.1 Splash** — logo Gestão Solar centralizado sobre o fundo com halo. Sem texto.

**1.2 Login** — logo no terço superior; campos E-mail e Senha; botão âmbar "Entrar"; link
"Entrar com Google"; ao pé, "Esqueci minha senha". Texto de apoio discreto: *"Use o mesmo
login do meuWatt ou do meuPlano."* Estado de erro: faixa vermelha acima dos campos, campos
preservando o que foi digitado.

**1.3 Login — carregando** — botão vira barra de progresso indeterminada, campos travados.

---

### GRUPO 2 — INÍCIO (aba 1)

**2.1 Início** — cabeçalho colapsável: "Bom dia, Renan" + data por extenso. Conteúdo:

- **Card "Agora"** — potência instantânea somada de todas as usinas em número grande (kW),
  barra fina mostrando % da capacidade instalada e, abaixo, "energia hoje" em MWh. Se
  houver uma só usina, o card leva o nome dela.
- **Faixa de atenção** (só quando há problema) — ex.: "2 inversores parados em Porto
  Ferreira", cor conforme a severidade, toque leva ao detalhe.
- **Card meuWatt** — geração do mês, meta do mês, barra de progresso comparando as duas.
  Um número de PR abaixo, discreto.
- **Card meuPlano** — situação da manutenção: "3 de 4 serviços do mês concluídos", com
  micro-indicador de 12 células (os 12 meses) pintadas com as cores de conformidade.
- **Card Financeiro** — próximo vencimento, ou "tudo em dia" em verde.
- **Notificações recentes** — até 3 itens; rodapé "Ver todas".

**2.2 Notificações** — cabeçalho colapsável "Notificações". Segmentado: Tudo · Ação ·
Sistema. Itens com ícone por tipo, título, resumo de uma linha, tempo relativo ("há 2 h");
não lidos com barra âmbar de 3 pt à esquerda. Puxar para atualizar.

**2.3 Notificações — vazio** — ilustração leve, "Nenhuma notificação por aqui".

---

### GRUPO 3 — USINAS (aba 2)

**3.1 Lista de usinas** — cabeçalho colapsável "Minhas usinas" + contagem. Card por usina:
nome, cidade/UF, capacidade em kWp, bolinha de status; à direita, geração de hoje em MWh e
potência agora. Faixa inferior do card com sparkline da curva do dia. Busca aparece ao
rolar para cima (quando houver mais de 6 usinas).

**3.2 Usina — Visão geral** — cabeçalho colapsável com nome da usina + cidade + kWp. Abas
internas: **Geral · Geração · Mapa · Equipamentos · Manutenção** (controle segmentado com
rolagem horizontal). Conteúdo de Geral:

- Linha de 4 KPIs: Geração hoje (MWh) · Potência agora (kW) · Disponibilidade (%) · PR (%).
- Gráfico "Hoje": curva de potência ao longo do dia com irradiância em linha clara ao
  fundo, e marcador tracejado no horário atual.
- Card "Equipamentos": "18 de 20 gerando", com pontos coloridos representando cada um.
- Card "Manutenção": próximo serviço previsto e situação do cronograma.
- Card "Clima": irradiância agora, acumulada do dia, temperatura do módulo.

**3.3 Geração — Diário** — seletor de data no topo (fita de dias roláveis, hoje à direita).

- KPIs: Geração do dia · Pico de potência (com horário) · Disponibilidade · PR do dia.
- Gráfico de potência + irradiância do dia.
- **Unidades Consumidoras**: lista por UC com nome, potência agora, barra de % da
  capacidade, sparkline do dia, energia do dia, e "N/N ok".
- **Eventos do dia**: paradas e alertas em ordem cronológica, com duração.

**3.4 Geração — Mensal** — seletor de mês.

- KPIs em duas linhas: Medido · Projeto (PVsyst) · Previsto — depois Produtividade
  (kWh/kWp) · PR · Disponibilidade real · Disponibilidade contratual.
- Gráfico de barras por dia: Projeto vs Medido lado a lado; dias futuros tracejados.
- Gráfico de PR diário com linha de referência do PR de projeto.
- Card de perdas: cascata Projeto → Previsto → Medido.
- Tabela "Totais do mês" com linha de tendência projetada.

**3.5 Geração — Anual** — seletor de ano. Mesma família de KPIs em base acumulada no ano.

- Barras por mês (Projeto / Previsto / Medido).
- **Linha do tempo de disponibilidade**: grade de células dia × inversor, colorida por
  causa da parada. Rolagem horizontal, com legenda fixa.
- Tabela mês a mês com total do ano.

**3.6 Geração — UCs** — ranking das unidades consumidoras por geração, PR e produtividade
no período escolhido; série diária por UC, com a legenda funcionando como filtro; tabela
de conta de energia da distribuidora quando houver.

**3.7 Mapa da planta** — a tela mais importante e a mais difícil. Uma tela só onde o dono
vê **tudo que está instalado e gerando**. Diagrama esquemático vertical, rolável:

- Topo: faixa de resumo — potência agora, energia hoje, PR, "18/20 equipamentos ok".
- Bloco de proteção geral (relé de proteção) com estado.
- Para cada transformador/skid: um cartão agrupando seus inversores; cada inversor é uma
  célula com nome curto, potência atual e cor de status; toque abre o detalhe.
- Bloco para estação solarimétrica (irradiância, temperatura) e relé de temperatura.
- Pinçar para dar zoom e arrastar para navegar; botão "Ajustar à tela".
- Desenhe também o estado com equipamento em falha (célula vermelha pulsando suavemente).

**3.8 Equipamentos — lista** — agrupada por tipo (Inversores, Estação solarimétrica, Relé
de proteção, Relé de temperatura, Transformadores). Cada linha: nome, modelo, potência
atual ou leitura principal, chip de status.

**3.9 Equipamento — inversor** — cabeçalho colapsável com nome + modelo + série.

- KPIs: Gerando agora (kW) · Hoje (kWh) · No mês (MWh) · Temperatura.
- Chip de estado grande: "Gerando" / "Parado há 3 h 20 min" / "Alerta".
- Gráfico de potência do dia, com seletor de data.
- **Histórico de paradas**: lista com início, fim, duração e causa; energia perdida
  estimada quando houver.
- Quando em falha: card com código e descrição em português.

**3.10 Equipamento — estação solarimétrica** — irradiância agora (W/m²), acumulada do dia,
temperatura ambiente e de módulo; gráfico do dia com as duas curvas; estado de comunicação.

**3.11 Equipamento — relé de proteção** — estado, e lista de eventos de trip com data,
hora e tipo.

**3.12 Equipamento — relé de temperatura** — leituras atuais por canal e gráfico do dia.

**3.13 Histórico de paradas** — todas as paradas da usina num período, agrupadas por dia;
cada item com equipamento, duração, causa e perda estimada. Filtro por equipamento e por
período (lista suspensa, não chips).

**3.14 Manutenção — cronograma** — **matriz de 12 meses × itens do plano**. Linhas são os
serviços contratados (ex.: "Termografia", "Análise de óleo"), colunas são os meses; cada
célula pintada: verde (cumprido) · azul (dentro do prazo) · laranja (venceu há pouco) ·
vermelho (vencido) · vazio (não se aplica). Rolagem horizontal com a coluna de nomes fixa.
Legenda ao pé. Toque na célula abre o detalhe.

**3.15 Cronograma — detalhe do item** — sheet subindo: nome do serviço, mês, situação, e
lista das OS que o atenderam, cada uma com data, técnico e botão para abrir.

**3.16 Lista de OS** — filtros de período e situação em lista suspensa. Cada item: número,
título, data, técnico, chip de situação (Aberta · Programada · Em execução · Fechada ·
Aprovada). Agrupada por mês.

**3.17 OS — detalhe** — cabeçalho colapsável com número + título. Corpo: usina, técnico
responsável, datas, classificação; lista de tarefas com situação individual; parecer
técnico; fotos em carrossel; botão âmbar fixo ao pé: **"Baixar PDF"**.

---

### GRUPO 4 — DOCUMENTOS (aba 3)

**4.1 Documentos** — cabeçalho colapsável "Documentos". Segmentado: **Relatórios · Ordens
de serviço · Cronograma**. Filtro por usina quando houver mais de uma.

- Cada item: ícone de PDF, título, período a que se refere, data de emissão, tamanho.
- Itens já baixados ganham selo "disponível offline".

**4.2 Gerar relatório** — sheet acionado pelo botão "+": escolher tipo (Diário · Mensal ·
Anual · UCs), usina e período; botão "Gerar PDF". Estado de geração com barra de progresso
e texto de etapa ("Montando o relatório…").

**4.3 Visualizador de PDF** — barra superior com voltar, título, número da página e
"Compartilhar". O documento ocupa o resto da tela, rolagem vertical contínua, pinçar para
zoom. Sem chrome de aplicação sobre o papel.

**4.4 Documentos — vazio** e **4.5 — falha ao gerar** (com botão "Tentar de novo").

---

### GRUPO 5 — FINANCEIRO (aba 4)

**5.1 Financeiro** — cabeçalho colapsável "Financeiro". Card de situação no topo: verde
"Tudo em dia" ou vermelho "1 mensalidade vencida". Abaixo, um bloco por produto assinado:

- **meuWatt** — valor mensal, dia de vencimento, situação da competência atual.
- **meuPlano** — idem.

Depois, "Histórico" — lista de competências em ordem decrescente, cada uma com mês,
produto, valor e chip de situação (Pago · A vencer · Em aberto · Vencido).

**5.2 Fatura — detalhe** — sheet: produto, competência, valor, vencimento, data de
pagamento, observação, e o comprovante quando houver (abre no visualizador de PDF).

---

### GRUPO 6 — ASSISTENTE (aba 5)

**6.1 Chat** — cabeçalho colapsável "Assistente". Balões: usuário à direita em âmbar suave,
assistente à esquerda em superfície. Composer fixo ao pé, acima da barra de abas, que sobe
junto com o teclado. Botão de microfone para ditar.

**6.2 Chat — estado inicial** — sem histórico: saudação curta e 4 sugestões prontas em
lista vertical ("Quando foi a última manutenção do inversor 3?", "Qual a senha do portal da
concessionária?", "O que está previsto para o próximo mês?", "Por que a geração caiu
ontem?").

**6.3 Chat — resposta com credencial** — quando o assistente devolve uma senha/acesso, ela
vem **oculta** num card dedicado: nome do acesso, usuário visível, senha como `••••••••` e
botão "Revelar". Ao tocar, diálogo de confirmação avisando que a revelação é registrada;
depois o valor aparece por 30 s com botão de copiar, e volta a ocultar. Desenhe os três
momentos.

**6.4 Chat — pensando** — três pontos animados no balão do assistente, com a etapa atual em
texto pequeno ("consultando as usinas…").

---

### GRUPO 7 — PERFIL E SISTEMA

**7.1 Perfil** — avatar grande, nome, e-mail, empresa. Lista: Notificações · Novidades ·
Configurações · Ajuda · Sair (em vermelho).

**7.2 Configurações** — notificações por tipo (comutadores), tema, unidades, limpar cache,
versão do app.

**7.3 Novidades** — changelog em cartões por versão, o mais novo primeiro.

**7.4 Estados transversais** — prancha com: skeleton de carregamento de card e de lista;
estado vazio genérico; erro de conexão com botão "Tentar de novo"; faixa de offline no topo
("Sem conexão — mostrando dados de 14:30").

---

## O QUE ENTREGAR

Para cada tela: mockup em alta fidelidade, **390 × 844 pt** (iPhone 14), tema escuro.
Onde a tela tiver estados relevantes (vazio, erro, carregando, em falha), entregue as
variações lado a lado.

Ao final, uma **prancha de sistema** com: paleta aplicada, escala tipográfica, e os
componentes base — card, KPI, chip de status, botão, campo, controle segmentado, item de
lista, barra de abas, e o cabeçalho nos dois estados (expandido e colapsado).

**Não invente** dados fora do domínio, cores fora da paleta, nem telas fora desta lista.
Se uma tela precisar de um dado que não foi especificado aqui, marque com um comentário em
vez de inventar.
