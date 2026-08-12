/**
 * Equipamentos da usina.
 *
 * A contagem do topo ("2 parados · 1 em alerta · 1 sem dados") existe para o dono não
 * precisar percorrer a lista para saber se há problema. O filtro é lista suspensa, não
 * fileira de chips — regra do produto.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { Barra, Card, Chevron, Num, SeletorLista, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import { equipamentos, resumoEquipamentos, usinaDetalhe, type Equipamento } from '@/features/exemplo'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

export default function Equipamentos() {
  const { id } = useLocalSearchParams<{ id: string }>()

  return (
    <Tela
      titulo="Equipamentos"
      subtitulo={
        <Text style={tipo.secundario}>
          {usinaDetalhe.nome} · <Num style={estilos.subNum}>{usinaDetalhe.inversores}</Num>{' '}
          inversores
        </Text>
      }
      voltar
      paraTabBar
    >
      <SeletorLista valor="Todos os status" />

      <View style={estilos.resumo}>
        <Num style={[estilos.resumoNum, { color: tons.parado }]}>{resumoEquipamentos.parados}</Num>
        <Text style={tipo.legenda}>parados ·</Text>
        <Num style={[estilos.resumoNum, { color: tons.alerta }]}>{resumoEquipamentos.alerta}</Num>
        <Text style={tipo.legenda}>em alerta ·</Text>
        <Num style={[estilos.resumoNum, { color: tons.semDados }]}>
          {resumoEquipamentos.semDados}
        </Num>
        <Text style={tipo.legenda}>sem dados</Text>
      </View>

      {equipamentos.map((e) => (
        <CardEquipamento key={e.id} equipamento={e} usinaId={id} />
      ))}
    </Tela>
  )
}

function CardEquipamento({ equipamento, usinaId }: { equipamento: Equipamento; usinaId?: string }) {
  const semDados = equipamento.potencia === '—'
  return (
    <Pressable onPress={() => router.push(`/equipamento/${equipamento.id}?usina=${usinaId ?? ''}`)}>
      <Card style={estilos.card}>
        <View style={estilos.topo}>
          <Num style={estilos.nome}>{equipamento.nome}</Num>
          <StatusChip tom={equipamento.tom} texto={equipamento.status} />
          <View style={estilos.espacador} />
          <Num style={[estilos.potencia, semDados && { color: tons.semDados }]}>
            {equipamento.potencia}
          </Num>
          {!semDados ? <Text style={estilos.unidade}>kW</Text> : null}
          <View style={estilos.seta}>
            <Chevron />
          </View>
        </View>

        <View style={estilos.barra}>
          <Barra pct={equipamento.pct} tom={equipamento.tom} fina />
        </View>

        <Num style={estilos.modelo}>{equipamento.modelo}</Num>
      </Card>
    </Pressable>
  )
}

const estilos = StyleSheet.create({
  subNum: { fontSize: 13, color: cores.textoRotulo },

  resumo: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: -espaco.sm },
  resumoNum: { fontFamily: fontes.monoSemi, fontSize: 12 },

  card: { paddingBottom: 12 },
  topo: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  nome: { fontFamily: fontes.monoSemi, fontSize: 15, color: cores.textoForte },
  espacador: { flex: 1 },
  potencia: { fontFamily: fontes.monoSemi, fontSize: 17, color: cores.textoForte },
  unidade: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo },
  seta: { marginLeft: espaco.xs },

  barra: { marginTop: 12 },
  modelo: { fontSize: 11.5, color: cores.textoFraco, marginTop: 7 },
})
