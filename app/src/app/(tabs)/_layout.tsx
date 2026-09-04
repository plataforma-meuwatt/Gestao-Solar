/**
 * As cinco abas.
 *
 * Geração e manutenção NÃO são abas: vivem dentro da usina. A barra responde
 * "que assunto?", não "que tela?".
 *
 * Os ícones vivem em `components/icones.tsx`, desenhados em SVG. Eram círculos vazados —
 * placeholders declarados, honestos enquanto não havia desenho —, e a barra inteira dizia a
 * mesma coisa cinco vezes: só o rótulo separava uma aba da outra, e é o desenho que se
 * reconhece de relance, com o polegar já a caminho.
 */

import { Redirect, Tabs } from 'expo-router'
import { StyleSheet } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import {
  IconeAssistente,
  IconeDocumentos,
  IconeInicio,
  IconeManutencao,
  IconeUsinas,
} from '@/components/icones'
import { useAuth } from '@/store/auth'
import { ALTURA_TAB_BAR, cores, fontes } from '@/theme/tokens'

/** O ícone da aba focada acende no âmbar; o das outras fica no cinza de ícone inativo. */
const icone =
  (Desenho: (p: { cor: string }) => React.ReactElement) =>
  ({ focused }: { focused: boolean }) => (
    <Desenho cor={focused ? cores.ambar : cores.iconeInativo} />
  )

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
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Início', tabBarIcon: icone(IconeInicio) }} />
      <Tabs.Screen name="usinas" options={{ title: 'Usinas', tabBarIcon: icone(IconeUsinas) }} />
      <Tabs.Screen
        name="documentos"
        options={{ title: 'Documentos', tabBarIcon: icone(IconeDocumentos) }}
      />
      <Tabs.Screen
        name="manutencao"
        options={{ title: 'Manutenção', tabBarIcon: icone(IconeManutencao) }}
      />
      <Tabs.Screen
        name="assistente"
        options={{ title: 'Assistente', tabBarIcon: icone(IconeAssistente) }}
      />
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
  item: { gap: 4 },
  rotulo: { fontFamily: fontes.uiMedio, fontSize: 10, letterSpacing: 0.1 },
})
