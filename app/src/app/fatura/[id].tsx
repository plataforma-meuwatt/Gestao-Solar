/**
 * Detalhe da fatura — folha que sobe sobre a lista.
 *
 * Não vira tela inteira de propósito: é informação de consulta rápida, e a folha mantém
 * o histórico visível atrás, preservando o contexto de onde o toque veio.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'

import { Num, StatusChip } from '@/components/base'
import { Folha, LinhaPdf, LinhaDetalhe } from '@/components/folha'
import { faturaDetalhe, historicoFaturas, situacaoRotulo, situacaoTom } from '@/features/exemplo'
import { cores, espaco, fontes } from '@/theme/tokens'

export default function Fatura() {
  const { id } = useLocalSearchParams<{ id: string }>()

  // A linha tocada define produto e competência; o resto do detalhe vem do BFF na Fase 6.
  const linha = historicoFaturas.find((h) => h.id === id)
  const d = faturaDetalhe
  const produto = linha?.produto ?? d.produto
  const situacao = linha?.situacao ?? d.situacao
  const valor = linha?.valor ?? d.valor

  return (
    <Folha
      visivel
      aoFechar={() => router.back()}
      cabecalho={
        <View>
          <View style={estilos.cabecalho}>
            <Text style={estilos.produto}>{produto}</Text>
            <StatusChip tom={situacaoTom[situacao]} texto={situacaoRotulo[situacao]} />
          </View>
          <Text style={estilos.competencia}>
            {linha ? `competência ${linha.mes.toLowerCase()}` : d.competencia}
          </Text>
        </View>
      }
    >
      <Num style={estilos.valor}>{valor}</Num>

      <View style={estilos.linhas}>
        {d.linhas.map((l) => (
          <LinhaDetalhe key={l.rotulo} rotulo={l.rotulo}>
            {l.mono ? (
              <Num style={estilos.valorLinha}>{l.valor}</Num>
            ) : (
              <Text style={estilos.valorLinhaTexto}>{l.valor}</Text>
            )}
          </LinhaDetalhe>
        ))}
      </View>

      <View style={estilos.observacao}>
        <Text style={estilos.observacaoTexto}>{d.observacao}</Text>
      </View>

      {situacao === 'pago' ? (
        <View style={estilos.comprovante}>
          <LinhaPdf
            nome={d.comprovante.nome}
            tamanho={d.comprovante.tamanho}
            semDivisoria
            onPress={() => router.push('/documento/comprovante')}
          />
        </View>
      ) : null}
    </Folha>
  )
}

const estilos = StyleSheet.create({
  cabecalho: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  produto: { fontFamily: fontes.uiForte, fontSize: 20, color: cores.textoForte },
  competencia: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo, marginTop: 4 },

  valor: {
    fontFamily: fontes.monoSemi,
    fontSize: 38,
    color: cores.textoForte,
    marginTop: espaco.md,
  },

  linhas: {
    gap: 11,
    marginTop: espaco.lg,
    paddingTop: espaco.md,
    borderTopWidth: 1,
    borderTopColor: cores.borda,
  },
  valorLinha: { fontSize: 13.5, color: cores.textoCorpo },
  valorLinhaTexto: { fontFamily: fontes.ui, fontSize: 13.5, color: cores.textoCorpo },

  observacao: {
    backgroundColor: cores.superficie,
    borderWidth: 1,
    borderColor: cores.borda,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginTop: espaco.md,
  },
  observacaoTexto: {
    fontFamily: fontes.ui,
    fontSize: 12.5,
    lineHeight: 19,
    color: cores.textoRotulo,
  },

  comprovante: {
    backgroundColor: cores.superficie,
    borderWidth: 1,
    borderColor: cores.borda,
    borderRadius: 12,
    marginTop: 12,
    overflow: 'hidden',
  },
})
