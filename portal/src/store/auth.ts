/**
 * A sessão do CLIENTE — e por que ela não é a do painel.
 *
 * O portal do gestor (`painel/`) e este site são aplicações separadas de propósito, e a
 * separação vai até a porta: o painel entra por `POST /api/painel/entrar` e recebe um token
 * marcado com `escopo: "painel"`; o portal entra por `POST /api/v1/auth/login`, a MESMA porta
 * do aplicativo, e recebe um token sem escopo. O BFF recusa um token de painel nas rotas de
 * cliente (`usuario_atual`, 401 "Esta sessão é do painel do gestor"). Um site de gestor e um
 * de cliente compartilhando sessão é o tipo de atalho que vira incidente.
 *
 * Três decisões que não devem ser desfeitas:
 *
 * **A sessão é lida de forma SÍNCRONA na criação do store.** No aplicativo ela vem do
 * `SecureStore`, que é assíncrono, e por isso ele precisa de um estado "hidratando"; aqui o
 * `localStorage` responde na hora, então o primeiro render já sabe se há sessão. Sem isso o
 * portal piscaria a tela de entrada para quem já está dentro, a cada abertura.
 *
 * **Renovar é silencioso, e acontece na abertura.** O token vale 30 dias; quem usa o portal
 * uma vez por semana o veria expirar sem nunca ter feito nada de errado. `renovar()` roda no
 * boot quando há sessão: se o servidor aceitar, o prazo recomeça sem pedir senha; se recusar,
 * a sessão cai — e cair aqui é melhor do que cair no meio de uma leitura.
 *
 * **Sair apaga tudo.** Token, cache de leitura em disco e cache de consultas em memória. O
 * caso real é a mesma pessoa com conta de gestor e conta de dono no mesmo computador: sem a
 * limpeza, as usinas de quem saiu apareceriam para quem entrou, apresentadas como leitura ao
 * vivo — que é vazamento, não atraso.
 */

import { create } from 'zustand'

import { api, aoPerderSessao, definirToken, mensagemDeErro } from '@/lib/api'
import { esquecerConsultas } from '@/lib/consulta'
import { identificarCache, limparCache } from '@/lib/leitura'

export type Usuario = {
  id: number
  nome: string
  apelido: string
  email: string | null
  empresa: string | null
  tem_meuwatt: boolean
  tem_meuplano: boolean
  nivel_acesso: number
  usinas: number
  /** Enquanto verdadeiro, o portal só deixa abrir a troca de senha. */
  trocar_senha: boolean
}

type Guardado = { token: string; usuario: Usuario }

const CHAVE = 'gs-portal-sessao'

function lerGuardado(): Guardado | null {
  try {
    const cru = localStorage.getItem(CHAVE)
    if (!cru) return null
    const dados = JSON.parse(cru) as Guardado
    return dados?.token && dados?.usuario?.id ? dados : null
  } catch {
    // JSON corrompido ou armazenamento bloqueado: sem sessão, cai no login.
    return null
  }
}

function guardar(dados: Guardado | null): void {
  try {
    if (dados) localStorage.setItem(CHAVE, JSON.stringify(dados))
    else localStorage.removeItem(CHAVE)
  } catch {
    // Sem armazenamento a sessão vale só para esta aba — melhor que recusar a entrada.
  }
}

type Estado = {
  token: string | null
  usuario: Usuario | null
  entrando: boolean
  erro: string | null
  entrar: (apelido: string, senha: string) => Promise<boolean>
  sair: () => void
  renovar: () => Promise<void>
  /** Depois de trocar a senha: o servidor devolve o perfil sem a marca `trocar_senha`. */
  atualizarUsuario: (usuario: Usuario) => void
}

const inicial = lerGuardado()
definirToken(inicial?.token ?? null)
identificarCache(inicial?.usuario.id ?? null)

export const useAuth = create<Estado>((set, get) => ({
  token: inicial?.token ?? null,
  usuario: inicial?.usuario ?? null,
  entrando: false,
  erro: null,

  async entrar(apelido, senha) {
    set({ entrando: true, erro: null })
    try {
      const { data } = await api.post<{ token: string; usuario: Usuario }>('/api/v1/auth/login', {
        apelido: apelido.trim(),
        senha,
      })
      // A ordem importa: o cache passa a ser da conta nova ANTES de qualquer leitura, e o
      // que sobrou da conta anterior sai de cena.
      limparCache()
      esquecerConsultas()
      identificarCache(data.usuario.id)
      definirToken(data.token)
      guardar({ token: data.token, usuario: data.usuario })
      set({ token: data.token, usuario: data.usuario, entrando: false, erro: null })
      return true
    } catch (erro) {
      set({ entrando: false, erro: mensagemDeErro(erro) })
      return false
    }
  },

  sair() {
    definirToken(null)
    identificarCache(null)
    limparCache()
    esquecerConsultas()
    guardar(null)
    set({ token: null, usuario: null, erro: null })
  },

  async renovar() {
    if (!get().token) return
    try {
      const { data } = await api.post<{ token: string; usuario: Usuario }>('/api/v1/auth/renovar')
      definirToken(data.token)
      identificarCache(data.usuario.id)
      guardar({ token: data.token, usuario: data.usuario })
      set({ token: data.token, usuario: data.usuario })
    } catch {
      // Recusa de renovação vira 401 no interceptor, que já chama `sair`. Qualquer outra
      // falha (rede, servidor fora) não pode derrubar quem está com a sessão válida na mão.
    }
  },

  atualizarUsuario(usuario) {
    const token = get().token
    if (token) guardar({ token, usuario })
    set({ usuario })
  },
}))

// O interceptor do axios não conhece o store; é aqui que os dois se encontram.
aoPerderSessao(() => useAuth.getState().sair())
