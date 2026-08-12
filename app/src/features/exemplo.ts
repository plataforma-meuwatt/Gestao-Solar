/**
 * Dados de exemplo, copiados do design da rodada 1.
 *
 * ISTO É ANDAIME. Existe para as telas renderizarem antes de o BFF ter endpoints, e sai
 * inteiro quando a Fase 1 ligar `GET /api/v1/home` e companhia. Nenhuma tela deve
 * calcular nada a partir daqui além do que a API vai devolver pronta — se uma conta
 * aparecer aqui, ela está no lugar errado (o BFF é quem agrega).
 *
 * Os números são os do designer, escolhidos para serem coerentes entre si: a parada do
 * INV-03 explica a faixa de atenção do Início, a queda no gráfico do dia e a posição
 * dele na comparação com os vizinhos.
 */

import type { Tom } from '@/theme/tokens'

export const usuario = { iniciais: 'RM', primeiroNome: 'Renan' }

/* ------------------------------------------------------------------ Início */

export const inicio = {
  atualizadoAs: '14:32',
  potenciaAgoraKw: '4.280',
  pctCapacidade: 69,
  energiaHojeMwh: '21,4',
  qtdUsinas: 3,

  atencao: {
    tom: 'parado' as Tom,
    titulo: '2 inversores parados em Porto Ferreira',
    detalhe: 'sem geração há 3 h 10 min',
  },

  meuWatt: {
    geracaoMesMwh: '812,6',
    metaMwh: '940,0',
    pctMeta: 86,
    diasRestantes: 9,
    pr: '82,4%',
  },

  meuPlano: {
    concluidos: 3,
    total: 4,
    // Conformidade por mês, como o meuPlano já devolve. null = mês futuro / não se aplica.
    meses: [
      'ok', 'ok', 'ok', 'multiplos', 'ok', 'ok', 'parado', 'tempoRuim',
      null, null, null, null,
    ] as (Tom | null)[],
  },

  financeiro: {
    proximoVencimento: '15/08',
    valor: 'R$ 4.180,00',
    situacao: 'Em dia',
  },
}

/* ----------------------------------------------------------- Notificações */

export type Notificacao = {
  id: number
  grupo: 'acao' | 'sistema'
  tom: Tom
  titulo: string
  resumo: string
  quando: string
  lida: boolean
}

export const notificacoes: Notificacao[] = [
  {
    id: 1,
    grupo: 'acao',
    tom: 'parado',
    titulo: 'Inversor parado',
    resumo: 'INV-03 · Porto Ferreira, sem geração desde 11:20',
    quando: 'há 2 h',
    lida: false,
  },
  {
    id: 2,
    grupo: 'acao',
    tom: 'multiplos',
    titulo: 'Serviço vencido',
    resumo: 'Termografia de agosto — Araraquara',
    quando: 'há 4 h',
    lida: false,
  },
  {
    id: 3,
    grupo: 'sistema',
    tom: 'ok',
    titulo: 'Serviço concluído',
    resumo: 'Limpeza de módulos — Ribeirão Bonito',
    quando: 'há 5 h',
    lida: true,
  },
  {
    id: 4,
    grupo: 'acao',
    tom: 'alerta',
    titulo: 'Fatura disponível',
    resumo: 'Mensalidade de agosto, vence em 15/08',
    quando: 'ontem',
    lida: true,
  },
  {
    id: 5,
    grupo: 'sistema',
    tom: 'tempoRuim',
    titulo: 'Perda por nuvens',
    resumo: 'Geração 22% abaixo do previsto em Porto Ferreira',
    quando: 'ontem',
    lida: true,
  },
  {
    id: 6,
    grupo: 'sistema',
    tom: 'semDados',
    titulo: 'Sem dados do datalogger',
    resumo: 'Araraquara sem comunicação entre 03:10 e 05:40',
    quando: 'há 2 d',
    lida: true,
  },
]

/* ----------------------------------------------------------------- Usinas */

export type Usina = {
  id: string
  nome: string
  cidade: string
  uf: string
  tom: Tom
  status: string
  potenciaKw: string | null
  capacidadeKwp: string
  pct: number
  energiaHoje: string | null
  rodape?: string
}

export const usinas: Usina[] = [
  {
    id: 'porto-ferreira',
    nome: 'Porto Ferreira',
    cidade: 'Porto Ferreira',
    uf: 'SP',
    tom: 'parado',
    status: '2 parados',
    potenciaKw: '1.480',
    capacidadeKwp: '2.800',
    pct: 53,
    energiaHoje: '8,6',
  },
  {
    id: 'ribeirao-bonito',
    nome: 'Ribeirão Bonito',
    cidade: 'Ribeirão Bonito',
    uf: 'SP',
    tom: 'ok',
    status: 'Gerando',
    potenciaKw: '1.910',
    capacidadeKwp: '2.200',
    pct: 87,
    energiaHoje: '9,4',
  },
  {
    id: 'araraquara',
    nome: 'Araraquara',
    cidade: 'Araraquara',
    uf: 'SP',
    tom: 'semDados',
    status: 'Sem dados',
    potenciaKw: null,
    capacidadeKwp: '1.200',
    pct: 0,
    energiaHoje: null,
    rodape: 'sem comunicação desde 03:10',
  },
]

export const totalUsinas = { quantidade: 3, capacidade: '6,2' }

/* --------------------------------------------------- Usina — Porto Ferreira */

export const usinaDetalhe = {
  id: 'porto-ferreira',
  nome: 'Porto Ferreira',
  capacidadeMwp: '2,8',
  inversores: 12,

  dia: {
    energiaMwh: '8,6',
    previstoMwh: '11,2',
    picoKw: '2.240',
    picoHora: '11:00',
    pr: '76,8%',
    // Potência hora a hora, das 6 h às 19 h.
    curva: [0.1, 0.5, 1.2, 2.0, 2.6, 3.1, 3.3, 2.4, 2.2, 1.9, 1.2, 0.6, 0.2, 0.0],
    indicePico: 6,
  },

  mes: {
    rotulo: 'Agosto, dia a dia',
    totalMwh: '642,3',
    // 31 dias; zero = dia ainda não ocorrido.
    dias: [
      24.1, 26.8, 27.4, 19.2, 12.6, 25.9, 28.1, 27.7, 26.4, 8.4, 14.9, 26.6, 27.2, 28.4,
      27.9, 26.1, 25.4, 27.6, 28.8, 21.3, 17.5, 26.9, 27.1, 26.3, 28.2, 27.4, 26.8, 25.9,
      21.4, 0, 0,
    ],
    limiarTempoRuim: 16,
  },

  manutencao: '3 de 4 no mês',
}

/* --------------------------------------------------------- Equipamentos */

export type Equipamento = {
  id: string
  nome: string
  modelo: string
  tom: Tom
  status: string
  potencia: string
  pct: number
}

export const equipamentos: Equipamento[] = [
  { id: 'inv-01', nome: 'INV-01', modelo: 'SUN2000-100KTL', tom: 'ok', status: 'Gerando', potencia: '92,4', pct: 92 },
  { id: 'inv-02', nome: 'INV-02', modelo: 'SUN2000-100KTL', tom: 'ok', status: 'Gerando', potencia: '88,1', pct: 88 },
  { id: 'inv-03', nome: 'INV-03', modelo: 'SUN2000-100KTL', tom: 'parado', status: 'Parado há 3 h 10', potencia: '0,0', pct: 0 },
  { id: 'inv-04', nome: 'INV-04', modelo: 'SUN2000-100KTL', tom: 'parado', status: 'Parado há 3 h 10', potencia: '0,0', pct: 0 },
  { id: 'inv-05', nome: 'INV-05', modelo: 'SUN2000-100KTL', tom: 'alerta', status: 'Alerta', potencia: '61,7', pct: 62 },
  { id: 'inv-06', nome: 'INV-06', modelo: 'SUN2000-100KTL', tom: 'tempoRuim', status: 'Tempo ruim', potencia: '44,9', pct: 45 },
  { id: 'inv-07', nome: 'INV-07', modelo: 'SUN2000-100KTL', tom: 'ok', status: 'Gerando', potencia: '90,2', pct: 90 },
  { id: 'inv-08', nome: 'INV-08', modelo: 'SUN2000-100KTL', tom: 'semDados', status: 'Sem dados', potencia: '—', pct: 0 },
]

export const resumoEquipamentos = { parados: 2, alerta: 1, semDados: 1 }

/* ------------------------------------------------------------ Documentos */

export type PecaPdf = { nome: string; tamanho: string; offline: boolean }

/**
 * Um fechamento mensal são DUAS peças — Relatório de Geração e Anexo de Paradas — e elas
 * andam juntas. É assim que o meuWatt publica hoje (`kind` = geracao | paradas), e por
 * isso o card agrupa em vez de listar dois itens soltos.
 */
export type Fechamento = {
  id: string
  competencia: string
  usina: string
  emitidoEm: string
  pecas: PecaPdf[]
}

export const fechamentos: Fechamento[] = [
  {
    id: 'pf-2026-07',
    competencia: 'Julho de 2026',
    usina: 'Porto Ferreira',
    emitidoEm: '01/08/2026',
    pecas: [
      { nome: 'Relatório de Geração', tamanho: '2,4 MB', offline: true },
      { nome: 'Anexo de Paradas', tamanho: '640 kB', offline: true },
    ],
  },
  {
    id: 'rb-2026-07',
    competencia: 'Julho de 2026',
    usina: 'Ribeirão Bonito',
    emitidoEm: '01/08/2026',
    pecas: [
      { nome: 'Relatório de Geração', tamanho: '2,1 MB', offline: false },
      { nome: 'Anexo de Paradas', tamanho: '512 kB', offline: false },
    ],
  },
  {
    id: 'pf-2026-06',
    competencia: 'Junho de 2026',
    usina: 'Porto Ferreira',
    emitidoEm: '01/07/2026',
    pecas: [
      { nome: 'Relatório de Geração', tamanho: '2,3 MB', offline: false },
      { nome: 'Anexo de Paradas', tamanho: '588 kB', offline: false },
    ],
  },
]

export const tiposRelatorio = ['Diário', 'Mensal', 'Anual', 'UCs']

/* ------------------------------------------------------------- Financeiro */

export type SituacaoFatura = 'pago' | 'aVencer' | 'emAberto' | 'vencido'

export const situacaoRotulo: Record<SituacaoFatura, string> = {
  pago: 'Pago',
  aVencer: 'A vencer',
  emAberto: 'Em aberto',
  vencido: 'Vencido',
}

export const situacaoTom: Record<SituacaoFatura, Tom> = {
  pago: 'ok',
  aVencer: 'alerta',
  emAberto: 'semDados',
  vencido: 'parado',
}

/**
 * O dono assina dois produtos e recebe uma cobrança só. A soma dos dois é o número que o
 * card do Início anuncia — se um dia divergir, é bug de agregação no BFF, não de tela.
 */
export const assinaturas = [
  {
    id: 'meuwatt',
    produto: 'meuWatt',
    descricao: 'monitoramento',
    valor: 'R$ 2.480,00',
    diaVencimento: 15,
    situacao: 'aVencer' as SituacaoFatura,
  },
  {
    id: 'meuplano',
    produto: 'meuPlano',
    descricao: 'manutenção',
    valor: 'R$ 1.700,00',
    diaVencimento: 15,
    situacao: 'aVencer' as SituacaoFatura,
  },
]

export const financeiro = {
  competenciaAtual: 'agosto de 2026',
  total: 'R$ 4.180,00',
  vencimento: '15/08',

  /** Quando há atraso, o card do topo troca de cor e passa a falar da parcela vencida. */
  pendencia: {
    titulo: '1 mensalidade vencida',
    valor: 'R$ 2.480,00',
    detalhe: 'meuWatt · abril de 2026 · vencida há',
    diasAtraso: '118 dias',
    orientacao: 'Fale com a administração para regularizar. O monitoramento segue ativo.',
  },

  rodape:
    'A baixa das mensalidades é feita pela administração. Este app informa a situação, não recebe pagamento.',
}

export type LinhaHistorico = {
  id: string
  mes: string
  produto: string
  valor: string
  situacao: SituacaoFatura
}

export const historicoFaturas: LinhaHistorico[] = [
  { id: 'h1', mes: 'Agosto de 2026', produto: 'meuWatt + meuPlano', valor: 'R$ 4.180,00', situacao: 'aVencer' },
  { id: 'h2', mes: 'Julho de 2026', produto: 'meuWatt + meuPlano', valor: 'R$ 4.180,00', situacao: 'pago' },
  { id: 'h3', mes: 'Junho de 2026', produto: 'meuWatt + meuPlano', valor: 'R$ 4.180,00', situacao: 'pago' },
  { id: 'h4', mes: 'Maio de 2026', produto: 'meuPlano', valor: 'R$ 1.700,00', situacao: 'emAberto' },
  { id: 'h5', mes: 'Abril de 2026', produto: 'meuWatt', valor: 'R$ 2.480,00', situacao: 'vencido' },
]

export const faturaDetalhe = {
  produto: 'meuWatt',
  situacao: 'pago' as SituacaoFatura,
  competencia: 'competência julho de 2026',
  valor: 'R$ 2.480,00',
  linhas: [
    { rotulo: 'Vencimento', valor: '15/07/2026', mono: true },
    { rotulo: 'Pago em', valor: '14/07/2026', mono: true },
    { rotulo: 'Forma', valor: 'Boleto', mono: false },
    { rotulo: 'Usinas cobertas', valor: '3', mono: false },
  ],
  observacao: 'Observação: valor proporcional à capacidade instalada contratada em março.',
  comprovante: { nome: 'Comprovante de pagamento', tamanho: '184 kB', offline: false },
}

/* ------------------------------------------------------ Inversor INV-03 */

export const inversor = {
  id: 'inv-03',
  nome: 'INV-03',
  usina: 'Porto Ferreira',
  modelo: 'SUN2000-100KTL',
  paradoHa: '3 h 10 min',
  ultimaGeracao: '11:20',

  potenciaAgora: '0,0',
  nominalKw: '100,0',
  energiaHoje: '128,4',
  energiaMes: '9.412,7',
  prMes: '79,1%',

  entradas: [
    { nome: 'MPPT 1', tensao: '712,4', corrente: '18,2', tom: 'ok' as Tom },
    { nome: 'MPPT 2', tensao: '709,8', corrente: '18,0', tom: 'ok' as Tom },
    { nome: 'MPPT 3', tensao: '0,0', corrente: '0,0', tom: 'parado' as Tom },
    { nome: 'MPPT 4', tensao: '0,0', corrente: '0,0', tom: 'parado' as Tom },
    { nome: 'MPPT 5', tensao: '0,0', corrente: '0,0', tom: 'parado' as Tom },
    { nome: 'MPPT 6', tensao: '0,0', corrente: '0,0', tom: 'parado' as Tom },
  ],

  alarmes: [
    { id: 1, tom: 'parado' as Tom, titulo: 'Falha de isolamento na entrada 3', quando: 'hoje, 11:20' },
    { id: 2, tom: 'multiplos' as Tom, titulo: 'Sobretemperatura do dissipador', quando: 'hoje, 11:18' },
    { id: 3, tom: 'semDados' as Tom, titulo: 'Comunicação restabelecida', quando: 'ontem, 06:02' },
  ],

  identificacao: [
    { rotulo: 'Fabricante / modelo', valor: 'SUN2000-100KTL', mono: false },
    { rotulo: 'Número de série', valor: 'HV2143078295', mono: true },
    { rotulo: 'Potência nominal', valor: '100,0 kW', mono: true },
    { rotulo: 'Em operação desde', valor: '14/03/2023', mono: true },
    { rotulo: 'Última comunicação', valor: 'hoje, 11:20', mono: true },
  ],

  geracaoDia: {
    energiaKwh: '128,4',
    esperadoKwh: '412,0',
    // Potência hora a hora; zera no índice 7, quando parou.
    curva: [0, 6, 24, 48, 70, 88, 92, 0, 0, 0, 0, 0, 0, 0],
    indiceCorte: 6,
    rotuloCorte: 'parou 11:20',
    picoKw: '92,4',
    horasGerando: '5 h 50',
    perdaEstimada: '283,6',
  },

  vizinhos: [
    { nome: 'INV-01', pct: 96, valor: '398,2', destacado: false },
    { nome: 'INV-02', pct: 92, valor: '381,7', destacado: false },
    { nome: 'INV-03', pct: 31, valor: '128,4', destacado: true },
    { nome: 'INV-04', pct: 29, valor: '121,9', destacado: true },
  ],
}
