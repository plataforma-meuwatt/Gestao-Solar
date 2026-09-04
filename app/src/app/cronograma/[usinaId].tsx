/**
 * O cronograma de manutenção do contrato, como o dono o lê.
 *
 * É a resposta para "a manutenção que eu contratei está sendo feita?" — não OS por OS,
 * mas o ano inteiro de uma vez: cada linha é uma atividade do contrato, cada coluna um
 * mês, e a marca diz o que aconteceu.
 *
 * **Doze meses a partir da âncora do CONTRATO, não de janeiro.** O de Porto Ferreira vai
 * de 2026-08 a 2027-07. Desenhar Jan→Dez encaixaria as marcas nas colunas erradas.
 *
 * **A marca vem do servidor, e o servidor a repassa do meuPlano.** Aquela cor é
 * conformidade calculada contra o histórico do ATIVO, não contra contagem de tarefas
 * (regra máxima do meuPlano). Nada é recalculado aqui: o dono precisa ver o mesmo número
 * nos dois produtos.
 *
 * **✓ e ~ são coisas diferentes.** `feito` é executado; `dispensado` é uma dispensa
 * registrada com motivo, que sai da conta daquele mês por decisão de alguém. Apagar essa
 * diferença — desenhar as duas como ✓ — era exatamente o risco que o meuPlano recusou
 * correr, e não vamos reintroduzi-lo na última tela da cadeia.
 *
 * A grade rola na horizontal porque doze colunas legíveis não cabem em 390 px, e
 * encolher a fonte até caber é como se perde a leitura de relance que a tela existe para
 * dar. A coluna do nome fica fixa à esquerda.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { useRef, useState } from 'react'
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native'

import { AbrirPdf } from '@/components/AbrirPdf'
import { CabecalhoCard, Card, Esqueleto, EstadoVazio, Num } from '@/components/base'
import { Tela } from '@/components/Tela'
import {
  tarefasDaCelula,
  urlDoPdfDoCronograma,
  useCronograma,
  type Celula,
  type LinhaCronograma,
  type Tarefa,
} from '@/features/manutencao'
import { inteiro } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

const LARGURA_NOME = 150
const LARGURA_MES = 34
/** Altura do corpo rolável. O cabeçalho fica FORA dele — é isso que o mantém parado
 *  quando a lista rola (o dono: "ao rolar pra baixo, os meses ficam congelados"). */
const ALTURA_CORPO = 340

/** "2026-08" → "ago". A grade não tem espaço para o mês inteiro. */
const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

function mesCurto(yyyyMm: string): string {
  const m = Number(yyyyMm.slice(5, 7))
  return MESES_CURTOS[m - 1] ?? yyyyMm.slice(5, 7)
}

/** O ano só aparece quando vira — é o que mostra que o contrato atravessa dezembro. */
function anoDe(yyyyMm: string): string {
  return yyyyMm.slice(2, 4)
}

export default function Cronograma() {
  const { usinaId } = useLocalSearchParams<{ usinaId: string }>()
  const { dados: c, carregando, erro, offlineDesde, recarregar } = useCronograma(usinaId)

  return (
    <Tela
      titulo="Cronograma"
      subtitulo={
        c ? (
          <Text style={tipo.secundario}>
            {c.usina}
            {c.previsto_ano > 0 ? (
              <>
                {' · '}
                <Num style={estilos.subNum}>{inteiro(c.feitos_ano)}</Num>
                {` de ${inteiro(c.previsto_ano)} cumpridas`}
              </>
            ) : null}
          </Text>
        ) : undefined
      }
      voltar
      offlineDesde={offlineDesde}
    >
      {carregando && !c ? (
        <Card>
          <Esqueleto largura="50%" altura={14} forte />
          <View style={estilos.espaco}>
            <Esqueleto altura={200} />
          </View>
        </Card>
      ) : erro || !c ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro ?? 'Cronograma indisponível.'}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : c.linhas.length === 0 ? (
        <EstadoVazio
          titulo="Sem cronograma"
          descricao={c.aviso ?? 'O contrato desta usina ainda não tem cronograma montado.'}
        />
      ) : (
        <>
          {c.aviso ? <Text style={estilos.aviso}>{c.aviso}</Text> : null}

          <Card>
            <CabecalhoCard
              rotulo="Plano do contrato"
              direita={
                c.versao !== null ? (
                  <Text style={estilos.versao}>
                    {c.status === 'CONSOLIDATED' ? 'consolidado' : 'rascunho'} · v{c.versao}
                  </Text>
                ) : undefined
              }
            />

            <Grade cronograma={c} />

            <Legenda />
          </Card>

          <Card>
            <CabecalhoCard rotulo="Cronograma em PDF" />
            <Text style={estilos.explicacao}>
              O plano anual completo, com a letra do estado em cada mês. O arquivo é
              baixado e aberto no leitor do seu aparelho.
            </Text>
            <View style={estilos.espaco}>
              <AbrirPdf
                url={urlDoPdfDoCronograma(c.usina_id)}
                arquivo={`cronograma-${c.usina_id}.pdf`}
                titulo={`Cronograma — ${c.usina}`}
                rotulo="Abrir o cronograma em PDF"
              />
            </View>
          </Card>
        </>
      )}
    </Tela>
  )
}

/**
 * A grade com CABEÇALHO CONGELADO e coluna de nomes fixa.
 *
 * O desenho: o cabeçalho dos meses fica FORA do rolar vertical (por isso não sai da tela ao
 * descer a lista) e DENTRO do rolar horizontal (por isso acompanha ao ir para dezembro). São
 * dois roláveis verticais — nomes e células — mantidos em sincronia; o que o usuário arrasta
 * é o da direita, e o da esquerda o segue.
 */
function Grade({ cronograma: c }: { cronograma: { meses: string[]; linhas: LinhaCronograma[]; usina_id: number } }) {
  const nomesRef = useRef<ScrollView>(null)
  const celulasRef = useRef<ScrollView>(null)
  const [celulaAberta, setCelulaAberta] = useState<
    { linha: LinhaCronograma; mes: string; tarefas: Tarefa[] | null; erro: string | null } | null
  >(null)

  /** Toque na célula: busca as tarefas daquele mês e abre a folha com elas.
   *
   *  A busca é feita AQUI, no toque, e não num efeito da folha: o efeito exigiria escrever
   *  estado depois da montagem (e o lint do projeto proíbe, com razão — é onde nascem os
   *  "setState num componente que já saiu da tela"). */
  const abrirCelula = (linha: LinhaCronograma, mes: string) => {
    if (linha.plan_item_id == null) {
      setCelulaAberta({ linha, mes, tarefas: [], erro: 'Esta linha não tem tarefas ligadas no plano.' })
      return
    }
    setCelulaAberta({ linha, mes, tarefas: null, erro: null })
    tarefasDaCelula(c.usina_id, linha.plan_item_id, mes)
      .then((ts) => setCelulaAberta((atual) =>
        atual && atual.mes === mes && atual.linha === linha ? { ...atual, tarefas: ts } : atual))
      .catch(() => setCelulaAberta((atual) =>
        atual && atual.mes === mes && atual.linha === linha
          ? { ...atual, tarefas: [], erro: 'Não deu para carregar as tarefas deste mês.' }
          : atual))
  }

  // Sincroniza o rolar vertical dos dois lados. `scrollTo` sem animação: com animação, a
  // coluna de nomes ficaria sempre um quadro atrás do dedo.
  const sincronizar = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    nomesRef.current?.scrollTo({ y: e.nativeEvent.contentOffset.y, animated: false })
  }

  return (
    <>
      <View style={estilos.grade}>
        <View style={estilos.colunaNome}>
          {/* canto: fica parado nos DOIS eixos */}
          <View style={estilos.cabecalhoNome}>
            <Text style={estilos.cabecalhoTexto}>Atividade</Text>
          </View>
          <ScrollView
            ref={nomesRef}
            style={{ height: ALTURA_CORPO }}
            showsVerticalScrollIndicator={false}
            // quem arrasta é a área das células; esta coluna apenas acompanha
            scrollEnabled={false}
          >
            {c.linhas.map((l, i) => (
              <View key={`n${i}`} style={estilos.celulaNome}>
                <Text style={estilos.nomeAtividade} numberOfLines={2}>
                  {l.nome}
                </Text>
                {l.periodicidade ? (
                  <Text style={estilos.periodicidade}>{l.periodicidade}</Text>
                ) : null}
              </View>
            ))}
          </ScrollView>
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View>
            {/* FORA do rolar vertical: é isto que congela os meses no topo */}
            <View style={estilos.cabecalhoMeses}>
              {c.meses.map((m, i) => (
                <View key={m} style={estilos.cabecalhoMes}>
                  <Text style={estilos.mesTexto}>{mesCurto(m)}</Text>
                  {i === 0 || m.slice(0, 4) !== c.meses[i - 1].slice(0, 4) ? (
                    <Text style={estilos.anoTexto}>{anoDe(m)}</Text>
                  ) : null}
                </View>
              ))}
              <View style={estilos.cabecalhoTotal}>
                <Text style={estilos.mesTexto}>ano</Text>
              </View>
            </View>

            <ScrollView
              ref={celulasRef}
              style={{ height: ALTURA_CORPO }}
              showsVerticalScrollIndicator={false}
              onScroll={sincronizar}
              scrollEventThrottle={16}
            >
              {c.linhas.map((l, i) => (
                <LinhaGrade
                  key={`l${i}`}
                  linha={l}
                  onAbrirCelula={(mes) => abrirCelula(l, mes)}
                />
              ))}
            </ScrollView>
          </View>
        </ScrollView>
      </View>

      {celulaAberta ? (
        <TarefasDoMes
          titulo={celulaAberta.linha.nome}
          mes={celulaAberta.mes}
          tarefas={celulaAberta.tarefas}
          erro={celulaAberta.erro}
          onFechar={() => setCelulaAberta(null)}
        />
      ) : null}
    </>
  )
}

/**
 * O que está atrás do X: as tarefas daquela atividade naquele mês.
 *
 * Pedido do dono (04/09/2026): *"quero clicar nos X com tarefa feita e abrir as informações
 * da tarefa"*. A célula dizia só a cor; agora ela abre a lista, e cada tarefa leva à ficha.
 */
function TarefasDoMes({
  titulo,
  mes,
  tarefas,
  erro,
  onFechar,
}: {
  titulo: string
  mes: string
  /** `null` = ainda buscando. `[]` = buscou e não há nada — são coisas diferentes. */
  tarefas: Tarefa[] | null
  erro: string | null
  onFechar: () => void
}) {
  return (
    <Modal transparent animationType="fade" visible onRequestClose={onFechar}>
      <Pressable style={estilos.fundoModal} onPress={onFechar} />
      <View style={estilos.folha}>
        <Text style={estilos.folhaTitulo}>{titulo}</Text>
        <Text style={estilos.folhaSub}>{mesCurto(mes)}/{anoDe(mes)}</Text>

        {erro ? (
          <Text style={tipo.fraco}>{erro}</Text>
        ) : tarefas === null ? (
          <ActivityIndicator color={cores.ambar} style={estilos.folhaEspera} />
        ) : tarefas.length === 0 ? (
          <Text style={tipo.fraco}>
            Nenhuma tarefa registrada neste mês para esta atividade.
          </Text>
        ) : (
          <ScrollView>
            {tarefas.map((t) => (
              <Pressable
                key={t.id ?? t.nome}
                style={({ pressed }) => [estilos.folhaItem, pressed && estilos.folhaItemTocado]}
                disabled={!t.id || !t.os_id}
                onPress={() => {
                  onFechar()
                  router.push(`/tarefa/${t.id}?os=${t.os_id}`)
                }}
              >
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={estilos.folhaItemNome} numberOfLines={2}>{t.nome}</Text>
                  {t.equipamento ? (
                    <Text style={estilos.folhaItemEquip} numberOfLines={1}>{t.equipamento}</Text>
                  ) : null}
                </View>
                <Text style={estilos.folhaItemSit}>{t.feita ? '✓' : t.situacao}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}

        <Pressable style={estilos.folhaFechar} onPress={onFechar}>
          <Text style={estilos.folhaFecharTexto}>Fechar</Text>
        </Pressable>
      </View>
    </Modal>
  )
}

function LinhaGrade({
  linha: l,
  onAbrirCelula,
}: {
  linha: LinhaCronograma
  onAbrirCelula: (mes: string) => void
}) {
  return (
    <View style={estilos.linha}>
      {l.meses.map((cel) => {
        // Só a célula que TEM algo abre: mês sem previsão não esconde tarefa nenhuma, e
        // um toque que abre uma folha vazia ensina o usuário a não tocar mais.
        const temConteudo = cel.previsto > 0 || cel.feito || cel.dispensado || cel.atrasado
        if (!temConteudo) {
          return (
            <View key={cel.mes} style={estilos.celula}>
              <Marca celula={cel} />
            </View>
          )
        }
        return (
          <Pressable
            key={cel.mes}
            style={({ pressed }) => [estilos.celula, pressed && estilos.celulaTocada]}
            onPress={() => onAbrirCelula(cel.mes)}
            accessibilityRole="button"
            accessibilityLabel={`Ver as tarefas de ${l.nome} em ${cel.mes}`}
          >
            <Marca celula={cel} />
          </Pressable>
        )
      })}
      <View style={estilos.celulaTotal}>
        <Num style={estilos.total}>
          {l.feitos}/{l.previsto_ano}
        </Num>
      </View>
    </View>
  )
}

/**
 * A marca de uma célula. Cinco estados, e a ordem dos testes importa: dispensado é
 * `verde_ressalva` e nunca deve cair no ramo de `feito`.
 */
function Marca({ celula: c }: { celula: Celula }) {
  if (c.feito) {
    return (
      <View style={[estilos.marca, { backgroundColor: tons.ok }]}>
        <Text style={estilos.marcaTexto}>✓</Text>
      </View>
    )
  }
  if (c.dispensado) {
    // Contorno, não preenchimento: cumprido por decisão não é cumprido por execução.
    return (
      <View style={[estilos.marca, estilos.marcaVazada, { borderColor: tons.ok }]}>
        <Text style={[estilos.marcaTextoVazado, { color: tons.ok }]}>~</Text>
      </View>
    )
  }
  if (c.atrasado) {
    return (
      <View style={[estilos.marca, { backgroundColor: tons.parado }]}>
        <Text style={estilos.marcaTexto}>!</Text>
      </View>
    )
  }
  if (c.previsto > 0) {
    // Previsto e ainda no prazo: um ponto, que não compete com ✓ nem com !.
    return <View style={estilos.ponto} />
  }
  // Mês em que o contrato não pede nada. Vazio de verdade, sem marca de "faltou".
  return <View style={estilos.vazio} />
}

function Legenda() {
  return (
    <View style={estilos.legenda}>
      <ItemLegenda cor={tons.ok} texto="Feito" />
      <ItemLegenda cor={tons.ok} texto="Dispensado" vazado />
      <ItemLegenda cor={tons.parado} texto="Atrasado" />
      <ItemLegenda cor={cores.textoFraco} texto="Previsto" ponto />
    </View>
  )
}

function ItemLegenda({
  cor,
  texto,
  vazado,
  ponto,
}: {
  cor: string
  texto: string
  vazado?: boolean
  ponto?: boolean
}) {
  return (
    <View style={estilos.itemLegenda}>
      {ponto ? (
        <View style={estilos.ponto} />
      ) : (
        <View
          style={[
            estilos.amostra,
            vazado
              ? { borderColor: cor, borderWidth: 1.5, backgroundColor: 'transparent' }
              : { backgroundColor: cor },
          ]}
        />
      )}
      <Text style={estilos.legendaTexto}>{texto}</Text>
    </View>
  )
}

const estilos = StyleSheet.create({
  celulaTocada: { opacity: 0.55 },

  fundoModal: { flex: 1, backgroundColor: '#00000099' },
  folha: {
    position: 'absolute', left: 0, right: 0, bottom: 0,
    backgroundColor: cores.superficieElevada,
    borderTopLeftRadius: 18, borderTopRightRadius: 18,
    padding: espaco.md, paddingBottom: espaco.lg, gap: 2,
    maxHeight: '70%',
  },
  folhaTitulo: { fontFamily: fontes.uiForte, fontSize: 15, color: cores.textoForte },
  folhaSub: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoFraco, marginBottom: espaco.xs },
  folhaEspera: { marginVertical: espaco.md },
  folhaItem: {
    flexDirection: 'row', alignItems: 'center', gap: espaco.xs,
    paddingVertical: 10, borderTopWidth: 1, borderTopColor: cores.borda,
  },
  folhaItemTocado: { opacity: 0.6 },
  folhaItemNome: { fontFamily: fontes.ui, fontSize: 13.5, color: cores.textoCorpo, lineHeight: 18 },
  folhaItemEquip: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco, marginTop: 1 },
  folhaItemSit: { fontFamily: fontes.uiForte, fontSize: 12, color: cores.textoRotulo },
  folhaFechar: { alignSelf: 'flex-end', paddingVertical: 10, paddingHorizontal: 4, marginTop: espaco.xs },
  folhaFecharTexto: { fontFamily: fontes.uiForte, fontSize: 13, color: cores.ambar },

  espaco: { marginTop: espaco.sm },
  subNum: { fontSize: 13, color: cores.textoRotulo },
  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },
  versao: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco },

  grade: { flexDirection: 'row', marginTop: espaco.xs },
  colunaNome: { width: LARGURA_NOME },

  cabecalhoNome: { height: 30, justifyContent: 'flex-end', paddingBottom: 5 },
  cabecalhoTexto: {
    fontFamily: fontes.ui,
    fontSize: 10,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: cores.textoRotulo,
  },
  cabecalhoMeses: { flexDirection: 'row', height: 30, alignItems: 'flex-end' },
  cabecalhoMes: { width: LARGURA_MES, alignItems: 'center', paddingBottom: 3 },
  cabecalhoTotal: { width: 46, alignItems: 'center', paddingBottom: 3 },
  mesTexto: { fontFamily: fontes.ui, fontSize: 10, color: cores.textoRotulo },
  anoTexto: { fontFamily: fontes.ui, fontSize: 8, color: cores.textoFraco },

  celulaNome: {
    height: 40,
    justifyContent: 'center',
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
    paddingRight: espaco.xs,
  },
  nomeAtividade: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoCorpo, lineHeight: 15 },
  periodicidade: { fontFamily: fontes.ui, fontSize: 9.5, color: cores.textoFraco },

  linha: {
    flexDirection: 'row',
    height: 40,
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  celula: { width: LARGURA_MES, alignItems: 'center', justifyContent: 'center' },
  celulaTotal: { width: 46, alignItems: 'center' },
  total: { fontSize: 11, color: cores.textoFraco },

  marca: { width: 20, height: 20, borderRadius: 5, alignItems: 'center', justifyContent: 'center' },
  marcaVazada: { backgroundColor: 'transparent', borderWidth: 1.5 },
  marcaTexto: { fontFamily: fontes.uiSemi, fontSize: 12, color: cores.fundo, lineHeight: 16 },
  marcaTextoVazado: { fontFamily: fontes.uiSemi, fontSize: 13, lineHeight: 16 },
  ponto: { width: 5, height: 5, borderRadius: 3, backgroundColor: cores.textoFraco },
  vazio: { width: 20, height: 20 },

  legenda: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: espaco.sm,
    marginTop: espaco.sm,
    paddingTop: espaco.sm,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  itemLegenda: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  amostra: { width: 11, height: 11, borderRadius: 3 },
  legendaTexto: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo },

  explicacao: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoCorpo,
    lineHeight: 17,
    marginTop: 4,
  },
})
