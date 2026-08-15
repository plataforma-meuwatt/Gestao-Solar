/**
 * As cinco abas.
 *
 * Geração e manutenção NÃO são abas: vivem dentro da usina. A barra responde
 * "que assunto?", não "que tela?".
 *
 * Os ícones são círculos vazados, como na prancha — placeholders declarados. Entram os
 * ícones reais quando existirem; até lá, um círculo honesto é melhor que um glifo
 * emprestado de outra família visual.
 */

import { Redirect, Tabs } from 'expo-router'
import { StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { useAuth } from '@/store/auth'
import { ALTURA_TAB_BAR, cores, fontes } from '@/theme/tokens'

function IconeAba({ focada }: { focada: boolean }) {
  return (
    <View
      style={[estilos.icone, { borderColor: focada ? cores.ambar : cores.iconeInativo }]}
    />
  )
}

export default function LayoutAbas() {
  const token = useAuth((s) => s.token)
  const insets = useSafeAreaInsets()
  if (!token) return <Redirect href="/login" />

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: cores.ambar,
        tabBarInactiveTintColor: cores.textoRotulo,
        // A barra cresce pela margem do sistema em vez de ficar sob ela: no Android o
        // modo edge-to-edge é padrão desde o SDK 57, e sem isto os botões de navegação
        // do aparelho cobrem os rótulos das abas.
        tabBarStyle: [
          estilos.barra,
          { height: ALTURA_TAB_BAR + insets.bottom, paddingBottom: 10 + insets.bottom },
        ],
        tabBarItemStyle: estilos.item,
        tabBarLabelStyle: estilos.rotulo,
        tabBarIcon: ({ focused }) => <IconeAba focada={focused} />,
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Início' }} />
      <Tabs.Screen name="usinas" options={{ title: 'Usinas' }} />
      <Tabs.Screen name="documentos" options={{ title: 'Documentos' }} />
      <Tabs.Screen name="manutencao" options={{ title: 'Manutenção' }} />
      <Tabs.Screen name="assistente" options={{ title: 'Assistente' }} />
    </Tabs>
  )
}

const estilos = StyleSheet.create({
  // Altura e recuo inferior vêm do componente, somados à margem do sistema.
  barra: {
    backgroundColor: cores.painelFlutuante,
    borderTopColor: cores.borda,
    borderTopWidth: 1,
    paddingTop: 8,
  },
  item: { gap: 6 },
  icone: { width: 22, height: 22, borderRadius: 11, borderWidth: 2 },
  rotulo: { fontFamily: fontes.uiMedio, fontSize: 10, letterSpacing: 0.1 },
})
