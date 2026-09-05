/**
 * O caminho do card ao PDF desenhado — o que este arquivo guarda.
 *
 * A tela de abrir um documento recebia só `id` e `tipo`. Dizia "Relatório de Geração" sem
 * dizer de qual usina nem de qual mês, e para a peça `resumo` — que o mapa local dela não
 * conhecia — dizia **"Documento"**. Era a segunda cópia do mapa de peças (a primeira estava
 * na aba), e duas cópias dão duas respostas: o mesmo Resumo Executivo de Pereiras aparecia
 * como nome de arquivo cru numa tela e como "Documento" na outra. Medido em produção
 * (05/09/2026, usuário 2): o fechamento 36 é Pereiras, agosto/2026, e só tem essa peça —
 * então o caso do "Documento" era o caso NORMAL, não a borda.
 *
 * Antes disso havia ainda um degrau: um texto explicando que o arquivo "será baixado" e um
 * botão para baixá-lo. Dois toques para uma ação, e o segundo só existia porque o WebView
 * não desenhava PDF.
 *
 * Cada teste abaixo diz, na primeira linha, qual defeito ele impede de voltar.
 *
 * **Como rodar:** `cd app && node --test tests/relatorio-abrir.test.ts`
 *
 * O Node 24 executa TypeScript por remoção de tipos, mas **não** executa `.tsx`: JSX não é
 * anotação de tipo, é sintaxe nova. Como a régua do cabeçalho mora numa tela, o gancho
 * abaixo transpila o `.tsx` com o próprio TypeScript do projeto e troca por duplos os
 * módulos que só existem dentro do aparelho. Com isso o que se exercita é a FUNÇÃO — e não
 * uma expressão regular procurando texto no arquivo, que passa com o defeito de volta
 * assim que alguém troca as aspas de lugar.
 */

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { join } from 'node:path'
import test from 'node:test'
import { pathToFileURL } from 'node:url'

import ts from 'typescript'

const RAIZ = join(import.meta.dirname, '..', 'src')

/** Módulos que só existem dentro do aparelho — trocados por duplos inertes. */
const DUPLOS: Record<string, string> = {
  react: 'export default {}',
  'react/jsx-runtime':
    'export function jsx() { return null }\nexport function jsxs() { return null }\nexport const Fragment = null',
  'react-native': `
    export const StyleSheet = { create: (o) => o }
    export const View = 'View'
    export const Text = 'Text'
    export const Pressable = 'Pressable'
    export const Modal = 'Modal'
  `,
  'react-native-safe-area-context': 'export function useSafeAreaInsets() { return { top: 0 } }',
  'expo-router': `
    export const router = { back() {}, push() {} }
    export function useLocalSearchParams() { return {} }
    export function Redirect() { return null }
  `,
  '@/lib/cache': 'export function fetchWithCache() { return { dados: null } }',
  '@/lib/api':
    "export const baseURL = 'https://exemplo'\nexport function tokenDaSessao() { return null }\nexport function detalheEmTexto(x) { return x ?? null }",
  '@/components/LeitorPdf': 'export function LeitorPdf() { return null }',
  '@/components/base': 'export function Botao() { return null }',
  '@/theme/tokens': `
    export const cores = new Proxy({}, { get: () => '#000' })
    export const espaco = new Proxy({}, { get: () => 8 })
    export const fontes = new Proxy({}, { get: () => 'x' })
    export const TOQUE_MIN = 44
  `,
}

registerHooks({
  resolve(especificador: string, contexto: unknown, proximo: (e: string, c: unknown) => unknown) {
    if (especificador in DUPLOS) return { url: `duplo:${especificador}`, shortCircuit: true }

    // O Node exige a extensão; o TypeScript, em `moduleResolution: bundler`, exige que ela
    // NÃO esteja escrita. O gancho reconcilia os dois — e tenta `.tsx` também, porque parte
    // da régua desta entrega mora dentro de uma tela.
    const base = especificador.startsWith('@/')
      ? join(RAIZ, especificador.slice(2))
      : especificador.startsWith('.') && !/\.tsx?$/.test(especificador)
        ? join(import.meta.dirname, especificador)
        : null
    if (base) {
      const achado = ['.ts', '.tsx'].find((ext) => existsSync(`${base}${ext}`))
      if (achado) return proximo(pathToFileURL(`${base}${achado}`).href, contexto)
    }
    return proximo(especificador, contexto)
  },
  load(url: string, contexto: unknown, proximo: (u: string, c: unknown) => unknown) {
    const duplo = url.startsWith('duplo:') ? DUPLOS[url.slice(6)] : undefined
    if (duplo !== undefined) return { format: 'module', source: duplo, shortCircuit: true }
    if (url.endsWith('.tsx')) {
      return {
        format: 'module',
        source: ts.transpileModule(readFileSync(new URL(url), 'utf8'), {
          compilerOptions: {
            jsx: ts.JsxEmit.ReactJSX,
            target: ts.ScriptTarget.ES2022,
            module: ts.ModuleKind.ESNext,
          },
        }).outputText,
        shortCircuit: true,
      }
    }
    return proximo(url, contexto)
  },
})

const { cabecalhoDoRelatorio } = await import('../src/app/relatorio/[id].tsx')
const { destinoDaPonte } = await import('../src/app/documento/[id].tsx')
const { PECAS, gavetaDoRelatorio } = await import('../src/features/relatorios')

/**
 * O fechamento 36 como o BFF o entregou hoje (05/09/2026, usuário 2), copiado da medição
 * e não inventado: é o caso que produzia "Documento" na tela antiga.
 */
const DOC_36 = {
  id: 36,
  nome: 'Relatório Dashboard — Pereiras — Agosto/2026',
  usina: 'Pereiras',
  plant_id: 2,
  periodo: 'MENSAL',
  de: '2026-08-01',
  ate: '2026-08-31',
  publicado_em: '2026-09-05T12:56:07.999069Z',
  competencia: '2026-08',
  ano: null,
  arquivos: [
    { tipo: 'resumo', nome: 'Resumo Executivo - Pereiras - Agosto 2026.pdf', bytes: 43238 },
  ],
}

/** O texto do arquivo, sem os comentários — para não achar uma palavra na explicação dela. */
function fonte(...caminho: string[]): string {
  return readFileSync(join(RAIZ, ...caminho), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

/* ═══════════════════════════════════════════════ o cabeçalho diz o que está aberto ══ */

test('o cabeçalho do Resumo Executivo diz a peça, a usina e o mês', () => {
  /* Defeito que guarda: o título "Documento". A tela conhecia dois tipos de peça num acervo
     de três, e para o `resumo` caía num fallback genérico — medido em produção, o
     fechamento 36 (Pereiras, agosto/2026) só tem essa peça. */
  const c = cabecalhoDoRelatorio({ tipo: 'resumo', usina: 'Pereiras', competencia: '2026-08' })

  assert.equal(c.titulo, 'Resumo Executivo')
  assert.equal(c.subtitulo, 'Pereiras · agosto de 2026')
  assert.equal(c.completo, 'Resumo Executivo · Pereiras · agosto de 2026')
})

test('o fechamento 36, como o servidor o entrega, produz esse cabeçalho', () => {
  /* Defeito que guarda: o cabeçalho funcionar só com parâmetro escrito à mão. A lista passa
     hoje apenas `tipo`, então usina e mês vêm do acervo já lido — e é a mesma régua de
     agrupamento da lista (`gavetaDoRelatorio`) que decide o período, para o mês não ter dois
     nomes dentro do aplicativo. O registro abaixo é o medido, não um exemplo. */
  const peca = DOC_36.arquivos[0]
  const c = cabecalhoDoRelatorio({
    tipo: peca.tipo,
    nome: peca.nome,
    usina: DOC_36.usina,
    competencia: gavetaDoRelatorio(DOC_36),
  })

  assert.equal(c.completo, 'Resumo Executivo · Pereiras · agosto de 2026')
})

test('nenhum caminho do cabeçalho produz a palavra "Documento"', () => {
  /* Defeito que guarda: o fallback genérico voltar por outra porta — uma peça nova no
     monitoramento, um `tipo` vazio, um link torto. Nada disso pode virar "Documento": o
     dono não foi buscar um "documento", foi buscar um relatório com nome. */
  for (const entrada of [
    { tipo: 'resumo' },
    { tipo: 'peca-que-o-produto-nao-conhece' },
    { tipo: '' },
    { tipo: 'geracao', usina: '   ', competencia: '   ' },
    { tipo: 'paradas', nome: '' },
  ]) {
    const c = cabecalhoDoRelatorio(entrada)
    assert.doesNotMatch(c.completo, /Documento/, `entrada: ${JSON.stringify(entrada)}`)
    assert.ok(c.titulo.trim().length > 0, `título vazio para ${JSON.stringify(entrada)}`)
  }
})

test('o rótulo da peça vem de PECAS, e não de um mapa próprio desta tela', () => {
  /* Defeito que guarda: a segunda cópia do mapa. Com um mapa próprio, acrescentar uma peça
     em `features/relatorios` corrigiria a lista e deixaria esta tela mentindo — que é
     exatamente o que acontecia com o `resumo`. */
  for (const [tipo, peca] of Object.entries(PECAS) as [string, { rotulo: string }][]) {
    assert.equal(cabecalhoDoRelatorio({ tipo }).titulo, peca.rotulo)
  }
  assert.doesNotMatch(
    fonte('app', 'relatorio', '[id].tsx'),
    /geracao['"]?\s*:/,
    'a tela voltou a ter um mapa de peças próprio',
  )
})

test('peça desconhecida cai no nome que o monitoramento deu, não num genérico', () => {
  /* Defeito que guarda: engolir o nome do upstream. Quando o meuWatt publicar uma peça que
     o produto ainda não classificou, o nome do arquivo é a única verdade que existe. */
  assert.equal(
    cabecalhoDoRelatorio({ tipo: 'laudo', nome: 'Laudo Termográfico - Tiete.pdf' }).titulo,
    'Laudo Termográfico - Tiete.pdf',
  )
})

test('o ANUAL não perde o período no cabeçalho', () => {
  /* Defeito que guarda: tratar o período como mês. O ANUAL cobre doze meses e a lista o
     agrupa em `ano:2026`; um cabeçalho que só soubesse ler `YYYY-MM` abriria o relatório do
     ano sem dizer de que ano é. */
  const c = cabecalhoDoRelatorio({ tipo: 'geracao', usina: 'Tiete', competencia: 'ano:2026' })
  assert.equal(c.subtitulo, 'Tiete · ano de 2026')
})

test('sem usina e sem mês o cabeçalho encolhe, e não escreve separador sozinho', () => {
  /* Defeito que guarda: o link antigo, sem parâmetro nenhum, produzir "Relatório de Geração
     ·  · " — pontuação anunciando um dado que não existe. */
  const c = cabecalhoDoRelatorio({ tipo: 'geracao' })
  assert.equal(c.titulo, 'Relatório de Geração')
  assert.equal(c.subtitulo, null)
  assert.equal(c.completo, 'Relatório de Geração')
})

test('a usina sozinha, sem o mês, não arrasta um separador vazio', () => {
  /* Defeito que guarda: juntar uma lista com buraco no meio. */
  assert.equal(
    cabecalhoDoRelatorio({ tipo: 'geracao', usina: 'Pereiras' }).completo,
    'Relatório de Geração · Pereiras',
  )
})

/* ════════════════════════════════════════════════════ um toque, e o mesmo leitor ══ */

test('a tela do relatório desenha o PDF ela mesma — não há degrau intermediário', () => {
  /* Defeito que guarda: o degrau. A tela antiga mostrava "O documento será baixado e aberto
     no leitor de PDF do seu aparelho" e um botão "Abrir documento": dois toques para uma
     ação, e o segundo só existia porque o desenho era impossível. */
  const tela = fonte('app', 'relatorio', '[id].tsx')

  assert.match(tela, /<LeitorPdf/, 'a tela precisa montar o leitor')
  assert.doesNotMatch(tela, /será baixado/)
  assert.doesNotMatch(tela, /Abrir documento/)
  // O leitor já tem o seu "Abrir em outro app" por dentro; esta tela não pode ter um botão
  // que PRECEDE o desenho — era ele o segundo toque.
  assert.doesNotMatch(tela, /<Botao/)
})

test('o botão de PDF da OS e da tarefa abre o MESMO leitor', () => {
  /* Defeito que guarda: a terceira cópia do caminho do PDF. Já houve duas — este componente
     e a tela de documento —, com o mesmo defeito nas duas, e foi por isso que o transporte
     virou `lib/pdf.ts`. O desenho não pode repetir a história. */
  const botao = fonte('components', 'AbrirPdf.tsx')

  assert.match(botao, /import \{ LeitorPdf \} from '@\/components\/LeitorPdf'/)
  assert.match(botao, /<LeitorPdf/)
  // `abrirPdf` baixa e entrega ao sistema sem nunca desenhar: quem o chama daqui está
  // saindo do aplicativo de novo.
  assert.doesNotMatch(botao, /abrirPdf/)
})

test('o botão de PDF não muda de contrato — três telas de fora dependem dele', () => {
  /* Defeito que guarda: trocar as propriedades junto com o destino. OS, tarefa e cronograma
     chamam `AbrirPdf` e não são desta entrega; um `titulo` que virasse `nome` quebraria as
     três de uma vez. */
  const botao = fonte('components', 'AbrirPdf.tsx')
  for (const propriedade of ['url', 'arquivo', 'titulo', 'rotulo']) {
    assert.match(botao, new RegExp(`\\b${propriedade}\\b`), `sumiu a propriedade ${propriedade}`)
  }

  for (const [pasta, arquivo] of [
    ['os', '[id].tsx'],
    ['tarefa', '[id].tsx'],
    ['cronograma', '[usinaId].tsx'],
  ]) {
    const chamador = fonte('app', pasta, arquivo)
    assert.match(chamador, /<AbrirPdf/, `${pasta} deixou de usar o botão`)
    assert.match(chamador, /url=\{/, `${pasta} parou de passar a url`)
  }
})

test('o leitor só nasce depois do toque', () => {
  /* Defeito que guarda: montar o `LeitorPdf` sempre. Ele baixa o PDF ao aparecer na árvore —
     e a de OS é a tela que o técnico abre com a rede do sítio. Toda ordem de serviço puxaria
     megabytes que ninguém pediu. */
  const botao = fonte('components', 'AbrirPdf.tsx')
  assert.match(botao, /visible=\{aberto\}/, 'o leitor precisa viver dentro da folha condicional')
})

/* ═══════════════════════════════════════════════════════════ a ponte não se perde ══ */

test('o endereço antigo leva ao novo preservando os parâmetros', () => {
  /* Defeito que guarda: a rota morta. O nome do arquivo É a rota no expo-router; renomear a
     tela sem deixar ponte transforma `/documento/36?tipo=resumo`, que alguém guardou, num
     erro. E uma ponte que esquecesse `tipo` seria PIOR que a rota morta: levaria à peça
     errada — medido, o fechamento 36 só tem o Resumo, e pedir `geracao` nele responde 404. */
  const ponte = fonte('app', 'documento', '[id].tsx')

  assert.equal(destinoDaPonte({ id: '36', tipo: 'resumo' }), '/relatorio/36?tipo=resumo')

  assert.match(ponte, /<Redirect/, 'a ponte precisa redirecionar')
  assert.doesNotMatch(ponte, /router\.replace/, 'replace num efeito pisca uma tela vazia antes')
})

test('a ponte repassa parâmetro que ela nem conhece', () => {
  /* Defeito que guarda: a ponte com uma lista de nomes escrita à mão. A lista pode ganhar um
     parâmetro amanhã — e uma ponte que só soubesse copiar `tipo` o largaria em silêncio,
     entregando à tela nova menos do que o endereço trazia. */
  assert.equal(
    destinoDaPonte({ id: '36', tipo: 'resumo', usina: 'Pereiras', competencia: '2026-08' }),
    '/relatorio/36?tipo=resumo&usina=Pereiras&competencia=2026-08',
  )
})

test('a ponte sem parâmetro nenhum não inventa uma interrogação', () => {
  /* Defeito que guarda: `/relatorio/36?` — endereço com cauda vazia, que suja o histórico e
     não é o mesmo endereço que a tela geraria. */
  assert.equal(destinoDaPonte({ id: '36' }), '/relatorio/36')
})

test('a ponte escapa o que vem da URL', () => {
  /* Defeito que guarda: concatenar texto de fora direto no endereço. Um valor com `&` ou
     espaço partiria a URL em dois parâmetros e a tela leria a peça errada. */
  assert.equal(
    destinoDaPonte({ id: '36', usina: 'Ouro Fino & Cia' }),
    '/relatorio/36?usina=Ouro+Fino+%26+Cia',
  )
})

test('a ponte não desenha nada — ela é só um desvio', () => {
  /* Defeito que guarda: a ponte virar uma segunda tela de leitura, com cabeçalho e leitor
     duplicados dentro dela. */
  const ponte = fonte('app', 'documento', '[id].tsx')
  assert.doesNotMatch(ponte, /LeitorPdf|StyleSheet/)
})
