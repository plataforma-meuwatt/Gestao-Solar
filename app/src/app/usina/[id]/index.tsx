/**
 * Usina — geração do dia e do mês.
 *
 * O segmentado Dia/Mês/Ano troca o recorte do card de geração; o gráfico do mês fica
 * sempre visível abaixo porque responde uma pergunta diferente ("o mês está indo bem?"),
 * e as duas linhas de navegação ao pé levam para equipamentos e manutenção.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import {
  CabecalhoCard,
  Card,
  FaixaAtencao,
  Kpi,
  LinhaNavegacao,
  Num,
  Segmentado,
} from '@/components/base'
import { BarrasDia, BarrasMes } from '@/components/graficos'
import { Tela } from '@/components/Tela'
import { usinaDetalhe, usinas } from '@/features/exemplo'
import { cores, espaco, fontes, tipo } from '@/theme/tokens'

const RECORTES = ['Dia', 'Mês', 'Ano']

export default function UsinaDetalhe() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [recorte, setRecorte] = useState(0)

  const usina = usinas.find((u) => u.id === id)
  const d = usinaDetalhe

  return (
    <Tela
      titulo={usina?.nome ?? d.nome}
      subtitulo={
        <Text style={tipo.secundario}>
          <Num style={estilos.subNum}>{d.capacidadeMwp}</Num> MWp ·{' '}
          <Num style={estilos.subNum}>{d.inversores}</Num> inversores
        </Text>
      }
      voltar
      paraTabBar
    >
      <FaixaAtencao
        tom="parado"
        titulo="2 inversores parados"
        onPress={() => router.push(`/usina/${id}/equipamentos`)}
      />

      <Card>
        <Segmentado opcoes={RECORTES} ativo={recorte} onEscolher={setRecorte} />

        {recorte === 0 ? (
          <View style={estilos.miolo}>
            <Text style={tipo.rotuloCard}>Energia hoje</Text>
            <View style={estilos.espacoKpi}>
              <Kpi
                valor={d.dia.energiaMwh}
                unidade="MWh"
                tamanho="grande"
                direita={
                  <Text style={tipo.legenda}>
                    previsto <Num style={estilos.previsto}>{d.dia.previstoMwh}</Num>
                  </Text>
                }
              />
            </View>
            <View style={estilos.espacoGrafico}>
              <BarrasDia valores={d.dia.curva} destaque={d.dia.indicePico} />
            </View>
            <RodapeDia />
          </View>
        ) : (
          <View style={estilos.miolo}>
            <Text style={tipo.fraco}>
              O recorte {RECORTES[recorte]} entra na Fase 2, com
              GET /api/v1/plants/{'{id}'}/generation/range.
            </Text>
          </View>
        )}
      </Card>

      <Card>
        <CabecalhoCard
          rotulo={d.mes.rotulo}
          direita={
            <Text style={tipo.legenda}>
              <Num style={estilos.totalMes}>{d.mes.totalMwh}</Num> MWh
            </Text>
          }
        />
        <View style={estilos.espacoGrafico}>
          <BarrasMes valores={d.mes.dias} limiarTempoRuim={d.mes.limiarTempoRuim} />
        </View>
      </Card>

      <Card semPadding>
        <LinhaNavegacao
          titulo="Equipamentos"
          valor={String(d.inversores)}
          primeiro
          onPress={() => router.push(`/usina/${id}/equipamentos`)}
        />
        <LinhaNavegacao titulo="Manutenção" valor={d.manutencao} tomValor="ok" />
      </Card>
    </Tela>
  )
}

function RodapeDia() {
  const { dia } = usinaDetalhe
  return (
    <View style={estilos.rodape}>
      <Coluna rotulo="pico" valor={dia.picoKw} unidade="kW" />
      <Coluna rotulo="às" valor={dia.picoHora} />
      <Coluna rotulo="PR do dia" valor={dia.pr} />
    </View>
  )
}

function Coluna({ rotulo, valor, unidade }: { rotulo: string; valor: string; unidade?: string }) {
  return (
    <View>
      <Text style={tipo.fraco}>{rotulo}</Text>
      <View style={estilos.colunaValor}>
        <Num style={estilos.colunaNum}>{valor}</Num>
        {unidade ? <Text style={estilos.colunaUnidade}>{unidade}</Text> : null}
      </View>
    </View>
  )
}

const estilos = StyleSheet.create({
  subNum: { fontSize: 13, color: cores.textoRotulo },

  miolo: { marginTop: espaco.md },
  espacoKpi: { marginTop: espaco.sm },
  espacoGrafico: { marginTop: 18 },

  previsto: { fontSize: 12, color: cores.textoCorpo },
  totalMes: { fontSize: 12, color: cores.textoForte },

  rodape: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 14,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  colunaValor: { flexDirection: 'row', alignItems: 'baseline', gap: espaco.xs, marginTop: 3 },
  colunaNum: { fontFamily: fontes.monoSemi, fontSize: 16, color: cores.textoForte },
  colunaUnidade: { fontFamily: fontes.uiMedio, fontSize: 11, color: cores.textoCorpo },
})
