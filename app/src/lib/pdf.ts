/**
 * Baixar um PDF do BFF, desenhá-lo dentro do app e entregá-lo ao sistema — a fonte única.
 *
 * Existiam duas cópias disto (o componente `AbrirPdf` e a tela `documento/[id]`), com o
 * mesmo defeito nas duas: o download por `File.downloadFileAsync` e a mensagem de erro
 * adivinhada por expressão regular sobre o texto da exceção. Consertar em um lugar deixava
 * o outro quebrado, então virou função.
 *
 * ## Por que `fetch` e não `downloadFileAsync`
 *
 * No Android o `downloadFileAsync` usa um `OkHttpClient()` sem configuração: *read timeout*
 * de **10 segundos**. Como o BFF só começa a responder depois que o PDF inteiro chegou do
 * meuPlano, esse relógio corre contra a GERAÇÃO do documento — e uma ficha com fotos leva
 * mais que isso na primeira vez. O `fetch` do React Native usa o cliente do próprio RN, sem
 * esse teto, e ainda entrega o corpo da resposta de erro, que é onde o servidor escreve o
 * motivo de verdade.
 *
 * ## Por que a mensagem vem do servidor
 *
 * O código antigo procurava "403" ou "502" no texto da exceção e escrevia uma frase própria.
 * A ponte achata falhas do meuPlano em 502, então uma questão de permissão chegava ao dono
 * como "não conseguiu gerar o PDF" — uma acusação falsa, e sem pista do que fazer. Agora o
 * que aparece na tela é o `detail` que o servidor escreveu.
 *
 * ## Por que o arquivo se partiu em degraus
 *
 * `baixarPdf` (traz os bytes e grava em cache), `compartilharPdf` (entrega ao sistema) e
 * `escreverPaginaDoLeitor` (monta a página que o leitor interno desenha). Antes havia só o
 * caminho do compartilhamento, porque o WebView do Android não desenha PDF sozinho — e o
 * preço era o dono sair do aplicativo para ler um relatório. Com o pdf.js embutido
 * (`lib/pdfjs-embutido.ts`) o desenho passou a ser possível DENTRO do app, e o
 * compartilhamento virou o segundo botão em vez do único caminho. Os degraus existem
 * separados para que o leitor não rebaixe o botão externo: quem já tem o arquivo em disco
 * compartilha sem baixar de novo.
 */

import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'

import { detalheEmTexto, tokenDaSessao } from '@/lib/api'
import { PDFJS_MIOLO, PDFJS_VERSAO, PDFJS_WORKER } from '@/lib/pdfjs-embutido'

/** Um PDF grande é normal; um "PDF" de 200 bytes é uma página de erro disfarçada. */
const MINIMO_PLAUSIVEL = 1000

/**
 * Acima disto o leitor interno não é tentado: vai direto ao aplicativo externo.
 *
 * O motivo é memória, não gosto. Para desenhar, o arquivo viaja em base64 dentro do HTML
 * (cresce um terço) e o pdf.js ainda mantém a cópia decodificada — um documento de 20 MB
 * pede perto de 60 MB só de texto e bytes num WebView que divide a memória com o resto do
 * aplicativo. O teto é declarado aqui, e a tela DIZ por que mandou para fora, em vez de
 * tentar, travar e culpar o aparelho.
 */
export const TETO_LEITOR_BYTES = 15 * 1024 * 1024

/** O que o visualizador dentro do WebView manda de volta. Veredito, nunca palpite. */
export type RecadoDoLeitor =
  | { tipo: 'documento-aberto'; paginas: number }
  | { tipo: 'pagina-pronta'; pagina: number; paginas: number }
  | { tipo: 'render-completo'; paginas: number; desenhadas: number; truncado: boolean }
  | { tipo: 'erro'; mensagem: string }

/* --------------------------------------------------------------- download */

/**
 * Baixa o PDF e grava em cache. **Não abre nada** — quem decide o destino é quem chamou.
 *
 * @returns o arquivo em disco, ou a frase a mostrar ao usuário.
 */
export async function baixarPdf({
  url,
  arquivo,
}: {
  url: string
  /** Nome do arquivo em cache. Sem extensão o Android não sabe o que abrir. */
  arquivo: string
}): Promise<{ arquivo: FileSystem.File } | { erro: string }> {
  let bytes: Uint8Array
  try {
    const resposta = await fetch(url, {
      headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
    })
    if (!resposta.ok) return { erro: await motivoDaResposta(resposta) }
    bytes = new Uint8Array(await resposta.arrayBuffer())
  } catch (e) {
    return {
      erro:
        e instanceof Error && /abort/i.test(e.message)
          ? 'O download foi interrompido. Tente de novo.'
          : 'Não foi possível baixar. Verifique a conexão e tente de novo.',
    }
  }

  if (bytes.byteLength < MINIMO_PLAUSIVEL) {
    return { erro: 'O servidor respondeu, mas o arquivo veio vazio. Tente de novo.' }
  }

  try {
    const destino = new FileSystem.File(FileSystem.Paths.cache, arquivo)
    // Apaga antes: o upstream versiona o PDF por fingerprint, então um arquivo antigo com
    // o mesmo nome entregaria a versão de ontem sem avisar.
    if (destino.exists) destino.delete()
    destino.create()
    destino.write(bytes)
    return { arquivo: destino }
  } catch {
    return { erro: 'O arquivo baixou, mas não deu para gravá-lo neste aparelho.' }
  }
}

/* ----------------------------------------------------------- compartilhar */

/** Entrega ao sistema um arquivo que JÁ está em disco. `null` quando deu certo. */
export async function compartilharPdf(uri: string, titulo: string): Promise<string | null> {
  try {
    if (!(await Sharing.isAvailableAsync())) return 'Este aparelho não tem com o que abrir PDF.'
    await Sharing.shareAsync(uri, {
      mimeType: 'application/pdf',
      dialogTitle: titulo,
      UTI: 'com.adobe.pdf',
    })
    return null
  } catch {
    return 'O arquivo baixou, mas não deu para abri-lo neste aparelho.'
  }
}

/**
 * Baixa e entrega ao compartilhamento do sistema — o caminho "abrir em outro aplicativo".
 *
 * @returns `null` quando deu certo, ou a frase a mostrar ao usuário.
 */
export async function abrirPdf({
  url,
  arquivo,
  titulo,
}: {
  url: string
  arquivo: string
  titulo: string
}): Promise<string | null> {
  const baixado = await baixarPdf({ url, arquivo })
  if ('erro' in baixado) return baixado.erro
  return compartilharPdf(baixado.arquivo.uri, titulo)
}

/* ------------------------------------------------------- página do leitor */

/**
 * As peças da página do leitor, na ordem em que devem ser gravadas.
 *
 * Devolve pedaços em vez de uma string só porque a maior delas — o base64 do PDF — pode
 * ter alguns megabytes, e concatenar tudo dobraria o pico de memória sem nenhum ganho: o
 * gravador escreve pedaço a pedaço, em modo *append*.
 *
 * É função pura para poder ser conferida em teste sem aparelho, sem WebView e sem rede.
 */
export function pedacosDaPaginaDoLeitor(pdfBase64: string): string[] {
  return [
    ABERTURA,
    // O worker vem ANTES do miolo: ele planta `globalThis.pdfjsWorker`, e é olhando esse
    // global que o pdf.js desiste de abrir um Web Worker (território incerto num documento
    // `file://`) e roda o parsing no thread principal.
    ABRE_MODULO,
    PDFJS_WORKER,
    FECHA_SCRIPT,
    ABRE_MODULO,
    PDFJS_MIOLO,
    // O visualizador entra no MESMO módulo do miolo, e é por isso que enxerga `getDocument`
    // sem `import`: num bloco de módulo embutido as declarações do topo estão todas no
    // mesmo escopo.
    VISUALIZADOR,
    FECHA_SCRIPT,
    ABRE_BASE64,
    pdfBase64,
    FECHA_SCRIPT,
    FECHAMENTO,
  ]
}

/**
 * Grava, ao lado do PDF, o HTML que o WebView vai abrir. Devolve o arquivo gravado.
 *
 * O WebView **nunca** vê a URL autenticada do BFF: o que ele recebe é este arquivo local,
 * com os bytes do documento já dentro. Token em URL vai para log; aqui não há URL nenhuma.
 */
export function escreverPaginaDoLeitor(pdf: FileSystem.File): FileSystem.File {
  const pagina = new FileSystem.File(FileSystem.Paths.cache, `${pdf.name}.leitor.html`)
  if (pagina.exists) pagina.delete()
  pagina.create()
  let primeiro = true
  for (const pedaco of pedacosDaPaginaDoLeitor(pdf.base64Sync())) {
    pagina.write(pedaco, { append: !primeiro })
    primeiro = false
  }
  return pagina
}

/* ------------------------------------------------------------------ peças */

// Partidas ao meio de propósito: a sequência inteira, escrita por extenso num arquivo que
// um dia fosse servido como HTML, fecharia a tag errada. Defesa barata contra um erro caro.
const ABRE_MODULO = '<scr' + 'ipt type="module">'
const ABRE_BASE64 = '<scr' + 'ipt type="application/base64" id="pdf">'
const FECHA_SCRIPT = '</scr' + 'ipt>'

/**
 * O `maximum-scale` alto é de propósito: quem lê laudo em campo precisa aproximar a foto
 * térmica. `user-scalable=no` seria acessibilidade jogada fora.
 */
const ABERTURA =
  `<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=6,minimum-scale=1">
<style>
  html,body{margin:0;padding:0;background:#0A0D1C;-webkit-text-size-adjust:100%}
  #paginas{display:flex;flex-direction:column;align-items:center;gap:10px;padding:10px 8px 24px}
  canvas{width:100%;height:auto;display:block;background:#fff;border-radius:6px;
         box-shadow:0 1px 8px rgba(0,0,0,.45)}
  .folha{width:100%;max-width:900px}
  #pdf{display:none}
</style></head><body><div id="paginas"></div>
` +
  '<scr' +
  'ipt>' +
  `
  // Rede de segurança FORA do módulo: erro de sintaxe dentro de um bloco de módulo não é
  // pego por try/catch nenhum, e sem isto a tela ficaria no "carregando" para sempre.
  window.__avisar = function (recado) {
    try { window.ReactNativeWebView.postMessage(JSON.stringify(recado)) } catch (e) {}
  }
  window.addEventListener('error', function (e) {
    window.__avisar({ tipo: 'erro', mensagem: (e && e.message) || 'falha ao carregar o visualizador' })
  })
  window.addEventListener('unhandledrejection', function (e) {
    var m = e && e.reason && e.reason.message
    window.__avisar({ tipo: 'erro', mensagem: m || 'falha ao desenhar o documento' })
  })
` +
  '</scr' +
  'ipt>\n'

const FECHAMENTO = `
</body></html>
`

/**
 * O visualizador. Duas decisões moram aqui e as duas vieram de defeito medido:
 *
 * 1. **`onLoadEnd` não é veredito.** A tentativa anterior de WebView apontava para o PDF,
 *    o `onLoadEnd` disparava, a tela saía do carregando e o dono ficava olhando folha
 *    branca. Aqui quem declara o fim é o desenho: `pagina-pronta` só sai depois que o
 *    `render` daquela página terminou, e é ele que tira a tela do carregando. Folha branca
 *    deixa de ser um estado alcançável.
 * 2. **Teto de páginas desenhadas.** Um pacote de fichas tem dezenas de páginas com foto;
 *    desenhar todas de uma vez estoura a memória do WebView e mata o aplicativo inteiro.
 *    Passando do teto, o leitor diz que truncou — e o botão externo continua ali.
 */
const VISUALIZADOR = `
const TETO_PAGINAS = 60
const avisar = window.__avisar
const alvo = document.getElementById('paginas')

async function desenhar() {
  if (!globalThis.pdfjsWorker) {
    avisar({ tipo: 'erro', mensagem: 'o motor de PDF (${PDFJS_VERSAO}) não carregou por inteiro' })
    return
  }

  const cru = atob(document.getElementById('pdf').textContent.trim())
  const bytes = new Uint8Array(cru.length)
  for (let i = 0; i < cru.length; i++) bytes[i] = cru.charCodeAt(i)

  const doc = await getDocument({ data: bytes, isEvalSupported: false }).promise
  const paginas = doc.numPages
  avisar({ tipo: 'documento-aberto', paginas: paginas })

  const largura = alvo.clientWidth || document.documentElement.clientWidth
  // Teto de 2 no fator de tela: num aparelho de 3x o canvas triplicaria de área, e a
  // memória com ele, sem que o olho enxergasse diferença numa folha A4 reduzida a 360 pt.
  const nitidez = Math.min(window.devicePixelRatio || 1, 2)
  const desenhadas = Math.min(paginas, TETO_PAGINAS)

  for (let n = 1; n <= desenhadas; n++) {
    const pagina = await doc.getPage(n)
    const base = pagina.getViewport({ scale: 1 })
    const escala = (largura / base.width) * nitidez
    const vista = pagina.getViewport({ scale: escala })

    const tela = document.createElement('canvas')
    tela.className = 'folha'
    tela.width = Math.floor(vista.width)
    tela.height = Math.floor(vista.height)
    alvo.appendChild(tela)

    await pagina.render({ canvasContext: tela.getContext('2d'), viewport: vista }).promise
    pagina.cleanup()
    avisar({ tipo: 'pagina-pronta', pagina: n, paginas: paginas })
  }

  avisar({
    tipo: 'render-completo',
    paginas: paginas,
    desenhadas: desenhadas,
    truncado: desenhadas < paginas,
  })
}

desenhar().catch(function (e) {
  avisar({ tipo: 'erro', mensagem: (e && e.message) || 'não deu para desenhar este documento' })
})
`

/* ------------------------------------------------------------------- erro */

/** O motivo que o SERVIDOR escreveu — nunca uma adivinhação a partir do número do status. */
async function motivoDaResposta(r: Response): Promise<string> {
  let detalhe: string | null = null
  try {
    const texto = await r.text()
    try {
      detalhe = detalheEmTexto((JSON.parse(texto) as { detail?: unknown }).detail)
    } catch {
      detalhe = null
    }
    if (!detalhe) detalhe = texto.trim().slice(0, 300) || null
  } catch {
    detalhe = null
  }

  if (r.status === 401) return 'A sua sessão expirou. Entre de novo.'
  if (r.status === 403) return detalhe ?? 'Este documento não está disponível para a sua conta.'
  if (r.status === 404) return detalhe ?? 'Este documento não existe mais.'
  return detalhe
    ? `Não deu para abrir o PDF: ${detalhe}`
    : `Não deu para abrir o PDF (erro ${r.status}). Tente mais tarde.`
}
