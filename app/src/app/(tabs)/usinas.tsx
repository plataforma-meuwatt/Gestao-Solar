/**
 * Lista de usinas.
 *
 * Cada card responde "esta está bem?" sem precisar abrir: potência agora contra a
 * capacidade instalada, com a barra dando a proporção de relance. A usina sem
 * comunicação mostra travessão e barra vazia — nunca zero, que se leria como
 * "gerou nada" em vez de "não sabemos".
 */

import { router } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { Barra, Card, Chevron, Num, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import { totalUsinas, usinas, usuario, type Usina } from '@/features/exemplo'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

export default function Usinas() {
  return (
    <Tela
      titulo="Usinas"
      subtitulo={
        <Text style={tipo.secundario}>
          <Num style={estilos.subNum}>{totalUsinas.quantidade}</Num> usinas ·{' '}
          <Num style={estilos.subNum}>{totalUsinas.capacidade}</Num> MWp
        </Text>
      }
      avatar={{ iniciais: usuario.iniciais, temAviso: true, onPress: () => router.push('/perfil') }}
      paraTabBar
    >
      {usinas.map((u) => (
        <CardUsina key={u.id} usina={u} />
      ))}
    </Tela>
  )
}

function CardUsina({ usina }: { usina: Usina }) {
  const semDados = usina.potenciaKw === null

  return (
    <Pressable onPress={() => router.push(`/usina/${usina.id}`)}>
      <Card>
        <View style={estilos.topo}>
          <Text style={estilos.nome}>{usina.nome}</Text>
          <StatusChip tom={usina.tom} texto={usina.status} />
          <View style={estilos.espacador} />
          <Chevron />
        </View>

        <View style={estilos.linhaPotencia}>
          {semDados ? (
            <Num style={[estilos.potencia, { color: tons.semDados }]}>—</Num>
          ) : (
            <>
              <Num style={estilos.potencia}>{usina.potenciaKw}</Num>
              <Text style={estilos.unidade}>kW</Text>
            </>
          )}
          <Text style={estilos.capacidade}>
            de <Num style={estilos.capacidadeNum}>{usina.capacidadeKwp}</Num> kWp
          </Text>
        </View>

        <View style={estilos.barra}>
          <Barra pct={usina.pct} />
        </View>

        <View style={estilos.rodape}>
          <Text style={tipo.legenda}>
            {usina.cidade}, {usina.uf}
          </Text>
          <Text style={tipo.legenda}>
            {usina.energiaHoje ? (
              <>
                hoje <Num style={estilos.energia}>{usina.energiaHoje}</Num> MWh
              </>
            ) : (
              usina.rodape
            )}
          </Text>
        </View>
      </Card>
    </Pressable>
  )
}

const estilos = StyleSheet.create({
  subNum: { fontSize: 13, color: cores.textoRotulo },

  topo: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  nome: { fontFamily: fontes.uiSemi, fontSize: 16, color: cores.textoForte },
  espacador: { flex: 1 },

  linhaPotencia: { flexDirection: 'row', alignItems: 'baseline', gap: 7, marginTop: 12 },
  potencia: { fontFamily: fontes.monoSemi, fontSize: 30, lineHeight: 30, color: cores.textoForte },
  unidade: { fontFamily: fontes.ui, fontSize: 14, color: cores.textoCorpo },
  capacidade: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginLeft: 'auto' },
  capacidadeNum: { fontSize: 12, color: cores.textoCorpo },

  barra: { marginTop: 12 },
  rodape: { flexDirection: 'row', justifyContent: 'space-between', marginTop: espaco.sm },
  energia: { fontSize: 12, color: cores.textoForte },
})
