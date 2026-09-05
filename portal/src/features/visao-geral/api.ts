/**
 * O contrato da Visão geral — o espelho, em TypeScript, do `ResumoOut` do BFF
 * (`bff/app/api/v1/resumo.py`).
 *
 * A tela inteira sai de UMA leitura. No navegador, montar a carteira aqui seriam seis
 * chamadas por usina e cinco esqueletos chegando fora de ordem; o BFF compõe internamente,
 * reusando as MESMAS funções que respondem cada aba (energia, paradas, ordens, cronograma,
 * pendências), e por isso o número do topo é, por construção, o mesmo que a tela da usina
 * mostra depois.
 *
 * **Todo campo de número é `number | null`, e o `null` é informação.** Nulo é "não deu para
 * ler" ou "não existe medição"; zero é medição. Trocar um pelo outro faria "0 OS em
 * andamento" aparecer para uma usina cujo meuPlano está fora do ar — a leitura mais cara que
 * este portal pode induzir. Por isso não há um único valor padrão neste arquivo: os
 * formatadores de `lib/format` escrevem "—" e a tela não decide nada.
 */

import { useLeitura, type Leitura } from '@/lib/leitura'

/** A manutenção de UMA usina, até o mês de referência. */
export type ManutencaoDaUsina = {
  /** Σ das ocorrências previstas no contrato até o mês de referência. */
  previsto_ate_mes: number | null
  /** Células verdes — executado. */
  feitos: number | null
  /**
   * Dispensadas com motivo registrado. NUNCA se soma a `feitos`: "foi feito" e "foi
   * dispensado" são afirmações diferentes, e apagar a diferença era o risco que o meuPlano
   * recusou correr.
   */
  dispensados: number | null
  atrasados: number | null
  /** OS ainda pedindo algo de alguém — a mesma régua da aba Ordens. */
  os_em_andamento: number | null
}

export type UsinaResumo = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
  /** Um dos seis tons; a régua é do servidor. */
  tom: string
  situacao: string

  potencia_kw: number | null
  energia_mes_kwh: number | null
  /** A meta do projeto (PVsyst cadastrado no meuWatt). Sem cadastro, nulo — nunca 100%. */
  esperado_mes_kwh: number | null
  pct: number | null

  paradas_mes: number | null
  /** Nulo também quando alguma parada veio sem duração — somar só as que têm mentiria a menor. */
  tempo_parado_min: number | null

  manutencao: ManutencaoDaUsina | null
  pendencias_abertas: number | null

  /** Por que algum bloco desta usina veio nulo. Só falha real entra aqui. */
  aviso: string | null
}

export type ManutencaoResumo = {
  os_em_andamento: number | null
  os_concluidas_mes: number | null
  /** Nulo quando nenhuma usina tem cronograma consolidado — não é "zero atrasado". */
  atrasados_total: number | null
}

export type PendenciasResumo = {
  abertas: number
  prazo_vencido: number | null
  /** Das abertas, as que a equipe marcou como "cobrada pelo cliente" — as que ELE abriu. */
  cobradas_abertas: number | null
}

/** Uma faixa do topo. `rota` é o caminho do portal para onde o clique leva. */
export type AtencaoResumo = {
  tom: string
  titulo: string
  detalhe: string | null
  rota: string
}

export type ResumoOut = {
  /** `YYYY-MM` do mês pedido. */
  referencia_mes: string
  /** Instante do DADO (não o da resposta): é ele que a tela carimba no "atualizado às". */
  atualizado_em: string

  potencia_agora_kw: number | null
  energia_mes_kwh: number | null
  esperado_mes_kwh: number | null
  /** Só das usinas que têm energia E meta — as sem meta ficam fora dos dois lados da conta. */
  pct_do_esperado: number | null
  tom: string
  situacao: string

  usinas: UsinaResumo[]
  /** Quantas usinas trouxeram energia do mês — o "de N" dos totais. */
  usinas_com_dado: number

  manutencao: ManutencaoResumo | null
  pendencias: PendenciasResumo | null
  atencao: AtencaoResumo[]

  aviso: string | null
}

/**
 * Prazo próprio da carteira.
 *
 * O `/resumo` compõe energia, paradas, manutenção e pendências de TODAS as usinas da conta
 * numa resposta só — é a chamada mais pesada do portal e, ao mesmo tempo, a tela em que o
 * cliente cai depois de entrar. Com o prazo padrão de 30 s ela nunca chegava a renderizar
 * numa carteira de sete usinas: 30 s de esqueleto, a tentativa automática, mais 30 s e um
 * "a conexão demorou demais" aos 62 s — com o servidor respondendo 200 e completo do outro
 * lado. O BFF ficou bem mais rápido (passou a reaproveitar a conexão com os upstreams), mas
 * o teto próprio aqui é o que impede a tela de voltar a mentir quando a carteira crescer.
 */
const PRAZO_DA_CARTEIRA_MS = 120_000

/**
 * A leitura da carteira num mês, EM DUAS ONDAS.
 *
 * `referencia` é `YYYY-MM-DD` e entra na chave do cache: cada mês guarda o seu, então andar
 * para trás e voltar não repete a viagem, e o mês aberto ontem reabre na hora — com o selo de
 * offline em cima — quando a rede estiver fora.
 *
 * Por que duas: a chamada inteira levava 22 s contra os upstreams reais, e esta tela tinha um
 * esqueleto só — a PRIMEIRA tela do portal ficava perto de meio minuto cinza, enquanto todas
 * as outras respondiam entre 1 e 8 s. A energia (monitoramento) chega em segundos; é a
 * manutenção — cronograma, ordens e pendências de cada usina — que arrasta. Separadas, a
 * carteira aparece com a energia e as colunas de manutenção preenchem sozinhas depois.
 *
 * As duas leituras são a MESMA rota com recortes diferentes, então nenhum número muda de
 * origem: o que a segunda traz é exatamente o que a chamada única trazia.
 */
export function useResumo(referencia: string): Leitura<ResumoOut> {
  return useLeitura<ResumoOut>(`resumo?referencia=${referencia}&blocos=energia`, {
    prazoMs: PRAZO_DA_CARTEIRA_MS,
  })
}

/**
 * A segunda onda: cronograma, ordens e pendências. Enquanto ela não chega, as colunas de
 * manutenção mostram "—" com um aviso de que ainda estão carregando — nunca zero, que se
 * leria como "ninguém está trabalhando".
 */
export function useResumoManutencao(referencia: string): Leitura<ResumoOut> {
  return useLeitura<ResumoOut>(`resumo?referencia=${referencia}&blocos=manutencao`, {
    prazoMs: PRAZO_DA_CARTEIRA_MS,
  })
}
