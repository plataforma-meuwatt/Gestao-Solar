/**
 * A folha que sobe, e o que vive dentro dela.
 *
 * Peça introduzida na rodada 2. Serve para escolhas curtas (gerar relatório) e para
 * detalhe que não merece uma tela inteira (fatura). Receita da prancha: véu preto a 55%
 * atrás, painel `#090E26` a 97% com raio 20 só no topo, e a alça de 38 × 4 pt que diz
 * "isto se arrasta para baixo".
 */

import type { ReactNode } from 'react'
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'

import { Chevron, StatusChip } from '@/components/base'
import { cores, espaco, fontes, raio, tomAlpha, tons, TOQUE_MIN } from '@/theme/tokens'

export function Folha({
  visivel,
  aoFechar,
  titulo,
  apoio,
  cabecalho,
  children,
}: {
  visivel: boolean
  aoFechar: () => void
  titulo?: string
  apoio?: string
  /** Substitui o par título/apoio quando o cabeçalho tem chip ou outro enfeite. */
  cabecalho?: ReactNode
  children: ReactNode
}) {
  return (
    <Modal visible={visivel} transparent animationType="slide" onRequestClose={aoFechar}>
      <View style={estilos.raiz}>
        {/* O véu fecha ao toque — é o gesto que todo mundo tenta primeiro. */}
        <Pressable style={estilos.veu} onPress={aoFechar} />
        <View style={estilos.painel}>
          <View style={estilos.alca} />
          {cabecalho ?? (
            <>
              {titulo ? <Text style={estilos.titulo}>{titulo}</Text> : null}
              {apoio ? <Text style={estilos.apoio}>{apoio}</Text> : null}
            </>
          )}
          <ScrollView showsVerticalScrollIndicator={false} bounces={false}>
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  )
}

/** Campo rotulado dentro da folha. */
export function CampoFolha({ rotulo, children, nota }: { rotulo: string; children: ReactNode; nota?: string }) {
  return (
    <View style={estilos.campo}>
      <Text style={estilos.rotuloCampo}>{rotulo}</Text>
      {children}
      {nota ? <Text style={estilos.nota}>{nota}</Text> : null}
    </View>
  )
}

/** Linha rótulo → valor, do detalhe da fatura. */
export function LinhaDetalhe({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <View style={estilos.linhaDetalhe}>
      <Text style={estilos.detalheRotulo}>{rotulo}</Text>
      {children}
    </View>
  )
}

/**
 * Selo de PDF: retângulo vermelho com "PDF" no pé, na proporção de uma folha.
 * Não é ícone de biblioteca — a prancha pediu placeholder declarado até existirem
 * ícones reais, e uma folha desenhada comunica melhor que um glifo emprestado.
 */
export function SeloPdf() {
  return (
    <View style={estilos.selo}>
      <Text style={estilos.seloTexto}>PDF</Text>
    </View>
  )
}

/**
 * Linha de um PDF: selo, nome, tamanho, selo de offline e seta.
 *
 * O tamanho só aparece para documento já publicado — o gerado sob demanda ainda não tem
 * tamanho, e inventar um seria mentir sobre um arquivo que não existe.
 */
export function LinhaPdf({
  nome,
  tamanho,
  offline,
  onPress,
  semDivisoria,
}: {
  nome: string
  tamanho?: string
  offline?: boolean
  onPress?: () => void
  semDivisoria?: boolean
}) {
  return (
    <Pressable
      style={[estilos.linhaPdf, semDivisoria && estilos.linhaPdfSemDivisoria]}
      onPress={onPress}
    >
      <SeloPdf />
      <View style={estilos.pdfMiolo}>
        <Text style={estilos.pdfNome}>{nome}</Text>
        {tamanho ? <Text style={estilos.pdfTamanho}>{tamanho}</Text> : null}
      </View>
      {offline ? <StatusChip tom="ok" texto="offline" /> : null}
      <Chevron />
    </Pressable>
  )
}

/** Botão flutuante de ação, acima da barra de abas. */
export function BotaoFlutuante({ onPress }: { onPress?: () => void }) {
  return (
    <Pressable style={estilos.fab} onPress={onPress}>
      <View style={estilos.fabBarraH} />
      <View style={estilos.fabBarraV} />
    </Pressable>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, justifyContent: 'flex-end' },
  veu: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: cores.veu },
  painel: {
    backgroundColor: cores.painelFlutuante,
    borderTopWidth: 1,
    borderTopColor: cores.borda,
    borderTopLeftRadius: raio.sheet,
    borderTopRightRadius: raio.sheet,
    paddingHorizontal: espaco.md,
    paddingTop: 10,
    paddingBottom: 28,
    maxHeight: '88%',
  },
  alca: {
    width: 38,
    height: 4,
    borderRadius: 2,
    backgroundColor: cores.superficieDestacada,
    alignSelf: 'center',
    marginBottom: espaco.md,
  },
  titulo: { fontFamily: fontes.uiForte, fontSize: 20, color: cores.textoForte },
  apoio: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo, marginTop: 4 },

  campo: { marginTop: espaco.md },
  rotuloCampo: {
    fontFamily: fontes.uiMedio,
    fontSize: 12,
    color: cores.textoRotulo,
    marginBottom: espaco.sm,
  },
  nota: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco, marginTop: espaco.sm },

  linhaDetalhe: { flexDirection: 'row', justifyContent: 'space-between' },
  detalheRotulo: { fontFamily: fontes.ui, fontSize: 13.5, color: cores.textoRotulo },

  selo: {
    width: 30,
    height: 36,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: tomAlpha('parado', 0.33),
    backgroundColor: tomAlpha('parado', 0.1),
    alignItems: 'center',
    justifyContent: 'flex-end',
    paddingBottom: 4,
  },
  seloTexto: { fontFamily: fontes.monoSemi, fontSize: 8.5, color: tons.parado },

  linhaPdf: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: espaco.md,
    paddingVertical: 11,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
    minHeight: TOQUE_MIN,
  },
  linhaPdfSemDivisoria: { borderTopWidth: 0 },
  pdfMiolo: { flex: 1, minWidth: 0 },
  pdfNome: { fontFamily: fontes.uiMedio, fontSize: 14, color: cores.textoForte },
  pdfTamanho: { fontFamily: fontes.mono, fontSize: 11, color: cores.textoFraco, marginTop: 3 },

  fab: {
    position: 'absolute',
    right: espaco.md,
    bottom: 84,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: cores.ambar,
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: TOQUE_MIN,
  },
  fabBarraH: { position: 'absolute', width: 20, height: 2.5, backgroundColor: cores.sobreAmbar },
  fabBarraV: { position: 'absolute', width: 2.5, height: 20, backgroundColor: cores.sobreAmbar },
})
