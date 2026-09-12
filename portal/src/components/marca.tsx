/**
 * A marca do Gestão Solar — o selo cheio e o lockup.
 *
 * **Por que existe um arquivo só para isto.** O `base.tsx` é o vocabulário de DADO: peça que
 * desenha número, estado e leitura do BFF. A marca não desenha dado nenhum — ela identifica o
 * produto — e tem uma restrição que nenhuma outra peça tem: o mesmo desenho sai em quatro
 * aplicações (interface, favicon, PDF, documento), e três delas são arquivo, não componente.
 * Juntar isso ao `base.tsx` misturaria as duas coisas num arquivo que já tem 1.800 linhas.
 *
 * **O desenho é inline, e o `public/marca/*.svg` é o mesmo desenho.** Os dois existem de
 * propósito: a interface precisa do SVG dentro do DOM (para herdar cor por classe do Tailwind
 * e escalar sem segunda requisição), e o favicon e o motor de PDF precisam de arquivo. O
 * contorno é o MESMO — se mudar aqui, regere lá, e vice-versa. O cabeçalho de
 * `public/marca/gs-selo.svg` diz como ele foi gerado.
 *
 * **Contorno, não `<text>`.** O `GS` é caminho vetorial extraído da Figtree 700 de
 * `public/fontes/`. Com `<text font-family="Figtree">` o selo dependeria de a fonte já ter
 * carregado: no primeiro render, e em qualquer contexto fora da página, a marca cairia na sans
 * do sistema — e uma marca que muda de forma conforme a rede não é uma marca.
 *
 * **Nenhum hexadecimal aqui.** As duas cores saem dos tokens (`fill-ambar`, `fill-fundo`), como
 * manda o cabeçalho do `tailwind.config.js`. O `grep` por `#RRGGBB` em `src/components` tem de
 * continuar voltando vazio.
 */

import { classesDoTom } from '@/lib/tons'

/**
 * O contorno do monograma, normalizado num quadrado de 100.
 *
 * Construção do handoff: Figtree 700, `letter-spacing: -.04em`, corpo a 43,75% do lado (14 px
 * num selo de 32, 24,5 px num de 56), centrado pela altura de caixa alta — e não pela caixa do
 * texto, que inclui as descendentes que o `GS` não tem e empurraria o par para cima.
 *
 * A 16 px este corpo fecha os vãos do `G` e do `S`. Por isso o favicon é arquivo próprio
 * (`public/favicon.svg`), com o corpo a 47% — e não este desenho reduzido.
 */
const GLIFO_GS =
  'M38.89 65.84Q34.21 65.84 30.60 63.80Q26.99 61.77 24.93 58.20Q22.88 54.64 22.88 50Q22.88 45.36 24.93 41.80Q26.99 38.23 30.60 36.20Q34.21 34.16 38.89 34.16Q41.69 34.16 44.05 34.99Q46.41 35.82 48.23 37.29Q50.04 38.76 51.27 40.64L46.37 43.70Q45.63 42.52 44.42 41.60Q43.22 40.68 41.78 40.16Q40.33 39.63 38.89 39.63Q36 39.63 33.77 40.97Q31.54 42.30 30.27 44.62Q29 46.94 29 50Q29 53.02 30.25 55.38Q31.49 57.74 33.77 59.08Q36.04 60.41 39.02 60.41Q41.25 60.41 43 59.56Q44.75 58.71 45.80 57.17Q46.85 55.64 46.98 53.59L39.89 53.59L39.89 48.91L52.76 48.91L52.76 52.63Q52.67 56.83 50.88 59.78Q49.08 62.73 45.98 64.28Q42.87 65.84 38.89 65.84 M65.71 65.84Q63.39 65.84 61.38 65.27Q59.36 64.70 57.79 63.67Q56.21 62.64 55.18 61.38Q54.16 60.11 53.85 58.71L59.71 56.96Q60.28 58.44 61.73 59.52Q63.17 60.59 65.36 60.63Q67.67 60.67 69.14 59.63Q70.61 58.58 70.61 56.91Q70.61 55.47 69.45 54.48Q68.29 53.50 66.28 52.98L62.29 51.92Q60.06 51.36 58.36 50.20Q56.65 49.04 55.69 47.33Q54.73 45.63 54.73 43.35Q54.73 39.02 57.59 36.59Q60.46 34.16 65.71 34.16Q68.64 34.16 70.85 35.02Q73.06 35.87 74.54 37.44Q76.03 39.02 76.82 41.16L71 42.96Q70.47 41.47 69.08 40.42Q67.67 39.37 65.53 39.37Q63.34 39.37 62.10 40.38Q60.85 41.38 60.85 43.22Q60.85 44.66 61.83 45.49Q62.82 46.33 64.53 46.76L68.55 47.77Q72.49 48.73 74.68 51.22Q76.86 53.72 76.86 56.78Q76.86 59.49 75.55 61.53Q74.24 63.56 71.74 64.70Q69.25 65.84 65.71 65.84'

/**
 * O selo cheio: quadrado âmbar com o `GS` vazado.
 *
 * `tamanho` é o lado em pixels — 32 no topo do portal, 56 na tela de entrada. O raio acompanha
 * (25% do lado, que é o que dá 8 px em 32 e 14 px em 56): um raio fixo deixaria o selo grande
 * com a quina quase viva e o pequeno quase redondo.
 *
 * `invertido` é a variante de fundo claro (PDF): as duas cores trocam de lugar.
 *
 * `aria-hidden` por padrão, porque onde o selo aparece o nome do produto já está escrito — ou no
 * texto ao lado, ou no `aria-label` do link que o embrulha. Selo e nome são a MESMA informação, e
 * um leitor de tela que anuncia as duas lê "Gestão Solar Gestão Solar". Sozinho e sem link que o
 * nomeie, passe `rotulo`.
 */
export function SeloGS({
  tamanho = 32,
  invertido = false,
  rotulo,
  className = '',
}: {
  tamanho?: number
  invertido?: boolean
  rotulo?: string
  className?: string
}) {
  const quadrado = invertido ? 'fill-fundo' : 'fill-ambar'
  const glifo = invertido ? 'fill-ambar' : 'fill-fundo'
  return (
    <svg
      viewBox="0 0 100 100"
      width={tamanho}
      height={tamanho}
      className={`shrink-0 ${className}`}
      role={rotulo ? 'img' : undefined}
      aria-label={rotulo}
      aria-hidden={rotulo ? undefined : true}
    >
      {/* 25 = 25% do lado do viewBox de 100. Não é medição: é geometria. */}
      <rect width="100" height="100" rx="25" className={quadrado} />
      <path d={GLIFO_GS} className={glifo} />
    </svg>
  )
}

/**
 * Selo + nome do produto.
 *
 * As medidas são as do handoff para cada aplicação: no topo do portal o selo tem 32 px, o gap
 * 10 px e o nome 15 px / 600 com `-.015em`; na tela de entrada o selo vai a 56 px, o gap a
 * 14 px e o nome a 21 px com `-.02em`. `descritor` (`carteira · geração · manutenção`) é só da
 * tela de entrada — no topo ele competiria com o seletor de usina, que é o que se lê ali.
 *
 * `classeNome` existe por causa das três larguras do portal: abaixo de 768 px o nome não cabe ao
 * lado do seletor de usina e o topo passa a mostrar só o selo (`hidden md:block`). Esconder o
 * nome não tira nada de quem usa leitor de tela — quem o nomeia é o `aria-label` do link que
 * embrulha o lockup, e ele não depende de largura de tela.
 */
export function LockupGS({
  tamanho = 32,
  descritor,
  classeNome = '',
}: {
  tamanho?: number
  descritor?: string
  classeNome?: string
}) {
  // A escala é derivada do selo, não tabelada: 15/32 e 21/56 caem os dois em ~0,47, e o gap em
  // ~0,3. Um par de medidas fixas se desencontraria no dia em que aparecesse um terceiro
  // tamanho. Nenhum dos dois vem da API: é proporção de desenho.
  const fonte = Math.round(tamanho * 0.47 * 10) / 10
  const gap = Math.round(tamanho * 0.3)
  return (
    <span className="flex items-center" style={{ gap: `${gap}px` }}>
      <SeloGS tamanho={tamanho} />
      <span className={`min-w-0 ${classeNome}`}>
        <span
          className="block truncate font-semibold text-forte"
          style={{ fontSize: `${fonte}px`, letterSpacing: '-0.015em' }}
        >
          Gestão Solar
        </span>
        {descritor ? (
          <span className="mono mt-1 block text-[10.5px] uppercase tracking-[0.14em] text-rotulo">
            {descritor}
          </span>
        ) : null}
      </span>
    </span>
  )
}

/**
 * O anel: a marca de DOCUMENTO.
 *
 * O selo cheio identifica o produto; o anel identifica uma peça que saiu dele — um PDF, um
 * fechamento, um relatório. São o mesmo monograma em dois pesos de presença: o selo é
 * chapado e pequeno, para conviver com o resto da interface; o anel é vazado e grande, para
 * ocupar a capa de um documento que ainda não tem miniatura.
 *
 * É o mesmo desenho da `Rosca` do fechamento de mês (`features/energia/graficos.tsx`), e
 * isso não é coincidência: as duas são um círculo que emoldura um dado.
 *
 * `tom` pinta o anel na cor do estado do documento (o anexo de paradas em `parado`, por
 * exemplo). Sem ele, âmbar — a cor da marca. `tracejado` é o documento que NÃO existe: a
 * peça não publicada não desaparece nem fica cinza-morta, ela aparece com a capa vazada.
 */
export function AnelGS({
  tamanho = 72,
  tom,
  tracejado = false,
}: {
  tamanho?: number
  tom?: string
  tracejado?: boolean
}) {
  const cor = tom ? classesDoTom(tom).texto : 'text-ambar-texto'
  const borda = tom ? classesDoTom(tom).borda : 'border-ambar/50'
  return (
    <span
      aria-hidden
      style={{ width: tamanho, height: tamanho, fontSize: Math.round(tamanho * 0.36) }}
      className={`inline-flex shrink-0 items-center justify-center rounded-[50%] border-[2.5px] font-semibold tracking-[-0.03em] ${cor} ${
        tracejado ? 'border-dashed border-borda-forte' : borda
      }`}
    >
      GS
    </span>
  )
}
