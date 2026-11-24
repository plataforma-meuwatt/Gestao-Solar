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
import { identificarCache, limparCache } from '@/lib/cache'
import { esquecerConsultas } from '@/lib/consulta'
import { apagar, gravar, ler } from '@/lib/cofre'

const CHAVE = 'gestaosolar.sessao.v1'

export type Usuario = {
  id: number
  nome: string
  /** Com o que ele entra. O e-mail é contato — ver `bff/app/core/apelido.py`. */
  apelido: string
  email: string | null
  empresa: string | null
  tem_meuwatt: boolean
  tem_meuplano: boolean
  nivel_acesso: number
  usinas: number
  trocar_senha: boolean
}

type Sessao = { token: string; usuario: Usuario }

/** A senha está certa e falta o código do autenticador (a verificação em duas etapas do gerente e da plataforma). Na
 *  primeira vez, `cadastrar` traz a chave e o endereço `otpauth://` que abre o autenticador neste celular. */
export type DuasEtapas = {
  desafio: string
  cadastrar: boolean
  qr: string | null
  segredo: string | null
  otpauth: string | null
}

type EstadoAuth = {
  token: string | null
  usuario: Usuario | null
  hidratado: boolean
  hidratar: () => Promise<void>
  /** Devolve o pedido do código quando a conta usa a verificação em duas etapas; senão, já entrou. */
  entrar: (apelido: string, senha: string) => Promise<DuasEtapas | null>
  entrarComCodigo: (desafio: string, codigo: string) => Promise<void>
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
  // Nome e empresa deliberadamente autoexplicativos. Antes eram "Renan Moraes" e
  // "Solaris Energia" — plausíveis a ponto de, numa captura de tela ou num vídeo de
  // demonstração, passarem por cliente real.
  nome: 'Conta de demonstração',
  apelido: 'demonstracao',
  email: null,
  empresa: null,
  tem_meuwatt: true,
  tem_meuplano: true,
  nivel_acesso: 2,
  usinas: 0,
  trocar_senha: false,
}

/** Guarda a sessão do login. A conta identifica o cache: sem isso, TODA sessão aberta por login gravava como
 *  `anonimo`, e a proteção "por construção" que o cache promete existiria só para quem entrasse pela hidratação. */
async function guardarSessao(sessao: Sessao, set: (p: Partial<EstadoAuth>) => void) {
  await gravar(CHAVE, JSON.stringify(sessao))
  definirToken(sessao.token)
  identificarCache(sessao.usuario?.id ?? null)
  set({ token: sessao.token, usuario: sessao.usuario })
}

export const useAuth = create<EstadoAuth>((set, get) => ({
  token: null,
  usuario: null,
  hidratado: false,

  hidratar: async () => {
    try {
      const bruto = await ler(CHAVE)
      if (bruto) {
        const s = JSON.parse(bruto) as Sessao
        definirToken(s.token)
        identificarCache(s.usuario?.id ?? null)
        set({ token: s.token, usuario: s.usuario })
      }
    } finally {
      // `hidratado` marca que já tentamos — a partir daqui a ausência de token significa
      // "não logado" de verdade, e não "ainda não li o disco".
      set({ hidratado: true })
    }
  },

  entrar: async (apelido, senha) => {
    const { data } = await api.post<{ token: string; usuario: Usuario; duas_etapas?: DuasEtapas | null }>(
      '/api/v1/auth/login',
      { apelido: apelido.trim().toLowerCase(), senha },
    )
    // a conta usa a verificação em duas etapas (o gerente e a plataforma): a senha está certa e falta o código
    if (data.duas_etapas) return data.duas_etapas
    await guardarSessao({ token: data.token, usuario: data.usuario }, set)
    return null
  },

  entrarComCodigo: async (desafio, codigo) => {
    const { data } = await api.post<{ token: string; usuario: Usuario }>('/api/v1/auth/login/codigo', {
      desafio,
      codigo,
    })
    await guardarSessao({ token: data.token, usuario: data.usuario }, set)
  },

  entrarEmDemonstracao: async () => {

    const sessao: Sessao = { token: 'demo', usuario: USUARIO_DEMO }
    await gravar(CHAVE, JSON.stringify(sessao))
    definirToken(sessao.token)
    identificarCache(sessao.usuario?.id ?? null)
    set({ token: sessao.token, usuario: sessao.usuario })
  },

  sair: async () => {
    // A sessão acaba no servidor também (R12: some de "Sessões abertas" e o token roubado deixa de valer), sem esperar:
    // sair nunca trava a tela, e sem rede o aparelho sai do mesmo jeito.
    const atual = get().token
    if (atual && atual !== 'demo')
      void api
        .post('/api/sessao/sair', null, { headers: { Authorization: `Bearer ${atual}` }, validateStatus: () => true })
        .catch(() => undefined)
    await apagar(CHAVE)
    // O cache de leitura vai junto, e não é zelo: o CLAUDE.md descreve a mesma pessoa com
    // DUAS contas no mesmo aparelho — `renanmarquezini` gestor e `renan.marquezini` dono.
    // Sem esta limpeza, quem entra depois vê as usinas de quem saiu, com nome e geração,
    // até a rede responder. E se a rede estiver ruim — que é o caso de usina — vê por
    // bastante tempo.
    await limparCache()
    // O cache em MEMÓRIA também: apagar só o disco deixava o TanStack devolver os dados
    // da conta anterior — e, por virem da memória, apresentados como leitura ao vivo.
    esquecerConsultas()
    identificarCache(null)
    definirToken(null)
    set({ token: null, usuario: null })
  },
}))
