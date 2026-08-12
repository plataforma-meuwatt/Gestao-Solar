/**
 * Documento HTML que envolve o app na versão web.
 *
 * Existe por um motivo específico: no react-native-web, `flex: 1` só se resolve se a
 * cadeia inteira tiver altura. Sem `height: 100%` em html/body/#root, o container cresce
 * sem limite — a barra de abas é empurrada para fora da tela e sobra o branco do body
 * embaixo do conteúdo. Era exatamente esse o sintoma.
 *
 * Este arquivo roda só no build web e não afeta iOS nem Android.
 */

import { ScrollViewStyleReset } from 'expo-router/html'
import type { PropsWithChildren } from 'react'

const CSS_BASE = `
html, body, #root {
  height: 100%;
  margin: 0;
  padding: 0;
  background-color: #02061A;
}
/* O app rola por dentro (ScrollView); a página em si não deve rolar. */
body { overflow: hidden; overscroll-behavior: none; }
/* A barra de rolagem do desktop desloca o layout e falseia a largura do celular. */
::-webkit-scrollbar { width: 0; height: 0; display: none; }
* { scrollbar-width: none; }
`

export default function Html({ children }: PropsWithChildren) {
  return (
    <html lang="pt-BR">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, shrink-to-fit=no, viewport-fit=cover"
        />
        {/* Reset do expo-router para o body não rolar junto com as ScrollViews. */}
        <ScrollViewStyleReset />
        <style dangerouslySetInnerHTML={{ __html: CSS_BASE }} />
      </head>
      <body>{children}</body>
    </html>
  )
}
