/**
 * Lista de usinas.
 *
 * Cada card responde "esta está bem?" sem precisar abrir: potência agora contra a
 * capacidade instalada, com a barra dando a proporção de relance. A usina sem
 * comunicação mostra travessão e barra vazia — nunca zero, que se leria como
 * "gerou nada" em vez de "não sabemos".
 *
 * A cor e a frase de status vêm prontas do BFF. A tela não decide se uma usina está bem:
 * essa régua é a mesma no meuWatt e mudaria com a loja no meio do caminho.
 */

import { router } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { Barra, Card, Chevron, Esqueleto, EstadoVazio, Num, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import { useUsinas, type Usina } from '@/features/usinas'
import { energia, inteiro, numero, potencia } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

export default function Usinas() {
  const { dados, carregando, erro, offlineDesde, recarregar } = useUsinas()
  const usuario = useAuth((s) => s.usuario)

  const lista = dados?.usinas ?? []

  return (
    <Tela
      titulo="Usinas"
      subtitulo={
        dados ? (
          <Text style={tipo.secundario}>
            <Num style={estilos.subNum}>{lista.length}</Num> usinas
            {/* A capacidade só aparece quando existe. Sem ela `total_kwp` é 0 — a
                capacidade vem dos inversores, e uma ponte fora do ar zera a soma. Exibir
                "0,0 MWp" seria fabricar um número para um desconhecido, e logo no
                subtítulo da tela. */}
            {dados.total_kwp > 0 ? (
              <>
                {' · '}
                <Num style={estilos.subNum}>{numero(dados.total_kwp / 1000, 1)}</Num> MWp
              </>
            ) : null}
          </Text>
        ) : undefined
      }
      avatar={{
        iniciais: iniciaisDe(usuario?.nome),
        temAviso: Boolean(dados?.aviso),
        onPress: () => router.push('/perfil'),
      }}
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {carregando ? (
        <CardsFantasma />
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : lista.length === 0 ? (
        <EstadoVazio
          titulo="Nenhuma usina ainda"
          descricao={
            dados?.aviso ??
            'Assim que uma usina for liberada para a sua conta, ela aparece aqui.'
          }
        />
      ) : (
        lista.map((u) => <CardUsina key={u.id} usina={u} />)
      )}
    </Tela>
  )
}

/** Iniciais para o avatar: as do primeiro e do último nome. */
function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  const primeira = partes[0][0]
  const ultima = partes.length > 1 ? partes[partes.length - 1][0] : ''
  return (primeira + ultima).toUpperCase()
}

function CardUsina({ usina }: { usina: Usina }) {
  const semDados = usina.potencia_kw === null
  // `potencia()` escolhe kW ou MW pela ordem de grandeza e formata em pt-BR; o design
  // pede o número grande e a unidade pequena ao lado, daí a separação.
  const [valor, unidade] = potencia(usina.potencia_kw).split(' ')
  const local = [usina.cidade, usina.uf].filter(Boolean).join(', ')

  return (
    <Pressable onPress={() => router.push(`/usina/${usina.id}`)}>
      <Card>
        <View style={estilos.topo}>
          <Text style={estilos.nome}>{usina.nome}</Text>
          <StatusChip tom={usina.tom} texto={usina.situacao} />
          <View style={estilos.espacador} />
          <Chevron />
        </View>

        <View style={estilos.linhaPotencia}>
          {semDados ? (
            <Num style={[estilos.potencia, { color: tons.semDados }]}>—</Num>
          ) : (
            <>
              <Num style={estilos.potencia}>{valor}</Num>
              <Text style={estilos.unidade}>{unidade}</Text>
            </>
          )}
          {usina.capacidade_kwp ? (
            <Text style={estilos.capacidade}>
              de <Num style={estilos.capacidadeNum}>{inteiro(usina.capacidade_kwp)}</Num> kWp
            </Text>
          ) : null}
        </View>

        {/* Sem percentual, NENHUMA barra. Uma barra vazia se lê como "não está gerando
            nada", que é uma afirmação — e aqui não se sabe. Mesma regra da tela inicial. */}
        {usina.pct_capacidade !== null ? (
          <View style={estilos.barra}>
            <Barra pct={usina.pct_capacidade} />
          </View>
        ) : null}

        <View style={estilos.rodape}>
          <Text style={tipo.legenda}>{local || '—'}</Text>
          <Text style={tipo.legenda} numberOfLines={1}>
            {usina.energia_hoje_kwh !== null ? (
              <>
                hoje <Num style={estilos.energia}>{energia(usina.energia_hoje_kwh)}</Num>
              </>
            ) : (
              (usina.aviso ?? 'sem dados do dia')
            )}
          </Text>
        </View>
      </Card>
    </Pressable>
  )
}

/** Skeleton, nunca spinner solto: três cards com o desenho do que vem. */
function CardsFantasma() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <View style={estilos.topo}>
            <Esqueleto largura="45%" altura={16} forte />
            <View style={estilos.espacador} />
            <Esqueleto largura={64} altura={18} />
          </View>
          <View style={estilos.linhaPotencia}>
            <Esqueleto largura="35%" altura={28} forte />
          </View>
          <View style={estilos.barra}>
            <Esqueleto altura={6} />
          </View>
          <View style={estilos.rodape}>
            <Esqueleto largura={110} altura={12} />
            <Esqueleto largura={80} altura={12} />
          </View>
        </Card>
      ))}
    </>
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
  rodape: { flexDirection: 'row', justifyContent: 'space-between', marginTop: espaco.sm, gap: 12 },
  energia: { fontSize: 12, color: cores.textoForte },
})
