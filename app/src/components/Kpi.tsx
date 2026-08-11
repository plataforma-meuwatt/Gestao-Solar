import { StyleSheet, Text, View } from 'react-native'

import { cores, espaco, tipo, tons, type Tom } from '@/theme/tokens'

/**
 * Número grande, contexto pequeno — o princípio 2 do produto.
 *
 * O valor vem SEMPRE já formatado (helpers de `lib/format.ts`), em fonte mono com
 * `fontVariant: tabular-nums`: com fonte proporcional os dígitos mudam de largura e o
 * número treme a cada atualização.
 */
export function Kpi({
  rotulo,
  valor,
  unidade,
  contexto,
  tom,
  grande,
}: {
  rotulo: string
  valor: string
  unidade?: string
  contexto?: string
  tom?: Tom
  grande?: boolean
}) {
  const corValor = tom ? tons[tom] : cores.textoForte
  return (
    <View style={estilos.raiz}>
      <Text style={estilos.rotulo}>{rotulo}</Text>
      <View style={estilos.linha}>
        <Text
          style={[grande ? tipo.kpiGrande : tipo.kpi, { color: corValor }, estilos.tabular]}
          numberOfLines={1}
        >
          {valor}
        </Text>
        {unidade ? <Text style={estilos.unidade}>{unidade}</Text> : null}
      </View>
      {contexto ? <Text style={estilos.contexto}>{contexto}</Text> : null}
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { gap: 2, flexShrink: 1 },
  rotulo: { ...tipo.rotulo },
  linha: { flexDirection: 'row', alignItems: 'baseline', gap: espaco.xs },
  tabular: { fontVariant: ['tabular-nums'] },
  unidade: { ...tipo.rotulo, color: cores.textoCorpo },
  contexto: { ...tipo.rotulo, opacity: 0.75 },
})
