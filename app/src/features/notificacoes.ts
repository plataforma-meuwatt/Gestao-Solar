/**
 * O que está aberto nas usinas desta pessoa.
 *
 * Não é uma caixa de entrada: os dois produtos têm a sua, mas ambas são escopadas ao dono
 * do token, e o BFF usa um token de serviço — pedir "minhas notificações" traria a caixa
 * de outra pessoa. A lista é montada a partir dos fatos: alertas ativos, ordens em aberto
 * e mensalidades vencidas.
 *
 * Consequência assumida: **não há "marcar como lida"**, porque marcaria para quem gerou o
 * token. Enquanto for assim, a tela é um retrato do que está aberto agora.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'
import type { Tom } from '@/theme/tokens'

export type Notificacao = {
  id: string
  /** `acao` pede providência; `sistema` só informa. */
  grupo: 'acao' | 'sistema'
  tom: Tom
  titulo: string
  resumo: string
  em: string | null
  plant_id: number | null
  usina: string | null
}

export type NotificacoesOut = {
  notificacoes: Notificacao[]
  /** Quantas pedem providência — é o número da bolinha do avatar. */
  acoes: number
  aviso: string | null
}

export function useNotificacoes(): Leitura<NotificacoesOut> {
  return fetchWithCache<NotificacoesOut>('notifications')
}
