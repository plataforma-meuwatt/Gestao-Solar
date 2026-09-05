// REGRA 0 do Gestão Solar, verificada por máquina.
//
// Todo dado do portal vem da API. Ausência é `null` e vira "—"; nunca zero. O `tsc` não
// pega um "coalescer para zero" num campo de tela — é código válido — e foi assim que uma
// usina sem leitura já saiu como "0 kW" no app. Este script varre `src/**` e falha o
// `check` (e por tabela o `build` e o Docker) apontando arquivo:linha.
//
// Também recusa o que a regra de UI proíbe: popup nativo do navegador, número cru
// (`toFixed` em vez de `format.ts`), sorteio e dado de mentira.
//
// E recusa uma armadilha do Tailwind que já custou uma tela inteira: o modificador de
// opacidade (`/40`) sobre um token de cor declarado como `rgba(...)` **substitui** o alfa
// do token em vez de multiplicá-lo. `bg-superficie-alta/40`, sobre um token que vale
// `rgba(255,255,255,0.08)`, emite `rgba(255,255,255,0.4)` — cinco vezes o alfa declarado e
// mais de três vezes o da superfície mais clara do design system (0,12). Foi assim que o
// Cronograma abriu com quinze faixas de cinza chapado ocupando 94 % da altura da tabela,
// sem que nenhum `tsc` ou revisão de diff tivesse como perceber: a classe é válida, o token
// existe, e o resultado só aparece no navegador. Os tokens `tom-*` são hexadecimais e não
// sofrem disso — `bg-tom-ok/10` continua legítimo e é a receita da marca.
//
// EXCEÇÃO DECLARADA: uma linha terminada em `// regra0: <motivo>` passa. Existe porque nem
// todo número é dado de negócio — coordenada de SVG e largura medida do layout não vêm da
// API e não representam medição nenhuma. Exigir o motivo escrito é o que separa a exceção
// legítima do atalho: quem burla tem de dizer por quê, e quem revisa lê a frase.

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'

const RAIZ = fileURLToPath(new URL('../src', import.meta.url))

/**
 * Os tokens de cor declarados como `rgba(...)` no `tailwind.config.js`, lidos do próprio
 * arquivo — e não copiados para cá. Copiar a lista deixaria a regra desatualizada no dia em
 * que alguém acrescentasse um token novo, que é justamente o dia em que ela faria falta.
 */
function tokensRgba(cores, prefixo = '') {
  const nomes = []
  for (const [chave, valor] of Object.entries(cores ?? {})) {
    const nome = prefixo ? `${prefixo}-${chave}` : chave
    if (typeof valor === 'string') {
      if (/^rgba\(/i.test(valor.trim())) nomes.push(nome)
    } else if (valor && typeof valor === 'object') {
      nomes.push(...tokensRgba(valor, nome))
    }
  }
  return nomes
}

const CONFIG = (await import(new URL('../tailwind.config.js', import.meta.url).href)).default
// Mais longo primeiro: sem isso `borda` casaria antes de `borda-fraca` e a alternância
// pararia no prefixo, deixando `border-borda-fraca/40` passar.
const TOKENS_RGBA = tokensRgba(CONFIG?.theme?.extend?.colors).sort((a, b) => b.length - a.length)

const REGRAS = [
  { nome: 'coalescer para zero', re: /(\?\?|\|\|)\s*0(?![\d.\w])/ },
  { nome: 'sorteio no lugar de dado', re: /Math\.random/ },
  { nome: 'dado de mentira', re: /\bMOCK_|\bfixture\b/i },
  { nome: 'popup nativo do navegador', re: /\bwindow\.(confirm|alert|prompt)\s*\(/ },
  { nome: 'número cru (use format.ts)', re: /\.toFixed\s*\(/ },
]

if (TOKENS_RGBA.length) {
  REGRAS.push({
    nome: 'alfa de token rgba trocado pelo modificador /NN (use o token puro)',
    re: new RegExp(`\\b(?:bg|border|text|ring|divide|outline)-(?:${TOKENS_RGBA.join('|')})\\/\\d`),
  })
}

function* arquivos(dir) {
  for (const nome of readdirSync(dir)) {
    const caminho = join(dir, nome)
    if (statSync(caminho).isDirectory()) yield* arquivos(caminho)
    else if (/\.(ts|tsx)$/.test(nome)) yield caminho
  }
}

const achados = []
for (const arquivo of arquivos(RAIZ)) {
  const linhas = readFileSync(arquivo, 'utf8').split('\n')
  linhas.forEach((linha, i) => {
    // A exceção vale para a linha inteira: quem a declara assume as regras dela.
    if (/\/\/\s*regra0:\s*\S/.test(linha)) return
    for (const regra of REGRAS) {
      if (regra.re.test(linha)) {
        achados.push(
          `${relative(process.cwd(), arquivo)}:${i + 1}  ${regra.nome}  ->  ${linha.trim()}`,
        )
      }
    }
  })
}

if (achados.length) {
  console.error('REGRA 0 violada:')
  for (const a of achados) console.error('  ' + a)
  process.exit(1)
}
console.log('regra 0: ok')
