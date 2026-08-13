/**
 * Cliente HTTP do app. Fala SÓ com o BFF — nunca direto com a mw-api ou o meuPlano.
 *
 * Dois detalhes herdados do app de campo do meuPlano, ambos por motivo concreto:
 *
 * - **Timeout curto (12 s).** Em usina a rede é ruim; falhar rápido e cair no cache é
 *   melhor experiência do que a tela ficar pendurada meio minuto.
 * - **401 só desloga se a requisição realmente enviou um token.** No cold start (e
 *   depois de uma atualização OTA) há uma janela em que a sessão ainda não hidratou;
 *   sem esta checagem o app desloga sozinho ao abrir.
 */

import axios from 'axios'
import Constants from 'expo-constants'

const configurado =
  (Constants.expoConfig?.extra as { apiUrl?: string } | undefined)?.apiUrl ??
  'http://localhost:8100'

/**
 * Em desenvolvimento, `localhost` é uma armadilha: no celular com Expo Go ele aponta para
 * o próprio aparelho, não para a máquina que roda o BFF — e o sintoma é "sem conexão com a
 * internet" numa rede que está perfeita.
 *
 * O endereço certo é o mesmo que serve o bundle. O Expo o publica em `hostUri`
 * (`192.168.0.12:8081`), então basta trocar a porta pela do BFF. Assim ninguém precisa
 * descobrir e digitar o IP da máquina — e ele continua funcionando quando o roteador
 * distribuir outro amanhã.
 *
 * Em produção vale o que está no `app.json`, sem adivinhação.
 */
function resolverBaseURL(): string {
  if (!__DEV__ || !/\/\/(localhost|127\.0\.0\.1)/.test(configurado)) return configurado

  const anfitriao = Constants.expoConfig?.hostUri?.split(':')[0]
  if (!anfitriao) return configurado

  const porta = configurado.split(':').pop()
  return `http://${anfitriao}:${porta}`
}

export const baseURL = resolverBaseURL()

export const api = axios.create({ baseURL, timeout: 12000 })

/** Preenchido pelo store de auth na hidratação; lido a cada requisição. */
let tokenAtual: string | null = null
let aoPerderSessao: (() => void) | null = null

export function definirToken(token: string | null) {
  tokenAtual = token
}

export function aoDeslogar(cb: () => void) {
  aoPerderSessao = cb
}

api.interceptors.request.use((config) => {
  if (tokenAtual) config.headers.Authorization = `Bearer ${tokenAtual}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (erro) => {
    const enviouToken = Boolean(erro?.config?.headers?.Authorization)
    if (erro?.response?.status === 401 && enviouToken) aoPerderSessao?.()
    return Promise.reject(erro)
  },
)

/** Mensagem de erro em português, pronta para a tela. O BFF sempre responde `detail`. */
export function mensagemDeErro(erro: unknown): string {
  if (axios.isAxiosError(erro)) {
    const detail = (erro.response?.data as { detail?: string } | undefined)?.detail
    if (detail) return detail
    if (erro.code === 'ECONNABORTED') return 'A conexão demorou demais. Tente de novo.'
    if (!erro.response) return 'Sem conexão com a internet.'
  }
  return 'Não foi possível completar a operação.'
}
