/**
 * Os componentes da prancha de sistema da rodada 1.
 *
 * Ficam juntos num arquivo só de propósito: são peças pequenas que se citam entre si
 * (Card usa Rotulo, Kpi usa Num, Barra usa os tons), e espalhá-las em dez arquivos de
 * vinte linhas dificultaria manter a coerência que a prancha estabelece.
 *
 * Nenhum valor literal aqui — tudo vem de `theme/tokens.ts`.
 */

import type { ReactNode } from 'react'
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native'
import Svg, { Defs, RadialGradient, Rect, Stop } from 'react-native-svg'

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
      <Chevron />
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
