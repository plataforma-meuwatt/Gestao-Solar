/**
 * A marca do Gestão Solar no aplicativo — o selo cheio e o lockup.
 *
 * **É o MESMO desenho do portal** (`portal/src/components/marca.tsx`) e dos arquivos de
 * `portal/public/marca/`: o mesmo quadrado âmbar, o mesmo raio de 25% do lado e o mesmo
 * contorno do monograma. Não é coincidência a ser "simplificada": o dono da usina abre o
 * aplicativo no celular e o portal no navegador, muitas vezes no mesmo dia, e duas marcas
 * parecidas-mas-não-iguais são pior do que duas marcas diferentes — a segunda diz "outro
 * produto", a primeira diz "alguém errou".
 *
 * **O `GS` é contorno vetorial, não texto.** Foi extraído da própria Figtree 700 (a mesma
 * face que `assets/fonts/` embute). Com `<Text>` o selo dependeria de a fonte já ter
 * carregado — e o `expo-font` carrega depois do primeiro render, então a marca apareceria
 * na sans do sistema e trocaria de forma no meio da abertura.
 *
 * **`react-native-svg` já é peça do aplicativo**, usada por `base.tsx` e por `icones.tsx`,
 * que toda tela carrega. Por isso desenhar aqui não é módulo nativo novo, e este arquivo
 * pode ir por OTA — ver o aviso do `CLAUDE.md` sobre importar nativo no topo de arquivo que
 * uma rota carrega.
 */

import { Text, View, type ViewStyle } from 'react-native'
import Svg, { Path, Rect } from 'react-native-svg'

import { cores, fontes } from '@/theme/tokens'

/**
 * O contorno do monograma, normalizado num quadrado de 100.
 *
 * Figtree 700, `letter-spacing: -.04em`, corpo a 43,75% do lado, centrado pela altura de
 * caixa alta — e não pela caixa do texto, que inclui descendentes que o `GS` não tem.
 * Byte a byte o mesmo do portal: se mudar lá, muda aqui.
 */
const GLIFO_GS =
  'M38.89 65.84Q34.21 65.84 30.60 63.80Q26.99 61.77 24.93 58.20Q22.88 54.64 22.88 50Q22.88 45.36 24.93 41.80Q26.99 38.23 30.60 36.20Q34.21 34.16 38.89 34.16Q41.69 34.16 44.05 34.99Q46.41 35.82 48.23 37.29Q50.04 38.76 51.27 40.64L46.37 43.70Q45.63 42.52 44.42 41.60Q43.22 40.68 41.78 40.16Q40.33 39.63 38.89 39.63Q36 39.63 33.77 40.97Q31.54 42.30 30.27 44.62Q29 46.94 29 50Q29 53.02 30.25 55.38Q31.49 57.74 33.77 59.08Q36.04 60.41 39.02 60.41Q41.25 60.41 43 59.56Q44.75 58.71 45.80 57.17Q46.85 55.64 46.98 53.59L39.89 53.59L39.89 48.91L52.76 48.91L52.76 52.63Q52.67 56.83 50.88 59.78Q49.08 62.73 45.98 64.28Q42.87 65.84 38.89 65.84 M65.71 65.84Q63.39 65.84 61.38 65.27Q59.36 64.70 57.79 63.67Q56.21 62.64 55.18 61.38Q54.16 60.11 53.85 58.71L59.71 56.96Q60.28 58.44 61.73 59.52Q63.17 60.59 65.36 60.63Q67.67 60.67 69.14 59.63Q70.61 58.58 70.61 56.91Q70.61 55.47 69.45 54.48Q68.29 53.50 66.28 52.98L62.29 51.92Q60.06 51.36 58.36 50.20Q56.65 49.04 55.69 47.33Q54.73 45.63 54.73 43.35Q54.73 39.02 57.59 36.59Q60.46 34.16 65.71 34.16Q68.64 34.16 70.85 35.02Q73.06 35.87 74.54 37.44Q76.03 39.02 76.82 41.16L71 42.96Q70.47 41.47 69.08 40.42Q67.67 39.37 65.53 39.37Q63.34 39.37 62.10 40.38Q60.85 41.38 60.85 43.22Q60.85 44.66 61.83 45.49Q62.82 46.33 64.53 46.76L68.55 47.77Q72.49 48.73 74.68 51.22Q76.86 53.72 76.86 56.78Q76.86 59.49 75.55 61.53Q74.24 63.56 71.74 64.70Q69.25 65.84 65.71 65.84'

/**
 * O selo cheio: quadrado âmbar com o `GS` vazado.
 *
 * `tamanho` é o lado em pixels. O raio acompanha (25% do lado): fixo, ele deixaria o selo
 * grande com a quina quase viva e o pequeno quase redondo.
 *
 * `invertido` troca as duas cores — é a variante de fundo claro, para o PDF.
 */
export function SeloGS({
  tamanho = 44,
  invertido = false,
}: {
  tamanho?: number
  invertido?: boolean
}) {
  return (
    <Svg width={tamanho} height={tamanho} viewBox="0 0 100 100">
      {/* 25 = 25% do lado do viewBox de 100. Não é medição: é geometria. */}
      <Rect width={100} height={100} rx={25} fill={invertido ? cores.fundo : cores.ambar} />
      <Path d={GLIFO_GS} fill={invertido ? cores.ambar : cores.fundo} />
    </Svg>
  )
}

/**
 * Selo + nome do produto.
 *
 * A escala do nome sai do selo (≈0,47 do lado), como no portal, e não de uma tabela: um par
 * de medidas fixas se desencontraria no dia em que aparecesse um terceiro tamanho.
 */
export function LockupGS({ tamanho = 56, style }: { tamanho?: number; style?: ViewStyle }) {
  const fonte = Math.round(tamanho * 0.47)
  return (
    <View style={[{ flexDirection: 'row', alignItems: 'center', gap: Math.round(tamanho * 0.3) }, style]}>
      <SeloGS tamanho={tamanho} />
      <Text
        style={{
          fontFamily: fontes.uiForte,
          fontSize: fonte,
          letterSpacing: -fonte * 0.015,
          color: cores.textoForte,
        }}
      >
        Gestão Solar
      </Text>
    </View>
  )
}
