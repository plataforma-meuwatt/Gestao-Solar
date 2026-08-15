/**
 * Manutenção — o histórico do que já foi feito, vindo do meuPlano.
 *
 * As outras telas olham para a frente: o que está em aberto, o que está agendado. Esta
 * olha para trás, que é como o dono confere se o contrato de O&M está sendo cumprido.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'

export type OrdemAtendida = {
  id: number | null
  usina: string
  /** O que o serviço era. O BFF já resolve entre `objetivo`, `name` e o título do container. */
  objetivo: string
  classificacao: string | null
  status: string | null
  fechada_em: string | null
  aprovada_em: string | null
  tecnico: string | null
  execucao_min: number | null
  tarefas: number | null
  tarefas_feitas: number | null
  resumo: string | null
}

export type ManutencaoOut = {
  /** Nulo = nenhuma usina respondeu. Zero é "nenhuma OS concluída", que é diferente. */
  total: number | null
  ordens: OrdemAtendida[]
  usinas_com_manutencao: number
  aviso: string | null
}

export function useManutencao(): Leitura<ManutencaoOut> {
  return fetchWithCache<ManutencaoOut>('manutencao')
}
