/**
 * O resumo da primeira tela, como o BFF o entrega.
 *
 * Cada campo aqui tem origem. Os que podem faltar são `| null` de propósito: quando o
 * número não existe, a tela **omite o bloco** em vez de preencher com algo plausível — foi
 * assim que esta tela passou meses anunciando 4.280 kW de três usinas que ninguém tinha.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'
import type { Tom } from '@/theme/tokens'

export type Atencao = {
  tom: Tom
  titulo: string
  detalhe: string | null
  /** Para onde o toque leva. Nulo quando o aviso não é de uma usina específica. */
  plant_id: number | null
}

export type ResumoFinanceiro = {
  situacao: 'em_dia' | 'a_vencer' | 'vencido'
  tom: Tom
  resumo: string
  proximo_vencimento: string | null
  total: number | null
}

export type InicioOut = {
  saudacao: string
  primeiro_nome: string
  atualizado_em: string

  potencia_agora_kw: number | null
  capacidade_total_kwp: number | null
  pct_capacidade: number | null
  energia_hoje_kwh: number | null

  usinas: number
  /** Quantas responderam. Menor que `usinas` significa número parcial, e a tela avisa. */
  usinas_com_dado: number

  atencao: Atencao | null
  financeiro: ResumoFinanceiro | null
  aviso: string | null
}

export function useInicio(): Leitura<InicioOut> {
  return fetchWithCache<InicioOut>('home')
}
