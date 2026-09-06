/**
 * A régua da tela "Baixar dados": as catorze variáveis que o monitoramento exporta, os
 * agrupamentos de cada bloco, quanto o arquivo dá, o que ESTA usina não tem e o que o
 * servidor vai recusar — tudo sem uma linha de JSX, para poder ser provado por teste sem
 * montar tela.
 *
 * **A régua é a mesma do meuWatt, e isso é verificável, não retórico.** São 4 linhas de
 * inversor + 7 de estação + 1 de fronteira + 2 de sistema = **14**, e os dois agrupamentos
 * de cada um dos três blocos que têm agrupamento. `pacotes.test.ts` conta. Item que cortar
 * uma linha "para simplificar" reprova um teste, e não depende de alguém reparar no diff.
 * O que muda em relação ao meuWatt é só o vocabulário visual (chip é proibido no portal, então
 * a régua devolve `Opcao[]` para lista suspensa e segmentado) — nunca o conjunto do que se
 * pode pedir.
 *
 * **Nenhuma linha some; a que não serve fica desabilitada DIZENDO por quê.** Sumir com a
 * linha faz o cliente concluir que o portal não oferece, quando o fato é sobre a usina dele —
 * ou sobre o produto, que é o caso da umidade (o monitoramento devolve `umidade: false`
 * fixo, com o comentário "não existe coluna em nenhuma tabela"). A garantia é do tipo
 * `Opcao`: `desabilitada: true` **exige** `detalhe`, então o `tsc` pega a parede sem porta.
 *
 * **Os PACOTES são atalho, não modo.** Eles PREENCHEM os quatro blocos, que estão à vista, e
 * somem. Não existe estado "personalizado": ele só era necessário quando a tela precisava
 * administrar a mentira de continuar chamando a seleção de "Geração da usina" depois que o
 * cliente a editou. Com os blocos na tela, a verdade está desenhada e o estado morre.
 *
 * **Os três limites do servidor têm TRÊS naturezas, e por isso três tratamentos.** Confundi-
 * los produz ou um muro sem porta, ou trinta e cinco segundos de espera para receber um 400:
 *
 * 1. **Teto de dias por passo** (`limites`) é aritmética nossa e certa → `impedimento` faz a
 *    conta, nomeia a saída e desabilita o botão ANTES da viagem. A opção de passo **não** é
 *    desabilitada na lista: desabilitar esconderia o porquê, e a saída para um período de
 *    120 dias costuma ser justamente trocar de passo. E quando a tela ajusta o passo sozinha,
 *    `ajustarPasso` devolve a frase que ANUNCIA o ajuste — mudança calada é a que se descobre
 *    no arquivo.
 * 2. **Retenção** (`retencao`) não é limite do arquivo, é **ausência de dado** → mora no
 *    período (`diasOferecidos` cola o motivo em cada dia) e numa linha sob o passo
 *    (`linhaDeRetencao`), e as DUAS trocam conforme a seleção: só o medidor alcança 24 meses,
 *    qualquer outra coisa para em 6. Uma frase só seria falsa metade do tempo. A saída existe
 *    porque o próprio servidor a garante: a checagem inteira de retenção está dentro de
 *    `if step != "1d"`, então o TOTAL POR DIA não tem prazo.
 * 3. **Orçamento de células** é ESTIMATIVA nossa → `avisoDeOrcamento` calcula e a tela mostra,
 *    mas **nunca bloqueia**, e a frase termina em "se quiser tentar assim mesmo, pode pedir".
 *    No limiar o benefício da dúvida é do cliente: não se recusa um pedido por uma conta minha
 *    que o servidor talvez aceitasse.
 *
 * A conta de baldes é a mesma de `mw-api/src/exports/service.py::validate_request`, de
 * propósito, e a de CÉLULAS também (`celulasDoOrcamento`) — quem decide `muito_grande` é ele.
 * A conta de COLUNAS é outra coisa e vive separada (`estimativa` → `abas`): ela responde
 * "o que eu encontro ao abrir a planilha", vem de `sheet_*` e não do orçamento, e é por aba.
 */

import { type Opcao, opcao } from '@/components/base'
import { dataCurta, inteiro } from '@/lib/format'
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
 *
 * Não há um mapa de reserva aqui, de propósito. Um `{native: 7, '5m': 31, …}` escrito no
 * portal parece prudência e é a pior espécie de mentira: no dia em que o monitoramento
 * afrouxar (ou apertar) um teto, a tela continuaria recusando (ou deixando passar) pelo
 * número velho, com a confiança de quem tem uma constante.
 */
export function tetoDeDias(limites: Record<string, number>, passo: Passo): number | null {
  const v = limites[passo]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/**
 * As cinco opções de detalhe, com o teto do servidor viajando junto da escolha.
 *
 * Nenhuma vem desabilitada, mesmo quando o período estourou o teto dela: quem lê "até 7 dias
 * por arquivo" ao lado de "Cada leitura" entende a troca que está fazendo, e a opção
 * desabilitada esconderia justamente a informação de que o cliente precisa para decidir entre
 * encurtar o período e engrossar o detalhe. Quem recusa o pedido é `impedimento`, com a
 * conta feita.
 */
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

/** O passo escolhido e — quando a escolha não foi do cliente — a frase que a anuncia. */
export type PassoEscolhido = { passo: Passo; aviso: string | null }

/**
 * O passo que cabe, e o aviso quando ele **não** foi o pedido.
 *
 * O ajuste silencioso é a mudança que se descobre no arquivo: o cliente escolhe "a cada 5
 * minutos", muda o período para quatro meses, e recebe um arquivo de hora em hora sem nunca
 * ter lido a palavra "hora". Por isso o aviso é parte do retorno, e não um efeito colateral
 * que a tela pode esquecer de mostrar.
 *
 * Engrossa o mínimo necessário: procura do mais FINO para o mais grosso e para no primeiro
 * que couber, preservando o máximo de detalhe.
 */
export function ajustarPasso(
  atual: Passo,
  dias: number,
  limites: Record<string, number>,
): PassoEscolhido {
  const cabe = (p: Passo) => {
    const teto = tetoDeDias(limites, p)
    return teto === null || dias <= teto
  }
  if (cabe(atual)) return { passo: atual, aviso: null }
  const tetoAtual = tetoDeDias(limites, atual)
  for (const p of [...PASSOS].reverse()) {
    if (cabe(p)) {
      return {
        passo: p,
        aviso:
          `O período tem ${dias} dias, e "${ROTULO_DO_PASSO[atual].toLowerCase()}" aceita ` +
          `${tetoAtual}. Ajustei para "${ROTULO_DO_PASSO[p].toLowerCase()}".`,
      }
    }
  }
  // Nem o passo mais grosso alcança. Deixa nele — que é o que aceita mais — e DIZ, em vez de
  // devolver um passo trocado em silêncio: `impedimento` ainda vai recusar o pedido, e o
  // cliente precisa entender que o problema passou a ser o período, não o detalhe.
  const maiorTeto = tetoDeDias(limites, PASSOS[0])
  return {
    passo: PASSOS[0],
    aviso:
      `O período tem ${dias} dias, e nenhum detalhe alcança tanto` +
      `${maiorTeto === null ? '' : ` (o máximo é ${maiorTeto})`}. Deixei em ` +
      `"${ROTULO_DO_PASSO[PASSOS[0]].toLowerCase()}" — encurte o período.`,
  }
}

/**
 * O detalhe que a tela abre marcado — e que **nunca nasce inválido**.
 *
 * Dia → 15 minutos; Mês → de hora em hora; Ano → total por dia. Se o período escolhido não
 * couber no sugerido (um "personalizado" de seis meses, por exemplo), engrossa até caber — e
 * devolve o aviso, porque abrir a tela num passo que o cliente não escolheu é exatamente a
 * mudança calada que `ajustarPasso` existe para nomear.
 */
export function passoSugerido(
  recorte: 'dia' | 'mes' | 'ano' | 'livre',
  dias: number,
  limites: Record<string, number>,
): PassoEscolhido {
  const inicial: Passo =
    recorte === 'dia' ? '15m' : recorte === 'mes' ? '1h' : recorte === 'ano' ? '1d' : '1h'
  return ajustarPasso(inicial, dias, limites)
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

/* ------------------------------------------------------------- as 14 linhas */

/**
 * A umidade não é uma `VarEstacao` — não existe coluna dela em tabela nenhuma do
 * monitoramento (`load_options` devolve `"umidade": False` com esse comentário escrito), e o
 * pedido não a aceita. Ela existe aqui só para ocupar a linha na tela, permanentemente
 * desabilitada, com o motivo. É a única chave da régua que nunca chega a viajar.
 */
export type ChaveDaEstacao = VarEstacao | 'umidade'

/** Uma variável da régua: como ela se chama para o cliente, e o que ela é. */
export type LinhaDeVariavel<C extends string> = {
  chave: C
  rotulo: string
  /** A segunda linha, que diz o que o número significa — não o que o botão faz. */
  ajuda: string
}

/** As quatro do inversor. */
export const VARIAVEIS_DO_INVERSOR: LinhaDeVariavel<VarInversor>[] = [
  {
    chave: 'geracao',
    rotulo: 'Geração (kWh)',
    ajuda: 'a energia gerada dentro de cada intervalo',
  },
  {
    chave: 'potencia',
    rotulo: 'Potência (kW)',
    ajuda: 'a média das leituras do intervalo; no total por dia, o pico do dia',
  },
  {
    chave: 'status',
    rotulo: 'Situação do inversor',
    ajuda: 'o texto que o inversor reporta, uma leitura de cada vez',
  },
  {
    chave: 'paradas',
    rotulo: 'Intervalos desligados',
    ajuda: 'a aba Paradas e os minutos desligados dentro de cada intervalo',
  },
]

/** As sete da estação — inclusive a que nenhuma usina tem. */
export const VARIAVEIS_DA_ESTACAO: LinhaDeVariavel<ChaveDaEstacao>[] = [
  {
    chave: 'poa',
    rotulo: 'Irradiação no plano dos módulos',
    ajuda: 'W/m² médio e kWh/m² no intervalo — é o denominador do PR',
  },
  {
    chave: 'ghi',
    rotulo: 'Irradiação no plano horizontal',
    ajuda: 'W/m² médio e kWh/m² no intervalo',
  },
  { chave: 'temp_modulo', rotulo: 'Temperatura do módulo', ajuda: 'sensor da estação, em °C' },
  { chave: 'temp_ambiente', rotulo: 'Temperatura ambiente', ajuda: 'sensor da estação, em °C' },
  { chave: 'vento', rotulo: 'Velocidade do vento', ajuda: 'sensor da estação, em m/s' },
  {
    chave: 'umidade',
    rotulo: 'Umidade do ar',
    ajuda: 'nenhuma estação envia umidade — o sensor não é integrado ao monitoramento',
  },
  {
    chave: 'temp_ambiente_rele',
    rotulo: 'Temperatura ambiente (pelo relé)',
    ajuda: 'a mesma grandeza, medida pelo relé em vez da estação',
  },
]

/** A única da fronteira. Vem sempre marcada: um medidor sem energia não é um pedido. */
export const VARIAVEIS_DA_FRONTEIRA: LinhaDeVariavel<'energia'>[] = [
  {
    chave: 'energia',
    rotulo: 'Energia (kWh)',
    ajuda: 'o quanto o acumulado de cada leitor andou dentro do intervalo',
  },
]

/** As duas do sistema. */
export const VARIAVEIS_DO_SISTEMA: LinhaDeVariavel<VarSistema>[] = [
  {
    chave: 'pr',
    rotulo: 'PR — quanto rendeu do que o sol ofereceu',
    ajuda: 'energia ÷ (irradiação × potência instalada) no intervalo; vazia sem luz',
  },
  {
    chave: 'produtividade',
    rotulo: 'Produtividade (kWh/kWp)',
    ajuda: 'energia ÷ potência instalada do grupo',
  },
]

/**
 * Quantas linhas de variável a régua oferece ao todo — 4 + 7 + 1 + 2.
 *
 * Existe para o teste ter um número só a conferir. Se um dia o monitoramento passar a exportar
 * uma grandeza nova, este número sobe junto com a lista; se alguém apagar uma linha "para
 * simplificar", ele desce e o teste reprova.
 */
export const TOTAL_DE_VARIAVEIS =
  VARIAVEIS_DO_INVERSOR.length +
  VARIAVEIS_DA_ESTACAO.length +
  VARIAVEIS_DA_FRONTEIRA.length +
  VARIAVEIS_DO_SISTEMA.length

/** Os rótulos, montados a partir da régua — para não existirem duas listas de nomes. */
export const ROTULO_DO_INVERSOR = Object.fromEntries(
  VARIAVEIS_DO_INVERSOR.map((v) => [v.chave, v.rotulo]),
) as Record<VarInversor, string>

export const ROTULO_DA_ESTACAO = Object.fromEntries(
  VARIAVEIS_DA_ESTACAO.map((v) => [v.chave, v.rotulo]),
) as Record<ChaveDaEstacao, string>

export const ROTULO_DO_SISTEMA = Object.fromEntries(
  VARIAVEIS_DO_SISTEMA.map((v) => [v.chave, v.rotulo]),
) as Record<VarSistema, string>

/** As colunas de clima exportáveis, sem o relé (que é distinção de operador). */
export const CLIMA: VarEstacao[] = ['poa', 'ghi', 'temp_modulo', 'temp_ambiente', 'vento']

/* --------------------------------------------------- disponibilidade e motivo */

function semInversores(o: OpcoesDeDados): boolean {
  return o.skids.every((s) => s.series.length === 0)
}

const SEM_INVERSOR = 'esta usina não tem inversores cadastrados no monitoramento'
const SEM_ESTACAO = 'esta usina não tem estação solarimétrica com dados'
const SEM_SENSOR =
  'a estação desta usina não coleta esta grandeza (ela só chega quando o registrador do ' +
  'inversor é importado)'
const SEM_RELE = 'esta usina não tem relé de temperatura'
const SEM_MEDIDOR = 'esta usina não tem medidor de fronteira'
const SEM_POA = 'sem estação não há irradiação, e sem irradiação não se calcula PR'
/**
 * O motivo da umidade sai da PRÓPRIA régua — uma frase, num lugar só. Procurado pela chave e
 * não pela posição: a linha pode mudar de lugar na lista, e a frase tem de ir junto.
 */
const SEM_UMIDADE =
  VARIAVEIS_DA_ESTACAO.find((v) => v.chave === 'umidade')?.ajuda ??
  'o monitoramento não coleta umidade'
const PRECISA_DE_INTERVALO =
  'precisa de um intervalo fechado para ser calculado — escolha "a cada 5 minutos" ou mais grosso'

/**
 * Por que esta variável de inversor não serve agora — ou `null` quando serve.
 *
 * O `status` é a única que o servidor recusa com 400 (`bloco_indisponivel`): é um texto por
 * leitura, e não há como resumir texto num intervalo.
 *
 * As **paradas** são o caso que custou uma medição para ser dito direito. O servidor **não**
 * recusa o pedido; ele o atende pela metade, calado. Medido na rota real (Porto Ferreira, um
 * dia, passo nativo, `variaveis: ['geracao','paradas']`): voltam as abas
 * `['Leia-me','Inversores','Paradas']` — ou seja, a **lista de paradas vem** —, mas a coluna
 * "Min. desligado" **não existe** na aba Inversores, porque `sheet_inversores` faz
 * `tem_paradas = "paradas" in sel.variaveis and win.step != "native"`. Metade do que a linha
 * promete some sem uma palavra, depois da espera.
 *
 * Daí ser impedimento aqui, e não um aviso: a saída nomeada não custa nada. A aba Paradas é a
 * MESMA em qualquer passo (é a lista de paradas que tocam a janela, não uma agregação por
 * balde), então trocar para "a cada 5 minutos" devolve a lista igual e os minutos por
 * intervalo de brinde.
 */
export function motivoDoInversor(
  chave: VarInversor,
  o: OpcoesDeDados,
  passo: Passo,
): string | null {
  if (semInversores(o)) return SEM_INVERSOR
  if (chave === 'status' && passo !== 'native') {
    return (
      `só sai em "${ROTULO_DO_PASSO.native.toLowerCase()}" — é um texto por leitura, e não ` +
      'há como resumir texto num intervalo'
    )
  }
  if (chave === 'paradas' && passo === 'native') {
    return (
      'em "cada leitura" não há intervalo, e os minutos desligados por intervalo não saem (só ' +
      'a aba Paradas). Escolha "a cada 5 minutos" ou mais grosso: a lista de paradas é a ' +
      'mesma, e aí os minutos vêm junto'
    )
  }
  return null
}

/**
 * Por que esta grandeza da estação não serve nesta usina — ou `null` quando serve.
 *
 * O motivo é escolhido pela CAUSA, e não pela chave (que é o atalho da tela do meuWatt): sem
 * estação nenhuma, "não tem estação"; com estação que não traz aquele sensor, "não coleta".
 * São duas conversas diferentes — uma se resolve instalando a estação, a outra importando o
 * registrador do inversor.
 */
export function motivoDaEstacao(chave: ChaveDaEstacao, o: OpcoesDeDados): string | null {
  if (chave === 'umidade') return SEM_UMIDADE
  if (chave === 'temp_ambiente_rele') return o.estacao.temp_ambiente_rele ? null : SEM_RELE
  if (!o.estacao.disponivel) return SEM_ESTACAO
  return o.estacao.colunas[chave] === true ? null : SEM_SENSOR
}

/** Por que o medidor não serve nesta usina — ou `null`. */
export function motivoDaFronteira(o: OpcoesDeDados): string | null {
  return o.leitores.length > 0 ? null : SEM_MEDIDOR
}

/**
 * Por que este índice não serve agora — ou `null`.
 *
 * A frase do PR diz a cadeia inteira, e não só o último elo: "sem estação não há irradiação,
 * e sem irradiação não se calcula PR" é a diferença entre "o portal está quebrado" e "eu sei
 * o que teria de instalar para ter isso".
 */
export function motivoDoSistema(
  chave: VarSistema,
  o: OpcoesDeDados,
  passo: Passo,
): string | null {
  if (passo === 'native') return PRECISA_DE_INTERVALO
  if (chave === 'pr') return o.sistema.pr ? null : SEM_POA
  return o.sistema.produtividade ? null : SEM_INVERSOR
}

/* ------------------------------------------------- as linhas viram Opcao[] */

/**
 * As quatro linhas do inversor, prontas para a lista.
 *
 * `opcao()` é o que garante estruturalmente que nenhuma volte desabilitada e muda: o motivo é
 * o argumento que desabilita.
 */
export function opcoesDoInversor(o: OpcoesDeDados, passo: Passo): Opcao[] {
  return VARIAVEIS_DO_INVERSOR.map((v) =>
    opcao(
      { valor: v.chave, rotulo: v.rotulo, detalhe: v.ajuda },
      motivoDoInversor(v.chave, o, passo),
    ),
  )
}

/** As sete da estação — a umidade sempre desabilitada, e nunca ausente. */
export function opcoesDaEstacao(o: OpcoesDeDados): Opcao[] {
  return VARIAVEIS_DA_ESTACAO.map((v) =>
    opcao({ valor: v.chave, rotulo: v.rotulo, detalhe: v.ajuda }, motivoDaEstacao(v.chave, o)),
  )
}

/** A única da fronteira. */
export function opcoesDaFronteira(o: OpcoesDeDados): Opcao[] {
  return VARIAVEIS_DA_FRONTEIRA.map((v) =>
    opcao({ valor: v.chave, rotulo: v.rotulo, detalhe: v.ajuda }, motivoDaFronteira(o)),
  )
}

/** As duas do sistema. */
export function opcoesDoSistema(o: OpcoesDeDados, passo: Passo): Opcao[] {
  return VARIAVEIS_DO_SISTEMA.map((v) =>
    opcao(
      { valor: v.chave, rotulo: v.rotulo, detalhe: v.ajuda },
      motivoDoSistema(v.chave, o, passo),
    ),
  )
}

/* ------------------------------------------------------------ agrupamentos */

/**
 * Os dois agrupamentos de cada bloco que tem um — a capacidade que o dono nomeou ("o diretor
 * quer sim baixar por skid") e que não pode ficar atrás de gaveta nenhuma.
 *
 * A fronteira agrupa por LEITOR e não por skid: o cadastro não tem vínculo leitor → skid, e
 * chamar a coluna de "Skid 3" quando o que existe é um leitor com nome próprio seria inventar
 * uma ligação. `rodapeDaFronteira` diz isso na tela.
 */
export const AGRUPAMENTO_DO_INVERSOR: Opcao[] = [
  { valor: 'lista', rotulo: 'Uma coluna por inversor', detalhe: 'mais o total da usina' },
  {
    valor: 'skid',
    rotulo: 'Uma coluna por skid',
    detalhe: 'cada coluna é a soma dos inversores marcados daquele skid',
  },
]

export const AGRUPAMENTO_DA_FRONTEIRA: Opcao[] = [
  { valor: 'leitor', rotulo: 'Uma coluna por leitor', detalhe: 'mais o total da usina' },
  { valor: 'usina', rotulo: 'Só o total da usina', detalhe: 'a soma dos leitores' },
]

export const AGRUPAMENTO_DO_SISTEMA: Opcao[] = [
  { valor: 'usina', rotulo: 'Da usina inteira', detalhe: 'um índice por intervalo' },
  { valor: 'skid', rotulo: 'De cada skid', detalhe: 'um índice por skid, por intervalo' },
]

/**
 * O que o cliente precisa saber sobre a coluna de skid antes de mexer na seleção.
 *
 * Sem esta frase, desmarcar um inversor e continuar lendo "SKID-02" no cabeçalho faz o número
 * parecer o skid inteiro. Medido na rota real: 8 inversores marcados em 2 de 5 skids devolvem
 * um arquivo com exatamente duas colunas, `SKID-01` e `SKID-02`, cada uma somando só os
 * marcados.
 */
export const AVISO_DA_SOMA_POR_SKID =
  'o que você desmarcar também sai da soma do skid — a coluna continua com o nome do skid'

/** Quem são os leitores desta usina, para a tela não prometer um vínculo que não existe. */
export function rodapeDaFronteira(o: OpcoesDeDados): string | null {
  if (o.leitores.length === 0) return null
  const nomes = o.leitores.map((l) => l.nome ?? `Leitor #${l.id}`)
  return (
    `Leitores: ${nomes.join(' · ')}. O cadastro não liga leitor a skid: cada leitor é uma ` +
    'coluna com o nome cadastrado.'
  )
}

/* ------------------------------------------------------------------ atalhos */

export type IdDePacote = 'geracao' | 'geracao_clima' | 'medidor' | 'desempenho' | 'tudo'

/** As colunas de clima que ESTA estação de fato coleta. */
export function climaDisponivel(o: OpcoesDeDados): VarEstacao[] {
  if (!o.estacao.disponivel) return []
  return CLIMA.filter((c) => o.estacao.colunas[c] === true)
}

/**
 * Os atalhos que PREENCHEM os blocos.
 *
 * Escolher um marca as caixas à vista e some — não deixa a tela num modo, e por isso não há um
 * estado "personalizado" para administrar depois que o cliente mexe. Quem baixa a mesma coisa
 * todo mês parte daqui; quem quer escolher coluna por coluna ignora e vai direto aos blocos,
 * que estão na tela.
 */
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
 * Por que este atalho não serve para esta usina — ou `null` quando serve.
 *
 * A linha **continua na lista**, com o motivo colado: sumir com ela faria o cliente concluir
 * que o portal não oferece, quando o fato é sobre a usina dele.
 */
export function motivoDoPacote(id: IdDePacote, o: OpcoesDeDados): string | null {
  if ((id === 'geracao' || id === 'geracao_clima') && semInversores(o)) return SEM_INVERSOR
  if (id === 'geracao_clima' && climaDisponivel(o).length === 0) return SEM_ESTACAO
  if (id === 'medidor' && o.leitores.length === 0) return SEM_MEDIDOR
  if (id === 'desempenho' && !o.sistema.pr && !o.sistema.produtividade) return SEM_POA
  if (id === 'tudo' && vazia(montarPacote('tudo', o))) {
    return 'não há nada exportável cadastrado nesta usina'
  }
  return null
}

/** O que o atalho pediria e a estação não tem — dito antes, não descoberto no arquivo. */
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

/** Só o medidor foi pedido — muda a cadência do passo nativo e o alcance da retenção. */
export function soMedidor(s: Selecao): boolean {
  return !!s.fronteira && !s.inversores && !s.estacao && !s.sistema
}

/**
 * O atalho traduzido em seleção — a mesma que os blocos da tela editam.
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
      // A irradiação vai junto porque é o denominador da PR: sem ela o cliente teria o índice
      // e nenhuma forma de conferi-lo.
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

/**
 * Uma aba do arquivo, como o cliente vai encontrá-la ao abrir no Excel.
 *
 * `null` em `linhas` ou `colunas` é **ausência declarada**, nunca zero: há coisa que não dá
 * para saber daqui (quantas paradas houve no período; quantos sensores o relé tem). Quem
 * mostra escreve o travessão ou a `nota` — jamais um número inventado.
 */
export type AbaEstimada = {
  nome: string
  /** Linhas de dado, sem contar o cabeçalho. */
  linhas: number | null
  /** Colunas, **contando a primeira, `Início (BRT)`**, que toda aba de dado tem. */
  colunas: number | null
  /** O que o número não fecha, escrito para o cliente. */
  nota?: string
}

export type Estimativa = {
  /** Linhas das abas de balde — a resposta curta para "que tamanho isto tem". */
  linhas: number
  /** As abas do caderno, na ordem em que o meuWatt as escreve. */
  abas: AbaEstimada[]
  /**
   * O orçamento do SERVIDOR (`validate_request`), que **não** é a forma do arquivo: ele conta
   * `2 × variáveis + 1` na estação, ignora o agrupamento da fronteira e cobra 5 colunas por
   * grupo no sistema. É de propósito que ele viva aqui separado de `abas` — foi por serem o
   * mesmo número que a tela dizia "37 colunas" para um caderno cuja aba mais larga tem 22.
   */
  celulas: number
}

/**
 * Quantos skids sobram no arquivo depois da seleção — os que têm **ao menos um** inversor
 * marcado.
 *
 * Nem o portal (que fazia `Math.min(nSkids, series.length)`, copiando o servidor) nem a tela
 * do meuWatt (que usava `opts.skids.length` cru) respondiam a esta pergunta, e com o
 * agrupamento por skid em primeiro plano ela erra justamente no caso que estamos abrindo.
 * Medido na rota real: 8 inversores marcados em 2 de 5 skids devolvem um arquivo com **duas**
 * colunas de skid (`SKID-01`, `SKID-02`), enquanto a conta antiga diria `min(5, 8)` = 5.
 *
 * A divergência em relação a `validate_request` deixou de ser um custo: o orçamento do
 * servidor agora tem função própria (`celulasDoOrcamento`) e é ele quem decide `muito_grande`.
 * Aqui a pergunta é outra — quantas colunas o cliente encontra ao abrir a planilha.
 */
function skidsNoArquivo(o: OpcoesDeDados, series: string[] | null): number {
  if (series === null) return o.skids.filter((k) => k.series.length > 0).length
  const marcadas = new Set(series)
  return o.skids.filter((k) => k.series.some((s) => marcadas.has(s.chave))).length
}

/**
 * O orçamento de células do servidor, copiado de `validate_request` **linha por linha**.
 *
 * Copiado de propósito, e é a única cópia legítima deste módulo: quem decide `muito_grande` é
 * ele, e uma conta mais fiel ao arquivo daria um aviso que não corresponde à recusa que vem.
 * Inclusive o `min(base, len(series))` do agrupamento por skid, que superconta — a régua do
 * orçamento não é a régua do arquivo.
 */
export function celulasDoOrcamento(s: Selecao, o: OpcoesDeDados, janela: Janela): number {
  const nSeries = o.skids.reduce((t, k) => t + k.series.length, 0)
  let colunas = 0
  if (s.inversores) {
    const marcadas = s.inversores.series
    let base = s.inversores.agrupamento === 'lista' ? nSeries : o.skids.length
    if (marcadas && marcadas.length > 0) base = Math.min(base, marcadas.length)
    const semParadas = s.inversores.variaveis.filter((v) => v !== 'paradas').length
    colunas += (base + 1) * semParadas
    if (s.inversores.variaveis.includes('paradas')) colunas += base + 1
  }
  if (s.estacao) colunas += 2 * s.estacao.variaveis.length + 1
  if (s.fronteira) colunas += o.leitores.length + 1
  if (s.sistema) colunas += (s.sistema.agrupamento === 'skid' ? o.skids.length : 1) * 5
  return janela.baldes * Math.max(colunas, 1)
}

/** Quantas colunas cada variável de clima ocupa na aba Estação, neste passo. */
function colunasDaVariavelDeClima(v: VarEstacao, passo: Passo): number {
  if (v === 'temp_ambiente_rele') return 0 // sai no bloco do relé, no fim da aba
  if (v === 'poa') return passo === 'native' ? 3 : passo === '1d' ? 1 : 2
  if (v === 'ghi') return passo === 'native' ? 2 : passo === '1d' ? 1 : 2
  // Temperatura do módulo, ambiente e vento: o valor, mais o máximo no total por dia.
  return passo === '1d' ? 2 : 1
}

/**
 * As abas do arquivo e a largura de cada uma — a conta REFEITA contra o escritor de lá
 * (`mw-api/src/exports/service.py::sheet_*`) e conferida abrindo os arquivos.
 *
 * A conta antiga era a do ORÇAMENTO, e por isso mentia em três lugares ao mesmo tempo, todos
 * medidos abrindo a planilha com `openpyxl` em 05/09/2026:
 *
 * | pedido | a tela dizia | o arquivo tem |
 * |---|---|---|
 * | 2 skids, geração, 1 h | 3 colunas | **4** (`Início (BRT)` faltava) |
 * | fronteira agrupada por USINA | 6 colunas | **3** (o agrupamento era ignorado) |
 * | fronteira por leitor, 5 leitores | 6 colunas | **8** (`Leitores com leitura` faltava) |
 *
 * E o pior não era nenhum dos três: era somar tudo num número só. "37 colunas" não era a
 * largura de aba nenhuma de um caderno cuja aba mais larga tinha 22 — o cliente não tem onde
 * conferir esse número, e o próprio Leia-me do arquivo o desmente linha a linha.
 */
export function estimativa(
  s: Selecao,
  o: OpcoesDeDados,
  janela: Janela,
  passo: Passo,
): Estimativa {
  const nSeries = o.skids.reduce((t, k) => t + k.series.length, 0)
  const abas: AbaEstimada[] = []

  if (s.inversores) {
    const grupos =
      s.inversores.agrupamento === 'lista'
        ? (s.inversores.series?.length ?? nSeries)
        : skidsNoArquivo(o, s.inversores.series)
    // `paradas` não é uma coluna de valor: é a coluna "Min. desligado" por grupo mais a aba.
    const valores = s.inversores.variaveis.filter((v) => v !== 'paradas')
    // A regra de lá: `tem_paradas = "paradas" in variaveis and step != "native"`.
    const temParadas = s.inversores.variaveis.includes('paradas') && passo !== 'native'
    // O total da usina só existe para o que soma. `status` é texto: não tem coluna de usina.
    const totais = valores.filter((v) => v !== 'status').length
    abas.push({
      nome: s.inversores.agrupamento === 'lista' ? 'Inversores' : 'Skids',
      linhas: janela.baldes,
      colunas: 1 + grupos * (valores.length + (temParadas ? 1 : 0)) + totais + (temParadas ? 1 : 0),
    })
    if (temParadas) {
      abas.push({
        nome: 'Paradas',
        linhas: null,
        colunas: null,
        nota: 'uma linha por parada no período',
      })
    }
  }

  if (s.estacao) {
    const clima = s.estacao.variaveis.reduce(
      (t, v) => t + colunasDaVariavelDeClima(v, passo),
      0,
    )
    const temPoaNativo = passo === 'native' && s.estacao.variaveis.includes('poa')
    // O bloco da estação (as colunas de clima e o `Amostras`) só existe quando há estação com
    // dado; o relé é outra fonte e sobrevive sozinho.
    const daEstacao = o.estacao.disponivel ? clima + (temPoaNativo ? 1 : 0) + 1 : 0
    const temRele = s.estacao.variaveis.includes('temp_ambiente_rele')
    abas.push({
      nome: 'Estação',
      linhas: janela.baldes,
      colunas: 1 + daEstacao,
      // ⛔ O número de sensores do relé NÃO vem nas opções (`load_options` devolve só
      // `temp_ambiente_rele: bool`), e Porto Ferreira tem cinco. Fechar a conta aqui exigiria
      // inventá-lo. Medido: 9 colunas com POA + relé, das quais 5 são de sensor.
      ...(temRele
        ? { nota: `mais ${passo === '1d' ? '2 colunas' : '1 coluna'} por sensor do relé` }
        : {}),
    })
  }

  if (s.fronteira) {
    const porLeitor = s.fronteira.agrupamento === 'leitor' ? (passo === 'native' ? 4 : 1) : 0
    // `Usina · Energia (kWh)` e `Leitores com leitura` — as duas que faltavam, e que o passo
    // nativo não tem (lá não há balde para somar).
    const totais = passo === 'native' ? 0 : 2
    abas.push({
      nome: 'Fronteira',
      linhas: janela.baldes,
      colunas: 1 + o.leitores.length * porLeitor + totais,
    })
  }

  if (s.sistema) {
    // O bloco do sistema ignora a seleção de inversores (`sheet_sistema` recebe `series_all`):
    // agrupado por skid, saem TODOS os skids da usina.
    const grupos = s.sistema.agrupamento === 'skid' ? skidsNoArquivo(o, null) : 1
    const temPr = s.sistema.variaveis.includes('pr')
    // Energia e Capacidade sempre; Produtividade se pedida; POA e PR se pedida a PR.
    const porGrupo = 2 + (s.sistema.variaveis.includes('produtividade') ? 1 : 0) + (temPr ? 2 : 0)
    const canonica = temPr && passo === '1d' && s.sistema.agrupamento === 'usina' ? 1 : 0
    abas.push({
      nome: 'Sistema',
      linhas: janela.baldes,
      colunas: 1 + grupos * porGrupo + canonica,
    })
  }

  return { linhas: janela.baldes, abas, celulas: celulasDoOrcamento(s, o, janela) }
}

/** O orçamento do servidor, quando ele o declarou. */
export function passaDoOrcamento(e: Estimativa, limites: Record<string, number>): boolean {
  const teto = limites.max_celulas
  return typeof teto === 'number' && Number.isFinite(teto) && e.celulas > teto
}

/**
 * O aviso de que o pedido talvez não caiba — e que **nunca** é um veto.
 *
 * A conta é a do servidor (`celulasDoOrcamento`), mas o acervo dele não é: `estimate_buckets`
 * conta os baldes que a janela COMPORTA, e não os que têm dado. Recusar o download com base
 * nela seria negar ao cliente um arquivo que talvez o monitoramento montasse sem reclamar. Por
 * isso a frase termina oferecendo o pedido: no limiar, o benefício da dúvida é de quem está
 * esperando os números.
 */
export function avisoDeOrcamento(
  e: Estimativa,
  limites: Record<string, number>,
): string | null {
  if (!passaDoOrcamento(e, limites)) return null
  return (
    `A conta desta tela dá ≈ ${inteiro(e.celulas)} células, e o monitoramento monta até ` +
    `${inteiro(limites.max_celulas)}. Diminua o período, escolha um detalhe mais grosso ou ` +
    'marque menos inversores. Se quiser tentar assim mesmo, pode pedir.'
  )
}

/* ------------------------------------------------------------------ retenção */

type Retencao = OpcoesDeDados['retencao']

/**
 * Até onde o acervo alcança para ESTA seleção, em uma linha sob o passo.
 *
 * São **duas** datas, e por isso a frase troca: o medidor guarda 24 meses, os inversores e a
 * estação guardam 6. Uma frase só seria falsa metade do tempo — e a metade em que fosse falsa
 * é justamente a de quem pede um ano de faturamento e leria "só os últimos 6 meses".
 *
 * No total por dia não há linha nenhuma a mostrar, e isso não é omissão: o servidor põe a
 * checagem inteira de retenção dentro de `if step != "1d"`, então o total por dia realmente
 * não tem prazo. É a saída que todas as frases de retenção nomeiam.
 */
export function linhaDeRetencao(s: Selecao, r: Retencao, passo: Passo): string | null {
  if (passo === '1d') return null
  if (soMedidor(s)) {
    return r.ssu_desde ? `Leituras do medidor desde ${dataCurta(r.ssu_desde)}.` : null
  }
  return r.snapshots_desde
    ? `Leitura fina de inversores e estação desde ${dataCurta(r.snapshots_desde)}.`
    : null
}

/**
 * Por que este dia só tem total diário — ou `null` quando o acervo o alcança inteiro.
 *
 * Vai colado em cada dia oferecido no seletor: a ausência é do ACERVO, não do arquivo, e o
 * cliente precisa saber disso enquanto escolhe, não depois de esperar meio minuto. Depende da
 * seleção pela mesma razão de `linhaDeRetencao`: um dia de 2025 é impossível para o inversor e
 * perfeitamente normal para o medidor.
 */
export function motivoDeRetencao(dia: string, r: Retencao, soMedidor = false): string | null {
  if (soMedidor) {
    return r.ssu_desde && dia < r.ssu_desde
      ? 'o monitoramento não guarda leitura do medidor tão atrás'
      : null
  }
  if (r.snapshots_desde && dia < r.snapshots_desde) {
    return 'a leitura minuto a minuto não existe mais — só o total por dia'
  }
  return null
}

/**
 * Os dias que o seletor "Personalizado" oferece, do mais recente para trás, com o motivo da
 * retenção colado em cada um.
 *
 * O fundo da lista é o do acervo do medidor (`ssu_desde`), que é o mais antigo que o
 * monitoramento guarda; sem ele, dois anos. Nada é cortado por gosto: abaixo daquela data não
 * há leitura nenhuma para pedir, de bloco nenhum.
 */
export function diasOferecidos(
  hoje: string,
  r: Retencao,
  soMedidor = false,
  maximo = 760,
): Opcao[] {
  const fundo = r.ssu_desde ?? null
  const saida: Opcao[] = []
  const d = daData(hoje)
  for (let i = 0; i < maximo; i += 1) {
    const iso = paraIso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - i))
    if (fundo && iso < fundo) break
    saida.push({
      valor: iso,
      rotulo: dataCurta(iso),
      detalhe: motivoDeRetencao(iso, r, soMedidor) ?? undefined,
    })
  }
  return saida
}

/* ------------------------------------------------------------------ impedimento */

/** O que impede este pedido de sair — com a conta feita e a saída nomeada. */
export type Impedimento = { texto: string }

/**
 * O que a tela sabe, com certeza, que o servidor vai recusar — ou atender pela metade.
 *
 * Só entram regras que são **aritmética nossa e certa**: contagem de dias contra o teto do
 * servidor, a retenção do acervo e as incompatibilidades de passo. O orçamento de células fica
 * de fora de propósito — é estimativa, e quem estima não veta.
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
        'Nenhum inversor está marcado. Marque ao menos um, ou volte a marcar todos no bloco ' +
        'dos inversores.',
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

  // As duas incompatibilidades de passo, pela MESMA régua que desabilita a linha no bloco —
  // uma frase, num lugar só. `status` o servidor recusa com 400; `paradas` ele atende pela
  // metade, em silêncio (ver `motivoDoInversor`), e é por isso que as duas param aqui.
  for (const v of s.inversores?.variaveis ?? []) {
    const motivo = motivoDoInversor(v, o, passo)
    if (motivo) return { texto: `"${ROTULO_DO_INVERSOR[v]}" ${motivo}.` }
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
      'Alguma coluna desta seleção esta usina não mede. Desmarque, nos blocos abaixo, o que ' +
      'estiver aparecendo como indisponível.',
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
