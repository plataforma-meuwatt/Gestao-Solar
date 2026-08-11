/**
 * Stack raiz. Hidrata a sessão antes de decidir qualquer rota — sem isso o app pisca a
 * tela de login para quem já está logado.
 */

import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { useEffect } from 'react'
import { View } from 'react-native'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { aoDeslogar } from '@/lib/api'
import { useAuth } from '@/store/auth'
import { cores } from '@/theme/tokens'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Dado de geração muda a cada poucos minutos; refazer a cada foco seria ruído.
      staleTime: 60_000,
      retry: 1,
    },
  },
})

export default function LayoutRaiz() {
  const hidratar = useAuth((s) => s.hidratar)
  const hidratado = useAuth((s) => s.hidratado)
  const sair = useAuth((s) => s.sair)

  useEffect(() => {
    void hidratar()
    aoDeslogar(() => void sair())
  }, [hidratar, sair])

  if (!hidratado) return <View style={{ flex: 1, backgroundColor: cores.fundo }} />

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerShown: false,
            animation: 'slide_from_right',
            contentStyle: { backgroundColor: cores.fundo },
          }}
        >
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="login" options={{ animation: 'fade' }} />
        </Stack>
      </QueryClientProvider>
    </SafeAreaProvider>
  )
}
