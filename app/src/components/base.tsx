/**
 * Os componentes da prancha de sistema da rodada 1.
 *
 * Ficam juntos num arquivo só de propósito: são peças pequenas que se citam entre si
 * (Card usa Rotulo, Kpi usa Num, Barra usa os tons), e espalhá-las em dez arquivos de
 * vinte linhas dificultaria manter a coerência que a prancha estabelece.
 *
 * Nenhum valor literal aqui — tudo vem de `theme/tokens.ts`.
 */

import { useState, type ReactNode } from 'react'
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native'
import Svg, { Circle, Defs, Line, Path, RadialGradient, Rect, Stop } from 'react-native-svg'

import {
  ambarAlpha,
  chipDoTom,
  cores,
  espaco,
  fontes,
  raio,
  tabular,
  tipo,
  tomAlpha,
  tons,
  TOQUE_MIN,
  type Tom,
} from '@/theme/tokens'

/* ------------------------------------------------------------------ fundo */

/**
 * Halo radial azul no topo, presente em toda tela. Sai da borda superior e some antes
 * do meio — é ele que impede o fundo quase preto de parecer chapado.
 */
export function Halo() {
  return (
    <Svg
      pointerEvents="none"
      style={estilos.halo}
      width={560}
      height={380}
      viewBox="0 0 560 380"
    >
      <Defs>
        <RadialGradient id="halo" cx="50%" cy="50%" r="50%">
          <Stop offset="0" stopColor={cores.halo} />
          <Stop offset="1" stopColor={cores.fundo} stopOpacity={0} />
        </RadialGradient>
      </Defs>
      <Rect width={560} height={380} fill="url(#halo)" />
    </Svg>
  )
}

/* ------------------------------------------------------------------ texto */

/** Número: sempre mono, sempre tabular. Existe para não repetir esses dois estilos. */
export function Num({
  children,
  style,
}: {
  children: ReactNode
  style?: StyleProp<TextStyle>
}) {
  return <Text style={[estilos.num, tabular, style]}>{children}</Text>
}

/** Rótulo de card: caixa alta, espaçado, sempre acima do número. */
export function Rotulo({ children }: { children: ReactNode }) {
  return <Text style={tipo.rotuloCard}>{children}</Text>
}

/* ------------------------------------------------------------------- card */

export function Card({
  children,
  style,
  semPadding,
  elevado,
}: {
  children: ReactNode
  style?: StyleProp<ViewStyle>
  /** Para cards cujo conteúdo é uma lista com divisórias de borda a borda. */
  semPadding?: boolean
  elevado?: boolean
}) {
  return (
    <View
      style={[
        estilos.card,
        semPadding && estilos.cardSemPadding,
        elevado && { backgroundColor: cores.superficieElevada },
        style,
      ]}
    >
      {children}
    </View>
  )
}

/** Cabeçalho de card: rótulo à esquerda, anotação discreta à direita. */
export function CabecalhoCard({ rotulo, direita }: { rotulo: string; direita?: ReactNode }) {
  return (
    <View style={estilos.cabecalhoCard}>
      <Rotulo>{rotulo}</Rotulo>
      {direita}
    </View>
  )
}

/* -------------------------------------------------------------------- kpi */

/**
 * Número grande, contexto pequeno. `tom` tinge o valor — é assim que "0,0 kW" de um
 * inversor parado sai em vermelho sem precisar de outro componente.
 */
export function Kpi({
  valor,
  unidade,
  direita,
  tom,
  tamanho = 'heroi',
}: {
  valor: string
  unidade?: string
  direita?: ReactNode
  tom?: Tom
  tamanho?: 'heroi' | 'grande' | 'medio' | 'pequeno'
}) {
  const escala = {
    heroi: tipo.kpiHeroi,
    grande: tipo.kpiGrande,
    medio: tipo.kpi,
    pequeno: tipo.kpiMedio,
  }[tamanho]

  return (
    <View style={estilos.kpiLinha}>
      <Text style={[escala, tabular, tom ? { color: tons[tom] } : null]} numberOfLines={1}>
        {valor}
      </Text>
      {unidade ? <Text style={estilos.kpiUnidade}>{unidade}</Text> : null}
      {direita ? <View style={estilos.kpiDireita}>{direita}</View> : null}
    </View>
  )
}

/** Trio de números no rodapé de um card, separado por uma linha fina. */
export function RodapeNumeros({
  itens,
}: {
  itens: { rotulo: string; valor: string; unidade?: string; tom?: Tom }[]
}) {
  return (
    <View style={estilos.rodapeNumeros}>
      {itens.map((it) => (
        <View key={it.rotulo}>
          <Text style={tipo.fraco}>{it.rotulo}</Text>
          <View style={estilos.rodapeValor}>
            <Num style={[estilos.rodapeNum, it.tom ? { color: tons[it.tom] } : null]}>
              {it.valor}
            </Num>
            {it.unidade ? <Text style={estilos.rodapeUnidade}>{it.unidade}</Text> : null}
          </View>
        </View>
      ))}
    </View>
  )
}

/* ------------------------------------------------------------------ barra */

/**
 * Barra de proporção. `pct` de 0 a 100; a cor default é o âmbar da marca, e um `tom`
 * a substitui quando a barra comunica estado (inversor parado, meta atingida).
 */
export function Barra({
  pct,
  tom,
  fina,
}: {
  pct: number
  tom?: Tom
  fina?: boolean
}) {
  const largura = Math.max(0, Math.min(100, pct))
  return (
    <View style={[estilos.barraTrilho, fina && estilos.barraFina]}>
      <View
        style={[
          estilos.barraPreenchida,
          { width: `${largura}%`, backgroundColor: tom ? tons[tom] : cores.ambar },
        ]}
      />
    </View>
  )
}

/* ------------------------------------------------------------------- chip */

export function StatusChip({ tom, texto, grande }: { tom: Tom; texto: string; grande?: boolean }) {
  const { backgroundColor, borderColor, color } = chipDoTom(tom)
  return (
    <View style={[estilos.chip, grande && estilos.chipGrande, { backgroundColor, borderColor }]}>
      <Text style={[estilos.chipTexto, grande && estilos.chipTextoGrande, { color }]}>{texto}</Text>
    </View>
  )
}

/* ----------------------------------------------------------------- setinha */

/** Seta de "abre detalhe". Um quadrado com duas bordas, girado — igual ao design. */
export function Chevron({ tamanho = 7 }: { tamanho?: number }) {
  return (
    <View
      style={{
        width: tamanho,
        height: tamanho,
        borderRightWidth: 1.5,
        borderTopWidth: 1.5,
        borderColor: cores.textoRotulo,
        transform: [{ rotate: '45deg' }],
      }}
    />
  )
}

/** Seta para baixo, do seletor de lista suspensa. */
export function ChevronBaixo() {
  return (
    <View style={estilos.chevronBaixo} />
  )
}

/* ------------------------------------------------------------- segmentado */

/**
 * Escolha entre poucas opções fixas. É este componente OU lista suspensa pesquisável —
 * nunca uma fileira de chips (regra do produto, herdada do meuPlano).
 */
export function Segmentado({
  opcoes,
  ativo,
  onEscolher,
}: {
  opcoes: string[]
  ativo: number
  onEscolher: (i: number) => void
}) {
  return (
    <View style={estilos.segTrilho}>
      {opcoes.map((op, i) => (
        <Pressable
          key={op}
          onPress={() => onEscolher(i)}
          style={[estilos.segItem, i === ativo && estilos.segItemAtivo]}
        >
          <Text style={[estilos.segTexto, i === ativo && estilos.segTextoAtivo]}>{op}</Text>
        </Pressable>
      ))}
    </View>
  )
}

/** Seletor de lista suspensa (a folha ainda não abre — entra com os dados reais). */
export function SeletorLista({ valor, onPress }: { valor: string; onPress?: () => void }) {
  return (
    <Pressable style={estilos.seletor} onPress={onPress}>
      <Text style={estilos.seletorTexto}>{valor}</Text>
      <ChevronBaixo />
    </Pressable>
  )
}

/* ------------------------------------------------------------------ botão */

export function Botao({
  titulo,
  onPress,
  variante = 'primario',
  desabilitado,
}: {
  titulo: string
  onPress?: () => void
  variante?: 'primario' | 'secundario'
  desabilitado?: boolean
}) {
  const primario = variante === 'primario'
  return (
    <Pressable
      onPress={onPress}
      disabled={desabilitado}
      style={[
        estilos.botao,
        primario ? estilos.botaoPrimario : estilos.botaoSecundario,
        desabilitado && estilos.botaoInativo,
      ]}
    >
      <Text style={primario ? estilos.botaoTextoPrimario : estilos.botaoTextoSecundario}>
        {titulo}
      </Text>
    </Pressable>
  )
}

/* ------------------------------------------------------------ item lista */

/**
 * Linha de lista com ícone à esquerda. `naoLido` acende a barra âmbar de 3 pt — o
 * marcador que a prancha define para item pendente.
 */
export function ItemLista({
  tom,
  titulo,
  resumo,
  quando,
  naoLido,
  onPress,
  primeiro,
}: {
  tom: Tom
  titulo: string
  resumo?: string
  quando?: string
  naoLido?: boolean
  onPress?: () => void
  /** A primeira linha de um card não leva divisória em cima. */
  primeiro?: boolean
}) {
  const { backgroundColor, borderColor } = chipDoTom(tom)
  return (
    <Pressable
      onPress={onPress}
      style={[
        estilos.item,
        !primeiro && estilos.itemComDivisoria,
        naoLido && { borderLeftWidth: 3, borderLeftColor: cores.ambar, paddingLeft: 13 },
        naoLido && { backgroundColor: cores.superficie },
      ]}
    >
      <View style={[estilos.itemIcone, { backgroundColor, borderColor }]}>
        <View style={[estilos.itemIconeMiolo, { borderColor: tons[tom] }]} />
      </View>
      <View style={estilos.itemMiolo}>
        <Text style={tipo.itemTitulo}>{titulo}</Text>
        {resumo ? (
          <Text style={estilos.itemResumo} numberOfLines={2}>
            {resumo}
          </Text>
        ) : null}
      </View>
      {quando ? <Num style={estilos.itemQuando}>{quando}</Num> : null}
    </Pressable>
  )
}

/** Linha de navegação: título, valor à direita, seta. */
export function LinhaNavegacao({
  titulo,
  valor,
  tomValor,
  onPress,
  primeiro,
}: {
  titulo: string
  valor?: string
  tomValor?: Tom
  onPress?: () => void
  primeiro?: boolean
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[estilos.linhaNav, !primeiro && estilos.itemComDivisoria]}
    >
      <Text style={estilos.linhaNavTitulo}>{titulo}</Text>
      {valor ? (
        <Text
          style={[estilos.linhaNavValor, tomValor ? { color: tons[tomValor] } : null]}
        >
          {valor}
        </Text>
      ) : null}
      {/* A seta é promessa de navegação. Desenhada sem `onPress`, o dono toca e nada
          acontece — e conclui que o aplicativo travou. */}
      {onPress ? <Chevron /> : null}
    </Pressable>
  )
}

/* ----------------------------------------------------------------- faixas */

/** Faixa de atenção: aparece só quando há problema, na cor da severidade. */
export function FaixaAtencao({
  tom,
  titulo,
  detalhe,
  onPress,
}: {
  tom: Tom
  titulo: string
  detalhe?: string
  onPress?: () => void
}) {
  const { backgroundColor, borderColor } = chipDoTom(tom)
  return (
    <Pressable onPress={onPress} style={[estilos.faixa, { backgroundColor, borderColor }]}>
      <View style={[estilos.faixaPonto, { backgroundColor: tons[tom] }]} />
      <View style={estilos.faixaMiolo}>
        <Text style={[estilos.faixaTitulo, { color: tons[tom] }]}>{titulo}</Text>
        {detalhe ? <Text style={estilos.faixaDetalhe}>{detalhe}</Text> : null}
      </View>
      {onPress ? <Chevron tamanho={8} /> : null}
    </Pressable>
  )
}

/** Faixa de offline, logo abaixo da barra de status. */
export function FaixaOffline({ desde }: { desde: string }) {
  return (
    <View style={estilos.faixaOffline}>
      <View style={estilos.faixaOfflinePonto} />
      <Text style={estilos.faixaOfflineTexto}>
        Sem conexão — mostrando dados de <Num style={estilos.faixaOfflineHora}>{desde}</Num>
      </Text>
    </View>
  )
}

/* ------------------------------------------------------------- skeletons */

/** Bloco cinza de carregamento. Skeleton, nunca spinner solto. */
export function Esqueleto({
  largura,
  altura,
  forte,
}: {
  largura?: number | `${number}%`
  altura: number
  forte?: boolean
}) {
  return (
    <View
      style={{
        width: largura ?? '100%',
        height: altura,
        borderRadius: altura / 2 > 8 ? 8 : altura / 2,
        backgroundColor: forte ? cores.superficieDestacada : cores.borda,
      }}
    />
  )
}

/* --------------------------------------------------------- estados vazios */

export function EstadoVazio({
  titulo,
  descricao,
  acao,
  tom = 'semDados',
}: {
  titulo: string
  descricao: string
  acao?: { titulo: string; onPress?: () => void }
  tom?: Tom
}) {
  const { backgroundColor, borderColor } = chipDoTom(tom)
  return (
    <View style={estilos.vazio}>
      <View style={[estilos.vazioCirculo, { backgroundColor, borderColor }]}>
        <View style={[estilos.vazioMiolo, { borderColor: tons[tom] }]} />
      </View>
      <Text style={tipo.secao}>{titulo}</Text>
      <Text style={estilos.vazioDescricao}>{descricao}</Text>
      {acao ? (
        <View style={estilos.vazioAcao}>
          <Botao titulo={acao.titulo} onPress={acao.onPress} />
        </View>
      ) : null}
    </View>
  )
}

/* ---------------------------------------------------------------- estilos */

const estilos = StyleSheet.create({
  grafBarras: { flexDirection: 'row', alignItems: 'flex-end', gap: 2 },
  grafColuna: { flex: 1, alignItems: 'center' },
  grafBarra: { width: '100%', borderRadius: 2, backgroundColor: cores.ambar },
  // A barra marcada clareia em vez de trocar de cor: cor significa estado do equipamento,
  // e uma barra selecionada não mudou de estado — só está sendo lida.
  grafBarraMarcada: { backgroundColor: cores.textoForte },
  grafEixo: { flexDirection: 'row', gap: 2, marginTop: 4 },
  grafRotulo: { fontSize: 8, color: cores.textoFraco },
  grafRotuloMarcado: { color: cores.textoForte, fontFamily: fontes.ui },

  grafLeitura: { height: 18, justifyContent: 'center', marginBottom: 4 },
  grafLeituraTexto: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoForte },
  grafLeituraVazia: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco },

  grafEixoLinha: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
  grafToque: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 },
  grafLegenda: { flexDirection: 'row', gap: espaco.md, marginTop: 2 },
  grafLegendaItem: { fontFamily: fontes.ui, fontSize: 10, color: cores.textoFraco },

  halo: { position: 'absolute', left: '50%', top: -200, marginLeft: -280 },

  num: { fontFamily: fontes.mono, fontSize: 13, color: cores.textoCorpo },

  card: {
    backgroundColor: cores.superficie,
    borderColor: cores.borda,
    borderWidth: 1,
    borderRadius: raio.card,
    padding: espaco.md,
  },
  cardSemPadding: { padding: 0, overflow: 'hidden' },
  cabecalhoCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },

  kpiLinha: { flexDirection: 'row', alignItems: 'baseline', gap: espaco.sm },
  kpiUnidade: { fontFamily: fontes.uiMedio, fontSize: 16, color: cores.textoCorpo },
  kpiDireita: { marginLeft: 'auto' },

  rodapeNumeros: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  rodapeValor: { flexDirection: 'row', alignItems: 'baseline', gap: espaco.xs, marginTop: 3 },
  rodapeNum: { fontFamily: fontes.monoSemi, fontSize: 17, color: cores.textoForte },
  rodapeUnidade: { fontFamily: fontes.uiMedio, fontSize: 12, color: cores.textoCorpo },

  barraTrilho: {
    height: 6,
    borderRadius: raio.barra,
    backgroundColor: cores.afundado,
    overflow: 'hidden',
  },
  barraFina: { height: 4, borderRadius: 2 },
  barraPreenchida: { height: '100%', borderRadius: raio.barra },

  chip: {
    borderWidth: 1,
    borderRadius: raio.chip,
    paddingHorizontal: 10,
    paddingVertical: 5,
    alignSelf: 'flex-start',
  },
  chipGrande: { paddingHorizontal: 12, paddingVertical: 7 },
  chipTexto: { fontFamily: fontes.uiSemi, fontSize: 11.5 },
  chipTextoGrande: { fontSize: 13 },

  chevronBaixo: {
    width: 8,
    height: 8,
    borderRightWidth: 1.5,
    borderBottomWidth: 1.5,
    borderColor: cores.textoRotulo,
    transform: [{ rotate: '45deg' }],
    marginBottom: 4,
  },

  segTrilho: {
    flexDirection: 'row',
    gap: espaco.xs,
    padding: espaco.xs,
    backgroundColor: cores.afundado,
    borderRadius: raio.campo,
  },
  segItem: {
    flex: 1,
    minHeight: 36,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 9,
  },
  segItemAtivo: { backgroundColor: cores.ambar },
  segTexto: { fontFamily: fontes.uiMedio, fontSize: 13.5, color: cores.textoRotulo },
  segTextoAtivo: { fontFamily: fontes.uiSemi, color: cores.sobreAmbar },

  seletor: {
    height: 50,
    borderRadius: raio.campo,
    backgroundColor: cores.afundado,
    borderWidth: 1,
    borderColor: cores.borda,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
  },
  seletorTexto: { fontFamily: fontes.ui, fontSize: 15, color: cores.textoCorpo },

  botao: {
    height: 52,
    borderRadius: raio.campo,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 10,
  },
  botaoPrimario: { backgroundColor: cores.ambar },
  botaoSecundario: {
    backgroundColor: cores.superficieElevada,
    borderWidth: 1,
    borderColor: cores.borda,
  },
  botaoInativo: { opacity: 0.4 },
  botaoTextoPrimario: { fontFamily: fontes.uiSemi, fontSize: 16, color: cores.sobreAmbar },
  botaoTextoSecundario: { fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte },

  item: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'flex-start',
    paddingHorizontal: espaco.md,
    paddingVertical: 14,
    minHeight: TOQUE_MIN,
  },
  itemComDivisoria: { borderTopWidth: 1, borderTopColor: cores.bordaFraca },
  itemIcone: {
    width: 34,
    height: 34,
    borderRadius: raio.chip,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  itemIconeMiolo: { width: 14, height: 14, borderRadius: 7, borderWidth: 2 },
  itemMiolo: { flex: 1, minWidth: 0 },
  itemResumo: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo, marginTop: 2 },
  itemQuando: { fontSize: 11, color: cores.textoFraco, marginTop: 2 },

  linhaNav: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: espaco.md,
    paddingVertical: 15,
    minHeight: TOQUE_MIN,
  },
  linhaNavTitulo: { flex: 1, fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte },
  linhaNavValor: { fontFamily: fontes.uiSemi, fontSize: 12.5, color: cores.textoRotulo },

  faixa: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderWidth: 1,
    borderRadius: raio.card,
    paddingHorizontal: espaco.md,
    paddingVertical: 14,
    minHeight: TOQUE_MIN,
  },
  faixaPonto: { width: 10, height: 10, borderRadius: 5 },
  faixaMiolo: { flex: 1 },
  faixaTitulo: { fontFamily: fontes.uiSemi, fontSize: 14.5 },
  faixaDetalhe: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 2 },

  faixaOffline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: espaco.sm,
    paddingHorizontal: espaco.md,
    paddingVertical: 9,
    backgroundColor: tomAlpha('semDados', 0.12),
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: tomAlpha('semDados', 0.33),
  },
  faixaOfflinePonto: { width: 8, height: 8, borderRadius: 4, backgroundColor: tons.semDados },
  faixaOfflineTexto: { fontFamily: fontes.uiMedio, fontSize: 12.5, color: tons.semDados },
  faixaOfflineHora: { fontSize: 12.5, color: tons.semDados },

  vazio: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: espaco.md,
    paddingHorizontal: 40,
    paddingBottom: 60,
  },
  vazioCirculo: {
    width: 96,
    height: 96,
    borderRadius: 48,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  vazioMiolo: { width: 40, height: 40, borderRadius: 16, borderWidth: 2 },
  vazioDescricao: {
    fontFamily: fontes.ui,
    fontSize: 13.5,
    lineHeight: 20,
    color: cores.textoRotulo,
    textAlign: 'center',
  },
  vazioAcao: { marginTop: espaco.xs, minWidth: 180 },
})

/** Exportado para telas que precisam da mesma receita de âmbar translúcido. */
export { ambarAlpha }

/* ------------------------------------------------------- gráfico de barras */

/**
 * Barras verticais para a geração por dia (recorte Mês) ou por mês (Ano).
 *
 * Sem biblioteca de gráfico: são `View`s com altura proporcional, no mesmo
 * vocabulário visual da `Barra`. Duas decisões que não devem ser "simplificadas":
 *
 * - **Dia sem leitura não vira barra zero.** Ele simplesmente não está em
 *   `pontos`, e o espaço fica vazio. Barra rasteira no zero se lê como "a usina
 *   não gerou", que é uma afirmação diferente de "não medimos".
 * - **O rótulo do eixo é ralo de propósito.** O passo se ajusta ao tamanho da série
 *   para caber ~6 marcas: 12 meses saem todos, 31 dias saem de 5 em 5, e a curva do dia
 *   (≈120 buckets de 5 min) sai de 20 em 20. Rótulo de 8px empilhado vira sujeira.
 */
export function GraficoBarras({
  pontos,
  altura = 120,
  unidade = 'kWh',
  casas = 1,
}: {
  pontos: { chave: string; rotulo: string; kwh: number }[]
  altura?: number
  /** Sufixo do valor lido ao tocar numa barra. */
  unidade?: string
  /** Casas decimais na leitura. Corrente e temperatura pedem 1; energia diária, 1. */
  casas?: number
}) {
  /*
   * Tocar numa barra mostra o valor dela.
   *
   * O eixo só cabe ~6 rótulos, então numa série de 31 dias a maioria das barras é anônima:
   * dá para ver que uma é menor que as outras e não dá para saber qual dia é, nem quanto.
   * O toque resolve as duas perguntas de uma vez, sem gastar espaço permanente na tela.
   *
   * Tocar de novo na mesma barra desmarca — sem isso a leitura fica presa na tela e o
   * usuário fica sem jeito de voltar ao estado limpo.
   */
  const [marcada, setMarcada] = useState<string | null>(null)

  if (pontos.length === 0) return null
  const maximo = Math.max(...pontos.map((p) => p.kwh), 0)
  const passo = Math.max(1, Math.ceil(pontos.length / 6))
  const lida = pontos.find((p) => p.chave === marcada) ?? null

  return (
    <View>
      {/*
       * A leitura ocupa lugar fixo, mesmo vazia. Se aparecesse e sumisse, o gráfico
       * saltaria alguns pixels a cada toque — que é justamente o tipo de tremor que se
       * quer evitar.
       */}
      <View style={estilos.grafLeitura}>
        {lida ? (
          <Text style={estilos.grafLeituraTexto}>
            {lida.rotulo} · <Num>{lida.kwh.toFixed(casas)}</Num> {unidade}
          </Text>
        ) : (
          <Text style={estilos.grafLeituraVazia}>toque numa barra para ver o valor</Text>
        )}
      </View>

      <View style={[estilos.grafBarras, { height: altura }]}>
        {pontos.map((p) => (
          <Pressable
            key={p.chave}
            style={estilos.grafColuna}
            // A coluna inteira é o alvo, não a barra: uma barra de valor baixo tem poucos
            // pixels de altura e seria impossível de acertar com o dedo.
            onPress={() => setMarcada((atual) => (atual === p.chave ? null : p.chave))}
            hitSlop={4}
          >
            <View
              style={[
                estilos.grafBarra,
                {
                  // `maximo` zero acontece quando todo o período mediu zero: as
                  // barras somem, e é isso mesmo — não há o que desenhar.
                  height: maximo > 0 ? Math.max(2, (p.kwh / maximo) * altura) : 0,
                },
                p.chave === marcada && estilos.grafBarraMarcada,
              ]}
            />
          </Pressable>
        ))}
      </View>
      <View style={estilos.grafEixo}>
        {pontos.map((p, i) => (
          <View key={p.chave} style={estilos.grafColuna}>
            {/* O rótulo da barra marcada aparece mesmo fora do passo do eixo. */}
            {i % passo === 0 || p.chave === marcada ? (
              <Text style={[estilos.grafRotulo, p.chave === marcada && estilos.grafRotuloMarcado]}>
                {p.rotulo}
              </Text>
            ) : null}
          </View>
        ))}
      </View>
    </View>
  )
}

/**
 * Curva do dia — potência e, quando a usina tem estação, irradiação junto.
 *
 * As duas grandezas têm unidades e ordens de grandeza diferentes (kW e W/m²), então cada
 * uma tem a sua escala vertical. Sobrepô-las na mesma escala não compara nada: a irradiação
 * some contra uma usina de 3 MW, ou a potência some contra 1200 W/m².
 *
 * O que a sobreposição mostra — e é o motivo de existir — é o DESCOLAMENTO. Sol firme com
 * potência caindo é inversor com problema; as duas caindo juntas é nuvem. Uma curva sozinha
 * não distingue os dois casos.
 *
 * Não há eixo Y desenhado de propósito: o número exato vem do toque, e dois eixos numéricos
 * numa tela de celular gastam largura sem responder pergunta nenhuma.
 */
export function GraficoLinha({
  pontos,
  altura = 150,
}: {
  pontos: { hora: string; kw: number; poa?: number | null }[]
  altura?: number
}) {
  const [largura, setLargura] = useState(0)
  const [marcado, setMarcado] = useState<number | null>(null)

  if (pontos.length < 2) return null

  const kws = pontos.map((p) => p.kw)
  const poas = pontos.map((p) => p.poa).filter((v): v is number => typeof v === 'number')
  const temPoa = poas.length > 0

  // Escalas partem do zero: uma curva de potência que começasse no mínimo do dia
  // exageraria variações pequenas e faria manhã tranquila parecer despencada.
  const kwMax = Math.max(...kws, 0.001)
  const poaMax = temPoa ? Math.max(...poas, 0.001) : 1

  const x = (i: number) => (i / (pontos.length - 1)) * largura
  const yKw = (v: number) => altura - (v / kwMax) * altura
  const yPoa = (v: number) => altura - (v / poaMax) * altura

  const caminho = (valor: (p: (typeof pontos)[number]) => number | null | undefined,
                   escala: (v: number) => number) => {
    let d = ''
    let aberto = false
    pontos.forEach((p, i) => {
      const v = valor(p)
      if (typeof v !== 'number') {
        // Lacuna: a linha para e recomeça. Ligar os dois lados desenharia uma
        // reta atravessando o buraco, que é interpolação inventada.
        aberto = false
        return
      }
      d += `${aberto ? 'L' : 'M'}${x(i).toFixed(1)} ${escala(v).toFixed(1)} `
      aberto = true
    })
    return d.trim()
  }

  const lido = marcado !== null ? pontos[marcado] : null

  return (
    <View>
      <View style={estilos.grafLeitura}>
        {lido ? (
          <Text style={estilos.grafLeituraTexto}>
            {lido.hora} · <Num>{lido.kw.toFixed(1)}</Num> kW
            {typeof lido.poa === 'number' ? (
              <>
                {'  ·  '}
                <Num>{lido.poa.toFixed(0)}</Num> W/m²
              </>
            ) : null}
          </Text>
        ) : (
          <Text style={estilos.grafLeituraVazia}>toque na curva para ver o valor</Text>
        )}
      </View>

      <View
        style={{ height: altura }}
        onLayout={(e) => setLargura(e.nativeEvent.layout.width)}
      >
        {largura > 0 ? (
          <>
            <Svg width={largura} height={altura}>
              {temPoa ? (
                <Path
                  d={caminho((p) => p.poa, yPoa)}
                  stroke={cores.textoFraco}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  fill="none"
                />
              ) : null}
              <Path d={caminho((p) => p.kw, yKw)} stroke={cores.ambar} strokeWidth={2} fill="none" />
              {lido ? (
                <>
                  <Line
                    x1={x(marcado as number)}
                    y1={0}
                    x2={x(marcado as number)}
                    y2={altura}
                    stroke={cores.textoFraco}
                    strokeWidth={1}
                  />
                  <Circle cx={x(marcado as number)} cy={yKw(lido.kw)} r={3} fill={cores.ambar} />
                </>
              ) : null}
            </Svg>

            {/*
             * O alvo do toque é a faixa inteira, não a linha: acertar um traço de 2 px com
             * o dedo é impossível. O índice sai da posição horizontal — em série de 5 em 5
             * minutos, o erro máximo é meio bucket.
             */}
            <Pressable
              style={estilos.grafToque}
              onPress={(e) => {
                const razao = e.nativeEvent.locationX / largura
                const i = Math.round(razao * (pontos.length - 1))
                const limitado = Math.min(pontos.length - 1, Math.max(0, i))
                setMarcado((atual) => (atual === limitado ? null : limitado))
              }}
            />
          </>
        ) : null}
      </View>

      <View style={estilos.grafEixoLinha}>
        <Text style={estilos.grafRotulo}>{pontos[0].hora}</Text>
        <Text style={estilos.grafRotulo}>{pontos[pontos.length - 1].hora}</Text>
      </View>

      {temPoa ? (
        <View style={estilos.grafLegenda}>
          <Text style={estilos.grafLegendaItem}>— potência</Text>
          <Text style={estilos.grafLegendaItem}>- - irradiação POA</Text>
        </View>
      ) : null}
    </View>
  )
}
