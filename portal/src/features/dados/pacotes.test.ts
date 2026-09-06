/**
 * A régua de "Baixar dados", guardada por teste — porque paridade que se confere lendo o diff
 * não é paridade, é lembrança.
 *
 * **O defeito que este arquivo existe para impedir tem nome e história.** A primeira versão
 * desta tela cortou capacidade sem cortar contrato: os quatro blocos foram para trás de uma
 * gaveta chamada "Escolher coluna por coluna", e escolher inversor por skid — que é
 * literalmente o que o diretor do cliente pediu — passou a exigir descobrir a gaveta, abri-la,
 * trocar o agrupamento e marcar um a um. O dono recusou. Cortar é fácil e some no diff; por
 * isso a paridade aqui é **numérica**: 4 + 7 + 1 + 2 = 14 linhas de variável, 2 agrupamentos
 * em cada um dos 3 blocos que têm agrupamento, 5 passos. Apagar uma linha reprova um teste.
 *
 * As outras seis coisas que ele guarda, cada uma um defeito real:
 *
 * 1. **A umidade não some da lista.** Ela era omitida do vetor de clima — a única violação da
 *    própria regra da tela. Quem não vê a linha conclui que o PORTAL não oferece; o fato é
 *    que nenhuma estação envia o dado (`load_options` devolve `"umidade": False` fixo). Fica
 *    na lista, desabilitada, com o motivo.
 * 2. **Ninguém desabilita sem dizer por quê.** Varredura: zero opções com `desabilitada` e
 *    `detalhe` vazio, em todos os blocos e nas duas usinas de teste.
 * 3. **`paradas` no passo nativo.** Medido na rota real: o servidor NÃO recusa — devolve as
 *    abas `['Leia-me','Inversores','Paradas']` e some, calado, com as colunas "Min. desligado"
 *    (`tem_paradas = … and win.step != "native"`). Metade da promessa evapora depois de trinta
 *    e cinco segundos de espera. Vira impedimento, com a saída nomeada.
 * 4. **O teto de dias vem do servidor, sempre.** Nenhum literal `7`/`31`/`92`/`366` no código
 *    da régua: sem a chave, `tetoDeDias` devolve `null` e a tela não impede nada. Um mapa de
 *    reserva parece prudência e é a pior mentira — continuaria recusando pelo número velho.
 * 5. **O ajuste do passo fala.** Era silencioso: o cliente escolhia 5 minutos, esticava o
 *    período e recebia um arquivo de hora em hora sem ler a palavra "hora".
 * 6. **A conta de colunas de skid.** Nem o portal (`Math.min(nSkids, series.length)`) nem a
 *    tela do meuWatt (`opts.skids.length` cru) respondiam "quantos skids ainda têm ao menos um
 *    inversor marcado". Medido na rota real: 8 inversores em 2 de 5 skids devolvem um arquivo
 *    com exatamente 2 colunas de skid.
 *
 * As duas usinas de teste são retratos de opções reais medidas hoje: `PORTO` é Porto Ferreira
 * (5 skids × 4 inversores, estação com POA/GHI e sem os demais sensores, relé, 5 leitores) e
 * `MAGRA` é a usina que quase não tem nada — o caso em que todos os motivos aparecem juntos.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import type { OpcoesDeDados, Passo, Selecao } from '@/features/dados/api'
import {
  AGRUPAMENTO_DA_FRONTEIRA,
  AGRUPAMENTO_DO_INVERSOR,
  AGRUPAMENTO_DO_SISTEMA,
  PASSOS,
  TOTAL_DE_VARIAVEIS,
  VARIAVEIS_DA_ESTACAO,
  VARIAVEIS_DA_FRONTEIRA,
  VARIAVEIS_DO_INVERSOR,
  VARIAVEIS_DO_SISTEMA,
  ajustarPasso,
  avisoDeOrcamento,
  diasOferecidos,
  estimativa,
  impedimento,
  janelaDo,
  linhaDeRetencao,
  motivoDaEstacao,
  motivoDeRetencao,
  motivoDoInversor,
  opcoesDaEstacao,
  opcoesDaFronteira,
  opcoesDePasso,
  opcoesDoInversor,
  opcoesDoSistema,
  passoSugerido,
  tetoDeDias,
} from '@/features/dados/pacotes'

/* ------------------------------------------------------------- as duas usinas */

/** Os tetos como o servidor os manda. Nada aqui é a régua repetindo: é a resposta dele. */
const LIMITES: Record<string, number> = {
  native: 7,
  '5m': 31,
  '15m': 92,
  '1h': 366,
  '1d': 366,
  max_celulas: 2_000_000,
}

function skid(n: number, quantos: number) {
  return {
    id: n,
    nome: `SKID-0${n}`,
    capacidade_kwp: 1480,
    series: Array.from({ length: quantos }, (_, i) => ({
      chave: `slot:${n * 100 + i}`,
      rotulo: `Inv ${n * 100 + i}`,
      numero_serie: `SN${n * 100 + i}`,
      capacidade_kwp: 370,
    })),
  }
}

/**
 * O próprio código da régua, para as duas varreduras que leem o texto dele.
 *
 * Lido a partir de `process.cwd()` (a raiz do portal, onde o vitest roda) e não de
 * `import.meta.url`: sob o ambiente jsdom a URL do módulo não tem esquema `file:`, e
 * `readFileSync` recusa.
 */
const FONTE = readFileSync(resolve(process.cwd(), 'src/features/dados/pacotes.ts'), 'utf8')

/** Porto Ferreira, como as opções vieram da rota hoje. */
const PORTO: OpcoesDeDados = {
  usina: { id: 4, nome: 'Porto Ferreira', capacidade_kwp: 7400 },
  skids: [skid(1, 4), skid(2, 4), skid(3, 4), skid(4, 4), skid(5, 4)],
  estacao: {
    disponivel: true,
    colunas: {
      poa: true,
      ghi: true,
      temp_modulo: false,
      temp_ambiente: false,
      vento: false,
      umidade: false,
    },
    temp_ambiente_rele: true,
  },
  leitores: [
    { id: 14, nome: 'Leitor Concessionaria SKID 1' },
    { id: 10, nome: 'Leitor Concessionaria SKID 2' },
    { id: 11, nome: 'Leitor Concessionaria SKID 3' },
    { id: 12, nome: 'Leitor Concessionaria SKID 4' },
    { id: 13, nome: 'Leitor Concessionaria SKID 5' },
  ],
  sistema: { pr: true, produtividade: true },
  retencao: { snapshots_desde: '2026-03-06', ssu_desde: '2024-09-05' },
  limites: LIMITES,
}

/** A usina que quase não tem nada: sem inversor, sem estação, sem relé, sem medidor. */
const MAGRA: OpcoesDeDados = {
  usina: { id: 99, nome: 'Usina Magra', capacidade_kwp: null },
  skids: [],
  estacao: {
    disponivel: false,
    colunas: {
      poa: false,
      ghi: false,
      temp_modulo: false,
      temp_ambiente: false,
      vento: false,
      umidade: false,
    },
    temp_ambiente_rele: false,
  },
  leitores: [],
  sistema: { pr: false, produtividade: false },
  retencao: { snapshots_desde: '2026-03-06', ssu_desde: '2024-09-05' },
  limites: LIMITES,
}

/**
 * Uma usina grande de verdade — 30 skids × 20 inversores. Existe por um motivo medido: Porto
 * Ferreira **não alcança** o orçamento de células do servidor (o maior pedido possível dentro
 * da retenção dá ~900 mil), então o aviso de orçamento só pode ser provado numa usina em que
 * ele de fato morde.
 */
const GRANDE: OpcoesDeDados = {
  ...PORTO,
  usina: { id: 100, nome: 'Usina Grande', capacidade_kwp: 220_000 },
  skids: Array.from({ length: 30 }, (_, i) => skid(i + 1, 20)),
}

const TODOS_OS_BLOCOS = (o: OpcoesDeDados, passo: Passo): Opcoes[] => [
  opcoesDoInversor(o, passo),
  opcoesDaEstacao(o),
  opcoesDaFronteira(o),
  opcoesDoSistema(o, passo),
]
type Opcoes = ReturnType<typeof opcoesDaEstacao>

const janelaDeUmDia = janelaDo('2026-09-03', '2026-09-03', '00:00', '23:59', '5m', false)

/* ------------------------------------------------------------------ paridade */

describe('paridade com a tela do meuWatt — contada, não lembrada', () => {
  it('oferece as catorze linhas de variável: 4 + 7 + 1 + 2', () => {
    expect(VARIAVEIS_DO_INVERSOR).toHaveLength(4)
    expect(VARIAVEIS_DA_ESTACAO).toHaveLength(7)
    expect(VARIAVEIS_DA_FRONTEIRA).toHaveLength(1)
    expect(VARIAVEIS_DO_SISTEMA).toHaveLength(2)
    expect(TOTAL_DE_VARIAVEIS).toBe(14)
  })

  it('oferece exatamente as quatro variáveis de inversor do contrato', () => {
    expect(VARIAVEIS_DO_INVERSOR.map((v) => v.chave)).toEqual([
      'geracao',
      'potencia',
      'status',
      'paradas',
    ])
  })

  it('oferece as sete linhas de estação, inclusive a umidade que nenhuma usina tem', () => {
    expect(VARIAVEIS_DA_ESTACAO.map((v) => v.chave)).toEqual([
      'poa',
      'ghi',
      'temp_modulo',
      'temp_ambiente',
      'vento',
      'umidade',
      'temp_ambiente_rele',
    ])
  })

  it('oferece as duas do sistema', () => {
    expect(VARIAVEIS_DO_SISTEMA.map((v) => v.chave)).toEqual(['pr', 'produtividade'])
  })

  it('oferece os dois agrupamentos de cada um dos três blocos que têm agrupamento', () => {
    expect(AGRUPAMENTO_DO_INVERSOR.map((a) => a.valor)).toEqual(['lista', 'skid'])
    expect(AGRUPAMENTO_DA_FRONTEIRA.map((a) => a.valor)).toEqual(['leitor', 'usina'])
    expect(AGRUPAMENTO_DO_SISTEMA.map((a) => a.valor)).toEqual(['usina', 'skid'])
  })

  it('oferece os cinco passos, do mais grosso ao mais fino', () => {
    expect(PASSOS).toEqual(['1d', '1h', '15m', '5m', 'native'])
    expect(opcoesDePasso(LIMITES)).toHaveLength(5)
  })

  it('toda linha tem ajuda escrita — a segunda linha que diz o que o número é', () => {
    const todas = [
      ...VARIAVEIS_DO_INVERSOR,
      ...VARIAVEIS_DA_ESTACAO,
      ...VARIAVEIS_DA_FRONTEIRA,
      ...VARIAVEIS_DO_SISTEMA,
    ]
    for (const v of todas) expect(v.ajuda.length).toBeGreaterThan(10)
  })
})

/* ------------------------------------------------- nada some, tudo diz por quê */

describe('nenhuma linha some; a que não serve diz por quê', () => {
  it('mostra a umidade sempre, sempre desabilitada, sempre com motivo', () => {
    for (const usina of [PORTO, MAGRA]) {
      const umidade = opcoesDaEstacao(usina).find((o) => o.valor === 'umidade')
      expect(umidade).toBeDefined()
      expect(umidade?.desabilitada).toBe(true)
      expect(umidade?.detalhe).toMatch(/nenhuma estação envia umidade/i)
    }
    // E o motivo não depende de a usina ter estação: é fato sobre o produto.
    expect(motivoDaEstacao('umidade', PORTO)).toBe(motivoDaEstacao('umidade', MAGRA))
  })

  it('NUNCA desabilita sem detalhe — varredura dos quatro blocos, nas duas usinas', () => {
    let vistas = 0
    for (const usina of [PORTO, MAGRA]) {
      for (const passo of PASSOS) {
        for (const bloco of TODOS_OS_BLOCOS(usina, passo)) {
          for (const o of bloco) {
            vistas += 1
            if (o.desabilitada) expect(o.detalhe.trim().length).toBeGreaterThan(0)
          }
        }
      }
    }
    // 2 usinas × 5 passos × 14 linhas: a varredura cobriu a régua inteira, não uma amostra.
    expect(vistas).toBe(2 * 5 * 14)
  })

  it('dá o motivo pela CAUSA e não pela chave: sem estação × sensor não coletado', () => {
    // Porto TEM estação, mas ela não traz vento: a conversa é "importar o registrador".
    expect(motivoDaEstacao('vento', PORTO)).toMatch(/não coleta esta grandeza/i)
    // A magra não tem estação nenhuma: a conversa é outra.
    expect(motivoDaEstacao('poa', MAGRA)).toMatch(/não tem estação solarimétrica/i)
    expect(motivoDaEstacao('poa', PORTO)).toBeNull()
  })

  it('diz o relé e o medidor com as palavras deles', () => {
    expect(motivoDaEstacao('temp_ambiente_rele', PORTO)).toBeNull()
    expect(motivoDaEstacao('temp_ambiente_rele', MAGRA)).toMatch(/relé de temperatura/i)
    expect(opcoesDaFronteira(MAGRA)[0].detalhe).toMatch(/medidor de fronteira/i)
    expect(opcoesDaFronteira(PORTO)[0].desabilitada).toBeUndefined()
  })

  it('conta a cadeia inteira do PR, em vez de só o último elo', () => {
    const pr = opcoesDoSistema(MAGRA, '1h').find((o) => o.valor === 'pr')
    expect(pr?.desabilitada).toBe(true)
    expect(pr?.detalhe).toMatch(/sem estação não há irradiação, e sem irradiação/i)
  })
})

/* ------------------------------------------------------ as duas omissões mudas */

describe('as duas omissões silenciosas do servidor viram fala', () => {
  it('status fora do passo nativo: desabilitado na linha E impedido no pedido', () => {
    const status = opcoesDoInversor(PORTO, '15m').find((o) => o.valor === 'status')
    expect(status?.desabilitada).toBe(true)
    expect(status?.detalhe).toMatch(/texto por leitura/i)
    expect(opcoesDoInversor(PORTO, 'native').find((o) => o.valor === 'status')?.desabilitada)
      .toBeUndefined()

    const sel: Selecao = {
      inversores: { variaveis: ['geracao', 'status'], agrupamento: 'lista', series: null },
      estacao: null,
      fronteira: null,
      sistema: null,
    }
    const imp = impedimento(sel, '15m', janelaDeUmDia, '2026-09-03', PORTO)
    expect(imp?.texto).toMatch(/Situação do inversor/)
  })

  it('paradas no passo nativo: impedida, com a saída nomeada (medido: as colunas somem)', () => {
    const motivo = motivoDoInversor('paradas', PORTO, 'native')
    expect(motivo).toMatch(/minutos desligados por intervalo não saem/i)
    expect(motivo).toMatch(/a cada 5 minutos/i)

    const linha = opcoesDoInversor(PORTO, 'native').find((o) => o.valor === 'paradas')
    expect(linha?.desabilitada).toBe(true)

    const sel: Selecao = {
      inversores: { variaveis: ['geracao', 'paradas'], agrupamento: 'lista', series: null },
      estacao: null,
      fronteira: null,
      sistema: null,
    }
    const nativa = janelaDo('2026-09-03', '2026-09-03', '00:00', '23:59', 'native', false)
    expect(impedimento(sel, 'native', nativa, '2026-09-03', PORTO)?.texto).toMatch(
      /Intervalos desligados/,
    )
    // Em qualquer passo com balde, o mesmo pedido passa.
    expect(impedimento(sel, '5m', janelaDeUmDia, '2026-09-03', PORTO)).toBeNull()
    expect(motivoDoInversor('paradas', PORTO, '5m')).toBeNull()
  })
})

/* ------------------------------------------------------------ teto de dias */

describe('o teto de dias é do servidor, e sem ele a tela não impede nada', () => {
  it('lê os cinco tetos do que o servidor mandou', () => {
    expect(PASSOS.map((p) => tetoDeDias(LIMITES, p))).toEqual([366, 366, 92, 31, 7])
  })

  it('devolve null quando o servidor não mandou a chave — e aí nada é impedido', () => {
    expect(tetoDeDias({}, 'native')).toBeNull()
    expect(tetoDeDias({ max_celulas: 10 }, '5m')).toBeNull()
    expect(tetoDeDias({ '5m': Number.NaN }, '5m')).toBeNull()

    const sel: Selecao = {
      inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: null },
      estacao: null,
      fronteira: null,
      sistema: null,
    }
    const semNada: OpcoesDeDados = {
      ...PORTO,
      limites: {},
      retencao: { snapshots_desde: null, ssu_desde: null },
    }
    const enorme = janelaDo('2020-01-01', '2026-09-03', '00:00', '23:59', 'native', false)
    expect(enorme.dias).toBeGreaterThan(2000)
    expect(impedimento(sel, 'native', enorme, '2020-01-01', semNada)).toBeNull()
  })

  it('não escreve nenhum teto de dias na régua — o número mora no servidor', () => {
    const semComentario = FONTE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
    for (const literal of ['7', '31', '92', '366']) {
      expect(new RegExp(`\\b${literal}\\b`).test(semComentario)).toBe(false)
    }
  })

  it('carrega "até N dias por arquivo" no detalhe, sem desabilitar nenhuma opção', () => {
    const opcoes = opcoesDePasso(LIMITES)
    expect(opcoes.find((o) => o.valor === 'native')?.detalhe).toBe('até 7 dias por arquivo')
    expect(opcoes.find((o) => o.valor === '15m')?.detalhe).toBe('até 92 dias por arquivo')
    for (const o of opcoes) expect(o.desabilitada).toBeUndefined()
    // Sem os tetos, o detalhe some — e não vira um número inventado.
    for (const o of opcoesDePasso({})) expect(o.detalhe).toBeUndefined()
  })

  it('impede o período que estoura o teto, com a conta feita e a saída nomeada', () => {
    const sel: Selecao = {
      inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: null },
      estacao: null,
      fronteira: null,
      sistema: null,
    }
    // 65 dias: estoura os 31 do passo de 5 minutos e ainda cabe nos 92 do de 15.
    const j = janelaDo('2026-07-01', '2026-09-03', '00:00', '23:59', '5m', false)
    expect(j.dias).toBe(65)
    const imp = impedimento(sel, '5m', j, '2026-07-01', PORTO)
    expect(imp?.texto).toContain('65 dias')
    expect(imp?.texto).toContain('aceita 31')
    expect(imp?.texto).toMatch(/Escolha "a cada 15 minutos" \(aceita 92\)/)
  })
})

/* ------------------------------------------------------ o ajuste que anuncia */

describe('o passo que a tela ajusta sozinha ANUNCIA que ajustou', () => {
  it('cala quando o passo pedido cabe', () => {
    expect(ajustarPasso('5m', 30, LIMITES)).toEqual({ passo: '5m', aviso: null })
  })

  it('devolve o passo novo E a frase que diz o que fez e por quê', () => {
    const r = ajustarPasso('5m', 60, LIMITES)
    expect(r.passo).toBe('15m')
    expect(r.aviso).toContain('60 dias')
    expect(r.aviso).toContain('aceita 31')
    expect(r.aviso).toMatch(/Ajustei para "a cada 15 minutos"/)
  })

  it('fala também quando NENHUM detalhe alcança — em vez de trocar calado', () => {
    const r = ajustarPasso('5m', 400, LIMITES)
    expect(r.passo).toBe('1d')
    expect(r.aviso).toContain('400 dias')
    expect(r.aviso).toMatch(/nenhum detalhe alcança tanto \(o máximo é 366\)/)
    expect(r.aviso).toMatch(/encurte o período/i)
  })

  it('engrossa o mínimo necessário — preserva o detalhe que couber', () => {
    expect(ajustarPasso('native', 20, LIMITES).passo).toBe('5m')
    expect(ajustarPasso('native', 200, LIMITES).passo).toBe('1h')
  })

  it('abre no detalhe do recorte, e avisa quando teve de engrossar', () => {
    expect(passoSugerido('dia', 1, LIMITES)).toEqual({ passo: '15m', aviso: null })
    expect(passoSugerido('mes', 31, LIMITES)).toEqual({ passo: '1h', aviso: null })
    expect(passoSugerido('ano', 366, LIMITES)).toEqual({ passo: '1d', aviso: null })
    expect(passoSugerido('livre', 200, LIMITES)).toEqual({ passo: '1h', aviso: null })
    // 120 dias no recorte de dia: "a cada 15 minutos" aceita 92, então engrossa — e avisa.
    const esticado = passoSugerido('dia', 120, LIMITES)
    expect(esticado.passo).toBe('1h')
    expect(esticado.aviso).toMatch(/Ajustei para "de hora em hora"/)
  })
})

/* ------------------------------------------------------------------ retenção */

describe('retenção: as duas datas, e a linha trocando conforme a seleção', () => {
  const soMedidor: Selecao = {
    inversores: null,
    estacao: null,
    fronteira: { variaveis: ['energia'], agrupamento: 'leitor' },
    sistema: null,
  }
  const comInversor: Selecao = {
    inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: null },
    estacao: null,
    fronteira: { variaveis: ['energia'], agrupamento: 'leitor' },
    sistema: null,
  }

  it('mostra os 24 meses do medidor quando só o medidor entra', () => {
    const linha = linhaDeRetencao(soMedidor, PORTO.retencao, '1h')
    expect(linha).toMatch(/medidor/i)
    expect(linha).toContain('05/09/2024')
  })

  it('mostra os 6 meses assim que qualquer outra coisa entra junto', () => {
    const linha = linhaDeRetencao(comInversor, PORTO.retencao, '1h')
    expect(linha).toMatch(/inversores e estação/i)
    expect(linha).toContain('06/03/2026')
  })

  it('não mostra prazo nenhum no total por dia — porque ele não tem prazo', () => {
    expect(linhaDeRetencao(comInversor, PORTO.retencao, '1d')).toBeNull()
    expect(linhaDeRetencao(soMedidor, PORTO.retencao, '1d')).toBeNull()
  })

  it('cala quando o servidor não mandou a data, em vez de inventar uma', () => {
    const sem = { snapshots_desde: null, ssu_desde: null }
    expect(linhaDeRetencao(comInversor, sem, '1h')).toBeNull()
    expect(linhaDeRetencao(soMedidor, sem, '1h')).toBeNull()
  })

  it('cola o motivo no dia que só tem total diário — e não no que o medidor alcança', () => {
    expect(motivoDeRetencao('2025-01-10', PORTO.retencao)).toMatch(/só o total por dia/i)
    expect(motivoDeRetencao('2025-01-10', PORTO.retencao, true)).toBeNull()
    expect(motivoDeRetencao('2026-08-01', PORTO.retencao)).toBeNull()
  })

  it('oferece dias até o fundo do acervo do medidor, com o motivo em cada um', () => {
    const dias = diasOferecidos('2026-09-05', PORTO.retencao, false, 400)
    expect(dias[0].valor).toBe('2026-09-05')
    expect(dias[0].detalhe).toBeUndefined()
    const antigo = dias.find((d) => d.valor === '2026-01-15')
    expect(antigo?.detalhe).toMatch(/só o total por dia/i)
    // Nada abaixo do fundo do acervo é oferecido: lá não há leitura de bloco nenhum.
    expect(dias.every((d) => d.valor >= '2024-09-05')).toBe(true)
  })

  it('impede o período fora da retenção fina, apontando o total por dia como saída', () => {
    const j = janelaDo('2025-01-10', '2025-01-12', '00:00', '23:59', '1h', false)
    const imp = impedimento(comInversor, '1h', j, '2025-01-10', PORTO)
    expect(imp?.texto).toContain('06/03/2026')
    expect(imp?.texto).toMatch(/um total por dia/i)
    // O mesmo período, no total por dia, passa: a checagem do servidor mora dentro do
    // `if step != "1d"`.
    const jd = janelaDo('2025-01-10', '2025-01-12', '00:00', '23:59', '1d', false)
    expect(impedimento(comInversor, '1d', jd, '2025-01-10', PORTO)).toBeNull()
  })
})

/* ------------------------------------------------------------------ estimativa */

/**
 * As larguras deste bloco NÃO são deduzidas do código: foram lidas com `openpyxl` nos
 * arquivos que a rota real devolveu em 05/09/2026 (Porto Ferreira, 1 dia, passo 1 h), e estão
 * anotadas caso a caso. É a única forma de guardar a diferença que motivou o conserto — a
 * conta antiga era a do ORÇAMENTO do servidor, que não descreve o arquivo.
 */
function aba(e: ReturnType<typeof estimativa>, nome: string) {
  const a = e.abas.find((x) => x.nome === nome)
  if (!a) throw new Error(`aba ${nome} não saiu: ${e.abas.map((x) => x.nome).join(', ')}`)
  return a
}

const so = (parte: Partial<Selecao>): Selecao => ({
  inversores: null,
  estacao: null,
  fronteira: null,
  sistema: null,
  ...parte,
})

const UM_DIA = janelaDo('2026-09-01', '2026-09-01', '00:00', '23:59', '1h', false)

describe('a estimativa descreve o ARQUIVO, aba por aba — e nunca veta', () => {
  it('conta a coluna "Início (BRT)", que faltava em todas as abas', () => {
    // Medido: 2 skids marcados, geração, 1 h →
    // ['Início (BRT)', 'SKID-01 · Energia', 'SKID-02 · Energia', 'Usina · Energia'] = 4.
    const marcadas = [...PORTO.skids[0].series, ...PORTO.skids[1].series].map((s) => s.chave)
    expect(marcadas).toHaveLength(8)
    const sel = so({
      inversores: { variaveis: ['geracao'], agrupamento: 'skid', series: marcadas },
    })
    const e = estimativa(sel, PORTO, UM_DIA, '1h')
    expect(aba(e, 'Skids').colunas).toBe(4)
    // A conta antiga dizia 3 — e o Leia-me do próprio arquivo dizia "Skids · 24 linhas · 4
    // colunas", contradizendo a tela na cara do cliente.
    expect(aba(e, 'Skids').colunas).not.toBe(3)
  })

  it('a aba se chama Skids quando o agrupamento é skid, e Inversores quando é lista', () => {
    // O aceite desta leva dizia "aba Inversores" nos dois casos. O escritor de lá é
    // `Sheet("Inversores" if agr == "lista" else "Skids")`, e o arquivo medido diz Skids.
    const porSkid = estimativa(
      so({ inversores: { variaveis: ['geracao'], agrupamento: 'skid', series: null } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(porSkid.abas.map((a) => a.nome)).toEqual(['Skids'])
    // Medido: 5 skids + Usina + Início = 7.
    expect(aba(porSkid, 'Skids').colunas).toBe(7)

    const porLista = estimativa(
      so({ inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: null } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    // Medido: 20 inversores + Usina + Início = 22.
    expect(aba(porLista, 'Inversores').colunas).toBe(22)
  })

  it('a situação do inversor não ganha coluna de total da usina — texto não soma', () => {
    // Medido no passo nativo: 21 colunas para 20 inversores. Não há 'Usina · Status'.
    const e = estimativa(
      so({ inversores: { variaveis: ['status'], agrupamento: 'lista', series: null } }),
      PORTO,
      janelaDo('2026-09-01', '2026-09-01', '00:00', '23:59', 'native', false),
      'native',
    )
    expect(aba(e, 'Inversores').colunas).toBe(21)
  })

  it('paradas rende coluna por grupo, o total, e a aba própria — cujas linhas ninguém sabe', () => {
    // Medido: 20 inversores × (Energia, Potência, Min. desligado) + 3 totais + Início = 64.
    const e = estimativa(
      so({
        inversores: {
          variaveis: ['geracao', 'potencia', 'paradas'],
          agrupamento: 'lista',
          series: null,
        },
      }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(e, 'Inversores').colunas).toBe(64)
    const paradas = aba(e, 'Paradas')
    // ⛔ Ausência declarada, nunca zero: quantas paradas houve no período não se sabe daqui.
    expect(paradas.linhas).toBeNull()
    expect(paradas.colunas).toBeNull()
    expect(paradas.nota).toMatch(/uma linha por parada/)
  })

  it('no passo nativo a aba Paradas não existe — a régua é a do escritor de lá', () => {
    const e = estimativa(
      so({
        inversores: { variaveis: ['geracao', 'paradas'], agrupamento: 'lista', series: null },
      }),
      PORTO,
      janelaDo('2026-09-01', '2026-09-01', '00:00', '23:59', 'native', false),
      'native',
    )
    expect(e.abas.map((a) => a.nome)).toEqual(['Inversores'])
  })

  it('a fronteira agrupada por USINA tem 3 colunas, não 6 — o agrupamento era ignorado', () => {
    // Medido: ['Início (BRT)', 'Usina · Energia (kWh)', 'Leitores com leitura'].
    const usina = estimativa(
      so({ fronteira: { variaveis: ['energia'], agrupamento: 'usina' } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(usina, 'Fronteira').colunas).toBe(3)
    expect(aba(usina, 'Fronteira').colunas).not.toBe(PORTO.leitores.length + 1)

    // E por leitor são 8, não 6: faltava a coluna "Leitores com leitura" (o meuWatt também
    // a esquece na conta dele).
    const leitor = estimativa(
      so({ fronteira: { variaveis: ['energia'], agrupamento: 'leitor' } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(leitor, 'Fronteira').colunas).toBe(8)
  })

  it('o sistema cobra por variável, e não 5 colunas fixas por grupo', () => {
    // Medido, agrupado por usina: só PR → 5 (Início, Energia, Capacidade, POA, PR);
    // PR + produtividade → 6.
    const soPr = estimativa(
      so({ sistema: { variaveis: ['pr'], agrupamento: 'usina' } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(soPr, 'Sistema').colunas).toBe(5)
    const ambas = estimativa(
      so({ sistema: { variaveis: ['pr', 'produtividade'], agrupamento: 'usina' } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(ambas, 'Sistema').colunas).toBe(6)
    // Medido, agrupado por skid, só produtividade: 5 skids × (Energia, Capacidade,
    // Produtividade) + Início = 16. A conta fixa de 5 por grupo diria 25.
    const porSkid = estimativa(
      so({ sistema: { variaveis: ['produtividade'], agrupamento: 'skid' } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(porSkid, 'Sistema').colunas).toBe(16)
    expect(aba(porSkid, 'Sistema').colunas).not.toBe(25)
  })

  it('o sistema por skid ignora a seleção de inversores — lá o escritor usa `series_all`', () => {
    const marcadas = PORTO.skids[0].series.map((s) => s.chave)
    const e = estimativa(
      so({
        inversores: { variaveis: ['geracao'], agrupamento: 'skid', series: marcadas },
        sistema: { variaveis: ['produtividade'], agrupamento: 'skid' },
      }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(e, 'Skids').colunas).toBe(3) // 1 skid + usina + Início
    expect(aba(e, 'Sistema').colunas).toBe(16) // os CINCO skids, mesmo assim
  })

  it('a estação conta duas colunas por irradiação, mais Amostras — e diz o que não sabe', () => {
    // Medido: POA + GHI a 1 h → ['Início', 'POA média', 'POA', 'GHI média', 'GHI',
    // 'Amostras'] = 6. Só POA → 4.
    const duas = estimativa(so({ estacao: { variaveis: ['poa', 'ghi'] } }), PORTO, UM_DIA, '1h')
    expect(aba(duas, 'Estação').colunas).toBe(6)
    const uma = estimativa(so({ estacao: { variaveis: ['poa'] } }), PORTO, UM_DIA, '1h')
    expect(aba(uma, 'Estação').colunas).toBe(4)
    expect(aba(uma, 'Estação').nota).toBeUndefined()

    // ⛔ Com o relé a largura NÃO fecha: quantos sensores a usina tem não vem nas opções, e
    // Porto Ferreira tem cinco (medido: 9 colunas com POA + relé). Diz-se isso em vez de
    // inventar o número.
    const comRele = estimativa(
      so({ estacao: { variaveis: ['poa', 'temp_ambiente_rele'] } }),
      PORTO,
      UM_DIA,
      '1h',
    )
    expect(aba(comRele, 'Estação').colunas).toBe(4)
    expect(aba(comRele, 'Estação').nota).toMatch(/1 coluna por sensor do rel/)
  })

  it('no total por dia a estação encolhe, e no nativo cresce', () => {
    // 1d: POA vira uma coluna só (kWh/m²). Nativo: POA rende leitura, Δ, unidade e ainda
    // 'Comunicação'.
    const dia = janelaDo('2026-09-01', '2026-09-01', '00:00', '23:59', '1d', false)
    const porDia = estimativa(so({ estacao: { variaveis: ['poa'] } }), PORTO, dia, '1d')
    expect(aba(porDia, 'Estação').colunas).toBe(3)
    const nat = janelaDo('2026-09-01', '2026-09-01', '00:00', '23:59', 'native', false)
    const nativo = estimativa(so({ estacao: { variaveis: ['poa'] } }), PORTO, nat, 'native')
    expect(aba(nativo, 'Estação').colunas).toBe(6)
  })

  it('todas as abas de balde têm as linhas da janela, com o minuto final incluído', () => {
    const dia = janelaDo('2026-09-03', '2026-09-03', '00:00', '23:59', '5m', false)
    expect(dia).toMatchObject({ dias: 1, baldes: 288, valida: true })
    const e = estimativa(
      so({
        inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: null },
        fronteira: { variaveis: ['energia'], agrupamento: 'usina' },
      }),
      PORTO,
      dia,
      '5m',
    )
    expect(e.linhas).toBe(288)
    expect(e.abas.map((a) => a.linhas)).toEqual([288, 288])
    const meio = janelaDo('2026-09-03', '2026-09-03', '06:00', '17:59', '1h', false)
    expect(meio.baldes).toBe(12)
    const invertido = janelaDo('2026-09-03', '2026-09-03', '18:00', '06:00', '1h', false)
    expect(invertido.valida).toBe(false)
  })

  it('o orçamento continua sendo o do SERVIDOR, e não a largura do arquivo', () => {
    // As duas contas divergem de propósito: `celulasDoOrcamento` copia `validate_request`
    // (que ignora o agrupamento da fronteira e cobra 5 por grupo no sistema), porque é ELE
    // quem decide `muito_grande`. Uma conta mais fiel ao arquivo daria um aviso que não
    // corresponde à recusa que chega.
    const sel = so({ fronteira: { variaveis: ['energia'], agrupamento: 'usina' } })
    const e = estimativa(sel, PORTO, UM_DIA, '1h')
    expect(aba(e, 'Fronteira').colunas).toBe(3)
    expect(e.celulas).toBe(24 * (PORTO.leitores.length + 1)) // a régua de lá: 6 colunas
  })

  it('avisa quando estoura o orçamento — e termina oferecendo o pedido assim mesmo', () => {
    const sel = so({
      inversores: { variaveis: ['geracao', 'potencia'], agrupamento: 'lista', series: null },
    })
    const j = janelaDo('2026-08-04', '2026-09-03', '00:00', '23:59', '5m', false)
    const e = estimativa(sel, GRANDE, j, '5m')
    expect(e.celulas).toBeGreaterThan(LIMITES.max_celulas)
    const aviso = avisoDeOrcamento(e, LIMITES)
    expect(aviso).toMatch(/Se quiser tentar assim mesmo, pode pedir\.$/)
    expect(aviso).toContain('2.000.000')
    // E o pedido continua saindo: quem estima não veta.
    expect(impedimento(sel, '5m', j, '2026-08-04', GRANDE)).toBeNull()

    // Porto Ferreira nunca chega lá: o maior pedido dentro da retenção dela fica bem abaixo.
    expect(avisoDeOrcamento(estimativa(sel, PORTO, j, '5m'), LIMITES)).toBeNull()
  })

  it('cala quando cabe, e quando o servidor não declarou orçamento', () => {
    const e = { linhas: 288, abas: [], celulas: 864 }
    expect(avisoDeOrcamento(e, LIMITES)).toBeNull()
    expect(avisoDeOrcamento({ linhas: 1, abas: [], celulas: 9e9 }, {})).toBeNull()
  })
})

/* --------------------------------------------------- o que a versão podada tinha */

describe('o que foi tirado por ser a versão simplificada', () => {
  it('não tem estado "personalizado" nem gaveta "Avançado" em lugar nenhum do módulo', () => {
    expect(/PERSONALIZADO/.test(FONTE)).toBe(false)
    expect(/Avan[çc]ado/i.test(FONTE)).toBe(false)
  })
})
