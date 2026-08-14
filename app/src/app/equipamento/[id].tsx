/**
 * Um inversor.
 *
 * Antes esta tela mostrava sempre o mesmo aparelho fictício — "SUN2000-100KTL, 100,0 kW
 * nominais, PR do mês 79,1%, parado desde 11:20" — independentemente de qual inversor
 * fosse tocado. Agora vem de `GET /api/v1/plants/{id}/equipamentos/{slot}`.
 *
 * Três blocos que existiam e **saíram por não terem fonte**, e não vão voltar como número
 * plausível: *PR do inversor* (performance ratio é por usina, depende da irradiância da
 * estação solarimétrica), *potência nominal AC* (o que o upstream tem é capacidade CC
 * instalada, que é outra coisa) e *histórico de paradas* (depende de `breakdowns/range`,
 * que responde 500 em produção).
 */

import { useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  CabecalhoCard,
  Card,
  Esqueleto,
  EstadoVazio,
  FaixaAtencao,
  Kpi,
  Num,
  StatusChip,
} from '@/components/base'
import { Tela } from '@/components/Tela'
import { useEquipamento } from '@/features/equipamentos'
import { duracao, energia, hora, numero, porcento, potencia } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

export default function Equipamento() {
  const { id, usina } = useLocalSearchParams<{ id: string; usina?: string }>()
  const { dados: e, carregando, erro, offlineDesde, recarregar } = useEquipamento(usina, id)

  if (carregando || !e) {
    return (
      <Tela titulo="Equipamento" voltar paraTabBar>
        {erro ? (
          <EstadoVazio
            tom="parado"
            titulo="Não deu para carregar"
            descricao={erro}
            acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
          />
        ) : (
          <Card>
            <Esqueleto largura="45%" altura={18} forte />
            <View style={{ marginTop: 16 }}>
              <Esqueleto largura="55%" altura={30} forte />
            </View>
            <View style={{ marginTop: 16 }}>
              <Esqueleto altura={6} />
            </View>
          </Card>
        )}
      </Tela>
    )
  }

  const semDados = e.potencia_kw === null

  return (
    <Tela
      titulo={e.nome}
      subtitulo={
        <Text style={tipo.secundario}>
          {e.usina}
          {e.modelo ? ` · ${e.modelo}` : ''}
        </Text>
      }
      voltar
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {e.ignorado ? (
        <FaixaAtencao
          tom="semDados"
          titulo="Ignorado no monitoramento"
          detalhe="Silenciado por quem opera a usina — fora das contagens de problema."
        />
      ) : null}

      {e.fabricante_alerta ? (
        <FaixaAtencao tom={e.tom} titulo={e.fabricante_alerta} detalhe={e.causa_parada ?? undefined} />
      ) : null}

      <Card>
        <View style={estilos.topo}>
          <StatusChip tom={e.tom} texto={e.situacao} />
          <View style={estilos.espacador} />
          {e.medido_em ? (
            <Text style={tipo.legenda}>
              <Num style={estilos.legendaNum}>{hora(e.medido_em)}</Num>
            </Text>
          ) : null}
        </View>

        <View style={estilos.kpi}>
          <Kpi
            valor={semDados ? '—' : potencia(e.potencia_kw)}
            tamanho="grande"
            direita={
              e.energia_hoje_kwh !== null ? (
                <Text style={tipo.legenda}>
                  hoje <Num style={estilos.legendaForte}>{energia(e.energia_hoje_kwh)}</Num>
                </Text>
              ) : undefined
            }
          />
        </View>

        {e.pct_capacidade !== null ? (
          <>
            <View style={estilos.barra}>
              <Barra pct={e.pct_capacidade} tom={e.tom === 'ok' ? undefined : e.tom} />
            </View>
            <Text style={tipo.legenda}>
              <Num style={estilos.legendaForte}>{e.pct_capacidade}%</Num> de{' '}
              <Num style={estilos.legendaForte}>{numero(e.capacidade_kwp, 1)}</Num> kWp
              instalados
            </Text>
          </>
        ) : null}

        {e.parado_ha_min !== null ? (
          <Text style={estilos.parado}>
            Parado há <Num style={estilos.legendaForte}>{duracao(e.parado_ha_min)}</Num>
            {e.causa_parada ? ` · ${e.causa_parada}` : ''}
          </Text>
        ) : null}
      </Card>

      <Card>
        <CabecalhoCard rotulo="O aparelho" />
        <View style={estilos.linhas}>
          <Linha rotulo="Número de série" valor={e.serial ?? '—'} />
          <Linha rotulo="Modelo" valor={e.modelo ?? '—'} />
          {e.transformador ? <Linha rotulo="Transformador" valor={e.transformador} /> : null}
          {e.temperatura_c !== null ? (
            <Linha rotulo="Temperatura" valor={`${numero(e.temperatura_c, 1)} °C`} />
          ) : null}
          {e.performance_pct !== null ? (
            <Linha rotulo="Desempenho" valor={porcento(e.performance_pct)} />
          ) : null}
          {e.desvio_mediana !== null ? (
            <Linha
              rotulo="Contra a mediana dos irmãos"
              valor={`${e.desvio_mediana > 0 ? '+' : ''}${numero(e.desvio_mediana * 100, 1)}%`}
            />
          ) : null}
        </View>
      </Card>

      {e.entradas.length > 0 ? (
        <Card>
          <CabecalhoCard
            rotulo="Entradas"
            direita={<Text style={tipo.legenda}>{e.entradas.length} MPPT</Text>}
          />
          <View style={estilos.entradas}>
            {e.entradas.map((m) => (
              <View key={m.numero} style={estilos.entrada}>
                <Text style={estilos.entradaNum}>{m.numero}</Text>
                <Num style={estilos.entradaValor}>
                  {m.tensao_v !== null ? `${numero(m.tensao_v, 0)} V` : '—'}
                </Num>
                <Num style={estilos.entradaSec}>
                  {m.corrente_a !== null ? `${numero(m.corrente_a, 1)} A` : '—'}
                </Num>
              </View>
            ))}
          </View>
        </Card>
      ) : null}

      {e.aviso ? <Text style={estilos.aviso}>{e.aviso}</Text> : null}
    </Tela>
  )
}

function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <View style={estilos.linha}>
      <Text style={tipo.legenda}>{rotulo}</Text>
      <Num style={estilos.linhaValor}>{valor}</Num>
    </View>
  )
}

const estilos = StyleSheet.create({
  topo: { flexDirection: 'row', alignItems: 'center' },
  espacador: { flex: 1 },
  legendaNum: { fontSize: 12, color: cores.textoRotulo },
  legendaForte: { fontSize: 12, color: cores.textoForte },

  kpi: { marginTop: 12 },
  barra: { marginVertical: 12 },
  parado: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: tons.parado,
    marginTop: espaco.sm,
    paddingTop: espaco.sm,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },

  linhas: { marginTop: espaco.sm, gap: 9 },
  linha: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  linhaValor: { fontSize: 12.5, color: cores.textoForte, flexShrink: 1 },

  entradas: { marginTop: espaco.sm, gap: 6 },
  entrada: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  entradaNum: {
    fontFamily: fontes.monoSemi,
    fontSize: 11,
    color: cores.textoRotulo,
    width: 22,
  },
  entradaValor: { fontSize: 12.5, color: cores.textoForte, width: 78 },
  entradaSec: { fontSize: 12, color: cores.textoCorpo },

  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },
})
