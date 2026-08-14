/**
 * Financeiro — mensalidades do meuWatt e do meuPlano.
 *
 * O problema que a tela resolve: o dono assina **dois produtos** e recebe **uma cobrança
 * só**. Por isso o card do topo mostra o total, e o bloco "O que compõe o total" abre a
 * conta por produto, fechando de volta na mesma soma. Se esses números divergirem, é bug
 * de agregação no BFF — a tela apenas exibe.
 *
 * Não há pagamento pelo app: a baixa é feita pela administração. A tela informa, não
 * cobra — nada de botão "Pagar agora". O rodapé que diz isso vem do servidor, porque é
 * regra de negócio: mudaria junto com o produto, não com o aplicativo.
 *
 * Qual card aparece no topo é decisão do BFF (`situacao`), não da tela. Uma parcela
 * vencida entre três pagas tem de pintar de vermelho, e essa é a espécie de regra que
 * não pode viver em dois lugares.
 */

import { router } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { Card, Chevron, Esqueleto, EstadoVazio, Num, Rotulo, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import {
  competenciaPorExtenso,
  diaEMes,
  useFinanceiro,
  type Assinatura,
  type Fatura,
  type FinanceiroOut,
} from '@/features/financeiro'
import { moeda } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo, tomAlpha, tons, TOQUE_MIN } from '@/theme/tokens'

const ROTULO_SITUACAO: Record<Fatura['situacao'], string> = {
  pago: 'Pago',
  a_vencer: 'A vencer',
  em_aberto: 'Em aberto',
  vencido: 'Vencido',
}

function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

export default function Financeiro() {
  const { dados, carregando, erro, offlineDesde, recarregar } = useFinanceiro()
  const usuario = useAuth((s) => s.usuario)

  const competencia = new Date().toISOString().slice(0, 7)

  return (
    <Tela
      titulo="Financeiro"
      subtitulo={competenciaPorExtenso(competencia)}
      avatar={{ iniciais: iniciaisDe(usuario?.nome), onPress: () => router.push('/perfil') }}
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {carregando ? (
        <Fantasma />
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : !dados || dados.assinaturas.length === 0 ? (
        <EstadoVazio
          titulo="Nenhuma assinatura"
          descricao={dados?.resumo ?? 'Ainda não há mensalidade cadastrada para esta conta.'}
        />
      ) : (
        <Conteudo dados={dados} />
      )}
    </Tela>
  )
}

function Conteudo({ dados }: { dados: FinanceiroOut }) {
  return (
    <>
      <CardSituacao dados={dados} />

      <Card semPadding>
        <View style={estilos.tituloBloco}>
          <Rotulo>O que compõe o total</Rotulo>
        </View>
        {dados.assinaturas.map((a) => (
          <LinhaProduto key={a.id} assinatura={a} />
        ))}
        <View style={estilos.linhaTotal}>
          <Text style={estilos.totalRotulo}>Uma cobrança só</Text>
          <Num style={estilos.totalValor}>{moeda(dados.total_mensal)}</Num>
        </View>
      </Card>

      {dados.historico.length > 0 ? (
        <Card semPadding>
          <View style={estilos.tituloBloco}>
            <Rotulo>Histórico</Rotulo>
          </View>
          {dados.historico.map((f) => (
            <LinhaFatura key={f.id} fatura={f} />
          ))}
        </Card>
      ) : null}

      <Text style={estilos.rodape}>{dados.rodape}</Text>
    </>
  )
}

/**
 * O card do topo. Em dia mostra o total e o vencimento; com atraso, troca de cor e passa
 * a falar da parcela vencida — que é o que a pessoa precisa resolver.
 */
function CardSituacao({ dados }: { dados: FinanceiroOut }) {
  const vencida = dados.situacao === 'vencido'
  const cor = tons[dados.tom] ?? tons.semDados

  return (
    <View
      style={[
        estilos.cardSituacao,
        {
          backgroundColor: tomAlpha(dados.tom, 0.1),
          borderColor: tomAlpha(dados.tom, 0.33),
        },
      ]}
    >
      <View style={estilos.linhaSituacao}>
        <View style={[estilos.pontoSituacao, { backgroundColor: cor }]} />
        <Text style={[estilos.tituloSituacao, { color: cor }]}>{dados.resumo}</Text>
      </View>

      <Num style={estilos.valorSituacao}>
        {moeda(vencida ? dados.total_vencido : dados.total_mensal)}
      </Num>

      <Text style={estilos.detalheSituacao}>
        {vencida ? (
          'em mensalidades vencidas'
        ) : (
          <>
            total do mês · vence em{' '}
            <Num style={estilos.detalheNum}>{diaEMes(dados.proximo_vencimento)}</Num>
          </>
        )}
      </Text>

      {vencida ? (
        <Text style={[estilos.orientacao, { borderTopColor: tomAlpha('parado', 0.2) }]}>
          Fale com a administração para regularizar.
        </Text>
      ) : null}
    </View>
  )
}

function LinhaProduto({ assinatura: a }: { assinatura: Assinatura }) {
  const atual = a.competencia_atual
  return (
    <View style={estilos.linhaProduto}>
      <View style={estilos.produtoMiolo}>
        <Text style={estilos.produtoNome}>{a.produto_nome}</Text>
        <Text style={estilos.produtoDescricao}>
          {a.fornece} · vence dia <Num style={estilos.diaVencimento}>{a.dia_vencimento}</Num>
        </Text>
      </View>
      <View style={estilos.produtoDireita}>
        <Num style={estilos.produtoValor}>{moeda(a.valor_mensal)}</Num>
        {atual ? (
          <View style={estilos.chipPequeno}>
            <StatusChip tom={atual.tom} texto={ROTULO_SITUACAO[atual.situacao]} />
          </View>
        ) : null}
      </View>
    </View>
  )
}

function LinhaFatura({ fatura }: { fatura: Fatura }) {
  return (
    <Pressable style={estilos.linhaHistorico} onPress={() => router.push(`/fatura/${fatura.id}`)}>
      <View style={estilos.historicoMiolo}>
        <Text style={estilos.historicoMes}>{competenciaPorExtenso(fatura.competencia)}</Text>
        <Text style={estilos.historicoProduto}>
          {fatura.produto_nome}
          {fatura.dias_atraso ? ` · vencida há ${fatura.dias_atraso} dias` : ''}
        </Text>
      </View>
      <View style={estilos.produtoDireita}>
        <Num style={estilos.historicoValor}>{moeda(fatura.valor)}</Num>
        <View style={estilos.chipPequeno}>
          <StatusChip tom={fatura.tom} texto={ROTULO_SITUACAO[fatura.situacao]} />
        </View>
      </View>
      <Chevron />
    </Pressable>
  )
}

function Fantasma() {
  return (
    <>
      <View style={[estilos.cardSituacao, { borderColor: cores.borda }]}>
        <Esqueleto largura="45%" altura={16} forte />
        <View style={{ marginTop: 14 }}>
          <Esqueleto largura="55%" altura={30} forte />
        </View>
        <View style={{ marginTop: 12 }}>
          <Esqueleto largura="40%" altura={12} />
        </View>
      </View>
      <Card>
        <Esqueleto altura={14} largura="35%" />
        <View style={{ marginTop: 14, gap: 10 }}>
          <Esqueleto altura={16} />
          <Esqueleto altura={16} />
        </View>
      </Card>
    </>
  )
}

const estilos = StyleSheet.create({
  cardSituacao: { borderWidth: 1, borderRadius: 16, padding: espaco.md },

  linhaSituacao: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  pontoSituacao: { width: 10, height: 10, borderRadius: 5 },
  tituloSituacao: { fontFamily: fontes.uiSemi, fontSize: 16, flexShrink: 1 },
  valorSituacao: {
    fontFamily: fontes.monoSemi,
    fontSize: 34,
    lineHeight: 34,
    color: cores.textoForte,
    marginTop: 12,
  },
  detalheSituacao: {
    fontFamily: fontes.ui,
    fontSize: 12.5,
    color: cores.textoRotulo,
    marginTop: espaco.sm,
  },
  detalheNum: { fontSize: 12.5, color: cores.textoCorpo },
  orientacao: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoRotulo,
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
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
