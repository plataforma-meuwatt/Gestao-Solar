/**
 * Moldura de celular para revisar o app no navegador do desktop.
 *
 * Só age na **web** e só quando a janela é larga: em tela estreita (ou no aparelho de
 * verdade) o app ocupa tudo, como deve. Em iOS e Android o componente é transparente.
 *
 * Existe porque revisar layout de celular numa janela de 1400 pt engana: cards esticam,
 * textos que quebrariam em duas linhas cabem numa só, e a barra de abas de 5 itens fica
 * folgada. As medidas são as mesmas do design — 390 × 844 pt, o iPhone 14.
 */

import type { ReactNode } from 'react'
import { Platform, StyleSheet, Text, useWindowDimensions, View } from 'react-native'

import { cores, fontes } from '@/theme/tokens'

const LARGURA = 390
const ALTURA = 844
/** Abaixo disto não sobra espaço para a moldura respirar — o app toma a tela inteira. */
const LIMIAR = 720

export function MolduraCelular({ children }: { children: ReactNode }) {
  const { width, height } = useWindowDimensions()

  const emModo = Platform.OS === 'web' && width >= LIMIAR
  if (!emModo) return <>{children}</>

  // Encolhe proporcionalmente se a janela for baixa, para o aparelho caber inteiro.
  const escala = Math.min(1, (height - 48) / ALTURA)

  return (
    <View style={estilos.palco}>
      <View style={[estilos.aparelho, { transform: [{ scale: escala }] }]}>{children}</View>
      <Text style={estilos.legenda}>
        390 × 844 pt · a moldura só aparece no navegador em janela larga
      </Text>
    </View>
  )
}

const estilos = StyleSheet.create({
  palco: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: cores.palco,
    gap: 12,
  },
  aparelho: {
    width: LARGURA,
    height: ALTURA,
    borderRadius: 30,
    borderWidth: 1,
    borderColor: cores.bordaForte,
    backgroundColor: cores.fundo,
    overflow: 'hidden',
  },
  legenda: { fontFamily: fontes.mono, fontSize: 11, color: cores.textoFraco },
})
