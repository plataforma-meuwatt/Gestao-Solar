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

import { api, definirToken } from '@/lib/api'

const CHAVE = 'gs_painel_sessao'

export type Perfil = 'atendimento' | 'administrador'

type Sessao = {
  token: string
  nome: string
  apelido: string
  perfil: Perfil
  areas: string[]
}

type Estado = Omit<Sessao, 'token' | 'perfil'> & {
  token: string | null
  perfil: Perfil | null
  entrar: (apelido: string, senha: string) => Promise<void>
  sair: () => void
  atualizar: (dados: { nome: string; perfil: Perfil; areas: string[] }) => void
  ehAdministrador: () => boolean
  /** Abre esta tela? Administrador abre tudo, aqui e no servidor. */
  pode: (area: string) => boolean
}

function ler(): Sessao | null {
  try {
    const bruto = localStorage.getItem(CHAVE)
    if (!bruto) return null
    const s = JSON.parse(bruto) as Sessao
    // Sessão gravada antes das áreas existirem não tem o campo. Ler `undefined` como
    // lista vazia evita o `map` de um `undefined` na primeira renderização do menu.
    return { ...s, areas: s.areas ?? [] }
  } catch {
    return null
  }
}

const inicial = ler()
if (inicial) definirToken(inicial.token)

function gravar(s: Sessao) {
  localStorage.setItem(CHAVE, JSON.stringify(s))
}

export const useAuth = create<Estado>((set, get) => ({
  token: inicial?.token ?? null,
  nome: inicial?.nome ?? '',
  apelido: inicial?.apelido ?? '',
  perfil: inicial?.perfil ?? null,
  areas: inicial?.areas ?? [],

  entrar: async (apelido, senha) => {
    const { data } = await api.post<{
      token: string
      nome: string
      apelido: string
      perfil: Perfil
      areas: string[]
    }>('/entrar', { apelido, senha })
    const sessao: Sessao = {
      token: data.token,
      nome: data.nome,
      apelido: data.apelido,
      perfil: data.perfil,
      areas: data.areas ?? [],
    }
    gravar(sessao)
    definirToken(sessao.token)
    set(sessao)
  },

  sair: () => {
    localStorage.removeItem(CHAVE)
    definirToken(null)
    set({ token: null, nome: '', apelido: '', perfil: null, areas: [] })
  },

  atualizar: ({ nome, perfil, areas }) => {
    const token = get().token
    if (!token) return
    const sessao: Sessao = { token, nome, apelido: get().apelido, perfil, areas }
    gravar(sessao)
    set(sessao)
  },

  ehAdministrador: () => get().perfil === 'administrador',

  pode: (area) => get().perfil === 'administrador' || get().areas.includes(area),
}))
