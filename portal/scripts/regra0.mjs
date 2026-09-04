// REGRA 0 do Gestão Solar, verificada por máquina.
//
// Todo dado do portal vem da API. Ausência é `null` e vira "—"; nunca zero. O `tsc` não
// pega um "coalescer para zero" num campo de tela — é código válido — e foi assim que uma
// usina sem leitura já saiu como "0 kW" no app. Este script varre `src/**` e falha o
// `check` (e por tabela o `build` e o Docker) apontando arquivo:linha.
//
// Também recusa o que a regra de UI proíbe: popup nativo do navegador, número cru
// (`toFixed` em vez de `format.ts`), sorteio e dado de mentira.

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'

const RAIZ = fileURLToPath(new URL('../src', import.meta.url))

const REGRAS = [
  { nome: 'coalescer para zero', re: /(\?\?|\|\|)\s*0(?![\d.\w])/ },
  { nome: 'sorteio no lugar de dado', re: /Math\.random/ },
  { nome: 'dado de mentira', re: /\bMOCK_|\bfixture\b/i },
  { nome: 'popup nativo do navegador', re: /\bwindow\.(confirm|alert|prompt)\s*\(/ },
  { nome: 'número cru (use format.ts)', re: /\.toFixed\s*\(/ },
]

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
