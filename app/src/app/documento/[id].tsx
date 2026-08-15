/**
 * Abrir um documento.
 *
 * Esta tela já foi duas coisas erradas. Primeiro uma **maquete**: duas folhas A4
 * desenhadas com blocos de texto falsos e um "3 de 13" idêntico para todo cliente.
 * Depois uma `WebView` apontada para o PDF — o que parecia certo e é pior, porque falha
 * em silêncio: **o WebView do Android não renderiza PDF**. O `onLoadEnd` dispara mesmo
 * assim, a tela sai do carregando, e o dono fica olhando uma folha branca para um
 * documento que existe e está autorizado.
 *
 * Enquanto não houver o visualizador embutido que o CLAUDE.md descreve (pdf.js dentro de
 * WebView, com a biblioteca em disco para funcionar sem rede), o caminho honesto é este:
 * **baixar o arquivo e entregá-lo ao share sheet do sistema**, que sabe abrir PDF em
 * qualquer aparelho. A tela diz o que vai fazer antes de fazer, e diz quando falha.
 *
 * O download passa pelo BFF com a sessão em cabeçalho — nunca na URL, que entra em log de
 * servidor e em histórico.
 */

import { router, useLocalSearchParams } from 'expo-router'
import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'
import { useState } from 'react'
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Botao, EstadoVazio } from '@/components/base'
import { urlDoArquivo } from '@/features/documentos'
import { tokenDaSessao } from '@/lib/api'
import { cores, espaco, fontes, TOQUE_MIN } from '@/theme/tokens'

const NOME_DA_PECA: Record<string, string> = {
  geracao: 'Relatório de Geração',
  paradas: 'Anexo de Paradas',
}

type Estado = 'pronto' | 'baixando' | 'erro'

export default function Documento() {
  const { id, tipo } = useLocalSearchParams<{ id: string; tipo?: string }>()
  const insets = useSafeAreaInsets()
  const [estado, setEstado] = useState<Estado>('pronto')
  const [erro, setErro] = useState<string | null>(null)

  const peca = tipo ?? 'geracao'
  const nome = NOME_DA_PECA[peca] ?? 'Documento'

  async function abrir() {
    if (!id) return
    setEstado('baixando')
    setErro(null)
    try {
      const destino = new FileSystem.File(
        FileSystem.Paths.cache,
        `relatorio-${id}-${peca}.pdf`,
      )
      if (destino.exists) destino.delete()

      const baixado = await FileSystem.File.downloadFileAsync(
        urlDoArquivo(Number(id), peca),
        destino,
        { headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` } },
      )

      if (!(await Sharing.isAvailableAsync())) {
        setEstado('erro')
        setErro('Este aparelho não tem com o que abrir PDF.')
        return
      }

      await Sharing.shareAsync(baixado.uri, {
        mimeType: 'application/pdf',
        dialogTitle: nome,
        UTI: 'com.adobe.pdf',
      })
      setEstado('pronto')
    } catch (e) {
      setEstado('erro')
      setErro(
        e instanceof Error && /40[13]/.test(e.message)
          ? 'Este documento não está disponível para a sua conta.'
          : 'Não foi possível baixar o documento. Verifique a conexão e tente de novo.',
      )
    }
  }

  return (
    <View style={[estilos.raiz, { paddingTop: insets.top }]}>
      <View style={estilos.barra}>
        <Pressable onPress={() => router.back()} hitSlop={12} style={estilos.voltar}>
          <View style={estilos.seta} />
        </Pressable>
        <Text style={estilos.titulo} numberOfLines={1}>
          {nome}
        </Text>
      </View>

      {estado === 'erro' ? (
        <View style={estilos.centro}>
          <EstadoVazio
            tom="parado"
            titulo="Não deu para abrir"
            descricao={erro ?? 'Documento indisponível.'}
            acao={{ titulo: 'Tentar de novo', onPress: () => void abrir() }}
          />
        </View>
      ) : (
        <View style={estilos.centro}>
          <View style={estilos.miolo}>
            <Text style={estilos.explicacao}>
              O documento será baixado e aberto no leitor de PDF do seu aparelho.
            </Text>
            {estado === 'baixando' ? (
              <View style={estilos.carregando}>
                <ActivityIndicator color={cores.ambar} />
                <Text style={estilos.carregandoTexto}>Baixando…</Text>
              </View>
            ) : (
              <Botao titulo="Abrir documento" onPress={() => void abrir()} />
            )}
            {Platform.OS === 'web' ? (
              <Text style={estilos.nota}>No navegador, o arquivo abre em outra aba.</Text>
            ) : null}
          </View>
        </View>
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
  titulo: { flex: 1, fontFamily: fontes.uiSemi, fontSize: 14.5, color: cores.textoForte },

  centro: { flex: 1, justifyContent: 'center', paddingHorizontal: espaco.lg },
  miolo: { gap: espaco.md },
  explicacao: {
    fontFamily: fontes.ui,
    fontSize: 13.5,
    color: cores.textoCorpo,
    lineHeight: 20,
    textAlign: 'center',
  },
  carregando: { alignItems: 'center', gap: 10, paddingVertical: espaco.sm },
  carregandoTexto: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo },
  nota: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    color: cores.textoRotulo,
    textAlign: 'center',
  },
})
