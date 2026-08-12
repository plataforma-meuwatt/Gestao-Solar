/**
 * Tokens visuais do Gestão Solar.
 *
 * Os valores vêm da prancha de sistema da rodada 1 do designer (`Claude Designer/`), que
 * por sua vez herda o rebrand 2026-08 do meuWatt. Fonte única: nenhuma cor, raio ou
 * medida literal fora deste arquivo.
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
  bordaFraca: branco(0.06),
  bordaForte: branco(0.12),

  ambar: '#FFC315',
  sobreAmbar: '#02061A',
  textoAmbar: '#FFD75E',

  textoForte: '#F5FDFF',
  textoCorpo: '#DDE2F6',
  textoRotulo: '#D6C4AC',
  textoFraco: '#94A3B8',

  /** Halo radial azul no topo de toda tela. */
  halo: 'rgba(64,110,255,0.20)',

  /** Contorno do ícone de aba inativa — mais forte que a borda de card, de propósito. */
  iconeInativo: branco(0.45),
} as const

/**
 * Os seis tons de status. NÃO invente um sétimo: a mesma régua vale no meuWatt, e cor
 * nova aqui é cor que o usuário não sabe ler.
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

/** Componentes RGB de cada tom, para montar as versões translúcidas. */
const RGB: Record<Tom, string> = {
  parado: '248,113,113',
  alerta: '251,191,36',
  multiplos: '251,146,60',
  tempoRuim: '125,211,252',
  ok: '52,211,153',
  semDados: '148,163,184',
}

/** Receita do chip de status: fundo a 10%, borda a 33%, texto na cor cheia. */
export function chipDoTom(tom: Tom) {
  return {
    backgroundColor: `rgba(${RGB[tom]},0.10)`,
    borderColor: `rgba(${RGB[tom]},0.33)`,
    color: tons[tom],
  }
}

/** Mesma cor com opacidade arbitrária — usado em barras, células e áreas de gráfico. */
export function tomAlpha(tom: Tom, alpha: number) {
  return `rgba(${RGB[tom]},${alpha})`
}

export const ambarAlpha = (alpha: number) => `rgba(255,195,21,${alpha})`

export const fontes = {
  /** Figtree em toda a interface. */
  ui: 'Figtree',
  uiMedio: 'Figtree-Medium',
  uiSemi: 'Figtree-SemiBold',
  uiForte: 'Figtree-Bold',
  /**
   * IBM Plex Mono em TODO número, hora e série. Não é preciosismo: com fonte
   * proporcional os dígitos mudam de largura e o número treme a cada atualização.
   */
  mono: 'IBMPlexMono',
  monoSemi: 'IBMPlexMono-SemiBold',
} as const

export const raio = { chip: 12, campo: 12, card: 16, sheet: 20, barra: 3 } as const

/** Espaçamento em múltiplos de 4. `md` (16) é o respiro padrão entre blocos. */
export const espaco = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 } as const

/** Altura da barra de abas. Constante única — o composer do chat se apoia nela. */
export const ALTURA_TAB_BAR = 68

/**
 * Cabeçalho colapsável: 108 pt expandido, 52 pt em faixa. O avatar encolhe junto,
 * de 40 para 34. O curso de 56 pt é o que a interpolação percorre.
 */
export const CABECALHO = { expandido: 108, faixa: 52, avatar: 40, avatarMin: 34 } as const
export const CURSO_CABECALHO = CABECALHO.expandido - CABECALHO.faixa

/** Alvo de toque mínimo. Nada clicável abaixo disso. */
export const TOQUE_MIN = 44

export const tipo = {
  /** KPI herói da tela (potência agora, energia do dia). */
  kpiHeroi: { fontFamily: fontes.monoSemi, fontSize: 46, lineHeight: 46, color: cores.textoForte },
  kpiGrande: { fontFamily: fontes.monoSemi, fontSize: 42, lineHeight: 42, color: cores.textoForte },
  kpi: { fontFamily: fontes.monoSemi, fontSize: 34, lineHeight: 34, color: cores.textoForte },
  kpiMedio: { fontFamily: fontes.monoSemi, fontSize: 28, lineHeight: 28, color: cores.textoForte },
  kpiPequeno: { fontFamily: fontes.monoSemi, fontSize: 17, color: cores.textoForte },

  titulo: { fontFamily: fontes.uiForte, fontSize: 26, lineHeight: 30, color: cores.textoForte },
  tituloFaixa: { fontFamily: fontes.uiSemi, fontSize: 17, color: cores.textoForte },
  secao: { fontFamily: fontes.uiSemi, fontSize: 18, color: cores.textoForte },
  itemTitulo: { fontFamily: fontes.uiSemi, fontSize: 14.5, color: cores.textoForte },

  corpo: { fontFamily: fontes.ui, fontSize: 15, color: cores.textoCorpo },
  secundario: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoRotulo },
  legenda: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo },
  fraco: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco },

  /** Rótulo de card: caixa alta, espaçado, sempre acima do número. */
  rotuloCard: {
    fontFamily: fontes.uiSemi,
    fontSize: 12,
    letterSpacing: 0.72,
    textTransform: 'uppercase' as const,
    color: cores.textoRotulo,
  },

  numero: { fontFamily: fontes.mono, fontSize: 13, color: cores.textoCorpo },
  numeroPequeno: { fontFamily: fontes.mono, fontSize: 11, color: cores.textoFraco },
} as const

/**
 * Números com largura de dígito fixa. Aplicar em TODO texto numérico — sem isto o valor
 * dança horizontalmente a cada atualização.
 */
export const tabular = { fontVariant: ['tabular-nums' as const] }
