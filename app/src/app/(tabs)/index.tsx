/**
 * Início — a tela que responde "está tudo bem?" em cinco segundos.
 *
 * Ordem dos blocos é deliberada e vem do design: potência agora (o dado mais perecível),
 * o que está errado, geração do mês, manutenção, financeiro, notificações. Quem abre o
 * app com pressa lê só o primeiro card.
 *
 * Os quatro estados (normal, offline, carregando, erro) estão todos aqui e são
 * alternáveis por `modo` — quando a Fase 1 ligar `GET /api/v1/home`, quem decide o modo
 * passa a ser o resultado da consulta.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  CabecalhoCard,
  Card,
  Esqueleto,
  EstadoVazio,
  FaixaAtencao,
  ItemLista,
  Kpi,
  Num,
  Rotulo,
  StatusChip,
} from '@/components/base'
import { CelulasDoAno } from '@/components/graficos'
import { Tela } from '@/components/Tela'
import { inicio, notificacoes, usuario } from '@/features/exemplo'
import { dataPorExtenso } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons, TOQUE_MIN } from '@/theme/tokens'

type Modo = 'normal' | 'offline' | 'carregando' | 'erro'

function saudacao(hora = new Date().getHours()): string {
  if (hora < 12) return 'Bom dia'
  if (hora < 18) return 'Boa tarde'
  return 'Boa noite'
}

export default function Inicio() {
  // Fase 1: vem de useQuery('/api/v1/home') — carregando, erro e offline saem do estado
  // da consulta, não de um useState.
  const [modo] = useState<Modo>('normal')

  const recentes = notificacoes.slice(0, 3)

  return (
    <Tela
      titulo={`${saudacao()}, ${usuario.primeiroNome}`}
      subtitulo={dataPorExtenso(new Date().toISOString())}
      avatar={{ iniciais: usuario.iniciais, temAviso: true, onPress: () => router.push('/perfil') }}
      offlineDesde={modo === 'offline' ? '14:30' : undefined}
      paraTabBar
    >
      {modo === 'carregando' ? <EsqueletoInicio /> : null}

      {modo === 'erro' ? (
        <EstadoVazio
          titulo="Não foi possível carregar"
          descricao="Verifique sua conexão. Seus dados continuam salvos."
          acao={{ titulo: 'Tentar de novo' }}
        />
      ) : null}

      {modo === 'normal' || modo === 'offline' ? (
        <>
          <Card>
            <CabecalhoCard
              rotulo="Agora"
              direita={
                <Num style={estilos.anotacao}>
                  {inicio.qtdUsinas} usinas · {inicio.atualizadoAs}
                </Num>
              }
            />
            <View style={estilos.espacoKpi}>
              <Kpi valor={inicio.potenciaAgoraKw} unidade="kW" />
            </View>
            <View style={estilos.espacoBarra}>
              <Barra pct={inicio.pctCapacidade} />
            </View>
            <View style={estilos.rodapeCard}>
              <Text style={tipo.legenda}>
                <Num style={estilos.destaqueLegenda}>{inicio.pctCapacidade}%</Num> da capacidade
                instalada
              </Text>
              <Text style={tipo.legenda}>
                energia hoje <Num style={estilos.destaqueForte}>{inicio.energiaHojeMwh}</Num> MWh
              </Text>
            </View>
          </Card>

          <FaixaProblema />

          <Card>
            <CabecalhoCard
              rotulo="Geração do mês"
              direita={<Text style={estilos.origem}>meuWatt</Text>}
            />
            <View style={estilos.espacoKpi}>
              <Kpi
                valor={inicio.meuWatt.geracaoMesMwh}
                unidade="MWh"
                tamanho="medio"
                direita={
                  <Text style={tipo.legenda}>
                    meta <Num style={estilos.destaqueLegenda}>{inicio.meuWatt.metaMwh}</Num>
                  </Text>
                }
              />
            </View>
            <View style={estilos.espacoBarra}>
              <Barra pct={inicio.meuWatt.pctMeta} tom="ok" />
            </View>
            <View style={estilos.rodapeCard}>
              <Text style={tipo.legenda}>
                <Num style={estilos.destaqueOk}>{inicio.meuWatt.pctMeta}%</Num> da meta, faltando{' '}
                {inicio.meuWatt.diasRestantes} dias
              </Text>
              <Text style={tipo.fraco}>
                PR <Num style={estilos.numFraco}>{inicio.meuWatt.pr}</Num>
              </Text>
            </View>
          </Card>

          <Card>
            <CabecalhoCard
              rotulo="Manutenção"
              direita={<Text style={estilos.origem}>meuPlano</Text>}
            />
            <View style={[estilos.espacoKpi, estilos.linhaManutencao]}>
              <Num style={estilos.kpiManutencao}>
                {inicio.meuPlano.concluidos} de {inicio.meuPlano.total}
              </Num>
              <Text style={estilos.legendaManutencao}>serviços do mês concluídos</Text>
            </View>
            <View style={estilos.espacoCelulas}>
              <CelulasDoAno meses={inicio.meuPlano.meses} />
            </View>
          </Card>

          <Card style={estilos.cardFinanceiro}>
            <View style={estilos.financeiroMiolo}>
              <Rotulo>Financeiro</Rotulo>
              <Text style={estilos.financeiroTitulo}>
                Próximo vencimento{' '}
                <Num style={estilos.financeiroData}>{inicio.financeiro.proximoVencimento}</Num>
              </Text>
              <Text style={estilos.financeiroValor}>
                mensalidade <Num style={estilos.destaqueLegenda}>{inicio.financeiro.valor}</Num>
              </Text>
            </View>
            <StatusChip tom="ok" texto={inicio.financeiro.situacao} />
          </Card>

          <Card semPadding>
            <View style={estilos.tituloLista}>
              <Rotulo>Notificações recentes</Rotulo>
            </View>
            {recentes.map((n) => (
              <ItemLista
                key={n.id}
                tom={n.tom}
                titulo={n.titulo}
                resumo={n.resumo}
                quando={n.quando}
                onPress={() => router.push('/notificacoes')}
              />
            ))}
            <Text style={estilos.verTodas} onPress={() => router.push('/notificacoes')}>
              Ver todas
            </Text>
          </Card>
        </>
      ) : null}
    </Tela>
  )
}

/** Só aparece quando há problema — em dia normal o Início não tem faixa nenhuma. */
function FaixaProblema() {
  const { tom, titulo, detalhe } = inicio.atencao
  return (
    <FaixaAtencao
      tom={tom}
      titulo={titulo}
      detalhe={detalhe}
      onPress={() => router.push('/usina/porto-ferreira')}
    />
  )
}

function EsqueletoInicio() {
  return (
    <>
      <Card style={estilos.esqueletoCard}>
        <Esqueleto largura={64} altura={10} forte />
        <Esqueleto largura={180} altura={38} forte />
        <Esqueleto altura={6} />
        <View style={estilos.esqueletoLinha}>
          <Esqueleto largura={120} altura={10} />
          <Esqueleto largura={90} altura={10} />
        </View>
      </Card>
      <Card style={estilos.esqueletoCard}>
        <Esqueleto largura={110} altura={10} forte />
        <Esqueleto largura={150} altura={28} forte />
        <Esqueleto altura={6} />
      </Card>
      <Card style={estilos.esqueletoCard}>
        <Esqueleto largura={100} altura={10} forte />
        <Esqueleto largura={200} altura={24} forte />
        <Esqueleto altura={22} />
      </Card>
      <Card style={estilos.esqueletoCard}>
        <Esqueleto largura={88} altura={10} forte />
        <Esqueleto largura={170} altura={18} />
      </Card>
    </>
  )
}

const estilos = StyleSheet.create({
  anotacao: { fontSize: 11, color: cores.textoFraco },
  origem: { fontFamily: fontes.uiMedio, fontSize: 11, color: cores.textoFraco },

  espacoKpi: { marginTop: 10 },
  espacoBarra: { marginTop: 14 },
  espacoCelulas: { marginTop: espaco.md },

  rodapeCard: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    marginTop: espaco.sm,
  },
  destaqueLegenda: { fontSize: 12, color: cores.textoCorpo },
  destaqueForte: { fontFamily: fontes.mono, fontSize: 12, color: cores.textoForte },
  destaqueOk: { fontSize: 12, color: tons.ok },
  numFraco: { fontSize: 11.5, color: cores.textoFraco },

  linhaManutencao: { flexDirection: 'row', alignItems: 'baseline', gap: espaco.sm },
  kpiManutencao: { fontFamily: fontes.monoSemi, fontSize: 28, color: cores.textoForte },
  legendaManutencao: { fontFamily: fontes.ui, fontSize: 14, color: cores.textoCorpo, flex: 1 },

  cardFinanceiro: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  financeiroMiolo: { flex: 1 },
  financeiroTitulo: {
    fontFamily: fontes.uiSemi,
    fontSize: 15,
    color: cores.textoForte,
    marginTop: espaco.sm,
  },
  financeiroData: { fontFamily: fontes.monoSemi, fontSize: 15, color: cores.textoForte },
  financeiroValor: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo, marginTop: 3 },

  tituloLista: { paddingHorizontal: espaco.md, paddingTop: 14, paddingBottom: espaco.xs },
  verTodas: {
    fontFamily: fontes.uiSemi,
    fontSize: 13,
    color: cores.textoAmbar,
    textAlign: 'center',
    paddingVertical: 13,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
    minHeight: TOQUE_MIN,
  },

  esqueletoCard: { gap: 14 },
  esqueletoLinha: { flexDirection: 'row', justifyContent: 'space-between' },
})
