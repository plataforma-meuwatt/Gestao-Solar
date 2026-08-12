/**
 * Visualizador de PDF.
 *
 * Uma barra fina de 48 pt e nada mais por cima do papel — o documento é o conteúdo, não
 * uma prévia dentro do app.
 *
 * O miolo aqui é uma **maquete das páginas**. O visualizador de verdade entra na Fase 5:
 * pdf.js dentro de uma WebView, com a biblioteca cacheada em disco para continuar
 * funcionando offline. Não se entrega o arquivo a um app externo — no Android isso dá
 * tela preta silenciosa, e foi por isso que o app de campo do meuPlano passou a renderizar
 * PDF por conta própria.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Num } from '@/components/base'
import { cores, espaco, fontes, papel, TOQUE_MIN } from '@/theme/tokens'

export default function Documento() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const insets = useSafeAreaInsets()

  return (
    <View style={[estilos.raiz, { paddingTop: insets.top }]}>
      <View style={estilos.barra}>
        <Pressable onPress={() => router.back()} hitSlop={12} style={estilos.voltar}>
          <View style={estilos.seta} />
        </Pressable>
        <View style={estilos.miolo}>
          <Text style={estilos.titulo} numberOfLines={1}>
            Relatório de Geração
          </Text>
          <Num style={estilos.pagina}>3 de 13</Num>
        </View>
        <Pressable hitSlop={10}>
          <Text style={estilos.compartilhar}>Compartilhar</Text>
        </Pressable>
      </View>

      <ScrollView
        style={estilos.papelArea}
        contentContainerStyle={estilos.papelConteudo}
        showsVerticalScrollIndicator={false}
      >
        <PaginaMaquete grande />
        <PaginaMaquete />
        <Text style={estilos.aviso}>
          Maquete das páginas ({id}). O documento real é renderizado na Fase 5, por pdf.js
          dentro de uma WebView.
        </Text>
      </ScrollView>
    </View>
  )
}

/** Uma folha branca com blocos de texto e figura, na proporção de um A4. */
function PaginaMaquete({ grande }: { grande?: boolean }) {
  return (
    <View style={estilos.pagina1}>
      <View style={[estilos.blocoTitulo, grande ? estilos.tituloLargo : estilos.tituloCurto]} />
      {grande ? <View style={estilos.blocoSubtitulo} /> : null}
      <View style={[estilos.linha, { width: '100%' }]} />
      <View style={[estilos.linha, { width: '96%' }]} />
      {grande ? <View style={[estilos.linha, { width: '88%' }]} /> : null}
      <View style={[estilos.figura, { height: grande ? 96 : 150 }]} />
      {grande ? (
        <>
          <View style={[estilos.linha, { width: '100%' }]} />
          <View style={[estilos.linha, { width: '72%' }]} />
          <View style={[estilos.linha, { width: '100%' }]} />
          <View style={[estilos.linha, { width: '64%' }]} />
          <View style={[estilos.figura, { height: 120 }]} />
        </>
      ) : null}
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.painelFlutuante },

  barra: {
    height: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: espaco.md,
    backgroundColor: cores.painelFlutuante,
    borderBottomWidth: 1,
    borderBottomColor: cores.borda,
  },
  voltar: { width: 26, height: TOQUE_MIN, alignItems: 'flex-start', justifyContent: 'center' },
  seta: {
    width: 11,
    height: 11,
    borderLeftWidth: 2,
    borderBottomWidth: 2,
    borderColor: cores.textoForte,
    transform: [{ rotate: '45deg' }],
    marginLeft: 4,
  },
  miolo: { flex: 1, minWidth: 0 },
  titulo: { fontFamily: fontes.uiSemi, fontSize: 14, color: cores.textoForte },
  pagina: { fontSize: 11, color: cores.textoFraco },
  compartilhar: { fontFamily: fontes.uiSemi, fontSize: 13, color: cores.textoAmbar },

  // Fundo mais claro que o app: papel branco sobre preto puro cansa a vista.
  papelArea: { flex: 1, backgroundColor: cores.fundoPapel },
  papelConteudo: { padding: 12, paddingHorizontal: 14, gap: 12 },

  pagina1: {
    backgroundColor: papel.folha,
    borderRadius: 2,
    paddingVertical: 28,
    paddingHorizontal: 26,
    gap: 9,
  },
  blocoTitulo: { height: 14, borderRadius: 2, backgroundColor: papel.titulo },
  tituloLargo: { width: '58%' },
  tituloCurto: { width: '44%', height: 11, marginBottom: 8 },
  blocoSubtitulo: {
    width: '34%',
    height: 8,
    borderRadius: 2,
    backgroundColor: papel.subtitulo,
    marginBottom: 10,
  },
  linha: { height: 7, borderRadius: 2, backgroundColor: papel.texto },
  figura: { borderRadius: 3, backgroundColor: papel.figura, marginVertical: 10 },

  aviso: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    lineHeight: 17,
    color: cores.textoFraco,
    textAlign: 'center',
    paddingVertical: espaco.md,
  },
})
