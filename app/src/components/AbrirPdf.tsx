/**
 * O botão que abre um PDF do BFF.
 *
 * O share sheet é o caminho, não o atalho: o WebView do Android não renderiza PDF — aponta-se
 * a `WebView` para o arquivo, o `onLoadEnd` dispara, a tela sai do carregando e o dono fica
 * olhando uma folha branca para um documento que existe e está autorizado. Enquanto não
 * houver pdf.js em disco, baixar e entregar ao sistema é o caminho honesto — e é por isso
 * que o botão diz o que vai fazer antes de fazer.
 *
 * O transporte e a mensagem de erro vivem em `lib/pdf.ts`, que é a mesma fonte usada pela
 * tela de documentos: a razão está lá.
 */

import { useState } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import { Botao } from '@/components/base'
import { abrirPdf } from '@/lib/pdf'
import { cores, espaco, fontes, tons } from '@/theme/tokens'

export function AbrirPdf({
  url,
  arquivo,
  titulo,
  rotulo = 'Abrir PDF',
}: {
  url: string
  /** Nome do arquivo em cache. Sem extensão o Android não sabe o que abrir. */
  arquivo: string
  /** O que aparece no diálogo do sistema. */
  titulo: string
  rotulo?: string
}) {
  const [baixando, setBaixando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  async function tocar() {
    setBaixando(true)
    setErro(null)
    setErro(await abrirPdf({ url, arquivo, titulo }))
    setBaixando(false)
  }

  return (
    <View style={estilos.raiz}>
      {baixando ? (
        <View style={estilos.carregando}>
          <ActivityIndicator color={cores.ambar} />
          <Text style={estilos.carregandoTexto}>Gerando o PDF…</Text>
        </View>
      ) : (
        <Botao titulo={rotulo} onPress={() => void tocar()} />
      )}
      {erro ? <Text style={estilos.erro}>{erro}</Text> : null}
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { gap: espaco.xs },
  carregando: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: espaco.xs, paddingVertical: 12 },
  carregandoTexto: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoRotulo },
  erro: { fontFamily: fontes.ui, fontSize: 12, color: tons.parado, lineHeight: 17 },
})
