/**
 * O que este arquivo guarda: a página que o leitor de PDF interno grava em disco.
 *
 * O leitor não pode ser conferido a olho num teste — quem desenha é o motor do WebView,
 * que não existe no Node. O que PODE ser conferido, e é onde moram os defeitos caros, é a
 * **montagem** da página: a ordem dos blocos, o escopo em que cada um cai, o que sobra
 * dentro do arquivo e o que nunca pode sobrar. Cada teste abaixo diz, na primeira linha,
 * qual defeito ele impede de voltar.
 *
 * **Como rodar** (sem dependência nova, sem instalação):
 *
 * ```
 * cd app && node --test tests/leitor-pdf.test.ts
 * ```
 *
 * O Node 24 executa TypeScript por remoção de tipos. O que ele não sabe fazer é resolver o
 * apelido `@/…` do Metro nem carregar `expo-file-system`/`expo-sharing`, que são módulos
 * nativos — daí os ganchos abaixo, que resolvem o apelido para o arquivo real e trocam SÓ
 * o que é do aparelho por duplos. Ninguém aqui testa o aparelho: testa-se a montagem, que
 * é texto e ordem.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { join } from 'node:path'
import test from 'node:test'
import { pathToFileURL } from 'node:url'

const RAIZ = join(import.meta.dirname, '..', 'src')

/**
 * O duplo de `expo-file-system`. Anota tudo o que aconteceu com o arquivo — é assim que
 * se prova que a gravação foi em *append* e que o arquivo velho foi apagado antes.
 */
const DUPLO_FS = `
export const registro = { escritas: [], apagados: [], criados: [] }
export const Paths = { cache: '/cache' }
export class File {
  constructor(...partes) {
    this.uri = partes.map((p) => (typeof p === 'string' ? p : p.cache ?? p.uri)).join('/')
    this.name = String(partes[partes.length - 1])
    this.exists = File.__existentes.has(this.uri)
    this.__base64 = File.__conteudo.get(this.uri) ?? ''
  }
  static __existentes = new Set()
  static __conteudo = new Map()
  base64Sync() { return this.__base64 }
  create() { registro.criados.push(this.uri) }
  delete() { registro.apagados.push(this.uri) }
  write(conteudo, opcoes) {
    registro.escritas.push({ uri: this.uri, conteudo, append: opcoes?.append ?? false })
  }
}
`

registerHooks({
  resolve(especificador: string, contexto: unknown, proximo: (e: string, c: unknown) => unknown) {
    if (especificador === 'expo-file-system') return { url: 'duplo:fs', shortCircuit: true }
    if (especificador === 'expo-sharing') return { url: 'duplo:sharing', shortCircuit: true }
    // `@/lib/api` arrasta axios, zustand e o armazenamento seguro. O leitor não usa nada
    // disso na montagem da página; só o download usa, e download não se testa aqui.
    if (especificador === '@/lib/api') return { url: 'duplo:api', shortCircuit: true }
    if (especificador.startsWith('@/')) {
      return proximo(pathToFileURL(join(RAIZ, `${especificador.slice(2)}.ts`)).href, contexto)
    }
    return proximo(especificador, contexto)
  },
  load(url: string, contexto: unknown, proximo: (u: string, c: unknown) => unknown) {
    if (url === 'duplo:fs') return { format: 'module', source: DUPLO_FS, shortCircuit: true }
    if (url === 'duplo:sharing') {
      return {
        format: 'module',
        source: 'export async function isAvailableAsync(){return true}\nexport async function shareAsync(){}',
        shortCircuit: true,
      }
    }
    if (url === 'duplo:api') {
      return {
        format: 'module',
        source: 'export function tokenDaSessao(){return "TOKEN-DE-TESTE"}\nexport function detalheEmTexto(d){return typeof d === "string" ? d : null}',
        shortCircuit: true,
      }
    }
    return proximo(url, contexto)
  },
})

const { pedacosDaPaginaDoLeitor, escreverPaginaDoLeitor, TETO_LEITOR_BYTES } = await import(
  '@/lib/pdf'
)
const { PDFJS_MIOLO, PDFJS_WORKER, PDFJS_BYTES, PDFJS_VERSAO } = await import(
  '@/lib/pdfjs-embutido'
)
const FS = (await import('expo-file-system')) as unknown as {
  registro: {
    escritas: { uri: string; conteudo: string; append: boolean }[]
    apagados: string[]
    criados: string[]
  }
  File: {
    new (...p: unknown[]): { uri: string; name: string; base64Sync(): string }
    __existentes: Set<string>
    __conteudo: Map<string, string>
  }
}

/** Um PDF minúsculo de verdade, em base64 — serve de carga sem depender de rede. */
const PDF_BASE64 = Buffer.from(
  '%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n',
).toString('base64')

function pagina(): string {
  return pedacosDaPaginaDoLeitor(PDF_BASE64).join('')
}

/* ------------------------------------------------------------ a montagem */

test('o worker do pdf.js entra ANTES do miolo', () => {
  /**
   * Defeito guardado: invertida a ordem, `globalThis.pdfjsWorker` ainda não existe quando o
   * miolo é avaliado — e o pdf.js tenta abrir um Web Worker de verdade, que num documento
   * `file://` não sobe. O `getDocument` fica pendurado para sempre, sem erro nenhum: a tela
   * no "carregando" até o relógio de segurança desistir.
   */
  const pedacos = pedacosDaPaginaDoLeitor(PDF_BASE64)
  const posWorker = pedacos.indexOf(PDFJS_WORKER)
  const posMiolo = pedacos.indexOf(PDFJS_MIOLO)
  assert.ok(posWorker >= 0, 'o worker precisa estar na página')
  assert.ok(posMiolo >= 0, 'o miolo precisa estar na página')
  assert.ok(posWorker < posMiolo, 'o worker tem de vir antes do miolo')
})

test('o worker embutido planta `globalThis.pdfjsWorker`', () => {
  /**
   * Defeito guardado: é esse global — e só ele — que faz o pdf.js DESISTIR do Web Worker e
   * rodar no thread principal. Uma versão do pdfjs-dist que pare de plantá-lo passaria pelo
   * compilador e pelo olho, e quebraria o leitor em campo.
   */
  assert.match(PDFJS_WORKER, /globalThis\.pdfjsWorker\s*=/)
})

test('o visualizador cai no MESMO bloco de módulo do miolo', () => {
  /**
   * Defeito guardado: em bloco separado, o visualizador não enxerga `getDocument` (cada
   * módulo tem escopo próprio) e morre com "getDocument is not defined" na primeira linha
   * útil — um erro que só aparece no aparelho.
   */
  const html = pagina()
  const depoisDoMiolo = html.slice(html.indexOf(PDFJS_MIOLO) + PDFJS_MIOLO.length)
  const fechamento = depoisDoMiolo.indexOf('</scr' + 'ipt>')
  assert.ok(fechamento > 0, 'o bloco do miolo precisa fechar')
  assert.ok(
    depoisDoMiolo.slice(0, fechamento).includes('getDocument({ data: bytes'),
    'o visualizador tem de estar dentro do mesmo bloco, antes do fechamento',
  )
})

test('os bytes do PDF viajam num bloco que não é JavaScript', () => {
  /**
   * Defeito guardado: base64 dentro de `<script>` executável vira código a ser analisado —
   * megabytes de "sintaxe inválida" que derrubam o bloco inteiro. Aqui ele vai num tipo que
   * o motor não executa, e é lido por `textContent`.
   */
  const html = pagina()
  assert.ok(html.includes('<scr' + 'ipt type="application/base64" id="pdf">'))
  assert.ok(html.includes(`>${PDF_BASE64}<`), 'o base64 tem de estar dentro do bloco, intacto')
})

test('o base64 chega ao outro lado byte a byte', () => {
  /**
   * Defeito guardado: qualquer escape, quebra de linha ou `trim` mal colocado no meio do
   * caminho corromperia o PDF — e o sintoma seria "arquivo inválido" para um arquivo que
   * está perfeito em disco.
   */
  const html = pagina()
  const abertura = '<scr' + 'ipt type="application/base64" id="pdf">'
  const inicio = html.indexOf(abertura) + abertura.length
  const fim = html.indexOf('</scr' + 'ipt>', inicio)
  const devolta = Buffer.from(html.slice(inicio, fim).trim(), 'base64')
  assert.deepEqual(devolta, Buffer.from(PDF_BASE64, 'base64'))
})

test('a rede de segurança é instalada antes de qualquer bloco de módulo', () => {
  /**
   * Defeito guardado: erro de SINTAXE dentro de `<script type="module">` não é pego por
   * try/catch nenhum — nem pelo que estivesse dentro do próprio módulo. Sem um `onerror`
   * clássico instalado antes, a página morre calada e a tela fica no "carregando" para
   * sempre. Foi assim que a tentativa anterior de WebView falhou em silêncio.
   */
  const html = pagina()
  const posRede = html.indexOf("window.addEventListener('error'")
  const posModulo = html.indexOf('type="module"')
  assert.ok(posRede > 0, 'a rede de segurança precisa existir')
  assert.ok(posRede < posModulo, 'ela tem de vir antes do primeiro módulo')
  assert.ok(html.includes("window.addEventListener('unhandledrejection'"))
})

test('o veredito só é postado depois que a página foi de fato desenhada', () => {
  /**
   * Defeito guardado: postar o veredito antes do `render` seria repetir o `onLoadEnd` —
   * a tela sai do carregando e o dono olha uma folha branca. O `pagina-pronta` tem de vir
   * DEPOIS do `await …render(…).promise`.
   */
  const html = pagina()
  const posRender = html.indexOf('.render({ canvasContext')
  const posAviso = html.indexOf("tipo: 'pagina-pronta'")
  assert.ok(posRender > 0 && posAviso > 0)
  assert.ok(posRender < posAviso, 'o aviso de página pronta tem de vir depois do desenho')
  assert.ok(html.includes("tipo: 'render-completo'"))
  assert.ok(html.includes("tipo: 'erro'"), 'o caminho de erro também tem de postar veredito')
})

test('nada do pdf.js contém a sequência que fecharia a tag no meio do código', () => {
  /**
   * Defeito guardado: um `</script` dentro do código embutido fecharia o bloco ali, e o
   * resto do pdf.js apareceria como texto cru na tela do dono. É invariante do pacote
   * instalado, e por isso é conferido aqui e também na geração.
   */
  assert.ok(!PDFJS_MIOLO.includes('</scr' + 'ipt'))
  assert.ok(!PDFJS_WORKER.includes('</scr' + 'ipt'))
})

test('a página não carrega nada de fora — nem CDN, nem arquivo vizinho', () => {
  /**
   * Defeito guardado: offline primeiro. Um `src=` apontando para a internet faria o leitor
   * depender de rede justamente em campo, que é onde ele precisa funcionar; e um `src=`
   * apontando para um arquivo vizinho falharia calado, porque o WebView é montado sem
   * acesso ao disco de propósito.
   *
   * A conferência de endereço externo é feita sobre o que NÓS escrevemos — o pdf.js carrega
   * endereços na própria tabela de textos e policiá-los seria falso rigor. O que prova que
   * nada é buscado é a ausência de `src=`/`<link` na página e a presença do global que faz
   * o motor desistir de abrir um Worker (conferida em teste próprio).
   */
  const html = pagina()
  assert.ok(!/<scr.pt[^>]*\ssrc=/i.test(html), 'nenhum bloco com `src`')
  assert.ok(!/<link\b/i.test(html), 'nenhuma folha de estilo externa')

  const nosso = pedacosDaPaginaDoLeitor(PDF_BASE64)
    .filter((p) => p !== PDFJS_MIOLO && p !== PDFJS_WORKER && p !== PDF_BASE64)
    .join('')
  assert.ok(!nosso.includes('://'), 'nada que escrevemos aponta para fora')
  assert.ok(!/\bfetch\s*\(|\bimport\s*\(/.test(nosso), 'o visualizador não busca nada')
})

test('nenhum segredo sobra dentro do arquivo gravado em disco', () => {
  /**
   * Defeito guardado: o caminho antigo apontaria o WebView para a URL autenticada do BFF, e
   * URL vai para log. Aqui o WebView só vê um arquivo local — então nem o token nem o
   * endereço podem aparecer no HTML.
   */
  const html = pagina()
  assert.ok(!html.includes('TOKEN-DE-TESTE'))
  assert.ok(!html.toLowerCase().includes('bearer'))
  assert.ok(!html.includes('/api/v1/'))
})

/* ------------------------------------------------------------- a gravação */

test('a gravação é em pedaços, com o primeiro sobrescrevendo e o resto em append', () => {
  /**
   * Defeito guardado: se todas as escritas fossem sobrescrita, só o último pedaço
   * sobreviveria e o arquivo seria `</body></html>` — folha branca com o motor inteiro
   * perdido. Se todas fossem append, o HTML de um documento anterior ficaria colado na
   * frente do novo.
   */
  FS.registro.escritas.length = 0
  FS.registro.apagados.length = 0
  FS.File.__conteudo.set('/cache/doc.pdf', PDF_BASE64)
  const pdf = new FS.File('/cache', 'doc.pdf')

  escreverPaginaDoLeitor(pdf as never)

  const escritas = FS.registro.escritas
  assert.ok(escritas.length > 3, 'a página é gravada em pedaços, não numa string só')
  assert.equal(escritas[0].append, false, 'o primeiro pedaço sobrescreve')
  assert.ok(
    escritas.slice(1).every((e) => e.append),
    'todos os demais são append',
  )
  assert.ok(
    escritas.some((e) => e.conteudo === PDF_BASE64),
    'o base64 é um pedaço próprio — nunca concatenado com o resto',
  )
})

test('o HTML de um documento anterior é apagado antes de gravar o novo', () => {
  /**
   * Defeito guardado: reaproveitar o arquivo faria o leitor abrir o documento de ontem —
   * o mesmo motivo pelo qual o download já apaga o PDF homônimo antes de gravar.
   */
  FS.registro.apagados.length = 0
  const nome = '/cache/doc.pdf.leitor.html'
  FS.File.__existentes.add(nome)
  escreverPaginaDoLeitor(new FS.File('/cache', 'doc.pdf') as never)
  assert.ok(FS.registro.apagados.includes(nome))
  FS.File.__existentes.delete(nome)
})

/* ---------------------------------------------------------------- limites */

test('o teto do leitor interno é declarado, e é o do aplicativo externo que segue depois', () => {
  /**
   * Defeito guardado: sem teto, um pacote de fichas de 24 MB viraria ~32 MB de base64 mais a
   * cópia decodificada dentro do WebView — memória que o Android reclama matando o
   * aplicativo. O teto existe para a tela DIZER por que mandou para fora, em vez de travar.
   */
  assert.equal(TETO_LEITOR_BYTES, 15 * 1024 * 1024)
})

test('as duas peças do pdf.js estão inteiras e do tamanho medido na geração', () => {
  /**
   * Defeito guardado: um `pdfjs-embutido.ts` truncado (edição à mão, merge malfeito) daria
   * um leitor que falha só em certos PDFs. Os bytes são conferidos contra o que o gerador
   * mediu, e o gerado contra o pacote instalado.
   */
  assert.equal(Buffer.byteLength(PDFJS_MIOLO), PDFJS_BYTES.miolo)
  assert.equal(Buffer.byteLength(PDFJS_WORKER), PDFJS_BYTES.worker)

  const pasta = join(import.meta.dirname, '..', 'node_modules', 'pdfjs-dist', 'legacy', 'build')
  assert.equal(readFileSync(join(pasta, 'pdf.min.mjs'), 'utf8'), PDFJS_MIOLO)
  assert.equal(readFileSync(join(pasta, 'pdf.worker.min.mjs'), 'utf8'), PDFJS_WORKER)
  assert.equal(
    PDFJS_VERSAO,
    JSON.parse(
      readFileSync(join(import.meta.dirname, '..', 'node_modules', 'pdfjs-dist', 'package.json'), 'utf8'),
    ).version,
  )
})
