/**
 * A sessão do CLIENTE — e por que ela não é a do painel.
 *
 * O portal do gestor (`painel/`) e este site são aplicações separadas de propósito, e a
 * separação vai até a porta: o painel entra pela rota de sessão dele e recebe um token
 * marcado com `escopo: "painel"`; o portal entra por `POST /api/v1/auth/login`, a MESMA porta
 * do aplicativo, e recebe um token sem escopo. O BFF recusa um token de painel nas rotas de
 * cliente (`usuario_atual`, 401 "Esta sessão é do painel do gestor"). Um site de gestor e um
 * de cliente compartilhando sessão é o tipo de atalho que vira incidente. A chave no
 * `localStorage` também é outra (`gs_portal_sessao` × `gs_painel_sessao`): os dois sites
 * podem abrir no mesmo navegador, e uma sessão não pode sobrescrever a outra.
 *
 * Quatro decisões que não devem ser desfeitas:
 *
 * **A sessão é lida de forma SÍNCRONA na criação do store.** No aplicativo ela vem do
 * `SecureStore`, que é assíncrono, e por isso ele precisa de um estado "hidratando"; aqui o
 * `localStorage` responde na hora, então o primeiro render já sabe se há sessão. Sem isso o
 * portal piscaria a tela de entrada para quem já está dentro, a cada abertura.
 *
 * **O perfil é revalidado na abertura** (`hidratar()` → `GET /auth/eu`). O que está no disco
 * é uma cópia de quando a pessoa entrou: se o gestor marcou senha provisória, revogou uma
 * usina ou desativou a conta, o portal só descobriria no primeiro erro de leitura. Um perfil
 * defasado é pior que uma leitura a mais — sobretudo o `trocar_senha`, que é justamente o que
 * bloqueia a navegação.
 *
 * **Renovar é silencioso, e só quando falta pouco.** O token vale 30 dias; quem usa o portal
 * uma vez por mês o veria expirar sem nunca ter feito nada de errado. `renovar()` roda no
 * boot e ao voltar o foco, e só age quando faltam menos de sete dias — renovar a cada
 * abertura seria uma escrita de sessão por F5, sem nada em troca. Se o servidor recusar, a
 * sessão cai — e cair aqui é melhor do que cair no meio de uma leitura.
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

/** O que o BFF devolve no login e na renovação. */
type Sessao = { token: string; expira_em?: string | null; usuario: Usuario }

type Guardado = { token: string; expira_em: string | null; usuario: Usuario }

/** Sublinhados, como `gs_painel_sessao`: as duas chaves convivem no mesmo navegador. */
const CHAVE = 'gs_portal_sessao'

/** A partir de quando vale a pena renovar. Sete dias: uma semana de folga. */
const DIAS_PARA_RENOVAR = 7

function lerGuardado(): Guardado | null {
  try {
    const cru = localStorage.getItem(CHAVE)
    if (!cru) return null
    const dados = JSON.parse(cru) as Guardado
    return dados?.token && dados?.usuario?.id
      ? { token: dados.token, expira_em: dados.expira_em ?? null, usuario: dados.usuario }
      : null
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
  expiraEm: string | null
  usuario: Usuario | null
  entrando: boolean
  erro: string | null
  entrar: (apelido: string, senha: string) => Promise<boolean>
  sair: () => void
  /** Revalida o perfil contra o servidor. Roda no boot, quando há sessão guardada. */
  hidratar: () => Promise<void>
  /** Estende o prazo quando falta pouco. Roda no boot e ao voltar o foco da janela. */
  renovar: () => Promise<void>
  /** Depois de trocar a senha: o servidor devolve o perfil sem a marca `trocar_senha`. */
  atualizarUsuario: (usuario: Usuario) => void
}

const inicial = lerGuardado()
definirToken(inicial?.token ?? null)
identificarCache(inicial?.usuario.id ?? null)

/** Falta menos de uma semana para o token vencer? Sem prazo conhecido, sim: renove. */
function estaPertoDeVencer(expiraEm: string | null): boolean {
  if (!expiraEm) return true
  const fim = new Date(expiraEm).getTime()
  if (Number.isNaN(fim)) return true
  return fim - Date.now() < DIAS_PARA_RENOVAR * 24 * 60 * 60 * 1000
}

export const useAuth = create<Estado>((set, get) => ({
  token: inicial?.token ?? null,
  expiraEm: inicial?.expira_em ?? null,
  usuario: inicial?.usuario ?? null,
  entrando: false,
  erro: null,

  async entrar(apelido, senha) {
    set({ entrando: true, erro: null })
    try {
      const { data } = await api.post<Sessao>('/api/v1/auth/login', {
        apelido: apelido.trim(),
        senha,
      })
      // A ordem importa: o cache passa a ser da conta nova ANTES de qualquer leitura, e o
      // que sobrou da conta anterior sai de cena.
      limparCache()
      esquecerConsultas()
      identificarCache(data.usuario.id)
      definirToken(data.token)
      const expira = data.expira_em ?? null
      guardar({ token: data.token, expira_em: expira, usuario: data.usuario })
      set({
        token: data.token,
        expiraEm: expira,
        usuario: data.usuario,
        entrando: false,
        erro: null,
      })
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
    set({ token: null, expiraEm: null, usuario: null, erro: null })
  },

  async hidratar() {
    const { token, expiraEm } = get()
    if (!token) return
    try {
      const { data } = await api.get<Usuario>('/api/v1/auth/eu')
      identificarCache(data.id)
      guardar({ token, expira_em: expiraEm, usuario: data })
      set({ usuario: data })
    } catch {
      // 401 já derruba a sessão pelo interceptor. Rede fora não pode expulsar quem tem
      // token válido: o portal segue com o perfil guardado, que é o certo até prova em
      // contrário.
    }
  },

  async renovar() {
    const { token, expiraEm } = get()
    if (!token || !estaPertoDeVencer(expiraEm)) return
    try {
      const { data } = await api.post<Sessao>('/api/v1/auth/renovar')
      definirToken(data.token)
      identificarCache(data.usuario.id)
      const expira = data.expira_em ?? null
      guardar({ token: data.token, expira_em: expira, usuario: data.usuario })
      set({ token: data.token, expiraEm: expira, usuario: data.usuario })
    } catch {
      // Recusa de renovação vira 401 no interceptor, que já chama `sair`. Qualquer outra
      // falha (rede, servidor fora) não pode derrubar quem está com a sessão válida na mão.
    }
  },

  atualizarUsuario(usuario) {
    const { token, expiraEm } = get()
    if (token) guardar({ token, expira_em: expiraEm, usuario })
    set({ usuario })
  },
}))

// O interceptor do axios não conhece o store; é aqui que os dois se encontram.
aoPerderSessao(() => useAuth.getState().sair())

// A aba que fica aberta a semana inteira: ao voltar o foco, o portal confere se o prazo está
// acabando e o estende em silêncio. Sem isto, a sessão venceria com a janela aberta e a
// próxima leitura cairia no login — no meio de uma reunião, sem aviso.
if (typeof window !== 'undefined') {
  window.addEventListener('focus', () => {
    void useAuth.getState().renovar()
  })
}
