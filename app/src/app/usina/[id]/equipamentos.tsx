/**
 * Equipamentos da usina.
 *
 * A contagem do topo existe para o dono não precisar percorrer a lista para saber se há
 * problema. Tudo vem de `GET /api/v1/plants/{id}/equipamentos` — antes esta tela mostrava
 * os mesmos oito inversores fictícios (INV-01 a INV-08, "2 parados há 3 h 10") para
 * qualquer usina de qualquer cliente.
 *
 * Inversor **ignorado** no meuWatt aparece na lista, apagado, e fica fora das contagens:
 * silenciá-lo foi decisão de quem opera, e contá-lo como problema seria discutir com essa
 * decisão a cada abertura.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  Card,
  Chevron,
  Esqueleto,
  EstadoVazio,
  Num,
  StatusChip,
} from '@/components/base'
import { Tela } from '@/components/Tela'
import { useEquipamentos, type Equipamento } from '@/features/equipamentos'
import { duracao, energia, hora, inteiro, potencia } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

export default function Equipamentos() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { dados, carregando, erro, offlineDesde, recarregar } = useEquipamentos(id)

  return (
    <Tela
      titulo="Equipamentos"
      subtitulo={
        dados ? (
          <Text style={tipo.secundario}>
            {dados.usina}
            {dados.total !== null ? (
              <>
                {' · '}
                <Num style={estilos.subNum}>{inteiro(dados.total)}</Num> inversores
              </>
            ) : null}
          </Text>
        ) : undefined
      }
      voltar
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
      ) : !dados || dados.equipamentos.length === 0 ? (
        <EstadoVazio
          titulo="Nenhum inversor"
          descricao={dados?.aviso ?? 'Esta usina não devolveu inversores no monitoramento.'}
        />
      ) : (
        <>
          <View style={estilos.resumo}>
            {dados.parados ? (
              <>
                <Num style={[estilos.resumoNum, { color: tons.parado }]}>{dados.parados}</Num>
                <Text style={tipo.legenda}>{dados.parados === 1 ? 'parado' : 'parados'}</Text>
              </>
            ) : null}
            {dados.alerta ? (
              <>
                <Num style={[estilos.resumoNum, { color: tons.alerta }]}>{dados.alerta}</Num>
                <Text style={tipo.legenda}>em alerta</Text>
              </>
            ) : null}
            {dados.sem_dados ? (
              <>
                <Num style={[estilos.resumoNum, { color: tons.semDados }]}>{dados.sem_dados}</Num>
                <Text style={tipo.legenda}>sem dados</Text>
              </>
            ) : null}
            {/* "Todos gerando" só quando estão MESMO gerando. De madrugada os três
                contadores de problema ficam em zero — todo inversor é `dormindo` — e a
                versão anterior afirmava "Todos gerando" no topo de uma lista em que cada
                card dizia "Fora da janela solar". */}
            {dados.dormindo ? (
              <>
                <View style={[estilos.ponto, { backgroundColor: tons.semDados }]} />
                <Text style={tipo.legenda}>
                  {dados.dormindo === dados.total
                    ? 'Fora da janela solar'
                    : `${dados.dormindo} fora da janela solar`}
                </Text>
              </>
            ) : !dados.parados && !dados.alerta && !dados.sem_dados ? (
              <>
                <View style={[estilos.ponto, { backgroundColor: tons.ok }]} />
                <Text style={tipo.legenda}>Todos gerando</Text>
              </>
            ) : null}
            <View style={estilos.espacador} />
            {dados.atualizado_em ? (
              <Text style={tipo.legenda}>
                <Num style={estilos.subNum}>{hora(dados.atualizado_em)}</Num>
              </Text>
            ) : null}
          </View>

          {dados.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}

          {dados.equipamentos.map((e) => (
            <CardEquipamento key={e.id} equipamento={e} usinaId={id} />
          ))}
        </>
      )}
    </Tela>
  )
}

function CardEquipamento({ equipamento: e, usinaId }: { equipamento: Equipamento; usinaId?: string }) {
  const semDados = e.potencia_kw === null
  const [valor, unidade] = potencia(e.potencia_kw).split(' ')

  return (
    <Pressable onPress={() => router.push(`/equipamento/${e.id}?usina=${usinaId ?? ''}`)}>
      <Card>
        <View style={[estilos.topo, e.ignorado && estilos.apagado]}>
          <Text style={estilos.nome}>{e.nome}</Text>
          <StatusChip tom={e.tom} texto={e.situacao} />
          <View style={estilos.espacador} />
          <Chevron />
        </View>

        <View style={[estilos.linhaPotencia, e.ignorado && estilos.apagado]}>
          {semDados ? (
            <Num style={[estilos.potencia, { color: tons.semDados }]}>—</Num>
          ) : (
            <>
              <Num style={estilos.potencia}>{valor}</Num>
              <Text style={estilos.unidade}>{unidade}</Text>
            </>
          )}
          {e.capacidade_kwp ? (
            <Text style={estilos.capacidade}>
              de <Num style={estilos.capacidadeNum}>{inteiro(e.capacidade_kwp)}</Num> kWp
            </Text>
          ) : null}
        </View>

        <View style={estilos.barra}>
          <Barra pct={e.pct_capacidade ?? 0} tom={e.tom === 'ok' ? undefined : e.tom} />
        </View>

        <View style={estilos.rodape}>
          <Text style={tipo.legenda} numberOfLines={1}>
            {e.modelo ?? e.serial ?? '—'}
          </Text>
          <Text style={tipo.legenda}>
            {e.energia_hoje_kwh !== null ? (
              <>
                hoje <Num style={estilos.energia}>{energia(e.energia_hoje_kwh)}</Num>
              </>
            ) : e.parado_ha_min !== null ? (
              <>
                parado há <Num style={estilos.energia}>{duracao(e.parado_ha_min)}</Num>
              </>
            ) : (
              '—'
            )}
          </Text>
        </View>
      </Card>
    </Pressable>
  )
}

function Fantasma() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <View style={estilos.topo}>
            <Esqueleto largura="30%" altura={16} forte />
            <View style={estilos.espacador} />
            <Esqueleto largura={70} altura={18} />
          </View>
          <View style={estilos.linhaPotencia}>
            <Esqueleto largura="35%" altura={26} forte />
          </View>
          <View style={estilos.barra}>
            <Esqueleto altura={6} />
          </View>
        </Card>
      ))}
    </>
  )
}

const estilos = StyleSheet.create({
  subNum: { fontSize: 13, color: cores.textoRotulo },

  resumo: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: espaco.xs },
  resumoNum: { fontSize: 15 },
  ponto: { width: 8, height: 8, borderRadius: 4 },
  espacador: { flex: 1 },

  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },

  topo: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  nome: { fontFamily: fontes.uiSemi, fontSize: 16, color: cores.textoForte },
  /** Ignorado no meuWatt: presente, mas visivelmente fora da conta. */
  apagado: { opacity: 0.45 },

  linhaPotencia: { flexDirection: 'row', alignItems: 'baseline', gap: 7, marginTop: 12 },
  potencia: { fontFamily: fontes.monoSemi, fontSize: 26, lineHeight: 26, color: cores.textoForte },
  unidade: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoCorpo },
  capacidade: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginLeft: 'auto' },
  capacidadeNum: { fontSize: 12, color: cores.textoCorpo },

  barra: { marginTop: 12 },
  rodape: { flexDirection: 'row', justifyContent: 'space-between', marginTop: espaco.sm, gap: 12 },
  energia: { fontSize: 12, color: cores.textoForte },
})
