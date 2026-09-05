/**
 * O que o Painel de energia lê do BFF — e nada além disso.
 *
 * Quatro leituras, todas do mesmo assunto ("quanto esta usina gerou e era para gerar"):
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
}

export type Totais = {
  medido_kwh: number | null
  projeto_kwh: number | null
  /** O projeto rateado pelos dias decorridos — comparar mês inteiro com meio mês acusaria
   *  de doente uma usina em dia. */
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
  /** A irradiação de PROJETO do período, na mesma janela do medido — nos dois planos. */
  hpoa_projeto: number | null
  ghi_projeto: number | null
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
  projeto_kwh: number | null
  projeto_proporcional_kwh: number | null
  previsto_kwh: number | null
  /** `pvsyst_diario` ou `manual_corrigido` — de onde veio o previsto. */
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
  tem_estacao: boolean
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

/* ------------------------------------------------------------------ leituras */

/** As quatro abas do Painel. `unidades` tem recorte próprio (mês ou ano). */
export type Aba = 'dia' | 'mes' | 'ano' | 'unidades'

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
