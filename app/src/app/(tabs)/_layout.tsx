/**
 * As cinco abas. Rótulo sempre visível sob o ícone; aba ativa em âmbar.
 *
 * Geração e manutenção NÃO são abas: vivem dentro da usina. A barra responde "que
 * assunto?", não "que tela?".
 */

import { Redirect, Tabs } from 'expo-router'

import { useAuth } from '@/store/auth'
import { ALTURA_TAB_BAR, cores, fontes } from '@/theme/tokens'

export default function LayoutAbas() {
  const token = useAuth((s) => s.token)
  if (!token) return <Redirect href="/login" />

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: cores.ambar,
        tabBarInactiveTintColor: cores.textoRotulo,
        tabBarStyle: {
          backgroundColor: cores.fundo,
          borderTopColor: cores.borda,
          height: ALTURA_TAB_BAR,
          paddingTop: 6,
          paddingBottom: 10,
        },
        tabBarLabelStyle: { fontFamily: fontes.uiMedio, fontSize: 11 },
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Início' }} />
      <Tabs.Screen name="usinas" options={{ title: 'Usinas' }} />
      <Tabs.Screen name="documentos" options={{ title: 'Documentos' }} />
      <Tabs.Screen name="financeiro" options={{ title: 'Financeiro' }} />
      <Tabs.Screen name="assistente" options={{ title: 'Assistente' }} />
    </Tabs>
  )
}
