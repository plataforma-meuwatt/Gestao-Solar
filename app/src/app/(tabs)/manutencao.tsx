/**
 * Manutenção — a manutenção contratada, do que está acontecendo ao que já foi feito.
 *
 * Esta aba era só histórico: as OS com `closed_at`, agrupadas por mês. Respondia "o que
 * fizeram em julho" e deixava de fora a pergunta que o dono faz primeiro — **está sendo
 * feita?**. Uma preventiva executada na semana passada e ainda em conferência não
 * aparecia em lugar nenhum: não estava fechada, então não era histórico.
 *
 * Agora a tela abre pelo presente. `em_andamento` vem escolhida pelo servidor (a OS não
 * encerrada mais recente) e ganha o cartão de cima, com a barra de tarefas cumpridas. O
 * resto desce em lista, com o histórico junto — é a mesma pergunta em dois tempos, e
 * separá-los em duas abas obrigaria o dono a saber de antemão em qual procurar.
 *
 * Cada cartão abre a OS (tarefas + PDF). O cronograma é por usina, então mora num
 * cartão próprio: com uma usina só, um atalho direto; com várias, uma linha por usina.
 *
 * Tudo vem de `GET /api/v1/manutencao/ordens`. A situação de cada OS é a **frase** que o
 * servidor decidiu — nunca o `status` cru, que diria "Em execução" para uma OS com as
 * dezessete tarefas prontas e faria o dono achar que o técnico ainda está na usina.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  CabecalhoCard,
  Card,
  Chevron,
  Esqueleto,
  EstadoVazio,
  LinhaNavegacao,
  Num,
  StatusChip,
} from '@/components/base'
import { Tela } from '@/components/Tela'
import { useOrdens, type Ordem } from '@/features/manutencao'
import { dataPorExtenso, duracao, inteiro } from '@/lib/format'
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

function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

/** A data que vale para esta OS: a de conclusão quando existe, senão a de agendamento. */
function dataDaOrdem(o: Ordem): string | null {
  return o.concluida_em ?? o.agendada_para
}

export default function Manutencao() {
  const usuario = useAuth((s) => s.usuario)
  const [usina, setUsina] = useState<string | null>(null)
  const { dados, carregando, erro, offlineDesde, recarregar } = useOrdens()

  /*
   * O filtro sai das PRÓPRIAS ordens, e não da lista de usinas do usuário.
   *
   * Quem tem sete usinas mas OS em três só quer escolher entre essas três — as outras
   * quatro seriam botões que levam a uma tela vazia. A lista de opções acompanha o
   * dado, então ela encolhe e cresce sozinha.
   */
  const usinasComOs = [...new Set((dados?.ordens ?? []).map((o) => o.usina))].sort()
  // Filtro que aponta para usina que sumiu da lista é ignorado, em vez de esvaziar a
  // tela sem explicação.
  const filtro = usina && usinasComOs.includes(usina) ? usina : null
  const visiveis = (dados?.ordens ?? []).filter((o) => !filtro || o.usina === filtro)

  // A OS em curso já sai destacada; repeti-la na lista abaixo seria o mesmo cartão duas
  // vezes na mesma rolagem. Com filtro ativo ela só é destacada se for da usina filtrada.
  const emCurso =
    dados?.em_andamento && (!filtro || dados.em_andamento.usina === filtro)
      ? dados.em_andamento
      : null
  const demais = visiveis.filter((o) => o.id !== emCurso?.id)

  // Uma entrada de cronograma por usina, com o `usina_id` que a rota precisa. Sai das
  // ordens porque é a lista que já está na tela — e é a que tem vínculo com o meuPlano.
  const usinasDoCronograma = [
    ...new Map(
      (dados?.ordens ?? []).map((o) => [o.usina_id, { id: o.usina_id, nome: o.usina }]),
    ).values(),
  ].sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'))

  return (
    <Tela
      titulo="Manutenção"
      subtitulo={
        dados ? (
          <Text style={tipo.secundario}>
            {dados.total !== null ? (
              <>
                <Num style={estilos.subNum}>{inteiro(visiveis.length)}</Num>{' '}
                {visiveis.length === 1 ? 'ordem de serviço' : 'ordens de serviço'}
              </>
            ) : (
              'manutenção indisponível'
            )}
            {' · '}
            {/* Com filtro, o nome da usina; sem filtro, quantas usinas a aba cobre. */}
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
              <Esqueleto altura={60} />
            </View>
          </Card>
          <Card>
            <Esqueleto altura={80} />
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
          titulo="Nenhuma ordem de serviço"
          descricao={
            dados?.aviso
            ?? 'Quando uma ordem de serviço for aberta no meuPlano, ela aparece aqui.'
          }
        />
      ) : (
        <>
          {dados.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}

          {/* Só com mais de uma usina na lista: um filtro de uma opção é enfeite. */}
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

          {emCurso ? <CardEmCurso ordem={emCurso} /> : null}

          {/* O cronograma é por usina, e é onde a pergunta "o contrato está sendo
              cumprido?" se responde de uma vez, sem abrir OS por OS. */}
          {usinasDoCronograma.length > 0 ? (
            <Card>
              <CabecalhoCard rotulo="Cronograma do contrato" />
              {usinasDoCronograma.map((u) => (
                <LinhaNavegacao
                  key={u.id}
                  titulo={usinasDoCronograma.length === 1 ? 'Ver o plano do ano' : u.nome}
                  onPress={() => router.push(`/cronograma/${u.id}`)}
                />
              ))}
            </Card>
          ) : null}

          {demais.length > 0 ? (
            <Text style={estilos.secao}>{emCurso ? 'Outras ordens' : 'Ordens de serviço'}</Text>
          ) : null}
          {demais.map((o) => (
            <CardOrdem key={o.id} ordem={o} />
          ))}

          {visiveis.length === 0 ? (
            <Card>
              <Text style={tipo.fraco}>Nenhuma ordem de serviço nesta usina.</Text>
            </Card>
          ) : null}
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

/**
 * A OS em curso, em destaque.
 *
 * A barra de tarefas é o que faz "17 de 17" virar leitura de relance — e é ela que
 * explica a frase "Executada · aguardando verificação" sem precisar de parágrafo.
 */
function CardEmCurso({ ordem: o }: { ordem: Ordem }) {
  const feitas = o.tarefas_feitas ?? 0
  const total = o.tarefas ?? 0
  const data = dataDaOrdem(o)
  return (
    <Pressable onPress={() => router.push(`/os/${o.id}`)}>
      <Card>
        <View style={estilos.emCursoTopo}>
          <Text style={estilos.rotuloAgora}>Acontecendo agora</Text>
          <StatusChip tom={tomDaClasse(o.classificacao)} texto={rotuloDaClasse(o.classificacao)} />
        </View>

        <Text style={estilos.objetivoGrande}>{o.objetivo}</Text>
        <Text style={estilos.usina}>
          {o.usina}
          {data ? ` · ${dataPorExtenso(data)}` : ''}
        </Text>

        <View style={estilos.situacaoLinha}>
          <StatusChip tom={o.tom} texto={o.situacao} grande />
        </View>

        {/* Zero tarefa não vira barra: "0 de 0" a 0% pareceria serviço não começado. */}
        {total > 0 ? (
          <View style={estilos.espaco}>
            <View style={estilos.progressoTopo}>
              <Text style={tipo.legenda}>Tarefas cumpridas</Text>
              <Text style={estilos.progressoNum}>
                <Num style={estilos.progressoForte}>{feitas}</Num>
                {` de ${total}`}
              </Text>
            </View>
            <Barra pct={(feitas / total) * 100} tom={feitas >= total ? 'ok' : 'alerta'} />
          </View>
        ) : null}

        <View style={estilos.abrir}>
          <Text style={estilos.abrirTexto}>Ver o que foi feito</Text>
          <Chevron />
        </View>
      </Card>
    </Pressable>
  )
}

function CardOrdem({ ordem: o }: { ordem: Ordem }) {
  const data = dataDaOrdem(o)
  return (
    <Pressable onPress={() => router.push(`/os/${o.id}`)}>
      <Card>
        <View style={estilos.topo}>
          <Text style={estilos.objetivo} numberOfLines={2}>
            {o.objetivo}
          </Text>
          <Chevron />
        </View>

        <Text style={estilos.usina}>
          {o.usina}
          {data ? ` · ${dataPorExtenso(data)}` : ''}
        </Text>

        <View style={estilos.selos}>
          <StatusChip tom={o.tom} texto={o.situacao} />
          <StatusChip tom={tomDaClasse(o.classificacao)} texto={rotuloDaClasse(o.classificacao)} />
        </View>

        <View style={estilos.linhas}>
          <Linha rotulo="Técnico" valor={o.tecnico ?? '—'} />
          <Linha rotulo="Execução" valor={duracao(o.execucao_min)} />
          {/* Tarefas só aparece quando a OS tem tarefas: "0/0" não é informação. */}
          {o.tarefas ? (
            <Linha rotulo="Tarefas" valor={`${o.tarefas_feitas ?? 0}/${o.tarefas}`} />
          ) : null}
        </View>
      </Card>
    </Pressable>
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
  espaco: { marginTop: espaco.sm },
  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },

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

  secao: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoRotulo,
    marginTop: espaco.sm,
    marginBottom: 2,
    paddingHorizontal: espaco.xs,
  },

  emCursoTopo: { flexDirection: 'row', alignItems: 'center', gap: espaco.xs },
  rotuloAgora: {
    flex: 1,
    fontFamily: fontes.ui,
    fontSize: 10,
    letterSpacing: 0.7,
    textTransform: 'uppercase',
    color: cores.textoAmbar,
  },
  objetivoGrande: {
    fontFamily: fontes.uiSemi,
    fontSize: 16,
    color: cores.textoForte,
    lineHeight: 22,
    marginTop: 6,
  },
  situacaoLinha: { marginTop: espaco.sm, alignSelf: 'flex-start' },

  progressoTopo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 5,
  },
  progressoNum: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo },
  progressoForte: { fontSize: 14, color: cores.textoForte },

  abrir: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 5,
    marginTop: espaco.sm,
  },
  abrirTexto: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoAmbar },

  topo: { flexDirection: 'row', alignItems: 'flex-start', gap: espaco.xs },
  objetivo: { fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte, flex: 1 },
  usina: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 2 },
  selos: { flexDirection: 'row', flexWrap: 'wrap', gap: espaco.xs, marginTop: espaco.sm },

  linhas: { marginTop: espaco.sm, gap: espaco.xs },
  linha: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  linhaValor: { fontSize: 12, color: cores.textoForte, flexShrink: 1 },
})
