/**
 * Sessão do painel.
 *
 * Guardada em `localStorage` — é uma ferramenta interna, em máquina do time, e a sessão
 * dura 8 horas por decisão do backend. O perfil vem junto só para a barra lateral esconder
 * o que a conta não abre: quem decide de verdade é o servidor, que recusa de qualquer
 * forma.
 */

import { create } from 'zustand'

import { api, definirToken } from '@/lib/api'

const CHAVE = 'gs_painel_sessao'

export type Perfil = 'atendimento' | 'administrador'

type Sessao = { token: string; nome: string; perfil: Perfil }

type Estado = {
  token: string | null
  nome: string
  perfil: Perfil | null
  entrar: (email: string, senha: string) => Promise<void>
  sair: () => void
  ehAdministrador: () => boolean
}

function ler(): Sessao | null {
  try {
    const bruto = localStorage.getItem(CHAVE)
    return bruto ? (JSON.parse(bruto) as Sessao) : null
  } catch {
    return null
  }
}

const inicial = ler()
if (inicial) definirToken(inicial.token)

export const useAuth = create<Estado>((set, get) => ({
  token: inicial?.token ?? null,
  nome: inicial?.nome ?? '',
  perfil: inicial?.perfil ?? null,

  entrar: async (email, senha) => {
    const { data } = await api.post<{ token: string; nome: string; perfil: Perfil }>('/entrar', {
      email,
      senha,
    })
    const sessao: Sessao = { token: data.token, nome: data.nome, perfil: data.perfil }
    localStorage.setItem(CHAVE, JSON.stringify(sessao))
    definirToken(sessao.token)
    set(sessao)
  },

  sair: () => {
    localStorage.removeItem(CHAVE)
    definirToken(null)
    set({ token: null, nome: '', perfil: null })
  },

  ehAdministrador: () => get().perfil === 'administrador',
}))
