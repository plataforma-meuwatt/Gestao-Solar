/**
 * Mapa único — o contrato com o BFF (`bff/app/api/v1/mapa.py`).
 *
 * O dono (18/11/2026): "o mapa pode ser tipo gestao.solar/mapa/usina … todos usam o mesmo". Nada do mapa mora aqui nem
 * no BFF: o voo e a posição de cada equipamento são do mapa do meuWatt, e o meuPlano diz qual equipamento da árvore cada
 * objeto é (`node_id`). A tela só desenha o que veio, e marcar ou mover vai, como a pessoa, pela rota do meuPlano.
 */

import { api } from '@/lib/api'

export type Geometria = { type: 'Point' | 'LineString' | 'Polygon'; coordinates: unknown }

export type ObjetoDoMapa = {
  id: number
  tipo: string
  nome: string | null
  geometria: Geometria | null
  origem?: string | null
  /** O equipamento da árvore do meuPlano que este objeto é; nulo = só desenho. */
  node_id: number | null
  node_nome: string | null
  node_tipo: string | null
  ambiguo?: boolean
}

export type MapaDoMeuPlano = {
  usina: { id: number; nome: string; latitude: number | null; longitude: number | null; area_poligono: number[][] | null }
  vinculado: boolean
  slug: string | null
  editar_url: string | null
  orto: { voo: string; url: string; bounds: [[number, number], [number, number]] } | null
  objetos: ObjetoDoMapa[]
  aviso: string | null
}

export type MapaOut = {
  usina: { id: number; nome: string }
  pode_editar: boolean
  por_que_nao_edita: string | null
  /** Nulo quando não deu para ler (o motivo está em `aviso`). */
  mapa: MapaDoMeuPlano | null
  aviso: string | null
}

export type EquipamentoAchado = { node_id: number; nome: string; tipo?: string; tipo_rotulo?: string; local?: string | null }

export type UsinaDoMapa = { id: number; nome: string; mp_usina_id: number | null; mw_slug: string | null }

export const caminhoDoMapa = (usinaId: number) => `mapa/usinas/${usinaId}`

export async function buscarEquipamentos(usinaId: number, nome: string): Promise<EquipamentoAchado[]> {
  const { data } = await api.get<{ achados?: EquipamentoAchado[]; parecidos?: EquipamentoAchado[] }>(
    `/api/v1/mapa/usinas/${usinaId}/equipamentos`, { params: { nome } })
  return [...(data.achados ?? []), ...(data.parecidos ?? [])]
}

export async function marcarNoMapa(usinaId: number, nodeId: number, lat: number, lng: number): Promise<{ avisos?: string[] }> {
  const { data } = await api.post(`/api/v1/mapa/usinas/${usinaId}/ponto`, { node_id: nodeId, lat, lng }, { timeout: 60_000 })
  return data
}

export async function usinasDoMapa(): Promise<UsinaDoMapa[]> {
  const { data } = await api.get<UsinaDoMapa[]>('/api/v1/mapa/usinas')
  return data
}
