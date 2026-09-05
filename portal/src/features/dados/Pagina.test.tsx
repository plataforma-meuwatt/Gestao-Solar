/**
 * O que estes testes guardam é a diferença entre uma tela que respeita os três limites do
 * servidor e uma que os confunde — e confundi-los produz, sempre, um dos dois piores desfechos
 * desta tela: um muro sem porta, ou trinta e quatro segundos de espera para receber um 400.
 *
 * 1. **Teto de dias por passo IMPEDE ANTES, com a conta feita e a saída nomeada.** É aritmética
 *    nossa e certa. Deixar clicar para receber a recusa depois da espera seria teatro; impedir
 *    sem dizer o número e sem nomear a alternativa seria um muro.
 * 2. **Retenção NÃO é limite do arquivo, é ausência de dado** — e por isso mora no seletor de
 *    período, colada em cada dia oferecido, com a saída que o próprio código do servidor
 *    garante (a checagem inteira está dentro de `if step != "1d"`: o total por dia não tem
 *    prazo). Sem essa frase, "o portal não tem" se lê como defeito do portal.
 * 3. **Orçamento de células é ESTIMATIVA nossa, e por isso DEIXA PEDIR.** No limiar, o
 *    benefício da dúvida é do cliente: bloquear por uma conta minha que o servidor talvez
 *    aceitasse é recusar um arquivo que existiria.
 * 4. **O `motivo` é traduzido; o `message` do meuWatt nunca é ecoado** — ele foi escrito para o
 *    operador de lá e fala em balde, snapshots e SSU. E a natureza da recusa decide a peça:
 *    espera ganha "Tentar de novo"; regra violada, não — repetir um `muito_grande` dá
 *    exatamente o mesmo resultado.
 * 5. **`series: null` não é "listei todos".** Nulo é "não mexi", e o inversor comissionado no
 *    meio do período entra sozinho no arquivo. Uma lista explícita congela o conjunto no que a
 *    tela viu. Se o corpo do POST perder essa distinção, ninguém percebe: o arquivo sai, só
 *    que sem uma coluna que deveria estar lá.
 *
 * E, por baixo de tudo: **a chave de série (`slot:170`) é transporte e não pode aparecer na
 * tela** — é o mesmo defeito que a `SeloClasse` já corrigiu quando a OS saía
 * "SERVICOS_ADICIONAIS" numa tela e "Serviços adicionais" na outra.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import { corpoDoPedido, nomeDoArquivo, type OpcoesDeDados, type Selecao } from '@/features/dados/api'
import {
  diasOferecidos,
  estimativa,
  impedimento,
  janelaDo,
  montarPacote,
  motivoDoPacote,
  passaDoOrcamento,
  traduzirMotivo,
} from '@/features/dados/pacotes'
import BaixarDados from '@/features/dados/Pagina'

// O salvamento do arquivo não é desta tela (é `lib/arquivo`), e o jsdom não tem
// `URL.createObjectURL`. O que se prova aqui é O QUE foi pedido e o que a tela disse.
vi.mock('@/lib/arquivo', () => ({ baixarBlob: vi.fn() }))
import { baixarBlob } from '@/lib/arquivo'

const USINA = 4

/** Porto Ferreira como ela é hoje, medida em 05/09/2026 pelo `GET /energia/dados/opcoes`. */
function opcoes(parcial: Partial<OpcoesDeDados> = {}): OpcoesDeDados {
  return {
    usina: { id: USINA, nome: 'Porto Ferreira', capacidade_kwp: 7402.5 },
    skids: [
      {
        id: 1,
        nome: 'SKID-01',
        capacidade_kwp: 1500,
        series: [
          { chave: 'slot:170', rotulo: 'Inv 13', numero_serie: 'GR2579042017', capacidade_kwp: 375 },
          { chave: 'slot:171', rotulo: 'Inv 14', numero_serie: 'GR2579042018', capacidade_kwp: 375 },
        ],
      },
      {
        id: 2,
        nome: 'SKID-02',
        capacidade_kwp: 1500,
        series: [
          { chave: 'slot:172', rotulo: 'Inv 15', numero_serie: 'GR2579042019', capacidade_kwp: 375 },
        ],
      },
    ],
    estacao: {
      disponivel: true,
      colunas: { poa: true, ghi: true, temp_modulo: false, temp_ambiente: false, vento: false },
      temp_ambiente_rele: true,
    },
    leitores: [{ id: 14, nome: 'Leitor Concessionária SKID 1' }],
    sistema: { pr: true, produtividade: true },
    retencao: { snapshots_desde: '2026-03-06', ssu_desde: '2024-09-05' },
    limites: { native: 7, '5m': 31, '15m': 92, '1h': 366, '1d': 366, max_celulas: 2_000_000 },
    ...parcial,
  }
}

function montar(dados: OpcoesDeDados = opcoes()) {
  vi.spyOn(api, 'get').mockResolvedValue({ data: dados } as never)
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[`/usinas/${USINA}/energia/dados`]}>
        <Routes>
          <Route path="/usinas/:id/energia/dados" element={<BaixarDados />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Uma resposta de `fetch` com corpo de planilha — o suficiente para passar do piso de 100 B. */
function planilha(): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'attachment; filename="dados-porto-ferreira-2026-08.xlsx"' },
    blob: async () => new Blob([new Uint8Array(4096)]),
    json: async () => ({}),
  } as unknown as Response
}

/** A recusa do BFF: `motivo` no PRIMEIRO nível, ao lado de `detail`. */
function recusa(status: number, motivo: string, message: string): Response {
  return {
    ok: false,
    status,
    headers: { get: () => null },
    json: async () => ({ detail: 'O monitoramento recusou este pedido.', motivo, message }),
    blob: async () => new Blob([]),
  } as unknown as Response
}

/** Abre a lista suspensa cujo gatilho mostra `rotulo` e escolhe a opção `alvo`. */
function escolher(rotuloAtual: string | RegExp, alvo: string | RegExp) {
  fireEvent.click(screen.getByRole('button', { name: rotuloAtual }))
  fireEvent.click(screen.getByRole('button', { name: alvo }))
}

async function telaPronta() {
  await screen.findByText('O que você quer levar')
}

describe('tela Baixar dados', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(1)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    // A conta de dias depende do "hoje": sem relógio fixo, o teste passaria hoje e falharia
    // em janeiro, sem nada ter mudado.
    vi.setSystemTime(new Date(2026, 8, 5, 12, 0, 0))
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.mocked(baixarBlob).mockClear()
    limparCache()
  })

  /* ---------------------------------------------------------------- 1. teto */

  it('o teto de dias impede ANTES, faz a conta e nomeia a saída', async () => {
    const buscar = vi.fn()
    vi.stubGlobal('fetch', buscar)
    montar()
    await telaPronta()

    // Ano corrente: 1º de janeiro a 5 de setembro de 2026 = 248 dias. O detalhe sugerido vira
    // "um total por dia" (que aceita 366); trocar para "a cada 5 minutos" (que aceita 31) é a
    // combinação que o servidor recusaria depois de meio minuto de espera.
    fireEvent.click(screen.getByRole('button', { name: 'Ano' }))
    escolher('Um total por dia', /A cada 5 minutos/)

    const aviso = screen.getByText(/O período tem 248 dias/)
    expect(aviso.textContent).toContain('"A cada 5 minutos" aceita 31')
    // A saída NOMEADA — sem ela isto seria um muro sem porta.
    expect(aviso.textContent).toContain('de hora em hora')
    expect(aviso.textContent).toContain('366')

    const botao = screen.getByRole('button', { name: 'Baixar planilha' })
    expect((botao as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(botao)
    expect(buscar).not.toHaveBeenCalled()

    // E a opção proibida CONTINUA escolhível na lista: desabilitá-la esconderia o porquê.
    fireEvent.click(screen.getByRole('button', { name: /A cada 5 minutos/ }))
    const alternativa = screen.getByRole('button', { name: /A cada 15 minutos/ })
    expect((alternativa as HTMLButtonElement).disabled).toBe(false)
  })

  /* ------------------------------------------------------------ 2. retenção */

  it('a retenção viaja colada no dia oferecido, e a saída é o total por dia', async () => {
    montar()
    await telaPronta()

    fireEvent.click(screen.getByRole('button', { name: 'Personalizado' }))
    // A lista de dias tem busca (são centenas): filtra-se pelo dia que se quer.
    const gatilhos = screen.getAllByRole('button', { name: /05\/09\/2026|01\/09\/2026/ })
    fireEvent.click(gatilhos[0])
    fireEvent.change(screen.getByPlaceholderText('Buscar…'), { target: { value: '01/02/2026' } })

    // O motivo está NA OPÇÃO, enquanto se escolhe — não depois de esperar meio minuto.
    expect(screen.getByText('a leitura minuto a minuto não existe mais — só o total por dia')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /01\/02\/2026/ }))

    const aviso = await screen.findByText(/A leitura fina de inversores e estação só existe desde/)
    expect(aviso.textContent).toContain('06/03/2026')
    expect(aviso.textContent).toContain('um total por dia')
    expect(aviso.textContent).toContain('não tem prazo')
  })

  /* ----------------------------------------------------------- 3. orçamento */

  it('a estimativa avisa mas DEIXA PEDIR — no limiar a palavra final é do servidor', async () => {
    const buscar = vi.fn().mockResolvedValue(planilha())
    vi.stubGlobal('fetch', buscar)
    // Orçamento minúsculo: qualquer pedido passa da nossa conta. O servidor é quem decide.
    montar(opcoes({ limites: { native: 7, '5m': 31, '15m': 92, '1h': 366, '1d': 366, max_celulas: 10 } }))
    await telaPronta()

    expect(screen.getByText(/perto do que um arquivo aguenta/)).toBeTruthy()
    const botao = screen.getByRole('button', { name: 'Baixar planilha' })
    expect((botao as HTMLButtonElement).disabled).toBe(false)

    fireEvent.click(botao)
    await waitFor(() => expect(vi.mocked(baixarBlob)).toHaveBeenCalledTimes(1))
    expect(buscar).toHaveBeenCalledTimes(1)
  })

  /* -------------------------------------------------------------- 4. recusa */

  it('a regra violada vira aviso SEM "tentar de novo"; a espera vira aviso COM', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(
        recusa(400, 'muito_grande', 'O arquivo teria ≈ 2.400.000 células (limite 2.000.000).'),
      )
      .mockResolvedValueOnce(
        recusa(429, 'muitos_pedidos', 'Rate limit exceeded: 10 per 1 minute'),
      )
    vi.stubGlobal('fetch', buscar)
    montar()
    await telaPronta()

    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await screen.findByText(/maior do que o monitoramento monta/)
    // A frase do operador do meuWatt não chega ao cliente: ele não sabe o que é uma célula de
    // orçamento, e "limite 2.000.000" não lhe diz o que fazer.
    expect(screen.queryByText(/células/)).toBeNull()
    expect(screen.queryByText(/limite 2\.000\.000/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Tentar de novo' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await screen.findByText(/atendendo muitos pedidos agora/)
    expect(screen.queryByText(/Rate limit/)).toBeNull()
    // Espera é o oposto de regra violada: repetir daqui a pouco funciona.
    expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeTruthy()
  })

  it('os seis motivos do servidor, mais a espera, têm tradução — e nenhuma é a frase de lá', () => {
    const motivos = [
      'periodo_invalido',
      'passo_excede_limite',
      'fora_da_retencao',
      'bloco_indisponivel',
      'sem_blocos',
      'muito_grande',
    ]
    for (const m of motivos) {
      const t = traduzirMotivo(m)
      expect(t, m).not.toBeNull()
      expect(t!.texto.length).toBeGreaterThan(20)
      expect(t!.espera).toBe(false)
      expect(t!.texto).not.toMatch(/snapshot|SSU|balde|células/i)
    }
    expect(traduzirMotivo('muitos_pedidos')!.espera).toBe(true)
    // Motivo que a tela não conhece cai no erro de transporte, que TEM "tentar de novo" — e
    // não é traduzido por chute.
    expect(traduzirMotivo('motivo_que_nasceu_ontem')).toBeNull()
    expect(traduzirMotivo(null)).toBeNull()
  })

  /* --------------------------------------------------------------- 5. série */

  it('"todos" viaja como campo AUSENTE, não como a lista de todos os inversores', async () => {
    const buscar = vi.fn().mockResolvedValue(planilha())
    vi.stubGlobal('fetch', buscar)
    montar()
    await telaPronta()

    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await waitFor(() => expect(buscar).toHaveBeenCalledTimes(1))

    const [url, init] = buscar.mock.calls[0]
    expect(String(url)).toContain(`/api/v1/energia/dados/arquivo?usina_id=${USINA}`)
    expect(String(url)).not.toMatch(/token|Bearer/i)
    const corpo = JSON.parse(String((init as RequestInit).body))
    expect(corpo.inversores.variaveis).toEqual(['geracao'])
    // A prova: a chave nem existe. `[]` seria "nenhuma série" e o arquivo sairia sem colunas;
    // a lista completa congelaria o conjunto e deixaria de fora o inversor que entrar depois.
    expect('series' in corpo.inversores).toBe(false)
    expect(corpo.estacao).toBeUndefined()
    expect(corpo.passo).toBe('1h')
  })

  it('o corpo do pedido separa os três estados de "quais inversores"', () => {
    const base = {
      inicio: '2026-08-01',
      fim: '2026-08-31',
      hora_inicio: '00:00',
      hora_fim: '23:59',
      passo: '1h' as const,
      estacao: null,
      fronteira: null,
      sistema: null,
    }
    const nulo = corpoDoPedido({
      ...base,
      inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: null },
    })
    const todas = corpoDoPedido({
      ...base,
      inversores: {
        variaveis: ['geracao'],
        agrupamento: 'lista',
        series: ['slot:170', 'slot:171', 'slot:172'],
      },
    })
    const vazio = corpoDoPedido({
      ...base,
      inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: [] },
    })
    expect('series' in (nulo.inversores as object)).toBe(false)
    expect((todas.inversores as { series: string[] }).series).toHaveLength(3)
    expect((vazio.inversores as { series: string[] }).series).toEqual([])
    // E a lista vazia nunca chega a viajar: a tela impede, porque `[]` no upstream é um
    // arquivo sem colunas.
    const nada: Selecao = {
      inversores: { variaveis: ['geracao'], agrupamento: 'lista', series: [] },
      estacao: null,
      fronteira: null,
      sistema: null,
    }
    const j = janelaDo('2026-08-01', '2026-08-31', '00:00', '23:59', '1h', false)
    expect(impedimento(nada, '1h', j, '2026-08-01', opcoes())!.texto).toContain(
      'Nenhum inversor está marcado',
    )
  })

  /* ------------------------------------------------------- o que a usina não tem */

  it('o pacote impossível continua na lista, desabilitado e com o motivo', async () => {
    montar(opcoes({ leitores: [] }))
    await telaPronta()

    fireEvent.click(screen.getByRole('button', { name: 'Geração da usina' }))
    const impossivel = screen.getByRole('button', { name: /Energia no medidor/ })
    // A linha NÃO some: sumir faria o cliente concluir que o portal não oferece, quando o
    // fato é sobre a usina dele. O que ela perde é o clique — e o motivo está escrito.
    expect((impossivel as HTMLButtonElement).disabled).toBe(true)
    expect(impossivel.textContent).toContain('esta usina não tem medidor de fronteira')

    fireEvent.click(impossivel)
    expect(screen.getAllByRole('button', { name: 'Geração da usina' }).length).toBeGreaterThan(0)
  })

  it('a ausência DERIVADA diz a cadeia inteira, e a estação parcial diz o que não vem', () => {
    const semEstacao = opcoes({
      estacao: { disponivel: false, colunas: {}, temp_ambiente_rele: false },
      sistema: { pr: false, produtividade: false },
    })
    expect(motivoDoPacote('desempenho', semEstacao)).toBe(
      'sem estação não há irradiação, e sem irradiação não se calcula PR',
    )
    expect(motivoDoPacote('geracao_clima', semEstacao)).toBe(
      'esta usina não tem estação solarimétrica com dados',
    )
    // Porto Ferreira mede POA e GHI e mais nada: o pacote não falha, leva o que existe — e diz
    // o que ficou de fora, senão faltaria uma coluna sem explicação.
    const sel = montarPacote('geracao_clima', opcoes())
    expect(sel.estacao!.variaveis).toEqual(['poa', 'ghi'])
  })

  /* --------------------------------------------------- a chave é transporte */

  it('a chave de série não aparece na tela, e tirar um inversor MATERIALIZA a lista', async () => {
    const buscar = vi.fn().mockResolvedValue(planilha())
    vi.stubGlobal('fetch', buscar)
    const { container } = montar()
    await telaPronta()

    fireEvent.click(screen.getByRole('button', { name: 'Escolher coluna por coluna' }))
    // O gatilho escreve a REGRA ("todos · 3 inversores"), que é diferente de uma lista de 3.
    fireEvent.click(screen.getByRole('button', { name: /todos · 3 inversores/ }))

    expect(screen.getByText('Inv 13')).toBeTruthy()
    // O que a pessoa tem na mão é o número de série; a chave é transporte e não aparece.
    expect(screen.getByText(/GR2579042017/)).toBeTruthy()
    expect(container.textContent).not.toContain('slot:')
    expect(container.textContent).not.toContain('inv:')

    // Desmarcar um a partir de "todos" é exatamente "todos menos este": vira lista explícita.
    // (Na lista de múltipla escolha cada linha é uma caixa, não um botão simples.)
    fireEvent.click(screen.getByRole('checkbox', { name: /Inv 13/ }))
    expect(screen.getByRole('button', { name: /2 de 3 inversores/ })).toBeTruthy()

    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await waitFor(() => expect(buscar).toHaveBeenCalledTimes(1))
    const corpo = JSON.parse(String((buscar.mock.calls[0][1] as RequestInit).body))
    expect(corpo.inversores.series).toEqual(['slot:171', 'slot:172'])
  })

  /* ------------------------------------------------------------- a espera */

  it('a espera mostra tempo decorrido e nenhuma porcentagem, e cancelar aborta o pedido', async () => {
    let abortado = false
    const buscar = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolver, rejeitar) => {
          init.signal?.addEventListener('abort', () => {
            abortado = true
            rejeitar(Object.assign(new DOMException('abort', 'AbortError')))
          })
        }),
    )
    vi.stubGlobal('fetch', buscar)
    montar()
    await telaPronta()

    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    const caixa = await screen.findByRole('dialog')
    expect(caixa.textContent).toContain('Gerando há')
    // Nenhuma porcentagem: o servidor monta o arquivo inteiro antes de responder, e não há
    // progresso para mostrar. Inventar um seria ficção.
    expect(caixa.textContent).not.toMatch(/\d+\s?%/)
    expect(caixa.textContent).toContain('Não feche esta aba')

    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(abortado).toBe(true))
    // Cancelar não é erro: ninguém errou, e a tela não acusa nada.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.queryByText(/Não deu para/)).toBeNull()
    expect(vi.mocked(baixarBlob)).not.toHaveBeenCalled()
  })

  /* ------------------------------------------------------------------ 404 */

  it('o 404 não vira diagnóstico sobre a usina: quem escreve a frase é o servidor', async () => {
    // Este caso saiu de uma conferência no navegador, não da imaginação: o BFF que rodava na
    // máquina era um processo antigo, sem a rota nova, e respondeu o "Not Found" padrão do
    // FastAPI. A tela, que afirmava por conta própria "esta usina não está ligada ao
    // monitoramento", disse isso de Porto Ferreira — que está ligada. Um 404 tem três causas
    // (fora do escopo, sem vínculo, rota que não subiu) e a tela não sabe qual é.
    const naoEncontrado = {
      isAxiosError: true,
      response: { status: 404, data: { detail: 'Not Found' } },
    }
    vi.spyOn(api, 'get').mockRejectedValue(naoEncontrado as never)
    const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={cliente}>
        <MemoryRouter initialEntries={[`/usinas/${USINA}/energia/dados`]}>
          <Routes>
            <Route path="/usinas/:id/energia/dados" element={<BaixarDados />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    // `useLeitura` tenta de novo UMA vez antes de desistir (e o atraso é real): sem folga no
    // prazo, o que se lê aqui é o esqueleto, e não a recusa.
    await screen.findByText('Não há dados brutos para baixar nesta usina', {}, { timeout: 5000 })
    expect(screen.getByText('Not Found')).toBeTruthy()
    // A afirmação que a tela NÃO pode fazer sozinha.
    expect(screen.queryByText(/não está ligada ao monitoramento/)).toBeNull()
  })

  /* -------------------------------------------------------------- contrato */

  it('a estimativa conta como o servidor conta, e o nome do arquivo vem do cabeçalho', () => {
    const o = opcoes()
    // Um dia inteiro a cada 15 minutos = 96 baldes; 3 inversores em lista + total = 4 colunas.
    const j = janelaDo('2026-08-01', '2026-08-01', '00:00', '23:59', '15m', false)
    expect(j.dias).toBe(1)
    expect(j.baldes).toBe(96)
    const e = estimativa(montarPacote('geracao', o), o, j)
    expect(e.colunas).toBe(4)
    expect(e.celulas).toBe(96 * 4)
    expect(passaDoOrcamento(e, o.limites)).toBe(false)

    expect(
      nomeDoArquivo('attachment; filename="dados-porto-ferreira-2026-08.xlsx"', 'dados.xlsx'),
    ).toBe('dados-porto-ferreira-2026-08.xlsx')
    expect(nomeDoArquivo(null, 'dados.xlsx')).toBe('dados.xlsx')
  })

  it('os dias oferecidos param onde o acervo do medidor para', () => {
    const dias = diasOferecidos('2026-09-05', { snapshots_desde: '2026-03-06', ssu_desde: '2026-09-01' })
    expect(dias).toHaveLength(5)
    expect(dias[0].valor).toBe('2026-09-05')
    expect(dias[4].valor).toBe('2026-09-01')
    // Antes da retenção fina, o motivo vai colado; depois dela, não há motivo nenhum a dar.
    expect(dias[0].detalhe).toBeUndefined()
    const antigos = diasOferecidos('2026-03-07', { snapshots_desde: '2026-03-06', ssu_desde: '2026-03-05' })
    expect(antigos[antigos.length - 1].detalhe).toContain('só o total por dia')
  })
})
