/**
 * Tokens visuais do Gestão Solar.
 *
 * Herdados do rebrand 2026-08 do meuWatt — os valores são os mesmos do `@theme` de
 * `mw-fe/src/index.css`, para que os dois produtos pareçam a mesma marca. Fonte única:
 * nenhuma cor literal fora deste arquivo.
 */

/** Branco/preto com opacidade, no formato que o React Native aceita. */
const branco = (a: number) => `rgba(255,255,255,${a})`
const preto = (a: number) => `rgba(0,0,0,${a})`

export const cores = {
  fundo: '#02061A',

  // Superfícies "glass": branco translúcido sobre o fundo. A separação entre blocos vem
  // da borda, não de sombra — sombra sobre fundo quase preto não aparece.
  superficie: branco(0.04),
  superficieElevada: branco(0.08),
  superficieDestacada: branco(0.12),
  afundado: preto(0.25),
  painelFlutuante: 'rgba(9,14,38,0.97)',

  borda: branco(0.08),
  bordaForte: branco(0.12),

  ambar: '#FFC315',
  sobreAmbar: '#02061A',
  textoAmbar: '#FFD75E',

  textoForte: '#F5FDFF',
  textoCorpo: '#DDE2F6',
  textoRotulo: '#D6C4AC',
} as const

/**
 * Os seis tons de status. NÃO invente um sétimo: a mesma régua vale no meuWatt, e cor
 * nova aqui significa cor que o usuário não sabe ler.
 */
export const tons = {
  parado: '#F87171',
  alerta: '#FBBF24',
  multiplos: '#FB923C',
  tempoRuim: '#7DD3FC',
  ok: '#34D399',
  semDados: '#94A3B8',
} as const

export type Tom = keyof typeof tons

/** Receita do chip de status: fundo a 10%, borda a 33%, texto na cor cheia. */
export function chipDoTom(tom: Tom) {
  const cor = tons[tom]
  return { backgroundColor: `${cor}1A`, borderColor: `${cor}55`, color: cor }
}

export const fontes = {
  /** Figtree em toda a interface. */
  ui: 'Figtree',
  uiMedio: 'Figtree-Medium',
  uiSemi: 'Figtree-SemiBold',
  uiForte: 'Figtree-Bold',
  /**
   * IBM Plex Mono em TODO número, hora e série. Não é preciosismo: com fonte
   * proporcional os dígitos mudam de largura e o KPI treme a cada atualização.
   */
  mono: 'IBMPlexMono',
  monoMedio: 'IBMPlexMono-Medium',
} as const

export const raio = { chip: 12, campo: 12, card: 16, sheet: 20 } as const

/** Espaçamento em múltiplos de 4. `md` (16) é o respiro padrão entre blocos. */
export const espaco = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 } as const

export const tipo = {
  kpiGrande: { fontFamily: fontes.mono, fontSize: 40, color: cores.textoForte },
  kpi: { fontFamily: fontes.mono, fontSize: 28, color: cores.textoForte },
  titulo: { fontFamily: fontes.uiForte, fontSize: 28, color: cores.textoForte },
  tituloColapsado: { fontFamily: fontes.uiSemi, fontSize: 17, color: cores.textoForte },
  secao: { fontFamily: fontes.uiSemi, fontSize: 17, color: cores.textoForte },
  corpo: { fontFamily: fontes.ui, fontSize: 15, color: cores.textoCorpo },
  rotulo: { fontFamily: fontes.uiMedio, fontSize: 12, color: cores.textoRotulo },
  numero: { fontFamily: fontes.mono, fontSize: 15, color: cores.textoCorpo },
} as const

/** Altura da barra de abas. Constante única — o composer do chat se apoia nela. */
export const ALTURA_TAB_BAR = 68
