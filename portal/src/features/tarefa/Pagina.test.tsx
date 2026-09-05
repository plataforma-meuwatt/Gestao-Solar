/**
 * O que este teste guarda é a leitura da ficha — e, principalmente, a FOTO, que é a
 * evidência do que o técnico viu e o pedido do dono ("quero abrir as tarefas e ver as
 * fotos").
 *
 * 1. **Cada evidência aparece uma vez só.** `equipamento.fotos` já soma sessão e respostas.
 *    Desenhar as duas listas sem deduplicar mostra a mesma foto duas vezes; não percorrer as
 *    perguntas mostra zero — foi o defeito real, com 61 fotos guardadas nas respostas.
 * 2. **`fotos` como NÚMERO não derruba a tela.** Durante o deploy do BFF a forma antiga (a
 *    contagem) e a nova (a lista) convivem, e o cache guarda a antiga em disco.
 * 3. **Um download por imagem.** Duas miniaturas do mesmo id dividem o mesmo pedido; sem
 *    isso, 61 miniaturas formam a fila que o servidor não vence e TODAS falham.
 * 4. **O `blob:` é revogado ao desmontar** — senão a ficha inteira fica presa na memória.
 * 5. **Falha de imagem se explica** e aceita nova tentativa: um quadrado vazio não diz se a
 *    sessão venceu, se a foto sumiu ou se a rede caiu.
 * 6. **`situacao` não é veredito.** "Não feito" é estado e vem na frente do valor; virar
 *    "reprovado" mudaria o que o laudo afirma.
 * 7. **A ficha pode falhar sem matar a tela** — o cabeçalho e o PDF continuam de pé.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import { Fotos } from '@/features/tarefa/Fotos'
import { esquecerImagensEmVoo } from '@/features/tarefa/imagem'
import Pagina from '@/features/tarefa/Pagina'
import type {
  EquipamentoDaFicha,
  Ficha,
  Foto,
  LinhaMedicao,
  Tarefa,
} from '@/features/tarefa/api'

/* ------------------------------------------------------------------ fixtures */

function tarefa(parcial: Partial<Tarefa> = {}): Tarefa {
  return {
    id: 6710,
    nome: 'O&M-Inversor-Mensal — 08/2026',
    grupo: 'Inversor',
    equipamento: 'UFV Porto Ferreira / Skid 01 / INV-01',
    status: 'APROVADA',
    situacao: 'Executada e verificada',
    feita: true,
    natureza: 'INSPECAO',
    parecer: 'Aprovado',
    parecer_tom: 'ok',
    os_id: 1016,
    mes_contratual: '2026-08',
    executada_em: '2026-08-12',
    descricao: null,
    observacoes: null,
    preenchimento: 100,
    ...parcial,
  }
}

function foto(id: number, legenda: string | null = null): Foto {
  return {
    id,
    legenda,
    url: `/api/v1/manutencao/ordens/1016/tarefas/6710/fotos/${id}`,
    thumb_url: `/api/v1/manutencao/ordens/1016/tarefas/6710/fotos/${id}?variante=thumb`,
  }
}

function equipamento(parcial: Partial<EquipamentoDaFicha> = {}): EquipamentoDaFicha {
  return {
    equipamento: 'INV-01',
    modelo: 'SUN2000',
    fabricante: 'Huawei',
    numero_serie: 'ABC123',
    executado_em: '12/08/2026 14:30',
    executado_por: 'Fulano de Tal',
    parecer: null,
    parecer_motivo: null,
    medicoes: [],
    checklist: [],
    fotos: [],
    ...parcial,
  }
}

function ficha(parcial: Partial<Ficha> = {}): Ficha {
  return {
    id: 6710,
    nome: 'O&M-Inversor-Mensal',
    coletiva: false,
    parecer: 'Aprovado',
    equipamentos: [equipamento()],
    fotos: 0,
    ...parcial,
  }
}

function linha(parcial: Partial<LinhaMedicao> = {}): LinhaMedicao {
  return {
    ponto: 'Fase R',
    valor: null,
    unidade: null,
    alvo: null,
    desvio: null,
    aprovado: null,
    situacao: null,
    observacao: null,
    ...parcial,
  }
}

/** Um erro do axios como o interceptor o entrega — é dele que sai a frase do servidor. */
function erroDoServidor(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })
}

/* ------------------------------------------------------------------ andaimes */

function responder(cabecalho: Tarefa | Error, respostas: Ficha | Error) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: unknown) => {
    const alvo = String(url).endsWith('/ficha') ? respostas : cabecalho
    if (alvo instanceof Error) throw alvo
    return { data: alvo } as never
  })
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/usinas/4/manutencao/ordens/1016/tarefas/6710']}>
        <Routes>
          <Route
            path="/usinas/:id/manutencao/ordens/:osId/tarefas/:taskId"
            element={<Pagina />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Uma imagem plausível: `baixarComSessao` recusa corpo curto (página de erro com 200). */
const BYTES = new Blob([new Uint8Array(2048)], { type: 'image/jpeg' })

let criados: string[] = []
let revogados: string[] = []
let pedidos: string[] = []

/** O `fetch` que serve as imagens — é por ele que a sessão vai em cabeçalho. */
function servindoImagens(resposta: 'ok' | { status: number; detail: string } = 'ok') {
  const espiao = vi.fn(async (url: unknown) => {
    pedidos.push(String(url))
    if (resposta === 'ok') {
      return { ok: true, status: 200, blob: async () => BYTES } as never
    }
    return {
      ok: false,
      status: resposta.status,
      json: async () => ({ detail: resposta.detail }),
    } as never
  })
  vi.stubGlobal('fetch', espiao)
  return espiao
}

describe('a ficha de uma tarefa', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(4)
    esquecerImagensEmVoo()
    criados = []
    revogados = []
    pedidos = []
    let n = 0
    URL.createObjectURL = vi.fn(() => {
      n += 1
      const url = `blob:foto-${n}`
      criados.push(url)
      return url
    })
    URL.revokeObjectURL = vi.fn((url: string) => {
      revogados.push(url)
    })
  })

  afterEach(() => {
    // Sem `globals` no vitest a árvore não se limpa sozinha, e uma asserção de AUSÊNCIA
    // passaria a falhar por um texto que é do caso anterior.
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    limparCache()
  })

  it('lê o cabeçalho e a ficha em chamadas separadas', async () => {
    const get = responder(tarefa(), ficha())
    montar()

    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(1))
    const caminhos = get.mock.calls.map((c) => String(c[0]))
    expect(caminhos).toContain('/api/v1/manutencao/ordens/1016/tarefas/6710')
    expect(caminhos).toContain('/api/v1/manutencao/ordens/1016/tarefas/6710/ficha')
  })

  it('a foto da resposta fica na pergunta e NÃO se repete no rodapé do equipamento', async () => {
    servindoImagens()
    const daResposta = foto(37, 'Conector aquecido')
    const daSessao = foto(99, 'Vista geral do skid')
    responder(
      tarefa(),
      ficha({
        equipamentos: [
          equipamento({
            // Como o servidor entrega: `fotos` do equipamento já SOMA sessão + respostas.
            fotos: [daResposta, daSessao],
            checklist: [
              {
                nome: 'Inspeção visual',
                perguntas: [
                  {
                    pergunta: 'Existem sinais de aquecimento?',
                    resposta: 'Sim',
                    problema: true,
                    observacao: null,
                    fotos: [daResposta],
                  },
                ],
              },
            ],
          }),
        ],
      }),
    )
    montar()

    expect(await screen.findByText('Existem sinais de aquecimento?')).toBeTruthy()
    // Duas miniaturas no total: a da resposta (na pergunta) e a da sessão (no rodapé) —
    // nunca três, que é o que sai quando o rodapé repete a foto da pergunta.
    await waitFor(() => expect(document.querySelectorAll('img').length).toBe(2))
    const pedidas = pedidos.filter((p) => p.includes('variante=thumb'))
    expect(pedidas.some((p) => p.includes('/fotos/37'))).toBe(true)
    expect(pedidas.filter((p) => p.includes('/fotos/37')).length).toBe(1)
    expect(pedidas.filter((p) => p.includes('/fotos/99')).length).toBe(1)
  })

  it('"fotos" chegando como número (servidor antigo) não quebra a tela', async () => {
    servindoImagens()
    responder(
      tarefa(),
      ficha({
        equipamentos: [
          // A forma ANTIGA do contrato: `fotos` era a contagem. O `.map` de um número
          // derrubaria a ficha inteira, e o cache faria a tela quebrada durar mais que o deploy.
          { ...equipamento({ equipamento: 'INV-02' }), fotos: 12 } as unknown as EquipamentoDaFicha,
        ],
      }),
    )
    montar()

    expect(await screen.findByText('INV-02')).toBeTruthy()
    expect(document.querySelectorAll('img').length).toBe(0)
  })

  it('duas miniaturas do mesmo id disparam um download só', async () => {
    const espiao = servindoImagens()
    const mesma = foto(37)
    render(
      <>
        <Fotos fotos={[mesma]} />
        <Fotos fotos={[mesma]} />
      </>,
    )

    await waitFor(() => expect(document.querySelectorAll('img').length).toBe(2))
    expect(espiao.mock.calls.length).toBe(1)
  })

  it('revoga o endereço da imagem ao desmontar', async () => {
    servindoImagens()
    const { unmount } = render(<Fotos fotos={[foto(37)]} />)

    await waitFor(() => expect(document.querySelectorAll('img').length).toBe(1))
    expect(criados.length).toBe(1)

    unmount()
    expect(revogados).toEqual(criados)
  })

  it('miniatura que falha mostra o MOTIVO do servidor e refaz o pedido ao clicar', async () => {
    const espiao = servindoImagens({ status: 404, detail: 'Foto não encontrada nesta tarefa.' })
    render(<Fotos fotos={[foto(37)]} />)

    const quadro = await screen.findByText('Foto não encontrada nesta tarefa.')
    expect(espiao.mock.calls.length).toBe(1)
    expect(document.querySelectorAll('img').length).toBe(0)

    fireEvent.click(quadro)
    await waitFor(() => expect(espiao.mock.calls.length).toBe(2))
  })

  it('mostra só as seis primeiras, com "ver todas" para o resto', async () => {
    servindoImagens()
    const muitas = Array.from({ length: 9 }, (_, i) => foto(i + 1))
    render(<Fotos fotos={muitas} titulo="Fotos" />)

    // Sessenta e uma miniaturas ao mesmo tempo formam a fila que o servidor não vence.
    await waitFor(() => expect(document.querySelectorAll('img').length).toBe(6))
    expect(screen.getByText('+3')).toBeTruthy()

    fireEvent.click(screen.getByText('ver todas'))
    await waitFor(() => expect(document.querySelectorAll('img').length).toBe(9))
  })

  it('"Não feito" é estado, vem na frente do valor e NÃO vira reprovado', async () => {
    responder(
      tarefa(),
      ficha({
        equipamentos: [
          equipamento({
            medicoes: [
              {
                nome: 'Torqueamento',
                unidade: null,
                linhas: [linha({ ponto: '—', valor: '1', situacao: 'Não feito', aprovado: null })],
              },
            ],
          }),
        ],
      }),
    )
    montar()

    const estado = await screen.findByText('Não feito')
    // Rótulo de estado não é julgamento: sem `aprovado`, não há cor de veredito.
    expect(estado.className).not.toContain('text-tom-parado')
    expect(estado.className).not.toContain('text-tom-ok')
    expect(screen.queryByText('reprovado')).toBeNull()
    // O valor bruto não aparece quando há rótulo: o "1" não diz nada num item de serviço.
    expect(screen.queryByText('1')).toBeNull()
  })

  it('ponto reprovado sem rótulo diz "reprovado"; o valor ausente vira travessão', async () => {
    responder(
      tarefa(),
      ficha({
        equipamentos: [
          equipamento({
            medicoes: [
              {
                nome: 'Resistência de isolamento',
                unidade: 'MΩ',
                linhas: [
                  linha({ ponto: 'Fase R', valor: '0,8', unidade: 'MΩ', aprovado: false }),
                  linha({ ponto: 'Fase S', valor: null, aprovado: null }),
                ],
              },
            ],
          }),
        ],
      }),
    )
    montar()

    expect(await screen.findByText('reprovado')).toBeTruthy()
    expect(screen.getByText('0,8 MΩ')).toBeTruthy()
    expect(screen.getByText('—')).toBeTruthy()
  })

  it('ficha que falha não mata a tela: o cabeçalho e o PDF continuam de pé', async () => {
    responder(tarefa(), erroDoServidor(502, 'Não deu para ler a ficha desta tarefa.'))
    montar()

    expect(await screen.findByText('O&M-Inversor-Mensal — 08/2026')).toBeTruthy()
    expect(
      await screen.findByText(/Não deu para carregar as respostas agora/, {}, { timeout: 5000 }),
    ).toBeTruthy()
    expect(screen.getByText('Abrir a ficha em PDF')).toBeTruthy()
  })

  it('tarefa de outra ordem (404) vira estado vazio com o caminho de volta', async () => {
    responder(
      erroDoServidor(404, 'Tarefa não encontrada nesta ordem de serviço.'),
      erroDoServidor(404, 'Tarefa não encontrada nesta ordem de serviço.'),
    )
    montar()

    expect(await screen.findByText('Tarefa não encontrada', {}, { timeout: 5000 })).toBeTruthy()
    const volta = screen.getByText('Ver a ordem de serviço') as HTMLAnchorElement
    expect(volta.getAttribute('href')).toBe('/usinas/4/manutencao/ordens/1016')
    // "Tentar de novo" é para rede caída; aqui insistir não abriria nada.
    expect(screen.queryByText('Tentar de novo')).toBeNull()
  })

  it('o PDF sai por botão — nunca por link com o endereço da API', async () => {
    responder(tarefa(), ficha())
    const { container } = montar()

    expect(await screen.findByText('Abrir a ficha em PDF')).toBeTruthy()
    const comApi = [...container.querySelectorAll('a')].filter((a) =>
      (a.getAttribute('href') ?? '').includes('/api/'),
    )
    expect(comApi.length).toBe(0)
  })
})
