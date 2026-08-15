/**
 * Stack raiz.
 *
 * Duas coisas precisam estar prontas antes de qualquer pixel aparecer:
 *
 * - a **sessão**, senão o app pisca a tela de login para quem já está logado;
 * - as **fontes**, porque toda a régua tipográfica assume Figtree e IBM Plex Mono — com
 *   a fonte de sistema no lugar, os KPIs saem com outra largura e a tela remonta na
 *   frente do usuário quando a face real chega.
 */

import { useFonts } from 'expo-font'
import { Stack } from 'expo-router'
import * as SplashScreen from 'expo-splash-screen'
import { StatusBar } from 'expo-status-bar'
import { useEffect } from 'react'
import { View } from 'react-native'
import { QueryClientProvider } from '@tanstack/react-query'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { Barreira } from '@/components/Barreira'
import { MolduraCelular } from '@/components/MolduraCelular'
import { aoDeslogar } from '@/lib/api'
import { queryClient } from '@/lib/consulta'
import { useAuth } from '@/store/auth'
import { cores } from '@/theme/tokens'

// A splash fica de pé até a sessão e as fontes estarem prontas — e quem a esconde é o
// código, não a plataforma. Sem isto o fim da abertura é uma corrida: se o React demora
// mais que o sistema, o que se vê é o fundo `#02061A` sem nada em cima, que se lê como
// "app travado". O `catch` cobre o caso de a splash já ter sido escondida.
void SplashScreen.preventAutoHideAsync().catch(() => {})

export default function LayoutRaiz() {
  const hidratar = useAuth((s) => s.hidratar)
  const hidratado = useAuth((s) => s.hidratado)
  const sair = useAuth((s) => s.sair)

  const [fontesProntas] = useFonts({
    Figtree: require('../../assets/fonts/Figtree-400.ttf'),
    'Figtree-Medium': require('../../assets/fonts/Figtree-500.ttf'),
    'Figtree-SemiBold': require('../../assets/fonts/Figtree-600.ttf'),
    'Figtree-Bold': require('../../assets/fonts/Figtree-700.ttf'),
    IBMPlexMono: require('../../assets/fonts/IBMPlexMono-500.ttf'),
    'IBMPlexMono-SemiBold': require('../../assets/fonts/IBMPlexMono-600.ttf'),
  })

  useEffect(() => {
    void hidratar()
    aoDeslogar(() => void sair())
  }, [hidratar, sair])

  const pronto = hidratado && fontesProntas

  useEffect(() => {
    if (pronto) void SplashScreen.hideAsync().catch(() => {})
  }, [pronto])

  // Fundo liso enquanto espera: é a splash continuando, não uma tela vazia.
  if (!pronto) {
    return <View style={{ flex: 1, backgroundColor: cores.fundo }} />
  }

  return (
    <MolduraCelular>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <StatusBar style="light" />
          {/* A barreira fica DENTRO dos provedores e por fora do Stack: uma tela que
              quebra não pode levar junto a navegação nem o cliente de dados. */}
          <Barreira nome="o aplicativo">
            <Stack
              screenOptions={{
                headerShown: false,
                animation: 'slide_from_right',
                contentStyle: { backgroundColor: cores.fundo },
              }}
            >
              <Stack.Screen name="(tabs)" />
              <Stack.Screen name="login" options={{ animation: 'fade' }} />
              <Stack.Screen name="perfil" options={{ animation: 'slide_from_left' }} />
            </Stack>
          </Barreira>
        </QueryClientProvider>
      </SafeAreaProvider>
    </MolduraCelular>
  )
}
