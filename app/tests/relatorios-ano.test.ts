/**
 * O que este arquivo guarda — a grade do ano (`/relatorios/ano`) e a tela que a desenha.
 *
 * Cada teste diz, na primeira linha, qual defeito ele impede de voltar. Os dados dos
 * cenários **foram medidos** contra a carteira real do usuário 2 em 05/09/2026 (7 usinas,
 * corpo de 9.863 B) — não são inventados:
 *
 * * Porto Ferreira: cronograma `CONSOLIDATED`, `pct_ate_hoje` 41,9 · `13/31` ·
 *   `mes_referencia` 2026-09 · `previsto_no_contrato` 269; agosto `publicado` com
 *   `geracao` (2.686.172 B) e `paradas` (2.604.352 B); setembro `corrente` 0/18; outubro,
 *   novembro e dezembro `futuro` com 13, 31 e 18;
 * * Pereiras: agosto `publicado` só com `resumo` (43.238 B, o EXECUTIVO) e maio
 *   `fechamento_sem_arquivo`;
 * * Ibitinga: doze meses `sem_fechamento`;
 * * UFV Leme: doze meses `sem_monitoramento`.
 *
 * **Como rodar** (sem dependência nova):
 *
 * ```
 * cd app && node --test tests/relatorios-ano.test.ts
 * ```
 *
 * O Node executa TypeScript por remoção de tipos. O que ele não sabe fazer é resolver o
 * apelido `@/…` do Metro nem carregar `lib/cache`/`lib/api`, que arrastam React Native e
 * axios inteiros — daí os ganchos abaixo. Ninguém aqui testa rede: o que se testa é a
 * régua, que é texto e classificação.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { join } from 'node:path'
import { describe, test } from 'node:test'
import { pathToFileURL } from 'node:url'

const RAIZ = join(import.meta.dirname, '..', 'src')
const BFF = join(import.meta.dirname, '..', '..', 'bff', 'app', 'api', 'v1')

registerHooks({
  resolve(especificador: string, contexto: unknown, proximo: (e: string, c: unknown) => unknown) {
    // Os dois módulos que só existem dentro do aparelho. O duplo entrega funções com a
    // mesma assinatura e nada mais: `useGradeDoAno` não é exercitado aqui (chamar um hook
    // fora do React nem faria sentido) e as urls só precisam de um `baseURL` qualquer.
    if (especificador === '@/lib/cache') return { url: 'duplo:cache', shortCircuit: true }
    if (especificador === '@/lib/api') return { url: 'duplo:api', shortCircuit: true }
    if (especificador.startsWith('@/')) {
      return proximo(pathToFileURL(join(RAIZ, `${especificador.slice(2)}.ts`)).href, contexto)
    }
    // O Node exige a extensão; o TypeScript, em `moduleResolution: bundler`, exige que ela
    // NÃO esteja escrita. O gancho reconcilia os dois.
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
        source:
          "export const baseURL = 'https://exemplo'\nexport function tokenDaSessao() { return null }\nexport function detalheEmTexto(x) { return typeof x === 'string' ? x : null }\nexport function mensagemDeErro() { return 'erro' }\n",
        shortCircuit: true,
      }
    }
    return proximo(url, contexto)
  },
})

const {
  anosOferecidos,
  CAMPOS_LIDOS,
  janelaPorExtenso,
  linhasVisiveis,
  marcaDaEnergia,
  marcaDaManutencao,
  mesesComConteudo,
  ofertaDoPacote,
  opcoesDeUsina,
  recorteDoAno,
  rotuloDoPublico,
  TETO_DO_PACOTE,
  urlDoPacoteDeFichas,
  urlDoRelatorioDeManutencao,
  usinaEscolhida,
} = (await import('@/features/relatorios-ano')) as typeof import('../src/features/relatorios-ano')

type Usina = import('../src/features/relatorios-ano').UsinaDoAno
type Celula = import('../src/features/relatorios-ano').CelulaDoAno

/* ══════════════════════════════════════════════════════════════════ os cenários ══ */

const semEnergia = (estado: string) => ({
  estado,
  documento_id: null,
  publicado_em: null,
  pecas: [],
})

/** A linha de Porto Ferreira, como o servidor a devolveu hoje. */
function portoFerreira(): Usina {
  const manut: (readonly [string, number, number] | null)[] = [
    null, null, null, null, null, null, null,
    ['fechado', 13, 13],
    ['corrente', 18, 0],
    ['futuro', 13, 0],
    ['futuro', 31, 0],
    ['futuro', 18, 0],
  ]
  const meses: Celula[] = manut.map((m, i) => ({
    mes: `2026-${String(i + 1).padStart(2, '0')}`,
    energia:
      i === 7
        ? {
            estado: 'publicado',
            documento_id: 35,
            publicado_em: '2026-09-05T12:00:00',
            pecas: [
              { tipo: 'geracao', nome: 'Relatório de Geração', bytes: 2686172 },
              { tipo: 'paradas', nome: 'Anexo de Paradas', bytes: 2604352 },
            ],
          }
        : semEnergia('sem_fechamento'),
    manutencao: m ? { situacao: m[0], previsto: m[1], cumprido: m[2] } : null,
  }))
  return {
    id: 4,
    nome: 'Porto Ferreira',
    tem_monitoramento: true,
    tem_manutencao: true,
    contrato: 'Contrato de O&M',
    contrato_id: 900,
    cronograma_status: 'CONSOLIDATED',
    cronograma_versao: 1,
    mes_referencia: '2026-09',
    previsto_ate_hoje: 31,
    cumprido_ate_hoje: 13,
    pct_ate_hoje: 41.9,
    previsto_no_contrato: 269,
    meses,
    anual: {
      energia: {
        disponivel: false,
        motivo: 'O monitoramento ainda não publica fechamento anual.',
        estado: 'sem_fechamento',
        documento_id: null,
        pecas: [],
      },
      manutencao: { disponivel: true, motivo: null, de: '2026-01', ate: '2026-09' },
    },
    aviso_manutencao: null,
  }
}

/** Pereiras: só o Resumo Executivo em agosto, e maio fechado sem arquivo. */
function pereiras(): Usina {
  const meses: Celula[] = Array.from({ length: 12 }, (_, i) => ({
    mes: `2026-${String(i + 1).padStart(2, '0')}`,
    energia:
      i === 7
        ? {
            estado: 'publicado',
            documento_id: 36,
            publicado_em: '2026-09-05T12:00:00',
            pecas: [{ tipo: 'resumo', nome: 'Resumo Executivo', bytes: 43238 }],
          }
        : i === 4
          ? semEnergia('fechamento_sem_arquivo')
          : semEnergia('sem_fechamento'),
    manutencao: null,
  }))
  return {
    ...portoFerreira(),
    id: 2,
    nome: 'Pereiras',
    cronograma_status: null,
    cronograma_versao: null,
    mes_referencia: null,
    previsto_ate_hoje: null,
    cumprido_ate_hoje: null,
    pct_ate_hoje: null,
    previsto_no_contrato: null,
    meses,
    aviso_manutencao: 'A equipe ainda não publicou o cronograma deste contrato.',
  }
}

function ibitinga(): Usina {
  return {
    ...pereiras(),
    id: 6,
    nome: 'Ibitinga',
    meses: Array.from({ length: 12 }, (_, i) => ({
      mes: `2026-${String(i + 1).padStart(2, '0')}`,
      energia: semEnergia('sem_fechamento'),
      manutencao: null,
    })),
  }
}

function ufvLeme(): Usina {
  return {
    ...pereiras(),
    id: 8,
    nome: 'UFV Leme',
    tem_monitoramento: false,
    meses: Array.from({ length: 12 }, (_, i) => ({
      mes: `2026-${String(i + 1).padStart(2, '0')}`,
      energia: semEnergia('sem_monitoramento'),
      manutencao: null,
    })),
    anual: {
      energia: {
        disponivel: false,
        motivo: 'Esta usina não está ligada ao monitoramento, de onde vêm os relatórios.',
        estado: 'sem_monitoramento',
        documento_id: null,
        pecas: [],
      },
      manutencao: { disponivel: true, motivo: null, de: '2026-01', ate: '2026-09' },
    },
  }
}

const CARTEIRA = () => [portoFerreira(), pereiras(), ibitinga(), ufvLeme()]

/**
 * O código sem os comentários.
 *
 * As guardas de fonte abaixo procuram construções proibidas (`new Date`, uma divisão, um
 * chip). Sem tirar os comentários antes, elas acusariam os próprios avisos que EXPLICAM por
 * que a construção é proibida — e o jeito de "consertar" seria apagar a explicação.
 */
function semComentarios(fonte: string): string {
  return fonte.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

/* ══════════════════════════════════════════════════════════════════════ contrato ══ */

describe('contrato — os campos que a tela lê existem no BFF', () => {
  const fonte = readFileSync(join(BFF, 'relatorios_ano.py'), 'utf8')

  /** Guarda: o BFF renomeia um campo e o celular segue lendo o nome antigo, calado.
   *
   *  Foi assim que "Contrato nº undefined" chegou à tela do dono — `undefined !== null` é
   *  verdadeiro, o guarda passou, e o cache em disco fez o defeito piscar. */
  for (const [modelo, campos] of Object.entries(CAMPOS_LIDOS)) {
    if (modelo === 'InventarioOut' || modelo === 'ParteOut' || modelo === 'PreparoOut') continue
    test(`${modelo} declara os campos que a grade lê`, () => {
      const bloco = fonte.split(`class ${modelo}(BaseModel):`)[1]
      assert.ok(bloco, `o modelo ${modelo} sumiu de relatorios_ano.py`)
      const corpo = bloco.split('\nclass ')[0]
      for (const campo of campos) {
        assert.match(
          corpo,
          new RegExp(`^\\s{4}${campo}\\s*:`, 'm'),
          `${modelo}.${campo} não existe mais no BFF`,
        )
      }
    })
  }

  /** Guarda: os modelos do pacote de fichas moram noutro arquivo e mudam por conta própria. */
  test('o inventário de fichas declara total, prontas e bytes — o que a tela promete antes de baixar', () => {
    const pacotes = readFileSync(join(BFF, 'pacotes.py'), 'utf8')
    for (const [modelo, campos] of [
      ['InventarioOut', CAMPOS_LIDOS.InventarioOut],
      ['ParteOut', CAMPOS_LIDOS.ParteOut],
      ['PreparoOut', CAMPOS_LIDOS.PreparoOut],
    ] as const) {
      const corpo = pacotes.split(`class ${modelo}(BaseModel):`)[1]?.split('\nclass ')[0]
      assert.ok(corpo, `o modelo ${modelo} sumiu de pacotes.py`)
      for (const campo of campos) {
        assert.match(corpo, new RegExp(`^\\s{4}${campo}\\s*:`, 'm'), `${modelo}.${campo} sumiu`)
      }
    }
  })

  /** Guarda: a rota do relatório do ano deixa de aceitar `de`/`ate` e a tela pede o ano
   *  inteiro, levando 400 no primeiro toque do dono. */
  test('as urls que a tela monta batem com as rotas do BFF', () => {
    assert.equal(
      urlDoRelatorioDeManutencao(4, '2026-01', '2026-09'),
      'https://exemplo/api/v1/manutencao/relatorio/pdf?usina_id=4&de=2026-01&ate=2026-09',
    )
    assert.equal(
      urlDoPacoteDeFichas(4, '2026-01', '2026-09', 2),
      'https://exemplo/api/v1/manutencao/fichas/pacote?usina_id=4&de=2026-01&ate=2026-09&parte=2',
    )
    const relatorio = readFileSync(join(BFF, 'relatorio.py'), 'utf8')
    assert.match(relatorio, /@router\.get\("\/manutencao\/relatorio\/pdf"\)/)
    const pacotes = readFileSync(join(BFF, 'pacotes.py'), 'utf8')
    assert.match(pacotes, /@router\.get\("\/manutencao\/fichas\/pacote"\)/)
  })
})

/* ══════════════════════════════════════════════════════ as cinco ausências da energia ══ */

describe('energia — cinco estados, cinco desenhos', () => {
  /** Guarda: as cinco ausências voltam a ser a mesma frase muda ("Sem arquivo anexado"),
   *  que o dono lê como "o aplicativo não baixou". */
  test('nenhum dos cinco estados desenha igual a outro', () => {
    const estados = [
      'publicado',
      'fechamento_sem_arquivo',
      'sem_fechamento',
      'sem_monitoramento',
      'indisponivel',
    ]
    const desenhos = estados.map((e) => {
      const m = marcaDaEnergia({
        estado: e,
        documento_id: null,
        publicado_em: null,
        pecas: e === 'publicado' ? [{ tipo: 'geracao', nome: 'x', bytes: 1 }] : [],
      })
      return `${m.letra}|${m.tom}|${m.forte}`
    })
    assert.equal(new Set(desenhos).size, estados.length, `desenhos repetidos: ${desenhos.join(' ')}`)
  })

  /** Guarda: "não sabemos" (a ponte caiu) volta a ser pintado como "ninguém publicou" —
   *  uma afirmação que o aplicativo não tem como fazer. */
  test('indisponível não se parece com sem_fechamento', () => {
    const caiu = marcaDaEnergia(semEnergia('indisponivel'))
    const vazio = marcaDaEnergia(semEnergia('sem_fechamento'))
    assert.notEqual(caiu.tom, vazio.tom)
    assert.match(caiu.rotulo, /não deu para saber/i)
  })

  /** Guarda: as quatro células medidas hoje deixam de ser distinguíveis na grade. */
  test('as quatro células medidas hoje têm marcas distintas', () => {
    const pf = portoFerreira().meses[7] // agosto: geracao + paradas
    const pe = pereiras().meses[7] // agosto: só o resumo
    const maio = pereiras().meses[4] // fechamento sem arquivo
    const ib = ibitinga().meses[7] // sem fechamento
    assert.deepEqual(
      [marcaDaEnergia(pf.energia).letra, marcaDaEnergia(pe.energia).letra],
      ['2', '1'],
      'o número da célula é a quantidade de peças',
    )
    assert.equal(marcaDaEnergia(maio.energia).tom, 'alerta')
    assert.equal(marcaDaEnergia(ib.energia).tom, 'semDados')
    const marcas = [pf, pe, maio, ib].map((c) => {
      const m = marcaDaEnergia(c.energia)
      return `${m.letra}|${m.tom}`
    })
    assert.equal(new Set(marcas).size, 4)
  })

  /** Guarda: um estado novo do servidor é achatado num dos cinco — a tela afirmaria uma
   *  coisa que ninguém disse. */
  test('estado desconhecido aparece como desconhecido, e não como um dos cinco', () => {
    const m = marcaDaEnergia(semEnergia('reprocessando'))
    assert.equal(m.letra, '?')
    assert.equal(m.rotulo, 'reprocessando')
  })

  /** Guarda: o Resumo Executivo perde o rótulo de público e a metade "executivo" do
   *  pedido do dono some da tela. */
  test('o público sai do mapa único de peças', () => {
    assert.equal(rotuloDoPublico('resumo'), 'EXECUTIVO')
    assert.equal(rotuloDoPublico('geracao'), 'TÉCNICO')
    assert.equal(rotuloDoPublico('paradas'), 'TÉCNICO')
    assert.equal(rotuloDoPublico('coisa_nova'), null)
  })
})

/* ══════════════════════════════════════════════════════════ o calendário do contrato ══ */

describe('manutenção — o mês que não venceu nunca é falta', () => {
  /** Guarda: `futuro` recebe cor de atraso.
   *
   *  Medido hoje em Porto Ferreira: out (13), nov (31) e dez (18) somam **62 atividades**
   *  que a tela acusaria de atrasadas se a régua saísse do relógio do celular em vez do
   *  `situacao` do meuPlano. */
  test('os três meses futuros de Porto Ferreira não recebem cor de falta', () => {
    const futuros = portoFerreira().meses.filter((c) => c.manutencao?.situacao === 'futuro')
    assert.equal(futuros.length, 3)
    assert.equal(
      futuros.reduce((s, c) => s + (c.manutencao?.previsto ?? 0), 0),
      62,
      'o cenário deixou de ser o medido',
    )
    for (const c of futuros) {
      const m = marcaDaManutencao(c.manutencao)
      assert.notEqual(m.tom, 'parado', `${c.mes} pintado como atraso`)
      assert.notEqual(m.tom, 'alerta', `${c.mes} pintado como pendência`)
      assert.match(m.rotulo, /ainda não venceu/)
      assert.equal(m.letra, String(c.manutencao?.previsto), 'o futuro mostra o previsto')
    }
  })

  /** Guarda: o mês em curso é cobrado como se já tivesse vencido. Setembro está 0/18 e
   *  ainda tem o mês inteiro pela frente. */
  test('o mês corrente é distinto do vencido incompleto', () => {
    const corrente = marcaDaManutencao({ situacao: 'corrente', previsto: 18, cumprido: 0 })
    const vencido = marcaDaManutencao({ situacao: 'fechado', previsto: 18, cumprido: 0 })
    assert.equal(corrente.tom, 'alerta')
    assert.equal(vencido.tom, 'parado')
    assert.notEqual(corrente.rotulo, vencido.rotulo)
  })

  test('agosto cumprido (13 de 13) é verde e preenchido', () => {
    const m = marcaDaManutencao(portoFerreira().meses[7].manutencao)
    assert.equal(m.tom, 'ok')
    assert.equal(m.forte, true)
    assert.equal(m.letra, '13')
    assert.equal(m.nota, 'de 13')
  })

  /** Guarda: mês fora do contrato vira um bloco de zeros, que se lê como "estava previsto
   *  e não foi feito". O contrato de Porto Ferreira começa em agosto: janeiro a julho não
   *  tinham nada combinado. */
  test('mês fora do contrato fica em branco, não em zero', () => {
    for (const c of portoFerreira().meses.slice(0, 7)) {
      assert.equal(c.manutencao, null)
      assert.equal(marcaDaManutencao(c.manutencao).letra, '')
    }
  })

  /** Guarda: "nada previsto neste mês" some dentro de "fora do contrato" — o primeiro é
   *  um mês do contrato sem atividade, o segundo é mês nenhum. */
  test('previsto zero dentro do contrato não é o mesmo que fora do contrato', () => {
    const zero = marcaDaManutencao({ situacao: 'fechado', previsto: 0, cumprido: 0 })
    const fora = marcaDaManutencao(null)
    assert.notEqual(zero.rotulo, fora.rotulo)
    assert.match(zero.rotulo, /Nada previsto/)
  })
})

/* ══════════════════════════════════════════════════════════ o recorte de vigência ══ */

describe('o percentual do ano — repassado, e nunca sozinho', () => {
  /** Guarda: alguém recalcula o percentual aqui e nasce a TERCEIRA resposta para "está
   *  sendo feito?" — foi assim que a mesma usina apareceu com "13 de 270" numa tela e
   *  "41,9 %" na outra. */
  test('o percentual é o do servidor, byte a byte', () => {
    const r = recorteDoAno(portoFerreira())
    assert.ok(r)
    assert.equal(r.pct, 41.9)
    assert.equal(r.cumprido, 13)
    assert.equal(r.previsto, 31)
    // 13/31 = 41,935…: um recálculo daria 41.9354…, não 41.9. É a prova de que o número
    // atravessou em vez de ser refeito.
    assert.notEqual(r.pct, (13 / 31) * 100)
  })

  /** Guarda: o percentual aparece sem a janela e sem o denominador, e vira meia frase. */
  test('a frase traz o denominador e o mês de referência colados', () => {
    const r = recorteDoAno(portoFerreira())
    assert.equal(r?.frase, '13 de 31 até setembro de 2026')
    assert.equal(r?.mesReferencia, '2026-09')
  })

  /** Guarda: o total do contrato (269) é confundido com o denominador do recorte (31) —
   *  são perguntas diferentes e a tela mostra os dois, cada um rotulado. */
  test('o total do contrato viaja junto, e não no lugar do denominador', () => {
    const r = recorteDoAno(portoFerreira())
    assert.equal(r?.noContrato, 269)
    assert.notEqual(r?.noContrato, r?.previsto)
  })

  /** Guarda: usina sem cronograma consolidado aparece como "0 %" em vez de "a equipe ainda
   *  não publicou". Cinco das seis usinas com contrato estão nesse estado hoje. */
  test('sem cronograma consolidado o recorte é nulo, nunca zero', () => {
    assert.equal(recorteDoAno(pereiras()), null)
    assert.equal(recorteDoAno(ibitinga()), null)
  })
})

/* ══════════════════════════════════════════════════════════════════════ a janela ══ */

describe('a janela do ano é impressa, e nunca chega a dezembro por engano', () => {
  /** Guarda: a tela monta `2026-01..2026-12` num ano em curso e leva
   *  **400 "ate não pode ser um mês futuro."** no primeiro toque — medido hoje. */
  test('a janela vem do servidor e sai por extenso', () => {
    assert.equal(janelaPorExtenso('2026-01', '2026-09'), 'janeiro a setembro de 2026')
    assert.equal(janelaPorExtenso('2026-09', '2026-09'), 'setembro de 2026')
    assert.equal(janelaPorExtenso('2025-11', '2026-02'), 'novembro de 2025 a fevereiro de 2026')
    assert.equal(janelaPorExtenso(null, '2026-09'), null)
  })

  /** Guarda: alguém troca a fatia de string por `new Date`.
   *
   *  `new Date('2026-01')` é meia-noite UTC — no Brasil, dezembro do ano anterior. A janela
   *  de "janeiro a setembro de 2026" viraria "dezembro a agosto". */
  test('o mês sai de fatia de string, não de Date', () => {
    assert.equal(janelaPorExtenso('2026-01', '2026-01'), 'janeiro de 2026')
    const fonte = semComentarios(readFileSync(join(RAIZ, 'features', 'relatorios-ano.ts'), 'utf8'))
    assert.equal(
      /new Date\(/.test(fonte),
      false,
      'o módulo do ano voltou a construir Date a partir de texto de mês',
    )
  })

  /** Guarda: o seletor oferece um ano que o servidor recusa (medido: `ano=2028` responde
   *  400 quando o corrente é 2026). */
  test('o seletor nunca oferece além do ano seguinte', () => {
    const anos = anosOferecidos(2026)
    assert.deepEqual(anos, [2027, 2026, 2025, 2024])
    assert.equal(Math.max(...anos), 2027)
  })
})

/* ══════════════════════════════════════════════════════════════════════ o filtro ══ */

describe('o filtro de usina não deixa a tela muda', () => {
  /** Guarda: uma usina guardada que saiu do escopo deixa a tela vazia para sempre, sem
   *  explicação — o mesmo grampo que a aba Manutenção já usa. */
  test('escolha que não existe mais volta para "todas"', () => {
    const carteira = CARTEIRA()
    assert.equal(usinaEscolhida(carteira, '4'), '4')
    assert.equal(usinaEscolhida(carteira, '999'), null)
    assert.equal(linhasVisiveis(carteira, '999').length, carteira.length)
    assert.equal(linhasVisiveis(carteira, '4').length, 1)
  })

  /** Guarda: opção com zero some da lista e quem procura por ela conclui que o aplicativo
   *  perdeu a usina. */
  test('usina sem nada no ano continua na lista, com zero', () => {
    const opcoes = opcoesDeUsina(CARTEIRA(), 'energia')
    assert.equal(opcoes[0].valor, null, '"Todas" vem primeiro')
    assert.equal(opcoes.length, 5)
    const leme = opcoes.find((o) => o.rotulo === 'UFV Leme')
    assert.equal(leme?.contagem, 0)
  })

  /** Guarda: a contagem do seletor promete uma coisa e a grade mostra outra. */
  test('a contagem é da família escolhida, e o total bate com a soma das linhas', () => {
    const carteira = CARTEIRA()
    const energia = opcoesDeUsina(carteira, 'energia')
    assert.equal(energia[0].contagem, 2, 'dois meses publicados na carteira hoje')
    assert.equal(mesesComConteudo(portoFerreira(), 'energia'), 1)
    const manutencao = opcoesDeUsina(carteira, 'manutencao')
    assert.equal(mesesComConteudo(portoFerreira(), 'manutencao'), 5)
    assert.equal(manutencao[0].contagem, 5)
    assert.equal(
      manutencao[0].contagem,
      carteira.reduce((s, u) => s + mesesComConteudo(u, 'manutencao'), 0),
    )
  })
})

/* ═══════════════════════════════════════════════════════════════ o pacote de fichas ══ */

describe('o pacote anuncia o que traz antes do primeiro byte', () => {
  const base = {
    usina: 'Porto Ferreira',
    usina_id: 4,
    de: '2026-01',
    ate: '2026-09',
    aviso_manutencao: null,
  }

  /** Guarda: volta o botão que baixa algo de tamanho desconhecido — e, com uma ficha sem
   *  PDF, o pacote sai incompleto sem ninguém conferir ("baixei dezessete e vieram três").
   *  Medido hoje: 27 fichas, 26 prontas, 27.071.615 B. */
  test('com ficha faltando, a oferta é PREPARAR e não baixar', () => {
    const o = ofertaDoPacote({
      ...base,
      total: 27,
      prontas: 26,
      bytes_estimados: 27071615,
      partes: [{ numero: 1, fichas: 27, bytes: 27071615 }],
    })
    assert.equal(o.tipo, 'preparar')
    assert.equal(o.tipo === 'preparar' && o.faltam, 1)
  })

  test('com tudo pronto, a oferta traz as partes com fichas e bytes', () => {
    const o = ofertaDoPacote({
      ...base,
      total: 27,
      prontas: 27,
      bytes_estimados: 27071615,
      partes: [{ numero: 1, fichas: 27, bytes: 27071615 }],
    })
    assert.equal(o.tipo, 'baixar')
    assert.deepEqual(o.tipo === 'baixar' && o.partes, [
      { numero: 1, fichas: 27, bytes: 27071615 },
    ])
  })

  /** Guarda: um pacote grande demais passa por um `ArrayBuffer` e derruba o aparelho sem
   *  dizer por quê. */
  test('acima do teto a tela manda para o site em vez de oferecer o botão', () => {
    const o = ofertaDoPacote({
      ...base,
      total: 400,
      prontas: 400,
      bytes_estimados: TETO_DO_PACOTE + 1,
      partes: [{ numero: 1, fichas: 400, bytes: TETO_DO_PACOTE + 1 }],
    })
    assert.equal(o.tipo, 'grande')
  })

  /** Guarda: período sem ficha nenhuma oferece um download que responderia 404. */
  test('período vazio não oferece download', () => {
    const o = ofertaDoPacote({
      ...base,
      total: 0,
      prontas: 0,
      bytes_estimados: null,
      partes: [],
      aviso: 'Nenhuma ficha registrada neste período.',
    })
    assert.equal(o.tipo, 'vazio')
  })

  /** Guarda: o servidor não calcula partes e a tela fica sem nenhum botão. */
  test('sem partes declaradas, uma parte é montada', () => {
    const o = ofertaDoPacote({ ...base, total: 5, prontas: 5, bytes_estimados: 100, partes: [] })
    assert.equal(o.tipo === 'baixar' && o.partes.length, 1)
  })
})

/* ═══════════════════════════════════════════════════════════════════════════ fonte ══ */

describe('fonte — o que não pode voltar a existir na tela do ano', () => {
  const tela = semComentarios(readFileSync(join(RAIZ, 'app', 'relatorios', 'ano.tsx'), 'utf8'))
  const modulo = semComentarios(readFileSync(join(RAIZ, 'features', 'relatorios-ano.ts'), 'utf8'))

  /** Guarda: a tela divide `cumprido_ate_hoje` por `previsto_ate_hoje` e inventa o terceiro
   *  percentual. A conta tem UM dono, e é o meuPlano. */
  test('nem a tela nem o módulo dividem os campos do recorte', () => {
    for (const [nome, fonte] of [['tela', tela], ['módulo', modulo]] as const) {
      assert.equal(
        /(cumprido_ate_hoje|cumprido)\s*\/\s*(previsto_ate_hoje|previsto)/.test(fonte),
        false,
        `o ${nome} voltou a calcular o percentual`,
      )
      assert.equal(/\*\s*100/.test(fonte), false, `o ${nome} voltou a montar um percentual`)
    }
  })

  /** Guarda: a tela deriva "mês vencido" do relógio do aparelho. Num fuso adiantado, no
   *  dia 1º, ela acusaria o mês inteiro de atraso. */
  test('a tela não deriva o estado do mês do relógio do celular', () => {
    const marcas = tela.match(/new Date\([^)]*\)/g) ?? []
    assert.deepEqual(
      marcas,
      ['new Date()'],
      'o único Date da tela é o ano corrente do seletor; qualquer outro está julgando mês',
    )
  })

  /** Guarda: o mapa de peças é copiado de novo — ele já esteve duplicado em dois arquivos,
   *  e por isso o Resumo Executivo aparecia com o nome de arquivo cru numa tela e como
   *  "Documento" na outra. */
  test('o mapa das peças não é recopiado; vem da fonte única', () => {
    for (const [nome, fonte] of [['tela', tela], ['módulo', modulo]] as const) {
      assert.equal(
        /'geracao'\s*:\s*\{/.test(fonte),
        false,
        `o ${nome} declarou o mapa de peças por conta própria`,
      )
    }
    assert.match(modulo, /from '@\/features\/relatorios'/)
  })

  /** Guarda: volta o chip de seleção que o dono não quer — de duas a duzentas opções, a
   *  escolha é lista suspensa ou segmentado. */
  test('a escolha de usina e de ano é lista suspensa, nunca chip', () => {
    assert.match(tela, /<EscolhaEmLista/)
    assert.equal(
      /\.map\([^)]*\)\s*=>\s*\(?\s*<Pressable[^>]*chip/i.test(tela),
      false,
      'apareceu uma fileira de pílulas de seleção',
    )
  })

  /** Guarda: a sessão vai parar na URL — e URL entra em log de servidor e em histórico. */
  test('nenhuma url carrega token', () => {
    for (const [nome, fonte] of [['tela', tela], ['módulo', modulo]] as const) {
      assert.equal(
        /[?&](token|access_token|jwt)=/.test(fonte),
        false,
        `o ${nome} pôs a sessão numa URL`,
      )
      assert.equal(/Authorization.*\$\{.*\}.*\?/.test(fonte), false)
    }
  })

  /** Guarda: alguém troca a chave do cache por uma sem o ano, e abrir 2025 e voltar para
   *  2026 lê do disco a grade do ano errado — no modo avião, para sempre. */
  test('o ano entra na chave do cache', () => {
    assert.match(modulo, /fetchWithCache<GradeDoAnoOut>\(`relatorios\/ano-\$\{ano\}`/)
  })


  /** Guarda: a coluna "ano" da geração vira botão.
   *
   *  Não existe fechamento anual publicado em lugar nenhum — medido hoje, `anual.energia.
   *  disponivel` é falso nas SETE usinas. Um botão ali é promessa de navegação: o dono toca,
   *  nada abre, e ele conclui que o aplicativo travou. A razão sai escrita no cartão abaixo
   *  da grade, sem precisar de toque. */
  test('o fecho anual da energia não é pressionável, e a razão fica escrita', () => {
    assert.match(
      tela,
      /onPress=\{familia === 'energia' \? undefined : onPress\}/,
      'a célula anual da energia voltou a receber onPress',
    )
    assert.match(tela, /function FechoAnualDeEnergia/)
    assert.match(tela, /fraseAnualDeEnergia\(u\.anual\.energia\)/)
  })

  /** Guarda: o botão do relatório do ano aparece antes da janela, e o dono aperta sem saber
   *  que período vai sair. Enquanto o ano corre, "o ano" é janeiro..mês corrente — pedir até
   *  dezembro responde 400. */
  test('a janela é impressa antes do botão do relatório', () => {
    const bloco = tela.slice(tela.indexOf('function AnualDeManutencao'))
    const janela = bloco.indexOf('Período coberto')
    const botao = bloco.indexOf('<AbrirPdf')
    assert.ok(janela > 0, 'a janela sumiu da folha do ano')
    assert.ok(botao > 0, 'o botão do relatório sumiu')
    assert.ok(janela < botao, 'o botão passou a vir antes da janela')
    assert.match(bloco, /janelaPorExtenso\(a\.de, a\.ate\)/)
  })

  /** Guarda: o pacote volta a ser baixado sem inventário — um botão para algo de tamanho
   *  desconhecido. Medido hoje: 27 fichas e 27.071.615 B em Porto Ferreira. */
  test('o download do pacote só existe depois do inventário', () => {
    const bloco = tela.slice(tela.indexOf('function PacoteDeFichas'))
    assert.match(bloco, /inventarioDeFichas\(usina\.id, de, ate\)/)
    // A url do pacote é montada uma vez só, e dentro de `baixar` — que a oferta gateia.
    const usos = bloco.match(/urlDoPacoteDeFichas\(/g) ?? []
    assert.equal(usos.length, 1, 'o pacote passou a ser montado em mais de um lugar')
    const oferta = bloco.indexOf('ofertaDoPacote(inventario)')
    assert.ok(oferta > 0, 'a oferta deixou de ser decidida pela régua testável')
    assert.match(bloco, /peso\(inventario\.bytes_estimados\)/, 'o peso sumiu da tela')
    assert.match(bloco, /inventario\.total/, 'a contagem de fichas sumiu da tela')
  })

  /** Guarda: a tela do ano abre uma SEGUNDA cópia do caminho do PDF em vez de reusar o
   *  leitor interno. Já houve duas cópias, e foi por isso que o transporte virou fonte
   *  única; o desenho não pode repetir a história. */
  test('o PDF abre pelo leitor único, nunca por um caminho próprio', () => {
    assert.match(tela, /<AbrirPdf/, 'o relatório do ano deixou de usar a peça única')
    assert.match(tela, /router\.push\(destino\)/, 'a peça deixou de abrir a tela do leitor')
    assert.equal(
      /Sharing\.shareAsync/.test(tela.slice(0, tela.indexOf('async function baixarPacote'))),
      false,
      'a tela voltou a sair do aplicativo para mostrar um PDF',
    )
  })

  /** Guarda: o aviso do topo (a ponte caiu) some e a tela afirma "ninguém publicou" quando
   *  ninguém sabe. */
  test('o aviso da carteira e o aviso por usina aparecem na tela', () => {
    assert.match(tela, /dados\.aviso/)
    assert.match(tela, /u\.aviso_manutencao/)
  })

  /**
   * O DEFEITO MEDIDO: o motivo da manutenção aparecia na aba de ENERGIA.
   *
   * O servidor mandava `"Manutenção: A equipe ainda não publicou o cronograma…"`, a tela
   * arrancava o prefixo com `replace(/^Manutenção: /, '')` e imprimia o resto nas duas
   * abas, cortado em uma linha. Na coluna de geração o dono lia cinco linhas de
   * "A equipe ainda não publico…" ao lado de células que falam de arquivo publicado.
   *
   * Dois cadeados: o motivo da linha só sai com a família certa, e prosa nunca mais é
   * analisada com expressão regular para descobrir de que família um campo é — quem diz
   * isso é o NOME do campo, vindo do servidor.
   */
  test('o motivo da manutenção só aparece na aba da manutenção', () => {
    assert.match(
      tela,
      /familia === 'manutencao' && u\.aviso_manutencao/,
      'o motivo da linha voltou a aparecer nas duas abas',
    )
  })

  test('nenhuma família é descoberta arrancando prefixo de prosa', () => {
    assert.equal(
      /replace\(\/\^Manuten/.test(tela),
      false,
      'voltou a usar expressão regular sobre a frase para separar as famílias',
    )
  })

  /**
   * O pedido do dono é "mês a mês, tanto GERAÇÃO quanto MANUTENÇÃO". A folha do mês
   * explicava "13 de 13" e não oferecia papel nenhum: o relatório de manutenção só existia
   * na coluna do ano. Medido em Porto Ferreira/agosto: `200, 408.192 B, 2,13 s`.
   *
   * E o mês que ainda não venceu NÃO ganha botão: pedir dezembro ao mesmo endereço responde
   * `400 "ate não pode ser um mês futuro."` (medido). Botão que só sabe dar erro é pior que
   * botão nenhum.
   */
  test('a folha do mês oferece o relatório de manutenção daquele mês', () => {
    assert.match(tela, /Abrir o relatório deste mês/)
    assert.match(
      tela,
      /urlDoRelatorioDeManutencao\(usina\.id, celula\.mes, celula\.mes\)/,
      'a janela do relatório do mês deixou de ser aquele mês',
    )
  })

  test('o mês que ainda não venceu não ganha botão de relatório', () => {
    assert.match(
      tela,
      /m\.situacao === 'futuro' \? null : \(\s*<AbrirPdf/,
      'a folha passou a oferecer um relatório que o servidor recusa com 400',
    )
  })
})
