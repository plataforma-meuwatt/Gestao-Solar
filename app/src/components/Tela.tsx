/**
 * A casca de toda tela: halo, cabeçalho colapsável e área rolável.
 *
 * O cabeçalho é UMA peça que encolhe de 108 para 52 pt conforme o scroll, não duas
 * telas diferentes — a interpolação acompanha o dedo, sem degrau. O avatar encolhe
 * junto (40 → 34) e o título grande dá lugar ao título de faixa.
 *
 * Nas abas raiz o canto superior esquerdo leva o avatar; nas telas de detalhe, a seta
 * de voltar. Nunca os dois, e sempre no mesmo lugar.
 */

import { router } from 'expo-router'
import { useRef, type ReactNode } from 'react'
import {
  Animated,
  Pressable,
  StyleSheet,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  type StyleProp,
  type ViewStyle,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { FaixaOffline, Halo } from '@/components/base'
import {
  ALTURA_TAB_BAR,
  CABECALHO,
  CURSO_CABECALHO,
  cores,
  espaco,
  fontes,
  tipo,
  TOQUE_MIN,
} from '@/theme/tokens'

export function Tela({
  titulo,
  subtitulo,
  voltar,
  avatar,
  offlineDesde,
  semRolagem,
  paraTabBar,
  children,
  contentStyle,
}: {
  titulo: string
  subtitulo?: ReactNode
  /** Telas de detalhe: seta no canto superior esquerdo. */
  voltar?: boolean
  /** Abas raiz: iniciais do usuário no canto superior esquerdo. */
  avatar?: { iniciais: string; temAviso?: boolean; onPress?: () => void }
  /** Preenchido quando a tela está mostrando cache; mostra a faixa cinza no topo. */
  offlineDesde?: string
  /** Para telas cujo conteúdo já rola por conta própria (lista virtualizada, chat). */
  semRolagem?: boolean
  /** Reserva o espaço da barra de abas no fim do conteúdo. */
  paraTabBar?: boolean
  children: ReactNode
  contentStyle?: StyleProp<ViewStyle>
}) {
  const insets = useSafeAreaInsets()
  // `useRef(new Animated.Value(0))` e não `useAnimatedValue`: o segundo é API recente do
  // React Native e o react-native-web ainda não a implementa, o que derruba a versão web
  // usada em desenvolvimento.
  const scroll = useRef(new Animated.Value(0)).current

  const progresso = scroll.interpolate({
    inputRange: [0, CURSO_CABECALHO],
    outputRange: [0, 1],
    extrapolate: 'clamp',
  })

  const alturaCabecalho = progresso.interpolate({
    inputRange: [0, 1],
    outputRange: [CABECALHO.expandido, CABECALHO.faixa],
  })
  const tamanhoAvatar = progresso.interpolate({
    inputRange: [0, 1],
    outputRange: [CABECALHO.avatar, CABECALHO.avatarMin],
  })
  // O bloco grande some mais rápido do que o cabeçalho encolhe (fator 1,6), senão o
  // título grande ainda estaria visível quando a faixa já o repetiu.
  const opacidadeGrande = progresso.interpolate({ inputRange: [0, 0.625], outputRange: [1, 0] })
  const deslocamentoGrande = progresso.interpolate({ inputRange: [0, 1], outputRange: [0, -10] })
  const opacidadeFaixa = progresso

  const aoRolar = (e: NativeSyntheticEvent<NativeScrollEvent>) =>
    scroll.setValue(e.nativeEvent.contentOffset.y)

  const cabecalho = (
    <Animated.View style={[estilos.cabecalho, { height: alturaCabecalho }]}>
      <View style={estilos.barraTopo}>
        {voltar ? (
          <Pressable onPress={() => router.back()} hitSlop={12} style={estilos.alvoCanto}>
            <View style={estilos.seta} />
          </Pressable>
        ) : avatar ? (
          <Pressable onPress={avatar.onPress} hitSlop={8} style={estilos.avatarAlvo}>
            <Animated.View
              style={[
                estilos.avatar,
                { width: tamanhoAvatar, height: tamanhoAvatar, borderRadius: tamanhoAvatar },
              ]}
            >
              <Text style={estilos.avatarTexto}>{avatar.iniciais}</Text>
            </Animated.View>
            {avatar.temAviso ? <View style={estilos.avatarAviso} /> : null}
          </Pressable>
        ) : (
          <View style={estilos.alvoCanto} />
        )}

        <Animated.Text
          style={[tipo.tituloFaixa, estilos.tituloFaixa, { opacity: opacidadeFaixa }]}
          numberOfLines={1}
        >
          {titulo}
        </Animated.Text>
      </View>

      <Animated.View
        style={[
          estilos.blocoGrande,
          { opacity: opacidadeGrande, transform: [{ translateY: deslocamentoGrande }] },
        ]}
      >
        <Text style={tipo.titulo} numberOfLines={1}>
          {titulo}
        </Text>
        {typeof subtitulo === 'string' ? (
          <Text style={estilos.subtitulo}>{subtitulo}</Text>
        ) : (
          subtitulo
        )}
      </Animated.View>
    </Animated.View>
  )

  return (
    <View style={[estilos.raiz, { paddingTop: insets.top }]}>
      <Halo />
      {offlineDesde ? <FaixaOffline desde={offlineDesde} /> : null}
      {cabecalho}

      {semRolagem ? (
        <View style={[estilos.conteudoFixo, contentStyle]}>{children}</View>
      ) : (
        <Animated.ScrollView
          onScroll={aoRolar}
          scrollEventThrottle={16}
          showsVerticalScrollIndicator={false}
          contentContainerStyle={[
            estilos.conteudo,
            paraTabBar && { paddingBottom: ALTURA_TAB_BAR + espaco.lg },
            contentStyle,
          ]}
        >
          {children}
        </Animated.ScrollView>
      )}
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo },

  cabecalho: {
    paddingHorizontal: espaco.md,
    overflow: 'hidden',
    borderBottomWidth: 1,
    borderBottomColor: cores.bordaFraca,
  },
  barraTopo: {
    height: CABECALHO.faixa,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  alvoCanto: {
    width: 26,
    height: TOQUE_MIN,
    alignItems: 'flex-start',
    justifyContent: 'center',
  },
  // A seta é um quadrado com duas bordas, girado — mesmo desenho do design.
  seta: {
    width: 11,
    height: 11,
    borderLeftWidth: 2,
    borderBottomWidth: 2,
    borderColor: cores.textoForte,
    transform: [{ rotate: '45deg' }],
    marginLeft: 4,
  },

  avatarAlvo: { justifyContent: 'center' },
  avatar: {
    borderWidth: 1,
    borderColor: cores.ambar,
    backgroundColor: cores.superficieElevada,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarTexto: { fontFamily: fontes.uiSemi, fontSize: 13, color: cores.textoAmbar },
  avatarAviso: {
    position: 'absolute',
    top: -1,
    right: -1,
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: cores.ambar,
    borderWidth: 2,
    borderColor: cores.fundo,
  },

  tituloFaixa: { flex: 1 },
  blocoGrande: { gap: 3 },
  subtitulo: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoRotulo },

  conteudo: { padding: espaco.md, gap: espaco.md, paddingBottom: espaco.lg },
  conteudoFixo: { flex: 1 },
})
