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
  /** A câmera do meuGuarda que este ponto é (só nas câmeras ligadas). */
  mg_camera_id?: number | null
  /** A ligação com o equipamento do monitoramento (quando houver): é por ela que o estado pinta o objeto. A VAGA do
   *  inversor (trocar o inversor mantém o desenho), a entrada dele e o trafo. */
  slot_id?: number | null
  string_number?: number | null
  transformer_id?: number | null
}

export type Ligacao = { slot_id?: number | null; string_number?: number | null; transformer_id?: number | null }

/** A vaga de inversor da usina e as strings dela: a quem um desenho se liga. */
export type VagaDoMapa = { slot_id: number; rotulo: string; trafo: string | null; transformer_id?: number | null; strings: number[] }
export type LigacoesDoMapa = { vagas: VagaDoMapa[]; trafos: { transformer_id: number; nome: string }[]; trafos_aviso?: string | null }

/** O estado de um objeto, lido no monitoramento. Sem leitura não existe "normal" (regra "nunca enganar"). */
export type EstadoDoObjeto = {
  estado: 'ok' | 'alarme' | 'problema' | 'sem_dado'; motivo?: string | null; desde?: string | null
  /** De quando é o dado deste objeto (não a hora do cálculo). */
  leitura_em?: string | null
  /** O equipamento do monitoramento que ele é ("Inv 03 · S12"). */
  equipamento?: string | null
  /** O "já sei" da tela Leituras: a equipe já sabe (a cor não muda). */
  conhecido?: { nota?: string | null; por?: string | null; ate?: string | null } | null
}

export type MapaDoMeuPlano = {
  usina: { id: number; nome: string; latitude: number | null; longitude: number | null; area_poligono: number[][] | null }
  vinculado: boolean
  slug: string | null
  editar_url: string | null
  /** `url` nula: o voo está cadastrado, mas o armazenamento não entregou a imagem agora. */
  orto: { voo: string; url: string | null; bounds: [[number, number], [number, number]] } | null
  objetos: ObjetoDoMapa[]
  aviso: string | null
}

export type MapaOut = {
  /** `tv_codigo`: o mapa desta usina no TermoVision (o GS embute a tela dele, R6); nulo = sem mapa lá. */
  usina: { id: number; nome: string; tv_codigo?: string | null }
  pode_editar: boolean
  por_que_nao_edita: string | null
  /** Cada camada com a permissão do produto dela: `null` = edita; o texto = por que não. */
  edicao?: { monitoramento: string | null; manutencao: string | null }
  /** O estado de cada objeto por id; `null` = não lido (o porquê em `estado_aviso`). */
  estado?: { lido_em: string | null; dados_de?: string | null; dia?: string | null; objetos: Record<string, EstadoDoObjeto> } | null
  estado_aviso?: string | null
  /** O monitoramento já move, redesenha e liga desenho ao equipamento (veio junto com o estado). */
  mapa_completo?: boolean
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

export type Desenho = { type: 'Point' | 'LineString' | 'Polygon'; coordinates: unknown }

export async function desenharObjeto(usinaId: number, tipo: string, nome: string | null, geometria: Desenho) {
  const { data } = await api.post(`/api/v1/mapa/usinas/${usinaId}/objetos`, { tipo, nome, geometria }, { timeout: 60_000 })
  return data
}

export async function ligacoesDoMapa(usinaId: number): Promise<LigacoesDoMapa> {
  const { data } = await api.get<LigacoesDoMapa>(`/api/v1/mapa/usinas/${usinaId}/ligacoes`)
  return data
}

export async function alterarObjeto(usinaId: number, objetoId: number,
  campos: { tipo?: string; nome?: string; geometria?: Desenho } & Ligacao) {
  const { data } = await api.patch(`/api/v1/mapa/usinas/${usinaId}/objetos/${objetoId}`, campos, { timeout: 60_000 })
  return data
}

export async function apagarObjeto(usinaId: number, objetoId: number) {
  await api.delete(`/api/v1/mapa/usinas/${usinaId}/objetos/${objetoId}`, { timeout: 60_000 })
}

export async function usinasDoMapa(): Promise<UsinaDoMapa[]> {
  const { data } = await api.get<UsinaDoMapa[]>('/api/v1/mapa/usinas')
  return data
}
