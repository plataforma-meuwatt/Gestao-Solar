/**
 * As usinas do dono, como o BFF as entrega.
 *
 * Os nomes de campo são os do servidor (`snake_case`), de propósito: renomear na fronteira
 * cria um segundo vocabulário para a mesma coisa, e é ele que faz alguém procurar
 * `capacidadeKwp` no `plants.py` e não achar. O contrato está em
 * `docs/CONTRATO_API.md` § Usinas.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'
import type { Tom } from '@/theme/tokens'

export type Usina = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
  capacidade_kwp: number | null

  /** Nulo é "sem comunicação", e a tela mostra travessão. Zero é "não gerou" — de noite,
   *  o esperado. Desenhar os dois igual é o erro que este campo existe para evitar. */
  potencia_kw: number | null
  energia_hoje_kwh: number | null
  disponibilidade_pct: number | null
  pct_capacidade: number | null

  /** Chave de `tons`, decidida pelo servidor: a regra de cor não é da tela. */
  tom: Tom
  situacao: string

  tem_meuwatt: boolean
  tem_meuplano: boolean
  aviso: string | null
}

export type UsinasOut = {
  usinas: Usina[]
  total_kwp: number
  potencia_agora_kw: number | null
  energia_hoje_kwh: number | null
  atualizado_em: string
  aviso: string | null
}

export type UsinaDetalhe = Usina & {
  /** Do meuPlano. Nulo = não deu para consultar; zero = não há ordem aberta. */
  ordens_abertas: number | null
  ordens_recentes: string[]

  /** Do meuWatt. Mesma regra: nulo é "não sabemos", não "nenhum". */
  inversores: number | null
  inversores_parados: number | null
  alertas_ativos: number | null
}

export function useUsinas(): Leitura<UsinasOut> {
  return fetchWithCache<UsinasOut>('plants')
}

export function useUsina(id: string | undefined): Leitura<UsinaDetalhe> {
  // Cada usina tem seu próprio cache — a chave entra no nome do arquivo. Sem `id` a
  // consulta fica desligada, senão a rota viraria `/plants/undefined`.
  return fetchWithCache<UsinaDetalhe>(`plants/${id ?? ''}`, { ativo: Boolean(id) })
}
