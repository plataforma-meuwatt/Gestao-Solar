/**
 * Manutenção — o histórico de ordens de serviço atendidas.
 *
 * Substituiu a aba Financeiro. Tudo vem de `GET /api/v1/manutencao`, que consulta o
 * meuPlano usina por usina e devolve só o que tem `closed_at` — serviço concluído é fato
 * datado, não status textual.
 *
 * A lista é agrupada por mês porque é assim que se lê histórico de manutenção: o dono
 * quer saber "o que fizeram em julho", não percorrer sessenta cartões seguidos.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'

import { Card, Esqueleto, EstadoVazio, Num, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import { useManutencao, type OrdemAtendida } from '@/features/manutencao'
import { competencia, dataHora, inteiro } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo, type Tom } from '@/theme/tokens'

/**
 * A classificação vem do meuPlano em caixa alta com underscore. O tom não é decoração:
 * corretiva é conserto (algo quebrou), preventiva é rotina cumprida. Ler a diferença de
 * relance é o valor desta tela.
 */
function tomDaClasse(c: string | null): Tom {
  const v = (c ?? '').toUpperCase()
  if (v.includes('CORRETIVA')) return 'alerta'
  if (v.includes('PREVENTIVA')) return 'ok'
  return 'semDados'
}

function rotuloDaClasse(c: string | null): string {
  if (!c) return 'sem classificação'
  // "SERVICOS_ADICIONAIS" → "Servicos adicionais". Sem isto o cartão vira um grito.
  const limpo = c.replace(/_/g, ' ').toLowerCase()
  return limpo.charAt(0).toUpperCase() + limpo.slice(1)
}

/** Minutos → "1 h 20" ou "45 min". Nulo vira travessão: não medimos ≠ foi instantâneo. */
function duracaoDeMinutos(min: number | null): string {
  if (min === null || min <= 0) return '—'
  const h = Math.floor(min / 60)
  const m = min % 60
  return h > 0 ? `${h} h${m ? ` ${m}` : ''}` : `${m} min`
}

function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

export default function Manutencao() {
  const usuario = useAuth((s) => s.usuario)
  const [usina, setUsina] = useState<string | null>(null)
  const { dados, carregando, erro, offlineDesde, recarregar } = useManutencao()

  /*
   * O filtro sai das PRÓPRIAS ordens, e não da lista de usinas do usuário.
   *
   * Quem tem sete usinas mas serviço concluído em três só quer escolher entre essas
   * três — as outras quatro seriam botões que levam a uma tela vazia. A lista de
   * opções acompanha o dado, então ela encolhe e cresce sozinha.
   */
  const usinasComOs = [...new Set((dados?.ordens ?? []).map((o) => o.usina))].sort()
  // Filtro que aponta para usina que sumiu do histórico é ignorado, em vez de
  // esvaziar a tela sem explicação.
  const filtro = usina && usinasComOs.includes(usina) ? usina : null
  const visiveis = (dados?.ordens ?? []).filter((o) => !filtro || o.usina === filtro)

  // Agrupa por mês de fechamento, preservando a ordem que o servidor já garantiu
  // (mais recente primeiro). Um `Map` mantém a ordem de inserção — reordenar aqui
  // desfaria o trabalho do BFF e abriria espaço para as duas telas discordarem.
  const meses = new Map<string, OrdemAtendida[]>()
  for (const o of visiveis) {
    const chave = o.fechada_em ? o.fechada_em.slice(0, 7) : 'sem-data'
    const atual = meses.get(chave)
    if (atual) atual.push(o)
    else meses.set(chave, [o])
  }

  return (
    <Tela
      titulo="Manutenção"
      subtitulo={
        dados ? (
          <Text style={tipo.secundario}>
            {dados.total !== null ? (
              <>
                <Num style={estilos.subNum}>{inteiro(visiveis.length)}</Num>{' '}
                {visiveis.length === 1 ? 'serviço concluído' : 'serviços concluídos'}
              </>
            ) : (
              'histórico indisponível'
            )}
            {' · '}
            {/* Com filtro, o nome da usina; sem filtro, quantas usinas o histórico cobre. */}
            {filtro ?? (
              <>
                <Num style={estilos.subNum}>{inteiro(dados.usinas_com_manutencao)}</Num>{' '}
                {dados.usinas_com_manutencao === 1 ? 'usina' : 'usinas'}
              </>
            )}
          </Text>
        ) : undefined
      }
      avatar={{ iniciais: iniciaisDe(usuario?.nome), onPress: () => router.push('/perfil') }}
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {carregando && !dados ? (
        <>
          <Card>
            <Esqueleto largura="60%" altura={16} forte />
            <View style={estilos.espaco}>
              <Esqueleto altura={40} />
            </View>
          </Card>
          <Card>
            <Esqueleto altura={60} />
          </Card>
        </>
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : !dados || dados.ordens.length === 0 ? (
        <EstadoVazio
          titulo="Nenhum serviço concluído"
          descricao={
            dados?.aviso
            ?? 'Quando uma ordem de serviço for fechada no meuPlano, ela aparece aqui.'
          }
        />
      ) : (
        <>
          {dados.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}

          {/* Só com mais de uma usina no histórico: um filtro de uma opção é enfeite. */}
          {usinasComOs.length > 1 ? (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={estilos.filtros}
            >
              <Filtro rotulo="Todas" ativo={filtro === null} onPress={() => setUsina(null)} />
              {usinasComOs.map((u) => (
                <Filtro
                  key={u}
                  rotulo={u}
                  ativo={filtro === u}
                  onPress={() => setUsina(filtro === u ? null : u)}
                />
              ))}
            </ScrollView>
          ) : null}

          {visiveis.length === 0 ? (
            <Card>
              <Text style={tipo.fraco}>Nenhum serviço concluído nesta usina.</Text>
            </Card>
          ) : null}

          {[...meses.entries()].map(([chave, ordens]) => (
            <View key={chave}>
              <Text style={estilos.mes}>
                {chave === 'sem-data' ? 'Sem data de fechamento' : competencia(chave)}
              </Text>
              {ordens.map((o) => (
                <CardOrdem key={`${o.id}-${o.fechada_em}`} ordem={o} />
              ))}
            </View>
          ))}
        </>
      )}
    </Tela>
  )
}

function Filtro({
  rotulo,
  ativo,
  onPress,
}: {
  rotulo: string
  ativo: boolean
  onPress: () => void
}) {
  return (
    <Pressable onPress={onPress} style={[estilos.filtro, ativo && estilos.filtroAtivo]}>
      <Text style={[estilos.filtroTexto, ativo && estilos.filtroTextoAtivo]} numberOfLines={1}>
        {rotulo}
      </Text>
    </Pressable>
  )
}

function CardOrdem({ ordem: o }: { ordem: OrdemAtendida }) {
  return (
    <Card>
      <View style={estilos.topo}>
        <Text style={estilos.objetivo} numberOfLines={2}>
          {o.objetivo}
        </Text>
        <StatusChip tom={tomDaClasse(o.classificacao)} texto={rotuloDaClasse(o.classificacao)} />
      </View>

      <Text style={estilos.usina}>{o.usina}</Text>

      <View style={estilos.linhas}>
        <Linha rotulo="Concluída" valor={o.fechada_em ? dataHora(o.fechada_em) : '—'} />
        <Linha rotulo="Técnico" valor={o.tecnico ?? '—'} />
        <Linha rotulo="Execução" valor={duracaoDeMinutos(o.execucao_min)} />
        {/* Tarefas só aparece quando a OS tem tarefas: "0/0" não é informação. */}
        {o.tarefas ? (
          <Linha rotulo="Tarefas" valor={`${o.tarefas_feitas ?? 0}/${o.tarefas}`} />
        ) : null}
      </View>

      {o.resumo ? (
        <Text style={estilos.resumo} numberOfLines={4}>
          {o.resumo}
        </Text>
      ) : null}
    </Card>
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
  subNum: { fontSize: 13, color: cores.textoRotulo },

  filtros: { gap: espaco.xs, paddingHorizontal: espaco.xs, paddingVertical: 2 },
  filtro: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: cores.borda,
    backgroundColor: cores.superficie,
    maxWidth: 200,
  },
  filtroAtivo: { backgroundColor: cores.ambar, borderColor: cores.ambar },
  filtroTexto: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoCorpo },
  filtroTextoAtivo: { color: cores.fundo },
  espaco: { marginTop: espaco.sm },
  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },

  mes: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoRotulo,
    marginTop: espaco.sm,
    marginBottom: 2,
    paddingHorizontal: espaco.xs,
  },

  topo: { flexDirection: 'row', alignItems: 'flex-start', gap: espaco.xs },
  objetivo: { fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte, flex: 1 },
  usina: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 2 },

  linhas: { marginTop: espaco.sm, gap: espaco.xs },
  linha: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  linhaValor: { fontSize: 12, color: cores.textoForte, flexShrink: 1 },

  resumo: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoCorpo,
    lineHeight: 17,
    marginTop: espaco.sm,
  },
})
