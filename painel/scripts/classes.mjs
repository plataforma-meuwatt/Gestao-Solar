/**
 * Classe de componente que não existe no CSS — o defeito mais silencioso deste front.
 *
 * Em 28/09/2026 as telas novas foram escritas com `className="botao"` e
 * `className="botao-secundario"`. As classes do projeto são `btn-primario` e
 * `btn-secundario`: os botões saíram **sem estilo nenhum**, parecendo texto solto, e o
 * estado desabilitado (`disabled:opacity-40`, que vive em `.btn`) deixou de aparecer.
 * O dono clicou em "Criar gerente" e concluiu que estava quebrado.
 *
 * Nada acusa isso: o Tailwind não reclama de classe que não conhece, o TypeScript não olha
 * string de `className`, e o build passa. Só a tela mostra — se alguém abrir aquela tela.
 *
 * ## A régua, e por que ela é estreita
 *
 * O script compara os tokens de `className` com o CSS **gerado** (`dist/assets/*.css`),
 * que contém tudo: os utilitários que o Tailwind emitiu e as classes próprias do
 * `index.css`. Um token que não está lá não pinta nada.
 *
 * Só são cobrados os tokens que parecem **classe própria**: uma palavra simples, sem
 * hífen, sem dois-pontos e sem dígito (`botao`, `cartao`, `campo`). Utilitário do Tailwind
 * fica de fora de propósito — variante, valor arbitrário e classe montada em tempo de
 * execução dariam falso positivo, e um gate que grita sem razão é desligado na segunda
 * semana.
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

// `fileURLToPath` e não `URL.pathname`: o repositório mora numa pasta com ESPAÇO no nome
// ("Gestao Solar"), e o pathname o entrega como `%20` — o `readdir` então procura um
// diretório que não existe e o gate morre antes de conferir qualquer coisa.
const RAIZ = fileURLToPath(new URL('..', import.meta.url))
const DIST = join(RAIZ, 'dist', 'assets')
const SRC = join(RAIZ, 'src')

/** Palavras que aparecem em `className` e não são classe: são estado do próprio código. */
const IGNORADAS = new Set(['undefined', 'null'])

function css() {
  const arquivos = readdirSync(DIST).filter((f) => f.endsWith('.css'))
  if (arquivos.length === 0) {
    console.error('classes: não achei CSS em dist/. Rode depois do vite build.')
    process.exit(1)
  }
  return arquivos.map((f) => readFileSync(join(DIST, f), 'utf8')).join('\n')
}

function* arquivosDoSrc(dir) {
  for (const entrada of readdirSync(dir, { withFileTypes: true })) {
    const caminho = join(dir, entrada.name)
    if (entrada.isDirectory()) yield* arquivosDoSrc(caminho)
    else if (/\.tsx?$/.test(entrada.name)) yield caminho
  }
}

const folha = css()
const suspeitos = new Map()

for (const arquivo of arquivosDoSrc(SRC)) {
  const texto = readFileSync(arquivo, 'utf8')
  const linhas = texto.split('\n')
  linhas.forEach((linha, i) => {
    // `className="..."` e `className={`...`}` — os dois jeitos usados no projeto.
    for (const m of linha.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
      const bruto = (m[1] ?? m[2] ?? '').replace(/\$\{[^}]*\}/g, ' ')
      for (const token of bruto.split(/\s+/).filter(Boolean)) {
        // Só palavra simples: sem hífen, sem variante, sem número, sem valor arbitrário.
        if (!/^[a-zà-ú]+$/i.test(token)) continue
        if (IGNORADAS.has(token)) continue
        if (folha.includes(`.${token}`)) continue
        const chave = `${arquivo.replace(RAIZ, '')}:${i + 1}`
        suspeitos.set(chave, [...(suspeitos.get(chave) ?? []), token])
      }
    }
  })
}

if (suspeitos.size > 0) {
  console.error('\nClasse que não existe no CSS gerado — ela não pinta nada:\n')
  for (const [onde, tokens] of suspeitos) {
    console.error(`  ${onde}  →  ${[...new Set(tokens)].join(', ')}`)
  }
  console.error('\nAs classes próprias do projeto estão em src/index.css (btn-primario,')
  console.error('btn-secundario, btn-fantasma, cartao, campo, rotulo-campo).\n')
  process.exit(1)
}

console.log('classes: nenhuma classe própria inexistente.')
