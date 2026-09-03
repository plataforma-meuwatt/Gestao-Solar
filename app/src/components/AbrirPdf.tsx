/**
 * Baixar um PDF do BFF e entregá-lo ao aparelho.
 *
 * A lógica já existia dentro de `app/documento/[id].tsx`; com a OS e o cronograma
 * ganhando PDF, ela passaria a viver em três telas — e o dia em que o `PdfViewer`
 * embutido do CLAUDE.md existir, seriam três lugares para trocar. Aqui é um.
 *
 * Duas coisas que não são detalhe:
 *
 * **A sessão vai em CABEÇALHO, nunca na URL.** Token em query entra em log de servidor
 * e em histórico de navegador.
 *
 * **O share sheet é o caminho, não o atalho.** O WebView do Android não renderiza PDF:
 * aponta-se a `WebView` para o arquivo, o `onLoadEnd` dispara, a tela sai do carregando
 * e o dono fica olhando uma folha branca para um documento que existe e está
 * autorizado. Enquanto não houver pdf.js em disco, baixar e entregar ao sistema é o
 * caminho honesto — e é por isso que o botão diz o que vai fazer antes de fazer.
 */

import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'
import { useState } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import { Botao } from '@/components/base'
import { tokenDaSessao } from '@/lib/api'
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

  async function abrir() {
    setBaixando(true)
    setErro(null)
    try {
      const destino = new FileSystem.File(FileSystem.Paths.cache, arquivo)
      // Apaga antes: o upstream versiona o PDF por fingerprint, então um arquivo
      // antigo com o mesmo nome entregaria a versão de ontem sem avisar.
      if (destino.exists) destino.delete()

      const baixado = await FileSystem.File.downloadFileAsync(url, destino, {
        headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
      })

      if (!(await Sharing.isAvailableAsync())) {
        setErro('Este aparelho não tem com o que abrir PDF.')
        return
      }

      await Sharing.shareAsync(baixado.uri, {
        mimeType: 'application/pdf',
        dialogTitle: titulo,
        UTI: 'com.adobe.pdf',
      })
    } catch (e) {
      // O 502 é o BFF dizendo que o meuPlano não gerou — e é diferente de rede ruim.
      const msg = e instanceof Error ? e.message : ''
      setErro(
        /40[13]/.test(msg)
          ? 'Este documento não está disponível para a sua conta.'
          : /50[023]/.test(msg)
            ? 'O meuPlano não conseguiu gerar este PDF agora. Tente mais tarde.'
            : 'Não foi possível baixar. Verifique a conexão e tente de novo.',
      )
    } finally {
      setBaixando(false)
    }
  }

  return (
    <View style={estilos.raiz}>
      {baixando ? (
        <View style={estilos.carregando}>
          <ActivityIndicator color={cores.ambar} />
          <Text style={estilos.carregandoTexto}>Gerando o PDF…</Text>
        </View>
      ) : (
        <Botao titulo={rotulo} onPress={() => void abrir()} />
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
