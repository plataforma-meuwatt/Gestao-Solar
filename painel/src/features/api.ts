/**
 * Tudo que o painel pede ao BFF, tipado num lugar só.
 *
 * Um arquivo em vez de um por tela: são vinte funções finas sobre o mesmo axios, e
 * espalhá-las esconderia o contrato, que é justamente o que precisa ficar visível.
 */

import { api } from '@/lib/api'

/* ------------------------------------------------------------------ tipos */

export type Produto = 'meuwatt' | 'meuplano'
export type SituacaoAcesso = 'nunca' | 'entregue' | 'usado'

export type ClienteResumo = {
  id: number
  nome: string
  apelido: string
  email: string | null
  empresa: string | null
  ativo: boolean
  usinas: number
  produtos: Produto[]
  acesso: SituacaoAcesso
}

export type Vinculo = {
  produto: Produto
  usuario_remoto_id: string
  email: string | null
  nome: string | null
  vinculado_em: string
}

export type UsinaDoCliente = {
  plant_link_id: number
  nome: string
  cidade: string | null
  uf: string | null
  tem_meuwatt: boolean
  tem_meuplano: boolean
}

export type ClienteDetalhe = {
  id: number
  nome: string
  apelido: string
  email: string | null
  empresa: string | null
  ativo: boolean
  acesso: SituacaoAcesso
  trocar_senha: boolean
  ultimo_login: string | null
  vinculos: Vinculo[]
  usinas: UsinaDoCliente[]
}

export type UsinaSugerida = {
  plant_link_id: number
  nome: string
  origem: string[]
  ja_concedida: boolean
  dono_atual: string | null
}

export type UsuarioRemoto = { id: string; email: string | null; nome: string | null }

export type Integracao = {
  produto: Produto
  configurada: boolean
  base_url: string | null
  usuario_servico: string | null
  estado: 'nunca' | 'ok' | 'falhou'
  detalhe: string | null
  testada_em: string | null
  usinas_visiveis: number | null
  /** `false` = conexão antiga, ainda por conta de serviço com senha. */
  por_token: boolean
  token_prefixo: string | null
  token_dono_nome: string | null
  token_dono_email: string | null
  token_gravado_em: string | null
}

export type ResultadoTeste = {
  ok: boolean
  detalhe: string
  usinas_visiveis: number | null
  dono_nome: string | null
  dono_email: string | null
}

export type EventoIntegracao = {
  evento:
    | 'token_gravado'
    | 'token_removido'
    | 'teste_ok'
    | 'teste_falhou'
    | 'senha_gravada'
    | 'sonda_ok'
    | 'sonda_falhou'
  ocorrido_em: string
  ator_email: string | null
  token_prefixo: string | null
  detalhe: string | null
  usinas_visiveis: number | null
}

export type UsinaLado = {
  id: string
  nome: string
  cidade: string | null
  uf: string | null
  kwp: number | null
}

export type Candidato = { mp_usina_id: number; nome: string; pontos: number; motivos: string[] }

/** De onde a usina vem. `meuplano` sozinho é normal: manutenção sem monitoramento. */
export type OrigemUsina = 'ambos' | 'meuwatt' | 'meuplano'

export type LinhaUsina = {
  chave: string
  nome: string
  /** Nulo = existe num produto e ainda não foi trazida para o Gestão Solar. */
  plant_link_id: number | null
  mw_slug: string | null
  mw_nome: string | null
  mp_usina_id: number | null
  mp_nome: string | null
  cidade: string | null
  uf: string | null
  kwp: number | null
  origem: OrigemUsina
  /** Existe aqui **e** está ligada. Só uma usina no app pode ser concedida a um cliente. */
  no_app: boolean
  /** Candidatas do meuPlano, para uma linha do meuWatt. */
  candidatos: Candidato[]
  /**
   * O caminho inverso: para uma usina só do meuPlano, de qual usina do meuWatt ela parece
   * ser par. As duas linhas continuam separadas de propósito — o sistema não sabe que são
   * a mesma —, mas o gestor não precisa cruzar os grupos a olho.
   */
  par_provavel_mw: string | null
  par_provavel_nome: string | null
  par_provavel_motivos: string[]
}

export type Conciliacao = {
  meuwatt: UsinaLado[]
  meuplano: UsinaLado[]
  linhas: LinhaUsina[]
  aviso: string | null
}

export type BlocoDiagnostico = { ok: boolean; detalhe: string; itens: Record<string, unknown>[] }

export type Diagnostico = {
  cliente: string
  usinas: UsinaDoCliente[]
  meuwatt: BlocoDiagnostico
  meuplano: BlocoDiagnostico
}

export type Membro = {
  id: number
  nome: string
  apelido: string
  email: string | null
  perfil: 'atendimento' | 'administrador'
  ativo: boolean
  ultimo_login: string | null
}

/* --------------------------------------------------------------- clientes */

export const listarClientes = () => api.get<ClienteResumo[]>('/clientes').then((r) => r.data)

export const obterCliente = (id: number) =>
  api.get<ClienteDetalhe>(`/clientes/${id}`).then((r) => r.data)

export const criarCliente = (dados: {
  nome: string
  apelido: string
  email?: string | null
  empresa?: string | null
}) =>
  api
    .post<{
      id: number
      nome: string
      apelido: string
      email: string | null
      senha_provisoria: string
    }>('/clientes', dados)
    .then((r) => r.data)

export const editarCliente = (
  id: number,
  dados: { nome?: string; empresa?: string | null; ativo?: boolean },
) => api.patch<ClienteResumo>(`/clientes/${id}`, dados).then((r) => r.data)

export const regenerarSenha = (id: number) =>
  api.post<{ senha_provisoria: string }>(`/clientes/${id}/senha`).then((r) => r.data)

/* --------------------------------------------------------------- vínculos */

export const procurarUsuario = (produto: Produto, email: string) =>
  api
    .get<UsuarioRemoto | null>(`/produtos/${produto}/usuarios`, { params: { email } })
    .then((r) => r.data)

export const vincular = (
  clienteId: number,
  produto: Produto,
  dados: { usuario_remoto_id: string; email?: string | null; nome?: string | null },
) => api.put<Vinculo>(`/clientes/${clienteId}/vinculos/${produto}`, dados).then((r) => r.data)

export const desvincular = (clienteId: number, produto: Produto) =>
  api.delete(`/clientes/${clienteId}/vinculos/${produto}`)

/* ----------------------------------------------------------------- usinas */

export const usinasSugeridas = (clienteId: number) =>
  api.get<UsinaSugerida[]>(`/clientes/${clienteId}/usinas-sugeridas`).then((r) => r.data)

export const definirUsinas = (clienteId: number, plant_link_ids: number[]) =>
  api.put(`/clientes/${clienteId}/usinas`, { plant_link_ids })

/* ------------------------------------------------------------- conciliação */

export const carregarConciliacao = () =>
  api.get<Conciliacao>('/conciliacao').then((r) => r.data)

/**
 * Grava o estado desejado de uma usina — casar, descasar e ligar/desligar no app são a
 * mesma operação vista de ângulos diferentes. Uma rota só evita que "trazer a usina do
 * meuPlano para o app" precise de duas chamadas, com a segunda podendo falhar sozinha.
 */
export const salvarUsina = (dados: {
  plant_link_id?: number | null
  mw_slug?: string | null
  mp_usina_id?: number | null
  nome: string
  cidade?: string | null
  uf?: string | null
  kwp?: number | null
  no_app?: boolean
}) => api.put<LinhaUsina>('/conciliacao/usina', dados).then((r) => r.data)

/** Tira a usina do Gestão Solar. Recusado enquanto algum cliente a tiver concedida. */
export const removerUsina = (plantLinkId: number) =>
  api.delete(`/conciliacao/usina/${plantLinkId}`)

/* ------------------------------------------------------------- integrações */

export const listarIntegracoes = () => api.get<Integracao[]>('/integracoes').then((r) => r.data)

export const salvarIntegracao = (
  produto: Produto,
  dados: { base_url: string; usuario_servico: string; senha?: string | null },
) => api.put<Integracao>(`/integracoes/${produto}`, dados).then((r) => r.data)

export const testarIntegracao = (produto: Produto) =>
  api.post<ResultadoTeste>(`/integracoes/${produto}/testar`).then((r) => r.data)

/** Cola o token e conecta. Se o token não servir, nada é gravado do lado do BFF —
 *  a resposta traz o motivo e a conexão anterior continua de pé. */
export const conectarPorToken = (produto: Produto, dados: { base_url: string; token: string }) =>
  api.put<ResultadoTeste>(`/integracoes/${produto}/token`, dados).then((r) => r.data)

export const desconectarToken = (produto: Produto) =>
  api.delete<Integracao>(`/integracoes/${produto}/token`).then((r) => r.data)

export const historicoIntegracao = (produto: Produto) =>
  api.get<EventoIntegracao[]>(`/integracoes/${produto}/eventos`).then((r) => r.data)

/* ------------------------------------------------------------------- sonda */

/**
 * `pendente` só existe no catálogo em repouso — é a rota que ainda não foi chamada nesta
 * sessão. Depois de sondar, toda rota está em um dos outros quatro estados.
 */
export type SituacaoRota = 'ok' | 'falhou' | 'pulada' | 'nao_sondada' | 'pendente'

export type RotaSondada = {
  chave: string
  metodo: string
  caminho: string
  /** O que esta rota sustenta do lado de cá — o que quebra no app se ela cair. */
  alimenta: string
  essencial: boolean
  situacao: SituacaoRota
  status: number | null
  ms: number | null
  detalhe: string | null
  itens: number | null
  campos: string[]
}

export type Varredura = {
  produto: Produto
  base_url: string | null
  ok: boolean
  detalhe: string
  executada_em: string
  rotas: RotaSondada[]
}

/** O catálogo, sem chamar nada. Abre instantâneo e vale mesmo com a ponte fora do ar. */
export const listarRotas = (produto: Produto) =>
  api.get<Varredura>(`/integracoes/${produto}/rotas`).then((r) => r.data)

/** Exercita o catálogo inteiro com o token gravado. Uma dúzia de chamadas ao produto. */
export const sondarRotas = (produto: Produto) =>
  api.post<Varredura>(`/integracoes/${produto}/rotas/sondar`).then((r) => r.data)

/* ------------------------------------------------------------ diagnóstico */

export const carregarDiagnostico = (clienteId: number) =>
  api.get<Diagnostico>(`/clientes/${clienteId}/diagnostico`).then((r) => r.data)

/* ----------------------------------------------------------------- equipe */

export const listarEquipe = () => api.get<Membro[]>('/equipe').then((r) => r.data)

export const criarMembro = (dados: {
  nome: string
  apelido: string
  email?: string | null
  perfil: 'atendimento' | 'administrador'
  senha: string
}) => api.post<Membro>('/equipe', dados).then((r) => r.data)

export const editarMembro = (
  id: number,
  dados: { perfil?: 'atendimento' | 'administrador'; ativo?: boolean },
) => api.patch<Membro>(`/equipe/${id}`, dados).then((r) => r.data)
