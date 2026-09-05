/**
 * A régua da tela "Baixar dados": o que cada pacote pede, quanto o arquivo dá, o que a usina
 * não tem e o que o servidor vai recusar — tudo sem uma linha de JSX, para poder ser provado
 * por teste sem montar tela.
 *
 * **A pergunta que este módulo responde não é a do meuWatt.** Lá a tela pergunta "que colunas
 * eu quero no arquivo?"; aqui a pergunta é "quero os números desta usina para trabalhar na
 * minha planilha". Por isso o cliente escolhe um PACOTE nomeado pela finalidade, e a segunda
 * linha dele conta a verdade sobre as colunas. Ninguém acorda querendo `slot:12` agrupado por
 * skid — mas quem quiser abre o Avançado, onde nada foi cortado.
 *
 * **Os três limites do servidor têm TRÊS naturezas, e por isso três tratamentos.** Confundi-
 * los produz ou um muro sem porta, ou trinta e quatro segundos de espera para receber um 400:
 *
 * 1. **Teto de dias por passo** (`limites`) é aritmética nossa e certa → `impedimento` faz a
 *    conta, nomeia a saída e desabilita o botão ANTES da viagem. A opção não é desabilitada
 *    na lista: desabilitar esconderia o porquê.
 * 2. **Retenção** (`retencao`) não é limite do arquivo, é **ausência de dado** → pertence ao
 *    seletor de período (`motivoDeRetencao` cola o motivo em cada dia oferecido), e a saída
 *    existe porque o próprio servidor a garante: a checagem inteira de retenção está dentro
 *    de `if step != "1d"`, então o TOTAL POR DIA não tem prazo.
 * 3. **Orçamento de células** é ESTIMATIVA nossa → `estimativa` calcula e a tela mostra
 *    "≈ N linhas × M colunas", mas **não bloqueia**. No limiar o benefício da dúvida é do
 *    cliente: nunca se recusa um pedido por uma conta minha que o servidor talvez aceitasse.
 *
 * A conta de baldes e colunas é a mesma de `mw-api/src/exports/service.py::validate_request`,
 * de propósito — é a única forma de a estimativa da tela e a decisão do servidor falarem do
 * mesmo arquivo. Ela é aproximada por natureza (daí o `≈` obrigatório na tela) e por isso
 * nunca vira veto.
 */

import type { Opcao } from '@/components/base'
import { dataCurta } from '@/lib/format'
import { daData, paraIso } from '@/lib/periodo'
import type {
  OpcoesDeDados,
  Passo,
  Selecao,
  VarEstacao,
  VarInversor,
  VarSistema,
} from '@/features/dados/api'

/* ------------------------------------------------------------------ passos */

/** Do mais grosso ao mais fino: é a ordem em que se procura o arquivo que cabe. */
export const PASSOS: Passo[] = ['1d', '1h', '15m', '5m', 'native']

export const ROTULO_DO_PASSO: Record<Passo, string> = {
  '1d': 'Um total por dia',
  '1h': 'De hora em hora',
  '15m': 'A cada 15 minutos',
  '5m': 'A cada 5 minutos',
  native: 'Cada leitura, como o equipamento mandou',
}

/** Minutos de cada balde. `native` não tem balde (são os instantes reais) e `1d` é o dia. */
const MINUTOS_DO_PASSO: Partial<Record<Passo, number>> = { '5m': 5, '15m': 15, '1h': 60 }

/**
 * Linhas por série e por dia no passo nativo.
 *
 * É o número que o próprio servidor mediu em produção (~60 s de dia, ~10 min à noite) e usa
 * na conta dele; o SSU sozinho lê de 5 em 5 minutos. Copiá-lo aqui seria criar duas verdades
 * se isto fosse um veto — não é: a estimativa nunca bloqueia, e a palavra final é do servidor.
 */
const LINHAS_NATIVAS_POR_DIA = 800
const LINHAS_NATIVAS_SO_MEDIDOR = 288

/**
 * O teto de dias do passo, **do servidor**. Nulo quando ele não mandou — e aí a tela não
 * inventa número nenhum nem impede coisa alguma.
 */
export function tetoDeDias(limites: Record<string, number>, passo: Passo): number | null {
  const v = limites[passo]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** As cinco opções de detalhe, com o teto do servidor viajando junto da escolha. */
export function opcoesDePasso(limites: Record<string, number>): Opcao[] {
  return PASSOS.map((p) => {
    const teto = tetoDeDias(limites, p)
    return {
      valor: p,
      rotulo: ROTULO_DO_PASSO[p],
      detalhe: teto === null ? undefined : `até ${teto} dias por arquivo`,
    }
  })
}

/**
 * O detalhe que a tela abre marcado — e que **nunca nasce inválido**.
 *
 * Dia → 15 minutos; Mês → de hora em hora; Ano → total por dia. Se o período escolhido não
 * couber no sugerido (um "personalizado" de seis meses, por exemplo), engrossa até caber.
 */
export function passoSugerido(
  recorte: 'dia' | 'mes' | 'ano' | 'livre',
  dias: number,
  limites: Record<string, number>,
): Passo {
  const inicial: Passo =
    recorte === 'dia' ? '15m' : recorte === 'mes' ? '1h' : recorte === 'ano' ? '1d' : '1h'
  const cabe = (p: Passo) => {
    const teto = tetoDeDias(limites, p)
    return teto === null || dias <= teto
  }
  if (cabe(inicial)) return inicial
  // Do mais fino ao mais grosso a partir daqui: o primeiro que couber.
  for (const p of [...PASSOS].reverse()) {
    if (cabe(p)) return p
  }
  return '1d'
}

/* ------------------------------------------------------------------ janela */

export type Janela = {
  /** Dias inclusive, como o servidor conta (`(fim - início).days + 1`). */
  dias: number
  /** Quantas linhas o arquivo terá — a estimativa, nunca uma promessa. */
  baldes: number
  /** Falso quando o fim é anterior ao início (ou o horário final ao inicial no mesmo dia). */
  valida: boolean
}

const MINUTOS_DO_HORARIO = (hhmm: string): number => {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

export function diasEntre(inicio: string, fim: string): number {
  const a = daData(inicio).getTime()
  const b = daData(fim).getTime()
  return Math.round((b - a) / 86_400_000) + 1
}

/**
 * A janela pedida, em dias e em linhas.
 *
 * O horário final é **inclusivo do minuto** (`23:59` cobre o dia inteiro) — é assim que o
 * servidor monta a janela, e uma conta diferente aqui faria a estimativa mentir por um balde.
 */
export function janelaDo(
  inicio: string,
  fim: string,
  horaInicio: string,
  horaFim: string,
  passo: Passo,
  soMedidor: boolean,
): Janela {
  const dias = diasEntre(inicio, fim)
  if (dias < 1) return { dias, baldes: 0, valida: false }
  if (passo === '1d') return { dias, baldes: dias, valida: true }
  if (passo === 'native') {
    const porDia = soMedidor ? LINHAS_NATIVAS_SO_MEDIDOR : LINHAS_NATIVAS_POR_DIA
    return { dias, baldes: dias * porDia, valida: true }
  }
  const minutos =
    (dias - 1) * 1440 + (MINUTOS_DO_HORARIO(horaFim) + 1 - MINUTOS_DO_HORARIO(horaInicio))
  if (minutos <= 0) return { dias, baldes: 0, valida: false }
  const passoMin = MINUTOS_DO_PASSO[passo] ?? 1
  return { dias, baldes: Math.max(1, Math.floor(minutos / passoMin)), valida: true }
}

/* ------------------------------------------------------------------ pacotes */

export type IdDePacote = 'geracao' | 'geracao_clima' | 'medidor' | 'desempenho' | 'tudo'
/** O pacote deixa de ter nome quando o cliente mexe no Avançado — e a tela diz isso. */
export const PERSONALIZADO = 'personalizado'

/** As colunas de clima que se pode exportar, sem o relé (que é distinção de operador). */
export const CLIMA: VarEstacao[] = ['poa', 'ghi', 'temp_modulo', 'temp_ambiente', 'vento']

export const ROTULO_DA_ESTACAO: Record<VarEstacao, string> = {
  poa: 'Irradiação no plano dos módulos',
  ghi: 'Irradiação no plano horizontal',
  temp_modulo: 'Temperatura do módulo',
  temp_ambiente: 'Temperatura ambiente',
  vento: 'Vento',
  temp_ambiente_rele: 'Temperatura ambiente (pelo relé)',
}

export const ROTULO_DO_INVERSOR: Record<VarInversor, string> = {
  geracao: 'Geração',
  potencia: 'Potência',
  status: 'Situação do inversor',
  paradas: 'Paradas',
}

export const ROTULO_DO_SISTEMA: Record<VarSistema, string> = {
  pr: 'PR — quanto rendeu do que o sol ofereceu',
  produtividade: 'Produtividade',
}

/** As colunas de clima que ESTA estação de fato coleta. */
export function climaDisponivel(o: OpcoesDeDados): VarEstacao[] {
  if (!o.estacao.disponivel) return []
  return CLIMA.filter((c) => o.estacao.colunas[c] === true)
}

export const PACOTES: { id: IdDePacote; rotulo: string; detalhe: string }[] = [
  {
    id: 'geracao',
    rotulo: 'Geração da usina',
    detalhe: 'uma coluna por inversor, mais o total',
  },
  {
    id: 'geracao_clima',
    rotulo: 'Geração + clima',
    detalhe: 'irradiação e temperatura ao lado da geração',
  },
  {
    id: 'medidor',
    rotulo: 'Energia no medidor',
    detalhe: 'a leitura que fecha o faturamento',
  },
  {
    id: 'desempenho',
    rotulo: 'Desempenho (PR e produtividade)',
    detalhe: 'quanto a usina rendeu do que o sol ofereceu',
  },
  {
    id: 'tudo',
    rotulo: 'Tudo o que esta usina mede',
    detalhe: 'arquivo grande — confira a estimativa',
  },
]

/**
 * Por que este pacote não serve para esta usina — ou `null` quando serve.
 *
 * A linha **continua na lista**, com o motivo colado: sumir com ela faria o cliente concluir
 * que o portal não oferece, quando o fato é sobre a usina dele. E a terceira frase é uma
 * ausência DERIVADA — dizer a cadeia inteira é a diferença entre "o portal está quebrado" e
 * "eu sei o que teria de instalar para ter isso".
 */
export function motivoDoPacote(id: IdDePacote, o: OpcoesDeDados): string | null {
  const semInversor = o.skids.every((s) => s.series.length === 0)
  if ((id === 'geracao' || id === 'geracao_clima') && semInversor) {
    return 'esta usina não tem inversores cadastrados no monitoramento'
  }
  if (id === 'geracao_clima' && climaDisponivel(o).length === 0) {
    return 'esta usina não tem estação solarimétrica com dados'
  }
  if (id === 'medidor' && o.leitores.length === 0) {
    return 'esta usina não tem medidor de fronteira'
  }
  if (id === 'desempenho' && !o.sistema.pr && !o.sistema.produtividade) {
    return 'sem estação não há irradiação, e sem irradiação não se calcula PR'
  }
  if (id === 'tudo' && vazia(montarPacote('tudo', o))) {
    return 'não há nada exportável cadastrado nesta usina'
  }
  return null
}

/** O que o pacote pediria e a estação não tem — dito antes, não descoberto no arquivo. */
export function faltamNoPacote(id: IdDePacote, o: OpcoesDeDados): string | null {
  if (id !== 'geracao_clima' && id !== 'tudo') return null
  const tem = climaDisponivel(o)
  if (tem.length === 0) return null
  const faltam = CLIMA.filter((c) => !tem.includes(c))
  if (faltam.length === 0) return null
  const nomes = faltam.map((c) => ROTULO_DA_ESTACAO[c].toLowerCase())
  return `esta estação não mede ${lista(nomes)}`
}

function lista(itens: string[]): string {
  if (itens.length === 1) return itens[0]
  return `${itens.slice(0, -1).join(', ')} nem ${itens[itens.length - 1]}`
}

export function vazia(s: Selecao): boolean {
  return !s.inversores && !s.estacao && !s.fronteira && !s.sistema
}

/** Só o medidor foi pedido — muda a cadência do passo nativo, como no servidor. */
export function soMedidor(s: Selecao): boolean {
  return !!s.fronteira && !s.inversores && !s.estacao && !s.sistema
}

/**
 * O pacote traduzido em seleção — a mesma que o Avançado edita.
 *
 * `series: null` de propósito: "não mexi". O inversor que entrar em operação no meio do
 * período aparece sozinho no arquivo, o que uma lista explícita impediria.
 */
export function montarPacote(id: IdDePacote, o: OpcoesDeDados): Selecao {
  const vazio: Selecao = { inversores: null, estacao: null, fronteira: null, sistema: null }
  const temInversor = o.skids.some((s) => s.series.length > 0)
  const inversores = temInversor
    ? { variaveis: ['geracao'] as VarInversor[], agrupamento: 'lista' as const, series: null }
    : null
  const clima = climaDisponivel(o)

  if (id === 'geracao') return { ...vazio, inversores }
  if (id === 'geracao_clima') {
    return { ...vazio, inversores, estacao: clima.length ? { variaveis: clima } : null }
  }
  if (id === 'medidor') {
    return o.leitores.length
      ? { ...vazio, fronteira: { variaveis: ['energia'], agrupamento: 'leitor' } }
      : vazio
  }
  if (id === 'desempenho') {
    const vars: VarSistema[] = []
    if (o.sistema.pr) vars.push('pr')
    if (o.sistema.produtividade) vars.push('produtividade')
    return {
      ...vazio,
      sistema: vars.length ? { variaveis: vars, agrupamento: 'usina' } : null,
      // A POA vai junto porque é o denominador da PR: sem ela o cliente teria o índice e
      // nenhuma forma de conferi-lo.
      estacao: o.estacao.colunas.poa === true ? { variaveis: ['poa'] } : null,
    }
  }
  const sistema: VarSistema[] = []
  if (o.sistema.pr) sistema.push('pr')
  if (o.sistema.produtividade) sistema.push('produtividade')
  return {
    inversores,
    estacao: clima.length ? { variaveis: clima } : null,
    fronteira: o.leitores.length ? { variaveis: ['energia'], agrupamento: 'leitor' } : null,
    sistema: sistema.length ? { variaveis: sistema, agrupamento: 'usina' } : null,
  }
}

/* ------------------------------------------------------------------ estimativa */

export type Estimativa = { linhas: number; colunas: number; celulas: number }

/**
 * Quantas linhas e quantas colunas o arquivo teria.
 *
 * A conta das colunas é a do servidor, campo a campo (`validate_request`), porque a tela e ele
 * precisam estar falando do mesmo arquivo. "Células" é orçamento interno e não aparece na
 * tela: o cliente vê o que vai encontrar quando abrir no Excel.
 */
export function estimativa(s: Selecao, o: OpcoesDeDados, janela: Janela): Estimativa {
  const nSeries = o.skids.reduce((t, k) => t + k.series.length, 0)
  const nSkids = o.skids.length
  let colunas = 0

  if (s.inversores) {
    let base = s.inversores.agrupamento === 'lista' ? nSeries : nSkids
    if (s.inversores.series && s.inversores.series.length > 0) {
      base = Math.min(base, s.inversores.series.length)
    }
    const semParadas = s.inversores.variaveis.filter((v) => v !== 'paradas').length
    colunas += (base + 1) * semParadas
    if (s.inversores.variaveis.includes('paradas')) colunas += base + 1
  }
  if (s.estacao) colunas += 2 * s.estacao.variaveis.length + 1
  if (s.fronteira) colunas += o.leitores.length + 1
  if (s.sistema) colunas += (s.sistema.agrupamento === 'skid' ? nSkids : 1) * 5

  const efetivas = Math.max(colunas, 1)
  return { linhas: janela.baldes, colunas, celulas: janela.baldes * efetivas }
}

/** O orçamento do servidor, quando ele o declarou. */
export function passaDoOrcamento(e: Estimativa, limites: Record<string, number>): boolean {
  const teto = limites.max_celulas
  return typeof teto === 'number' && Number.isFinite(teto) && e.celulas > teto
}

/* ------------------------------------------------------------------ retenção */

/**
 * Por que este dia só tem total diário — ou `null` quando o acervo o alcança inteiro.
 *
 * Vai colado em cada dia oferecido no seletor: a ausência é do ACERVO, não do arquivo, e o
 * cliente precisa saber disso enquanto escolhe, não depois de esperar meio minuto.
 */
export function motivoDeRetencao(dia: string, r: Retencao): string | null {
  if (r.snapshots_desde && dia < r.snapshots_desde) {
    return 'a leitura minuto a minuto não existe mais — só o total por dia'
  }
  return null
}

type Retencao = OpcoesDeDados['retencao']

/* ------------------------------------------------------------------ impedimento */

/** O que impede este pedido de sair — com a conta feita e a saída nomeada. */
export type Impedimento = { texto: string }

/**
 * O que a tela sabe, com certeza, que o servidor vai recusar.
 *
 * Só entram regras que são **aritmética nossa e certa**: contagem de dias contra o teto, a
 * retenção do acervo e as duas incompatibilidades de passo que o servidor declara. O
 * orçamento de células fica de fora de propósito — é estimativa, e quem estima não veta.
 *
 * Toda frase nomeia a saída. Limite sem saída nomeada é só um muro.
 */
export function impedimento(
  s: Selecao,
  passo: Passo,
  janela: Janela,
  inicio: string,
  o: OpcoesDeDados,
): Impedimento | null {
  if (vazia(s)) {
    return { texto: 'Nada foi escolhido para o arquivo. Escolha o que você quer levar.' }
  }
  if (s.inversores && s.inversores.series && s.inversores.series.length === 0) {
    return {
      texto:
        'Nenhum inversor está marcado. Escolha ao menos um, ou volte para "todos" em ' +
        '"Escolher coluna por coluna".',
    }
  }
  if (!janela.valida) {
    return { texto: 'O período termina antes de começar. Confira as datas e os horários.' }
  }

  const teto = tetoDeDias(o.limites, passo)
  if (teto !== null && janela.dias > teto) {
    const alternativa = PASSOS.slice()
      .reverse()
      .find((p) => {
        const t = tetoDeDias(o.limites, p)
        return t !== null && janela.dias <= t
      })
    const saida = alternativa
      ? `Escolha "${ROTULO_DO_PASSO[alternativa].toLowerCase()}" (aceita ${tetoDeDias(o.limites, alternativa)}) ou um período menor.`
      : 'Escolha um período menor.'
    return {
      texto: `O período tem ${janela.dias} dias. "${ROTULO_DO_PASSO[passo]}" aceita ${teto}. ${saida}`,
    }
  }

  if (passo !== '1d') {
    const precisaFino = !!s.inversores || !!s.estacao || !!s.sistema
    const { snapshots_desde: snapshots, ssu_desde: ssu } = o.retencao
    if (precisaFino && snapshots && inicio < snapshots) {
      return {
        texto:
          `A leitura fina de inversores e estação só existe desde ${dataCurta(snapshots)}. ` +
          'Escolha "um total por dia" — esse não tem prazo — ou um período mais recente.',
      }
    }
    if (s.fronteira && ssu && inicio < ssu) {
      return {
        texto:
          `A leitura do medidor só existe desde ${dataCurta(ssu)}. ` +
          'Escolha "um total por dia" ou um período mais recente.',
      }
    }
  }

  if (s.inversores?.variaveis.includes('status') && passo !== 'native') {
    return {
      texto:
        `"${ROTULO_DO_INVERSOR.status}" só sai em "${ROTULO_DO_PASSO.native.toLowerCase()}" ` +
        '(é um texto por leitura). Troque o detalhe ou tire essa coluna no Avançado.',
    }
  }
  if (s.sistema && passo === 'native') {
    return {
      texto:
        'PR e produtividade precisam de um intervalo fechado para serem calculados. ' +
        'Escolha "a cada 5 minutos" ou mais grosso.',
    }
  }
  return null
}

/* ------------------------------------------------------------------ recusa */

/**
 * A recusa do servidor em português — **traduzida do `motivo`, nunca ecoada do `message`**.
 *
 * O texto do meuWatt foi escrito para o operador de lá: fala em balde, snapshots e SSU. Quem
 * escreve para o cliente é o portal.
 *
 * `espera` separa as duas naturezas: espera é `Aviso` COM "Tentar de novo" (repetir daqui a
 * pouco funciona); regra violada é `Aviso` SEM botão — oferecer repetição num `muito_grande`
 * seria crueldade, porque repetir dá exatamente o mesmo resultado. Motivo desconhecido devolve
 * `null`, e a tela cai no erro de transporte, que tem o botão.
 */
export type Recusa = { texto: string; espera: boolean }

const RECUSAS: Record<string, Recusa> = {
  periodo_invalido: {
    texto:
      'O período pedido não é válido: ou termina antes de começar, ou começa no futuro. ' +
      'Escolha outro período.',
    espera: false,
  },
  passo_excede_limite: {
    texto:
      'Este período é longo demais para o detalhe escolhido. Escolha um detalhe mais grosso ' +
      '(de hora em hora, ou um total por dia) ou um período menor.',
    espera: false,
  },
  fora_da_retencao: {
    texto:
      'Neste período a leitura fina já não existe. Escolha "um total por dia" — esse não tem ' +
      'prazo — ou um período mais recente.',
    espera: false,
  },
  bloco_indisponivel: {
    texto:
      'Alguma coluna desta seleção esta usina não mede. Abra "Escolher coluna por coluna" e ' +
      'tire o que não estiver disponível.',
    espera: false,
  },
  sem_blocos: {
    texto: 'Nada foi escolhido para o arquivo. Escolha o que você quer levar.',
    espera: false,
  },
  muito_grande: {
    texto:
      'Este pedido daria um arquivo maior do que o monitoramento monta. Diminua o período, ' +
      'escolha menos detalhe, ou baixe menos inversores.',
    espera: false,
  },
  muitos_pedidos: {
    texto:
      'O monitoramento está atendendo muitos pedidos agora. Espere um minuto e peça de novo.',
    espera: true,
  },
}

export function traduzirMotivo(motivo: string | null): Recusa | null {
  if (!motivo) return null
  return RECUSAS[motivo] ?? null
}

/* ------------------------------------------------------------------ dias oferecidos */

/**
 * Os dias que o seletor "Personalizado" oferece, do mais recente para trás, com o motivo da
 * retenção colado em cada um.
 *
 * O fundo da lista é o do acervo do medidor (`ssu_desde`), que é o mais antigo que o
 * monitoramento guarda; sem ele, dois anos. Nada é cortado por gosto: abaixo daquela data não
 * há leitura nenhuma para pedir.
 */
export function diasOferecidos(hoje: string, r: Retencao, maximo = 760): Opcao[] {
  const fundo = r.ssu_desde ?? null
  const saida: Opcao[] = []
  const d = daData(hoje)
  for (let i = 0; i < maximo; i += 1) {
    const iso = paraIso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - i))
    if (fundo && iso < fundo) break
    saida.push({
      valor: iso,
      rotulo: dataCurta(iso),
      detalhe: motivoDeRetencao(iso, r) ?? undefined,
    })
  }
  return saida
}
