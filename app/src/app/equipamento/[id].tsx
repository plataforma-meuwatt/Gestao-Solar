/**
 * Inversor — estado agora, geração do dia e por que ele parou.
 *
 * A tela é dividida em duas abas porque responde duas perguntas diferentes: "o que está
 * acontecendo agora" (potência, MPPTs, alarmes) e "quanto isso custou hoje" (curva com a
 * marca da parada, comparação com os vizinhos).
 *
 * O valor de potência sai em vermelho quando é zero por parada — é o mesmo número, mas
 * "0,0 kW" em cinza se leria como noite.
 */

import { useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  Botao,
  Card,
  Kpi,
  Num,
  RodapeNumeros,
  Rotulo,
  Segmentado,
} from '@/components/base'
import { BarraComparativa, CurvaDia } from '@/components/graficos'
import { Tela } from '@/components/Tela'
import { inversor } from '@/features/exemplo'
import { cores, espaco, fontes, tipo, tomAlpha, tons } from '@/theme/tokens'

const ABAS = ['Agora', 'Geração']

export default function Equipamento() {
  useLocalSearchParams<{ id: string; usina: string }>()
  const [aba, setAba] = useState(0)
  const inv = inversor

  return (
    <Tela
      titulo={inv.nome}
      subtitulo={`${inv.usina} · ${inv.modelo}`}
      voltar
      paraTabBar
    >
      <Segmentado opcoes={ABAS} ativo={aba} onEscolher={setAba} />

      {aba === 0 ? <AbaAgora /> : <AbaGeracao />}
    </Tela>
  )
}

function AbaAgora() {
  const inv = inversor
  return (
    <>
      <View style={[estilos.avisoParada, { borderColor: tomAlpha('parado', 0.33) }]}>
        <View style={estilos.pontoParada} />
        <View style={estilos.avisoMiolo}>
          <Text style={estilos.avisoTitulo}>
            Parado há <Num style={estilos.avisoNum}>{inv.paradoHa}</Num>
          </Text>
          <Text style={estilos.avisoDetalhe}>
            última geração às <Num style={estilos.avisoDetalheNum}>{inv.ultimaGeracao}</Num>
          </Text>
        </View>
      </View>

      <Card>
        <Rotulo>Potência agora</Rotulo>
        <View style={estilos.espacoKpi}>
          <Kpi
            valor={inv.potenciaAgora}
            unidade="kW"
            tom="parado"
            direita={
              <Text style={tipo.legenda}>
                nominal <Num style={estilos.nominal}>{inv.nominalKw}</Num> kW
              </Text>
            }
          />
        </View>
        <View style={estilos.espacoBarra}>
          <Barra pct={0} tom="parado" />
        </View>
        <RodapeNumeros
          itens={[
            { rotulo: 'energia hoje', valor: inv.energiaHoje, unidade: 'kWh' },
            { rotulo: 'energia no mês', valor: inv.energiaMes, unidade: 'kWh' },
            { rotulo: 'PR do mês', valor: inv.prMes },
          ]}
        />
      </Card>

      <Card semPadding>
        <View style={estilos.tituloBloco}>
          <Rotulo>Entradas (MPPT)</Rotulo>
        </View>
        {inv.entradas.map((e) => (
          <View key={e.nome} style={estilos.linhaMppt}>
            <View style={[estilos.pontoMppt, { backgroundColor: tons[e.tom] }]} />
            <Num style={estilos.mpptNome}>{e.nome}</Num>
            <Num style={estilos.mpptTensao}>{e.tensao} V</Num>
            <Num style={estilos.mpptCorrente}>{e.corrente} A</Num>
          </View>
        ))}
      </Card>

      <Card semPadding>
        <View style={estilos.tituloBloco}>
          <Rotulo>Alarmes</Rotulo>
        </View>
        {inv.alarmes.map((a) => (
          <View key={a.id} style={estilos.linhaAlarme}>
            <View
              style={[
                estilos.iconeAlarme,
                {
                  backgroundColor: tomAlpha(a.tom, 0.1),
                  borderColor: tomAlpha(a.tom, 0.33),
                },
              ]}
            >
              <View style={[estilos.iconeAlarmeMiolo, { borderColor: tons[a.tom] }]} />
            </View>
            <View style={estilos.alarmeMiolo}>
              <Text style={estilos.alarmeTitulo}>{a.titulo}</Text>
              <Num style={estilos.alarmeQuando}>{a.quando}</Num>
            </View>
          </View>
        ))}
      </Card>

      <Card>
        <Rotulo>Identificação</Rotulo>
        <View style={estilos.identificacao}>
          {inv.identificacao.map((linha) => (
            <View key={linha.rotulo} style={estilos.linhaId}>
              <Text style={estilos.idRotulo}>{linha.rotulo}</Text>
              {linha.mono ? (
                <Num style={estilos.idValor}>{linha.valor}</Num>
              ) : (
                <Text style={estilos.idValorTexto}>{linha.valor}</Text>
              )}
            </View>
          ))}
        </View>
      </Card>

      <Botao titulo="Ver manutenção deste equipamento" variante="secundario" />
    </>
  )
}

function AbaGeracao() {
  const g = inversor.geracaoDia
  return (
    <>
      <Card>
        <Kpi
          valor={g.energiaKwh}
          unidade="kWh"
          tamanho="grande"
          direita={
            <Text style={tipo.legenda}>
              esperado <Num style={estilos.nominal}>{g.esperadoKwh}</Num>
            </Text>
          }
        />
        <View style={estilos.espacoGrafico}>
          <CurvaDia valores={g.curva} corteEm={g.indiceCorte} rotuloCorte={g.rotuloCorte} />
        </View>
        <RodapeNumeros
          itens={[
            { rotulo: 'pico', valor: g.picoKw, unidade: 'kW' },
            { rotulo: 'horas gerando', valor: g.horasGerando },
            { rotulo: 'perda estimada', valor: g.perdaEstimada, tom: 'parado' },
          ]}
        />
      </Card>

      <Card>
        <Rotulo>Comparado aos vizinhos</Rotulo>
        <View style={estilos.vizinhos}>
          {inversor.vizinhos.map((v) => (
            <BarraComparativa
              key={v.nome}
              nome={v.nome}
              pct={v.pct}
              valor={v.valor}
              destacado={v.destacado}
            />
          ))}
        </View>
        <Text style={estilos.notaVizinhos}>
          kWh no dia. A comparação entre inversores ainda não tem endpoint no meuWatt — o BFF
          monta a partir de /plants/{'{slug}'}/slots.
        </Text>
      </Card>
    </>
  )
}

const estilos = StyleSheet.create({
  avisoParada: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: tomAlpha('parado', 0.1),
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: espaco.md,
    paddingVertical: 14,
  },
  pontoParada: { width: 10, height: 10, borderRadius: 5, backgroundColor: tons.parado },
  avisoMiolo: { flex: 1 },
  avisoTitulo: { fontFamily: fontes.uiSemi, fontSize: 14.5, color: tons.parado },
  avisoNum: { fontFamily: fontes.monoSemi, fontSize: 14.5, color: tons.parado },
  avisoDetalhe: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 2 },
  avisoDetalheNum: { fontSize: 12, color: cores.textoRotulo },

  espacoKpi: { marginTop: 10 },
  espacoBarra: { marginTop: 14 },
  espacoGrafico: { marginTop: 18 },
  nominal: { fontSize: 12.5, color: cores.textoCorpo },

  tituloBloco: { paddingHorizontal: espaco.md, paddingTop: 14, paddingBottom: 6 },

  linhaMppt: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: espaco.md,
    paddingVertical: 11,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  pontoMppt: { width: 8, height: 8, borderRadius: 4 },
  mpptNome: { fontSize: 12.5, color: cores.textoRotulo },
  mpptTensao: { fontSize: 13, color: cores.textoForte, marginLeft: 'auto' },
  mpptCorrente: { fontSize: 13, color: cores.textoCorpo, width: 66, textAlign: 'right' },

  linhaAlarme: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: espaco.md,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  iconeAlarme: {
    width: 34,
    height: 34,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconeAlarmeMiolo: { width: 14, height: 14, borderRadius: 7, borderWidth: 2 },
  alarmeMiolo: { flex: 1 },
  alarmeTitulo: { fontFamily: fontes.uiSemi, fontSize: 14, color: cores.textoForte },
  alarmeQuando: { fontSize: 11.5, color: cores.textoFraco, marginTop: 3 },

  identificacao: { gap: 11, marginTop: 11 },
  linhaId: { flexDirection: 'row', justifyContent: 'space-between' },
  idRotulo: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoRotulo },
  idValor: { fontSize: 13, color: cores.textoCorpo },
  idValorTexto: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoCorpo },

  vizinhos: { gap: 11, marginTop: 14 },
  notaVizinhos: {
    fontFamily: fontes.ui,
    fontSize: 11,
    lineHeight: 16,
    color: cores.textoFraco,
    marginTop: 12,
  },
})
