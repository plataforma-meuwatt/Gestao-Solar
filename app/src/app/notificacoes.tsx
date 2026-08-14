/**
 * Notificações.
 *
 * O segmentado filtra de verdade — **Ação** são as que pedem decisão do dono (inversor
 * parado, serviço em aberto, mensalidade vencida); **Sistema** é o que só informa. Quem
 * separa é o servidor; a tela nunca recalcula.
 *
 * Antes esta lista era três avisos escritos à mão, com "há 2 h" fixo — inclusive um sobre
 * "perda por nuvens", que não existe como evento em produto nenhum. Agora vem de
 * `GET /api/v1/notifications`, montada a partir do que está de fato aberto.
 *
 * **Não há "marcar como lida", e é de propósito.** Os endpoints dos dois produtos gravam
 * na caixa do dono do token — que é o token de serviço do BFF, não o do cliente. Marcar
 * lido marcaria para a pessoa errada. Enquanto for assim, a tela é um retrato do agora, e
 * "puxe para atualizar" virou o que sempre deveria ter sido: um gesto que recarrega.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'

import { Esqueleto, EstadoVazio, ItemLista, Segmentado } from '@/components/base'
import { Tela } from '@/components/Tela'
import { useNotificacoes } from '@/features/notificacoes'
import { quando } from '@/lib/format'
import { cores, espaco, fontes } from '@/theme/tokens'

const GRUPOS = ['Tudo', 'Ação', 'Sistema'] as const

export default function Notificacoes() {
  const [seg, setSeg] = useState(0)
  const { dados, carregando, erro, offlineDesde, atualizando, recarregar } = useNotificacoes()

  const todas = dados?.notificacoes ?? []
  const lista = todas.filter((n) =>
    seg === 0 ? true : seg === 1 ? n.grupo === 'acao' : n.grupo === 'sistema',
  )

  return (
    <Tela
      titulo="Notificações"
      subtitulo={dados && dados.acoes > 0 ? `${dados.acoes} pedem atenção` : undefined}
      voltar
      offlineDesde={offlineDesde}
      semRolagem
    >
      <View style={estilos.filtro}>
        <Segmentado opcoes={[...GRUPOS]} ativo={seg} onEscolher={setSeg} />
      </View>

      {carregando ? (
        <View style={estilos.fantasma}>
          {[0, 1, 2].map((i) => (
            <View key={i} style={estilos.linhaFantasma}>
              <Esqueleto largura="70%" altura={14} forte />
              <Esqueleto largura="45%" altura={11} />
            </View>
          ))}
        </View>
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : lista.length === 0 ? (
        <EstadoVazio
          titulo={seg === 0 ? 'Nada aberto por aqui' : 'Nada neste grupo'}
          descricao={
            dados?.aviso ??
            'Alertas de geração, serviços em aberto e mensalidades aparecem nesta tela.'
          }
        />
      ) : (
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={estilos.lista}
          refreshControl={
            <RefreshControl
              refreshing={atualizando}
              onRefresh={recarregar}
              tintColor={cores.textoRotulo}
            />
          }
        >
          {dados?.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}
          {lista.map((n, i) => (
            <ItemLista
              key={n.id}
              tom={n.tom}
              titulo={n.titulo}
              resumo={n.usina && !n.resumo.includes(n.usina) ? `${n.usina} · ${n.resumo}` : n.resumo}
              quando={n.em ? quando(n.em) : undefined}
              naoLido={n.grupo === 'acao'}
              primeiro={i === 0}
              onPress={n.plant_id ? () => router.push(`/usina/${n.plant_id}`) : undefined}
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
  fantasma: { paddingHorizontal: espaco.md, gap: espaco.md, paddingTop: espaco.xs },
  linhaFantasma: { gap: 8, paddingVertical: 10 },
  aviso: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    color: cores.textoRotulo,
    paddingHorizontal: espaco.md,
    paddingBottom: 10,
  },
})
