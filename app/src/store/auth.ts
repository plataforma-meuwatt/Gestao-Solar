/**
 * Sessão do usuário.
 *
 * Guardada em `expo-secure-store` (keychain / keystore), não em AsyncStorage — é um token
 * de acesso a dados de usina. Sem middleware `persist` do zustand de propósito: a
 * hidratação precisa ser explícita e acontecer ANTES da primeira requisição, senão o
 * interceptor de 401 dispara no cold start.
 */

import { create } from 'zustand'

import { api, definirToken } from '@/lib/api'
import { apagar, gravar, ler } from '@/lib/cofre'

const CHAVE = 'gestaosolar.sessao.v1'

export type Usuario = {
  id: number
  nome: string
  email: string
  empresa: string | null
  tem_meuwatt: boolean
  tem_meuplano: boolean
  nivel_acesso: number
}

type Sessao = { token: string; usuario: Usuario }

type EstadoAuth = {
  token: string | null
  usuario: Usuario | null
  hidratado: boolean
  hidratar: () => Promise<void>
  entrar: (email: string, senha: string) => Promise<void>
  entrarEmDemonstracao: () => Promise<void>
  sair: () => Promise<void>
}

/**
 * Sessão de mentira para percorrer as telas antes de o BFF existir.
 *
 * O token é `demo` de propósito: se alguma tela tentar chamar a API de verdade com ele, o
 * servidor recusa — é melhor falhar visivelmente do que passar por autenticado. A entrada
 * só aparece em `__DEV__`, então não existe no app publicado.
 */
const USUARIO_DEMO: Usuario = {
  id: 0,
  nome: 'Renan Moraes',
  email: 'demonstracao@gestaosolar.app',
  empresa: 'Solaris Energia',
  tem_meuwatt: true,
  tem_meuplano: true,
  nivel_acesso: 2,
}

export const useAuth = create<EstadoAuth>((set) => ({
  token: null,
  usuario: null,
  hidratado: false,

  hidratar: async () => {
    try {
      const bruto = await ler(CHAVE)
      if (bruto) {
        const s = JSON.parse(bruto) as Sessao
        definirToken(s.token)
        set({ token: s.token, usuario: s.usuario })
      }
    } finally {
      // `hidratado` marca que já tentamos — a partir daqui a ausência de token significa
      // "não logado" de verdade, e não "ainda não li o disco".
      set({ hidratado: true })
    }
  },

  entrar: async (email, senha) => {
    const { data } = await api.post<{ token: string; usuario: Usuario }>('/api/v1/auth/login', {
      email,
      senha,
    })
    const sessao: Sessao = { token: data.token, usuario: data.usuario }
    await gravar(CHAVE, JSON.stringify(sessao))
    definirToken(sessao.token)
    set({ token: sessao.token, usuario: sessao.usuario })
  },

  entrarEmDemonstracao: async () => {
    const sessao: Sessao = { token: 'demo', usuario: USUARIO_DEMO }
    await gravar(CHAVE, JSON.stringify(sessao))
    definirToken(sessao.token)
    set({ token: sessao.token, usuario: sessao.usuario })
  },

  sair: async () => {
    await apagar(CHAVE)
    definirToken(null)
    set({ token: null, usuario: null })
  },
}))
