/**
 * Financeiro — mensalidades do meuWatt e do meuPlano.
 *
 * O problema que a tela resolve: o dono assina **dois produtos** e recebe **uma cobrança
 * só**. Por isso o card do topo mostra o total, e o bloco "O que compõe o total" abre a
 * conta por produto, fechando de volta na mesma soma. Se esses números divergirem, é bug
 * de agregação no BFF — a tela apenas exibe.
 *
 * Não há pagamento pelo app: a baixa é feita pela administração. A tela informa, não
 * cobra — nada de botão "Pagar agora".
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { Card, Chevron, Num, Rotulo, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import {
  assinaturas,
  financeiro,
  historicoFaturas,
  situacaoRotulo,
  situacaoTom,
  usuario,
  type LinhaHistorico,
} from '@/features/exemplo'
import { cores, espaco, fontes, tipo, tomAlpha, tons, TOQUE_MIN } from '@/theme/tokens'

export default function Financeiro() {
  // Fase 6: sai de GET /api/v1/billing — `situacao` no topo do payload decide o card.
  const [temPendencia] = useState(false)

  return (
    <Tela
      titulo="Financeiro"
      subtitulo={financeiro.competenciaAtual}
      avatar={{ iniciais: usuario.iniciais, onPress: () => router.push('/perfil') }}
      paraTabBar
    >
      {temPendencia ? <CardVencida /> : <CardEmDia />}

      <Card semPadding>
        <View style={estilos.tituloBloco}>
          <Rotulo>O que compõe o total</Rotulo>
        </View>
        {assinaturas.map((a) => (
          <View key={a.id} style={estilos.linhaProduto}>
            <View style={estilos.produtoMiolo}>
              <Text style={estilos.produtoNome}>{a.produto}</Text>
              <Text style={estilos.produtoDescricao}>
                {a.descricao} · vence dia <Num style={estilos.diaVencimento}>{a.diaVencimento}</Num>
              </Text>
            </View>
            <View style={estilos.produtoDireita}>
              <Num style={estilos.produtoValor}>{a.valor}</Num>
              <View style={estilos.chipPequeno}>
                <StatusChip tom={situacaoTom[a.situacao]} texto={situacaoRotulo[a.situacao]} />
              </View>
            </View>
          </View>
        ))}
        <View style={estilos.linhaTotal}>
          <Text style={estilos.totalRotulo}>Uma cobrança só</Text>
          <Num style={estilos.totalValor}>{financeiro.total}</Num>
        </View>
      </Card>

      <Card semPadding>
        <View style={estilos.tituloBloco}>
          <Rotulo>Histórico</Rotulo>
        </View>
        {historicoFaturas.map((h) => (
          <LinhaFatura key={h.id} fatura={h} />
        ))}
      </Card>

      <Text style={estilos.rodape}>{financeiro.rodape}</Text>
    </Tela>
  )
}

function CardEmDia() {
  return (
    <View style={[estilos.cardSituacao, estilos.cardOk]}>
      <View style={estilos.linhaSituacao}>
        <View style={[estilos.pontoSituacao, { backgroundColor: tons.ok }]} />
        <Text style={[estilos.tituloSituacao, { color: tons.ok }]}>Tudo em dia</Text>
      </View>
      <Num style={estilos.valorSituacao}>{financeiro.total}</Num>
      <Text style={estilos.detalheSituacao}>
        total de {financeiro.competenciaAtual.split(' ')[0]} · vence em{' '}
        <Num style={estilos.detalheNum}>{financeiro.vencimento}</Num>
      </Text>
    </View>
  )
}

function CardVencida() {
  const p = financeiro.pendencia
  return (
    <View style={[estilos.cardSituacao, estilos.cardVencida]}>
      <View style={estilos.linhaSituacao}>
        <View style={[estilos.pontoSituacao, { backgroundColor: tons.parado }]} />
        <Text style={[estilos.tituloSituacao, { color: tons.parado }]}>{p.titulo}</Text>
      </View>
      <Num style={estilos.valorSituacao}>{p.valor}</Num>
      <Text style={estilos.detalheSituacao}>
        {p.detalhe} <Num style={estilos.detalheNum}>{p.diasAtraso}</Num>
      </Text>
      <Text style={estilos.orientacao}>{p.orientacao}</Text>
    </View>
  )
}

function LinhaFatura({ fatura }: { fatura: LinhaHistorico }) {
  return (
    <Pressable style={estilos.linhaHistorico} onPress={() => router.push(`/fatura/${fatura.id}`)}>
      <View style={estilos.historicoMiolo}>
        <Text style={estilos.historicoMes}>{fatura.mes}</Text>
        <Text style={estilos.historicoProduto}>{fatura.produto}</Text>
      </View>
      <View style={estilos.produtoDireita}>
        <Num style={estilos.historicoValor}>{fatura.valor}</Num>
        <View style={estilos.chipPequeno}>
          <StatusChip tom={situacaoTom[fatura.situacao]} texto={situacaoRotulo[fatura.situacao]} />
        </View>
      </View>
      <Chevron />
    </Pressable>
  )
}

const estilos = StyleSheet.create({
  cardSituacao: { borderWidth: 1, borderRadius: 16, padding: espaco.md },
  cardOk: { backgroundColor: tomAlpha('ok', 0.1), borderColor: tomAlpha('ok', 0.33) },
  cardVencida: { backgroundColor: tomAlpha('parado', 0.1), borderColor: tomAlpha('parado', 0.33) },

  linhaSituacao: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  pontoSituacao: { width: 10, height: 10, borderRadius: 5 },
  tituloSituacao: { fontFamily: fontes.uiSemi, fontSize: 16 },
  valorSituacao: {
    fontFamily: fontes.monoSemi,
    fontSize: 34,
    lineHeight: 34,
    color: cores.textoForte,
    marginTop: 12,
  },
  detalheSituacao: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo, marginTop: espaco.sm },
  detalheNum: { fontSize: 12.5, color: cores.textoCorpo },
  orientacao: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoRotulo,
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: tomAlpha('parado', 0.2),
  },

  tituloBloco: { paddingHorizontal: espaco.md, paddingTop: 14, paddingBottom: espaco.xs },

  linhaProduto: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: espaco.md,
    paddingVertical: 13,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
    minHeight: TOQUE_MIN,
  },
  produtoMiolo: { flex: 1 },
  produtoNome: { fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte },
  produtoDescricao: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 3 },
  diaVencimento: { fontSize: 12, color: cores.textoRotulo },
  produtoDireita: { alignItems: 'flex-end' },
  produtoValor: { fontFamily: fontes.monoSemi, fontSize: 15, color: cores.textoForte },
  chipPequeno: { marginTop: 5 },

  linhaTotal: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: espaco.md,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: cores.bordaForte,
    backgroundColor: cores.superficie,
  },
  totalRotulo: { flex: 1, fontFamily: fontes.uiSemi, fontSize: 13, color: cores.textoRotulo },
  totalValor: { fontFamily: fontes.monoSemi, fontSize: 16, color: cores.textoForte },

  linhaHistorico: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: espaco.md,
    paddingVertical: 13,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
    minHeight: TOQUE_MIN,
  },
  historicoMiolo: { flex: 1, minWidth: 0 },
  historicoMes: { fontFamily: fontes.uiSemi, fontSize: 14.5, color: cores.textoForte },
  historicoProduto: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 3 },
  historicoValor: { fontSize: 14, color: cores.textoCorpo },

  rodape: {
    ...tipo.fraco,
    lineHeight: 17,
    paddingHorizontal: espaco.xs,
  },
})
