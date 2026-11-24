/**
 * Sessão do painel.
 *
 * Guardada em `localStorage` — é uma ferramenta interna, em máquina do time, e a sessão
 * dura 8 horas por decisão do backend.
 *
 * Perfil e áreas vêm junto para a barra lateral montar o menu e para o painel saber onde
 * pousar quem entra. **Isso é conforto de interface, não segurança**: quem digitar a URL
 * na mão toma 403 do servidor, que confere a área a cada requisição.
 *
 * O que está aqui é uma FOTO do login. O acesso muda no meio das oito horas — alguém
 * concede ou revoga uma área — e por isso a casca revalida em `GET /eu` ao abrir e grava
 * o que voltar por `atualizar`. Sem isso, quem perdesse o WhatsApp continuaria vendo o
 * item, clicaria, tomaria 403 e leria isso como defeito do painel.
 */

import { create } from 'zustand'

import { api, baseDaApi, definirToken } from '@/lib/api'
import { aceita, fraseDaPortaErrada } from '@/lib/portao'

const CHAVE = 'gs_painel_sessao'

export type Perfil = 'atendimento' | 'administrador' | 'gestor_empresa' | 'tecnico'

/**
 * Qual portão esta sessão abre. Quem manda é o servidor — o campo vem do login e é
 * repetido em `GET /eu`; aqui ele só escolhe o menu e o cliente HTTP.
 */
export type Escopo = 'painel' | 'empresa' | 'tecnico'

type Sessao = {
  token: string
  nome: string
  apelido: string
  perfil: Perfil
  areas: string[]
  escopo: Escopo
  /** O nome da empresa, quando a sessão é de empresa. Fica fixo no topo da tela. */
  empresa: string | null
}

/** A senha está certa e falta o código do autenticador (a verificação em duas etapas, R12). Na primeira vez,
 *  `cadastrar` vem com o QR, a chave e o endereço que abre o autenticador no celular. */
export type DuasEtapas = {
  desafio: string
  cadastrar: boolean
  qr: string | null
  segredo: string | null
  otpauth: string | null
}

type Estado = Omit<Sessao, 'token' | 'perfil'> & {
  token: string | null
  perfil: Perfil | null
  /** Devolve o pedido do código quando a conta usa a verificação em duas etapas; senão, já entrou. */
  entrar: (apelido: string, senha: string) => Promise<DuasEtapas | null>
  entrarComCodigo: (desafio: string, codigo: string) => Promise<void>
  sair: () => void
  atualizar: (dados: { nome: string; perfil: Perfil; areas: string[] }) => void
  /** Assume outro papel da mesma pessoa, com a sessão que o servidor acabou de emitir. */
  assumir: (dados: {
    token: string
    nome: string
    apelido: string
    perfil: Perfil
    escopo: Escopo
    empresa: string | null
  }) => void
  /** A sessão nova deste aparelho (a senha trocada encerrou as outras): troca só o token guardado. */
  trocarToken: (token: string) => void
  ehAdministrador: () => boolean
  /** A sessão é do gerente da empresa de O&M — o outro portão, o outro menu. */
  ehEmpresa: () => boolean
  /** A sessão é do técnico: um portão só dele, com uma tela só — o WhatsApp dele. */
  ehTecnico: () => boolean
  /** Abre esta tela do painel da plataforma? Administrador abre tudo, aqui e no servidor. */
  pode: (area: string) => boolean
}

function ler(): Sessao | null {
  try {
    const bruto = localStorage.getItem(CHAVE)
    if (!bruto) return null
    const s = JSON.parse(bruto) as Sessao
    // Sessão gravada antes das áreas existirem não tem o campo. Ler `undefined` como
    // lista vazia evita o `map` de um `undefined` na primeira renderização do menu.
    // Sessão gravada antes do multiempresa não tem escopo: ler como `painel` mantém
    // quem já estava logado exatamente onde estava.
    return { ...s, areas: s.areas ?? [], escopo: s.escopo ?? 'painel', empresa: s.empresa ?? null }
  } catch {
    return null
  }
}

const inicial = ler()
if (inicial) definirToken(inicial.token)

function gravar(s: Sessao) {
  localStorage.setItem(CHAVE, JSON.stringify(s))
}

/** O que `POST /entrar` (e `/entrar/codigo`) devolve: a sessão, ou o pedido do código. */
type RespostaDeEntrar = {
  token: string
  nome: string
  apelido: string
  perfil: Perfil
  areas: string[]
  escopo?: Escopo
  empresa?: string | null
  duas_etapas?: DuasEtapas | null
}

function sessaoDe(data: RespostaDeEntrar): Sessao {
  return {
    token: data.token,
    nome: data.nome,
    apelido: data.apelido,
    perfil: data.perfil,
    areas: data.areas ?? [],
    escopo: data.escopo ?? 'painel',
    empresa: data.empresa ?? null,
  }
}

export const useAuth = create<Estado>((set, get) => ({
  token: inicial?.token ?? null,
  nome: inicial?.nome ?? '',
  apelido: inicial?.apelido ?? '',
  perfil: inicial?.perfil ?? null,
  areas: inicial?.areas ?? [],
  escopo: inicial?.escopo ?? 'painel',
  empresa: inicial?.empresa ?? null,

  entrar: async (apelido, senha) => {
    // Uma porta de login para os dois portões: o servidor confere a senha e devolve o
    // token JÁ marcado com o escopo do perfil. O front não escolhe nada aqui.
    const { data } = await api.post<RespostaDeEntrar>('/entrar', { apelido, senha })
    // Senha certa na porta errada: a sessão NÃO é guardada aqui — a pessoa é mandada ao
    // endereço do perfil dela (o gerente no oem-gs, o administrador no adm-gs).
    if (!aceita(data.escopo ?? 'painel')) throw new Error(fraseDaPortaErrada(data.escopo ?? 'painel'))
    if (data.duas_etapas) return data.duas_etapas
    const sessao = sessaoDe(data)
    gravar(sessao)
    definirToken(sessao.token)
    set(sessao)
    return null
  },

  entrarComCodigo: async (desafio, codigo) => {
    const { data } = await api.post<RespostaDeEntrar>('/entrar/codigo', { desafio, codigo })
    if (!aceita(data.escopo ?? 'painel')) throw new Error(fraseDaPortaErrada(data.escopo ?? 'painel'))
    const sessao = sessaoDe(data)
    gravar(sessao)
    definirToken(sessao.token)
    set(sessao)
  },


  sair: () => {
    // a sessão acaba no servidor também (R4); sem esperar: sair nunca trava a tela
    const atual = get().token
    if (atual)
      fetch(`${baseDaApi()}/api/sessao/sair`, { method: 'POST', headers: { Authorization: `Bearer ${atual}` } }).catch(
        () => undefined,
      )
    localStorage.removeItem(CHAVE)
    definirToken(null)
    set({ token: null, nome: '', apelido: '', perfil: null, areas: [], escopo: 'painel', empresa: null })
  },

  // A sessão do OUTRO papel da mesma pessoa. O token já vem do portão certo; aqui só se
  // troca o que está guardado — e as áreas vêm vazias porque quem manda é o servidor, que
  // as devolve em `GET /eu` na primeira volta da casca.
  assumir: (dados) => {
    const sessao: Sessao = {
      token: dados.token,
      nome: dados.nome,
      apelido: dados.apelido,
      perfil: dados.perfil,
      areas: [],
      escopo: dados.escopo,
      empresa: dados.empresa,
    }
    gravar(sessao)
    definirToken(sessao.token)
    set(sessao)
  },

  trocarToken: (token) => {
    const atual = get()
    if (!atual.token || !atual.perfil) return
    const sessao: Sessao = {
      token,
      nome: atual.nome,
      apelido: atual.apelido,
      perfil: atual.perfil,
      areas: atual.areas,
      escopo: atual.escopo,
      empresa: atual.empresa,
    }
    gravar(sessao)
    definirToken(token)
    set({ token })
  },

  atualizar: ({ nome, perfil, areas }) => {
    const token = get().token
    if (!token) return
    const sessao: Sessao = {
      token,
      nome,
      apelido: get().apelido,
      perfil,
      areas,
      escopo: get().escopo,
      empresa: get().empresa,
    }
    gravar(sessao)
    set(sessao)
  },

  ehAdministrador: () => get().perfil === 'administrador',

  ehEmpresa: () => get().escopo === 'empresa',

  ehTecnico: () => get().escopo === 'tecnico',

  // As ÁREAS são do painel da plataforma. Numa sessão de empresa elas não existem, e
  // responder `true` aqui abriria itens de menu que o servidor recusa — a pessoa clicaria
  // e leria 403 como defeito. O menu da empresa é outro, montado por escopo.
  pode: (area) =>
    get().escopo === 'painel' &&
    (get().perfil === 'administrador' || get().areas.includes(area)),
}))
