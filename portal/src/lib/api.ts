/**
 * Cliente HTTP do portal. Fala SÓ com o BFF — nunca direto com o meuWatt ou o meuPlano.
 *
 * Diferenças deliberadas em relação ao painel do gestor (`painel/src/lib/api.ts`):
 *
 * - **`baseURL` é a origem pura**, sem o prefixo do painel do gestor. O portal consome as rotas de
 *   cliente (`/api/v1/...`) e cada chamada escreve o caminho completo. Copiar o painel
 *   entregaria um site que loga no endpoint errado.
 * - **401 só desloga se a requisição realmente enviou um token.** O painel deslogava em
 *   QUALQUER 401; o app corrigiu isso porque no cold start a sessão ainda não tinha
 *   hidratado e ele se deslogava sozinho. Aqui a sessão é lida do `localStorage` de forma
 *   síncrona, mas a renovação (`/auth/renovar`) e o `/auth/eu` do boot chegam no mesmo
 *   instante — a guarda custa uma linha e fecha o caso para sempre.
 * - **Timeout de 30 s com override por chamada.** A ficha coletiva e o relatório de
 *   manutenção passam de 12 s no BFF; o portal está num notebook com rede boa, então o
 *   padrão pode ser mais folgado, e o que precisar de mais pede na chamada.
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
 * `/api` para o BFF local. Em produção o portal e a API são serviços separados, em
 * domínios separados, e o valor vem de `/config.js` (gerado a partir de `API_URL`).
 *
 * Fixado aqui, uma vez: `baseURL` é decidido na criação do cliente, então o `config.js`
 * é carregado de forma síncrona no `index.html`, antes deste módulo.
 */
export const baseURL = (window.__GS_API__ ?? '').replace(/\/$/, '')

export const api = axios.create({ baseURL, timeout: 30_000 })

let tokenAtual: string | null = null
let aoPerder: (() => void) | null = null

export function definirToken(valor: string | null) {
  tokenAtual = valor
}

/**
 * O token da sessão, para quem não passa pelo axios — o download de PDF e de documento
 * (`lib/arquivo.ts`). Vai em CABEÇALHO, nunca na URL: endereço entra em log de servidor,
 * em histórico do navegador e em relatório de erro, e um token vazado ali vale tanto
 * quanto a senha.
 */
export function tokenDaSessao(): string | null {
  return tokenAtual
}

export function aoPerderSessao(cb: () => void) {
  aoPerder = cb
}

api.interceptors.request.use((config) => {
  if (tokenAtual) config.headers.Authorization = `Bearer ${tokenAtual}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (erro) => {
    const enviouToken = Boolean(erro?.config?.headers?.Authorization)
    if (erro?.response?.status === 401 && enviouToken) aoPerder?.()
    return Promise.reject(erro)
  },
)

/**
 * Mensagem de erro em português, pronta para a tela.
 *
 * O BFF responde `detail` em texto — mas o FastAPI, quando recusa a VALIDAÇÃO de um
 * parâmetro (422), responde `detail` como uma lista de objetos. Entregue a um nó de texto
 * do React, o objeto derruba a tela. Esta função é o funil de TODO erro exibido, então
 * devolve texto de verdade — sempre.
 */
export function mensagemDeErro(erro: unknown): string {
  if (axios.isAxiosError(erro)) {
    const texto = detalheEmTexto((erro.response?.data as { detail?: unknown } | undefined)?.detail)
    if (texto) return texto
    if (erro.code === 'ECONNABORTED') return 'A conexão demorou demais. Tente de novo.'
    if (!erro.response) return 'Sem conexão com o servidor.'
    return `Erro ${erro.response.status}.`
  }
  if (erro instanceof Error && erro.message) return erro.message
  return 'Não foi possível completar a operação.'
}

/**
 * O `detail` de uma resposta de erro, achatado em uma frase.
 *
 * Exportado porque o download de arquivo não passa pelo axios e precisa da mesma régua
 * para mostrar o motivo que o servidor escreveu.
 */
export function detalheEmTexto(detail: unknown): string | null {
  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail)) {
    // 422 do FastAPI: uma entrada por campo recusado. O `msg` é a frase legível; o `loc`
    // diz qual campo, e sem ele a frase ("Field required") não ajuda ninguém.
    const frases = detail
      .map((d) => {
        if (typeof d === 'string') return d
        if (d && typeof d === 'object') {
          const msg = (d as { msg?: unknown }).msg
          const loc = (d as { loc?: unknown }).loc
          const campo = Array.isArray(loc) ? loc.filter((p) => typeof p === 'string').pop() : null
          if (typeof msg === 'string') return campo ? `${campo}: ${msg}` : msg
        }
        return null
      })
      .filter((f): f is string => Boolean(f))
    return frases.length ? frases.join(' · ') : null
  }
  if (detail && typeof detail === 'object') {
    const msg = (detail as { msg?: unknown }).msg
    if (typeof msg === 'string') return msg
  }
  return null
}
