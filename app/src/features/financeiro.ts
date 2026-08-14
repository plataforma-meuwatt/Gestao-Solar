/**
 * Mensalidades, como o BFF as entrega.
 *
 * Este é o único módulo do app cujo dado não vem de upstream nenhum: assinatura de
 * produto não existe no meuWatt nem no meuPlano, e nasce no BFF. Contrato em
 * `docs/CONTRATO_API.md` § Financeiro.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'
import type { Tom } from '@/theme/tokens'

export type SituacaoFatura = 'pago' | 'a_vencer' | 'em_aberto' | 'vencido'

export type Fatura = {
  id: number
  produto: string
  produto_nome: string
  /** `YYYY-MM`. */
  competencia: string
  valor: number
  vencimento: string
  pago_em: string | null
  situacao: SituacaoFatura
  /** Já decidido pelo servidor — a tela não reimplementa a régua de cor. */
  tom: Tom
  dias_atraso: number | null
  comprovante_url: string | null
}

export type Assinatura = {
  id: number
  produto: string
  produto_nome: string
  fornece: string
  valor_mensal: number
  dia_vencimento: number
  ativo: boolean
  competencia_atual: Fatura | null
}

export type FinanceiroOut = {
  situacao: 'em_dia' | 'a_vencer' | 'vencido'
  tom: Tom
  resumo: string
  assinaturas: Assinatura[]
  historico: Fatura[]
  total_mensal: number
  total_vencido: number
  proximo_vencimento: string | null
  rodape: string
}

export function useFinanceiro(): Leitura<FinanceiroOut> {
  return fetchWithCache<FinanceiroOut>('billing')
}

/** `2026-08` → `agosto de 2026`. O servidor manda a competência crua, de propósito. */
export function competenciaPorExtenso(competencia: string): string {
  const [ano, mes] = competencia.split('-').map(Number)
  if (!ano || !mes) return competencia
  const nome = new Date(ano, mes - 1, 1).toLocaleDateString('pt-BR', { month: 'long' })
  return `${nome} de ${ano}`
}

/** `2026-09-05` → `05/09`. Data curta, para o card do topo. */
export function diaEMes(iso: string | null): string {
  if (!iso) return '—'
  const [, mes, dia] = iso.split('-')
  return dia && mes ? `${dia}/${mes}` : iso
}
