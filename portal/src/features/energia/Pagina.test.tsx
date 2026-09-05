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
 *
 * A data é congelada em 15/09/2026 porque a tela decide o que é passado, o que é o mês em
 * curso e o que é futuro; sem relógio fixo, metade destas asserções mudaria de resultado
 * conforme o dia em que o teste roda.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { Dia, Painel, Unidades, UsinaDetalhe } from '@/features/energia/api'
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
  t_amb_media: null,
  t_amb_max: null,
  t_mod_media: null,
  t_mod_max: null,
  pontos: [],
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
    projeto_kwh: 1100000,
    projeto_proporcional_kwh: 560000,
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
    },
    totais: {
      medido_kwh: 540000,
      projeto_kwh: 1100000,
      projeto_ate_hoje_kwh: 560000,
      tendencia_kwh: 1080000,
    },
    meteo: { ...METEO_VAZIA, tem_estacao: true, hpoa: 120.4, ghi: 108.9, razao: 1.11, pontos: [] },
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

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/usinas/4/energia']}>
        <Routes>
          <Route path="/usinas/:id/energia" element={<PainelDeEnergia />} />
        </Routes>
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
})
