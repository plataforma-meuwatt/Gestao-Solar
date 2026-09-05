/**
 * O que este arquivo guarda — a aba Relatórios, defeito por defeito.
 *
 * Cada teste diz, na primeira linha, qual defeito ele impede de voltar. Os quatro que
 * motivaram o arquivo, todos medidos contra produção em 05/09/2026 (usuário 2, 7 usinas,
 * 6 fechamentos no acervo):
 *
 * 1. **O mês do relatório saía da PUBLICAÇÃO.** Os fechamentos 35 (Porto Ferreira) e 36
 *    (Pereiras) cobrem agosto e foram publicados em 05/09 — a lista vem ordenada por
 *    `publicado_em`, e agrupar pelo mesmo campo poria agosto na gaveta de setembro.
 * 2. **`new Date('2026-08-01')`** é meia-noite UTC: no Brasil o mês responde julho. O corte
 *    é por fatia de string, e o teste de fonte proíbe `new Date` neste módulo.
 * 3. **O mapa das peças estava duplicado** em dois arquivos, com duas entradas cada,
 *    enquanto o acervo já tem três: o Resumo Executivo aparecia com o nome de arquivo cru
 *    na lista e como "Documento" na tela de abrir.
 * 4. **A chave de cache** é `'documents'` e não pode acompanhar o rótulo: ela vira nome de
 *    arquivo em disco (`u2__documents.json`) e trocá-la órfã o cache de todo celular
 *    instalado — na tela de quem está no campo.
 *
 * **Como rodar** (sem dependência nova):
 *
 * ```
 * cd app && node --test tests/relatorios.test.ts
 * ```
 *
 * O Node 24 executa TypeScript por remoção de tipos. O que ele não sabe é resolver o
 * apelido `@/…` do Metro nem carregar `lib/api`/`lib/cache`, que arrastam axios,
 * expo-constants e o React Native inteiro — daí os ganchos abaixo, que resolvem o apelido
 * e trocam SÓ esses dois módulos por duplos. Ninguém aqui testa rede: o que se testa é a
 * régua, que é texto e aritmética.
 */

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { join } from 'node:path'
import { describe, test } from 'node:test'
import { pathToFileURL } from 'node:url'

const APP = join(import.meta.dirname, '..')
const RAIZ = join(APP, 'src')
const BFF = join(APP, '..', 'bff', 'app', 'api', 'v1')

registerHooks({
  resolve(especificador: string, contexto: unknown, proximo: (e: string, c: unknown) => unknown) {
    if (especificador === '@/lib/cache' || especificador === '@/lib/api') {
      return { url: `duplo:${especificador.slice(6)}`, shortCircuit: true }
    }
    if (especificador.startsWith('@/')) {
      return proximo(pathToFileURL(join(RAIZ, `${especificador.slice(2)}.ts`)).href, contexto)
    }
    if (especificador.startsWith('.') && !especificador.endsWith('.ts')) {
      return proximo(`${especificador}.ts`, contexto)
    }
    return proximo(especificador, contexto)
  },
  load(url: string, contexto: unknown, proximo: (u: string, c: unknown) => unknown) {
    if (url === 'duplo:cache') {
      return {
        format: 'module',
        source: 'export function fetchWithCache() { return null }',
        shortCircuit: true,
      }
    }
    if (url === 'duplo:api') {
      return {
        format: 'module',
        source: "export const baseURL = 'https://exemplo'\nexport const api = {}",
        shortCircuit: true,
      }
    }
    return proximo(url, contexto)
  },
})

const {
  agruparPorGaveta,
  CAMPOS_LIDOS,
  detalheDaPeca,
  frasePecaAusente,
  gavetaDoRelatorio,
  mesDoRelatorio,
  PECAS,
  peso,
  recorte,
  rotuloDaGaveta,
  rotuloDaPeca,
  subtituloDaAba,
  urlDoArquivo,
  vazioDaLista,
} = await import('../src/features/relatorios.ts')
type Relatorio = import('../src/features/relatorios.ts').Relatorio

const fonte = (rel: string) => readFileSync(join(APP, rel), 'utf8')

/* ------------------------------------------------------------------ auxílio */

/** Um relatório do acervo, com só o que cada teste precisa dizer. */
function rel(campos: Partial<Relatorio> & Pick<Relatorio, 'id' | 'usina' | 'de'>): Relatorio {
  return {
    nome: `Relatório ${campos.id}`,
    plant_id: null,
    periodo: 'MENSAL',
    ate: campos.de,
    publicado_em: `${campos.de}T12:00:00`,
    competencia: campos.de.slice(0, 7),
    ano: null,
    arquivos: [],
    ...campos,
  }
}

/**
 * O acervo REAL, medido em 05/09/2026 e na ordem em que o servidor o entrega (publicação
 * mais recente primeiro). Fixture inventada esconderia justamente o caso 35/36.
 */
const ACERVO: Relatorio[] = [
  rel({
    id: 35,
    usina: 'Porto Ferreira',
    plant_id: 4,
    de: '2026-08-01',
    ate: '2026-08-31',
    publicado_em: '2026-09-05T13:07:00',
    competencia: '2026-08',
    nome: 'Relatório Mensal — Agosto 2026',
    arquivos: [
      { tipo: 'geracao', nome: 'Relatorio-Geracao - Porto Ferreira.pdf', bytes: 2686172 },
      { tipo: 'paradas', nome: 'Anexo-Paradas - Porto Ferreira - Agosto.pdf', bytes: 2604352 },
    ],
  }),
  rel({
    id: 36,
    usina: 'Pereiras',
    plant_id: 2,
    de: '2026-08-01',
    ate: '2026-08-31',
    publicado_em: '2026-09-05T13:09:00',
    competencia: '2026-08',
    arquivos: [
      { tipo: 'resumo', nome: 'Resumo Executivo - Pereiras - Agosto 2026.pdf', bytes: 43238 },
    ],
  }),
  rel({ id: 15, usina: 'Tiete', plant_id: 5, de: '2026-05-01', publicado_em: '2026-06-15T10:00:00' }),
  rel({ id: 16, usina: 'Ouro Fino', plant_id: 1, de: '2026-05-01', publicado_em: '2026-06-15T10:00:00' }),
  rel({ id: 17, usina: 'Pirapozinho', plant_id: 3, de: '2026-05-01', publicado_em: '2026-06-15T10:00:00' }),
  rel({ id: 18, usina: 'Pereiras', plant_id: 2, de: '2026-05-01', publicado_em: '2026-06-15T10:00:00' }),
]

/* ══════════════════════════════════════════════════════════════════════════
 * 1. CONTRATO — o campo que a tela lê ainda existe do outro lado?
 * ═════════════════════════════════════════════════════════════════════════ */

/**
 * Os campos de cada modelo Pydantic de `documents.py`.
 *
 * Reconhece as DUAS formas, e a segunda é o ponto: `competencia` e `ano` são
 * `@computed_field` — `def competencia(self)`, não `competencia:`. Um parser que só
 * enxergasse a declaração de atributo daria o contrato por quebrado no dia em que ele está
 * certo, e alguém "consertaria" o teste apagando a checagem.
 */
function camposPorModelo(arquivo: string): Map<string, Set<string>> {
  const linhas = readFileSync(join(BFF, `${arquivo}.py`), 'utf8').split('\n')
  const saida = new Map<string, Set<string>>()
  let atual: Set<string> | null = null
  for (const linha of linhas) {
    const cabecalho = /^class ([A-Za-z_]\w*)\(BaseModel\):/.exec(linha)
    if (cabecalho) {
      atual = new Set<string>()
      saida.set(cabecalho[1], atual)
      continue
    }
    if (atual === null) continue
    // O bloco termina na primeira linha que volta à coluna zero, senão o corpo "vaza"
    // para o código de módulo e argumentos de função entram como campos.
    if (linha.trim() !== '' && !/^\s/.test(linha)) {
      atual = null
      continue
    }
    const campo = /^ {4}([a-z_]\w*)\s*:/.exec(linha)
    if (campo) atual.add(campo[1])
    const derivado = /^ {4}def ([a-z_]\w*)\(self/.exec(linha)
    if (derivado) atual.add(derivado[1])
  }
  return saida
}

describe('contrato com o BFF', () => {
  test('o arquivo do BFF está onde este teste espera', () => {
    // Teste de contrato que se auto-desliga quando não acha o outro lado não guarda nada.
    assert.ok(
      existsSync(join(BFF, 'documents.py')),
      `não achei documents.py em ${BFF} — o contrato não pode ser conferido sem ele`,
    )
  })

  const modelos = camposPorModelo('documents')

  for (const [modelo, campos] of Object.entries(CAMPOS_LIDOS)) {
    test(`${modelo} — todo campo que a aba lê existe no modelo do BFF`, () => {
      const doServidor = modelos.get(modelo)
      assert.ok(doServidor, `documents.py não declara ${modelo}`)
      for (const campo of campos) {
        assert.ok(
          doServidor.has(campo),
          `${modelo}.${campo} sumiu do BFF — a aba Relatórios lê esse campo`,
        )
      }
    })
  }

  test('o defeito nomeado: o eixo do mês e o peso do arquivo vêm do servidor', () => {
    // `competencia` é a régua do mês, e ela mora no servidor de propósito: derivada de
    // `de`, não há como divergir dele. `bytes` é o peso — o upstream sempre mandou e o
    // BFF jogava fora, e é o que separa 43 KB de 2,7 MB para quem está no 3G.
    const documento = modelos.get('DocumentoOut')
    const arquivo = modelos.get('ArquivoOut')
    assert.ok(documento?.has('competencia'), 'DocumentoOut perdeu `competencia`')
    assert.ok(documento?.has('ano'), 'DocumentoOut perdeu `ano`')
    assert.ok(arquivo?.has('bytes'), 'ArquivoOut perdeu `bytes`')
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 2. O EIXO DO MÊS — competência, nunca publicação; string, nunca Date
 * ═════════════════════════════════════════════════════════════════════════ */

describe('o mês do relatório', () => {
  test('o defeito medido: agosto publicado em setembro fica em AGOSTO', () => {
    // Os fechamentos 35 e 36, de produção. Se o mês voltar a sair de `publicado_em`, os
    // dois caem em setembro e o dono não acha o relatório do mês que foi procurar.
    assert.equal(mesDoRelatorio(ACERVO[0]), '2026-08')
    assert.equal(mesDoRelatorio(ACERVO[1]), '2026-08')
    assert.ok(ACERVO[0].publicado_em.startsWith('2026-09'), 'a fixture perdeu o caso')
  })

  test('dia 1 não escorrega para o mês anterior (o que `new Date` faria)', () => {
    // `new Date('2026-08-01')` é meia-noite UTC; em UTC−3 o mês responde julho. Qualquer
    // documento que comece no dia 1 — que é TODO mensal — cairia na gaveta errada.
    for (const mes of ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']) {
      const r = rel({ id: 1, usina: 'X', de: `2026-${mes}-01` })
      assert.equal(mesDoRelatorio(r), `2026-${mes}`)
    }
  })

  test('cache gravado antes de `competencia` existir continua respondendo', () => {
    // O envelope em disco não tem versão: um JSON de formato anterior faz parse e é
    // desenhado como está, com o campo novo valendo `undefined`. O espelho `de.slice(0,7)`
    // é o que impede a tela de abrir sem gaveta nenhuma para quem estava offline.
    const velho = { ...rel({ id: 9, usina: 'X', de: '2026-08-01' }), competencia: null }
    assert.equal(mesDoRelatorio(velho), '2026-08')
  })

  test('ANUAL não tem mês — ele cobre doze', () => {
    // Dar competência ao anual o trancaria na gaveta de janeiro e o esconderia dos outros
    // onze meses. Ele responde por ano, e a gaveta diz isso.
    const anual = { ...rel({ id: 7, usina: 'X', de: '2026-01-01' }), periodo: 'ANUAL', ano: 2026, competencia: null }
    assert.equal(mesDoRelatorio(anual), null)
    assert.equal(gavetaDoRelatorio(anual), 'ano:2026')
    assert.equal(rotuloDaGaveta('ano:2026'), 'Ano de 2026')
  })

  test('o rótulo da gaveta é o mês por extenso, em pt-BR', () => {
    assert.equal(rotuloDaGaveta('2026-08'), 'Agosto de 2026')
    assert.equal(rotuloDaGaveta('2026-05'), 'Maio de 2026')
  })

  test('agrupar preserva a ordem do servidor, sem reordenar', () => {
    // Duas réguas de ordenação dariam duas respostas para "qual é o mais novo". A ordem é
    // a da publicação, decidida pelo BFF; aqui só se agrupa.
    const gavetas = agruparPorGaveta(ACERVO)
    assert.deepEqual(gavetas.map((g) => g.chave), ['2026-08', '2026-05'])
    assert.deepEqual(gavetas[0].itens.map((r) => r.id), [35, 36])
    assert.equal(gavetas[1].itens.length, 4)
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 3. AS PEÇAS — uma fonte só, com público e peso
 * ═════════════════════════════════════════════════════════════════════════ */

describe('as peças do fechamento', () => {
  test('o defeito medido: o Resumo Executivo tem nome de produto, não de arquivo', () => {
    // Antes: `NOME_DA_PECA` conhecia `geracao` e `paradas`, e o resumo do fechamento 36
    // saía "Resumo Executivo - Pereiras - Agosto 2026.pdf" ao lado de "Relatório de
    // Geração" — o nome cru do upstream, com extensão, numa lista de rótulos.
    const resumo = ACERVO[1].arquivos[0]
    assert.equal(rotuloDaPeca(resumo), 'Resumo Executivo')
    assert.notEqual(rotuloDaPeca(resumo), resumo.nome)
  })

  test('as três peças estão declaradas, com público', () => {
    assert.deepEqual(Object.keys(PECAS).sort(), ['geracao', 'paradas', 'resumo'])
    assert.equal(PECAS.geracao.publico, 'tecnico')
    assert.equal(PECAS.paradas.publico, 'tecnico')
    assert.equal(PECAS.resumo.publico, 'executivo')
  })

  test('peça desconhecida cai no nome do upstream, e não em "Documento"', () => {
    // Uma quarta peça amanhã não pode virar um rótulo genérico: o nome do arquivo diz
    // mais do que "Documento", que era o que a tela de abrir escrevia.
    const nova = { tipo: 'termografia', nome: 'Laudo termográfico.pdf', bytes: 10 }
    assert.equal(rotuloDaPeca(nova), 'Laudo termográfico.pdf')
    assert.equal(detalheDaPeca(nova), '10 B')
  })

  test('o defeito medido: 43 KB e 2,7 MB são a diferença entre tocar e não tocar', () => {
    assert.equal(detalheDaPeca(ACERVO[1].arquivos[0]), 'executivo · 43 KB')
    assert.equal(detalheDaPeca(ACERVO[0].arquivos[0]), 'técnico · 2,7 MB')
    assert.equal(detalheDaPeca(ACERVO[0].arquivos[1]), 'técnico · 2,6 MB')
  })

  test('peso ausente é travessão — nunca zero', () => {
    // Coalescer ausência para 0 escreveria "0 B" num arquivo que existe: seria afirmar
    // que o PDF está vazio. Zero DECLARADO pelo servidor continua sendo zero.
    assert.equal(peso(null), '—')
    assert.equal(peso(undefined), '—')
    assert.equal(peso(0), '0 B')
    assert.equal(detalheDaPeca({ tipo: 'geracao', nome: 'x.pdf', bytes: null }), 'técnico · —')
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 4. OS FILTROS — e a tela que nunca fica vazia por causa deles
 * ═════════════════════════════════════════════════════════════════════════ */

describe('o recorte', () => {
  test('as opções saem dos próprios relatórios, e nenhuma nasce com zero', () => {
    // Medido: a conta tem 7 usinas e só 5 têm fechamento. Oferecer as 7 daria duas opções
    // que levam a uma tela vazia — e é a lista de opções que tem de acompanhar o acervo.
    const r = recorte(ACERVO, null, null)
    assert.deepEqual(
      r.opcoesDeUsina.map((o) => o.rotulo),
      ['Todas as usinas', 'Ouro Fino', 'Pereiras', 'Pirapozinho', 'Porto Ferreira', 'Tiete'],
    )
    for (const o of r.opcoesDeUsina) assert.ok(o.contagem > 0, `${o.rotulo} nasceu com zero`)
    assert.equal(r.opcoesDeUsina[0].contagem, 6)
    assert.equal(r.opcoesDeUsina.find((o) => o.valor === 'Pereiras')?.contagem, 2)
  })

  test('os períodos do acervo são exatamente os dois medidos hoje', () => {
    const r = recorte(ACERVO, null, null)
    assert.deepEqual(
      r.opcoesDeGaveta.map((o) => o.rotulo),
      ['Todos os períodos', 'Agosto de 2026', 'Maio de 2026'],
    )
    assert.deepEqual(r.opcoesDeGaveta.map((o) => o.contagem), [6, 2, 4])
  })

  test('filtrar por usina e por mês devolve o que se pediu', () => {
    const r = recorte(ACERVO, 'Pereiras', '2026-08')
    assert.deepEqual(r.visiveis.map((x) => x.id), [36])
    assert.equal(r.ajuste, null)
  })

  test('o defeito nomeado: usina que saiu do escopo volta sozinha para Todas', () => {
    // Sem o grampo, um filtro guardado de uma usina que o gestor retirou deixa a tela
    // vazia PARA SEMPRE, e sem dizer por quê.
    const r = recorte(ACERVO, 'Usina Que Saiu', null)
    assert.equal(r.usina, null)
    assert.equal(r.visiveis.length, 6)
    assert.match(r.ajuste ?? '', /não tem relatório publicado/)
  })

  test('o vazio que o grampo simples não pega: a COMBINAÇÃO não existe', () => {
    // Porto Ferreira existe. Maio existe. "Porto Ferreira em maio" não existe — e as duas
    // escolhas, cada uma válida sozinha, produziriam uma tela vazia sem explicação.
    const r = recorte(ACERVO, 'Porto Ferreira', '2026-05')
    assert.equal(r.usina, 'Porto Ferreira')
    assert.equal(r.gaveta, null, 'o mês tinha de ter sido largado')
    assert.deepEqual(r.visiveis.map((x) => x.id), [35])
    assert.match(r.ajuste ?? '', /Não há relatório de Porto Ferreira em maio de 2026/)
  })

  test('as opções de período são contadas DENTRO da usina escolhida', () => {
    // É o que impede a tela de oferecer "Maio de 2026" numa usina que não tem maio.
    const r = recorte(ACERVO, 'Porto Ferreira', null)
    assert.deepEqual(r.opcoesDeGaveta.map((o) => o.rotulo), ['Todos os períodos', 'Agosto de 2026'])
  })

  test('acervo vazio não estoura, e não inventa opção', () => {
    const r = recorte([], 'Pereiras', '2026-08')
    assert.deepEqual(r.visiveis, [])
    assert.equal(r.opcoesDeUsina.length, 1)
    assert.equal(r.opcoesDeGaveta.length, 1)
  })

  test('o subtítulo conta o que está na tela', () => {
    assert.equal(subtituloDaAba(recorte(ACERVO, null, null)), '6 relatórios · 5 usinas')
    assert.equal(subtituloDaAba(recorte(ACERVO, 'Pereiras', null)), '2 relatórios · Pereiras')
    assert.equal(subtituloDaAba(recorte(ACERVO, 'Pereiras', '2026-08')), '1 relatório · agosto de 2026')
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 5. AS TRÊS AUSÊNCIAS — cada uma com o seu texto
 * ═════════════════════════════════════════════════════════════════════════ */

describe('a tela vazia', () => {
  test('o defeito nomeado: com a ponte caída, o título não pode AFIRMAR que nada foi publicado', () => {
    // Quando o monitoramento não responde, não se sabe se há relatório algum. O título
    // antigo dizia "Nenhum relatório publicado" com o aviso do servidor logo abaixo —
    // título e corpo se contradiziam no mesmo cartão.
    const v = vazioDaLista('Relatórios indisponíveis: timeout')
    assert.notEqual(v.titulo, 'Nenhum relatório publicado')
    assert.equal(v.descricao, 'Relatórios indisponíveis: timeout')
    assert.equal(v.ponte, true)
  })

  test('sem aviso, o vazio é o vazio honesto', () => {
    const v = vazioDaLista(null)
    assert.equal(v.titulo, 'Nenhum relatório publicado')
    assert.equal(v.ponte, false)
  })

  test('a terceira ausência: fechamento sem peça diz de quem é a ação', () => {
    // Quatro dos seis fechamentos medidos hoje estão assim. "Sem arquivo anexado." é
    // verdade e não é resposta: o dono lê "o aplicativo não baixou".
    const frase = frasePecaAusente()
    assert.match(frase, /anexad/i, 'a frase precisa dizer que ninguém anexou')
    assert.match(frase, /retirad/i, 'a frase precisa dizer a segunda causa')
    assert.match(frase, /equipe/i, 'a frase precisa dizer de quem é a ação')
    assert.notEqual(frase, 'Sem arquivo anexado.')
    // Quatro dos seis cartões a exibem na mesma rolagem: parágrafo repetido não é lido.
    assert.ok(frase.length <= 120, `a frase cresceu demais (${frase.length} caracteres)`)
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 6. FONTE — o que não pode voltar a existir no código
 * ═════════════════════════════════════════════════════════════════════════ */

describe('a aba, o arquivo e a rota', () => {
  test('a barra tem cinco abas, na ordem, e a terceira é Relatórios', () => {
    // O `name` do `<Tabs.Screen>` é o nome do ARQUIVO. Trocar um sem o outro faz a aba
    // sumir da barra e as quatro restantes se embaralharem.
    const layout = fonte('src/app/(tabs)/_layout.tsx')
    const nomes = [...layout.matchAll(/name="([a-z]+)"/g)].map((m) => m[1])
    assert.deepEqual(nomes, ['index', 'usinas', 'relatorios', 'manutencao', 'assistente'])
    assert.match(layout, /title: 'Relatórios'/)
    assert.equal(layout.includes(`name="documentos"`), false)
  })

  test('a rota existe com o nome novo, e a antiga não ficou para trás', () => {
    assert.ok(existsSync(join(APP, 'src/app/(tabs)/relatorios.tsx')))
    assert.equal(existsSync(join(APP, 'src/app/(tabs)/documentos.tsx')), false)
    assert.ok(existsSync(join(APP, 'src/features/relatorios.ts')))
    assert.equal(existsSync(join(APP, 'src/features/documentos.ts')), false)
  })

  test('o endereço antigo não vira rota morta', () => {
    // Nada no repositório gera `gestaosolar://documentos`, mas o esquema é público e o
    // endereço é válido por construção. O expo-router não redireciona sozinho.
    const ponte = fonte('src/app/documentos.tsx')
    assert.match(ponte, /Redirect/)
    assert.match(ponte, /['"]\/relatorios['"]/)
  })

  test('o defeito nomeado: a chave de cache continua sendo `documents`', () => {
    // Ela é o caminho do BFF sem `/api/v1/` e vira nome de arquivo em disco. Trocá-la para
    // acompanhar o rótulo órfã o `u{id}__documents.json` de todo celular já instalado.
    const modulo = fonte('src/features/relatorios.ts')
    assert.match(modulo, /fetchWithCache<RelatoriosOut>\('documents'\)/)
    assert.match(urlDoArquivo(36, 'resumo'), /\/api\/v1\/documents\/36\/file\?tipo=resumo$/)

    // O nome do arquivo em disco, pela MESMA régua de `lib/cache.ts` — é ele que precisa
    // continuar existindo no celular de quem já tem o app instalado.
    const sanitizar = (chave: string) => chave.replace(/[^a-z0-9]+/gi, '_')
    assert.equal(`u2__${sanitizar('documents')}.json`, 'u2__documents.json')
    const cache = fonte('src/lib/cache.ts')
    assert.ok(
      cache.includes('${donoDoCache}__${chave.replace(/[^a-z0-9]+/gi, \'_\')}.json'),
      'a régua do nome de arquivo mudou em lib/cache.ts — este teste precisa acompanhá-la',
    )
  })

  test('o defeito nomeado: `new Date` não volta ao módulo do mês', () => {
    // O corte do mês é por fatia de string. Um `new Date` aqui devolve o mês anterior no
    // Brasil para todo documento que comece no dia 1 — que é todo mensal.
    const modulo = fonte('src/features/relatorios.ts')
    const semComentarios = modulo.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
    assert.equal(semComentarios.includes('new Date'), false, '`new Date` voltou ao módulo')
  })

  test('o defeito nomeado: o mapa das peças tem UMA fonte', () => {
    // Ele vivia em dois arquivos com duas entradas cada. Duas cópias é o mesmo que duas
    // respostas, e foi assim que o Resumo saiu como nome de arquivo numa tela e como
    // "Documento" na outra.
    const suspeitos = ['src/app/(tabs)/relatorios.tsx', 'src/app/documentos.tsx']
    for (const alvo of suspeitos) {
      const texto = fonte(alvo)
      assert.equal(
        /NOME_DA_PECA|'Relatório de Geração'|'Anexo de Paradas'|'Resumo Executivo'/.test(texto),
        false,
        `${alvo} declara rótulo de peça por conta própria — a fonte é features/relatorios.ts`,
      )
    }
  })

  test('a aba leva à grade do ano, e a grade não é uma sexta aba', () => {
    const tela = fonte('src/app/(tabs)/relatorios.tsx')
    assert.match(tela, /['"]\/relatorios\/ano['"]/)
    assert.equal(existsSync(join(APP, 'src/app/(tabs)/ano.tsx')), false)
  })

  test('a aba abre o PDF em um toque, pela rota nova', () => {
    // O degrau intersticial existia porque a WebView não renderizava PDF — nunca por
    // necessidade. E o destino é `/relatorio/{id}`, não o endereço antigo.
    const tela = fonte('src/app/(tabs)/relatorios.tsx')
    assert.match(tela, /\/relatorio\/\$\{r\.id\}\?tipo=\$\{a\.tipo\}/)
    assert.equal(/push\(`\/documento\//.test(tela), false)
  })
})
