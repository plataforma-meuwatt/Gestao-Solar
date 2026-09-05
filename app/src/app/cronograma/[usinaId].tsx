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
 * **Blocos, não noventa e quatro linhas.** O contrato de Porto Ferreira tem 94 atividades.
 * Planas numa grade de doze colunas, elas viram a análise equipamento a equipamento que o
 * cliente não quer ler — e foi o que a captura de tela mostrou: quinze faixas cinzas
 * chapadas, meses vazios, nada legível. As linhas chegam com `grupo` do servidor e a tela as
 * recolhe: quinze blocos fechados, cada um dizendo quanto cumpriu e quanto está atrasado, e o
 * detalhe atrás de um toque.
 *
 * **O laranja existe.** O meuPlano tem CINCO estados de célula, e o BFF só transforma três em
 * booleano — `laranja` (venceu o mês, ainda está na janela de tolerância) não tem booleano
 * nenhum e caía no mesmo ponto cinza do "no prazo". A atividade que ainda dá tempo de salvar
 * ficava indistinguível da que nem venceu. A marca vem de `marcaDaCelula`, que lê o campo cru.
 *
 * **Dois números, e cada um com o seu rótulo.** "Cumpridas no ano" conta os doze meses,
 * inclusive os que não chegaram; o recorte de vigência conta só o que já venceu dentro do
 * contrato. Foi confundir os dois que produziu "13 de 270" numa tela e "41,9 %" na outra. A
 * conta é feita no meuPlano e só repassada — aqui não se divide nada, e os dois aparecem
 * juntos, cada um com o denominador colado.
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
  agruparCronograma,
  marcaDaCelula,
  recorteDoCronograma,
  TOM_DA_MARCA,
  type Bloco,
} from '@/features/manutencao-regras'
import {
  tarefasDaCelula,
  urlDoPdfDoCronograma,
  useCronograma,
  type Celula,
  type CronogramaOut,
  type LinhaCronograma,
  type Tarefa,
} from '@/features/manutencao'
import { inteiro, numero } from '@/lib/format'
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
                {` de ${inteiro(c.previsto_ano)} no ano`}
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

          <RecorteDeVigencia cronograma={c} />

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

          {/* O JSON responde 200 com matriz vazia quando não há consolidação, mas o PDF
              responde 404 — um arquivo não tem como avisar por dentro. O servidor diz se
              há o que gerar, e sem isso o botão não existe em vez de dar erro. */}
          {c.pdf_disponivel ? (
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
          ) : null}
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
  // Fechados por padrão. Abrir todos devolveria as 94 linhas que esta tela existe para
  // recolher; o cabeçalho de cada bloco já diz o que há dentro.
  const [abertos, setAbertos] = useState<Record<string, true>>({})
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

  const blocos = agruparCronograma(c.linhas)

  /*
   * As duas colunas desenham a MESMA sequência de faixas, e por isso ela é montada uma vez
   * só. Sem isto, um `if` a mais de um lado desalinharia nome e células — e a atividade
   * apareceria com a marca da vizinha, que é o pior defeito possível numa tela de
   * conformidade.
   */
  type Faixa =
    | { tipo: 'bloco'; bloco: Bloco<LinhaCronograma> }
    | { tipo: 'linha'; linha: LinhaCronograma; chave: string }

  const faixas: Faixa[] = []
  for (const b of blocos) {
    faixas.push({ tipo: 'bloco', bloco: b })
    if (abertos[b.grupo]) {
      b.linhas.forEach((l, i) => faixas.push({ tipo: 'linha', linha: l, chave: `${b.grupo}#${i}` }))
    }
  }

  const alternar = (grupo: string) =>
    setAbertos((atual) => {
      const proximo = { ...atual }
      if (proximo[grupo]) delete proximo[grupo]
      else proximo[grupo] = true
      return proximo
    })

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
            {faixas.map((f) =>
              f.tipo === 'bloco' ? (
                <Pressable
                  key={`b:${f.bloco.grupo}`}
                  style={({ pressed }) => [estilos.celulaBloco, pressed && estilos.celulaTocada]}
                  onPress={() => alternar(f.bloco.grupo)}
                  accessibilityRole="button"
                  accessibilityState={{ expanded: Boolean(abertos[f.bloco.grupo]) }}
                  accessibilityLabel={`${abertos[f.bloco.grupo] ? 'Recolher' : 'Abrir'} ${f.bloco.grupo}, ${f.bloco.linhas.length} atividades`}
                >
                  <Text style={estilos.seta}>{abertos[f.bloco.grupo] ? '▾' : '▸'}</Text>
                  <View style={estilos.blocoMiolo}>
                    <Text style={estilos.nomeBloco} numberOfLines={2}>
                      {f.bloco.grupo}
                    </Text>
                    <Text style={estilos.blocoSub}>
                      {f.bloco.linhas.length}
                      {f.bloco.linhas.length === 1 ? ' atividade' : ' atividades'}
                    </Text>
                  </View>
                </Pressable>
              ) : (
                <View key={`n:${f.chave}`} style={estilos.celulaNome}>
                  <Text style={estilos.nomeAtividade} numberOfLines={2}>
                    {f.linha.nome}
                  </Text>
                  {f.linha.periodicidade ? (
                    <Text style={estilos.periodicidade}>{f.linha.periodicidade}</Text>
                  ) : null}
                </View>
              ),
            )}
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
              {faixas.map((f) =>
                f.tipo === 'bloco' ? (
                  <ResumoDoBloco key={`rb:${f.bloco.grupo}`} bloco={f.bloco} meses={c.meses} />
                ) : (
                  <LinhaGrade
                    key={`l:${f.chave}`}
                    linha={f.linha}
                    onAbrirCelula={(mes) => abrirCelula(f.linha, mes)}
                  />
                ),
              )}
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
 * A marca de uma célula. Quem decide qual é `marcaDaCelula` — a ordem dos testes é regra e
 * está testada lá, não aqui. Isto é só o desenho de cada uma das seis.
 */
function Marca({ celula: c }: { celula: Celula }) {
  const marca = marcaDaCelula(c)
  if (marca === 'feito') {
    return (
      <View style={[estilos.marca, { backgroundColor: tons[TOM_DA_MARCA.feito] }]}>
        <Text style={estilos.marcaTexto}>✓</Text>
      </View>
    )
  }
  if (marca === 'dispensado') {
    // Contorno, não preenchimento: cumprido por decisão não é cumprido por execução.
    return (
      <View style={[estilos.marca, estilos.marcaVazada, { borderColor: tons[TOM_DA_MARCA.dispensado] }]}>
        <Text style={[estilos.marcaTextoVazado, { color: tons[TOM_DA_MARCA.dispensado] }]}>~</Text>
      </View>
    )
  }
  if (marca === 'atrasado') {
    return (
      <View style={[estilos.marca, { backgroundColor: tons[TOM_DA_MARCA.atrasado] }]}>
        <Text style={estilos.marcaTexto}>!</Text>
      </View>
    )
  }
  if (marca === 'alerta') {
    // Venceu o mês e ainda está na janela de tolerância. Antes caía no ponto cinza do "no
    // prazo" — e era exatamente esta a atividade sobre a qual valia a pena ligar hoje.
    return (
      <View style={[estilos.marca, { backgroundColor: tons[TOM_DA_MARCA.alerta] }]}>
        <Text style={estilos.marcaTexto}>•</Text>
      </View>
    )
  }
  if (marca === 'previsto') {
    // Previsto e ainda no prazo: um ponto, que não compete com ✓ nem com !.
    return <View style={estilos.ponto} />
  }
  // Mês em que o contrato não pede nada. Vazio de verdade, sem marca de "faltou".
  return <View style={estilos.vazio} />
}

/**
 * A faixa do bloco fechado, do lado das células.
 *
 * Não é um resumo inventado: cada mês mostra a marca MAIS GRAVE das linhas do bloco naquele
 * mês, na ordem atrasado → alerta → previsto → feito → dispensado. Um bloco recolhido nunca
 * pode esconder um atraso — recolher é para tirar detalhe da frente, não notícia ruim.
 */
function ResumoDoBloco({ bloco, meses }: { bloco: Bloco<LinhaCronograma>; meses: string[] }) {
  const GRAVIDADE = ['atrasado', 'alerta', 'previsto', 'feito', 'dispensado', 'vazio'] as const
  return (
    <View style={estilos.linhaBloco}>
      {meses.map((m, i) => {
        let pior: (typeof GRAVIDADE)[number] = 'vazio'
        for (const l of bloco.linhas) {
          const cel = l.meses[i]
          if (!cel) continue
          const marca = marcaDaCelula(cel)
          if (GRAVIDADE.indexOf(marca) < GRAVIDADE.indexOf(pior)) pior = marca
        }
        return (
          <View key={m} style={estilos.celula}>
            {pior === 'vazio' ? (
              <View style={estilos.vazio} />
            ) : (
              <View style={[estilos.pontoBloco, { backgroundColor: tons[TOM_DA_MARCA[pior]] }]} />
            )}
          </View>
        )
      })}
      <View style={estilos.celulaTotal}>
        <Num style={estilos.totalBloco}>
          {bloco.feitos}/{bloco.previsto_ano}
        </Num>
      </View>
    </View>
  )
}

function Legenda() {
  return (
    <View style={estilos.legenda}>
      <ItemLegenda cor={tons[TOM_DA_MARCA.feito]} texto="Feito" />
      <ItemLegenda cor={tons[TOM_DA_MARCA.dispensado]} texto="Dispensado" vazado />
      <ItemLegenda cor={tons[TOM_DA_MARCA.alerta]} texto="Venceu o mês" />
      <ItemLegenda cor={tons[TOM_DA_MARCA.atrasado]} texto="Atrasado" />
      <ItemLegenda cor={cores.textoFraco} texto="Previsto" ponto />
    </View>
  )
}

/**
 * O recorte de vigência — o número que responde "está sendo feito?".
 *
 * Ele vem PRONTO do meuPlano e é só repassado. O denominador viaja colado ao percentual
 * ("13 de 31") porque foi a sua ausência que permitiu ler 41,9 % como se fosse do ano todo,
 * ao lado de outra tela dizendo "13 de 270" para a mesma usina — sem uma única atividade
 * atrasada. Sem recorte publicado, travessão: "0 %" seria um número que ninguém mediu.
 */
function RecorteDeVigencia({ cronograma: c }: { cronograma: CronogramaOut }) {
  const r = recorteDoCronograma(c)
  if (!r) return null
  return (
    <Card>
      <CabecalhoCard
        rotulo="Cumprimento do contrato"
        direita={
          r.ate ? (
            <Text style={estilos.versao}>
              até {mesCurto(r.ate)}/{anoDe(r.ate)}
            </Text>
          ) : undefined
        }
      />
      <View style={estilos.recorteLinha}>
        <Num style={estilos.recortePct}>{r.pct === null ? '—' : `${numero(r.pct, 1)}%`}</Num>
        {r.fracao ? <Text style={estilos.recorteFracao}>{r.fracao}</Text> : null}
      </View>
      <Text style={estilos.recorteNota}>
        Conta só os meses que já venceram dentro da vigência do contrato.
        {r.noContrato !== null
          ? ` O contrato prevê ${inteiro(r.noContrato)} no ano inteiro.`
          : ''}
      </Text>
    </Card>
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

  // O bloco fechado. Faixa da mesma altura da linha, para nome e células não desalinharem.
  celulaBloco: {
    height: 40,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderTopWidth: 1,
    borderTopColor: cores.borda,
    paddingRight: espaco.xs,
  },
  seta: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo, width: 12 },
  blocoMiolo: { flex: 1, minWidth: 0 },
  nomeBloco: { fontFamily: fontes.uiSemi, fontSize: 12, color: cores.textoForte, lineHeight: 15 },
  blocoSub: { fontFamily: fontes.ui, fontSize: 9.5, color: cores.textoFraco },
  linhaBloco: {
    flexDirection: 'row',
    height: 40,
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: cores.borda,
  },
  pontoBloco: { width: 8, height: 8, borderRadius: 4 },
  totalBloco: { fontSize: 11, color: cores.textoRotulo },

  recorteLinha: { flexDirection: 'row', alignItems: 'baseline', gap: espaco.sm, marginTop: 2 },
  recortePct: { ...tipo.kpiMedio },
  recorteFracao: { fontFamily: fontes.mono, fontSize: 13, color: cores.textoRotulo },
  recorteNota: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    color: cores.textoFraco,
    lineHeight: 16,
    marginTop: 6,
  },

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
