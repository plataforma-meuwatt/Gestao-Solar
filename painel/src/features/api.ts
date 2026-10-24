/**
 * Tudo que o painel pede ao BFF, tipado num lugar só.
 *
 * Um arquivo em vez de um por tela: são vinte funções finas sobre o mesmo axios, e
 * espalhá-las esconderia o contrato, que é justamente o que precisa ficar visível.
 */

import axios from 'axios'

import { api, apiEmpresa, apiTecnico, aplicarInterceptores, baseDaApi } from '@/lib/api'

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

/**
 * A conta do cliente num produto, e o estado da conexão com ela.
 *
 * `nome` e `email` não foram digitados por ninguém: são o que o produto respondeu quando
 * o token foi apresentado. É por isso que um token colado na ficha da pessoa errada
 * aparece na hora — a tela mostra o nome de quem o token realmente é.
 */
export type Vinculo = {
  produto: Produto
  usuario_remoto_id: string
  email: string | null
  nome: string | null
  vinculado_em: string
  /** A pessoa colou o token DELA (o adm vê só o fato: não tem token, nem o prefixo). */
  tem_token: boolean
  token_gravado_em: string | null
  estado: 'nunca' | 'ok' | 'falhou'
  detalhe: string | null
  usinas_visiveis: number | null
  /** O produto aceita "Entrar com Gestão Solar" para esta conta. */
  login_externo: boolean
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


export type BlocoDiagnostico = { ok: boolean; detalhe: string; itens: Record<string, unknown>[] }

export type Diagnostico = {
  cliente: string
  usinas: UsinaDoCliente[]
  meuwatt: BlocoDiagnostico
  meuplano: BlocoDiagnostico
  /** O que o cliente vai encontrar na aba Cronograma do portal. Opcional enquanto uma
   *  aba antiga do painel conversa com a API nova: sem ele a tela só omite o bloco. */
  manutencao?: BlocoDiagnostico
}

export type Perfil = 'atendimento' | 'administrador'

/** Uma pessoa do staff: quem entra no painel com apelido e senha. */
export type Membro = {
  id: number
  nome: string
  apelido: string
  email: string | null
  perfil: Perfil
  ativo: boolean
  ultimo_login: string | null
  /** O que está GRAVADO. Administrador vem com a lista vazia e abre tudo pelo perfil —
   *  a tela desenha as caixinhas dele marcadas e desligadas, em vez de fingir que dá
   *  para desmarcar. */
  areas: string[]
}

/** Uma tela do painel que se concede a alguém. O catálogo vem do BFF. */
export type Area = {
  chave: string
  rotulo: string
  descricao: string
  /** `Operação` ou `Sistema` — o mesmo agrupamento do menu. */
  grupo: string
}

/** Quem sou eu e o que abro AGORA — o acesso muda no meio da sessão de 8 horas. */
export type Eu = {
  nome: string
  apelido: string
  perfil: Perfil
  areas: string[]
}

/* --------------------------------------------------------------- clientes */

export const listarClientes = () => api.get<ClienteResumo[]>('/clientes').then((r) => r.data)

export const obterCliente = (id: number) =>
  api.get<ClienteDetalhe>(`/clientes/${id}`).then((r) => r.data)

export const editarCliente = (id: number, dados: { nome?: string; ativo?: boolean }) => api.patch<ClienteResumo>(`/clientes/${id}`, dados).then((r) => r.data)

export const regenerarSenha = (id: number) =>
  api.post<{ senha_provisoria: string }>(`/clientes/${id}/senha`).then((r) => r.data)

/* ----------------------------------------------------------------- usinas */

export const usinasSugeridas = (clienteId: number) =>
  api.get<UsinaSugerida[]>(`/clientes/${clienteId}/usinas-sugeridas`).then((r) => r.data)

export const definirUsinas = (clienteId: number, plant_link_ids: number[]) =>
  api.put(`/clientes/${clienteId}/usinas`, { plant_link_ids })

/* ------------------------------------------------------------ permissões */

/**
 * O que o cliente pode receber no aplicativo.
 *
 * A rota devolve o CATÁLOGO inteiro com `concedida` marcada, e não só o concedido: é o
 * que permite desenhar as chaves desligadas. Uma lista só do concedido não teria como
 * mostrar o que ainda falta conceder.
 */
export type PermissaoDoCliente = {
  categoria: string
  categoria_rotulo: string
  subcategoria: string
  rotulo: string
  descricao: string
  concedida: boolean | null
}

export const permissoesDoCliente = (clienteId: number) =>
  api.get<PermissaoDoCliente[]>(`/clientes/${clienteId}/permissoes`).then((r) => r.data)

/** Substituição, não acréscimo: manda a lista COMPLETA de `categoria.subcategoria`. */
export const definirPermissoes = (clienteId: number, permissoes: string[]) =>
  api.put(`/clientes/${clienteId}/permissoes`, { permissoes })

/* ------------------------------------------- administração do WhatsApp */

/**
 * As credenciais da Meta, cadastradas na tela e guardadas pelo gateway.
 *
 * O BFF não guarda nada disso: ele repassa ao gateway, que cifra. Nenhum segredo volta por
 * estas rotas — o que chega é o prefixo do token, o estado e a data do último teste.
 */
export type CredenciaisWhatsapp = {
  configurada: boolean
  envio_pronto: boolean
  webhook_pronto: boolean
  phone_number_id?: string | null
  waba_id?: string | null
  app_id?: string | null
  /** A configuração do Embedded Signup — abre a janela da Meta para cada técnico. */
  es_config_id?: string | null
  numero_exibicao?: string | null
  token_prefixo?: string | null
  token_gravado_em?: string | null
  estado: string
  detalhe?: string | null
  testada_em?: string | null
  atualizada_em?: string | null
  atualizada_por?: string | null
  cifragem_disponivel: boolean
  /** O endereço a cadastrar no webhook da Meta. Vem do servidor: a tela não o monta. */
  webhook_url?: string | null
}

export type ResultadoWhatsapp = { ok: boolean; detalhe: string }

export type EventoWhatsapp = {
  evento: string
  ocorrido_em: string
  ator?: string | null
  token_prefixo?: string | null
  detalhe?: string | null
}

export const credenciaisWhatsapp = () =>
  api.get<CredenciaisWhatsapp>('/whatsapp').then((r) => r.data)

/** Campo de segredo vazio significa "não mexer": quem só corrigiu o WABA não tem o token. */
export const salvarCredenciaisWhatsapp = (dados: {
  phone_number_id: string
  waba_id?: string | null
  app_id?: string | null
  es_config_id?: string | null
  token?: string | null
  app_secret?: string | null
  verify_token?: string | null
}) => api.put<ResultadoWhatsapp>('/whatsapp', dados).then((r) => r.data)

export const testarCredenciaisWhatsapp = () =>
  api.post<ResultadoWhatsapp>('/whatsapp/testar').then((r) => r.data)

export const removerCredenciaisWhatsapp = () => api.delete('/whatsapp')

export const eventosWhatsapp = (limite = 30) =>
  api.get<EventoWhatsapp[]>('/whatsapp/eventos', { params: { limite } }).then((r) => r.data)

/** Um número da conta da Meta, como ela o descreve. */
export type NumeroWhatsapp = {
  id: string
  numero: string | null
  nome: string | null
  qualidade: string | null
  verificado: string | null
}

/** Um modelo de mensagem. `parametros` é quantos `{{n}}` o corpo espera. */
export type TemplateWhatsapp = {
  nome: string
  situacao: string
  categoria: string | null
  idioma: string | null
  corpo: string | null
  parametros: number
}

export const numerosWhatsapp = () =>
  api.get<NumeroWhatsapp[]>('/whatsapp/numeros').then((r) => r.data)

export const templatesWhatsapp = () =>
  api.get<TemplateWhatsapp[]>('/whatsapp/templates').then((r) => r.data)

export const enviarTesteWhatsapp = (dados: {
  telefone: string
  template: string
  parametros: string[]
}) =>
  api
    .post<{ ok: boolean; wamid: string | null; status: string; erro: string | null }>(
      '/whatsapp/enviar-teste',
      dados,
    )
    .then((r) => r.data)

/* ------------------------------------------------- central de notificações */

/**
 * O que o cliente recebe no WhatsApp, e de quais usinas.
 *
 * A matriz vem inteira — todo tipo × toda usina dele —, e não só o que está marcado: uma
 * lista do marcado não teria como desenhar o que falta marcar. O `contato` responde a outra
 * metade da pergunta, a que costuma ser esquecida: mesmo com tudo marcado, sem telefone e
 * sem aceite não sai nada.
 */
export type UsinaMarcada = {
  plant_link_id: number
  nome: string
  marcada: boolean
}

export type TipoDeNotificacao = {
  tipo: string
  rotulo: string
  descricao: string
  /** De qual produto vem o gatilho: meuWatt ou meuPlano. */
  origem: string
  usinas: UsinaMarcada[]
}

export type ContatoWhatsapp = {
  telefone: string | null
  telefone_exibicao: string | null
  e_celular: boolean
  aceite_em: string | null
  aceite_por: string | null
  apto: boolean
  /** A frase do que falta resolver. `null` quando está apto. */
  impedimento: string | null
}

export type CentralDeNotificacoes = {
  cliente: string
  contato: ContatoWhatsapp
  tipos: TipoDeNotificacao[]
  marcados: number
  sem_usinas: boolean
}

export type EnvioDeNotificacao = {
  tipo: string
  tipo_rotulo: string
  usina: string | null
  destino: string | null
  status: string
  erro: string | null
  criada_em: string
}

export const centralDeNotificacoes = (clienteId: number) =>
  api.get<CentralDeNotificacoes>(`/clientes/${clienteId}/notificacoes`).then((r) => r.data)

/** Telefone em texto livre — quem normaliza é o servidor, num lugar só. */
export const salvarContatoWhatsapp = (
  clienteId: number,
  dados: { telefone?: string | null; aceite?: boolean },
) =>
  api
    .patch<ContatoWhatsapp>(`/clientes/${clienteId}/notificacoes/contato`, dados)
    .then((r) => r.data)

/** Substituição: manda a matriz inteira, do jeito que ela deve ficar. */
export const definirNotificacoes = (
  clienteId: number,
  itens: { tipo: string; plant_link_id: number }[],
) => api.put(`/clientes/${clienteId}/notificacoes`, { itens })

export const historicoDeNotificacoes = (clienteId: number) =>
  api
    .get<EnvioDeNotificacao[]>(`/clientes/${clienteId}/notificacoes/historico`)
    .then((r) => r.data)

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

/** Exercita o catálogo inteiro com a conexão DA EMPRESA escolhida (a plataforma não tem
 *  token). Uma dúzia de chamadas ao produto. */
export const sondarRotas = (produto: Produto, empresaId: number) =>
  api
    .post<Varredura>(`/integracoes/${produto}/rotas/sondar`, null, { params: { empresa_id: empresaId } })
    .then((r) => r.data)

/* ------------------------------------------------------------ diagnóstico */

export const carregarDiagnostico = (clienteId: number) =>
  api.get<Diagnostico>(`/clientes/${clienteId}/diagnostico`).then((r) => r.data)

/* ---------------------------------------------- usuários do sistema (staff) */

export const meuAcesso = () => api.get<Eu>('/eu').then((r) => r.data)

export const catalogoDeAreas = () => api.get<Area[]>('/areas').then((r) => r.data)

export const listarUsuarios = () => api.get<Membro[]>('/usuarios').then((r) => r.data)

export const criarUsuario = (dados: {
  nome: string
  apelido: string
  email?: string | null
  perfil: Perfil
  senha: string
  areas: string[]
}) => api.post<Membro>('/usuarios', dados).then((r) => r.data)

/** `areas` é a lista COMPLETA: o que não vier é revogado. Omitir não mexe em acesso. */
export const editarUsuario = (
  id: number,
  dados: { perfil?: Perfil; ativo?: boolean; areas?: string[] },
) => api.patch<Membro>(`/usuarios/${id}`, dados).then((r) => r.data)

/** O administrador define a senha nova. Não é a provisória do cliente: o staff não tem
 *  tela de troca, então o que for definido aqui é a senha dele. */
export const redefinirSenhaUsuario = (id: number, senha: string) =>
  api.put<void>(`/usuarios/${id}/senha`, { senha }).then(() => undefined)

/* --------------------------------------------------- empresas (a plataforma) */

export type Empresa = {
  id: number
  nome: string
  documento: string | null
  ativa: boolean
  /** Quem é da empresa (de origem ou também dela), e por papel. */
  usuarios: number
  gerentes: number
  tecnicos: number
  donos: number
  usinas: number
  /** Para qual empresa de cada produto esta linha aponta. Sem nenhum dos dois, ela é
   *  fantasma: aparece na lista e todas as telas dela vêm vazias. */
  mw_enterprise_id: number | null
  mp_tenant_id: number | null
  /** O estado da conta DA EMPRESA em cada produto (`ok` · `falhou` · `nunca`); nulo = o
   *  gerente ainda não conectou. Só o estado — o token é dela. */
  conexao_meuwatt: string | null
  conexao_meuplano: string | null
}

export const listarEmpresas = () => api.get<Empresa[]>('/empresas').then((r) => r.data)

/** Todas as usinas do sistema, com a empresa dona — o inventário do adm (só leitura: trazer
 *  e casar usina é do gerente, no oem-gs). */
export type UsinaDaPlataforma = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
  kwp: number | null
  tem_meuwatt: boolean
  tem_meuplano: boolean
  dono_id: number | null
  dono_nome: string | null
  empresa_id: number | null
  empresa: string | null
  no_app: boolean
}

export const usinasDaPlataforma = () => api.get<UsinaDaPlataforma[]>('/usinas').then((r) => r.data)

export const obterEmpresa = (id: number) => api.get<Empresa>(`/empresas/${id}`).then((r) => r.data)

export const criarEmpresa = (dados: { nome: string; documento?: string | null }) =>
  api.post<Empresa>('/empresas', dados).then((r) => r.data)

export const editarEmpresa = (
  id: number,
  dados: { nome?: string; documento?: string | null; ativa?: boolean },
) => api.patch<Empresa>(`/empresas/${id}`, dados).then((r) => r.data)

/* ------------------------------------------ o portão do gerente da empresa */

/**
 * As chamadas do OUTRO portão, e por isso no outro cliente (`apiEmpresa`).
 *
 * Nenhuma delas manda `empresa_id`: o recorte sai da sessão, no servidor. Um parâmetro de
 * empresa aqui seria a porta para ler a carteira do concorrente trocando um número.
 */

export type EuNaEmpresa = {
  nome: string
  apelido: string
  empresa: string
  empresa_id: number
}

export type UsinaDaEmpresa = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
  kwp: number | null
  ativo: boolean
  clientes: number
}

export type ClienteDaEmpresa = {
  id: number
  nome: string
  apelido: string
  email: string | null
  ativo: boolean
  usinas: number
}

export type UsuarioDaEmpresa = {
  id: number
  nome: string
  apelido: string
  perfil: string
  ativo: boolean
}

export const euNaEmpresa = () => apiEmpresa.get<EuNaEmpresa>('/eu').then((r) => r.data)

export const usinasDaEmpresa = () =>
  apiEmpresa.get<UsinaDaEmpresa[]>('/usinas').then((r) => r.data)

export const clientesDaEmpresa = () =>
  apiEmpresa.get<ClienteDaEmpresa[]>('/clientes').then((r) => r.data)

export const usuariosDaEmpresa = () =>
  apiEmpresa.get<UsuarioDaEmpresa[]>('/usuarios').then((r) => r.data)

export type ItemDaCarteira = {
  id: number
  nome: string
  detalhe: string | null
  empresa_id: number | null
  empresa_nome: string | null
}

export type Carteira = { usinas: ItemDaCarteira[]; clientes: ItemDaCarteira[] }

export const carteiraDaEmpresa = (id: number) =>
  api.get<Carteira>(`/empresas/${id}/carteira`).then((r) => r.data)

/** As listas COMPLETAS: o que sair delas fica sem dono. Sem `clientes`, as contas ficam
 *  como estão (usuário se põe e se tira pela lista de usuários da empresa). */
export const salvarCarteira = (id: number, dados: { usinas: number[]; clientes?: number[] }) =>
  api.put<Carteira>(`/empresas/${id}/carteira`, dados).then((r) => r.data)

export type ConexaoDaEmpresa = {
  produto: Produto
  configurada: boolean
  base_url: string | null
  estado: string
  detalhe: string | null
  testada_em: string | null
  usinas_visiveis: number | null
  token_prefixo: string | null
  token_dono_nome: string | null
  token_dono_email: string | null
  token_gravado_em: string | null
  /** `false` = quem responde por este produto ainda é a credencial da PLATAFORMA. */
  propria: boolean
}

export type TesteDaConexao = {
  ok: boolean
  detalhe: string
  usinas_visiveis: number | null
  dono_nome: string | null
  dono_email: string | null
}

export const conexoesDaEmpresa = () =>
  apiEmpresa.get<ConexaoDaEmpresa[]>('/conexoes').then((r) => r.data)

export const conectarEmpresa = (produto: Produto, dados: { base_url: string; token: string }) =>
  apiEmpresa.put<TesteDaConexao>(`/conexoes/${produto}/token`, dados).then((r) => r.data)

export const desconectarEmpresa = (produto: Produto) =>
  apiEmpresa.delete<void>(`/conexoes/${produto}/token`).then(() => undefined)

export type GerenteCriado = {
  id: number
  nome: string
  apelido: string
  senha: string
  /** A conta nova ficou no seu grupo de papéis — "Trocar papel" já a mostra. */
  agrupada: boolean
}

/** A senha aparece UMA vez. Não é guardada em texto: quem perder, redefine. */
export const criarGerente = (
  empresaId: number,
  dados: { nome: string; apelido: string; email?: string | null; minha?: boolean },
) => api.post<GerenteCriado>(`/empresas/${empresaId}/gerente`, dados).then((r) => r.data)

export type EmpresaDoProduto = {
  id: number
  nome: string
  documento: string | null
  usinas: number | null
  pessoas: number | null
  escolhida: boolean
}

export type CatalogoDeEmpresas = {
  meuwatt: EmpresaDoProduto[]
  meuplano: EmpresaDoProduto[]
  mw_enterprise_id: number | null
  mp_tenant_id: number | null
  avisos: string[]
}

/**
 * O catálogo e o vínculo vivem no portão da EMPRESA, não no do painel.
 *
 * Quem casa a empresa é quem tem o token, e isso é o gerente: a plataforma cadastra a
 * empresa e o usuário dela, e não tem credencial no meuWatt nem no meuPlano. Montar a
 * lista com a credencial de serviço mostraria a carteira de quem a gerou — que não é a do
 * inquilino.
 */
export const catalogoDeVinculos = () =>
  apiEmpresa.get<CatalogoDeEmpresas>('/vinculos/catalogo').then((r) => r.data)

/** Campo ausente mantém o vínculo; `null` explícito descasa. */
export const salvarVinculos = (dados: {
  mw_enterprise_id?: number | null
  mp_tenant_id?: number | null
}) =>
  apiEmpresa
    .put<{ mw_enterprise_id: number | null; mp_tenant_id: number | null }>('/vinculos', dados)
    .then((r) => r.data)

/* ------------------------------------------------ os papéis de uma pessoa */

export type Papel = {
  apelido: string
  nome: string
  escopo: 'painel' | 'empresa' | 'cliente'
  perfil: string
  empresa: string | null
  atual: boolean
  /** Trocar para este papel exige a senha dele — vale para as contas da plataforma. */
  exige_senha: boolean
}

export type TrocaDePapel = {
  token: string
  expira_em: string
  apelido: string
  nome: string
  escopo: 'painel' | 'empresa' | 'cliente'
  perfil: string
  empresa: string | null
}

/** A rota atravessa os três portões, então mora fora do prefixo do painel. */
const sessao = axios.create({ baseURL: `${baseDaApi()}/api/sessao`, timeout: 30000 })
aplicarInterceptores(sessao)

export const meusPapeis = () => sessao.get<Papel[]>('/papeis').then((r) => r.data)

export const trocarDePapel = (apelido: string, senha?: string) =>
  sessao.post<TrocaDePapel>('/trocar', { apelido, senha: senha ?? null }).then((r) => r.data)

/* ------------------------------------------- agrupar contas (administrador) */

export type ContaParaAgrupar = {
  id: number
  apelido: string
  nome: string
  perfil: string
  empresa: string | null
  pessoa_id: number | null
  pessoa_nome: string | null
}

export const contasParaAgrupar = () =>
  api.get<ContaParaAgrupar[]>('/pessoas/contas').then((r) => r.data)

export const agruparContas = (dados: { nome: string; apelidos: string[] }) =>
  api.post<{ id: number; nome: string; contas: string[] }>('/pessoas', dados).then((r) => r.data)

export const desagruparConta = (apelido: string) =>
  api.delete<void>(`/pessoas/${apelido}`).then(() => undefined)

/** O que o gerente liberou no assistente, por produto. */
export type ProdutoDoBot = 'bot_meuplano' | 'bot_meuwatt' | 'bot_helper'

/** Uma conta como a PLATAFORMA a vê: papel, empresas, celular, bot e se a pessoa tem o
 *  token dela — nunca o token. */
export type UsuarioDaEmpresaAdmin = {
  id: number
  nome: string
  apelido: string
  perfil: string
  ativo: boolean
  email: string | null
  ultimo_login: string | null
  telefone: string | null
  /** Usinas concedidas (as desta empresa, na lista de uma empresa). */
  usinas: number
  /** Liberado pelo gerente, e o que responde de fato (liberado E com o token dela). */
  bot: ProdutoDoBot[]
  bot_ativo: ProdutoDoBot[]
  /** Produtos em que a pessoa tem o token DELA. */
  tokens: Produto[]
  /** A empresa que cuida da conta, quando não é a desta lista. */
  cuidada_por: string | null
  outras_empresas: string[]
  /** Está no MEU grupo de papéis — é a que aparece em "Trocar papel". */
  minha: boolean
}

export const usuariosDaEmpresaAdmin = (empresaId: number) =>
  api.get<UsuarioDaEmpresaAdmin[]>(`/empresas/${empresaId}/usuarios`).then((r) => r.data)

export type PapelNaEmpresa = 'cliente' | 'gestor_empresa' | 'tecnico'

export const editarUsuarioDaEmpresa = (
  empresaId: number,
  usuarioId: number,
  dados: { ativo?: boolean; senha?: string; perfil?: PapelNaEmpresa },
) =>
  api
    .patch<UsuarioDaEmpresaAdmin>(`/empresas/${empresaId}/usuarios/${usuarioId}`, dados)
    .then((r) => r.data)

/** A senha provisória aparece UMA vez — entregue com o apelido, que é o que autentica. */
export const criarUsuarioDaEmpresa = (
  empresaId: number,
  dados: { nome: string; apelido: string; email?: string | null; perfil: PapelNaEmpresa },
) =>
  api
    .post<{ id: number; nome: string; apelido: string; senha: string }>(
      `/empresas/${empresaId}/usuarios`,
      dados,
    )
    .then((r) => r.data)

/** Põe uma conta que JÁ EXISTE nesta empresa, sem tirar das outras. */
export const porUsuarioNaEmpresa = (empresaId: number, usuarioId: number) =>
  api.put<UsuarioDaEmpresaAdmin>(`/empresas/${empresaId}/usuarios/${usuarioId}`).then((r) => r.data)

/** Tira a conta desta empresa (e as usinas que ela recebia daqui). A conta continua existindo. */
export const tirarUsuarioDaEmpresa = (empresaId: number, usuarioId: number) =>
  api.delete<void>(`/empresas/${empresaId}/usuarios/${usuarioId}`).then(() => undefined)

/* ------------------------------------------ todos os usuários (o inverso de Empresas) */

export type EmpresaDaConta = { id: number; nome: string; origem: boolean }

export type Conta = UsuarioDaEmpresaAdmin & {
  da_plataforma: boolean
  areas: string[]
  /** A de origem primeiro. Vazio numa conta que não é da plataforma = sem empresa. */
  empresas: EmpresaDaConta[]
}

export const todasAsContas = () => api.get<Conta[]>('/contas').then((r) => r.data)

/** Renova a senha / desativa uma conta de EMPRESA (a da plataforma usa `/usuarios`). */
export const editarConta = (id: number, dados: { ativo?: boolean; senha?: string }) =>
  api.patch<Conta>(`/contas/${id}`, dados).then((r) => r.data)

/* ------------------------------------------------------------- log do bot */

export type RegistroBot = {
  id: number
  em: string
  telefone: string
  usuario_id: number | null
  usuario: string | null
  apelido: string | null
  empresa: string | null
  resultado: 'respondeu' | 'sem_conta' | 'nao_liberado' | 'sem_texto' | 'zerou' | 'erro'
  ferramentas: string[]
  pergunta: string | null
  resposta: string | null
  duracao_ms: number | null
  erro: string | null
}

export const logDoBot = (filtro: { empresa_id?: number; usuario_id?: number; resultado?: string } = {}) =>
  api.get<RegistroBot[]>('/whatsapp/bot/registros', { params: filtro }).then((r) => r.data)

/** O mesmo log, no oem-gs: só as pessoas que a empresa da sessão cuida. */
export const logDoBotDaEmpresa = () =>
  apiEmpresa.get<RegistroBot[]>('/bot/registros').then((r) => r.data)

/* ------------------------------------------------ um usuário em mais de uma empresa */

export type EmpresaDaSessao = { id: number; nome: string; ativa: boolean; origem: boolean; atual: boolean }

export const minhasEmpresas = () => sessao.get<EmpresaDaSessao[]>('/empresas').then((r) => r.data)

export const trocarDeEmpresa = (empresaId: number) =>
  sessao.post<TrocaDePapel>('/empresa', { empresa_id: empresaId }).then((r) => r.data)

/** Trocar a PRÓPRIA senha — vale para os três portões, por isso fora do prefixo do painel. */
export const trocarMinhaSenha = (dados: { senha_atual: string; senha_nova: string }) =>
  sessao.post<void>('/senha', dados).then(() => undefined)

/* ------------------------------- o gerente opera a empresa dele (com o token) */

export type CandidataDeUsina = { mp_usina_id: number; nome: string; motivos: string[] }

export type LinhaDeUsina = {
  chave: string
  nome: string
  plant_link_id: number | null
  mw_slug: string | null
  mp_usina_id: number | null
  cidade: string | null
  uf: string | null
  kwp: number | null
  origem: 'ambos' | 'meuwatt' | 'meuplano' | 'micro'
  no_app: boolean
  mw_micro_plant_id: number | null
  par_provavel_mw: string | null
  par_provavel_nome: string | null
  /** As candidatas do meuPlano, da mais provável para a menos. */
  candidatos: CandidataDeUsina[]
}

export type CatalogoDeUsinas = {
  linhas: LinhaDeUsina[]
  /** Quantas a empresa escolheu não ver. */
  ocultas: number
  /** Todas as do meuPlano, para casar à mão quando a sugestão não serve. */
  usinas_do_meuplano: { id: number; nome: string }[]
  avisos: string[]
}

export const catalogoDeUsinas = () =>
  apiEmpresa.get<CatalogoDeUsinas>('/usinas/catalogo').then((r) => r.data)

export const salvarUsinaDaEmpresa = (dados: {
  plant_link_id?: number | null
  mw_slug?: string | null
  mp_usina_id?: number | null
  mw_micro_plant_id?: number | null
  nome: string
  cidade?: string | null
  uf?: string | null
  kwp?: number | null
  no_app?: boolean
}) => apiEmpresa.put<LinhaDeUsina>('/usinas', dados).then((r) => r.data)

export const criarClienteDaEmpresa = (dados: {
  nome: string
  apelido: string
  email?: string | null
  /** `cliente` (dono de usina), `gestor_empresa` ou `tecnico`. Os papéis de uma empresa. */
  perfil?: 'cliente' | 'gestor_empresa' | 'tecnico'
  telefone?: string | null
  /** Puxar do meuPlano: a pessoa de lá a que a conta nasce ligada. */
  mp_user_id?: number | null
}) =>
  apiEmpresa
    .post<{ id: number; nome: string; apelido: string; senha: string; avisos?: string[] }>('/clientes', dados)
    .then((r) => r.data)

export const definirUsinasDoCliente = (clienteId: number, plant_link_ids: number[]) =>
  apiEmpresa.put<void>(`/clientes/${clienteId}/usinas`, { plant_link_ids }).then(() => undefined)

/** A micro usina vista pela EMPRESA: traz junto com qual usina daqui ela já está casada. */
export type MicroDaEmpresa = {
  id: number
  nome: string
  kwp: number | null
  estacoes: string[]
  plant_link_id: number | null
  usina_nome: string | null
}

export const microUsinasDaEmpresa = () =>
  apiEmpresa
    .get<{ micro: MicroDaEmpresa[]; aviso: string | null }>('/micro-usinas')
    .then((r) => r.data)

export const casarMicroUsina = (microId: number, plant_link_id: number | null) =>
  apiEmpresa.put<MicroDaEmpresa>(`/micro-usinas/${microId}`, { plant_link_id }).then((r) => r.data)

/** Preferência de tela desta empresa: some da lista de trazer, nada mais muda. */
export const ocultarUsina = (dados: {
  mw_slug?: string | null
  mp_usina_id?: number | null
  mw_micro_plant_id?: number | null
}) => apiEmpresa.post<void>('/usinas/ocultar', dados).then(() => undefined)

export const mostrarTodasAsUsinas = () =>
  apiEmpresa.delete<void>('/usinas/ocultas').then(() => undefined)

export type UsuarioDetalhado = {
  id: number
  nome: string
  apelido: string
  perfil: string
  ativo: boolean
  email: string | null
  usinas: number
  produtos: Produto[]
  /** Celular, já formatado: `(17) 9 9737-7626`. */
  telefone: string | null
  /** O que o assistente do WhatsApp responde a esta pessoa (precisa do celular). */
  bot_meuplano: boolean
  bot_meuwatt: boolean
  bot_helper: boolean
  /** A pessoa do meuPlano a que o cadastro está ligado (nome), ou nulo: cadastro só daqui. */
  meuplano: string | null
  /** A conta é de OUTRA empresa e também desta: o nome da que cuida dela. Daqui só se
   *  concedem as usinas desta empresa; senha, celular, tokens e bot são de lá. */
  cuidada_por: string | null
}

/** Uma pessoa que a empresa administra no meuPlano — de onde o cadastro pode ser puxado. */
export type PessoaMeuPlano = {
  id: number
  nome: string | null
  email: string | null
  telefone: string | null
  ativo: boolean
  /** apelido da conta daqui já ligada a ela, ou nulo */
  ligada_a: string | null
}

export const pessoasDoMeuPlano = () =>
  apiEmpresa.get<PessoaMeuPlano[]>('/meuplano/pessoas').then((r) => r.data)

export const ligarAoMeuPlano = (usuarioId: number, mpUserId: number) =>
  apiEmpresa
    .put<{ usuario: UsuarioDetalhado; avisos: string[] }>(`/usuarios/${usuarioId}/meuplano`, {
      mp_user_id: mpUserId,
    })
    .then((r) => r.data)

export const desligarDoMeuPlano = (usuarioId: number) =>
  apiEmpresa.delete<UsuarioDetalhado>(`/usuarios/${usuarioId}/meuplano`).then((r) => r.data)

export const usuariosDetalhados = () =>
  apiEmpresa.get<UsuarioDetalhado[]>('/usuarios/detalhados').then((r) => r.data)

export const conectarContaDoCliente = (usuarioId: number, produto: Produto, token: string) =>
  apiEmpresa
    .put<{ ok: boolean; detalhe: string }>(`/usuarios/${usuarioId}/conexoes/${produto}`, { token })
    .then((r) => r.data)

export const desconectarContaDoCliente = (usuarioId: number, produto: Produto) =>
  apiEmpresa.delete<void>(`/usuarios/${usuarioId}/conexoes/${produto}`).then(() => undefined)

export const editarContaDaEmpresa = (
  usuarioId: number,
  dados: { ativo?: boolean; senha?: string; nome?: string; email?: string; telefone?: string } &
    Partial<Record<ProdutoDoBot, boolean>>,
) => apiEmpresa.patch<UsuarioDetalhado>(`/usuarios/${usuarioId}`, dados).then((r) => r.data)

/** As usinas que esta conta recebe hoje — a tela precisa antes de salvar a lista completa. */
export type Concedida = { plant_link_id: number; nome: string; da_empresa: boolean }

export const usinasConcedidas = (usuarioId: number) =>
  apiEmpresa.get<Concedida[]>(`/usuarios/${usuarioId}/usinas`).then((r) => r.data)

// ── o técnico: o WhatsApp Business dele ─────────────────────────────────────

export type EuTecnico = {
  nome: string
  apelido: string
  empresa: string | null
  /** A conta dele no meuPlano — é ela que liga o número aos tickets dele. */
  meuplano: { vinculado: boolean; nome: string | null; email: string | null }
}

export type ContaWhatsapp = {
  phone_number_id: string
  numero_exibicao: string | null
  nome_verificado: string | null
  /** O número continua no aplicativo do celular. */
  coexistencia: boolean
  estado: 'conectada' | 'desconectada'
  detalhe: string | null
  conectada_em: string
  desconectada_em: string | null
}

export type MeuWhatsapp = {
  app_id: string | null
  config_id: string | null
  /** A versão da Graph que o gateway usa — o `FB.init` fala a mesma. */
  versao: string | null
  /** Falso enquanto o administrador da plataforma não completou o app da Meta. */
  pronto: boolean
  contas: ContaWhatsapp[]
}

export type ConexaoWhatsappIn = {
  code: string
  waba_id: string
  phone_number_id: string
  business_id?: string | null
  evento?: string | null
}

export const euTecnico = () => apiTecnico.get<EuTecnico>('/eu').then((r) => r.data)

export const meuWhatsapp = () => apiTecnico.get<MeuWhatsapp>('/whatsapp').then((r) => r.data)

export const conectarMeuWhatsapp = (dados: ConexaoWhatsappIn) =>
  apiTecnico.post<{ ok: boolean; detalhe: string }>('/whatsapp', dados).then((r) => r.data)

export const desconectarMeuWhatsapp = (phoneNumberId: string) =>
  apiTecnico.delete(`/whatsapp/${encodeURIComponent(phoneNumberId)}`)
