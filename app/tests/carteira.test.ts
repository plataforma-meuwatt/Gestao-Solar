/**
 * O que este arquivo guarda.
 *
 * O aplicativo era o único consumidor do BFF sem um teste sequer — e foi por aí que
 * `OrdemOut.numero` virou `contrato_numero` no servidor e o celular passou a imprimir
 * "Contrato nº undefined" em toda ordem, intermitente por causa do cache em disco. Cada
 * teste abaixo diz, na primeira linha, qual defeito ele impede de voltar.
 *
 * **Como rodar** (sem dependência nova, sem instalação):
 *
 * ```
 * cd app && node --test tests/carteira.test.ts
 * ```
 *
 * O Node 24 executa TypeScript por remoção de tipos e traz o executor de testes embutido.
 * O que ele não sabe fazer é resolver o apelido `@/…` do Metro nem carregar `lib/cache`,
 * que arrasta React Native inteiro — daí os ganchos abaixo, que resolvem o apelido para o
 * arquivo real e trocam SÓ o módulo de rede por um duplo. Ninguém aqui testa a rede: o que
 * se testa é a régua, que é aritmética e texto.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { join } from 'node:path'
import test from 'node:test'
import { pathToFileURL } from 'node:url'

const RAIZ = join(import.meta.dirname, '..', 'src')

registerHooks({
  resolve(especificador: string, contexto: unknown, proximo: (e: string, c: unknown) => unknown) {
    // `lib/cache` só existe dentro do aparelho: importa expo-file-system, react-query e
    // react-native. O duplo entrega uma função com a mesma assinatura e nada mais — o
    // `useComparativo` não é exercitado aqui, e chamar um hook fora do React nem faria
    // sentido.
    if (especificador === '@/lib/cache') {
      return { url: 'duplo:cache', shortCircuit: true }
    }
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
    return proximo(url, contexto)
  },
})

const { fraseDaJanela, ordenarPeloRanking, periodoDaCarteira, rankingDe } =
  await import('../src/features/carteira')
type Janela = import('../src/features/carteira').Janela
type Ranking = import('../src/features/carteira').Ranking

/* ------------------------------------------------------------------ auxílio */

/** Uma usina do comparativo, com só o que cada teste precisa dizer. */
function usina(id: number, nome: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    nome,
    cidade: null,
    uf: null,
    capacidade_kwp: 1000,
    energia_kwh: null,
    energia_comparavel_kwh: null,
    produtividade_kwh_kwp: null,
    pr_pct: null,
    disponibilidade_real_pct: null,
    disponibilidade_contratual_pct: null,
    perdas_paradas_kwh: null,
    irradiacao_hpoa: null,
    irradiacao_ghi: null,
    paradas_pendentes: null,
    meses_medidos: [],
    motivo: null,
    ...extra,
  }
}

function ranking(itens: Array<[number, string, number, boolean?]>, extra: Partial<Ranking> = {}) {
  return {
    chave: 'produtividade',
    titulo: 'Produtividade',
    pergunta: 'Qual usina rende mais para o tamanho que tem?',
    nota: null,
    unidade: 'kWh/kWp',
    ordem: 'desc',
    fora: [],
    ...extra,
    itens: itens.map(([usina_id, nome, valor, empatado]) => ({
      posicao: 0,
      usina_id,
      usina: nome,
      valor,
      empatado: empatado ?? false,
      denominador: null,
    })),
  } as Ranking
}

/** O mesmo, mas com as posições escritas à mão — é o servidor quem as decide. */
function comPosicoes(r: Ranking, posicoes: number[]): Ranking {
  return { ...r, itens: r.itens.map((i, n) => ({ ...i, posicao: posicoes[n] })) }
}

/* --------------------------------------------------------------- o período */

test('o mês pedido vai do dia 1 ao último dia — inclusive em fevereiro bissexto', () => {
  /* Defeito que guarda: montar o fim do mês com uma tabela de 30/31 dias, ou com
     `new Date('2028-02-01')`, que é meia-noite UTC e no fuso do Brasil volta janeiro. */
  assert.deepEqual(periodoDaCarteira('2028-02-17', 'mes'), { de: '2028-02-01', ate: '2028-02-29' })
  assert.deepEqual(periodoDaCarteira('2026-02-17', 'mes'), { de: '2026-02-01', ate: '2026-02-28' })
  assert.deepEqual(periodoDaCarteira('2026-09-05', 'mes'), { de: '2026-09-01', ate: '2026-09-30' })
})

test('o mês em curso pede o mês INTEIRO, não "até hoje"', () => {
  /* Defeito que guarda: travar o fim em hoje aqui dentro. Quem trava é o servidor
     (`truncada_em_hoje`); mandar daqui uma data que muda todo dia trocaria a chave do
     cache do aparelho a cada abertura — e o cache é o que faz a tela abrir no pátio sem
     sinal. Duas referências do mesmo mês têm de dar exatamente o mesmo par de datas. */
  assert.deepEqual(periodoDaCarteira('2026-09-01', 'mes'), periodoDaCarteira('2026-09-28', 'mes'))
})

test('o ano pedido vai de 1º de janeiro a 31 de dezembro', () => {
  /* Defeito que guarda: pedir o ano a partir do mês da referência ("de 2026-09-01"), que
     compararia doze meses de uma usina com quatro de outra sem ninguém perceber. */
  assert.deepEqual(periodoDaCarteira('2026-09-05', 'ano'), { de: '2026-01-01', ate: '2026-12-31' })
})

/* ---------------------------------------------------------------- a ordem */

test('a ordem é a do servidor, mesmo quando discorda de uma ordenação local', () => {
  /* Defeito que guarda: ordenar aqui por `produtividade_kwh_kwp`. Parece inofensivo e é o
     erro mais caro deste projeto — a mesma usina apareceu com -64,3 % numa tela e +101,7 %
     na outra. O valor do ranking sai da JANELA COMUM; o campo da linha, do período pedido.
     Ordenar pelo campo poria Alfa em primeiro no celular e em terceiro no computador. */
  const usinas = [
    usina(1, 'Alfa', { produtividade_kwh_kwp: 200 }),
    usina(2, 'Beta', { produtividade_kwh_kwp: 70 }),
    usina(3, 'Gama', { produtividade_kwh_kwp: 90 }),
  ]
  const r = comPosicoes(ranking([[3, 'Gama', 90], [2, 'Beta', 70], [1, 'Alfa', 50]]), [1, 2, 3])

  const { ordenadas, fora } = ordenarPeloRanking(usinas, r)

  assert.deepEqual(ordenadas.map((l) => l.usina.nome), ['Gama', 'Beta', 'Alfa'])
  assert.deepEqual(ordenadas.map((l) => l.valor), [90, 70, 50])
  assert.deepEqual(fora, [])
})

test('empate mantém a posição repetida que o servidor mandou', () => {
  /* Defeito que guarda: renumerar as posições na tela (1, 2, 3). O servidor divide o
     empate de propósito — 1, 1, 3 —, porque desempatar coroaria uma usina pela inicial
     dela. Renumerar aqui inventa um vencedor que ninguém mediu. */
  const usinas = [usina(1, 'Alfa'), usina(2, 'Beta'), usina(3, 'Gama')]
  const r = comPosicoes(
    ranking([[1, 'Alfa', 90, true], [2, 'Beta', 90, true], [3, 'Gama', 10]]),
    [1, 1, 3],
  )

  const { ordenadas } = ordenarPeloRanking(usinas, r)

  assert.deepEqual(ordenadas.map((l) => l.posicao), [1, 1, 3])
  assert.deepEqual(ordenadas.map((l) => l.empatado), [true, true, false])
})

test('usina sem dado no período fica FORA da ordem, com o motivo do servidor', () => {
  /* Defeito que guarda: completar a lista ordenada com quem o servidor excluiu. A usina
     sem medição apareceria em último lugar, com 0,0 kWh/kWp — que se lê como "rendeu
     nada" quando o que houve foi a ponte cair. Ela continua na tela, mas com travessão. */
  const usinas = [
    usina(1, 'Alfa', { produtividade_kwh_kwp: 90 }),
    usina(2, 'Beta', { motivo: 'Monitoramento indisponível: tempo esgotado' }),
  ]
  const r = comPosicoes(ranking([[1, 'Alfa', 90]]), [1])

  const { ordenadas, fora } = ordenarPeloRanking(usinas, r)

  assert.deepEqual(ordenadas.map((l) => l.usina.nome), ['Alfa'])
  assert.deepEqual(fora.map((u) => u.nome), ['Beta'])
  assert.equal(fora[0].motivo, 'Monitoramento indisponível: tempo esgotado')
})

test('sem ranking, NADA é ordenado — a tela não inventa uma ordem própria', () => {
  /* Defeito que guarda: cair numa ordenação local quando o bloco de energia não trouxe o
     ranking (upstream fora do ar, bloco não pedido). Seria a segunda régua, nascendo
     justamente no momento em que ninguém tem como conferi-la. */
  const usinas = [usina(1, 'Alfa', { produtividade_kwh_kwp: 10 }), usina(2, 'Beta')]

  const { ordenadas, fora } = ordenarPeloRanking(usinas, undefined)

  assert.deepEqual(ordenadas, [])
  assert.deepEqual(fora.map((u) => u.nome), ['Alfa', 'Beta'])
})

test('id que o ranking cita e a lista não tem é ignorado — nunca vira linha fantasma', () => {
  /* Defeito que guarda: montar a linha com o `usina` do próprio ranking. Sairia uma usina
     sem capacidade, sem energia e sem toque, misturada às reais. */
  const usinas = [usina(1, 'Alfa', { produtividade_kwh_kwp: 90 })]
  const r = comPosicoes(ranking([[9, 'Usina de outro escopo', 999], [1, 'Alfa', 90]]), [1, 2])

  const { ordenadas } = ordenarPeloRanking(usinas, r)

  assert.deepEqual(ordenadas.map((l) => l.usina.nome), ['Alfa'])
})

test('rankingDe não cai no primeiro da lista quando a chave não existe', () => {
  /* Defeito que guarda: `bloco.rankings[0]` como reserva. A ordem dos rankings é do
     servidor: a tela mostraria energia absoluta sob o título de produtividade — duas
     perguntas diferentes com a mesma cara. */
  const bloco = {
    usinas: [],
    totais: {
      usinas_no_total: 0,
      energia_kwh: null,
      capacidade_kwp: null,
      produtividade_kwh_kwp: null,
      perdas_paradas_kwh: null,
    },
    rankings: [ranking([], { chave: 'energia', titulo: 'Energia' })],
  }

  assert.equal(rankingDe(bloco, 'produtividade'), undefined)
  assert.equal(rankingDe(bloco, 'energia')?.chave, 'energia')
  assert.equal(rankingDe(null, 'energia'), undefined)
})

/* ---------------------------------------------------------------- a janela */

function janela(extra: Partial<Janela> = {}): Janela {
  return {
    de: '2026-01-01',
    ate: '2026-12-31',
    meses: [],
    meses_comuns: [],
    rotulo: null,
    completa: true,
    encolhida_por: [],
    fora_da_comparacao: [],
    sem_detalhe: [],
    comparaveis: 0,
    nota: null,
    truncada_em_hoje: false,
    ...extra,
  }
}

test('a janela é declarada com as palavras do servidor, e a nota vem junto', () => {
  /* Defeito que guarda: mostrar o ranking sem dizer de que período ele fala. Duas usinas
     com datas de entrada diferentes não têm o mesmo período medido, e comparar doze meses
     com quatro sem escrever isso é o jeito silencioso de mentir. */
  assert.equal(fraseDaJanela(janela({ rotulo: 'ago de 2026' })), 'ago de 2026')
  assert.equal(
    fraseDaJanela(
      janela({
        rotulo: 'jun a set de 2026',
        completa: false,
        nota: 'Porto Ferreira mede desde junho.',
      }),
    ),
    'jun a set de 2026 · Porto Ferreira mede desde junho.',
  )
})

test('sem rótulo, a tela não escreve período nenhum', () => {
  /* Defeito que guarda: uma frase de reserva do tipo "período completo". Seria afirmar uma
     cobertura que ninguém conferiu — exatamente o que a janela comum existe para impedir. */
  assert.equal(fraseDaJanela(janela()), null)
  assert.equal(fraseDaJanela(janela({ rotulo: '   ' })), null)
  assert.equal(fraseDaJanela(null), null)
  assert.equal(fraseDaJanela(undefined), null)
})

/* ------------------------------------------------------------ vocabulário */

/**
 * As telas que AINDA nomeiam o produto para o cliente, com o dono de cada arquivo.
 *
 * Não é uma lista para onde empurrar o que dá trabalho: o teste falha nos dois sentidos —
 * arquivo novo com o nome próprio entra em falha, e arquivo já corrigido que continue aqui
 * também. Os dois abaixo estão fora do meu alcance nesta leva (outro agente escreve neles
 * agora); a régua que decide o vocabulário é a de `bff/tests/test_vocabulario_do_cliente.py`.
 */
const PENDENTES: Record<string, string> = {
  'assistente.tsx': 'A descrição do estado vazio cita o sistema de manutenção pelo nome.',
  'manutencao.tsx': 'A frase de lista vazia cita o sistema de manutenção pelo nome.',
}

/**
 * Remove comentários, deixando só o que pode chegar à tela.
 *
 * O comentário que explica de onde vem o dado é obrigação de quem mantém o arquivo — o que
 * não pode é a explicação viajar para o cliente. A linha de comentário só é reconhecida
 * quando `//` abre um trecho (início de linha ou depois de espaço), para não decepar
 * `https://` dentro de um texto.
 */
function semComentarios(fonte: string): string {
  return fonte.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|\s)\/\/[^\n]*/g, '$1')
}

function telas(pasta: string): string[] {
  return readdirSync(pasta, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory()
      ? telas(join(pasta, e.name))
      : e.name.endsWith('.tsx') || e.name.endsWith('.ts')
        ? [join(pasta, e.name)]
        : [],
  )
}

test('nenhuma tela escreve o nome do produto para o cliente', () => {
  /* Defeito que guarda: o cliente descobrir, por um chip de canto de tela ou pela linha de
     apoio do login, que existem dois outros sistemas com nome próprio — nos quais ele não
     tem conta, cujo nome não conhece e a quem não tem como cobrar. O portal é um só; foi
     essa a frase do dono que criou a regra. O nome escrito para gente é sempre camelCase,
     e é isso que se procura: `tem_meuwatt`, que é campo do servidor, não aparece na tela. */
  const encontrados: Record<string, string> = {}

  for (const arquivo of telas(join(RAIZ, 'app'))) {
    const achado = semComentarios(readFileSync(arquivo, 'utf8')).match(/meuWatt|meuPlano/)
    if (achado) encontrados[arquivo.split(/[\\/]/).pop()!] = achado[0]
  }

  const sobrando = Object.keys(encontrados).filter((a) => !(a in PENDENTES))
  assert.deepEqual(
    sobrando,
    [],
    `estas telas escrevem o nome do produto para o cliente: ${sobrando.join(', ')}`,
  )

  const jaCorrigidos = Object.keys(PENDENTES).filter((a) => !(a in encontrados))
  assert.deepEqual(
    jaCorrigidos,
    [],
    `estas telas já foram corrigidas — tire-as de PENDENTES: ${jaCorrigidos.join(', ')}`,
  )
})

test('as duas telas desta entrega falam do serviço, não do produto', () => {
  /* Defeito que guarda: trocar o texto por outro nome próprio, ou por um genérico que não
     diz nada ("outros sistemas"). O vocabulário é o mesmo que o BFF já usa nas rotas do
     cliente: monitoramento e manutenção. */
  const usina = readFileSync(join(RAIZ, 'app', 'usina', '[id]', 'index.tsx'), 'utf8')
  assert.match(semComentarios(usina), /'Monitoramento'/)
  assert.match(semComentarios(usina), /'Manutenção'/)

  const login = semComentarios(readFileSync(join(RAIZ, 'app', 'login.tsx'), 'utf8'))
  assert.match(login, /monitoramento e de manutenção/)
})
