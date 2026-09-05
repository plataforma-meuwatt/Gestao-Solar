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
import { Pressable, StyleSheet, Text, View } from 'react-native'

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
import { EscolhaEmLista, type Opcao } from '@/components/EscolhaEmLista'
import { Tela } from '@/components/Tela'
import { tomValido } from '@/features/manutencao-regras'
import { useOrdens, type Ordem } from '@/features/manutencao'
import { usePendencias } from '@/features/pendencias'
import { dataPorExtenso, duracao, inteiro } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo } from '@/theme/tokens'

/**
 * O selo da classificação — rótulo e cor JÁ decididos pelo servidor.
 *
 * Havia aqui, e na tela da OS, um par de funções que traduzia o código da classificação e
 * escolhia a cor dele — duas cópias, e portanto dois resultados: `SERVICOS_ADICIONAIS` saía
 * "Servicos adicionais" numa tela e "Serviços adicionais" na outra. O BFF manda
 * `classificacao` pronta e `classificacao_tom` ao lado exatamente para isso não existir.
 * Sem classificação, selo nenhum — um chip escrito "sem classificação" ocupa o lugar de um
 * dado e não é um.
 */
function SeloDaClasse({ ordem: o }: { ordem: Ordem }) {
  if (!o.classificacao) return null
  return <StatusChip tom={tomValido(o.classificacao_tom)} texto={o.classificacao} />
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
  // Só o CONTADOR: a lista mora na tela própria. O cartão precisa dizer quantas são, senão
  // é um botão que promete algo sem dizer se há o que ver atrás dele.
  const { dados: pend } = usePendencias()

  /*
   * O filtro sai das PRÓPRIAS ordens, e não da lista de usinas do usuário.
   *
   * Quem tem sete usinas mas OS em três só quer escolher entre essas três — as outras
   * quatro seriam botões que levam a uma tela vazia. A lista de opções acompanha o
   * dado, então ela encolhe e cresce sozinha.
   */
  const usinasComOs = [...new Set((dados?.ordens ?? []).map((o) => o.usina))].sort()
  const opcoesDeUsina: Opcao[] = [
    { valor: null, rotulo: 'Todas as usinas', contagem: (dados?.ordens ?? []).length },
    ...usinasComOs.map((u) => ({
      valor: u,
      rotulo: u,
      contagem: (dados?.ordens ?? []).filter((o) => o.usina === u).length,
    })),
  ]
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

          {/* Lista suspensa, nunca uma fileira de chips (regra do produto). A fileira que
              havia aqui rolava para fora da tela a partir da quarta usina, escondendo as
              opções — e com a contagem ao lado o dono sabe para onde a escolha leva antes
              de tocar. Só com mais de uma usina: um filtro de uma opção é enfeite. */}
          {usinasComOs.length > 1 ? (
            <View style={estilos.filtros}>
              <EscolhaEmLista
                rotulo="Usina"
                titulo="Ver as ordens de qual usina"
                valor={filtro}
                aoEscolher={setUsina}
                opcoes={opcoesDeUsina}
              />
            </View>
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

          {/* A outra metade da pergunta: o cronograma diz o que foi cumprido, isto diz o
              que ficou pendente. `abertas` nulo = alguma usina não respondeu, e um total
              parcial que parece completo é pior do que nenhum — a linha vai sem valor. */}
          <Card>
            <CabecalhoCard rotulo="Pendências" />
            <LinhaNavegacao
              titulo="O que ficou pendente"
              valor={pend?.abertas != null ? `${pend.abertas} em aberto` : undefined}
              tomValor={pend?.prazo_vencido ? 'parado' : undefined}
              onPress={() => router.push('/pendencias')}
            />
            {pend?.prazo_vencido ? (
              <Text style={estilos.pendAviso}>
                <Num style={estilos.pendNum}>{pend.prazo_vencido}</Num>
                {' com prazo vencido'}
              </Text>
            ) : null}
          </Card>

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
          <SeloDaClasse ordem={o} />
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
          <SeloDaClasse ordem={o} />
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

  filtros: { paddingHorizontal: espaco.xs, paddingBottom: espaco.xs },
  pendAviso: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    color: cores.textoFraco,
    marginTop: 6,
  },
  pendNum: { fontSize: 12, color: cores.textoForte },

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
