/**
 * Tela cheia com zoom, para qualquer gráfico.
 *
 * Num celular em pé, um gráfico tem ~330 px de largura. Uma série de 5 em 5 minutos tem
 * mais de cem pontos: eles se atropelam, e o toque que lê o valor erra de bucket porque
 * cada um ocupa menos de três pixels. Ampliar não é enfeite — é o que torna a série densa
 * legível.
 *
 * O zoom é **horizontal**. O eixo do tempo é o que está espremido; a altura já cabe. Ampliar
 * os dois lados exigiria rolagem vertical dentro do gráfico e perderia a linha de base, que
 * é a referência de leitura.
 *
 * O pinça vem do `react-native-gesture-handler`, que já está no app. Os botões continuam
 * ali ao lado: pinçar com uma mão segurando o celular é desconfortável, e há quem não
 * descubra o gesto — um controle invisível não é um controle.
 */

import { useState } from 'react'
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector, GestureHandlerRootView } from 'react-native-gesture-handler'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { cores, espaco, fontes, raio, tipo } from '@/theme/tokens'

/** Limites do zoom. Abaixo de 1 o gráfico ficaria menor que a tela — não há o que ganhar. */
const MIN = 1
const MAX = 8

export function GraficoExpansivel({
  titulo,
  children,
  alturaCheia = 260,
}: {
  titulo: string
  /**
   * O gráfico, como função da altura. É função e não elemento porque ele é desenhado
   * DUAS vezes — embutido no card e ampliado na folha — com alturas diferentes; um
   * elemento já montado ficaria preso ao tamanho de origem.
   *
   * A largura não entra no contrato: os gráficos se medem sozinhos pelo `onLayout`, e
   * dentro da folha o contêiner já é `base × zoom`. Passá-la seria duplicar a verdade.
   */
  children: (altura: number | undefined) => React.ReactNode
  alturaCheia?: number
}) {
  const [aberto, setAberto] = useState(false)

  return (
    <>
      <View style={estilos.cabeca}>
        <View style={estilos.espacador} />
        <Pressable onPress={() => setAberto(true)} hitSlop={10} style={estilos.botaoExpandir}>
          <Text style={estilos.botaoTexto}>expandir</Text>
        </Pressable>
      </View>

      {children(undefined)}

      <Modal
        visible={aberto}
        animationType="slide"
        onRequestClose={() => setAberto(false)}
        // Sem isto o Android fecha o app no botão voltar em vez de fechar a folha.
        transparent={false}
      >
        <TelaCheia titulo={titulo} altura={alturaCheia} onFechar={() => setAberto(false)}>
          {children}
        </TelaCheia>
      </Modal>
    </>
  )
}

function TelaCheia({
  titulo,
  altura,
  onFechar,
  children,
}: {
  titulo: string
  altura: number
  onFechar: () => void
  children: (altura: number | undefined) => React.ReactNode
}) {
  const insets = useSafeAreaInsets()
  const [base, setBase] = useState(0)
  const [zoom, setZoom] = useState(1)
  // O pinça precisa saber de onde partiu: `scale` do gesto é relativo ao início dele.
  const [ancora, setAncora] = useState(1)

  const limitar = (v: number) => Math.min(MAX, Math.max(MIN, v))

  /*
   * `runOnJS(true)` NÃO é detalhe de performance — é o que impede o app de fechar.
   *
   * Com o `react-native-reanimated` instalado, os callbacks do gesto viram worklets e
   * rodam na thread de UI. `setZoom` e `setAncora` são closures de JavaScript comum:
   * chamá-las de dentro de um worklet estoura na hora, e o sintoma é o aplicativo
   * fechando ao abrir o gráfico em tela cheia. Com a marca, o gesto entrega os eventos
   * na thread de JS, onde `setState` existe.
   */
  const pinca = Gesture.Pinch()
    .runOnJS(true)
    .onStart(() => setAncora(zoom))
    .onUpdate((e) => setZoom(limitar(ancora * e.scale)))

  const largura = base > 0 ? base * zoom : undefined

  return (
    <GestureHandlerRootView style={estilos.raiz}>
      <View style={[estilos.barra, { paddingTop: insets.top + espaco.xs }]}>
        <Text style={estilos.titulo} numberOfLines={1}>
          {titulo}
        </Text>
        <View style={estilos.espacador} />
        <Pressable onPress={onFechar} hitSlop={12} style={estilos.botaoExpandir}>
          <Text style={estilos.botaoTexto}>fechar</Text>
        </Pressable>
      </View>

      <View style={estilos.medida} onLayout={(e) => setBase(e.nativeEvent.layout.width)}>
        <GestureDetector gesture={pinca}>
          {/*
           * A rolagem horizontal é o que permite alcançar o gráfico ampliado. Fica
           * desligada em 1× para o pinça não competir com ela quando não há o que rolar.
           */}
          <ScrollView
            horizontal
            scrollEnabled={zoom > 1}
            showsHorizontalScrollIndicator={zoom > 1}
            contentContainerStyle={{ width: largura ?? '100%' }}
          >
            <View style={estilos.miolo}>{children(altura)}</View>
          </ScrollView>
        </GestureDetector>
      </View>

      <View style={[estilos.controles, { paddingBottom: insets.bottom + espaco.sm }]}>
        <Botao texto="−" onPress={() => setZoom(limitar(zoom / 1.5))} inerte={zoom <= MIN} />
        <Pressable onPress={() => setZoom(1)} hitSlop={8} style={estilos.nivel}>
          <Text style={estilos.nivelTexto}>{zoom.toFixed(1)}×</Text>
          <Text style={estilos.nivelDica}>toque para voltar ao normal</Text>
        </Pressable>
        <Botao texto="+" onPress={() => setZoom(limitar(zoom * 1.5))} inerte={zoom >= MAX} />
      </View>
    </GestureHandlerRootView>
  )
}

function Botao({
  texto,
  onPress,
  inerte,
}: {
  texto: string
  onPress: () => void
  inerte?: boolean
}) {
  return (
    <Pressable
      onPress={inerte ? undefined : onPress}
      hitSlop={10}
      style={[estilos.zoomBotao, inerte && estilos.zoomBotaoInerte]}
    >
      <Text style={[estilos.zoomTexto, inerte && estilos.zoomTextoInerte]}>{texto}</Text>
    </Pressable>
  )
}

const estilos = StyleSheet.create({
  cabeca: { flexDirection: 'row', alignItems: 'center' },
  espacador: { flex: 1 },
  botaoExpandir: {
    paddingHorizontal: espaco.xs,
    paddingVertical: 2,
    borderRadius: raio.chip,
    backgroundColor: cores.superficieElevada,
  },
  botaoTexto: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoCorpo },

  raiz: { flex: 1, backgroundColor: cores.fundo },
  barra: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: espaco.md,
    paddingBottom: espaco.xs,
    gap: espaco.xs,
  },
  titulo: { ...tipo.tituloFaixa, color: cores.textoForte, flexShrink: 1 },

  medida: { flex: 1, justifyContent: 'center' },
  miolo: { flex: 1, justifyContent: 'center', paddingHorizontal: espaco.md },

  controles: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: espaco.md,
    paddingTop: espaco.sm,
  },
  zoomBotao: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: cores.superficieElevada,
  },
  zoomBotaoInerte: { opacity: 0.35 },
  zoomTexto: { fontFamily: fontes.ui, fontSize: 20, color: cores.textoForte, lineHeight: 24 },
  zoomTextoInerte: { color: cores.textoFraco },

  nivel: { alignItems: 'center', minWidth: 140 },
  nivelTexto: { fontFamily: fontes.mono, fontSize: 14, color: cores.textoForte },
  nivelDica: { fontFamily: fontes.ui, fontSize: 10, color: cores.textoFraco },
})
