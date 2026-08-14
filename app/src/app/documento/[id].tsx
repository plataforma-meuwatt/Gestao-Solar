/**
 * Visualizador de PDF.
 *
 * Uma barra fina e nada mais por cima do papel — o documento é o conteúdo, não uma prévia
 * dentro do app.
 *
 * O que estava aqui era uma **maquete**: duas folhas brancas desenhadas com blocos de
 * texto falsos, o título fixo "Relatório de Geração" para qualquer documento e um
 * contador "3 de 13" idêntico para todo cliente — o único número literal que sobreviveu
 * no aplicativo, e logo acima do aviso que confessava a encenação. O PDF real nunca era
 * buscado, embora o endpoint (`/api/v1/documents/{id}/file`) já estivesse pronto e
 * autorizado.
 *
 * Agora o arquivo é carregado de verdade, por uma `WebView` apontando para o BFF. Ela não
 * passa pelos interceptadores do axios, então a sessão vai em **cabeçalho** — nunca na
 * URL, que entra em log de servidor, histórico e relatório de erro. A rota confere o
 * escopo antes de servir os bytes.
 *
 * Nada de entregar o arquivo a um app externo: no Android isso dá tela preta silenciosa.
 * "Compartilhar" abre o share sheet nativo, que é outra coisa.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { WebView } from 'react-native-webview'

import { EstadoVazio } from '@/components/base'
import { urlDoArquivo } from '@/features/documentos'
import { tokenDaSessao } from '@/lib/api'
import { cores, espaco, fontes, TOQUE_MIN } from '@/theme/tokens'

const NOME_DA_PECA: Record<string, string> = {
  geracao: 'Relatório de Geração',
  paradas: 'Anexo de Paradas',
}

export default function Documento() {
  const { id, tipo } = useLocalSearchParams<{ id: string; tipo?: string }>()
  const insets = useSafeAreaInsets()
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState<string | null>(null)

  const peca = tipo ?? 'geracao'
  const url = id ? urlDoArquivo(Number(id), peca) : null

  return (
    <View style={[estilos.raiz, { paddingTop: insets.top }]}>
      <View style={estilos.barra}>
        <Pressable onPress={() => router.back()} hitSlop={12} style={estilos.voltar}>
          <View style={estilos.seta} />
        </Pressable>
        <View style={estilos.miolo}>
          {/* O título é a peça que se pediu, não um rótulo fixo: abrir o Anexo de
              Paradas mostrava "Relatório de Geração". */}
          <Text style={estilos.titulo} numberOfLines={1}>
            {NOME_DA_PECA[peca] ?? 'Documento'}
          </Text>
        </View>
      </View>

      {!url || erro ? (
        <View style={estilos.centro}>
          <EstadoVazio
            tom="parado"
            titulo="Não deu para abrir"
            descricao={erro ?? 'Documento não encontrado.'}
            acao={{ titulo: 'Voltar', onPress: () => router.back() }}
          />
        </View>
      ) : (
        <>
          {/* No navegador a WebView vira um iframe, e alguns visualizadores de PDF do
              desktop o bloqueiam. O aplicativo, que é o alvo, usa a WebView nativa. */}
          <WebView
            source={{
              uri: url,
              headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
            }}
            style={estilos.papel}
            originWhitelist={['*']}
            onLoadEnd={() => setCarregando(false)}
            onError={() => {
              setCarregando(false)
              setErro('O arquivo não pôde ser carregado.')
            }}
            onHttpError={(e) => {
              setCarregando(false)
              const s = e.nativeEvent.statusCode
              setErro(
                s === 404
                  ? 'Este documento não está disponível para a sua conta.'
                  : `O servidor respondeu ${s}.`,
              )
            }}
          />
          {carregando ? (
            <View style={estilos.carregando} pointerEvents="none">
              <ActivityIndicator color={cores.ambar} />
              <Text style={estilos.carregandoTexto}>
                Abrindo o documento{Platform.OS === 'web' ? ' (melhor no aplicativo)' : ''}…
              </Text>
            </View>
          ) : null}
        </>
      )}
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo },
  barra: {
    height: 48,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: espaco.md,
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: cores.bordaFraca,
  },
  voltar: { width: 26, height: TOQUE_MIN, justifyContent: 'center' },
  seta: {
    width: 11,
    height: 11,
    borderLeftWidth: 2,
    borderBottomWidth: 2,
    borderColor: cores.textoForte,
    transform: [{ rotate: '45deg' }],
    marginLeft: 4,
  },
  miolo: { flex: 1 },
  titulo: { fontFamily: fontes.uiSemi, fontSize: 14.5, color: cores.textoForte },

  papel: { flex: 1, backgroundColor: cores.fundo },
  centro: { flex: 1, justifyContent: 'center' },
  carregando: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    top: 48,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: cores.fundo,
  },
  carregandoTexto: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo },
})
