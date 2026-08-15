/**
 * Permissões e push.
 *
 * **Há DUAS permissões, e as duas precisam existir.** O gestor decide se esta pessoa deve
 * receber avisos de usina parada; o Android decide se o aplicativo pode mostrar aviso
 * nenhum. Uma sem a outra não entrega nada — e os dois casos se parecem na tela ("não
 * chega notificação"), então a tela precisa saber distinguir e dizer qual falta.
 *
 * O token do Expo (`ExponentPushToken[...]`) só é pedido DEPOIS de o Android autorizar.
 * Pedir antes devolve erro, e um erro no meio da abertura do app parece defeito.
 */

import * as Notifications from 'expo-notifications'
import Constants from 'expo-constants'
import { Platform } from 'react-native'

import { api } from '@/lib/api'
import { fetchWithCache, type Leitura } from '@/lib/cache'

/** Chave canônica da permissão de aviso de usina parada. */
export const PERMISSAO_USINA_PARADA = 'notificacao.usina_parada'

export type MinhasPermissoes = { permissoes: string[] }

export function usePermissoes(): Leitura<MinhasPermissoes> {
  return fetchWithCache<MinhasPermissoes>('me/permissoes')
}

export function temPermissao(dados: MinhasPermissoes | null, chave: string): boolean {
  return Boolean(dados?.permissoes?.includes(chave))
}

/** O que o Android respondeu sobre mostrar notificações. */
export type EstadoDoSistema = 'concedida' | 'negada' | 'nao_perguntado' | 'indisponivel'

export async function estadoNoSistema(): Promise<EstadoDoSistema> {
  // Navegador não tem push. Dizer "negada" ali mandaria o usuário procurar um ajuste
  // do sistema que não existe.
  //
  // Emulador NÃO é testado aqui de propósito: `Constants.isDevice` saiu do
  // `expo-constants` nesta versão, e `expo-device` só entraria com build nativo novo.
  // A detecção acontece sozinha e mais tarde — no emulador o `getExpoPushTokenAsync`
  // falha, o registro devolve `null` e a tela mostra que o aviso não está ativo.
  if (Platform.OS === 'web') return 'indisponivel'
  const { status, canAskAgain } = await Notifications.getPermissionsAsync()
  if (status === 'granted') return 'concedida'
  if (status === 'undetermined' || canAskAgain) return 'nao_perguntado'
  return 'negada'
}

/**
 * Pede a permissão ao sistema e, se concedida, registra o aparelho no BFF.
 *
 * Devolve o estado final para a tela reagir sem consultar de novo.
 */
export async function pedirERegistrar(): Promise<EstadoDoSistema> {
  if (Platform.OS === 'web') return 'indisponivel'

  const atual = await Notifications.getPermissionsAsync()
  let status = atual.status
  if (status !== 'granted') {
    // Só pergunta se ainda dá: com `canAskAgain` falso o sistema não mostra mais o
    // diálogo, e chamar de novo devolve "denied" na hora, sem o usuário ver nada.
    if (!atual.canAskAgain) return 'negada'
    status = (await Notifications.requestPermissionsAsync()).status
  }
  if (status !== 'granted') return 'negada'

  await registrarAparelho()
  return 'concedida'
}

/**
 * Manda o token deste aparelho para o BFF.
 *
 * O `projectId` é obrigatório fora do Expo Go: sem ele o Expo não sabe para qual projeto
 * emitir o token, e a chamada falha com uma mensagem que não ajuda ninguém.
 */
export async function registrarAparelho(): Promise<string | null> {
  if (Platform.OS === 'web') return null

  const projectId =
    Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId
  if (!projectId) return null

  try {
    if (Platform.OS === 'android') {
      /*
       * O canal precisa existir ANTES do primeiro aviso, e o nome dele é o mesmo que o
       * BFF manda em `channelId`. Sem canal, o Android entrega no canal padrão, que na
       * maioria dos aparelhos vem sem som e sem vibração — o aviso chega e ninguém vê.
       */
      await Notifications.setNotificationChannelAsync('paradas', {
        name: 'Usina parada',
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 250, 250, 250],
        lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      })
    }

    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId })
    await api.post('/api/v1/me/dispositivos', {
      token,
      plataforma: Platform.OS,
      versao_app: Constants.expoConfig?.version ?? null,
    })
    return token
  } catch {
    // Falhar aqui não pode derrubar a abertura do app: sem push o aplicativo continua
    // inteiro, e a tela de Perfil mostra que o aviso não está ativo.
    return null
  }
}

/** Chamado no logout: sem isto o aparelho seguiria recebendo avisos da conta que saiu. */
export async function esquecerAparelho(): Promise<void> {
  if (Platform.OS === 'web') return
  const projectId =
    Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId
  if (!projectId) return
  try {
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId })
    await api.delete(`/api/v1/me/dispositivos/${encodeURIComponent(token)}`)
  } catch {
    // Se não deu para avisar o servidor, o token morre sozinho: o Expo passa a
    // responder `DeviceNotRegistered` e o BFF apaga a linha no próximo envio.
  }
}
