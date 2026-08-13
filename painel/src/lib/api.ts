/**
 * Cliente HTTP do painel.
 *
 * O 401 desloga; o 403 **não** — ele significa "esta conta não abre esta área", e derrubar
 * a sessão faria o atendente ser expulso ao esbarrar numa tela de administrador, o que
 * pareceria bug em vez de permissão.
 */

import axios from 'axios'

declare global {
  interface Window {
    /** Endereço da API, escrito em `/config.js` quando o contêiner sobe. */
    __GS_API__?: string
  }
}

/**
 * Onde está a API.
 *
 * Vazio significa mesma origem — o caso do desenvolvimento, em que o Vite faz proxy de
 * `/api` para o BFF local. Em produção o painel e a API são serviços separados, em
 * domínios separados, e o valor vem de `/config.js` (gerado a partir de `API_URL`).
 *
 * A resolução acontece aqui, uma vez, e não em cada chamada: `baseURL` é fixado na criação
 * do cliente, então um `config.js` que chegasse tarde não teria efeito — é por isso que
 * ele é carregado de forma síncrona no `index.html`, antes deste módulo.
 */
const base = (window.__GS_API__ ?? '').replace(/\/$/, '')

export const api = axios.create({ baseURL: `${base}/api/painel`, timeout: 30000 })

let token: string | null = null
let aoPerder: (() => void) | null = null

export function definirToken(valor: string | null) {
  token = valor
}

export function aoPerderSessao(cb: () => void) {
  aoPerder = cb
}

api.interceptors.request.use((config) => {
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (erro) => {
    if (erro?.response?.status === 401) aoPerder?.()
    return Promise.reject(erro)
  },
)

/** Mensagem pronta para a tela. O BFF sempre responde `detail`. */
export function mensagemDeErro(erro: unknown): string {
  if (axios.isAxiosError(erro)) {
    const detail = (erro.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    // Erro de validação do FastAPI vem como lista de campos.
    if (Array.isArray(detail) && detail.length) {
      const primeiro = detail[0] as { msg?: string; loc?: string[] }
      const campo = primeiro.loc?.slice(-1)[0]
      return campo ? `${campo}: ${primeiro.msg}` : String(primeiro.msg)
    }
    if (erro.code === 'ECONNABORTED') return 'A operação demorou demais. Tente de novo.'
    if (!erro.response) return 'Sem conexão com o servidor.'
    return `Erro ${erro.response.status}.`
  }
  return 'Não foi possível completar a operação.'
}
