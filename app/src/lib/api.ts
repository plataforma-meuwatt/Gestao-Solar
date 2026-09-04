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

/**
 * O token da sessão, para quem não passa pelos interceptadores do axios — hoje só a
 * `WebView` que abre PDF. Ela recebe o valor em **cabeçalho**, nunca na URL: endereço
 * entra em log de servidor, em histórico e em relatório de erro, e um token vazado ali
 * vale tanto quanto a senha.
 */
export function tokenDaSessao(): string | null {
  return tokenAtual
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

/**
 * Mensagem de erro em português, pronta para a tela.
 *
 * O BFF responde `detail` em texto — mas o FastAPI, quando recusa a VALIDAÇÃO de um
 * parâmetro (422), responde `detail` como uma **lista de objetos** (`[{type, loc, msg}]`).
 * O antigo `as { detail?: string }` desligava a checagem do TypeScript e esse valor saía
 * daqui como se fosse texto; entregue a um `<Text>`, o React derruba a tela com "Objects
 * are not valid as a React child". Esta função é o funil de TODO erro exibido no app, então
 * ela devolve texto de verdade — sempre.
 */
export function mensagemDeErro(erro: unknown): string {
  if (axios.isAxiosError(erro)) {
    const texto = detalheEmTexto((erro.response?.data as { detail?: unknown } | undefined)?.detail)
    if (texto) return texto
    if (erro.code === 'ECONNABORTED') return 'A conexão demorou demais. Tente de novo.'
    if (!erro.response) return 'Sem conexão com a internet.'
  }
  return 'Não foi possível completar a operação.'
}

/**
 * O `detail` de uma resposta de erro, achatado em uma frase.
 *
 * Exportado porque o download de PDF não passa pelo axios e precisa da mesma régua para
 * mostrar o motivo que o servidor escreveu.
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
    const msg = (detail as { msg?: unknown; detail?: unknown }).msg
    if (typeof msg === 'string') return msg
  }
  return null
}
