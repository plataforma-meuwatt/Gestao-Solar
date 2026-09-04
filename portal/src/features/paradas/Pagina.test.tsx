/**
 * O que este teste guarda é a diferença entre duas frases que, desenhadas errado, ficam
 * idênticas na tela — e uma delas mente para o lado bom:
 *
 * 1. **`total = null` (o monitoramento não respondeu) NÃO pode virar "Nenhuma parada no
 *    período".** É o erro mais caro desta tela: o dono leria "mês tranquilo" onde ninguém
 *    conseguiu ler nada.
 * 2. **Parada em aberto não tem fim.** A célula mostra "—"; carimbar uma hora ali a faria
 *    parecer resolvida.
 * 3. **Soma pela metade não vira número.** Quando uma linha vem sem duração, o BFF manda
 *    `null` no total e a tela diz por quê, em vez de somar só o que tem.
 *
 * O horário não é comparado por extenso de propósito: `dataHora` converte para o fuso da
 * máquina, e um teste preso a "08:00" quebraria em qualquer computador fora do Brasil sem
 * que nada estivesse errado.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { ParadasOut } from '@/features/paradas/api'
import Paradas from '@/features/paradas/Pagina'

const ABERTA = {
  id: 1,
  inicio: '2026-09-10T08:00:00-03:00',
  fim: null,
  duracao_min: null,
  perda_kwh: null,
  tipo: 'parada',
  em_aberto: true,
  tom: 'parado',
}

const RESOLVIDA = {
  id: 2,
  inicio: '2026-09-02T09:30:00-03:00',
  fim: '2026-09-02T12:30:00-03:00',
  duracao_min: 180,
  perda_kwh: 13800,
  tipo: 'degradacao',
  em_aberto: false,
  tom: 'ok',
}

function resposta(parcial: Partial<ParadasOut>): ParadasOut {
  return {
    recorte: 'mes',
    inicio: '2026-09-01',
    fim: '2026-09-30',
    total: 0,
    tempo_parado_min: null,
    perda_kwh: null,
    em_aberto: 0,
    paradas: [],
    fonte: 'paradas',
    aviso: null,
    ...parcial,
  }
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/usinas/7/paradas']}>
        <Routes>
          <Route path="/usinas/:id/paradas" element={<Paradas />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('tela de Paradas', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    // Sem `globals` no vitest, a limpeza da árvore renderizada NÃO é automática: sem esta
    // linha o `screen` enxerga a tela do teste anterior junto com a atual, e uma asserção de
    // ausência ("não diz 'nenhuma parada'") passa a falhar por um texto que não é deste caso.
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('pergunta ao BFF as paradas da usina da URL, no mês', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({}) })
    montar()
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(String(get.mock.calls[0][0])).toContain('/api/v1/plants/7/paradas?recorte=mes')
  })

  it('sem parada no período, diz que não houve parada — e em verde', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ total: 0 }) })
    montar()
    // Zero parada é uma BOA notícia, e o cartão diz isso pela COR — não pela mesma cor
    // apagada de "não deu para ler", que é a outra maneira de a lista ficar vazia.
    const titulo = await screen.findByText('Nenhuma parada no período')
    expect(titulo.className).toContain('text-tom-ok')
  })

  it('sem resposta do monitoramento, mostra o aviso do servidor — nunca "nenhuma parada"', async () => {
    const aviso = 'O monitoramento não respondeu as paradas deste período.'
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ total: null, fonte: null, aviso }) })
    montar()
    expect(await screen.findByText(aviso)).toBeTruthy()
    expect(screen.queryByText('Nenhuma parada no período')).toBeNull()
  })

  it('parada em aberto fica sem fim, com o selo do servidor', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({ total: 2, em_aberto: 1, paradas: [ABERTA, RESOLVIDA] }),
    })
    const { container } = montar()

    expect(await screen.findByText('Em aberto')).toBeTruthy()
    expect(screen.getByText('Resolvida')).toBeTruthy()

    const linhas = container.querySelectorAll('tbody tr')
    expect(linhas.length).toBe(2)
    // A ordem é a que o servidor mandou; a primeira linha é a parada ainda aberta.
    const celulas = linhas[0].querySelectorAll('td')
    expect(celulas[1].textContent).toBe('—') // fim
    expect(celulas[2].textContent).toBe('—') // duração desconhecida, não "0 min"
    expect(celulas[4].textContent).toBe('Parada')
    expect(linhas[1].querySelectorAll('td')[4].textContent).toBe('Degradação')
  })

  it('escreve os números em pt-BR e explica a soma que o servidor recusou fazer', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({
        total: 2,
        em_aberto: 1,
        tempo_parado_min: null,
        perda_kwh: null,
        paradas: [ABERTA, RESOLVIDA],
      }),
    })
    montar()

    // 13800 kWh viram "13,8 MWh"; 180 min viram "3 h" — tudo por `lib/format`.
    expect(await screen.findByText('13,8 MWh')).toBeTruthy()
    expect(screen.getByText('3 h')).toBeTruthy()
    expect(screen.getByText('alguma parada veio sem o tempo')).toBeTruthy()
    expect(screen.getByText('alguma parada veio sem o número')).toBeTruthy()
    expect(screen.getByText('Ainda parada')).toBeTruthy()
  })
})
