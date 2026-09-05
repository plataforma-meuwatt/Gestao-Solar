/**
 * Gera `src/lib/pdfjs-embutido.ts` a partir do pdf.js instalado em `node_modules`.
 *
 * ## Por que EMBUTIR e não buscar de uma CDN
 *
 * O app é usado em campo, com rede ruim ou nenhuma. Um leitor que só desenha depois de
 * baixar 1,8 MB de um terceiro é um leitor que não funciona justo quando é preciso — e
 * contraria a primeira regra do produto (offline primeiro). Embutido, o pdf.js viaja
 * dentro do bundle JS, e bundle JS sobe por **OTA**: o cliente vê hoje, sem APK novo.
 *
 * ## Por que o build `legacy`
 *
 * O build moderno usa sintaxe que o motor do Android System WebView antigo não conhece.
 * O `legacy` é transpilado para baixo e é o único que se pode prometer a um parque de
 * aparelhos que não escolhemos.
 *
 * ## Por que o WORKER também entra (e é ele o pesado)
 *
 * pdf.js roda o miolo de parsing num Web Worker. Num documento `file://` de WebView o
 * Worker é território incerto, então usamos o caminho oficial de *fake worker*: o próprio
 * `pdf.worker.min.mjs` termina com `globalThis.pdfjsWorker={WorkerMessageHandler}`, e o
 * `pdf.min.mjs` verifica esse global ANTES de tentar `new Worker(...)` — achando-o, desiste
 * do Worker sozinho e roda tudo no thread principal. Sem o worker embutido não há leitor:
 * o `getDocument` ficaria pendurado para sempre esperando um Worker que não vem.
 *
 * ## As três travas de build
 *
 * Este script FALHA (em vez de gerar um arquivo silenciosamente quebrado) quando:
 *  1. o `pdf.worker.min.mjs` deixa de plantar `globalThis.pdfjsWorker` — seria o leitor
 *     travando no "carregando" para sempre, sem erro nenhum;
 *  2. algum dos dois arquivos deixa de terminar em declaração `export{…}` — sinal de que a
 *     forma do build mudou e a inclusão como módulo inline precisa ser reconferida;
 *  3. algum deles passa a conter a sequência `</script` — que fecharia a tag no meio do
 *     código e transformaria o resto do pdf.js em texto visível na tela.
 *
 * ## Como rodar
 *
 * ```
 * cd app && npm run embutir-pdfjs
 * ```
 *
 * O arquivo gerado É versionado: quem clona o repositório não precisa do `pdfjs-dist`
 * instalado para o app compilar. O `pdfjs-dist` é devDependency exatamente por isso — ele
 * serve a este script, e não ao aplicativo.
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const RAIZ = join(dirname(fileURLToPath(import.meta.url)), '..')
const DESTINO = join(RAIZ, 'src', 'lib', 'pdfjs-embutido.ts')

const versao = require('pdfjs-dist/package.json').version
const pasta = join(RAIZ, 'node_modules', 'pdfjs-dist', 'legacy', 'build')

const miolo = ler(join(pasta, 'pdf.min.mjs'), 'pdf.min.mjs')
const worker = ler(join(pasta, 'pdf.worker.min.mjs'), 'pdf.worker.min.mjs')

if (!/globalThis\.pdfjsWorker\s*=/.test(worker)) {
  throw new Error(
    'pdf.worker.min.mjs não planta mais `globalThis.pdfjsWorker`. Sem esse global o pdf.min.mjs ' +
      'tenta abrir um Web Worker de verdade e o leitor trava no carregando, sem erro. ' +
      'Reveja o caminho de fake worker antes de gerar o embutido.',
  )
}

writeFileSync(DESTINO, arquivoGerado(), 'utf8')

const total = Buffer.byteLength(miolo) + Buffer.byteLength(worker)
process.stdout.write(
  `pdfjs-embutido.ts gerado — pdf.js ${versao} (legacy)\n` +
    `  miolo  ${bytes(miolo)}\n` +
    `  worker ${bytes(worker)}\n` +
    `  soma   ${total.toLocaleString('pt-BR')} B\n` +
    `  arquivo gerado: ${Buffer.byteLength(readFileSync(DESTINO, 'utf8')).toLocaleString('pt-BR')} B\n`,
)

/* ------------------------------------------------------------------ peças */

function ler(caminho, nome) {
  const fonte = readFileSync(caminho, 'utf8')
  if (fonte.includes('</script')) {
    throw new Error(
      `${nome} contém a sequência "</script", que fecharia a tag no meio do código e ` +
        'derramaria o resto do pdf.js como texto na tela. Escape essa sequência antes de embutir.',
    )
  }
  if (!/export\s*\{[^}]*\}\s*;?\s*$/.test(fonte)) {
    throw new Error(
      `${nome} não termina mais em declaração \`export{…}\`. A forma do build mudou; ` +
        'reconfira se ele ainda pode ser incluído como <script type="module"> inline.',
    )
  }
  return fonte
}

function bytes(s) {
  return `${Buffer.byteLength(s).toLocaleString('pt-BR')} B`
}

function arquivoGerado() {
  return `/**
 * GERADO por \`scripts/embutir-pdfjs.mjs\` — não edite à mão.
 *
 * pdf.js ${versao}, build \`legacy\`, minificado. As duas strings abaixo são código-fonte
 * JavaScript que o leitor injeta como \`<script type="module">\` dentro do arquivo HTML que
 * grava em disco — nunca são avaliadas neste bundle.
 *
 * Estão embutidas de propósito: o app é usado em campo e um leitor que depende de CDN é um
 * leitor que falha sem rede. Por viverem no bundle JS, sobem por OTA — não exigem APK novo.
 *
 * Para atualizar: \`npm i -D pdfjs-dist@<versão>\` e \`npm run embutir-pdfjs\`.
 */

/** Versão do pdf.js embutido. Aparece no rodapé de erro do leitor, para diagnóstico. */
export const PDFJS_VERSAO = ${JSON.stringify(versao)}

/**
 * \`legacy/build/pdf.worker.min.mjs\`. Entra ANTES do miolo: ele planta
 * \`globalThis.pdfjsWorker\`, e é esse global que faz o pdf.js desistir de abrir um Web
 * Worker e rodar no thread principal — o caminho que funciona num documento \`file://\`.
 */
export const PDFJS_WORKER = ${JSON.stringify(worker)}

/** \`legacy/build/pdf.min.mjs\`. Expõe \`getDocument\` no escopo do módulo inline. */
export const PDFJS_MIOLO = ${JSON.stringify(miolo)}

/** Tamanho em bytes de cada peça — medido na geração, não estimado. */
export const PDFJS_BYTES = {
  worker: ${Buffer.byteLength(worker)},
  miolo: ${Buffer.byteLength(miolo)},
} as const
`
}
