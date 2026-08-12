/**
 * Notificações.
 *
 * O segmentado filtra de verdade — Ação são as que pedem uma decisão do dono (inversor
 * parado, serviço vencido, fatura), Sistema é o que só informa. A separação é do
 * servidor no meuPlano (`notification_groups.py`); aqui ela nunca é recalculada.
 */

import { useState } from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'

import { EstadoVazio, ItemLista, Segmentado } from '@/components/base'
import { Tela } from '@/components/Tela'
import { notificacoes } from '@/features/exemplo'
import { cores, espaco, fontes } from '@/theme/tokens'

const GRUPOS = ['Tudo', 'Ação', 'Sistema'] as const

export default function Notificacoes() {
  const [seg, setSeg] = useState(0)

  const lista = notificacoes.filter((n) =>
    seg === 0 ? true : seg === 1 ? n.grupo === 'acao' : n.grupo === 'sistema',
  )
  const naoLidas = notificacoes.filter((n) => !n.lida).length

  return (
    <Tela
      titulo="Notificações"
      subtitulo={naoLidas > 0 ? `${naoLidas} não lidas` : undefined}
      voltar
      semRolagem
    >
      <View style={estilos.filtro}>
        <Segmentado opcoes={[...GRUPOS]} ativo={seg} onEscolher={setSeg} />
      </View>

      {lista.length === 0 ? (
        <EstadoVazio
          titulo="Nenhuma notificação por aqui"
          descricao="Avisos de geração, manutenção e cobrança aparecem nesta tela."
        />
      ) : (
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={estilos.lista}>
          <Text style={estilos.puxar}>puxe para atualizar</Text>
          {lista.map((n, i) => (
            <ItemLista
              key={n.id}
              tom={n.tom}
              titulo={n.titulo}
              resumo={n.resumo}
              quando={n.quando}
              naoLido={!n.lida}
              primeiro={i === 0}
            />
          ))}
        </ScrollView>
      )}
    </Tela>
  )
}

const estilos = StyleSheet.create({
  filtro: { paddingHorizontal: espaco.md, paddingTop: 14, paddingBottom: 10 },
  lista: { paddingBottom: espaco.md },
  puxar: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    color: cores.textoFraco,
    textAlign: 'center',
    paddingTop: 6,
    paddingBottom: 10,
  },
})
