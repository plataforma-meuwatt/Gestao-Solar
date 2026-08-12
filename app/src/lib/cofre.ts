/**
 * Guarda a sessão no lugar mais seguro que a plataforma oferece.
 *
 * No celular é o `expo-secure-store` (keychain no iOS, keystore no Android) — é um token
 * de acesso a dados de usina, não cabe em armazenamento comum.
 *
 * Na web o SecureStore não existe: os módulos nativos não têm implementação e a chamada
 * estoura em tempo de execução. Lá o fallback é o `localStorage`, e isso é aceitável
 * porque a web só roda em desenvolvimento (o alvo do produto é iOS e Android). Se um dia
 * houver build web de produção, este é o ponto a revisitar.
 */

import { Platform } from 'react-native'
import * as SecureStore from 'expo-secure-store'

const naWeb = Platform.OS === 'web'

export async function ler(chave: string): Promise<string | null> {
  if (naWeb) {
    try {
      return globalThis.localStorage?.getItem(chave) ?? null
    } catch {
      return null
    }
  }
  return SecureStore.getItemAsync(chave)
}

export async function gravar(chave: string, valor: string): Promise<void> {
  if (naWeb) {
    try {
      globalThis.localStorage?.setItem(chave, valor)
    } catch {
      // Modo privado do navegador rejeita a escrita; em dev isso só custa relogar.
    }
    return
  }
  await SecureStore.setItemAsync(chave, valor)
}

export async function apagar(chave: string): Promise<void> {
  if (naWeb) {
    try {
      globalThis.localStorage?.removeItem(chave)
    } catch {
      // idem
    }
    return
  }
  await SecureStore.deleteItemAsync(chave)
}
