/**
 * Os três gráficos da rodada 1. Todos em `react-native-svg` direto — nenhuma biblioteca
 * de charts: são formas simples, e uma dependência de gráfico traria um sistema de temas
 * paralelo ao nosso, que é justamente o que a prancha de sistema evita.
 *
 * Regra comum: cor só significa estado. Âmbar translúcido é o normal, âmbar cheio é o
 * pico, azul-claro é perda por tempo ruim, vermelho é parada.
 */

import { StyleSheet, Text, View } from 'react-native'
import Svg, { Line, Path } from 'react-native-svg'

import { Num } from '@/components/base'
import { ambarAlpha, cores, espaco, fontes, tomAlpha, tons } from '@/theme/tokens'

/** Rótulos de hora sob um gráfico do dia. */
function EixoHoras({ horas }: { horas: string[] }) {
  return (
    <View style={estilos.eixo}>
      {horas.map((h) => (
        <Num key={h} style={estilos.eixoTexto}>
          {h}
        </Num>
      ))}
    </View>
  )
}

/**
 * Barras da geração ao longo do dia. `destaque` marca a barra do pico em âmbar cheio —
 * é o que responde "a que horas ela rendeu mais".
 */
export function BarrasDia({
  valores,
  destaque,
  altura = 118,
}: {
  valores: number[]
  destaque?: number
  altura?: number
}) {
  const max = Math.max(...valores, 0.0001)
  return (
    <View>
      <View style={[estilos.barras, { height: altura }]}>
        {valores.map((v, i) => (
          <View
            key={i}
            style={[
              estilos.barra,
              {
                height: Math.max(2, (v / max) * altura),
                backgroundColor: i === destaque ? cores.ambar : ambarAlpha(0.45),
              },
            ]}
          />
        ))}
      </View>
      <EixoHoras horas={['06', '09', '12', '15', '18']} />
    </View>
  )
}

/**
 * Barras dia a dia do mês. Dias com perda climática saem em azul-claro; dias ainda não
 * ocorridos ficam no cinza da superfície — a barra vazia diz "ainda não aconteceu", não
 * "gerou zero".
 */
export function BarrasMes({
  valores,
  limiarTempoRuim,
  altura = 62,
}: {
  valores: number[]
  /** Abaixo deste valor, o dia é atribuído a tempo ruim. */
  limiarTempoRuim: number
  altura?: number
}) {
  const max = Math.max(...valores, 0.0001)
  return (
    <View>
      <View style={[estilos.barrasMes, { height: altura }]}>
        {valores.map((v, i) => (
          <View
            key={i}
            style={[
              estilos.barraMes,
              {
                height: Math.max(2, (v / max) * altura),
                backgroundColor:
                  v === 0
                    ? cores.borda
                    : v < limiarTempoRuim
                      ? tons.tempoRuim
                      : ambarAlpha(0.55),
              },
            ]}
          />
        ))}
      </View>
      <View style={estilos.eixo}>
        {['01', '10', '20', '31'].map((d) => (
          <Num key={d} style={estilos.eixoTexto}>
            {d}
          </Num>
        ))}
      </View>
      <View style={estilos.legenda}>
        <ItemLegenda cor={ambarAlpha(0.55)} texto="normal" />
        <ItemLegenda cor={tons.tempoRuim} texto="perda por tempo ruim" />
      </View>
    </View>
  )
}

function ItemLegenda({ cor, texto }: { cor: string; texto: string }) {
  return (
    <View style={estilos.itemLegenda}>
      <View style={[estilos.marcaLegenda, { backgroundColor: cor }]} />
      <Text style={estilos.textoLegenda}>{texto}</Text>
    </View>
  )
}

/**
 * Curva de potência do dia com a marca da parada.
 *
 * `corteEm` é o índice em que o equipamento parou: a linha tracejada vermelha ali é o
 * que transforma "gerou pouco" em "parou às 11:20" — sem ela o gráfico não explica nada.
 */
export function CurvaDia({
  valores,
  corteEm,
  rotuloCorte,
  altura = 140,
}: {
  valores: number[]
  corteEm?: number
  rotuloCorte?: string
  altura?: number
}) {
  const L = 326
  const max = Math.max(...valores, 0.0001)
  const px = (i: number) => (i / (valores.length - 1)) * L
  const py = (v: number) => altura - (v / max) * altura

  const pontos = valores.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' L')
  const linha = `M${pontos}`
  const area = `M0,${altura} L${pontos} L${L},${altura} Z`
  const xCorte = corteEm !== undefined ? px(corteEm) : null

  return (
    <View>
      <View>
        <Svg width="100%" height={altura} viewBox={`0 0 ${L} ${altura}`} preserveAspectRatio="none">
          {[0, altura / 2, altura].map((y, i) => (
            <Line
              key={y}
              x1={0}
              y1={y}
              x2={L}
              y2={y}
              stroke={i === 2 ? cores.bordaForte : cores.bordaFraca}
              strokeWidth={1}
            />
          ))}
          <Path d={area} fill={ambarAlpha(0.16)} />
          <Path d={linha} fill="none" stroke={cores.ambar} strokeWidth={2.5} strokeLinejoin="round" />
          {xCorte !== null ? (
            <Line
              x1={xCorte}
              y1={0}
              x2={xCorte}
              y2={altura}
              stroke={tons.parado}
              strokeWidth={1.5}
              strokeDasharray="4 4"
            />
          ) : null}
        </Svg>
        {rotuloCorte && xCorte !== null ? (
          <View style={[estilos.rotuloCorte, { left: `${(xCorte / L) * 100}%` }]}>
            <Num style={estilos.rotuloCorteTexto}>{rotuloCorte}</Num>
          </View>
        ) : null}
      </View>
      <EixoHoras horas={['06', '09', '12', '15', '18']} />
    </View>
  )
}

/**
 * Doze células, uma por mês, com a cor de conformidade que o meuPlano já calcula.
 * Vazio = o mês ainda não chegou ou o serviço não se aplica.
 */
export function CelulasDoAno({ meses }: { meses: (keyof typeof tons | null)[] }) {
  return (
    <View>
      <View style={estilos.celulas}>
        {meses.map((m, i) => (
          <View
            key={i}
            style={[
              estilos.celula,
              m
                ? { backgroundColor: tomAlpha(m, 0.18), borderColor: tomAlpha(m, 0.55) }
                : { backgroundColor: cores.superficie, borderColor: cores.borda },
            ]}
          />
        ))}
      </View>
      <View style={estilos.eixo}>
        <Num style={estilos.eixoTexto}>JAN</Num>
        <Num style={estilos.eixoTexto}>DEZ</Num>
      </View>
    </View>
  )
}

/** Barra horizontal de comparação entre pares (inversor × vizinhos). */
export function BarraComparativa({
  nome,
  pct,
  valor,
  destacado,
}: {
  nome: string
  pct: number
  valor: string
  destacado?: boolean
}) {
  const cor = destacado ? tons.parado : ambarAlpha(0.55)
  return (
    <View style={estilos.comparativa}>
      <Num style={[estilos.comparativaNome, destacado && { color: tons.parado }]}>{nome}</Num>
      <View style={estilos.comparativaTrilho}>
        <View style={[estilos.comparativaPreenchida, { width: `${pct}%`, backgroundColor: cor }]} />
      </View>
      <Num style={[estilos.comparativaValor, destacado && { color: tons.parado }]}>{valor}</Num>
    </View>
  )
}

const estilos = StyleSheet.create({
  barras: { flexDirection: 'row', alignItems: 'flex-end', gap: espaco.xs },
  barra: { flex: 1, borderTopLeftRadius: 3, borderTopRightRadius: 3 },

  barrasMes: { flexDirection: 'row', alignItems: 'flex-end', gap: 2 },
  barraMes: { flex: 1, borderTopLeftRadius: 2, borderTopRightRadius: 2 },

  eixo: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 7 },
  eixoTexto: { fontSize: 10, color: cores.textoFraco },

  legenda: { flexDirection: 'row', gap: 14, marginTop: 12 },
  itemLegenda: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  marcaLegenda: { width: 8, height: 8, borderRadius: 2 },
  textoLegenda: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo },

  rotuloCorte: {
    position: 'absolute',
    top: 0,
    marginLeft: -34,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: tomAlpha('parado', 0.1),
    borderWidth: 1,
    borderColor: tomAlpha('parado', 0.33),
  },
  rotuloCorteTexto: { fontFamily: fontes.monoSemi, fontSize: 10.5, color: tons.parado },

  celulas: { flexDirection: 'row', gap: espaco.xs },
  celula: { flex: 1, height: 22, borderRadius: 4, borderWidth: 1 },

  comparativa: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  comparativaNome: { fontSize: 12, color: cores.textoRotulo, width: 52 },
  comparativaTrilho: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    backgroundColor: cores.afundado,
    overflow: 'hidden',
  },
  comparativaPreenchida: { height: '100%', borderRadius: 4 },
  comparativaValor: {
    fontSize: 12.5,
    color: cores.textoCorpo,
    width: 52,
    textAlign: 'right',
  },
})
