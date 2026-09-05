/**
 * A quinta aba — o fechamento do mês, sem a fábrica de PDF.
 *
 * O que cada teste guarda são afirmações que, desenhadas errado, ficam plausíveis na tela e
 * sempre a favor de alguém:
 *
 * 1. **A aba mora na URL e é travada no MÊS.** `?aba=relatorio` tem de abrir a aba, e o
 *    seletor de período tem de continuar o de mês: um fechamento narrativo de um ano não
 *    existe (as considerações, a timeline e a classificação das paradas são escritas mês a
 *    mês), e oferecer dia ou ano ali entregaria uma tela que o servidor não sabe responder.
 * 2. **O par potencial × medido é o motivo da aba existir.** Sem os dois desvios lado a
 *    lado, um mês fraco tem duas explicações possíveis — sol ou parada — e nenhuma escrita.
 * 3. **A perda diz sobre que base foi tirada.** O mesmo percentual muda conforme se divide
 *    pela fronteira ou pelos inversores; publicá-lo mudo é publicar um número que o cliente
 *    não tem como conferir.
 * 4. **Aqui não se gera documento.** A fábrica de impressão do meuWatt (botões, capa,
 *    contracapa, `window.print`) ficou lá por pedido do dono; este teste falha se qualquer
 *    palavra dela voltar ao DOM.
 * 5. **As considerações são somente leitura.** Um campo de edição poria o cliente dentro do
 *    caderno da equipe — e o valor do texto para ele é justamente ser o que a equipe
 *    assinou. Zero `<textarea>` e zero `<input>` na aba inteira.
 * 6. **Mês sem timeline não desenha uma espinha vazia.** Curadoria ausente é decisão de
 *    produto do meuWatt e atravessa: a seção não existe, e isso não é erro.
 * 7. **Lista de paradas vazia não é "a usina não parou".** Quando o monitoramento não
 *    respondeu, a tela diz que não sabe; as duas frases custam coisas diferentes.
 * 8. **A disponibilidade contratual sai do painel do MESMO mês.** É o número de teor
 *    contratual que as causas explicam; recontá-lo aqui daria ao portal duas respostas para
 *    a mesma pergunta — como já deu, com −64,3% numa tela e +101,7% na outra.
 * 9. **Sem classificação não é "interna".** O selo cinza é a ausência da causa, e ela fica
 *    no ranking de propósito: é a parcela que ainda pode mudar de lado na conta contratual.
 * 10. **As horas paradas nunca saem sem o denominador.** 141 h soltas leem-se como uma
 *    semana parada; ao lado de "de 4.090 h possíveis", leem-se como o que são.
 * 11. **As duas leituras da mesma perda, quando divergem, são NOMEADAS.** Reescalar uma
 *    pela outra produziria um kWh que ninguém mediu.
 * 12. **O potencial é impresso, não recalculado.** O servidor soma `medido + perdido` a
 *    partir do mesmo painel que a aba Mês publica; refazer a soma aqui é como o portal
 *    passou a ter dois números para a mesma perda.
 *
 * A data é congelada em 15/09/2026 porque a tela decide o que é mês em curso e o que já
 * fechou — sem relógio fixo, metade destas asserções mudaria conforme o dia em que rodam.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { Painel, RelatorioMes, UsinaDetalhe } from '@/features/energia/api'
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

const REGRA_DO_FECHAMENTO = {
  potencial:
    'Energia potencial = energia medida + energia perdida em paradas. É o que a usina teria entregue se não tivesse parado.',
  perda:
    'A energia perdida é a mesma que sustenta a disponibilidade do portal — um número só para a mesma pergunta.',
  horas:
    'As horas paradas somam o tempo de CADA inversor afetado, só no período diurno: uma parada de 1h que atinge 3 inversores soma 3h.',
  causas:
    'As causas vêm da classificação feita pela equipe. Parada ainda sem causa aparece como não classificada, e não é distribuída entre as demais.',
}

const AGRUPAMENTO =
  'Uma linha por parada registrada pelo monitoramento. Paradas que a equipe agrupou aparecem numa linha só, com o número de inversores atingidos.'

/**
 * O fechamento com os defaults do contrato do BFF.
 *
 * `paradas_origem: 'alertas'` é o default de propósito: quem quer testar o caso "o
 * monitoramento não respondeu" tem de dizer isso explicitamente, porque é exatamente a
 * distinção que o teste 7 guarda.
 */
function relatorio(parcial: Partial<RelatorioMes> = {}): RelatorioMes {
  return {
    referencia: '2026-09-01',
    inicio: '2026-09-01',
    fim: '2026-09-30',
    rotulo: 'Setembro / 2026',
    em_curso: true,
    dia_de_corte: 15,
    medido_inversores_kwh: 540000,
    perdida_kwh: 6200,
    projeto_proporcional_kwh: 560000,
    medido_vs_projeto_pct: -3.6,
    potencial_kwh: 546200,
    potencial_vs_projeto_pct: -2.5,
    perda_pct: 1.13,
    perda_base: 'inversor',
    perda_origem: 'monitoramento',
    horas_paradas: 141.6,
    horas_possiveis: 4090,
    inversores_considerados: 20,
    eventos_sem_duracao: 0,
    causas: [],
    eventos: [],
    paradas_origem: 'alertas',
    causas_total_kwh: null,
    causas_origem: 'alertas',
    causas_conferem: null,
    eventos_agrupamento: AGRUPAMENTO,
    consideracoes: null,
    timeline: { exibir: false, marcos: [] },
    regra: REGRA_DO_FECHAMENTO,
    aviso: null,
    ...parcial,
  }
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

/** O painel do mês — só o que a aba Relatório lê dele: as duas disponibilidades. */
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
    disponibilidade_real_pct: 98.42,
    disponibilidade_contratual_pct: 99.31,
    paradas_pendentes: 2,
    perdida_kwh: 6200,
    perdida_externa_kwh: 1100,
    desvios: {
      medido_vs_projeto_pct: -3.6,
      medido_vs_previsto_pct: null,
      previsto_vs_projeto_pct: null,
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
    meteo: METEO_VAZIA,
    janela: {
      meses: ['2026-09'],
      fora: [],
      rotulo: 'set de 2026',
      parcial: false,
      regra: 'O acumulado vai do dia 1 até o último dia medido.',
    },
    regra: {
      disponibilidade: 'Disponibilidade = energia medida ÷ energia esperada.',
      contratual: 'A contratual desconta a energia perdida por causa externa.',
      perda_distribuida: 'Parada de vários dias tem a perda distribuída entre eles.',
      origem: 'Os percentuais vêm prontos do monitoramento.',
    },
    dias: [],
    meses: [],
    meses_disponiveis: null,
    disponibilidade_tecnica: null,
    aviso: null,
    ...parcial,
  }
}

/** O dublê do BFF: casa o pedaço do endereço com a resposta. A ordem importa. */
function servidor(pares: [string, unknown][]) {
  return vi.spyOn(api, 'get').mockImplementation((async (url: string) => {
    for (const [pedaco, dados] of pares) {
      if (String(url).includes(pedaco)) return { data: dados }
    }
    throw new Error(`sem dublê para ${url}`)
  }) as never)
}

/** O cenário completo: usina, painel do ano (que o seletor de mês lê), painel do mês e o
 *  fechamento. Quem quiser um caso sem painel do mês omite o par correspondente. */
function cenario(r: RelatorioMes, p: Painel | null = painel()) {
  const pares: [string, unknown][] = [
    ['plants/4', USINA],
    ['relatorio-mes', r],
    ['painel?recorte=ano', painel({ recorte: 'ano' })],
  ]
  if (p) pares.push(['painel?recorte=mes', p])
  return servidor(pares)
}

function montar(endereco = '/usinas/4/energia?aba=relatorio') {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[endereco]}>
        <Routes>
          <Route path="/usinas/:id/energia" element={<PainelDeEnergia />} />
        </Routes>
      </MemoryRouter>,
    </QueryClientProvider>,
  )
}

describe('Painel de energia · aba Relatório', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(HOJE)
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    limparCache()
  })

  it('?aba=relatorio abre a aba e pede o fechamento do mês ao BFF', async () => {
    const get = cenario(relatorio())
    montar()

    await screen.findByText('O fechamento de Setembro / 2026')
    await waitFor(() => {
      const pedidos = get.mock.calls.map((c) => String(c[0]))
      expect(pedidos.some((p) => p.includes('energia/usinas/4/relatorio-mes'))).toBe(true)
      // A referência é normalizada para o dia 1: o BFF só usa o mês, e sem normalizar o
      // dia 15 e o dia 16 criariam duas chaves de cache para a MESMA resposta.
      expect(pedidos.some((p) => p.includes('relatorio-mes?referencia=2026-09-01'))).toBe(true)
    })
  })

  it('o seletor de período fica no MÊS — não há passo de dia nem de ano', async () => {
    cenario(relatorio())
    montar()

    await screen.findByText('O fechamento de Setembro / 2026')
    // O seletor de mês (com a lista dos meses medidos) é exclusivo do recorte mensal.
    expect(screen.getByRole('button', { name: 'Escolher o mês' })).toBeTruthy()
    // E o rótulo do passo é o do MÊS: nem "2026" (ano) nem "15 de Set de 2026" (dia).
    expect(screen.getByText('Setembro de 2026')).toBeTruthy()
    expect(screen.queryByText('15 de Set de 2026')).toBeNull()
    expect(screen.queryByText('2026')).toBeNull()
  })

  it('publica energia potencial e potencial vs projeto — o par que separa sol de parada', async () => {
    cenario(relatorio())
    montar()

    await screen.findByText('Energia potencial')
    // 546.200 kWh → "546,2 MWh". O número é IMPRESSO: o servidor somou medido + perdido a
    // partir do mesmo painel que a aba Mês publica.
    expect(screen.getByText('546,2 MWh')).toBeTruthy()
    expect(screen.getByText('Potencial vs projeto')).toBeTruthy()
    expect(screen.getByText('−2,5%')).toBeTruthy()
    // E o par: o desvio do medido continua ao lado, senão não há comparação nenhuma.
    expect(screen.getByText('Medido vs projeto')).toBeTruthy()
    expect(screen.getByText('−3,6%')).toBeTruthy()
  })

  it('o potencial é o que o servidor mandou — a tela não refaz a soma', async () => {
    // Um potencial que NÃO é medido + perdido: se a tela recalculasse, ela imprimiria
    // 546,2 MWh e este teste passaria a medir a conta da tela, não a do servidor.
    cenario(relatorio({ potencial_kwh: 700000 }))
    montar()

    await screen.findByText('Energia potencial')
    expect(screen.getByText('700,0 MWh')).toBeTruthy()
    expect(screen.queryByText('546,2 MWh')).toBeNull()
  })

  it('o cartão de perdas escreve a base do percentual — "base inversor"', async () => {
    cenario(relatorio({ perda_pct: 1.13, perda_base: 'inversor' }))
    montar()

    await screen.findByText('Da geração do mês')
    expect(screen.getByText('1,1%')).toBeTruthy()
    expect(screen.getByText(/base inversor/)).toBeTruthy()
    expect(screen.queryByText(/base fronteira/)).toBeNull()
  })

  it('quando a base é a fronteira, é ISSO que a tela escreve', async () => {
    cenario(relatorio({ perda_pct: 0.98, perda_base: 'fronteira' }))
    montar()

    await screen.findByText('Da geração do mês')
    expect(screen.getByText(/base fronteira/)).toBeTruthy()
    expect(screen.queryByText(/base inversor/)).toBeNull()
  })

  it('não há fábrica de PDF: nem "PDF", nem "Imprimir", nem window.print', async () => {
    const imprimir = vi.fn()
    // `window.print` não existe no jsdom; declará-lo é o que permite provar que ninguém o
    // chama — e a espiã pega também um `beforeprint` que alguém plugasse.
    Object.defineProperty(window, 'print', { value: imprimir, configurable: true, writable: true })

    cenario(
      relatorio({
        consideracoes: { texto: 'Mês normal.', autor: 'Equipe', em: '2026-10-02T14:10:00' },
        causas: [
          {
            categoria: 'Falha de comunicação',
            eventos: 3,
            energia_kwh: 4200,
            horas: 120,
            externa: false,
            classificada: true,
          },
        ],
        timeline: {
          exibir: true,
          marcos: [
            {
              id: 'm1',
              em: '2026-09-04T08:00:00',
              tom: 'parada',
              chip: 'Parada',
              titulo: 'Inversor 7 fora',
              sub: null,
              grupo: 'g1',
            },
          ],
        },
      }),
    )
    const { container } = montar()

    await screen.findByText('O fechamento de Setembro / 2026')
    const texto = container.textContent ?? ''
    expect(texto).not.toContain('PDF')
    expect(texto).not.toContain('Imprimir')
    expect(texto).not.toContain('imprimir')
    expect(imprimir).not.toHaveBeenCalled()
  })

  it('as considerações são TEXTO com autor e data — zero campos de edição na aba', async () => {
    cenario(
      relatorio({
        consideracoes: {
          texto: 'Mês marcado pela troca do inversor 7.\nSem impacto contratual.',
          autor: 'Marina Duarte',
          em: '2026-10-02T14:10:00',
        },
      }),
    )
    const { container } = montar()

    const bloco = await screen.findByTestId('consideracoes')
    expect(bloco.textContent).toContain('Mês marcado pela troca do inversor 7.')
    expect(screen.getByText(/Marina Duarte/)).toBeTruthy()
    expect(screen.getByText(/02\/10/)).toBeTruthy()
    // Somente leitura: escrever o fechamento é trabalho de operação.
    expect(container.querySelectorAll('textarea').length).toBe(0)
    expect(container.querySelectorAll('input').length).toBe(0)
    expect(container.querySelectorAll('[contenteditable="true"]').length).toBe(0)
  })

  it('mês sem considerações diz que a equipe ainda não escreveu — e não some calado', async () => {
    cenario(relatorio({ consideracoes: null }))
    montar()

    await screen.findByText('Considerações gerais de Setembro / 2026')
    expect(screen.getByText(/ainda não escreveu o fechamento deste mês/)).toBeTruthy()
    expect(screen.queryByTestId('consideracoes')).toBeNull()
  })

  it('usina sem timeline curada não desenha a seção — e não mostra erro', async () => {
    const { container } = (() => {
      cenario(relatorio({ timeline: { exibir: false, marcos: [] } }))
      return montar()
    })()

    await screen.findByText('O fechamento de Setembro / 2026')
    expect(screen.queryByTestId('timeline')).toBeNull()
    expect(screen.queryByText('A história do mês')).toBeNull()
    // Ausência de curadoria é decisão de produto, não falha: nada de erro na tela.
    expect(container.textContent).not.toContain('Não deu para carregar')
    expect(container.textContent).not.toContain('Tentar de novo')
  })

  it('timeline curada aparece com o marco, e o tom narrativo vira um dos seis tons', async () => {
    cenario(
      relatorio({
        timeline: {
          exibir: true,
          marcos: [
            {
              id: 'm1',
              em: '2026-09-04T08:00:00',
              tom: 'parada',
              chip: 'Parada',
              titulo: 'Skid 2 fora por queda da concessionária',
              sub: 'Retomado às 11h40',
              grupo: 'g1',
            },
            {
              id: 'm2',
              em: '2026-09-04T11:40:00',
              tom: 'inventado_pelo_upstream',
              chip: 'Novo',
              titulo: 'Vocabulário que ainda não existe aqui',
              sub: null,
              grupo: 'g1',
            },
          ],
        },
      }),
    )
    const { container } = montar()

    await screen.findByTestId('timeline')
    expect(screen.getByText('Skid 2 fora por queda da concessionária')).toBeTruthy()
    expect(screen.getByText('Retomado às 11h40')).toBeTruthy()
    // `parada` é traduzido para o tom vermelho do portal; o nome desconhecido cai no
    // neutro, nunca numa cor errada.
    expect(container.querySelector('.bg-tom-parado')).toBeTruthy()
    expect(container.querySelector('.bg-tom-semDados')).toBeTruthy()
  })

  it('paradas não lidas ≠ usina que não parou', async () => {
    cenario(relatorio({ paradas_origem: null, causas: [], eventos: [] }))
    montar()

    await screen.findByText('Por que a usina parou')
    expect(screen.getByText(/não puderam ser lidas neste período/)).toBeTruthy()
    expect(screen.queryByText('Nenhuma parada registrada no período.')).toBeNull()
  })

  it('mês realmente sem parada diz que não houve nenhuma', async () => {
    cenario(relatorio({ paradas_origem: 'alertas', causas: [], eventos: [] }))
    montar()

    await screen.findByText('Por que a usina parou')
    expect(screen.getByText('Nenhuma parada registrada no período.')).toBeTruthy()
  })

  it('o ranking de causas classifica externa, interna e não classificada — sem confundir as duas últimas', async () => {
    cenario(
      relatorio({
        causas: [
          {
            categoria: 'Queda da concessionária',
            eventos: 2,
            energia_kwh: 3100,
            horas: 8.5,
            externa: true,
            classificada: true,
          },
          {
            categoria: 'Falha de comunicação',
            eventos: 4,
            energia_kwh: 1800,
            horas: 30,
            externa: false,
            classificada: true,
          },
          {
            categoria: 'Não classificada',
            eventos: 1,
            energia_kwh: 900,
            horas: null,
            externa: false,
            classificada: false,
          },
        ],
      }),
    )
    montar()

    await screen.findByText('Queda da concessionária')
    expect(screen.getByText('Externa')).toBeTruthy()
    expect(screen.getByText('Interna')).toBeTruthy()
    // A parada sem causa NÃO vira "Interna": é a ausência da classificação, e ela fica no
    // ranking porque é a parcela que ainda pode mudar de lado na conta contratual.
    expect(screen.getAllByText('Não classificada').length).toBeGreaterThan(0)
    // Categoria sem horas sai em travessão, nunca em zero.
    expect(screen.getByText('—')).toBeTruthy()
    expect(screen.queryByText('0,0 h')).toBeNull()
  })

  it('a disponibilidade contratual vem do painel do MESMO mês, ao lado das causas', async () => {
    cenario(
      relatorio({
        causas: [
          {
            categoria: 'Queda da concessionária',
            eventos: 2,
            energia_kwh: 3100,
            horas: 8.5,
            externa: true,
            classificada: true,
          },
        ],
      }),
      painel({ disponibilidade_real_pct: 98.42, disponibilidade_contratual_pct: 99.31 }),
    )
    montar()

    await screen.findByText('Disponibilidade contratual')
    expect(screen.getByText('99,3%')).toBeTruthy()
    expect(screen.getByText('98,4%')).toBeTruthy()
    // Enquanto houver parada sem causa, a contratual está incompleta — e a tela diz.
    expect(screen.getByText(/a contratual está incompleta/)).toBeTruthy()
  })

  it('as horas paradas nunca saem sem o denominador', async () => {
    const { container } = (() => {
      cenario(relatorio({ horas_paradas: 141.6, horas_possiveis: 4090, inversores_considerados: 20 }))
      return montar()
    })()

    await screen.findByText('Horas paradas')
    expect(screen.getAllByText('141,6 h').length).toBeGreaterThan(0)
    expect(screen.getAllByText('4.090,0 h').length).toBeGreaterThan(0)
    // O denominador aparece nas duas pontas: no detalhe do KPI e no texto da régua.
    expect(screen.getAllByText(/possíveis/).length).toBeGreaterThan(0)
    // E a régua, que é o que impede o absoluto de ser lido para o lado alarmante.
    expect(container.querySelector('[data-testid="regua-horas"]')).toBeTruthy()
  })

  it('parada sem duração calculada deixa as horas em travessão e explica por quê', async () => {
    cenario(relatorio({ horas_paradas: null, eventos_sem_duracao: 2 }))
    montar()

    await screen.findByText('Horas paradas')
    expect(screen.getByText(/2 paradas vieram sem duração calculada/)).toBeTruthy()
    // Sem as duas pontas, não há régua: uma barra vazia seria "não parou nada".
    expect(screen.queryByTestId('regua-horas')).toBeNull()
  })

  it('quando as duas leituras da mesma perda não batem, a tela NOMEIA cada janela', async () => {
    cenario(
      relatorio({
        perdida_kwh: 6200,
        perda_origem: 'monitoramento',
        causas_total_kwh: 5100,
        causas_origem: 'alertas',
        causas_conferem: false,
        causas: [
          {
            categoria: 'Falha de comunicação',
            eventos: 4,
            energia_kwh: 5100,
            horas: 30,
            externa: false,
            classificada: true,
          },
        ],
      }),
    )
    montar()

    await screen.findByText('Por que a usina parou')
    expect(screen.getByText(/não fecha com a energia perdida do período/)).toBeTruthy()
    expect(screen.getByText(/de alertas/)).toBeTruthy()
    expect(screen.getByText(/de monitoramento/)).toBeTruthy()
  })

  it('as paradas do mês listam causa, inversores atingidos e a limitação do agrupamento', async () => {
    cenario(
      relatorio({
        eventos: [
          {
            inicio: '2026-09-04',
            fim: '2026-09-04',
            em_aberto: false,
            tipo: 'parada',
            unidade: 'UC Centro',
            causa: 'Queda da concessionária',
            origem: 'externa',
            externa: true,
            classificada: true,
            inversores_afetados: 3,
            horas: 8.5,
            energia_kwh: 3100,
          },
          {
            inicio: '2026-09-11',
            fim: null,
            em_aberto: true,
            tipo: 'degradacao',
            unidade: null,
            causa: null,
            origem: null,
            externa: false,
            classificada: false,
            inversores_afetados: 1,
            horas: null,
            energia_kwh: null,
          },
        ],
      }),
    )
    montar()

    await screen.findByText('As paradas do mês')
    expect(screen.getByText('Queda da concessionária')).toBeTruthy()
    expect(screen.getByText('UC Centro')).toBeTruthy()
    expect(screen.getByText('em aberto')).toBeTruthy()
    expect(screen.getByText('Baixa geração')).toBeTruthy()
    // A limitação da FONTE é declarada pelo servidor e impressa aqui.
    expect(screen.getByText(AGRUPAMENTO)).toBeTruthy()
  })

  it('o aviso do servidor aparece — e a aba abre mesmo com parte dos dados faltando', async () => {
    cenario(
      relatorio({
        aviso: 'Faltou parte dos dados: as considerações do mês não vieram.',
        consideracoes: null,
      }),
    )
    montar()

    expect(
      await screen.findByText('Faltou parte dos dados: as considerações do mês não vieram.'),
    ).toBeTruthy()
    expect(screen.getByText('O fechamento de Setembro / 2026')).toBeTruthy()
  })

  it('trocar de aba leva o Relatório para a URL e traz de volta o conteúdo do mês', async () => {
    cenario(relatorio())
    montar('/usinas/4/energia')

    // Abre no Mês (o padrão) e o fechamento ainda não foi pedido.
    await screen.findByText('Quanto a usina gerou · Setembro / 2026')
    expect(screen.queryByText('O fechamento de Setembro / 2026')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Relatório' }))
    await screen.findByText('O fechamento de Setembro / 2026')
    expect(screen.queryByText('Quanto a usina gerou · Setembro / 2026')).toBeNull()
  })
})
