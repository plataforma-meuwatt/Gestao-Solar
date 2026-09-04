/**
 * Os ícones das abas.
 *
 * Desenhados aqui, em `react-native-svg`, e não trazidos de uma família pronta. Duas razões,
 * nesta ordem:
 *
 * 1. **Não se acrescenta peça nativa por OTA.** Uma família de ícones em fonte traz módulo e
 *    asset novos, e o aplicativo se atualiza sem passar pela loja: aparelho com binário
 *    anterior ficaria sem os ícones — ou pior. Traço em SVG usa o que já está instalado
 *    desde o primeiro build.
 * 2. **Coerência.** O desenho do produto é de traço fino sobre fundo escuro; um glifo
 *    emprestado de outra família chega com outro peso e outra caixa, e a barra fica com
 *    cinco pesos diferentes.
 *
 * Todos partem da mesma grade de 24, com traço de 1,8 e pontas arredondadas — é o que faz
 * cinco desenhos diferentes parecerem da mesma mão.
 */

import Svg, { Circle, Line, Path, Rect } from 'react-native-svg'

type Props = { cor: string; tamanho?: number }

const T = 1.8 // espessura única: a barra inteira tem o mesmo peso de traço

function Base({ cor, tamanho = 23, children }: Props & { children: React.ReactNode }) {
  return (
    <Svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none"
         stroke={cor} strokeWidth={T} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </Svg>
  )
}

/** Início: a casa. O telhado sozinho seria mais leve, mas some no meio dos outros traços. */
export function IconeInicio(p: Props) {
  return (
    <Base {...p}>
      <Path d="M3.5 10.2 12 3.6l8.5 6.6" />
      <Path d="M5.6 11.8V20h12.8v-8.2" />
      <Path d="M9.7 20v-4.7h4.6V20" />
    </Base>
  )
}

/**
 * Usinas: o painel fotovoltaico, deitado como no campo.
 *
 * Um sol seria mais óbvio e diria a coisa errada — o assunto da aba é o ATIVO, não o
 * tempo. As três divisões são o que faz o retângulo virar módulo à primeira vista.
 */
export function IconeUsinas(p: Props) {
  return (
    <Base {...p}>
      <Path d="M2.7 15.4 5.1 6.6h13.8l2.4 8.8H2.7Z" />
      <Line x1="8.1" y1="6.6" x2="6.8" y2="15.4" />
      <Line x1="15.9" y1="6.6" x2="17.2" y2="15.4" />
      <Line x1="3.9" y1="11" x2="20.1" y2="11" />
      <Line x1="12" y1="15.4" x2="12" y2="20.4" />
    </Base>
  )
}

/** Documentos: a folha com o canto dobrado — a dobra é o que a separa de um retângulo. */
export function IconeDocumentos(p: Props) {
  return (
    <Base {...p}>
      <Path d="M13.6 3.2H7.3a1.9 1.9 0 0 0-1.9 1.9v13.8a1.9 1.9 0 0 0 1.9 1.9h9.4a1.9 1.9 0 0 0 1.9-1.9V8.2Z" />
      <Path d="M13.6 3.2v5h5" />
      <Line x1="8.9" y1="13.2" x2="15.1" y2="13.2" />
      <Line x1="8.9" y1="16.6" x2="13.2" y2="16.6" />
    </Base>
  )
}

/**
 * Manutenção: a chave de boca.
 *
 * A engrenagem é o desenho automático para "manutenção" e diz "configurações" na barra de
 * um aplicativo — a chave não tem essa ambiguidade.
 */
export function IconeManutencao(p: Props) {
  return (
    <Base {...p}>
      <Path d="M15.3 3.6a5 5 0 0 0-5.8 6.6L3.4 16.3a2 2 0 0 0 2.8 2.8l6.1-6.1a5 5 0 0 0 6.6-5.8l-2.9 2.9-2.6-.7-.7-2.6Z" />
    </Base>
  )
}

/** Assistente: o balão de conversa, com as reticências de quem responde. */
export function IconeAssistente(p: Props) {
  return (
    <Base {...p}>
      <Path d="M20.4 12.9a7.3 7.3 0 0 1-7.8 7.3 8 8 0 0 1-2.3-.4l-4.7 1.4 1.4-4.4a7.6 7.6 0 0 1-.6-3 7.3 7.3 0 0 1 7.3-7.3h.5a7.3 7.3 0 0 1 6.2 6.2Z" />
      <Circle cx="9.6" cy="13" r={0.9} fill={p.cor} stroke="none" />
      <Circle cx="13" cy="13" r={0.9} fill={p.cor} stroke="none" />
      <Circle cx="16.4" cy="13" r={0.9} fill={p.cor} stroke="none" />
    </Base>
  )
}

/** Usado por quem precisa de um retângulo neutro de mesmo peso (estados vazios). */
export function IconeGenerico(p: Props) {
  return (
    <Base {...p}>
      <Rect x="4" y="4" width="16" height="16" rx="3" />
    </Base>
  )
}
