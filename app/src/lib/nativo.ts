/**
 * Carregar um módulo NATIVO sem derrubar o aplicativo quando ele não existe no binário.
 *
 * ## Por que isto precisa existir
 *
 * O aplicativo se atualiza por OTA (`expo-updates`), e OTA entrega **só JavaScript**. Um
 * módulo nativo novo só chega num APK novo. Quando o JS publicado importa um módulo que o
 * binário instalado não tem, `requireNativeModule` lança **na avaliação do módulo** — antes
 * de qualquer render, antes de qualquer dado. Para quem está com o aparelho na mão, a tela
 * simplesmente não abre.
 *
 * Foi exatamente o que aconteceu em 04/09/2026: `expo-screen-orientation` entrou junto com
 * o gráfico em tela cheia (commit `07c4b18`), a `version` do `app.json` nunca subiu, e todo
 * OTA publicado desde então passou a exigir, de APKs antigos, um módulo que eles não têm.
 * Como `grafico-cheio.tsx` é importado pelas três telas atrás do clique numa usina, o
 * sintoma foi cirúrgico: as abas abriam, a usina não.
 *
 * ## A regra
 *
 * **Módulo nativo não se importa no topo de um arquivo que uma rota carrega.** Carregue-o
 * por aqui, use o que ele oferece quando `!= null`, e tenha um comportamento honesto para
 * quando for `null` — a função perdida degrada, o resto da tela vive. Módulos que existem
 * desde o primeiro build (SVG, gesture-handler, file-system…) não precisam disto; a regra
 * vale para o que for adicionado depois.
 */

/** Um módulo por nome: `require` é resolvido uma vez e o resultado (inclusive a ausência) fica. */
const cache = new Map<string, unknown>()

/**
 * Devolve o módulo, ou `null` se ele não estiver no binário instalado.
 *
 * O `carregar` recebe um `require` de verdade — literal, para o Metro conseguir empacotar o
 * módulo — e é chamado dentro de um `try`. Nada de `import()` assíncrono: quem chama está
 * num efeito ou num toque e precisa da resposta agora.
 */
export function moduloNativo<T>(nome: string, carregar: () => T): T | null {
  if (cache.has(nome)) return cache.get(nome) as T | null
  let modulo: T | null = null
  try {
    modulo = carregar()
  } catch {
    // Sem o módulo no binário. Não é erro de programação nem de rede: é um aparelho com
    // APK anterior à dependência. Silencioso de propósito — quem chama decide o que fazer.
    modulo = null
  }
  cache.set(nome, modulo)
  return modulo
}
