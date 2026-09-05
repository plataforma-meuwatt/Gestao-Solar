/**
 * Os testes do aplicativo. Antes deste arquivo não havia nenhum.
 *
 * Isso não é uma nota de rodapé: o aplicativo era o ÚNICO consumidor do BFF sem um teste
 * sequer, e foi por isso que "Contrato nº undefined" chegou à tela do dono e ficou lá. O BFF
 * renomeou `OrdemOut.numero` para `contrato_numero`, o portal acompanhou porque tem suíte, e
 * o celular continuou lendo um campo que não existe mais — com um guarda (`!== null`) que
 * `undefined` atravessa. O cache em disco fez o defeito piscar: quem tinha a resposta antiga
 * gravada via o número certo até o arquivo ser reescrito.
 *
 * Rodar: `node --test tests/manutencao-regras.test.ts` (o Node 24 lê TypeScript direto; os
 * `import type` são apagados antes de o módulo carregar, e é por isso que o módulo de regras
 * não pode ganhar nenhum import de valor do React Native).
 *
 * O arquivo mora FORA de `src/` de propósito. O `tsconfig` do aplicativo inclui `src/**` e
 * não tem `@types/node` na lista de tipos nem `allowImportingTsExtensions`; deixá-lo lá
 * dentro faria `npm run check` reprovar por causa de `node:test` e da extensão `.ts` no
 * import — que o executor de testes EXIGE. Fora de `src/`, o Metro também não o empacota
 * junto com o aplicativo.
 *
 * São três famílias:
 *
 * 1. **contrato** — os campos que cada tela lê existem nos modelos Pydantic do BFF? É a
 *    família que teria pegado o defeito no minuto da renomeação;
 * 2. **regras** — agrupar, marcar e filtrar, que é desenho de tela e mora aqui;
 * 3. **fonte** — o que não pode voltar a existir no código (tradução duplicada, número
 *    interpolado sem guarda).
 */

import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, test } from 'node:test'

import {
  agruparCronograma,
  CAMPOS_LIDOS,
  contarPorSituacao,
  filtrarPendencias,
  marcaDaCelula,
  recorteDoCronograma,
  recorteInicial,
  rotuloDoContrato,
  SITUACAO_INICIAL,
  SITUACOES,
  TOM_DA_MARCA,
  tomValido,
  vazioPorFiltro,
  type CelulaLida,
} from '../src/features/manutencao-regras.ts'

const AQUI = dirname(fileURLToPath(import.meta.url))
const APP = join(AQUI, '..')
const BFF = join(APP, '..', 'bff', 'app', 'api', 'v1')

const fonte = (rel: string) => readFileSync(join(APP, rel), 'utf8')

/* ══════════════════════════════════════════════════════════════════════════
 * 1. CONTRATO — o campo que a tela lê ainda existe do outro lado?
 * ═════════════════════════════════════════════════════════════════════════ */

/**
 * Os campos de cada modelo Pydantic de um arquivo do BFF.
 *
 * O bloco da classe termina na primeira linha que volta à coluna zero — sem isso o corpo
 * "vaza" para o código de módulo que vem depois e o parser acha argumentos de função
 * (`db`, `usuario`, `try`) como se fossem campos, o que faria o teste passar por engano.
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
    if (linha.trim() !== '' && !/^\s/.test(linha)) {
      atual = null
      continue
    }
    const campo = /^ {4}([a-z_]\w*)\s*:/.exec(linha)
    if (campo) atual.add(campo[1])
  }
  return saida
}

describe('contrato com o BFF', () => {
  test('os arquivos do BFF estão onde este teste espera', () => {
    // Um teste de contrato que se auto-desliga quando não acha o outro lado não guarda
    // nada. Se o BFF mudar de lugar, é aqui que se descobre — e não em campo.
    for (const arquivo of ['manutencao', 'pendencias']) {
      assert.ok(
        existsSync(join(BFF, `${arquivo}.py`)),
        `não achei ${arquivo}.py em ${BFF} — o teste de contrato não pode rodar sem ele`,
      )
    }
  })

  const porArquivo = new Map<string, Map<string, Set<string>>>()
  const modelosDe = (arquivo: string) => {
    let m = porArquivo.get(arquivo)
    if (!m) {
      m = camposPorModelo(arquivo)
      porArquivo.set(arquivo, m)
    }
    return m
  }

  // Uma checagem por ROTA lida — é a granularidade que o relatório de falha precisa ter:
  // "a rota X perdeu o campo Y", e não "algo mudou em algum lugar".
  const rotas = [...new Set(CAMPOS_LIDOS.map((c) => c.rota))]
  for (const rota of rotas) {
    test(`${rota} — todo campo que a tela lê existe no modelo do BFF`, () => {
      for (const entrada of CAMPOS_LIDOS.filter((c) => c.rota === rota)) {
        const modelo = modelosDe(entrada.arquivo).get(entrada.modelo)
        assert.ok(modelo, `${entrada.arquivo}.py não declara ${entrada.modelo}`)
        for (const campo of entrada.campos) {
          assert.ok(
            modelo.has(campo),
            `${entrada.modelo}.${campo} sumiu do BFF — a tela de ${rota} lê esse campo`,
          )
        }
      }
    })
  }

  test('o defeito nomeado: OrdemOut tem contrato_numero e NÃO tem mais numero', () => {
    // As duas metades importam. A primeira é o campo novo; a segunda impede alguém de
    // "restaurar a compatibilidade" reintroduzindo `numero` no BFF — o dia em que os dois
    // existirem juntos, a tela volta a poder ler o errado sem ninguém notar.
    const ordem = modelosDe('manutencao').get('OrdemOut')
    assert.ok(ordem)
    assert.ok(ordem.has('contrato_numero'))
    assert.equal(ordem.has('numero'), false)
  })

  test('o tipo Ordem do aplicativo acompanhou a renomeação', () => {
    const src = fonte('src/features/manutencao.ts')
    const bloco = src.slice(src.indexOf('export type Ordem = {'), src.indexOf('export type OrdensOut'))
    assert.match(bloco, /contrato_numero: number \| null/)
    assert.doesNotMatch(bloco, /^\s+numero: /m)
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 2. REGRAS
 * ═════════════════════════════════════════════════════════════════════════ */

describe('a linha "Contrato" da OS', () => {
  test('969 vira "nº 969"', () => {
    assert.equal(rotuloDoContrato(969), 'nº 969')
  })

  test('AUSENTE não vira linha — é este o "Contrato nº undefined"', () => {
    // O guarda antigo era `o.numero !== null`. Como o campo tinha sido renomeado, o valor
    // era `undefined`, e `undefined !== null` é verdadeiro: a linha era desenhada com o
    // texto "nº undefined" em TODA ordem de serviço.
    assert.equal(rotuloDoContrato(undefined), null)
    assert.equal(rotuloDoContrato(null), null)
  })

  test('NaN também não vira linha', () => {
    assert.equal(rotuloDoContrato(Number.NaN), null)
  })
})

describe('a marca de uma célula do cronograma', () => {
  const cel = (p: Partial<CelulaLida>): CelulaLida => ({
    estado: null,
    feito: false,
    dispensado: false,
    atrasado: false,
    previsto: 0,
    ...p,
  })

  test('LARANJA é "venceu o mês", e não o cinza de "no prazo"', () => {
    // O defeito: o BFF só transforma três dos cinco `cell_status` em booleano, e `laranja`
    // não tem booleano nenhum. A tela caía no `previsto > 0` e desenhava o mesmo ponto
    // cinza do azul — a atividade que ainda dá tempo de salvar ficava indistinguível da
    // que nem venceu.
    assert.equal(marcaDaCelula(cel({ estado: 'laranja', previsto: 1 })), 'alerta')
    assert.equal(marcaDaCelula(cel({ estado: 'azul', previsto: 1 })), 'previsto')
  })

  test('o laranja tem tom PRÓPRIO — se empatar com o previsto, o defeito voltou', () => {
    assert.notEqual(TOM_DA_MARCA.alerta, TOM_DA_MARCA.previsto)
    assert.equal(TOM_DA_MARCA.alerta, 'alerta')
  })

  test('dispensado NUNCA cai no ramo de feito', () => {
    // Apagar a diferença entre executado e dispensado-com-motivo era o risco de produto
    // que o meuPlano recusou correr; não se reintroduz na última tela da cadeia.
    assert.equal(marcaDaCelula(cel({ estado: 'verde_ressalva', dispensado: true })), 'dispensado')
    assert.equal(marcaDaCelula(cel({ estado: 'verde', feito: true })), 'feito')
  })

  test('vermelho é atraso, e mês sem previsão fica vazio', () => {
    assert.equal(marcaDaCelula(cel({ estado: 'vermelho', atrasado: true, previsto: 1 })), 'atrasado')
    assert.equal(marcaDaCelula(cel({})), 'vazio')
  })

  test('estado desconhecido não vira alerta por acaso', () => {
    assert.equal(marcaDaCelula(cel({ estado: 'roxo', previsto: 2 })), 'previsto')
  })
})

describe('os blocos do cronograma', () => {
  const linha = (grupo: string, previsto: number, feitos: number, meses: CelulaLida[] = []) => ({
    grupo,
    previsto_ano: previsto,
    feitos,
    meses,
  })

  test('94 linhas viram um bloco por grupo, na ordem em que apareceram', () => {
    const linhas = [
      linha('Subestação', 2, 1),
      linha('Subestação', 1, 0),
      linha('CFTV', 12, 4),
      linha('Alambrado', 1, 1),
      linha('CFTV', 4, 2),
    ]
    const blocos = agruparCronograma(linhas)
    assert.deepEqual(blocos.map((b) => b.grupo), ['Subestação', 'CFTV', 'Alambrado'])
    assert.equal(blocos[0].linhas.length, 2)
    assert.equal(blocos[1].linhas.length, 2)
  })

  test('os totais do bloco somam as linhas dele', () => {
    const blocos = agruparCronograma([linha('CFTV', 12, 4), linha('CFTV', 4, 2)])
    assert.equal(blocos[0].previsto_ano, 16)
    assert.equal(blocos[0].feitos, 6)
  })

  test('o bloco fechado conta atrasos e alertas — recolher não pode esconder notícia ruim', () => {
    const c = (p: Partial<CelulaLida>): CelulaLida => ({
      estado: null, feito: false, dispensado: false, atrasado: false, previsto: 0, ...p,
    })
    const blocos = agruparCronograma([
      linha('CFTV', 3, 0, [
        c({ estado: 'vermelho', atrasado: true, previsto: 1 }),
        c({ estado: 'laranja', previsto: 1 }),
        c({ estado: 'azul', previsto: 1 }),
      ]),
      linha('CFTV', 1, 0, [c({ estado: 'vermelho', atrasado: true, previsto: 1 })]),
    ])
    assert.equal(blocos[0].atrasos, 2)
    assert.equal(blocos[0].alertas, 1)
  })

  test('grupo em branco vira "Outras atividades", nunca um bloco sem nome', () => {
    const blocos = agruparCronograma([linha('   ', 1, 0)])
    assert.equal(blocos[0].grupo, 'Outras atividades')
  })
})

describe('o recorte de vigência', () => {
  const base = {
    mes_referencia: '2026-09',
    previsto_ate_hoje: 31,
    cumprido_ate_hoje: 13,
    pct_ate_hoje: 41.9,
    previsto_no_contrato: 269,
  }

  test('repassa o percentual do meuPlano e imprime o denominador ao lado', () => {
    const r = recorteDoCronograma(base)
    assert.ok(r)
    assert.equal(r.pct, 41.9)
    assert.equal(r.fracao, '13 de 31')
    assert.equal(r.ate, '2026-09')
    assert.equal(r.noContrato, 269)
  })

  test('NÃO refaz a conta: mudar só o percentual do servidor muda só a saída dele', () => {
    // É a lição de "13 de 270" contra "41,9 %". Se esta tela dividisse por conta própria,
    // 13/31 daria 41,9 e o teste acima passaria mesmo com a conta escondida aqui dentro —
    // por isso o percentual entra em desacordo deliberado com a fração.
    const r = recorteDoCronograma({ ...base, pct_ate_hoje: 12.5 })
    assert.ok(r)
    assert.equal(r.pct, 12.5)
    assert.equal(r.fracao, '13 de 31')
  })

  test('sem recorte publicado devolve null — e a tela mostra travessão, não 0 %', () => {
    assert.equal(
      recorteDoCronograma({
        mes_referencia: null,
        previsto_ate_hoje: null,
        cumprido_ate_hoje: null,
        pct_ate_hoje: null,
        previsto_no_contrato: null,
      }),
      null,
    )
  })

  test('recorte pela metade não inventa a fração', () => {
    const r = recorteDoCronograma({ ...base, cumprido_ate_hoje: null })
    assert.ok(r)
    assert.equal(r.fracao, null)
    assert.equal(r.pct, 41.9)
  })
})

describe('a lista de pendências', () => {
  const p = (id: number, usina: string, coluna: string, cobrada: boolean) => ({
    id, usina, coluna, cobrada_pelo_cliente: cobrada,
  })
  const itens = [
    p(1, 'Porto Ferreira', 'aguardando', true),
    p(2, 'Porto Ferreira', 'em_andamento', false),
    p(3, 'Pirapozinho', 'concluida', true),
    p(4, 'Pirapozinho', 'aguardando', false),
  ]

  test('abre em "Em aberto" e o concluído fica de fora', () => {
    assert.equal(SITUACAO_INICIAL, 'abertas')
    const visiveis = filtrarPendencias(itens, {
      usina: null, situacao: SITUACAO_INICIAL, soCobradas: false,
    })
    assert.deepEqual(visiveis.map((x) => x.id), [1, 2, 4])
  })

  test('a pendência ATRASADA continua em "Em aberto"', () => {
    // Ela mora em `coluna: aguardando`; é a `situacao` que vira "Prazo vencido". Filtrar
    // pela frase — que foi a tentação — a faria sumir de todos os recortes, e justamente
    // ela é a que o dono precisa ver.
    const atrasada = p(9, 'Porto Ferreira', 'aguardando', true)
    const visiveis = filtrarPendencias([atrasada], {
      usina: null, situacao: 'abertas', soCobradas: false,
    })
    assert.deepEqual(visiveis.map((x) => x.id), [9])
  })

  test('"cobradas por mim" e a usina se combinam, e a ordem do servidor é preservada', () => {
    const visiveis = filtrarPendencias(itens, {
      usina: 'Porto Ferreira', situacao: 'todas', soCobradas: true,
    })
    assert.deepEqual(visiveis.map((x) => x.id), [1])
    const todas = filtrarPendencias(itens, { usina: null, situacao: 'todas', soCobradas: false })
    assert.deepEqual(todas.map((x) => x.id), [1, 2, 3, 4])
  })

  test('a contagem de cada opção respeita os OUTROS filtros ligados', () => {
    const contagem = contarPorSituacao(itens, { usina: 'Pirapozinho', soCobradas: false })
    assert.equal(contagem.abertas, 1)
    assert.equal(contagem.concluidas, 1)
    assert.equal(contagem.todas, 2)
    // Nenhuma opção some da lista por estar zerada: sumir faz quem procura concluir que o
    // aplicativo perdeu o dado.
    assert.equal(SITUACOES.length, Object.keys(contagem).length)
  })

  test('abrir num recorte vazio é proibido: sem cobrança, abre em "Todas"', () => {
    assert.equal(recorteInicial(3), 0)
    assert.equal(recorteInicial(0), 1)
    assert.equal(recorteInicial(null), 1)
    assert.equal(recorteInicial(undefined), 1)
  })

  test('quando o filtro esvazia a tela, ela diz onde estão as outras', () => {
    const aviso = vazioPorFiltro(itens, {
      usina: 'Porto Ferreira', situacao: 'concluidas', soCobradas: false,
    })
    assert.match(aviso ?? '', /4 pendências/)
    // Com linha para mostrar, nenhuma frase; sem nada em lugar nenhum, também não — aí o
    // estado vazio da tela já explica, e duas explicações se contradizem.
    assert.equal(vazioPorFiltro(itens, { usina: null, situacao: 'todas', soCobradas: false }), null)
    assert.equal(vazioPorFiltro([], { usina: null, situacao: 'todas', soCobradas: false }), null)
  })
})

describe('o tom que chega do servidor', () => {
  test('um tom novo não derruba a tela — vira semDados', () => {
    assert.equal(tomValido('parado'), 'parado')
    assert.equal(tomValido('turquesa'), 'semDados')
    assert.equal(tomValido(null), 'semDados')
    assert.equal(tomValido(undefined), 'semDados')
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 3. FONTE — o que não pode voltar a existir
 * ═════════════════════════════════════════════════════════════════════════ */

describe('o código-fonte das telas', () => {
  /** As telas desta entrega. `src/app/tarefa/[id].tsx` fica de fora — ver o teste abaixo. */
  const MEUS = [
    'src/features/manutencao.ts',
    'src/features/manutencao-regras.ts',
    'src/features/pendencias.ts',
    'src/app/os/[id].tsx',
    'src/app/(tabs)/manutencao.tsx',
    'src/app/cronograma/[usinaId].tsx',
    'src/app/pendencias/index.tsx',
    'src/components/EscolhaEmLista.tsx',
  ]

  test('nenhuma tela traduz de novo a classificação nem a cor do parecer', () => {
    // Eram três cópias das mesmas funções, e por isso três resultados: `SERVICOS_ADICIONAIS`
    // saía "Servicos adicionais" numa tela e "Serviços adicionais" na outra. O BFF manda
    // `classificacao`, `classificacao_tom` e `parecer_tom` prontos.
    for (const arquivo of MEUS) {
      const src = fonte(arquivo)
      for (const morto of ['tomDaClasse', 'rotuloDaClasse', 'tomDoParecer']) {
        assert.ok(!src.includes(morto), `${arquivo} ainda menciona ${morto}`)
      }
    }
  })

  test('a tela da OS lê os campos do servidor, e o contrato passa pelo guarda', () => {
    const src = fonte('src/app/os/[id].tsx')
    assert.ok(src.includes('rotuloDoContrato(o?.contrato_numero)'))
    assert.ok(src.includes('classificacao_tom'))
    assert.ok(src.includes('parecer_tom'))
    // O número nunca é interpolado direto: era `` `nº ${o.numero}` `` que imprimia o
    // "undefined". Qualquer volta a esse padrão reprova aqui.
    assert.ok(!/`nº \$\{/.test(src), 'o número do contrato voltou a ser interpolado sem guarda')
    assert.ok(!/\bo\.numero\b/.test(src))
  })

  test('o cronograma agrupa em blocos e desenha o estado laranja', () => {
    const src = fonte('src/app/cronograma/[usinaId].tsx')
    assert.ok(src.includes('agruparCronograma'), 'as 94 linhas voltaram a ser desenhadas planas')
    // A DELEGAÇÃO, e não a simples menção ao nome: a primeira versão deste teste checava só
    // `src.includes('marcaDaCelula')`, e passou verde com a tela decidindo a marca de novo —
    // o nome ainda aparecia noutro ponto do arquivo. Um teste que passa com o defeito de
    // volta não é teste, então aqui se exige a linha que faz a delegação.
    assert.ok(
      src.includes('const marca = marcaDaCelula(c)'),
      'a marca voltou a ser decidida dentro da tela em vez de vir das regras',
    )
    for (const ramo of ['alerta', 'dispensado', 'atrasado', 'previsto']) {
      assert.ok(src.includes(`marca === '${ramo}'`), `o estado ${ramo} perdeu o desenho próprio`)
    }
  })

  test('nenhuma tela desta entrega usa chip para escolher opção', () => {
    // Regra do produto: lista suspensa pesquisável ou segmentado, de duas a duzentas opções.
    // A fileira de pílulas de usina da aba Manutenção é o caso que a motivou — a partir da
    // quarta usina ela rolava para fora da tela e escondia as opções.
    for (const arquivo of ['src/app/(tabs)/manutencao.tsx', 'src/app/pendencias/index.tsx']) {
      const src = fonte(arquivo)
      assert.ok(!/borderRadius: 999/.test(src), `${arquivo} tem pílula de seleção`)
      assert.ok(
        src.includes('EscolhaEmLista') || src.includes('Segmentado'),
        `${arquivo} precisa escolher por lista suspensa ou segmentado`,
      )
    }
  })

  test('a lista de pendências não promete navegação que não existe', () => {
    // Sem tela de detalhe no aplicativo, uma seta faria o dono tocar e concluir que travou.
    const src = fonte('src/app/pendencias/index.tsx')
    assert.ok(!src.includes('<Chevron'), 'a lista ganhou seta sem ter para onde ir')
  })

  test('DÍVIDA DECLARADA: a terceira cópia da cor do parecer segue de pé', () => {
    // `src/app/tarefa/[id].tsx` está FORA da lista de arquivos desta entrega (outro agente
    // pode estar escrevendo nele agora), então a cópia não foi removida lá. Este teste
    // fixa a dívida em vez de escondê-la: no dia em que alguém apagar a função de lá, ele
    // reprova e manda apagar esta exceção junto — e é assim que a dívida não vira ruína.
    const src = fonte('src/app/tarefa/[id].tsx')
    assert.ok(
      src.includes('tomDoParecer'),
      'a cópia de tomDoParecer saiu de src/app/tarefa/[id].tsx — apague esta exceção e '
        + 'inclua o arquivo na lista MEUS acima',
    )
  })
})
