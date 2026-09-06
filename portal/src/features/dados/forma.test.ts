/**
 * A memória da tela guarda a FORMA da pergunta — e o defeito que este teste tranca é o de
 * restaurá-la às cegas.
 *
 * A versão anterior fazia `JSON.parse(cru) as FormaGuardada` e entregava o resultado à tela.
 * Enquanto os blocos moravam atrás de uma gaveta ninguém sentia; com a seleção de inversores
 * em primeiro plano, a mesma linha devolve `slot:170` de um inversor que saiu da usina, ou POA
 * numa usina que perdeu a estação — e a tela abre travada por um equipamento que morreu meses
 * atrás, sem nada que explique o quê. Os cinco casos que doem:
 *
 * 1. **sobrou parte** → usa o que sobrou, calado (24 guardados, 20 hoje → 20);
 * 2. **não sobrou série nenhuma** → volta a `null` (= todos), **nunca** `[]` — a lista vazia
 *    viajaria como "nenhuma série" e o monitoramento devolveria um arquivo sem coluna, com
 *    status 200, que abre no Excel e não tem nada dentro;
 * 3. **bloco inteiro impossível** → volta a "Não entra" COM motivo escrito; sumir com a linha
 *    calada faz o cliente concluir que o portal deixou de oferecer;
 * 4. **o período nunca é guardado** — reabrir a tela apontada para agosto devolveria, calado,
 *    o arquivo do mês errado, e um arquivo errado que abre sem reclamar é pior que um erro;
 * 5. **`localStorage` que lança** (aba anônima, cota estourada) não derruba a tela nem o
 *    download: os dois caminhos degradam no padrão, que é sempre válido.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { definirToken } from '@/lib/api'
import type { OpcoesDeDados, Pedido, Selecao } from '@/features/dados/api'
import {
  baixarDados,
  Cancelado,
  corpoDoPedido,
  ErroDaExportacao,
  MOTIVO_PRAZO,
  nomeDoArquivo,
  PRAZO_DO_ARQUIVO_MS,
} from '@/features/dados/api'
import {
  chaveDaForma,
  gravarForma,
  lerForma,
  reconciliar,
  type FormaGuardada,
} from '@/features/dados/forma'

/* ------------------------------------------------------------------ cenário */

/** Uma usina com `porSkid` inversores em cada skid, chaves `slot:1`, `slot:2`, … */
function opcoes(porSkid: number[], extras: Partial<OpcoesDeDados> = {}): OpcoesDeDados {
  let n = 0
  return {
    usina: { id: 4, nome: 'Porto Ferreira', capacidade_kwp: 7400 },
    skids: porSkid.map((quantos, i) => ({
      id: i + 1,
      nome: `SKID-0${i + 1}`,
      capacidade_kwp: 1480,
      series: Array.from({ length: quantos }, () => {
        n += 1
        return {
          chave: `slot:${n}`,
          rotulo: `Inv ${n}`,
          numero_serie: `NS${n}`,
          capacidade_kwp: 75,
        }
      }),
    })),
    estacao: {
      disponivel: true,
      colunas: { poa: true, ghi: true, temp_modulo: true, temp_ambiente: true, vento: true },
      temp_ambiente_rele: false,
    },
    leitores: [{ id: 1, nome: 'Leitor A' }],
    sistema: { pr: true, produtividade: true },
    retencao: { snapshots_desde: '2026-03-06', ssu_desde: '2024-09-05' },
    limites: { native: 7, '5m': 31, '15m': 92, '1h': 366, '1d': 366, max_celulas: 2_000_000 },
    ...extras,
  }
}

const SEM_ESTACAO: Partial<OpcoesDeDados> = {
  estacao: { disponivel: false, colunas: {}, temp_ambiente_rele: false },
}

function selecaoCheia(series: string[] | null): Selecao {
  return {
    inversores: { variaveis: ['geracao'], agrupamento: 'lista', series },
    estacao: { variaveis: ['poa', 'ghi'] },
    fronteira: { variaveis: ['energia'], agrupamento: 'leitor' },
    sistema: { variaveis: ['pr'], agrupamento: 'usina' },
  }
}

function forma(selecao: Selecao): FormaGuardada {
  return { passo: '15m', selecao, horaInicio: '00:00', horaFim: '23:59' }
}

/** O que está de fato no disco, sem passar pelo leitor (que é o que se quer provar). */
function noDisco(usinaId: number): Record<string, unknown> {
  const cru = localStorage.getItem(chaveDaForma(usinaId))
  expect(cru).not.toBeNull()
  return JSON.parse(cru as string) as Record<string, unknown>
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

/* ------------------------------------------------------------------ séries */

describe('a seleção de inversores reconciliada', () => {
  it('mantém só as séries que a usina ainda tem, sem avisar nada', () => {
    const guardadas = Array.from({ length: 24 }, (_, i) => `slot:${i + 1}`)
    const { forma: lida, descartados } = reconciliar(
      forma(selecaoCheia(guardadas)),
      opcoes([10, 10]),
    )

    expect(lida?.selecao.inversores?.series).toHaveLength(20)
    expect(lida?.selecao.inversores?.series).toEqual(guardadas.slice(0, 20))
    // Manutenção de cadastro não é problema do cliente: sobrou seleção, ele não é avisado.
    expect(descartados).toEqual([])
  })

  it('volta a "todos" quando NENHUMA série guardada existe mais — e não à lista vazia', () => {
    const { forma: lida } = reconciliar(
      forma(selecaoCheia(['slot:170', 'slot:171', 'slot:172'])),
      opcoes([3]),
    )

    // `null` é "não mexi" e alcança os três de hoje; `[]` viajaria como "nenhuma série" e o
    // monitoramento devolveria um arquivo sem coluna nenhuma.
    expect(lida?.selecao.inversores?.series).toBeNull()
    expect(lida?.selecao.inversores?.series).not.toEqual([])
    // O bloco continua de pé: quem sumiu foi o equipamento, não a capacidade.
    expect(lida?.selecao.inversores?.variaveis).toEqual(['geracao'])
  })

  it('preserva a distinção entre "não mexi" (null) e lista explícita', () => {
    const nulo = reconciliar(forma(selecaoCheia(null)), opcoes([2]))
    expect(nulo.forma?.selecao.inversores?.series).toBeNull()

    // Lista que sobrevive continua lista, mesmo cobrindo todos: congelar o conjunto é uma
    // decisão do cliente, e transformá-la em `null` faria entrar sozinho o inversor novo.
    const explicita = reconciliar(forma(selecaoCheia(['slot:1', 'slot:2'])), opcoes([2]))
    expect(explicita.forma?.selecao.inversores?.series).toEqual(['slot:1', 'slot:2'])
  })

  it('descarta o bloco quando a usina ficou sem inversor nenhum, com motivo', () => {
    const { forma: lida, descartados } = reconciliar(forma(selecaoCheia(null)), opcoes([]))

    expect(lida?.selecao.inversores).toBeNull()
    expect(descartados.map((d) => d.bloco)).toContain('inversores')
    expect(descartados.find((d) => d.bloco === 'inversores')?.motivo).not.toHaveLength(0)
  })

  it('joga fora variável que não existe no vocabulário e mantém as boas', () => {
    const suja = forma({
      ...selecaoCheia(null),
      inversores: {
        variaveis: ['geracao', 'temperatura_do_cafe', 'potencia'] as never,
        agrupamento: 'skid',
        series: null,
      },
    })
    const { forma: lida } = reconciliar(suja, opcoes([2]))

    expect(lida?.selecao.inversores?.variaveis).toEqual(['geracao', 'potencia'])
    expect(lida?.selecao.inversores?.agrupamento).toBe('skid')
  })
})

/* ------------------------------------------------------------------ blocos */

describe('bloco que a usina não tem mais', () => {
  it('devolve a estação a "Não entra" com o motivo escrito', () => {
    const { forma: lida, descartados } = reconciliar(
      forma(selecaoCheia(null)),
      opcoes([2], SEM_ESTACAO),
    )

    expect(lida?.selecao.estacao).toBeNull()
    const motivo = descartados.find((d) => d.bloco === 'estacao')?.motivo
    expect(motivo).toBeTruthy()
    expect((motivo as string).length).toBeGreaterThan(10)
    // Os outros três blocos não são afetados: só cai o que ficou impossível.
    expect(lida?.selecao.inversores).not.toBeNull()
    expect(lida?.selecao.fronteira).not.toBeNull()
  })

  it('mantém a estação quando ao menos uma coluna guardada sobreviveu', () => {
    const so_poa = opcoes([2], {
      estacao: { disponivel: true, colunas: { poa: true, ghi: false }, temp_ambiente_rele: false },
    })
    const { forma: lida, descartados } = reconciliar(forma(selecaoCheia(null)), so_poa)

    expect(lida?.selecao.estacao?.variaveis).toEqual(['poa'])
    expect(descartados).toEqual([])
  })

  it('descarta o medidor quando a usina não tem mais leitor', () => {
    const { forma: lida, descartados } = reconciliar(forma(selecaoCheia(null)), {
      ...opcoes([2]),
      leitores: [],
    })

    expect(lida?.selecao.fronteira).toBeNull()
    expect(descartados.find((d) => d.bloco === 'fronteira')?.motivo).toBeTruthy()
  })

  it('descarta o desempenho quando a usina deixou de calcular PR e produtividade', () => {
    const { forma: lida, descartados } = reconciliar(forma(selecaoCheia(null)), {
      ...opcoes([2]),
      sistema: { pr: false, produtividade: false },
    })

    expect(lida?.selecao.sistema).toBeNull()
    // A cadeia inteira, e não só o efeito.
    expect(descartados.find((d) => d.bloco === 'sistema')?.motivo).toContain('irradiação')
  })
})

/* ------------------------------------------------------------------ o período */

describe('o período nunca é guardado', () => {
  it('não grava nenhuma data, nem quando quem chama passa um pedido inteiro', () => {
    // O engano provável: `Pedido` é `Selecao` mais `inicio`/`fim`, então um espalhamento
    // distraído gravaria as datas sem que o `tsc` tivesse o que reclamar.
    const comDatas = {
      ...forma(selecaoCheia(null)),
      inicio: '2026-08-01',
      fim: '2026-08-31',
    } as FormaGuardada
    gravarForma(4, comDatas)

    const gravado = noDisco(4)
    expect(Object.keys(gravado).sort()).toEqual(['horaFim', 'horaInicio', 'passo', 'selecao'])
    expect(localStorage.getItem(chaveDaForma(4))).not.toMatch(/\d{4}-\d{2}-\d{2}/)
  })

  it('guarda a forma por usina, e a de uma não vaza para a outra', () => {
    gravarForma(4, forma(selecaoCheia(['slot:1'])))

    expect(chaveDaForma(4)).not.toBe(chaveDaForma(6))
    expect(localStorage.getItem(chaveDaForma(6))).toBeNull()
    expect(lerForma(6, opcoes([2])).forma).toBeNull()
  })
})

/* ------------------------------------------------------------------ armazenamento */

describe('ler e gravar', () => {
  it('faz a volta completa: o que foi gravado é o que a tela recebe', () => {
    gravarForma(4, { ...forma(selecaoCheia(['slot:1', 'slot:2'])), passo: '1h' })
    const { forma: lida, descartados } = lerForma(4, opcoes([2, 2]))

    expect(lida?.passo).toBe('1h')
    expect(lida?.selecao.inversores?.series).toEqual(['slot:1', 'slot:2'])
    expect(lida?.horaFim).toBe('23:59')
    expect(descartados).toEqual([])
  })

  it('não derruba a leitura quando o armazenamento lança', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('bloqueado', 'SecurityError')
    })

    expect(() => lerForma(4, opcoes([2]))).not.toThrow()
    expect(lerForma(4, opcoes([2]))).toEqual({ forma: null, descartados: [] })
  })

  it('não derruba o download quando gravar falha por cota', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('cheio', 'QuotaExceededError')
    })

    // Guardar preferência é conveniência; o download já está pronto para sair.
    expect(() => gravarForma(4, forma(selecaoCheia(null)))).not.toThrow()
  })

  it('abre no padrão quando o guardado está estragado ou é de outro formato', () => {
    localStorage.setItem(chaveDaForma(4), '{isso não é json')
    expect(lerForma(4, opcoes([2])).forma).toBeNull()

    // Sem passo legível não há forma: o passo governa o teto de dias e a cadência do arquivo,
    // e chutar um faria a tela abrir mentindo sobre o que vai baixar.
    localStorage.setItem(chaveDaForma(4), JSON.stringify({ passo: '3m', selecao: {} }))
    expect(lerForma(4, opcoes([2])).forma).toBeNull()

    localStorage.setItem(chaveDaForma(4), JSON.stringify(['uma lista']))
    expect(lerForma(4, opcoes([2])).forma).toBeNull()
  })

  it('recusa horário impossível e cai no dia inteiro', () => {
    localStorage.setItem(
      chaveDaForma(4),
      JSON.stringify({ passo: '5m', selecao: {}, horaInicio: '25:70', horaFim: 'ontem' }),
    )
    const { forma: lida } = lerForma(4, opcoes([2]))

    expect(lida?.horaInicio).toBe('00:00')
    expect(lida?.horaFim).toBe('23:59')
  })
})

/* ================================================================== o transporte */

/**
 * O transporte do arquivo mora neste arquivo de teste porque é o único que este item possui
 * (`api.ts`, `forma.ts` e este). São dois defeitos distintos e ambos custam caro:
 *
 * 1. **cancelar e ser cortado chegam ao `fetch` como o MESMO `AbortError`.** Quem abortou é
 *    quem sabe por quê — e a versão anterior guardava esse "por quê" num `useRef` da tela,
 *    de onde ele some na primeira refatoração de componente. Cancelamento é decisão do
 *    cliente e CALA (pintar de vermelho o que ele mandou parar é acusá-lo); o corte aos três
 *    minutos é decisão NOSSA e FALA, porque ele ficou olhando e merece saber o que fazer.
 * 2. **o nome do arquivo é o que o servidor escreveu**, e não um remontado aqui: remontar
 *    cria uma segunda verdade sobre o mesmo arquivo, e quem sabe o que montou é o servidor.
 */
describe('o transporte do arquivo', () => {
  const pedido: Pedido = {
    inicio: '2026-08-01',
    fim: '2026-08-31',
    hora_inicio: '00:00',
    hora_fim: '23:59',
    passo: '5m',
    inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: null },
    estacao: null,
    fronteira: null,
    sistema: null,
  }

  /** Uma resposta que nunca chega — como a de verdade, que só chega com o XLSX pronto. */
  function fetchQueNuncaResponde() {
    return vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener('abort', () =>
            reject(new DOMException('abortado', 'AbortError')),
          )
        }),
    )
  }

  afterEach(() => {
    vi.useRealTimers()
    definirToken(null)
  })

  it('cancelar CALA: sai como desistência, não como erro', async () => {
    vi.stubGlobal('fetch', fetchQueNuncaResponde())
    const controlador = new AbortController()
    // O tratador é ligado ANTES de abortar: a rejeição acontece no mesmo tique do `abort()`,
    // e ligá-lo depois deixaria uma rejeição sem dono no relatório do vitest.
    const capturado = baixarDados(4, pedido, controlador.signal).catch((e: unknown) => e)
    controlador.abort()

    const erro = await capturado
    expect(erro).toBeInstanceOf(Cancelado)
    expect(erro).not.toBeInstanceOf(ErroDaExportacao)
  })

  it('o corte aos três minutos FALA, e diz qual é a saída', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', fetchQueNuncaResponde())
    const capturado = baixarDados(4, pedido).catch((e: unknown) => e)
    // Antes do prazo nada acontece: a rota é síncrona e 38 s de espera são normais.
    await vi.advanceTimersByTimeAsync(PRAZO_DO_ARQUIVO_MS - 1000)
    await vi.advanceTimersByTimeAsync(2000)

    const erro = await capturado
    expect(erro).toBeInstanceOf(ErroDaExportacao)
    expect((erro as ErroDaExportacao).motivo).toBe(MOTIVO_PRAZO)
    expect((erro as ErroDaExportacao).message).toMatch(/período menor|detalhe mais grosso/)
  })

  it('o cliente ganha do relógio quando os dois acontecem', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', fetchQueNuncaResponde())
    const controlador = new AbortController()
    const capturado = baixarDados(4, pedido, controlador.signal).catch((e: unknown) => e)
    controlador.abort()
    await vi.advanceTimersByTimeAsync(PRAZO_DO_ARQUIVO_MS + 1000)

    // Para quem cancelou, o que aconteceu foi ter cancelado.
    expect(await capturado).toBeInstanceOf(Cancelado)
  })

  it('lê o nome do cabeçalho do servidor, e não o remonta', () => {
    // Este cabeçalho foi LIDO da rota real (Porto Ferreira, 04/09, passo 1 dia) e bate com o
    // que `_nome_do_arquivo` do BFF monta para o mesmo pedido — a ponta a ponta fechada.
    expect(
      nomeDoArquivo(
        `attachment; filename="dados-porto-ferreira-2026-09-04-1d.xlsx"; filename*=UTF-8''dados-porto-ferreira-2026-09-04-1d.xlsx`,
        'reserva.xlsx',
      ),
    ).toBe('dados-porto-ferreira-2026-09-04-1d.xlsx')
    expect(nomeDoArquivo('attachment; filename="dados-ibitinga.xlsx"', 'reserva.xlsx')).toBe(
      'dados-ibitinga.xlsx',
    )
    // Sem cabeçalho o download não pode falhar: cai no nome de reserva.
    expect(nomeDoArquivo(null, 'reserva.xlsx')).toBe('reserva.xlsx')
  })

  it('bloco ausente fica FORA do corpo, e `series: null` também', () => {
    const corpo = corpoDoPedido(pedido)

    expect(Object.keys(corpo)).not.toContain('estacao')
    expect(Object.keys(corpo)).not.toContain('fronteira')
    // Lista vazia viajaria como "nenhuma série"; a chave ausente é "não mexi".
    expect(Object.keys(corpo.inversores as object)).not.toContain('series')
  })

  it('o motivo da recusa vem do PRIMEIRO nível, para a tela saber se repetir adianta', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: 'período longo demais', motivo: 'muito_grande' }), {
            status: 400,
          }),
      ),
    )

    const erro = await baixarDados(4, pedido).catch((e: unknown) => e)
    expect(erro).toBeInstanceOf(ErroDaExportacao)
    expect((erro as ErroDaExportacao).motivo).toBe('muito_grande')
    expect((erro as ErroDaExportacao).status).toBe(400)
  })
})
