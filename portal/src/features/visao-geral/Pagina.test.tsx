/**
 * A carteira é a PRIMEIRA tela do portal, e era a mais lenta e a mais fraca de desenho.
 *
 * O que este teste guarda:
 *
 * 1. **Duas ondas.** A chamada única levava 22 s contra os upstreams reais e a tela tem um
 *    esqueleto só: o cliente corporativo olhava quase meio minuto de cinza. Agora a energia
 *    (rápida) desenha a carteira e a manutenção (lenta) preenche depois — duas leituras da
 *    MESMA rota, para que nenhum número mude de origem.
 * 2. **Enquanto a 2ª onda não chega, a célula não escreve "—".** Um traço se lê como "não
 *    há", e o cliente concluiria "nenhuma OS em andamento" antes de o servidor responder.
 * 3. **Oito colunas, não nove.** Medido e esperado moram na mesma célula.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { ResumoOut, UsinaResumo } from '@/features/visao-geral/api'
import VisaoGeral from '@/features/visao-geral/Pagina'

const PORTO: UsinaResumo = {
  id: 7,
  nome: 'Porto Ferreira',
  cidade: 'Descalvado',
  uf: 'SP',
  tom: 'ok',
  situacao: 'Gerando',
  potencia_kw: 300,
  energia_mes_kwh: 128037.3,
  esperado_mes_kwh: 130266.67,
  pct: 98.3,
  paradas_mes: 6,
  tempo_parado_min: 43,
  manutencao: null,
  pendencias_abertas: null,
  aviso: null,
}

const IBITINGA: UsinaResumo = { ...PORTO, id: 9, nome: 'Ibitinga', cidade: 'Itápolis' }

function resposta(parcial: Partial<ResumoOut>): ResumoOut {
  return {
    referencia_mes: '2026-09',
    atualizado_em: '2026-09-04T12:00:00Z',
    potencia_agora_kw: 420,
    energia_mes_kwh: 350900.1,
    esperado_mes_kwh: 376248.19,
    pct_do_esperado: 93.3,
    tom: 'alerta',
    situacao: 'Abaixo do esperado',
    usinas_com_dado: 2,
    usinas: [PORTO, IBITINGA],
    manutencao: null,
    pendencias: null,
    atencao: [],
    aviso: null,
    ...parcial,
  }
}

/** As duas ondas respondem por URL: a de energia na hora, a de manutenção quando mandado. */
function servidor(manutencao?: ResumoOut, atrasarManutencao = false) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: unknown) => {
    const caminho = String(url)
    if (caminho.includes('blocos=manutencao')) {
      if (atrasarManutencao) await new Promise(() => {})
      return { data: manutencao ?? resposta({}) } as never
    }
    return { data: resposta({}) } as never
  })
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<VisaoGeral />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Visão geral', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('pede a energia e a manutenção em ondas separadas', async () => {
    const get = servidor()
    montar()
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThanOrEqual(2))
    const urls = get.mock.calls.map((c) => String(c[0]))
    expect(urls.some((u) => u.includes('blocos=energia'))).toBe(true)
    expect(urls.some((u) => u.includes('blocos=manutencao'))).toBe(true)
  })

  it('desenha a carteira com a energia, sem esperar a manutenção', async () => {
    servidor(undefined, true)
    montar()
    // A tabela já está de pé com a usina e o número de energia, com a 2ª onda pendurada.
    // `findAllByText` porque o nome aparece DUAS vezes de propósito: na linha da tabela e
    // como rótulo da barra no gráfico da carteira.
    expect((await screen.findAllByText('Porto Ferreira')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Ibitinga').length).toBeGreaterThan(0)
  })

  it('enquanto a manutenção não chega, a célula não diz "—"', async () => {
    servidor(undefined, true)
    const { container } = montar()
    await screen.findAllByText('Porto Ferreira')
    // O ponto de "ainda perguntando" existe; "—" ali seria uma afirmação de ausência.
    await waitFor(() =>
      expect(container.querySelectorAll('[aria-label="carregando"]').length).toBeGreaterThan(0),
    )
  })

  it('quando a manutenção chega, os números aparecem', async () => {
    servidor(
      resposta({
        usinas: [
          { ...PORTO, manutencao: { previsto_ate_mes: 12, feitos: 9, dispensados: 1, atrasados: 2, os_em_andamento: 1 }, pendencias_abertas: 3 },
          IBITINGA,
        ],
        manutencao: { os_em_andamento: 1, os_concluidas_mes: 4, atrasados_total: 2 },
        pendencias: { abertas: 3, prazo_vencido: 1, cobradas_abertas: 0 },
      }),
    )
    montar()
    expect(await screen.findByText('Concluídas no mês')).toBeTruthy()
  })

  it('a tabela cabe em oito colunas: medido e esperado na mesma célula', async () => {
    servidor()
    const { container } = montar()
    await screen.findAllByText('Porto Ferreira')
    const cabecalhos = Array.from(container.querySelectorAll('thead th')).map((t) =>
      (t.textContent ?? '').trim(),
    )
    expect(cabecalhos.length).toBeLessThanOrEqual(8)
    expect(cabecalhos).toContain('Energia no mês')
    expect(cabecalhos).not.toContain('Esperado')
  })

  it('usina sem meta diz "sem meta" na célula, e não um número inventado', async () => {
    servidor()
    vi.spyOn(api, 'get').mockImplementation(async (url: unknown) => {
      if (String(url).includes('blocos=manutencao')) return { data: resposta({}) } as never
      return {
        data: resposta({ usinas: [{ ...PORTO, esperado_mes_kwh: null, pct: null }] }),
      } as never
    })
    montar()
    expect(await screen.findByText('sem meta')).toBeTruthy()
  })
})
