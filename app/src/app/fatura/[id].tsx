/**
 * Detalhe da mensalidade — folha que sobe sobre a lista.
 *
 * Não vira tela inteira de propósito: é consulta rápida, e a folha mantém o histórico
 * visível atrás, preservando o contexto de onde o toque veio.
 *
 * Antes esta tela **ignorava o `id` da rota** e desenhava sempre a mesma fatura fictícia —
 * qualquer linha do histórico abria "R$ 2.480,00, boleto, 3 usinas cobertas, comprovante
 * de 184 kB". Agora vem de `GET /api/v1/billing/invoices/{id}`.
 *
 * Saíram por não existirem: forma de pagamento (não há coluna nem gateway), "usinas
 * cobertas" (a assinatura é por cliente, não por usina) e o tamanho do comprovante
 * (guarda-se a URL, não os bytes).
 */

import { router, useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'

import { Esqueleto, EstadoVazio, Num, StatusChip } from '@/components/base'
import { Folha, LinhaDetalhe } from '@/components/folha'
import { competenciaPorExtenso, useFatura, type SituacaoFatura } from '@/features/financeiro'
import { moeda } from '@/lib/format'
import { cores, espaco, fontes } from '@/theme/tokens'

const ROTULO: Record<SituacaoFatura, string> = {
  pago: 'Pago',
  a_vencer: 'A vencer',
  em_aberto: 'Em aberto',
  vencido: 'Vencido',
}

const dataBR = (iso: string | null) =>
  iso ? iso.split('-').reverse().join('/') : '—'

export default function Fatura() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { dados: f, carregando, erro, recarregar } = useFatura(id)

  if (carregando || !f) {
    return (
      <Folha visivel aoFechar={() => router.back()} cabecalho={<Esqueleto largura="45%" altura={20} forte />}>
        {erro ? (
          <EstadoVazio
            tom="parado"
            titulo="Não deu para carregar"
            descricao={erro}
            acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
          />
        ) : (
          <View style={{ gap: 14, marginTop: espaco.md }}>
            <Esqueleto largura="55%" altura={34} forte />
            <Esqueleto altura={14} />
            <Esqueleto altura={14} />
          </View>
        )}
      </Folha>
    )
  }

  return (
    <Folha
      visivel
      aoFechar={() => router.back()}
      cabecalho={
        <View>
          <View style={estilos.cabecalho}>
            <Text style={estilos.produto}>{f.produto_nome}</Text>
            <StatusChip tom={f.tom} texto={ROTULO[f.situacao]} />
          </View>
          <Text style={estilos.competencia}>
            competência {competenciaPorExtenso(f.competencia)}
          </Text>
        </View>
      }
    >
      <Num style={estilos.valor}>{moeda(f.valor)}</Num>

      <View style={estilos.linhas}>
        <LinhaDetalhe rotulo="Vencimento">
          <Num style={estilos.valorLinha}>{dataBR(f.vencimento)}</Num>
        </LinhaDetalhe>

        {f.pago_em ? (
          <LinhaDetalhe rotulo="Pago em">
            <Num style={estilos.valorLinha}>{dataBR(f.pago_em)}</Num>
          </LinhaDetalhe>
        ) : null}

        {f.dias_atraso !== null ? (
          <LinhaDetalhe rotulo="Em atraso">
            <Num style={estilos.valorLinha}>{f.dias_atraso} dias</Num>
          </LinhaDetalhe>
        ) : null}
      </View>

      <View style={estilos.observacao}>
        <Text style={estilos.observacaoTexto}>
          A baixa das mensalidades é feita pela administração. Este aplicativo informa a
          situação, não recebe pagamento.
        </Text>
      </View>
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

  observacao: {
    marginTop: espaco.lg,
    paddingTop: espaco.md,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  observacaoTexto: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoRotulo,
    lineHeight: 17,
  },
})
