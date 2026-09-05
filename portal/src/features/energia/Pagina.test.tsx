/**
 * O que este teste guarda são as afirmações que, desenhadas errado, ficam idênticas na tela
 * — e sempre a favor de alguém:
 *
 * 1. **PR descartado NÃO é PR zero.** "A usina rendeu 0%" é uma afirmação sobre a usina;
 *    "o monitoramento descartou a leitura" é uma afirmação sobre o sensor. Elas custam
 *    coisas diferentes numa reunião de contrato.
 * 2. **Dia que ainda não aconteceu não é dia sem geração.** A barra rasteira diria a
 *    segunda coisa; o contorno tracejado diz a primeira.
 * 3. **Sem medidor na fronteira, não há número de fronteira.** Nem zero, nem o antigo
 *    `medido × 0,987` que o próprio meuWatt removeu por ser um número inventado vestido de
 *    medição — e, sem os dois lados, também não há "perda até a fronteira".
 * 4. **O previsto diz de onde veio.** Quando o número sai da correção manual, a tela
 *    escreve isso; publicá-lo mudo seria vender palpite como medida.
 * 5. **Mês sem medição não se clica.** Ele aparece na lista (esconder seria esconder do
 *    cliente que aquele mês não foi medido), mas desabilitado e dizendo por quê.
 * 6. **Disponibilidade técnica não é a dos cartões.** O aviso do servidor tem de estar na
 *    tela junto da linha do tempo, senão o cliente lê dois percentuais contraditórios.
 * 7. **Os quatro estados existem** — esqueleto, vazio, erro e offline com selo.
 * 8. **O rodapé da tabela fecha com o cartão do topo.** Eram três somas convivendo: o
 *    cartão numa janela, a coluna noutra, a conciliação numa terceira. Nenhuma estava
 *    errada sozinha; juntas, davam três respostas para "a usina bateu o projeto?".
 * 9. **O acumulado diz de que meses saiu.** O mês fora da conta continua VISÍVEL, marcado
 *    e com o motivo — sumir com ele esconderia do cliente que aquele mês não foi medido.
 * 10. **O atingimento é impresso, não recalculado.** Refazê-lo aqui (`100 + desvio`) é
 *    literalmente como o portal chegou a exibir 36% numa tela e 101,7% na outra.
 * 11. **Estação que existe e não mediu hoje não é usina sem estação.** São duas perguntas,
 *    e a tela só nega o aparelho quando o CADASTRO disse que ele não existe.
 * 12. **A aba e o período moram na URL.** Este portal é aberto por um diretor que manda o
 *    endereço para o time; enquanto a aba vivia em `useState`, o endereço era sempre o
 *    mesmo e o destinatário caía noutra tela — e um F5 desfazia a navegação.
 *
 * A data é congelada em 15/09/2026 porque a tela decide o que é passado, o que é o mês em
 * curso e o que é futuro; sem relógio fixo, metade destas asserções mudaria de resultado
 * conforme o dia em que o teste roda.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { Dia, MesDoAno, Painel, Unidades, UsinaDetalhe } from '@/features/energia/api'
import PainelDeEnergia from '@/features/energia/Pagina'

const HOJE = new Date(2026, 8, 15, 10, 0, 0) // 15 de setembro de 2026, hora local

const USINA: UsinaDetalhe = {
  id: 4,
  nome: 'UFV Porto Ferreira',
  cidade: 'Porto Ferreira',
  uf: 'SP',
  capacidade_kwp: 7402.5,
  potencia_kw: 3120.4,
  energia_hoje_kwh: 18400,
  disponibilidade_pct: 99.9,
  pct_capacidade: 42.1,
  tom: 'ok',
  situacao: 'Gerando',
  fora_da_janela_solar: false,
  tem_meuwatt: true,
  tem_meuplano: true,
  aviso: null,
}

const REGRA = {
  disponibilidade: 'Disponibilidade = energia medida ÷ energia esperada.',
  contratual: 'A contratual desconta a energia perdida por causa externa.',
  perda_distribuida: 'Parada de vários dias tem a perda distribuída entre eles.',
  origem: 'Os percentuais vêm prontos do monitoramento.',
}

const METEO_VAZIA = {
  tem_estacao: false,
  tem_sensor_temperatura: false,
  hpoa: null,
  ghi: null,
  razao: null,
  hpoa_projeto: null,
  ghi_projeto: null,
  hpoa_projeto_origem: null,
  ghi_projeto_origem: null,
  t_amb_media: null,
  t_amb_max: null,
  t_mod_media: null,
  t_mod_max: null,
  pontos: [],
}

/** A janela do mês de setembro: um mês, medido, nada de fora. */
const JANELA_DO_MES = {
  meses: ['2026-09'],
  fora: [],
  rotulo: 'set de 2026',
  parcial: false,
  regra:
    'O acumulado vai do dia 1 até o último dia medido, e o projeto é rateado até o mesmo dia.',
}

/**
 * Uma linha da tabela de meses, com os defaults do contrato.
 *
 * O default de `no_acumulado` é `false` de propósito: quem quer um mês DENTRO da conta tem
 * de dizer isso, e é essa a informação que a linha e o rodapé usam.
 */
function mesDoAno(parcial: Partial<MesDoAno> & { mes: string; rotulo: string }): MesDoAno {
  return {
    medido_kwh: null,
    projeto_kwh: null,
    previsto_kwh: null,
    desvio_vs_projeto_pct: null,
    pr_pct: null,
    disponibilidade_real_pct: null,
    disponibilidade_contratual_pct: null,
    perdida_kwh: null,
    perdida_externa_kwh: null,
    fronteira_mwh: null,
    faturado_mwh: null,
    disponibilidade_origem: null,
    no_acumulado: false,
    em_curso: false,
    futuro: false,
    ...parcial,
  }
}

function painel(parcial: Partial<Painel> = {}): Painel {
  return {
    recorte: 'mes',
    referencia: '2026-09-15',
    inicio: '2026-09-01',
    fim: '2026-09-30',
    rotulo: 'Setembro / 2026',
    em_curso: true,
    dia_de_corte: 15,
    capacidade_kwp: 7402.5,
    medido_inversores_kwh: 540000,
    medido_fronteira_kwh: null,
    perda_inv_fronteira_pct: null,
    fronteira_parcial: false,
    fronteira_meses: [],
    projeto_kwh: 1100000,
    projeto_proporcional_kwh: 560000,
    atingimento_pct: 96.4,
    projeto_origem: 'pvsyst_diario',
    previsto_kwh: null,
    previsto_origem: null,
    produtividade_kwh_kwp: 72.9,
    pr_pct: 81.6,
    disponibilidade_real_pct: 99.89,
    disponibilidade_contratual_pct: 99.94,
    paradas_pendentes: 0,
    perdida_kwh: 6200,
    perdida_externa_kwh: 1100,
    desvios: {
      medido_vs_projeto_pct: -3.5,
      medido_vs_previsto_pct: 1.2,
      previsto_vs_projeto_pct: -4.6,
      hpoa_vs_projeto_pct: null,
      ghi_vs_projeto_pct: null,
    },
    conciliacao: {
      fronteira_mwh: null,
      faturado_mwh: null,
      diferenca_mwh: null,
      diferenca_pct: null,
      situacao: null,
      tolerancia_pct: 1.0,
      meses: [],
    },
    totais: {
      medido_kwh: 540000,
      projeto_kwh: 1100000,
      projeto_ate_hoje_kwh: 560000,
      tendencia_kwh: 1080000,
    },
    meteo: { ...METEO_VAZIA, tem_estacao: true, hpoa: 120.4, ghi: 108.9, razao: 1.11, pontos: [] },
    janela: JANELA_DO_MES,
    regra: REGRA,
    dias: [],
    meses: [],
    meses_disponiveis: null,
    disponibilidade_tecnica: null,
    aviso: null,
    ...parcial,
  }
}

function dia(parcial: Partial<Dia> = {}): Dia {
  return {
    dia: '2026-09-15',
    gerado_kwh: 18400,
    pico_kw: 5100,
    pico_hora: '12:35',
    potencia_agora_kw: 3120,
    inversores_gerando: 19,
    inversores_total: 20,
    disponibilidade_pct: 99.9,
    pr_pct: 82.1,
    pr_descartado: false,
    hpoa_agora: 780,
    hpoa_acumulada: 5.4,
    ghi_acumulada: 4.9,
    tem_estacao: true,
    estacao_com_leitura: true,
    estacao_indefinida: false,
    curva: [],
    eventos: [],
    ucs: [],
    faisca_horas: [],
    aviso: null,
    ...parcial,
  }
}

function unidades(parcial: Partial<Unidades> = {}): Unidades {
  return {
    recorte: 'mes',
    inicio: '2026-09-01',
    fim: '2026-09-15',
    ucs_ativas: 0,
    capacidade_total_kwp: null,
    energia_periodo_kwh: null,
    maior: null,
    ucs: [],
    serie_dias: [],
    serie: [],
    ranking_geracao: [],
    ranking_pr: [],
    ranking_produtividade: [],
    pr_referencia_pct: 80,
    faturas_situacao: null,
    aviso: null,
    ...parcial,
  }
}

/**
 * O dublê do BFF: casa o pedaço do endereço com a resposta.
 *
 * A ordem importa — `painel?recorte=ano` tem de ser conferido antes de `painel`, senão o
 * ano receberia a resposta do mês e a tela ficaria certa por acidente.
 */
function servidor(pares: [string, unknown][]) {
  return vi.spyOn(api, 'get').mockImplementation((async (url: string) => {
    for (const [pedaco, dados] of pares) {
      if (String(url).includes(pedaco)) return { data: dados }
    }
    throw new Error(`sem dublê para ${url}`)
  }) as never)
}

/**
 * O `MemoryRouter` guarda o endereço em memória e NÃO toca em `window.location` — ler dali
 * daria sempre vazio e o teste passaria a medir o navegador do vitest, não o portal. Este
 * espião publica a barra de endereço numa marca de teste, que é o que as asserções leem.
 */
function EspiaoDoEndereco() {
  const { search } = useLocation()
  return <span data-testid="endereco">{search}</span>
}

const enderecoAtual = () => screen.getByTestId('endereco').textContent ?? ''

function montar(endereco = '/usinas/4/energia') {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[endereco]}>
        <Routes>
          <Route path="/usinas/:id/energia" element={<PainelDeEnergia />} />
        </Routes>
        <EspiaoDoEndereco />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Painel de energia', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(HOJE)
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    // Sem `globals` no vitest a limpeza da árvore NÃO é automática: sem esta linha o
    // `screen` enxerga a tela do teste anterior junto com a atual, e uma asserção de
    // ausência passa a falhar por um texto que não é deste caso.
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    limparCache()
  })

  it('abre no Mês e pergunta ao BFF o painel do mês e o do ano', async () => {
    const get = servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel()],
    ])
    montar()

    await screen.findByText('UFV Porto Ferreira')
    await waitFor(() => {
      const pedidos = get.mock.calls.map((c) => String(c[0]))
      expect(pedidos.some((p) => p.includes('energia/usinas/4/painel?recorte=mes'))).toBe(true)
      // A referência do recorte anual é normalizada para 1º de janeiro: é o que faz a aba
      // Ano e o seletor de mês dividirem UMA leitura em vez de duas.
      expect(
        pedidos.some((p) => p.includes('painel?recorte=ano&referencia=2026-01-01')),
      ).toBe(true)
    })
  })

  it('dia com PR descartado fica SEM barra e diz "descartada" — nunca 0%', async () => {
    const dias = [
      {
        dia: 1,
        data: '2026-09-01',
        medido_kwh: 36000,
        projeto_kwh: 37000,
        pr_pct: 81.2,
        pr_descartado: false,
        futuro: false,
      },
      {
        dia: 2,
        data: '2026-09-02',
        medido_kwh: 35000,
        projeto_kwh: 37000,
        pr_pct: null,
        pr_descartado: true,
        futuro: false,
      },
    ]
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel({ dias })],
    ])
    const { container } = montar()

    await screen.findByText('Performance ratio dia a dia')
    // O dia medido tem barra de PR; o descartado não tem NENHUMA.
    expect(container.querySelector('[data-testid="pr-2026-09-01"]')).toBeTruthy()
    expect(container.querySelector('[data-testid="pr-2026-09-02"]')).toBeNull()
    expect(
      screen.getByText(
        'Um dia teve a leitura de PR descartada pelo monitoramento e ficou sem barra.',
      ),
    ).toBeTruthy()
    // E em lugar nenhum do gráfico o dia descartado virou zero.
    expect(screen.queryByText('0,0%')).toBeNull()
  })

  it('dia que ainda não aconteceu sai tracejado, sem barra de medição', async () => {
    const dias = [
      {
        dia: 15,
        data: '2026-09-15',
        medido_kwh: 30000,
        projeto_kwh: 37000,
        pr_pct: 80,
        pr_descartado: false,
        futuro: false,
      },
      {
        dia: 16,
        data: '2026-09-16',
        medido_kwh: null,
        projeto_kwh: 37000,
        pr_pct: null,
        pr_descartado: false,
        futuro: true,
      },
    ]
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel({ dias })],
    ])
    const { container } = montar()

    await screen.findByText('Geração dia a dia')
    expect(container.querySelector('[data-testid="barra-2026-09-15"]')).toBeTruthy()
    // O dia 16 não tem barra de medição — tem o contorno da meta.
    expect(container.querySelector('[data-testid="barra-2026-09-16"]')).toBeNull()
    const futuro = container.querySelector('[data-testid="futuro-2026-09-16"]')
    expect(futuro).toBeTruthy()
    expect(futuro?.className).toContain('border-dashed')
    expect(screen.getByText('ainda não aconteceu')).toBeTruthy()
  })

  it('sem medidor na fronteira, o cartão não existe — e não há "perda até a fronteira"', async () => {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel({ medido_fronteira_kwh: null, perda_inv_fronteira_pct: null })],
    ])
    montar()

    await screen.findByText('Quanto a usina gerou · Setembro / 2026')
    expect(screen.queryByText('Medido (fronteira)')).toBeNull()
    expect(screen.queryByText(/perda até a fronteira/)).toBeNull()
    expect(
      screen.getByText('Este mês não tem medição na fronteira nem fatura emitida para conferir.'),
    ).toBeTruthy()
  })

  it('fronteira que não cobre a usina aparece como medição parcial, e não como perda', async () => {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      [
        'painel?recorte=mes',
        painel({
          medido_fronteira_kwh: 420000,
          perda_inv_fronteira_pct: null,
          fronteira_parcial: true,
        }),
      ],
    ])
    montar()

    await screen.findByText('Medido (fronteira)')
    expect(screen.queryByText(/perda até a fronteira/)).toBeNull()
    expect(
      screen.getByText(/O medidor do ponto de entrega não cobre o mesmo conjunto/),
    ).toBeTruthy()
  })

  it('o desvio de irradiação aparece quando há projeto, e some quando não há', async () => {
    // É a comparação que separa "o sol não veio" de "a usina não rendeu" — sem ela um mês
    // fraco tem duas explicações possíveis e nenhuma escrita. Sem projeto de irradiação a
    // linha SOME: um travessão ali não informaria nada e ocuparia o lugar do que informa.
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      [
        'painel?recorte=mes',
        painel({
          desvios: {
            medido_vs_projeto_pct: -3.5,
            medido_vs_previsto_pct: 1.2,
            previsto_vs_projeto_pct: -4.6,
            hpoa_vs_projeto_pct: -3.85,
            ghi_vs_projeto_pct: null,
          },
        }),
      ],
    ])
    montar()

    await screen.findByText('Sol medido × projeto (plano dos módulos)')
    expect(screen.getByText('−3,9%')).toBeTruthy()
    expect(screen.queryByText('Sol medido × projeto (plano horizontal)')).toBeNull()
  })

  it('sensor de ambiente mudo diz "sem leitura" — nunca um número que ninguém mediu', async () => {
    // Porto Ferreira: o relé de ambiente só devolve o valor de fábrica (o servidor descarta
    // a série inteira e manda nulo) enquanto o do módulo mede. Sem este ramo o card sairia
    // "— °C" ao lado de um número, que parece defeito da tela em vez de sensor parado.
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      [
        'painel?recorte=mes',
        painel({
          meteo: {
            ...METEO_VAZIA,
            tem_estacao: true,
            tem_sensor_temperatura: true,
            hpoa: 120.4,
            t_amb_media: null,
            t_amb_max: null,
            t_mod_media: 33.8,
            t_mod_max: 47.2,
          },
        }),
      ],
    ])
    montar()

    await screen.findByText('Temperatura ambiente')
    expect(screen.getByText('sem leitura')).toBeTruthy()
    expect(screen.getByText('o sensor de ambiente não mediu no período')).toBeTruthy()
    expect(screen.getByText('33,8 °C')).toBeTruthy()
    expect(screen.queryByText('0,0 °C')).toBeNull()
  })

  it('previsto vindo da correção manual aparece com a procedência escrita', async () => {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      [
        'painel?recorte=mes',
        painel({ previsto_kwh: 560000, previsto_origem: 'manual_corrigido' }),
      ],
    ])
    montar()

    expect(await screen.findByText('Previsto (irradiação medida)')).toBeTruthy()
    expect(
      screen.getByText('da meta mensal digitada no projeto, corrigida pela irradiação medida'),
    ).toBeTruthy()
  })

  it('mês sem medição fica desabilitado no seletor, dizendo por quê', async () => {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano', meses_disponiveis: ['2026-08', '2026-09'] })],
      ['painel?recorte=mes', painel()],
    ])
    montar()

    fireEvent.click(await screen.findByLabelText('Escolher o mês'))

    const julho = await screen.findByRole('button', { name: /Julho de 2026/ })
    expect(julho.hasAttribute('disabled')).toBe(true)
    expect(screen.getAllByText('sem medição neste mês').length).toBeGreaterThan(0)

    const setembro = screen.getByRole('button', { name: /Setembro de 2026/ })
    expect(setembro.hasAttribute('disabled')).toBe(false)
  })

  /**
   * O ANO de uma usina cuja série começa no meio — a forma de Porto Ferreira em 2026.
   *
   * Cinco meses sem medição com meta cadastrada, três fechados, um em curso (com a meta
   * rateada, que é o que faz a coluna somar o cartão) e três por vir. É a única forma em
   * que somar a coluna inteira e ler o acumulado do servidor dão números diferentes — e era
   * exatamente esse par de números que a tela publicava lado a lado.
   *
   * Somar as doze linhas de projeto daria 9.480,0 MWh; o acumulado do servidor é 2.880,0.
   */
  function anoDePortoFerreira(): Painel {
    const semMedicao = ['jan', 'fev', 'mar', 'abr', 'mai'].map((rotulo, i) =>
      mesDoAno({
        mes: `2026-0${i + 1}`,
        rotulo,
        projeto_kwh: 900000,
      }),
    )
    const medidos = [
      mesDoAno({
        mes: '2026-06',
        rotulo: 'jun',
        medido_kwh: 700000,
        projeto_kwh: 800000,
        disponibilidade_real_pct: 99.89,
        disponibilidade_origem: 'mes_conferido',
        no_acumulado: true,
      }),
      mesDoAno({
        mes: '2026-07',
        rotulo: 'jul',
        medido_kwh: 750000,
        projeto_kwh: 820000,
        disponibilidade_real_pct: 99.99,
        disponibilidade_origem: 'rollup_do_ano',
        no_acumulado: true,
      }),
      mesDoAno({
        mes: '2026-08',
        rotulo: 'ago',
        medido_kwh: 780000,
        projeto_kwh: 830000,
        disponibilidade_real_pct: 99.9,
        disponibilidade_origem: 'mes_conferido',
        no_acumulado: true,
      }),
      mesDoAno({
        mes: '2026-09',
        rotulo: 'set',
        medido_kwh: 400000,
        // A meta RATEADA até hoje — é ela que faz a coluna somar exatamente o cartão.
        projeto_kwh: 430000,
        disponibilidade_real_pct: 99.5,
        disponibilidade_origem: 'mes_conferido',
        no_acumulado: true,
        em_curso: true,
      }),
    ]
    const futuros = ['out', 'nov', 'dez'].map((rotulo, i) =>
      mesDoAno({
        mes: `2026-1${i}`,
        rotulo,
        projeto_kwh: 700000,
        futuro: true,
      }),
    )

    return painel({
      recorte: 'ano',
      rotulo: '2026',
      referencia: '2026-01-01',
      inicio: '2026-01-01',
      fim: '2026-12-31',
      medido_inversores_kwh: 2630000,
      projeto_kwh: 2880000,
      projeto_proporcional_kwh: 2880000,
      atingimento_pct: 91.3,
      desvios: {
        medido_vs_projeto_pct: -8.68,
        medido_vs_previsto_pct: 1.2,
        previsto_vs_projeto_pct: -4.6,
        hpoa_vs_projeto_pct: null,
        ghi_vs_projeto_pct: null,
      },
      totais: {
        medido_kwh: 2630000,
        projeto_kwh: 9480000,
        projeto_ate_hoje_kwh: 2880000,
        tendencia_kwh: null,
      },
      meses: [...semMedicao, ...medidos, ...futuros],
      janela: {
        meses: ['2026-06', '2026-07', '2026-08', '2026-09'],
        fora: [
          ...semMedicao.map((m) => ({
            mes: m.mes,
            rotulo: `${m.rotulo}/2026`,
            motivo: 'sem_medicao',
          })),
          ...futuros.map((m) => ({ mes: m.mes, rotulo: `${m.rotulo}/2026`, motivo: 'futuro' })),
        ],
        rotulo: 'jun a set de 2026',
        parcial: true,
        regra: 'O acumulado soma só os meses com medição, e o projeto soma os MESMOS meses.',
      },
    })
  }

  async function abrirOAno(ano: Painel) {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', ano],
      ['painel?recorte=mes', painel()],
    ])
    const tela = montar()
    await screen.findByText('UFV Porto Ferreira')
    fireEvent.click(screen.getByRole('button', { name: 'Ano' }))
    await screen.findByText('Detalhamento mensal')
    return tela
  }

  /** O rodapé da tabela cujo total começa por este título. */
  function rodapeDe(container: HTMLElement, titulo: string): HTMLElement {
    const achado = [...container.querySelectorAll('tfoot')].find((r) =>
      r.textContent?.includes(titulo),
    )
    if (!achado) throw new Error(`sem rodapé "${titulo}" na tela`)
    return achado as HTMLElement
  }

  it('sem correção pelo clima, o cartão de previsto não promete correção nenhuma', async () => {
    // Quatro das sete usinas do dono não têm estação nem PVsyst diário. A tela publicava,
    // lado a lado, `PROJETO 2.379,8 MWh · do valor mensal digitado no projeto` e
    // `PREVISTO 2.379,8 MWh · da meta diária do projeto, corrigida pela irradiação medida`
    // — o mesmo byte, dois rótulos, e uma correção que nunca houve.
    await abrirOAno({
      ...anoDePortoFerreira(),
      previsto_kwh: 2880000,
      previsto_origem: 'mensal_digitado',
      projeto_origem: 'mensal_digitado',
    })

    expect(screen.getByText('Previsto')).toBeTruthy()
    expect(screen.queryByText('Previsto (irradiação medida)')).toBeNull()
    expect(
      screen.queryByText(/da meta diária do projeto, corrigida pela irradiação medida/),
    ).toBeNull()
    expect(screen.getAllByText('do valor mensal digitado no projeto').length).toBeGreaterThan(1)
  })

  it('com correção pelo clima medido, o cartão volta a dizer que foi corrigido', async () => {
    await abrirOAno({
      ...anoDePortoFerreira(),
      previsto_kwh: 2900000,
      previsto_origem: 'manual_corrigido',
    })

    expect(screen.getByText('Previsto (irradiação medida)')).toBeTruthy()
    expect(
      screen.getByText('da meta mensal digitada no projeto, corrigida pela irradiação medida'),
    ).toBeTruthy()
  })

  it('o total de GHI do projeto sai de parcelas VISÍVEIS na tabela', async () => {
    // O cartão publicava `GHI 969,5 · projeto 988,2 kWh/m²` — e o desvio de −1,9 % saía dele
    // — com a tabela abaixo sem uma única coluna de onde os 988,2 pudessem ter vindo.
    const base = anoDePortoFerreira()
    const { container } = await abrirOAno({
      ...base,
      meteo: {
        ...METEO_VAZIA,
        tem_estacao: true,
        hpoa: 200,
        ghi: 180,
        hpoa_projeto: 210,
        ghi_projeto: 190,
        hpoa_projeto_origem: 'mensal_digitado',
        ghi_projeto_origem: 'mensal_digitado',
        pontos: [
          {
            chave: '2026-06',
            rotulo: 'jun',
            hpoa: 100,
            hpoa_projeto: 105,
            ghi: 90,
            ghi_projeto: 95,
            t_amb: null,
            t_mod: null,
            t_mod_max: null,
          },
          {
            chave: '2026-07',
            rotulo: 'jul',
            hpoa: 100,
            hpoa_projeto: 105,
            ghi: 90,
            ghi_projeto: 95,
            t_amb: null,
            t_mod: null,
            t_mod_max: null,
          },
        ],
      },
    })

    expect(screen.getByText('GHI projeto')).toBeTruthy()
    // As duas parcelas (95 + 95) somam o total do rodapé (190) — a coluna fecha com o cartão.
    const total = rodapeDe(container, 'Acumulado do período')
    expect(total.textContent).toContain('190,0')
    expect(screen.getAllByText('95,0').length).toBe(2)
  })

  it('o acumulado de fronteira diz quando a janela dele é mais curta que a da geração', async () => {
    // Em Porto Ferreira o cartão dizia 1.132,9 MWh sob o rótulo "acumulado · jun a set", e a
    // coluna somava jul+ago+set: junho está na janela e não tem medidor.
    await abrirOAno({
      ...anoDePortoFerreira(),
      medido_fronteira_kwh: 1132900,
      fronteira_meses: ['2026-07', '2026-08', '2026-09'],
    })

    expect(
      screen.getByText(
        /Só jul\/2026 a set\/2026 tem leitura de medidor — os demais meses do acumulado não entram nesta soma\./,
      ),
    ).toBeTruthy()
  })

  it('quando o medidor cobre a janela inteira, a tela não inventa ressalva', async () => {
    await abrirOAno({
      ...anoDePortoFerreira(),
      medido_fronteira_kwh: 1500000,
      fronteira_meses: ['2026-06', '2026-07', '2026-08', '2026-09'],
    })

    expect(screen.queryByText(/tem leitura de medidor/)).toBeNull()
  })

  it('o "Total do período" fecha com o cartão do topo — o mesmo medido e o mesmo projeto', async () => {
    // A asserção que guarda a lição mais cara desta leva: enquanto o rodapé somava a coluna
    // e o cartão somava a janela, o cliente que conferia a tabela com o dedo achava um
    // terceiro número, e nenhum dos três estava errado sozinho.
    const { container } = await abrirOAno(anoDePortoFerreira())

    // Cada um aparece DUAS vezes: no cartão de geração e no rodapé da tabela.
    expect(screen.getAllByText('2.880,0 MWh').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('2.630,0 MWh').length).toBeGreaterThanOrEqual(2)

    const total = rodapeDe(container, 'Total do período')
    expect(total.textContent).toContain('2.880,0 MWh')
    expect(total.textContent).toContain('2.630,0 MWh')
    // A soma das DOZE linhas de projeto (9.480,0 MWh) não pode entrar no rodapé: ela
    // responde a outra pergunta com a cara desta.
    expect(total.textContent).not.toContain('9.480,0 MWh')

    // Ela aparece na tela, sim — uma vez, no cartão, e NOMEADA como o alvo do ano inteiro.
    // Um número sem nome ao lado de outro parecido é como a tela dava três respostas.
    expect(screen.getByText('9.480,0 MWh')).toBeTruthy()
    expect(screen.getByText(/ano inteiro/)).toBeTruthy()
  })

  it('o mês fora do acumulado continua na tabela — marcado e com o motivo', async () => {
    await abrirOAno(anoDePortoFerreira())

    // Os cinco meses sem medição continuam visíveis (o cliente quer ver o ano inteiro) e
    // dizem por que não entraram na conta.
    expect(screen.getAllByText('fora da conta · sem medição').length).toBe(5)
    // O mês em curso entra na conta — com a meta rateada — e por isso NÃO é marcado como
    // fora; ele só se identifica como em curso.
    expect(screen.getByText('em curso')).toBeTruthy()
    // E o rodapé diz sobre que meses ele somou, ali mesmo.
    expect(screen.getAllByText('jun a set de 2026').length).toBeGreaterThanOrEqual(1)
  })

  it('a janela do acumulado é escrita na tela, com os meses de fora e o motivo de cada um', async () => {
    await abrirOAno(anoDePortoFerreira())

    const nota = screen.getByTestId('janela-do-acumulado')
    expect(nota.textContent).toContain('O acumulado soma')
    expect(nota.textContent).toContain('jun a set de 2026')
    expect(nota.textContent).toContain('4 meses')
    // Os meses de fora saem em FAIXA, não um a um: oito rótulos em fila viram uma frase que
    // ninguém lê — e frase que ninguém lê não informa.
    expect(nota.textContent).toContain('jan/2026 a mai/2026')
    expect(nota.textContent).toContain('sem medição')
    expect(nota.textContent).toContain('out/2026 a dez/2026')
    expect(nota.textContent).toContain('ainda não começou')
    // A regra vem escrita do servidor; a tela imprime.
    expect(nota.textContent).toContain('o projeto soma os MESMOS meses')
  })

  it('a disponibilidade do mês diz quando saiu do resumo do ano, e não da leitura do mês', async () => {
    // Os dois discordam em centésimos no upstream. Num número de teor contratual, a tela
    // tem de poder dizer qual dos dois está mostrando.
    await abrirOAno(anoDePortoFerreira())

    expect(screen.getAllByText('do resumo do ano').length).toBe(1)
    expect(screen.getByText('99,99%')).toBeTruthy()
  })

  it('o atingimento é IMPRESSO, não recalculado de 100 + desvio', async () => {
    // Os dois campos vêm de propósito inconsistentes neste dublê: no servidor eles saem da
    // mesma divisão e concordam sempre, então só uma discordância plantada revela uma tela
    // que faz a conta por fora. `100 + (−3,5)` daria "96,5%".
    const ano = anoDePortoFerreira()
    await abrirOAno({
      ...ano,
      atingimento_pct: 44.4,
      desvios: { ...ano.desvios, medido_vs_projeto_pct: -3.5 },
    })

    expect(screen.getByText('44,4%')).toBeTruthy()
    expect(screen.queryByText('96,5%')).toBeNull()
    expect(screen.queryByText('96%')).toBeNull()
  })

  it('no Mês, a rosca também imprime o atingimento do servidor', async () => {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      [
        'painel?recorte=mes',
        painel({
          atingimento_pct: 44.4,
          desvios: {
            medido_vs_projeto_pct: -3.5,
            medido_vs_previsto_pct: 1.2,
            previsto_vs_projeto_pct: -4.6,
            hpoa_vs_projeto_pct: null,
            ghi_vs_projeto_pct: null,
          },
        }),
      ],
    ])
    montar()

    await screen.findByText('Fechamento até hoje')
    expect(screen.getByText('44,4%')).toBeTruthy()
    expect(screen.queryByText('96,5%')).toBeNull()
  })

  it('a conta de energia do ano confere só os meses com os dois lados', async () => {
    const ano = anoDePortoFerreira()
    const meses = ano.meses.map((m) => {
      if (m.mes === '2026-06') return { ...m, fronteira_mwh: 700, faturado_mwh: 690 }
      // Julho tem medidor e ainda não tem fatura: aparece na tabela, fica fora da conta.
      if (m.mes === '2026-07') return { ...m, fronteira_mwh: 745, faturado_mwh: null }
      if (m.mes === '2026-08') return { ...m, fronteira_mwh: 700, faturado_mwh: 705 }
      return m
    })
    await abrirOAno({
      ...ano,
      meses,
      conciliacao: {
        fronteira_mwh: 1400,
        faturado_mwh: 1395,
        diferenca_mwh: 5,
        diferenca_pct: 0.36,
        situacao: 'Conciliado',
        tolerancia_pct: 1,
        meses: ['2026-06', '2026-08'],
      },
    })

    expect(screen.getByText('Conta de energia, mês a mês')).toBeTruthy()
    // O rodapé é a conciliação do servidor — 1.400,0 —, e não a coluna inteira (2.145,0),
    // que somaria um mês cuja fatura a distribuidora ainda nem emitiu.
    expect(screen.getByText('1.400,0')).toBeTruthy()
    expect(screen.queryByText('2.145,0')).toBeNull()
    expect(screen.getByText('não conferido')).toBeTruthy()
    expect(screen.getByText('jun/2026 e ago/2026')).toBeTruthy()
    // A diferença do mês é fronteira − conta, o MESMO sentido do total do servidor.
    expect(screen.getByText('+10,0')).toBeTruthy()
    expect(screen.getByText('−5,0')).toBeTruthy()
  })

  it('a linha do tempo por inversor vem com o aviso de técnica × energética', async () => {
    const ano = painel({
      recorte: 'ano',
      rotulo: '2026',
      disponibilidade_tecnica: {
        aviso:
          'Aqui a disponibilidade é TÉCNICA: quanto tempo cada inversor ficou de pé dentro da janela de sol. Ela não bate com a disponibilidade dos cartões acima, que é energética.',
        primeiro_dia: '2026-01-01',
        ultimo_dia: '2026-09-15',
        inversores: [
          {
            nome: 'Inversor 1',
            disponibilidade_pct: 98.4,
            faixas: [
              { de: '2026-01-01', ate: '2026-08-31', dias: 243, estado: 'operando' },
              { de: '2026-09-01', ate: '2026-09-15', dias: 15, estado: 'potencia_zero' },
            ],
          },
        ],
      },
    })
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', ano],
      ['painel?recorte=mes', painel()],
    ])
    montar()

    await screen.findByText('UFV Porto Ferreira')
    fireEvent.click(screen.getByRole('button', { name: 'Ano' }))

    expect(await screen.findByText('Tempo de pé, inversor por inversor')).toBeTruthy()
    expect(screen.getByText(/disponibilidade é TÉCNICA/)).toBeTruthy()
    expect(screen.getByText('Inversor 1')).toBeTruthy()
    expect(screen.getByText('Operando')).toBeTruthy()
    expect(screen.getByText('Sem produção')).toBeTruthy()
  })

  it('dia sem incidente diz "operação sem incidentes" — em verde, não em cinza de falha', async () => {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel()],
      ['/dia?data=', dia({ eventos: [] })],
    ])
    montar()

    await screen.findByText('UFV Porto Ferreira')
    fireEvent.click(screen.getByRole('button', { name: 'Dia' }))

    const titulo = await screen.findByText('Operação sem incidentes')
    expect(titulo.className).toContain('text-tom-ok')
  })

  it('no Dia, PR descartado escreve "descartada" e não desenha percentual', async () => {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel()],
      ['/dia?data=', dia({ pr_pct: null, pr_descartado: true })],
    ])
    montar()

    await screen.findByText('UFV Porto Ferreira')
    fireEvent.click(screen.getByRole('button', { name: 'Dia' }))

    expect(await screen.findByText('leitura descartada pelo monitoramento')).toBeTruthy()
    expect(screen.queryByText('0,0%')).toBeNull()
  })

  /** Abre a aba Dia com a resposta dada, já montada e clicada. */
  async function abrirODia(resposta: Dia) {
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel()],
      ['/dia?data=', resposta],
    ])
    montar()
    await screen.findByText('UFV Porto Ferreira')
    fireEvent.click(screen.getByRole('button', { name: 'Dia' }))
    await screen.findByText('A operação do dia')
  }

  const CURVA = [
    { hora: '09:00', kw: 2100, poa: null },
    { hora: '09:15', kw: 2400, poa: null },
  ]

  it('estação que existe e ainda não mediu hoje NÃO vira usina sem estação', async () => {
    // Às 3h da manhã não há sol, e a régua antiga fazia esta tela afirmar "esta usina não
    // tem estação solarimétrica" sobre a mesma usina que na véspera mediu 7,1 kWh/m².
    await abrirODia(
      dia({
        tem_estacao: true,
        estacao_com_leitura: false,
        estacao_indefinida: false,
        pr_pct: null,
        hpoa_agora: null,
        hpoa_acumulada: null,
        ghi_acumulada: null,
        curva: CURVA,
      }),
    )

    expect(
      screen.getAllByText(
        'A estação solarimétrica desta usina ainda não registrou leitura neste dia.',
      ).length,
    ).toBeGreaterThan(0)
    expect(screen.queryByText(/não tem estação solarimétrica/)).toBeNull()
    // O bloco de condições depende da LEITURA: três travessões em fila não informam nada.
    expect(screen.queryByText('Condições do dia')).toBeNull()
  })

  it('usina sem estação no cadastro continua dizendo que não tem', async () => {
    await abrirODia(
      dia({
        tem_estacao: false,
        estacao_com_leitura: false,
        estacao_indefinida: false,
        pr_pct: null,
        curva: CURVA,
      }),
    )

    expect(
      screen.getAllByText('Esta usina não tem estação solarimétrica — só a potência é medida.')
        .length,
    ).toBeGreaterThan(0)
  })

  it('cadastro que não pôde ser lido não vira afirmação sobre o aparelho', async () => {
    await abrirODia(
      dia({
        tem_estacao: false,
        estacao_com_leitura: false,
        estacao_indefinida: true,
        pr_pct: null,
        curva: CURVA,
      }),
    )

    expect(screen.queryByText(/não tem estação solarimétrica/)).toBeNull()
    expect(
      screen.getAllByText(
        'Não houve leitura de irradiância neste dia — e o cadastro dos aparelhos não pôde ser consultado agora.',
      ).length,
    ).toBeGreaterThan(0)
  })

  it('nas Unidades, a legenda ISOLA a unidade escolhida', async () => {
    const comUcs = unidades({
      ucs_ativas: 2,
      capacidade_total_kwp: 7402.5,
      energia_periodo_kwh: 540000,
      maior: { nome: 'UC Norte', share_pct: 61.2 },
      ucs: [
        {
          indice: 0,
          nome: 'UC Norte',
          capacidade_kwp: 4500,
          inversores: 12,
          geracao_kwh: 330000,
          share_pct: 61.2,
          produtividade: 73.3,
          pr_pct: 82.1,
          disponibilidade_real_pct: 99.8,
          disponibilidade_contratual_pct: 99.9,
          faturado_mwh: null,
        },
        {
          indice: 1,
          nome: 'UC Sul',
          capacidade_kwp: 2902.5,
          inversores: 8,
          geracao_kwh: 210000,
          share_pct: 38.8,
          produtividade: 72.4,
          pr_pct: null,
          disponibilidade_real_pct: 99.5,
          disponibilidade_contratual_pct: 99.7,
          faturado_mwh: 205.4,
        },
      ],
      serie_dias: ['2026-09-01', '2026-09-02'],
      serie: [
        { indice: 0, nome: 'UC Norte', valores: [20000, 21000] },
        { indice: 1, nome: 'UC Sul', valores: [12000, null] },
      ],
      ranking_geracao: [0, 1],
      ranking_pr: [0, 1],
      ranking_produtividade: [0, 1],
      faturas_situacao: 'Parcial',
    })
    servidor([
      ['plants/4', USINA],
      ['painel?recorte=ano', painel({ recorte: 'ano' })],
      ['painel?recorte=mes', painel()],
      ['/unidades?', comUcs],
    ])
    montar()

    await screen.findByText('UFV Porto Ferreira')
    fireEvent.click(screen.getByRole('button', { name: 'Unidades' }))

    expect(await screen.findByText('Geração diária · todas as unidades')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'UC Sul', pressed: false }))
    expect(await screen.findByText('Geração diária · UC Sul')).toBeTruthy()
    // Clicar de novo devolve o conjunto — a legenda alterna, não vira filtro grudado.
    fireEvent.click(screen.getByRole('button', { name: 'UC Sul', pressed: true }))
    expect(await screen.findByText('Geração diária · todas as unidades')).toBeTruthy()
  })

  describe('os quatro estados', () => {
    it('carregando: a tela abre com esqueleto, não com zeros', async () => {
      vi.spyOn(api, 'get').mockImplementation((() => new Promise(() => {})) as never)
      const { container } = montar()
      await waitFor(() => expect(container.querySelector('.animate-pulse')).toBeTruthy())
    })

    it('erro na usina: cartão de erro com "Tentar de novo"', async () => {
      vi.spyOn(api, 'get').mockRejectedValue(new Error('rede fora'))
      montar()
      // Prazo folgado de propósito: a leitura ainda tenta UMA vez antes de desistir (ver
      // `useLeitura`), e a espera dessa segunda tentativa passa do prazo padrão do
      // `findBy`. Encurtar aqui esconderia justamente o comportamento que se quer provar.
      expect(await screen.findByText('Não deu para carregar', {}, { timeout: 5000 })).toBeTruthy()
      expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeTruthy()
    })

    it('erro só no bloco: a página fica de pé e o bloco oferece nova tentativa', async () => {
      vi.spyOn(api, 'get').mockImplementation((async (url: string) => {
        if (String(url).includes('plants/4')) return { data: USINA }
        throw new Error('o monitoramento não respondeu')
      }) as never)
      montar()

      // O cabeçalho da usina continua na tela — o defeito é do painel, não da página.
      expect(await screen.findByText('UFV Porto Ferreira')).toBeTruthy()
      expect(
        await screen.findByText('o monitoramento não respondeu', {}, { timeout: 5000 }),
      ).toBeTruthy()
      expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeTruthy()
    })

    it('vazio: sem unidades, a tela explica em vez de mostrar tabela vazia', async () => {
      servidor([
        ['plants/4', USINA],
        ['painel?recorte=ano', painel({ recorte: 'ano' })],
        ['painel?recorte=mes', painel()],
        ['/unidades?', unidades()],
      ])
      montar()

      await screen.findByText('UFV Porto Ferreira')
      fireEvent.click(screen.getByRole('button', { name: 'Unidades' }))

      expect(
        await screen.findByText(
          'O monitoramento não devolveu unidades consumidoras nesta usina.',
        ),
      ).toBeTruthy()
      expect(screen.getAllByText('Sem unidades para comparar.').length).toBe(3)
    })

    it('offline: com cache e rede caída, mostra o dado velho COM o selo', async () => {
      // O cache é o do usuário 7 (`identificarCache`), e a chave carrega o caminho no BFF.
      localStorage.setItem(
        'leitura:u7:plants/4',
        JSON.stringify({ dados: USINA, gravadoEm: '2026-09-15T08:30:00.000Z' }),
      )
      vi.spyOn(api, 'get').mockRejectedValue(new Error('rede fora'))
      montar()

      expect(await screen.findByText('UFV Porto Ferreira')).toBeTruthy()
      expect(
        await screen.findByText(/Sem conexão com o servidor/, {}, { timeout: 5000 }),
      ).toBeTruthy()
    })
  })
  /**
   * O endereço é o que se manda por e-mail.
   *
   * O portal já decidira que a URL nomeia a família (`/manutencao/ordens`, e não `/ordens`)
   * porque "link colado em e-mail tem de dizer de que assunto se trata". A aba ficou de fora
   * dessa decisão e vivia em `useState`: abrir o Ano de Porto Ferreira e mandar o endereço
   * levava o destinatário para setembro. Recarregar a página fazia o mesmo estrago.
   */
  describe('o endereço carrega a tela', () => {
    it('`?aba=ano` abre no Ano — e pede ao BFF o painel do ano', async () => {
      const get = servidor([
        ['plants/4', USINA],
        ['painel?recorte=ano', painel({ recorte: 'ano' })],
        ['painel?recorte=mes', painel()],
      ])
      montar('/usinas/4/energia?aba=ano')

      await screen.findByText('UFV Porto Ferreira')
      // O conteúdo do ano é o que distingue a aba: o acumulado diz de que meses saiu.
      expect(await screen.findByText(/O acumulado soma/)).toBeTruthy()
      await waitFor(() => {
        const pedidos = get.mock.calls.map((c) => String(c[0]))
        expect(pedidos.some((p) => p.includes('painel?recorte=ano'))).toBe(true)
      })
    })

    it('aba inexistente cai no padrão, calada — endereço truncado não vira tela quebrada', async () => {
      const get = servidor([
        ['plants/4', USINA],
        ['painel?recorte=ano', painel({ recorte: 'ano' })],
        ['painel?recorte=mes', painel()],
      ])
      montar('/usinas/4/energia?aba=trimestre')

      await screen.findByText('UFV Porto Ferreira')
      // Cliente de e-mail corta endereço; o que não pode é a tela sumir por causa disso.
      // A prova de que valeu o padrão é o pedido do MÊS, que só a aba Mês faz.
      await waitFor(() => {
        const pedidos = get.mock.calls.map((c) => String(c[0]))
        expect(pedidos.some((p) => p.includes('painel?recorte=mes'))).toBe(true)
      })
    })

    it('trocar de aba ESCREVE no endereço — é o que torna o link mandável', async () => {
      servidor([
        ['plants/4', USINA],
        ['painel?recorte=ano', painel({ recorte: 'ano' })],
        ['painel?recorte=mes', painel()],
      ])
      montar()

      await screen.findByText('UFV Porto Ferreira')
      fireEvent.click(screen.getByRole('button', { name: 'Ano' }))

      await waitFor(() => {
        expect(enderecoAtual()).toContain('aba=ano')
      })
    })

    it('o padrão não suja o endereço: voltar ao Mês limpa o parâmetro', async () => {
      servidor([
        ['plants/4', USINA],
        ['painel?recorte=ano', painel({ recorte: 'ano' })],
        ['painel?recorte=mes', painel()],
      ])
      montar('/usinas/4/energia?aba=ano')

      await screen.findByText('UFV Porto Ferreira')
      fireEvent.click(screen.getByRole('button', { name: 'Mês' }))

      await waitFor(() => {
        expect(enderecoAtual()).not.toContain('aba=')
      })
    })
  })
})
