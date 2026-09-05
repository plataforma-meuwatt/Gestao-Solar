/**
 * O que o Painel de energia lê do BFF — e nada além disso.
 *
 * Cinco leituras, todas do mesmo assunto ("quanto esta usina gerou e era para gerar"):
 *
 * - `plants/{id}` — quem é a usina (nome, cidade, capacidade) e como ela está agora. É só o
 *   cabeçalho da página; os números do painel vêm das outras três.
 * - `energia/usinas/{id}/painel?recorte=mes|ano` — o dashboard do mês e o do ano: geração,
 *   performance, desvios, conciliação com a conta de energia, série diária/mensal,
 *   meteorologia e (no ano) a linha do tempo por inversor.
 * - `energia/usinas/{id}/dia?data=` — a operação de um dia: números, curva, eventos e UCs.
 * - `energia/usinas/{id}/unidades?recorte=mes|ano` — o comparativo entre unidades
 *   consumidoras. **Endereço próprio, não `?recorte=unidades`**: a tela carrega o
 *   comparativo sem arrastar o painel inteiro junto.
 * - `energia/usinas/{id}/relatorio-mes?referencia=` — o FECHAMENTO do mês: energia
 *   potencial, perdas com a base declarada, causas classificadas, horas paradas com o
 *   denominador, as considerações escritas pela equipe e a timeline curada. **Sem
 *   `recorte`**: o fechamento é sempre mensal.
 *
 * Os tipos são o espelho dos schemas de `bff/app/api/v1/energia.py`, com uma regra que
 * atravessa todos: **`null` é ausência, e ausência não é zero.** Onde o BFF escreve
 * `float | None`, aqui é `number | null`, e a tela imprime "—". Coalescer nulo para zero
 * transformaria "não medimos" em "não gerou" no meio de uma reunião de contrato.
 *
 * O que NÃO está aqui é tão deliberado quanto o que está: o número de série do inversor, o
 * id do transformador e as bandeiras internas de descarte de PR ficam do lado de lá da
 * ponte, por decisão do BFF. A UC é identificada por NOME e por um índice estável da
 * resposta; o inversor, pela etiqueta da posição.
 */

import { useLeitura, type Leitura } from '@/lib/leitura'

/* ------------------------------------------------------------------ a usina */

/**
 * A usina como o cabeçalho da página a mostra.
 *
 * É um subconjunto declarado do `UsinaDetalheOut` do BFF: os campos de contagem de aparelho
 * existem na resposta e ficam de fora do tipo de propósito — o que não é lido aqui não pode
 * escapar para a tela por descuido.
 */
export type UsinaDetalhe = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
  capacidade_kwp: number | null
  /** Nulo = sem comunicação. "Não sabemos" ≠ "não está gerando". */
  potencia_kw: number | null
  energia_hoje_kwh: number | null
  disponibilidade_pct: number | null
  /** Quanto da capacidade está em uso agora, 0–100. Nulo quando falta um dos dois. */
  pct_capacidade: number | null
  /** Um dos seis tons, já decidido pelo servidor. */
  tom: string
  situacao: string
  fora_da_janela_solar: boolean
  tem_meuwatt: boolean
  tem_meuplano: boolean
  aviso: string | null
}

/* ------------------------------------------------------------------ o painel */

/** Os desvios estruturais, COM SINAL: positivo = acima da referência. */
export type Desvios = {
  medido_vs_projeto_pct: number | null
  medido_vs_previsto_pct: number | null
  /** O efeito do clima: quanto a irradiação real afastou o previsto do projeto. */
  previsto_vs_projeto_pct: number | null
  /**
   * A irradiação MEDIDA contra a do projeto, nos dois planos. É o que separa "o sol não
   * veio" de "a usina não rendeu"; nulo quando a usina não tem irradiação de projeto
   * cadastrada, e aí a linha nem aparece.
   */
  hpoa_vs_projeto_pct: number | null
  ghi_vs_projeto_pct: number | null
}

export type Conciliacao = {
  /** `fronteira − faturado`, nesta ordem. A tela repete o sinal do servidor; inverter a
   *  subtração numa das duas pontas daria dois números para a mesma diferença. */
  fronteira_mwh: number | null
  faturado_mwh: number | null
  diferenca_mwh: number | null
  diferenca_pct: number | null
  /**
   * `Conciliado` · `Pequena divergência` · `Divergência relevante`. Nulo quando falta um dos
   * dois lados (fatura ainda não emitida é ESTADO, não erro) e nulo também quando a
   * fronteira é parcial — classificar cobertura incompleta como divergência mandaria o
   * cliente cobrar da distribuidora um defeito do medidor dele.
   */
  situacao: string | null
  tolerancia_pct: number
  /**
   * Os meses que a conferência cobre — os que têm medidor E fatura.
   *
   * É a ÚNICA conta do painel com janela própria, e por isso ela a declara: a fatura de um
   * mês recém-fechado leva semanas para sair, e somar a fronteira de um mês sem fatura
   * inventaria uma divergência do tamanho daquele mês. Vazio no recorte `mes`, onde a
   * janela é o próprio mês.
   */
  meses: string[]
}

/** Um mês do período que NÃO entrou no acumulado, e por quê. */
export type MesForaDoAcumulado = {
  mes: string
  rotulo: string
  /** `futuro` · `sem_medicao` · `sem_detalhe_mensal`. */
  motivo: string
}

/**
 * QUAIS meses o acumulado somou — e quais ficaram de fora, com o motivo.
 *
 * É a peça que faz a tela poder DIZER de onde o número saiu. Todo acumulado do painel
 * (medido, projeto, previsto, perdida, fronteira, irradiação, temperatura) sai desta
 * janela; a única exceção declarada é a conciliação, que tem a sua em `Conciliacao.meses`.
 *
 * Sem isto, consertar o número só adiava a pergunta: o cliente que lê "atingimento 102%"
 * pergunta em seguida "sobre que meses?", e a tela não tinha como responder.
 */
export type Janela = {
  /** Os meses (`YYYY-MM`) somados, em ordem. */
  meses: string[]
  fora: MesForaDoAcumulado[]
  /** "jun a set de 2026" — pronto para a tela escrever ao lado do número. */
  rotulo: string | null
  /** A janela cobre menos do que o período pedido. */
  parcial: boolean
  /** A regra, escrita pelo servidor em linguagem de cliente. A tela imprime. */
  regra: string
}

export type Totais = {
  /** Medido e projeto na MESMA janela (`Painel.janela`) — os dois lados da comparação. */
  medido_kwh: number | null
  /** O projeto do PERÍODO INTEIRO (o mês fechado, os doze meses do ano) — o alvo, futuro
   *  incluído. É outra pergunta, e não o denominador de nada. */
  projeto_kwh: number | null
  /** O projeto NA JANELA DO ACUMULADO — o par de `medido_kwh`. */
  projeto_ate_hoje_kwh: number | null
  /** Projeção linear do fechamento, só no período em curso. Prever o passado não é previsão. */
  tendencia_kwh: number | null
}

export type DiaDoMes = {
  dia: number
  data: string
  medido_kwh: number | null
  projeto_kwh: number | null
  /** Nulo quando o dia não tem PR. Dia sem PR NÃO vira 0%. */
  pr_pct: number | null
  /** O monitoramento descartou a leitura por implausibilidade — a tela escreve "descartada". */
  pr_descartado: boolean
  /** O que faz a barra sair tracejada em vez de rasteira. */
  futuro: boolean
}

export type MesDoAno = {
  /** `YYYY-MM`. */
  mes: string
  rotulo: string
  medido_kwh: number | null
  projeto_kwh: number | null
  previsto_kwh: number | null
  desvio_vs_projeto_pct: number | null
  pr_pct: number | null
  disponibilidade_real_pct: number | null
  disponibilidade_contratual_pct: number | null
  perdida_kwh: number | null
  perdida_externa_kwh: number | null
  fronteira_mwh: number | null
  faturado_mwh: number | null
  /**
   * De onde saiu a disponibilidade DESTA linha: `mes_conferido` (o mesmo número que a aba
   * Mês publica para aquele mês) ou `rollup_do_ano` (o resumo anual do monitoramento, rede
   * de segurança de quando a leitura do mês não veio). Os dois discordam no upstream, e
   * num número de teor contratual a tela precisa dizer qual está mostrando.
   */
  disponibilidade_origem: string | null
  /** O mês entrou no acumulado do período (ver `Painel.janela`). */
  no_acumulado: boolean
  em_curso: boolean
  futuro: boolean
}

export type PontoMeteo = {
  /** `YYYY-MM-DD` no mês, `YYYY-MM` no ano. */
  chave: string
  rotulo: string
  hpoa: number | null
  hpoa_projeto: number | null
  ghi: number | null
  /** A PARCELA do projeto no plano horizontal — a mesma que `meteo.ghi_projeto` soma. */
  ghi_projeto: number | null
  t_amb: number | null
  t_mod: number | null
  t_mod_max: number | null
}

export type Meteo = {
  /** Sem estação não há irradiação medida — e sem ela não há PR. É o portão que faz a tela
   *  esconder o bloco em vez de desenhar quatro travessões. */
  tem_estacao: boolean
  tem_sensor_temperatura: boolean
  hpoa: number | null
  ghi: number | null
  /** `hpoa ÷ ghi` — quanto o plano inclinado ganha sobre o horizontal. */
  razao: number | null
  /**
   * A irradiação de PROJETO do período, na mesma janela do medido — nos dois planos.
   *
   * No ano ela só sai quando cobre TODOS os meses do acumulado: referência de quatro meses
   * ao lado de medição de sete devolvia "+176% de sol". Referência parcial não vira
   * comparação — e aí a tela mostra a medida sozinha, que é verdade.
   */
  hpoa_projeto: number | null
  ghi_projeto: number | null
  /** `pvsyst_diario` ou `mensal_digitado` — qual fonte do projeto falou. O digitado é um
   *  número do mês inteiro, e por isso a coluna da tabela pode sair em travessão sem que o
   *  total esteja errado. */
  hpoa_projeto_origem: string | null
  ghi_projeto_origem: string | null
  t_amb_media: number | null
  t_amb_max: number | null
  t_mod_media: number | null
  t_mod_max: number | null
  pontos: PontoMeteo[]
}

/** Um trecho contínuo de dias no mesmo estado — as duas pontas incluídas. */
export type FaixaTecnica = {
  de: string
  ate: string
  dias: number
  /** `operando` · `potencia_zero` · `falha_comunicacao` · `nao_instalado` · `sem_dado`. */
  estado: string
}

export type InversorTecnico = {
  /** A etiqueta da POSIÇÃO. Nunca o número de série. */
  nome: string
  disponibilidade_pct: number | null
  faixas: FaixaTecnica[]
}

/**
 * Tempo de pé por inversor — uma régua DIFERENTE da dos cartões.
 *
 * O `aviso` vem escrito do servidor e é obrigatório na tela: os cartões medem
 * disponibilidade ENERGÉTICA (kWh perdidos) e esta mede TEMPO. Publicá-los lado a lado sem
 * dizer isso entregaria dois percentuais contraditórios num documento de teor contratual.
 */
export type DisponibilidadeTecnica = {
  aviso: string
  primeiro_dia: string
  ultimo_dia: string
  inversores: InversorTecnico[]
}

/** As fórmulas em linguagem de cliente. A tela imprime; não recalcula nada. */
export type Regra = {
  disponibilidade: string
  contratual: string
  perda_distribuida: string
  origem: string
}

export type Painel = {
  recorte: string
  referencia: string
  inicio: string
  fim: string
  rotulo: string
  /** Período ainda aberto — há dias futuros, e o fechamento é projeção. */
  em_curso: boolean
  /** Dia do mês até onde há medição. Nulo em período fechado. */
  dia_de_corte: number | null

  capacidade_kwp: number | null

  medido_inversores_kwh: number | null
  /** A medição do OUTRO aparelho (SSU), no ponto de entrega. Nulo sem medidor. */
  medido_fronteira_kwh: number | null
  /** Só sai quando a diferença entre os dois é fisicamente uma perda. */
  perda_inv_fronteira_pct: number | null
  /**
   * A fronteira não cobre a mesma usina que os inversores (medidor instalado no meio do
   * período, medidor a menos, leitura falhada). O número continua sendo medição — a tela o
   * rotula como parcial e NÃO desenha a perda, porque a diferença não é perda.
   */
  fronteira_parcial: boolean
  /** Os meses da janela que REALMENTE têm leitura de medidor. Pode ser mais curto que
   *  `janela.meses` — e quando é, a tela DIZ, porque o número grande sai só desses. */
  fronteira_meses: string[]
  /** A meta do PERÍODO INTEIRO — o alvo, futuro incluído. No recorte `ano` ela coincide com
   *  a da janela; no `mes` é o mês fechado. Não é o denominador de nada. */
  projeto_kwh: number | null
  /** A meta NA JANELA DO ACUMULADO — o par de `medido_inversores_kwh` e o denominador de
   *  `atingimento_pct`. É este o número que a coluna da tabela tem de somar. */
  projeto_proporcional_kwh: number | null
  /**
   * `medido ÷ projeto` na janela, em %.
   *
   * É EXATAMENTE o `pct_do_projeto` da tela de desempenho — mesma janela, mesma fonte,
   * mesmo arredondamento. A tela IMPRIME; recalcular aqui (de `100 + desvio`, por exemplo)
   * é como o mesmo portal acabou exibindo 36% numa tela e 101,7% na outra.
   */
  atingimento_pct: number | null
  /** `pvsyst_diario` ou `mensal_digitado` — de onde veio a meta. */
  projeto_origem: string | null
  previsto_kwh: number | null
  /**
   * De onde veio o previsto: `manual_corrigido` (a meta mensal corrigida pela irradiação
   * MEDIDA) ou — quando não houve correção — a própria origem do projeto
   * (`pvsyst_diario` / `mensal_digitado`), porque aí o previsto É o projeto.
   *
   * ⛔ Quem escreve a frase é `origemDoPrevisto`, uma só, e ela só fala em correção quando
   * a origem é `manual_corrigido`.
   */
  previsto_origem: string | null

  produtividade_kwh_kwp: number | null
  pr_pct: number | null
  disponibilidade_real_pct: number | null
  disponibilidade_contratual_pct: number | null
  /** Paradas ainda sem causa classificada. Enquanto houver, a contratual está incompleta. */
  paradas_pendentes: number
  perdida_kwh: number | null
  perdida_externa_kwh: number | null

  desvios: Desvios
  conciliacao: Conciliacao
  totais: Totais
  meteo: Meteo
  /** De onde saíram os acumulados. A tela imprime; ver `Janela`. */
  janela: Janela
  regra: Regra

  dias: DiaDoMes[]
  meses: MesDoAno[]

  /**
   * Os meses do ano que TÊM medição, para o seletor pular os vazios. Vem preenchido só no
   * recorte `ano`. Nulo = "não consultado neste recorte" e a tela libera os meses passados;
   * `[]` = consultado e nenhum mês tem dado.
   */
  meses_disponiveis: string[] | null

  disponibilidade_tecnica: DisponibilidadeTecnica | null

  aviso: string | null
}

/* ------------------------------------------------------------------ o dia */

export type PontoCurva = {
  hora: string
  kw: number
  /** Irradiância no plano dos módulos, W/m². Nulo quando a usina não tem estação. */
  poa: number | null
}

export type EventoDoDia = {
  hora: string
  /** A etiqueta do slot dada pelo operador. O número de série NUNCA sai do BFF. */
  inversor: string
  evento: string
  duracao_min: number | null
  resolvido_em: string | null
  em_curso: boolean
}

export type UnidadeDoDia = {
  /** Índice estável desta UC dentro da resposta — é por ele que a tela a referencia. */
  indice: number
  nome: string
  kwp: number | null
  inversores: number
  potencia_agora_kw: number | null
  pct_capacidade: number | null
  energia_kwh: number | null
  ok: number
  total: number
  /** Potência média em cada fatia de 15 min, alinhada a `faisca_horas`. Nulo numa posição
   *  = a UC não reportou naquela fatia; é lacuna, não zero. */
  faisca: (number | null)[]
}

export type Dia = {
  dia: string
  gerado_kwh: number | null
  pico_kw: number | null
  pico_hora: string | null
  potencia_agora_kw: number | null
  inversores_gerando: number | null
  inversores_total: number | null
  disponibilidade_pct: number | null
  /** Nulo quando não há estação **ou** quando o meuWatt descartou a leitura — e aí
   *  `pr_descartado` é `true`, para a tela escrever "descartada" em vez de desenhar zero. */
  pr_pct: number | null
  pr_descartado: boolean
  hpoa_agora: number | null
  hpoa_acumulada: number | null
  ghi_acumulada: number | null
  /**
   * A usina TEM estação solarimétrica — pergunta de CADASTRO, respondida pela mesma lista de
   * aparelhos da tela de equipamentos. O ativo é permanente: ele não deixa de existir às 3h
   * da manhã só porque ainda não houve sol.
   */
  tem_estacao: boolean
  /** A estação MEDIU alguma coisa neste dia. É o outro lado da pergunta, e é o que separa
   *  "não existe" de "ainda não mediu" — de madrugada isto é falso e `tem_estacao` continua
   *  verdadeiro. Enquanto era um campo só, a tela negava de manhã uma estação que existe. */
  estacao_com_leitura: boolean
  /** O cadastro não pôde ser lido, e `tem_estacao` caiu na leitura do dia. A tela NÃO pode
   *  afirmar "não tem estação" com base num palpite. */
  estacao_indefinida: boolean
  curva: PontoCurva[]
  /** Vazio = operação sem incidentes. É estado, não falta de dado. */
  eventos: EventoDoDia[]
  ucs: UnidadeDoDia[]
  /** As horas das fatias da faísca — uma só para todas as UCs, na mesma escala de tempo. */
  faisca_horas: string[]
  aviso: string | null
}

/* ------------------------------------------------------------------ unidades */

export type SerieDaUnidade = {
  indice: number
  nome: string
  /** Um valor por dia de `serie_dias`. Nulo = sem leitura naquele dia. */
  valores: (number | null)[]
}

export type UnidadeDoPeriodo = {
  indice: number
  nome: string
  capacidade_kwp: number | null
  inversores: number
  geracao_kwh: number | null
  share_pct: number | null
  produtividade: number | null
  /** Nulo quando o monitoramento não pareou o dado — nunca 0. */
  pr_pct: number | null
  disponibilidade_real_pct: number | null
  disponibilidade_contratual_pct: number | null
  /** Nulo = fatura ainda não emitida, que é estado e não erro. */
  faturado_mwh: number | null
}

export type Unidades = {
  recorte: string
  inicio: string
  fim: string
  ucs_ativas: number
  capacidade_total_kwp: number | null
  energia_periodo_kwh: number | null
  maior: { nome: string; share_pct: number | null } | null
  ucs: UnidadeDoPeriodo[]
  serie_dias: string[]
  serie: SerieDaUnidade[]
  /** Os rankings saem prontos do servidor, como a ordem dos `indice`, para as três listas
   *  não divergirem entre telas. */
  ranking_geracao: number[]
  ranking_pr: number[]
  ranking_produtividade: number[]
  pr_referencia_pct: number
  /** Nulo = nenhuma fatura emitida para o período. "Parcial" = faltam UCs. */
  faturas_situacao: string | null
  aviso: string | null
}

/* ------------------------------------------------------------------ o fechamento */

/**
 * Uma fatia do ranking de causas — por que a usina parou e quanto isso custou.
 *
 * `classificada: false` é a categoria "Não classificada": não é uma causa, é a AUSÊNCIA
 * dela. Ela fica no ranking de propósito — escondê-la esconderia justamente a energia sem
 * explicação, que é a parcela que ainda pode mudar de lado na conta contratual.
 */
export type CausaDaParada = {
  categoria: string
  eventos: number
  /** Nulo = o monitoramento não trouxe o número em nenhum evento da categoria. */
  energia_kwh: number | null
  /** Horas somadas por inversor afetado. Nulo quando algum evento veio sem duração —
   *  somar só os que têm faria a conta parecer menor do que foi. */
  horas: number | null
  /** A causa estava fora do alcance da manutenção. É o que a contratual desconta. */
  externa: boolean
  classificada: boolean
}

/**
 * Uma parada do mês, com a causa e a classificação.
 *
 * **A contagem é por parada, não por evento agrupado por escopo.** O agrupamento
 * "usina / skid / inversor" do meuWatt mora no front dele e em endpoints que respondem 403
 * ao nosso token; a frase que declara isso vem pronta do servidor (`eventos_agrupamento`) e
 * a tela a imprime. Inventar um segundo detector aqui daria duas contagens para a mesma
 * pergunta na primeira vez que o de lá mudasse.
 */
export type EventoDeParada = {
  /** Dia BRT de início, `YYYY-MM-DD` — o mesmo critério de recorte da tela de Paradas. */
  inicio: string
  /** Nulo = ainda em aberto. */
  fim: string | null
  em_aberto: boolean
  /** `parada` (inversor sem produzir) ou `degradacao` (produzindo abaixo dos pares). */
  tipo: string
  unidade: string | null
  /** Nulo = ainda não classificada. */
  causa: string | null
  origem: string | null
  externa: boolean
  classificada: boolean
  /** Só passa de 1 quando a própria equipe agrupou as linhas no monitoramento. */
  inversores_afetados: number
  horas: number | null
  energia_kwh: number | null
}

/** Um card da timeline curada. Conteúdo 100% autorado pela operação. */
export type MarcoDaTimeline = {
  id: string
  /** Instante do marco, ISO. */
  em: string
  /** `parada | retomada | normalizado | recorrente | degradacao | manutencao | info` —
   *  vocabulário NARRATIVO do meuWatt, que não é o dos seis tons do portal. Quem traduz é
   *  `tomDoMarco`, em `Relatorio.tsx`. */
  tom: string
  chip: string
  titulo: string
  sub: string | null
  grupo: string | null
}

export type TimelineCurada = {
  /**
   * A operação LIGOU a seção para este mês. Falso — ou mês nunca curado — significa que a
   * seção **não existe** no mês, e a tela não desenha uma espinha vazia. É decisão de
   * produto do meuWatt, e ela atravessa: seção nenhuma é melhor que seção vazia.
   */
  exibir: boolean
  marcos: MarcoDaTimeline[]
}

/**
 * O fechamento narrativo do mês, escrito pela equipe.
 *
 * **Somente leitura no portal.** Escrever é trabalho de operação: um campo de edição aqui
 * poria o cliente dentro do caderno da equipe, e o texto que ele lê é justamente o que a
 * equipe assinou. A tela não tem `<textarea>` nem `<input>` nesta seção — e há teste para
 * isso.
 */
export type ConsideracoesDoMes = {
  texto: string
  autor: string | null
  /** Instante da última edição, ISO. */
  em: string | null
}

/** As fórmulas do fechamento, em linguagem de cliente. A tela imprime; não recalcula. */
export type RegraDoFechamento = {
  potencial: string
  perda: string
  horas: string
  causas: string
}

/**
 * O fechamento do mês — a quinta aba do painel.
 *
 * Espelho de `RelatorioMesOut` (`bff/app/api/v1/energia.py`). Os quatro primeiros números
 * são **cópia do painel do mesmo mês**, e estão aqui para o potencial ser conferível na
 * própria resposta: `potencial_kwh` é exatamente `medido_inversores_kwh + perdida_kwh`, e
 * não um parecido. Foi assim que o portal deixou de ter duas respostas para a mesma perda.
 */
export type RelatorioMes = {
  referencia: string
  inicio: string
  fim: string
  rotulo: string
  em_curso: boolean
  /** Dia do mês até onde há medição. Nulo em mês fechado. */
  dia_de_corte: number | null

  medido_inversores_kwh: number | null
  perdida_kwh: number | null
  projeto_proporcional_kwh: number | null
  medido_vs_projeto_pct: number | null

  /** `medido + perdido em paradas` — o que a usina teria entregue se não tivesse parado. */
  potencial_kwh: number | null
  /**
   * `(potencial − projeto) ÷ projeto`, em %.
   *
   * O par mais valioso da aba: com este bom e o `medido_vs_projeto_pct` ruim, o mês foi de
   * PARADAS; com os dois ruins, faltou SOL. Sem os dois lado a lado, um mês fraco tem duas
   * explicações possíveis e nenhuma escrita.
   */
  potencial_vs_projeto_pct: number | null

  /** Quanto da geração do mês se perdeu: `perdida ÷ (base + perdida)`, em %. */
  perda_pct: number | null
  /** `fronteira` ou `inversor` — sobre QUAL medição o percentual acima foi tirado. Sai
   *  declarado porque as duas bases dão números diferentes para a mesma pergunta, e a
   *  tela é obrigada a escrever qual delas falou. */
  perda_base: string | null
  /** De onde veio `perdida_kwh`. É o mesmo número que sustenta a disponibilidade. */
  perda_origem: string | null

  /** Horas paradas somadas por inversor afetado, no recorte diurno. */
  horas_paradas: number | null
  /** O denominador: horas de sol decorridas × nº de inversores. Sem ele, "141 h" soam
   *  como uma semana parada. */
  horas_possiveis: number | null
  inversores_considerados: number | null
  /** Eventos cuja duração o monitoramento não soube calcular — é o motivo de
   *  `horas_paradas` sair em travessão. */
  eventos_sem_duracao: number

  causas: CausaDaParada[]
  eventos: EventoDeParada[]
  /** `alertas` = as paradas foram lidas. Nulo = NÃO foram, e listas vazias significam
   *  "não sei", não "não parou" — a tela precisa dizer coisas diferentes nos dois casos. */
  paradas_origem: string | null
  causas_total_kwh: number | null
  causas_origem: string | null
  /** As duas leituras da mesma perda batem. Falso = a tela DIZ de que janela cada número
   *  saiu, em vez de reescalar uma pela outra (rateio produz número que ninguém mediu). */
  causas_conferem: boolean | null
  /** A frase que declara a limitação do agrupamento. Vem do servidor porque é limitação
   *  da FONTE: se ela mudar, muda lá. */
  eventos_agrupamento: string

  consideracoes: ConsideracoesDoMes | null
  timeline: TimelineCurada

  regra: RegraDoFechamento
  aviso: string | null
}

/* ------------------------------------------------------------------ leituras */

/**
 * As cinco abas do Painel. `unidades` tem recorte próprio (mês ou ano); `relatorio` é
 * travada no MÊS — o fechamento narrativo de um ano não existe, porque as considerações, a
 * timeline e a classificação das paradas são todas escritas mês a mês.
 */
export type Aba = 'dia' | 'mes' | 'ano' | 'unidades' | 'relatorio'

/** O recorte de período que o painel e as unidades aceitam. */
export type RecortePainel = 'mes' | 'ano'

/**
 * A referência normalizada para a chave de cache.
 *
 * No recorte `ano` o BFF só usa o ANO da referência. Sem normalizar, andar de agosto para
 * setembro criaria duas chaves de cache para a MESMA resposta — e, pior, o seletor de mês
 * (que lê `meses_disponiveis` do painel anual) pediria o ano inteiro de novo a cada troca
 * de mês. Com a normalização, a aba Ano e o seletor da aba Mês compartilham uma leitura só.
 */
export function referenciaDoRecorte(recorte: RecortePainel, referencia: string): string {
  return recorte === 'ano' ? `${referencia.slice(0, 4)}-01-01` : referencia
}

export function useUsinaDetalhe(id: number, ativo = true): Leitura<UsinaDetalhe> {
  return useLeitura<UsinaDetalhe>(`plants/${id}`, { ativo })
}

/**
 * O painel do mês ou do ano.
 *
 * Prazo maior que o padrão: lá atrás isto é uma leitura do `generation/range` do meuWatt
 * cruzada com o projeto, a fronteira e as faturas — e, no ano, mais uma conferência de
 * disponibilidade por mês medido. Com o prazo padrão de 30 s, o painel seria a única coisa
 * da tela a falhar por tempo, e justamente na primeira abertura do dia (o upstream cacheia
 * dez minutos; a primeira leitura é a cara).
 */
export function usePainel(
  id: number,
  recorte: RecortePainel,
  referencia: string,
  ativo = true,
): Leitura<Painel> {
  const ref = referenciaDoRecorte(recorte, referencia)
  return useLeitura<Painel>(`energia/usinas/${id}/painel?recorte=${recorte}&referencia=${ref}`, {
    ativo,
    prazoMs: 90_000,
  })
}

/**
 * O fechamento do mês.
 *
 * A referência é normalizada para o **dia 1**: o BFF só usa o mês dela, e sem normalizar
 * andar do dia 3 para o dia 4 do mesmo mês criaria duas chaves de cache para a MESMA
 * resposta. `dia_de_corte` e `em_curso` de lá saem do relógio da usina, não daqui — então
 * normalizar não muda nenhum número.
 *
 * Prazo maior que o padrão pelo mesmo motivo do painel: lá atrás são oito leituras do
 * meuWatt em paralelo (as cinco do painel mais paradas, considerações e timeline).
 */
export function useRelatorioMes(
  id: number,
  referencia: string,
  ativo = true,
): Leitura<RelatorioMes> {
  const ref = `${referencia.slice(0, 7)}-01`
  return useLeitura<RelatorioMes>(`energia/usinas/${id}/relatorio-mes?referencia=${ref}`, {
    ativo,
    prazoMs: 90_000,
  })
}

export function useDia(id: number, dia: string, ativo = true): Leitura<Dia> {
  return useLeitura<Dia>(`energia/usinas/${id}/dia?data=${dia}`, { ativo, prazoMs: 60_000 })
}

export function useUnidades(
  id: number,
  recorte: RecortePainel,
  referencia: string,
  ativo = true,
): Leitura<Unidades> {
  const ref = referenciaDoRecorte(recorte, referencia)
  return useLeitura<Unidades>(
    `energia/usinas/${id}/unidades?recorte=${recorte}&referencia=${ref}`,
    { ativo, prazoMs: 90_000 },
  )
}

/* ------------------------------------------------------------------ ausência */

/**
 * A usina não existe para este cliente — ou não é monitorada.
 *
 * Os dois casos vêm do BFF como 404 com frase própria, e os dois pedem a MESMA tela: um
 * vazio que explica, não um erro vermelho com "Tentar de novo" — tentar de novo não vai
 * fazer a usina aparecer.
 *
 * Quem decide é o STATUS, não a frase. Casar o texto do `detail` pendurava a tela na prosa
 * do BFF: bastava reescrever a mensagem para a tela cair no erro genérico, sem nada quebrar
 * e sem ninguém notar. `Leitura.status` nasceu deste caso.
 */
export function ehUsinaAusente(leitura: Leitura<unknown>): boolean {
  return leitura.dados === null && leitura.status === 404
}
