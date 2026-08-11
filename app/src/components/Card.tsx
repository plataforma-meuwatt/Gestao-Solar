import type { ReactNode } from 'react'
import { StyleSheet, Text, View, type ViewStyle } from 'react-native'

import { cores, espaco, raio, tipo } from '@/theme/tokens'

/**
 * Superfície glass padrão. A separação vem da BORDA, não de sombra — sombra sobre um
 * fundo quase preto não aparece.
 */
export function Card({
  titulo,
  children,
  style,
}: {
  titulo?: string
  children: ReactNode
  style?: ViewStyle
}) {
  return (
    <View style={[estilos.card, style]}>
      {titulo ? <Text style={estilos.titulo}>{titulo}</Text> : null}
      {children}
    </View>
  )
}

const estilos = StyleSheet.create({
  card: {
    backgroundColor: cores.superficie,
    borderColor: cores.borda,
    borderWidth: 1,
    borderRadius: raio.card,
    padding: espaco.md,
    gap: espaco.sm,
  },
  titulo: { ...tipo.rotulo, textTransform: 'uppercase', letterSpacing: 0.6 },
})
