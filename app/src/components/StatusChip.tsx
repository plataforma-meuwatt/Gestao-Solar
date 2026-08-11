import { StyleSheet, Text, View } from 'react-native'

import { chipDoTom, fontes, raio, type Tom } from '@/theme/tokens'

/** Chip de estado. A receita de cor (fundo 10%, borda 33%, texto cheio) mora nos tokens. */
export function StatusChip({ tom, texto }: { tom: Tom; texto: string }) {
  const { backgroundColor, borderColor, color } = chipDoTom(tom)
  return (
    <View style={[estilos.chip, { backgroundColor, borderColor }]}>
      <Text style={[estilos.texto, { color }]}>{texto}</Text>
    </View>
  )
}

const estilos = StyleSheet.create({
  chip: {
    borderWidth: 1,
    borderRadius: raio.chip,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  texto: { fontFamily: fontes.uiMedio, fontSize: 12 },
})
