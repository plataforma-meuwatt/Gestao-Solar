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

import { Barreira } from '@/components/Barreira'
import { moduloNativo } from '@/lib/nativo'
import { cores, espaco, fontes, raio, tipo } from '@/theme/tokens'

/**
 * O girar da tela é NATIVO — e nativo não chega por OTA.
 *
 * `expo-screen-orientation` entrou depois do último APK distribuído, e importá-lo no topo
 * deste arquivo derrubava as três telas que o carregam (a usina, os equipamentos dela e o
 * equipamento) em todo aparelho com binário anterior. Carregado por aqui, o aparelho antigo
 * perde só o girar: a folha abre em retrato, com pinça e botões funcionando.
 */
type Orientacao = typeof import('expo-screen-orientation')
const orientacao = () =>
  moduloNativo<Orientacao>('expo-screen-orientation', () =>
    // `require` de propósito: `import` no topo é justamente o que derrubava a tela em
    // binário sem o módulo, e `import()` assíncrono não serve dentro de um efeito.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('expo-screen-orientation'),
  )

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

  /*
   * A ORIENTAÇÃO MUDA FORA DA FOLHA — antes de ela existir, e depois de ela sumir.
   *
   * O aplicativo é travado em retrato no `app.json`, o que vira `screenOrientation` no
   * manifesto do Android. Destravar isso em tempo de execução com um `Modal` JÁ montado
   * faz o sistema recriar a Activity por baixo de uma folha que continua aberta — e o
   * aplicativo fecha. Era exatamente o que acontecia desde que o girar entrou (`07c4b18`):
   * o `unlockAsync` morava num efeito DENTRO da folha, ou seja, no pior momento possível.
   *
   * Destravando antes de abrir e retravando depois de fechar, a troca acontece com uma
   * árvore estável dos dois lados, e o girar continua funcionando como o dono pediu.
   */
  const abrir = () => {
    const so = orientacao()
    if (!so) return setAberto(true) // sem o módulo, a folha abre em retrato — e só
    so.unlockAsync()
      .catch(() => {}) // aparelho que recusa destravar não impede de ver o gráfico
      .finally(() => setAberto(true))
  }

  const fechar = () => {
    setAberto(false)
    const so = orientacao()
    if (so) void so.lockAsync(so.OrientationLock.PORTRAIT_UP).catch(() => {})
  }

  return (
    <>
      <View style={estilos.cabeca}>
        <View style={estilos.espacador} />
        <Pressable onPress={abrir} hitSlop={10} style={estilos.botaoExpandir}>
          <Text style={estilos.botaoTexto}>expandir</Text>
        </Pressable>
      </View>

      {children(undefined)}

      <Modal
        visible={aberto}
        animationType="slide"
        onRequestClose={fechar}
        // Sem isto o Android fecha o app no botão voltar em vez de fechar a folha.
        transparent={false}
        // iOS: sem declarar as orientações aceitas, a folha continua em retrato mesmo
        // com o aparelho deitado. No Android quem manda é o `ScreenOrientation`, e a
        // propriedade é ignorada — declarar as duas cobre os dois sistemas.
        supportedOrientations={['portrait', 'landscape']}
      >
        {/* A folha vai dentro de uma barreira própria: um gráfico que quebre ao ampliar
            mostra o motivo e deixa fechar, em vez de derrubar a tela inteira por trás. */}
        <Barreira nome="o gráfico ampliado">
          <TelaCheia titulo={titulo} altura={alturaCheia} onFechar={fechar}>
            {children}
          </TelaCheia>
        </Barreira>
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

  /*
   * Deitar o celular é o zoom que não custa nada: o eixo espremido é o horizontal, e virar
   * o aparelho quase dobra a largura útil antes de qualquer pinça. Quem destrava e retrava
   * é o `GraficoExpansivel`, antes de abrir e depois de fechar — ver a razão lá.
   */
  const [zoom, setZoom] = useState(1)
  // O pinça precisa saber de onde partiu: `scale` do gesto é relativo ao início dele.
  const [ancora, setAncora] = useState(1)
  const [alturaUtil, setAlturaUtil] = useState<number | null>(null)

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

      <View
        style={estilos.medida}
        onLayout={(e) => {
          setBase(e.nativeEvent.layout.width)
          // Em paisagem sobra pouca altura: descontar a barra e os controles evita o
          // gráfico empurrar os botões de zoom para fora da tela.
          setAlturaUtil(Math.max(120, e.nativeEvent.layout.height - espaco.md))
        }}
      >
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
            <View style={estilos.miolo}>{children(alturaUtil ?? altura)}</View>
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
