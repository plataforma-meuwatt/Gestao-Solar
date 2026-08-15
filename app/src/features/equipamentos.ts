/**
 * Os inversores de uma usina, como o BFF os entrega.
 *
 * O `id` é a **posição física** (`slot-12`), não o número de série: o serial muda quando o
 * aparelho é trocado, a posição não. É por isso que a rota de detalhe é endereçada por ele.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'
import type { Tom } from '@/theme/tokens'

export type Equipamento = {
  id: string
  nome: string
  serial: string | null
  modelo: string | null

  tom: Tom
  situacao: string

  /** Nulo = sem comunicação (travessão). Zero = está lá e não gera. */
  potencia_kw: number | null
  capacidade_kwp: number | null
  pct_capacidade: number | null
  energia_hoje_kwh: number | null
  temperatura_c: number | null

  parado_desde: string | null
  parado_ha_min: number | null

  /** Silenciado pelo operador no meuWatt — fora das contagens de problema. */
  ignorado: boolean

  /** O trafo/skid a que pertence. `null` = a usina não tem a estrutura cadastrada. */
  skid: string | null
  /** Afastamento da mediana dos irmãos, em %. Negativo = produzindo menos. */
  desvio_mediana_pct: number | null
}

/** Relé de proteção: as flags e as três fases. Nulo é travessão, nunca zero. */
export type ReleProtecao = {
  id: string
  nome: string
  modelo: string | null
  skid: string | null
  comunicando: boolean
  tensao_a: number | null
  tensao_b: number | null
  tensao_c: number | null
  corrente_a: number | null
  corrente_b: number | null
  corrente_c: number | null
  potencia_a: number | null
  potencia_b: number | null
  potencia_c: number | null
  potencia_total: number | null
  reativo_kvar: number | null
  frequencia_hz: number | null
  flags: string[]
  funcoes: string[]
  medido_em: string | null
}

/** Relé de temperatura: as bobinas e o ambiente, com a máxima que o aparelho registrou. */
export type ReleTemperatura = {
  id: string
  nome: string
  skid: string | null
  comunicando: boolean
  s1: number | null
  s2: number | null
  s3: number | null
  ambiente: number | null
  maxima_s1: number | null
  maxima_s2: number | null
  maxima_s3: number | null
  maxima_ambiente: number | null
  bobinas: Record<string, unknown>[]
  medido_em: string | null
}

export type EquipamentosOut = {
  usina: string
  total: number | null
  parados: number | null
  alerta: number | null
  sem_dados: number | null
  /** Fora da janela solar. Estado esperado — de madrugada é a usina inteira. */
  dormindo: number | null
  ignorados: number | null
  /** Quando foi MEDIDO, não quando o servidor respondeu. */
  atualizado_em: string | null
  aviso: string | null
  equipamentos: Equipamento[]
  reles_protecao: ReleProtecao[]
  reles_temperatura: ReleTemperatura[]
}

export type Entrada = { numero: number; tensao_v: number | null; corrente_a: number | null }

export type EquipamentoDetalhe = Equipamento & {
  usina: string
  plant_id: number
  fabricante_alerta: string | null
  causa_parada: string | null
  /** Tri-estado no meuWatt: nulo é "o detector não sabe", não "está bem". */
  em_falha: boolean | null
  performance_pct: number | null
  desvio_mediana: number | null
  medido_em: string | null
  transformador: string | null
  entradas: Entrada[]

  /**
   * Curva de potência do dia, em buckets de 5 min, vinda de `charts/intraday`.
   * Lista vazia = o monitoramento não devolveu leitura deste inversor hoje. Bucket em
   * que o aparelho não mediu NÃO está aqui — a lacuna é dado, e preenchê-la com zero
   * diria "estava gerando nada" quando a verdade é "não sabemos".
   */
  curva: { hora: string; kw: number }[]
  strings_a: (number | null)[]
  aviso: string | null
}

export function useEquipamentos(plantId: string | undefined): Leitura<EquipamentosOut> {
  return fetchWithCache<EquipamentosOut>(`plants/${plantId ?? ''}/equipamentos`, {
    ativo: Boolean(plantId),
  })
}

export function useEquipamento(
  plantId: string | undefined,
  equipamentoId: string | undefined,
): Leitura<EquipamentoDetalhe> {
  return fetchWithCache<EquipamentoDetalhe>(
    `plants/${plantId ?? ''}/equipamentos/${equipamentoId ?? ''}`,
    { ativo: Boolean(plantId && equipamentoId) },
  )
}

/**
 * Séries do dia de um equipamento — correntes de string, fases do relé, bobinas do trafo.
 *
 * `valores` vem alinhado a `horas`, com `null` onde o aparelho não mediu. O alinhamento é
 * o que permite ao gráfico interromper a linha na posição certa; encurtar a lista faria
 * as séries escorregarem no eixo.
 */
export type Serie = { rotulo: string; valores: (number | null)[] }

export type CurvaEquipamento = {
  dia: string
  horas: string[]
  series: Serie[]
  aviso: string | null
}

export function useCurvaStrings(
  usinaId: string | undefined,
  equipamentoId: string | undefined,
  dia: string,
  ativo: boolean,
): Leitura<CurvaEquipamento> {
  return fetchWithCache<CurvaEquipamento>(
    `plants/${usinaId ?? ''}/equipamentos/${equipamentoId ?? ''}/strings?dia=${dia}`,
    { ativo: Boolean(usinaId && equipamentoId) && ativo },
  )
}

export function useCurvaTemperatura(
  usinaId: string | undefined,
  sensorId: string,
  dia: string,
  ativo: boolean,
): Leitura<CurvaEquipamento> {
  return fetchWithCache<CurvaEquipamento>(
    `plants/${usinaId ?? ''}/reles/temperatura/${encodeURIComponent(sensorId)}/curva?dia=${dia}`,
    { ativo: Boolean(usinaId) && ativo },
  )
}

export function useCurvaProtecao(
  usinaId: string | undefined,
  releId: string,
  dia: string,
  grandeza: 'tensao' | 'corrente' | 'potencia',
  ativo: boolean,
): Leitura<CurvaEquipamento> {
  return fetchWithCache<CurvaEquipamento>(
    `plants/${usinaId ?? ''}/reles/protecao/${encodeURIComponent(releId)}/curva?dia=${dia}&grandeza=${grandeza}`,
    { ativo: Boolean(usinaId) && ativo },
  )
}

/** A máxima de cada dia num intervalo, para ver se a bobina vem esquentando. */
export type Maximas = {
  inicio: string
  fim: string
  dias: { dia: string; maxima: number | null }[]
  pico: number | null
  pico_em: string | null
  aviso: string | null
}

export function useMaximas(
  usinaId: string | undefined,
  sensorId: string,
  dias: number,
  ativo: boolean,
): Leitura<Maximas> {
  return fetchWithCache<Maximas>(
    `plants/${usinaId ?? ''}/reles/temperatura/${encodeURIComponent(sensorId)}/maximas?dias=${dias}`,
    { ativo: Boolean(usinaId) && ativo },
  )
}

/** Histórico de flags do relé de proteção, mais recente primeiro. */
export type EventoDeTrip = {
  quando: string | null
  codigo: string | null
  evento: string | null
  de: string | null
  para: string | null
}

export type HistoricoDeFlags = {
  rele: string | null
  eventos: EventoDeTrip[]
  aviso: string | null
}

export function useHistoricoDeFlags(
  usinaId: string | undefined,
  releId: string,
  ativo: boolean,
): Leitura<HistoricoDeFlags> {
  return fetchWithCache<HistoricoDeFlags>(
    `plants/${usinaId ?? ''}/reles/protecao/${encodeURIComponent(releId)}/flags`,
    { ativo: Boolean(usinaId) && ativo },
  )
}
