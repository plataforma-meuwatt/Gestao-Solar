/**
 * A memória da tela "Baixar dados": o que fica guardado entre visitas, e o que **nunca** fica.
 *
 * **A FORMA da pergunta é guardada por usina; o PERÍODO não.** Quem baixa a mesma planilha
 * todo mês não quer remontar a seleção — mas reabrir a tela já apontada para agosto devolveria,
 * calado, o arquivo do mês errado, e um arquivo errado que abre no Excel sem reclamar é pior do
 * que um erro. O período recomeça sempre à vista, no mês corrente. A garantia não é a boa
 * intenção de quem chama: `gravarForma` **remonta o objeto campo a campo** a partir de uma
 * lista fechada, então um `Pedido` inteiro (que carrega `inicio` e `fim`) passado por engano
 * entra sem as datas.
 *
 * **Restaurar às cegas é o defeito que este módulo existe para fechar.** A versão anterior
 * fazia `JSON.parse(cru) as FormaGuardada` e devolvia o resultado direto para a tela. Com a
 * seleção de inversores em primeiro plano isso passa a doer de verdade: devolve `slot:170` de
 * um inversor que saiu da usina, ou POA numa usina que perdeu a estação — e a tela abre travada
 * por um equipamento que morreu meses atrás, sem nada na tela que explique o quê. Aqui a
 * leitura é **reconciliada** contra as opções de hoje, com três regras:
 *
 * 1. **sobrou parte → usa o que sobrou, calado.** Guardei 24 inversores, a usina tem 20: leva
 *    os 20. Avisar seria transformar manutenção de cadastro em problema do cliente.
 * 2. **não sobrou NENHUMA série → volta a `null`, que é "todos".** Nunca a lista vazia: `[]`
 *    viajaria como "nenhuma série" e o monitoramento devolveria um arquivo sem coluna
 *    nenhuma — o pior desfecho possível, porque tem status 200 e abre.
 * 3. **o bloco inteiro ficou impossível → volta a "Não entra", com o motivo escrito.** Aqui
 *    o silêncio seria mentira: a estação sumiu do cadastro e a coluna some da tela sem
 *    explicação faz o cliente concluir que o portal deixou de oferecer.
 *
 * **Gravar degrada em silêncio, ler nunca derruba.** `localStorage` lança de verdade em aba
 * anônima com cookies de terceiros bloqueados e quando a cota estoura. Guardar uma preferência
 * não pode custar um download, e não poder LER a preferência não pode custar a tela: os dois
 * caminhos caem no padrão, que é sempre válido.
 *
 * **O que não se guarda, além do período:** recusa, falha e a confirmação de sucesso. Os três
 * são sobre UM pedido, e ressuscitá-los na visita seguinte afirmaria um fato que já não é
 * (é o mesmo defeito que o meuWatt corrigiu no commit `c23b330`, quando o "arquivo pronto" da
 * usina anterior sobrevivia à troca de usina).
 */

import type {
  OpcoesDeDados,
  Passo,
  Selecao,
  VarEstacao,
  VarInversor,
  VarSistema,
} from '@/features/dados/api'

/* ------------------------------------------------------------------ vocabulário */

/** Tudo o que sobrevive a um recarregamento — e nada mais. */
export type FormaGuardada = {
  passo: Passo
  selecao: Selecao
  /** `HH:MM` do primeiro dia. */
  horaInicio: string
  /** `HH:MM` do último dia, inclusivo do minuto. */
  horaFim: string
  /**
   * De qual atalho a seleção partiu, quando partiu de um. É opcional de propósito: o atalho
   * PREENCHE os blocos e some — não é um modo em que a tela fica —, então a tela funciona
   * inteira sem ele e quem não o usa não grava nada.
   */
  pacote?: string
}

export type BlocoDaSelecao = 'inversores' | 'estacao' | 'fronteira' | 'sistema'

/** Um bloco que a usina não tem mais, com o porquê pronto para a tela. */
export type Descartado = { bloco: BlocoDaSelecao; motivo: string }

/**
 * O que a leitura devolve.
 *
 * `forma` nula é "não havia nada guardado (ou o que havia não era legível)" — a tela abre no
 * padrão dela. Uma forma COM `selecao` toda nula é outra coisa: havia memória, e a usina
 * perdeu tudo o que ela pedia; `descartados` diz bloco a bloco o que aconteceu, e a tela tem
 * de mostrar isso em vez de abrir calada com nada marcado.
 */
export type FormaLida = { forma: FormaGuardada | null; descartados: Descartado[] }

const PASSOS_VALIDOS: Passo[] = ['native', '5m', '15m', '1h', '1d']
const VARS_INVERSOR: VarInversor[] = ['geracao', 'potencia', 'status', 'paradas']
const VARS_SISTEMA: VarSistema[] = ['pr', 'produtividade']
/** As colunas que vêm da estação; o relé é gate próprio e entra à parte. */
const COLUNAS_DA_ESTACAO: VarEstacao[] = ['poa', 'ghi', 'temp_modulo', 'temp_ambiente', 'vento']

/** `00:00` a `23:59`. O que não casa não vira horário: vira o padrão do dia inteiro. */
const HORARIO = /^([01]\d|2[0-3]):[0-5]\d$/

const HORA_INICIO_PADRAO = '00:00'
const HORA_FIM_PADRAO = '23:59'

/**
 * Onde a forma desta usina mora.
 *
 * A usina entra na chave porque a seleção é sobre o cadastro DELA: uma chave só devolveria a
 * seleção de Porto Ferreira ao abrir Ibitinga, com séries que não existem lá.
 */
export function chaveDaForma(usinaId: number): string {
  return `dados:forma:u${usinaId}`
}

/* ------------------------------------------------------------------ leitura crua */

function objeto(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
}

function textos(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
}

function horario(v: unknown, padrao: string): string {
  return typeof v === 'string' && HORARIO.test(v) ? v : padrao
}

/**
 * As chaves de série que a usina tem HOJE.
 *
 * É um `Set` e não uma lista porque a reconciliação de uma seleção grande (uma usina de 200
 * inversores, com a seleção guardada do mesmo tamanho) seria quadrática com `includes`.
 */
function chavesDeHoje(opcoes: OpcoesDeDados): Set<string> {
  const chaves = new Set<string>()
  for (const skid of opcoes.skids) {
    for (const serie of skid.series) chaves.add(serie.chave)
  }
  return chaves
}

/** As colunas de estação que ESTA usina de fato coleta hoje, o relé incluído. */
function estacaoDeHoje(opcoes: OpcoesDeDados): Set<VarEstacao> {
  const tem = new Set<VarEstacao>()
  if (opcoes.estacao.disponivel) {
    for (const c of COLUNAS_DA_ESTACAO) {
      if (opcoes.estacao.colunas[c] === true) tem.add(c)
    }
  }
  // O relé não é a estação: uma usina sem estação pode ter relé com temperatura ambiente, e
  // amarrar um ao outro apagaria a única coluna de clima que ela teria.
  if (opcoes.estacao.temp_ambiente_rele) tem.add('temp_ambiente_rele')
  return tem
}

/* ------------------------------------------------------------------ reconciliação */

/**
 * A forma guardada, confrontada com o que a usina tem hoje.
 *
 * Separada da leitura de propósito: é aqui que mora a decisão, e ela se prova sem tocar em
 * `localStorage` nenhum. `cru` é `unknown` porque o que está no armazenamento foi escrito por
 * uma versão anterior desta tela, ou por ninguém — tratar como `FormaGuardada` sem conferir é
 * exatamente o defeito que este módulo fecha.
 */
export function reconciliar(cru: unknown, opcoes: OpcoesDeDados): FormaLida {
  const bruto = objeto(cru)
  if (!bruto) return { forma: null, descartados: [] }

  const passoCru = bruto.passo
  const passo = PASSOS_VALIDOS.find((p) => p === passoCru)
  // Sem passo legível não há forma: o passo governa o teto de dias e a cadência do arquivo, e
  // chutar um faria a tela abrir mentindo sobre o que vai baixar.
  if (!passo) return { forma: null, descartados: [] }

  const guardada = objeto(bruto.selecao)
  const descartados: Descartado[] = []
  const selecao: Selecao = { inversores: null, estacao: null, fronteira: null, sistema: null }

  /* --- inversores ------------------------------------------------------------ */
  const inversores = objeto(guardada?.inversores)
  if (inversores) {
    const chaves = chavesDeHoje(opcoes)
    const variaveis = textos(inversores.variaveis).filter((v): v is VarInversor =>
      VARS_INVERSOR.includes(v as VarInversor),
    )
    if (chaves.size === 0) {
      descartados.push({
        bloco: 'inversores',
        motivo: 'esta usina não tem mais inversores no monitoramento',
      })
    } else if (variaveis.length === 0) {
      descartados.push({
        bloco: 'inversores',
        motivo: 'a escolha guardada não tem nenhuma coluna de inversor',
      })
    } else {
      // `null` é "não mexi" e alcança o inversor que entrar em operação depois; uma lista é o
      // conjunto congelado. Os dois estados são deliberados, e a reconciliação preserva a
      // distinção: lista que sobrevive continua lista, mesmo que hoje cubra todos.
      let series: string[] | null = null
      if (Array.isArray(inversores.series)) {
        const sobrou = textos(inversores.series).filter((k) => chaves.has(k))
        series = sobrou.length > 0 ? sobrou : null
      }
      selecao.inversores = {
        variaveis,
        agrupamento: inversores.agrupamento === 'skid' ? 'skid' : 'lista',
        series,
      }
    }
  }

  /* --- estação --------------------------------------------------------------- */
  const estacao = objeto(guardada?.estacao)
  if (estacao) {
    const tem = estacaoDeHoje(opcoes)
    const variaveis = textos(estacao.variaveis).filter((v): v is VarEstacao =>
      tem.has(v as VarEstacao),
    )
    if (variaveis.length > 0) {
      selecao.estacao = { variaveis }
    } else {
      descartados.push({
        bloco: 'estacao',
        motivo:
          tem.size === 0
            ? 'esta usina não tem mais estação solarimétrica com dados'
            : 'as colunas de clima que estavam guardadas esta estação não mede mais',
      })
    }
  }

  /* --- fronteira -------------------------------------------------------------- */
  const fronteira = objeto(guardada?.fronteira)
  if (fronteira) {
    if (opcoes.leitores.length > 0) {
      selecao.fronteira = {
        variaveis: ['energia'],
        agrupamento: fronteira.agrupamento === 'usina' ? 'usina' : 'leitor',
      }
    } else {
      descartados.push({
        bloco: 'fronteira',
        motivo: 'esta usina não tem mais medidor de fronteira',
      })
    }
  }

  /* --- sistema ---------------------------------------------------------------- */
  const sistema = objeto(guardada?.sistema)
  if (sistema) {
    const variaveis = textos(sistema.variaveis).filter(
      (v): v is VarSistema =>
        VARS_SISTEMA.includes(v as VarSistema) && opcoes.sistema[v as VarSistema] === true,
    )
    if (variaveis.length > 0) {
      selecao.sistema = {
        variaveis,
        agrupamento: sistema.agrupamento === 'skid' ? 'skid' : 'usina',
      }
    } else {
      descartados.push({
        bloco: 'sistema',
        // A cadeia inteira, e não só o efeito: sem irradiação não há denominador para a PR, e
        // dizer isso é a diferença entre "o portal quebrou" e "eu sei o que instalar".
        motivo: 'sem estação não há irradiação, e sem irradiação não se calcula PR',
      })
    }
  }

  const pacote = typeof bruto.pacote === 'string' ? bruto.pacote : undefined
  return {
    forma: {
      passo,
      selecao,
      horaInicio: horario(bruto.horaInicio, HORA_INICIO_PADRAO),
      horaFim: horario(bruto.horaFim, HORA_FIM_PADRAO),
      ...(pacote ? { pacote } : {}),
    },
    descartados,
  }
}

/* ------------------------------------------------------------------ armazenamento */

/** A forma desta usina, já reconciliada com o que ela tem hoje. */
export function lerForma(usinaId: number, opcoes: OpcoesDeDados): FormaLida {
  let cru: string | null = null
  try {
    cru = localStorage.getItem(chaveDaForma(usinaId))
  } catch {
    // Armazenamento bloqueado (aba anônima, cookies de terceiros barrados): a tela abre no
    // padrão, que é sempre válido. Não poder LER uma preferência não pode custar a tela.
    return { forma: null, descartados: [] }
  }
  if (!cru) return { forma: null, descartados: [] }
  try {
    return reconciliar(JSON.parse(cru), opcoes)
  } catch {
    // JSON estragado pela metade — escrita interrompida, ou mão humana no console.
    return { forma: null, descartados: [] }
  }
}

/**
 * O que vai para o disco, campo a campo.
 *
 * Remontar em vez de serializar o que veio é a tranca do período: `Pedido` é `Selecao` mais
 * `inicio`/`fim`/`hora_*`/`passo`, então um espalhamento distraído (`{...pedido}`) gravaria as
 * datas sem que `tsc` tivesse o que reclamar — e a visita seguinte abriria apontada para o mês
 * errado. Aqui só entra o que está escrito abaixo.
 */
function corpoGuardavel(forma: FormaGuardada): Record<string, unknown> {
  const s = forma.selecao
  return {
    passo: forma.passo,
    horaInicio: forma.horaInicio,
    horaFim: forma.horaFim,
    ...(forma.pacote ? { pacote: forma.pacote } : {}),
    selecao: {
      inversores: s.inversores
        ? {
            variaveis: s.inversores.variaveis,
            agrupamento: s.inversores.agrupamento,
            series: s.inversores.series,
          }
        : null,
      estacao: s.estacao ? { variaveis: s.estacao.variaveis } : null,
      fronteira: s.fronteira
        ? { variaveis: s.fronteira.variaveis, agrupamento: s.fronteira.agrupamento }
        : null,
      sistema: s.sistema
        ? { variaveis: s.sistema.variaveis, agrupamento: s.sistema.agrupamento }
        : null,
    },
  }
}

/** Guarda a forma desta usina. Falhar aqui não é assunto do cliente. */
export function gravarForma(usinaId: number, forma: FormaGuardada): void {
  try {
    localStorage.setItem(chaveDaForma(usinaId), JSON.stringify(corpoGuardavel(forma)))
  } catch {
    // Cota estourada ou armazenamento bloqueado: guardar a preferência nunca pode derrubar
    // um download que já está pronto para sair.
  }
}
