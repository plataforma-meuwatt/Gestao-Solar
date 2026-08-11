/**
 * Cabeçalho grande que colapsa ao rolar — o princípio 5 do produto, e o comportamento que
 * amarra todas as telas.
 *
 * Expandido: título grande + subtítulo. Ao rolar, encolhe continuamente até uma faixa fina
 * com só a seta e o título. A transição acompanha o scroll (interpolação), nunca troca de
 * estado em degrau: o degrau é o que faz o cabeçalho "pular" e chamar atenção para si.
 *
 * A seta de voltar aparece em toda tela que não é aba raiz (`voltar`), sempre no mesmo
 * lugar — canto superior esquerdo.
 */

import { router } from 'expo-router'
import type { ReactNode } from 'react'
import {
  Animated,
  Pressable,
  StyleSheet,
  Text,
  View,
  useAnimatedValue,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { cores, espaco, tipo } from '@/theme/tokens'

const ALTURA_EXPANDIDA = 108
const ALTURA_FAIXA = 52
const CURSO = ALTURA_EXPANDIDA - ALTURA_FAIXA

export function TelaColapsavel({
  titulo,
  subtitulo,
  voltar,
  acaoDireita,
  children,
}: {
  titulo: string
  subtitulo?: string
  voltar?: boolean
  acaoDireita?: ReactNode
  children: ReactNode
}) {
  const insets = useSafeAreaInsets()
  const scroll = useAnimatedValue(0)

  const progresso = scroll.interpolate({
    inputRange: [0, CURSO],
    outputRange: [0, 1],
    extrapolate: 'clamp',
  })

  const alturaCabecalho = progresso.interpolate({
    inputRange: [0, 1],
    outputRange: [ALTURA_EXPANDIDA, ALTURA_FAIXA],
  })
  const opacidadeGrande = progresso.interpolate({ inputRange: [0, 0.6], outputRange: [1, 0] })
  const opacidadeFaixa = progresso.interpolate({ inputRange: [0.5, 1], outputRange: [0, 1] })

  const aoRolar = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    scroll.setValue(e.nativeEvent.contentOffset.y)
  }

  return (
    <View style={[estilos.raiz, { paddingTop: insets.top }]}>
      <Animated.View style={[estilos.cabecalho, { height: alturaCabecalho }]}>
        <View style={estilos.barra}>
          {voltar ? (
            <Pressable onPress={() => router.back()} hitSlop={12} style={estilos.voltar}>
              <Text style={estilos.seta}>‹</Text>
            </Pressable>
          ) : (
            <View style={estilos.voltar} />
          )}
          <Animated.Text
            style={[tipo.tituloColapsado, estilos.tituloFaixa, { opacity: opacidadeFaixa }]}
            numberOfLines={1}
          >
            {titulo}
          </Animated.Text>
          <View style={estilos.acao}>{acaoDireita}</View>
        </View>

        <Animated.View style={[estilos.blocoGrande, { opacity: opacidadeGrande }]}>
          <Text style={tipo.titulo} numberOfLines={1}>
            {titulo}
          </Text>
          {subtitulo ? <Text style={tipo.rotulo}>{subtitulo}</Text> : null}
        </Animated.View>
      </Animated.View>

      <Animated.ScrollView
        onScroll={aoRolar}
        scrollEventThrottle={16}
        contentContainerStyle={estilos.conteudo}
        showsVerticalScrollIndicator={false}
      >
        {children}
      </Animated.ScrollView>
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo },
  cabecalho: { justifyContent: 'flex-start', overflow: 'hidden' },
  barra: { height: ALTURA_FAIXA, flexDirection: 'row', alignItems: 'center' },
  // 44 pt é a área de toque mínima; a seta pequena não pode ter alvo pequeno.
  voltar: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  seta: { color: cores.textoForte, fontSize: 32, lineHeight: 34 },
  tituloFaixa: { flex: 1 },
  acao: { minWidth: 44, alignItems: 'flex-end', paddingRight: espaco.md },
  blocoGrande: { paddingHorizontal: espaco.md, gap: 2 },
  conteudo: { padding: espaco.md, gap: espaco.md, paddingBottom: espaco.xl },
})
