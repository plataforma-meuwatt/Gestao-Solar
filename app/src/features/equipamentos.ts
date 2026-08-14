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
}

export type EquipamentosOut = {
  usina: string
  total: number | null
  parados: number | null
  alerta: number | null
  sem_dados: number | null
  ignorados: number | null
  /** Quando foi MEDIDO, não quando o servidor respondeu. */
  atualizado_em: string | null
  aviso: string | null
  equipamentos: Equipamento[]
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
