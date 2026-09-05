/**
 * O botão que abre um PDF do BFF — a ficha da tarefa, a OS inteira, o cronograma.
 *
 * Este botão **saía do aplicativo**: baixava o arquivo e o entregava ao compartilhamento do
 * sistema, porque o WebView do Android não desenha PDF — aponta-se a `WebView` para o
 * arquivo, o `onLoadEnd` dispara, a tela sai do carregando e o dono fica olhando uma folha
 * branca para um documento que existe e está autorizado. Com o pdf.js embutido
 * (`components/LeitorPdf`) o desenho passou a ser possível aqui dentro, e o caminho externo
 * virou o segundo botão em vez do único.
 *
 * ## Por que ele usa o `LeitorPdf`, e não uma tela própria
 *
 * Porque senão nasceria a **terceira** cópia do caminho do PDF. Já houve duas — este
 * componente e a tela de documento —, com o mesmo defeito nas duas, e foi por isso que o
 * transporte virou `lib/pdf.ts`. O desenho não pode repetir a história: baixar, montar a
 * página, contar o que foi desenhado, mostrar o erro do servidor palavra por palavra e
 * oferecer o "Abrir em outro app" é tudo do `LeitorPdf`. A tela de relatório monta a mesma
 * peça em cima de um cabeçalho; aqui ela é montada dentro de uma folha, porque o botão vive
 * no meio de outra tela (a OS, a tarefa) e empurrar uma rota nova roubaria o lugar de onde
 * a pessoa veio.
 *
 * ## O que NÃO mudou, de propósito
 *
 * As propriedades. `url`, `arquivo`, `titulo` e `rotulo` são as mesmas de antes — a OS, a
 * tarefa e o cronograma continuam chamando exatamente como chamavam. A troca do destino é
 * interna; se fosse contrato, três telas que não são desta entrega precisariam mudar junto.
 */

import { useState } from 'react'
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Botao } from '@/components/base'
import { LeitorPdf } from '@/components/LeitorPdf'
import { cores, espaco, fontes, TOQUE_MIN } from '@/theme/tokens'

export function AbrirPdf({
  url,
  arquivo,
  titulo,
  rotulo = 'Abrir PDF',
}: {
  url: string
  /** Nome do arquivo em cache. Sem extensão o Android não sabe o que abrir. */
  arquivo: string
  /** O que aparece no cabeçalho da folha e no diálogo do sistema. */
  titulo: string
  rotulo?: string
}) {
  const [aberto, setAberto] = useState(false)

  return (
    <View style={estilos.raiz}>
      <Botao titulo={rotulo} onPress={() => setAberto(true)} />

      <Modal
        visible={aberto}
        animationType="slide"
        // O botão de voltar do Android fecha a folha em vez de sair da tela de trás.
        onRequestClose={() => setAberto(false)}
        presentationStyle="fullScreen"
      >
        <FolhaDoLeitor url={url} arquivo={arquivo} titulo={titulo} aoFechar={() => setAberto(false)} />
      </Modal>
    </View>
  )
}

/**
 * A folha: cabeçalho com o nome do documento e o fechar, e o leitor ocupando o resto.
 *
 * O `LeitorPdf` é só o miolo — ele não desenha cabeçalho nenhum, de propósito, para servir
 * tanto a esta folha quanto à tela de relatório sem que uma das duas tenha de esconder
 * pedaço da outra.
 *
 * Enquanto `aberto` é falso o leitor **não existe na árvore**: sem isso, toda tela de OS e
 * de tarefa baixaria o PDF ao abrir, para ninguém ver — e é a tela que o técnico abre com a
 * rede do sítio.
 */
function FolhaDoLeitor({
  url,
  arquivo,
  titulo,
  aoFechar,
}: {
  url: string
  arquivo: string
  titulo: string
  aoFechar: () => void
}) {
  const insets = useSafeAreaInsets()

  return (
    <View style={[estilos.folha, { paddingTop: insets.top }]}>
      <View style={estilos.barra}>
        <Text style={estilos.titulo} numberOfLines={1}>
          {titulo}
        </Text>
        <Pressable
          onPress={aoFechar}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Fechar"
          style={estilos.fechar}
        >
          <Text style={estilos.fecharTexto}>Fechar</Text>
        </Pressable>
      </View>

      <LeitorPdf url={url} arquivo={arquivo} titulo={titulo} />
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { gap: espaco.xs },

  folha: { flex: 1, backgroundColor: cores.fundo },
  barra: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: espaco.md,
    paddingVertical: 6,
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: cores.bordaFraca,
  },
  titulo: { flex: 1, fontFamily: fontes.uiSemi, fontSize: 14.5, color: cores.textoForte },
  fechar: { height: TOQUE_MIN, justifyContent: 'center' },
  fecharTexto: { fontFamily: fontes.uiSemi, fontSize: 13, color: cores.ambar },
})
