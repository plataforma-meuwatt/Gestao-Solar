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

/** Porta do BFF quando ele roda na máquina de quem desenvolve. */
const PORTA_LOCAL = 8100

/**
 * Onde fica a API.
 *
 * A ordem de decisão é por **ambiente**, e não por "qual valor não está vazio" — e a
 * diferença custou uma tarde. A versão anterior partia de `EXPO_PUBLIC_API_URL` com
 * `localhost` como último recurso, e trocava `localhost` pelo IP da máquina **só quando
 * `__DEV__`**. Isso funciona no APK, porque `eas build` injeta a variável a partir de
 * `eas.json`; mas **`eas update` não injeta nada**: o bundle publicado por OTA sai com
 * `process.env.EXPO_PUBLIC_API_URL === undefined`, cai no `localhost`, e a guarda que
 * salvaria está trancada atrás de `__DEV__` — desligado justamente ali.
 *
 * O resultado é o pior tipo de falha: no celular, `localhost` é o próprio celular. A
 * conexão é recusada sem resposta HTTP, e a tela diz "sem conexão com a internet" numa
 * rede perfeita. Pior ainda, some pela metade — a tela que tem cache continua desenhando
 * o que já sabia, e só a tela sem cache conta a verdade.
 *
 * Agora o endereço de produção vem do `app.json`, que é embutido em **todo** bundle —
 * `eas build` e `eas update` —, e a adivinhação de rede local só acontece onde faz
 * sentido.
 */
function resolverBaseURL(): string {
  // Override explícito vence sempre: é assim que se aponta o app para o servidor de outra
  // pessoa, ou para produção a partir da máquina de quem desenvolve.
  const escolhido = process.env.EXPO_PUBLIC_API_URL
  if (escolhido) return escolhido

  const doAppJson = (Constants.expoConfig?.extra as { apiUrl?: string } | undefined)?.apiUrl

  // Aplicativo instalado (APK ou OTA): vale o `app.json`, sem adivinhar.
  if (!__DEV__) return doAppJson ?? 'https://gestao-solar-production.up.railway.app'

  // Desenvolvimento: o BFF roda na mesma máquina que serve o bundle. O Expo publica esse
  // endereço em `hostUri` (`192.168.0.12:8081`), então basta trocar a porta — ninguém
  // precisa descobrir e digitar o IP, e continua valendo quando o roteador mudar amanhã.
  const anfitriao = Constants.expoConfig?.hostUri?.split(':')[0]
  return `http://${anfitriao ?? 'localhost'}:${PORTA_LOCAL}`
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
