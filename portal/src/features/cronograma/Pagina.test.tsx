/**
 * O cronograma é o artefato que o dono nomeou ("ele quer ver o CRONOGRAMA com o X"), e a
 * frase seguinte é o limite: *"e olha lá — ele só quer saber se está sendo feito"*.
 *
 * O que este teste guarda:
 *
 * 1. **Nada de vocabulário de banco.** "INSPECAO", "ensaio" e "6/MONTH" chegavam à tela de
 *    um cliente corporativo brasileiro. A tradução é do servidor; aqui se prova que a tela
 *    mostra o que ele mandou e não remonta o código cru.
 * 2. **94 linhas de ensaio não abrem de uma vez.** Elas nascem recolhidas sob o bloco a que
 *    pertencem, com o total do bloco à mostra — que é a resposta que ele quer.
 * 3. **PDF só quando existe.** Quem decide é o servidor: a rota do JSON responde 200 com a
 *    frase de "ainda não publicado" e a do PDF responde 404, e a tela não pode adivinhar.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { CronogramaOut, LinhaCronograma } from '@/features/cronograma/api'
import Cronograma from '@/features/cronograma/Pagina'

const MESES = ['2026-08', '2026-09', '2026-10', '2026-11', '2026-12', '2027-01',
               '2027-02', '2027-03', '2027-04', '2027-05', '2027-06', '2027-07']

function linha(parcial: Partial<LinhaCronograma>): LinhaCronograma {
  return {
    plan_item_id: 1,
    nome: 'Medição do TTR',
    categoria: 'Ensaio',
    categoria_codigo: 'ensaio',
    periodicidade: 'Semestral',
    grupo: 'Subestação',
    previsto_ano: 2,
    feitos: 1,
    meses: MESES.map((m, i) => ({
      mes: m,
      previsto: i === 0 ? 1 : 0,
      estado: i === 0 ? 'verde' : null,
      feito: i === 0,
      dispensado: false,
      atrasado: false,
    })),
    ...parcial,
  }
}

function cronograma(parcial: Partial<CronogramaOut>): CronogramaOut {
  return {
    usina: 'Porto Ferreira',
    usina_id: 7,
    contrato_id: 665,
    contrato: 'O&M 2026',
    pdf_disponivel: true,
    status: 'CONSOLIDATED',
    versao: 1,
    meses: MESES,
    linhas: [linha({}), linha({ plan_item_id: 2, nome: 'Limpeza do quadro', grupo: 'CFTV' })],
    previsto_ano: 4,
    feitos_ano: 2,
    aviso: null,
    ...parcial,
  }
}

function servidor(dados: CronogramaOut) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: unknown) => {
    if (String(url).includes('/manutencao/contratos')) {
      return {
        data: {
          usina: 'Porto Ferreira',
          usina_id: 7,
          contratos: [
            { id: 665, numero: 665, titulo: 'O&M 2026', inicio: '2026-08-01',
              fim: '2027-07-31', vigente: true, versao_cronograma: 1 },
          ],
          aviso: null,
        },
      } as never
    }
    return { data: dados } as never
  })
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/usinas/7/cronograma']}>
        <Routes>
          <Route path="/usinas/:id/cronograma" element={<Cronograma />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('tela de Cronograma', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('agrupa as atividades por bloco e as mostra recolhidas', async () => {
    servidor(cronograma({}))
    montar()
    // Os blocos aparecem; as atividades de dentro, não — é a diferença entre responder
    // "está sendo feito?" e despejar a matriz técnica do plano na cara do cliente.
    expect(await screen.findByText('Subestação')).toBeTruthy()
    expect(screen.getByText('CFTV')).toBeTruthy()
    expect(screen.queryByText('Medição do TTR')).toBeNull()
  })

  it('abrir o bloco mostra as atividades dele', async () => {
    servidor(cronograma({}))
    montar()
    const bloco = await screen.findByText('Subestação')
    bloco.click()
    await waitFor(() => expect(screen.getByText('Medição do TTR')).toBeTruthy())
    // O bloco vizinho continua recolhido: abrir um não abre todos.
    expect(screen.queryByText('Limpeza do quadro')).toBeNull()
  })

  it('um bloco só não vira acordeão: a lista abre inteira', async () => {
    servidor(cronograma({ linhas: [linha({})] }))
    montar()
    expect(await screen.findByText('Medição do TTR')).toBeTruthy()
  })

  it('mostra o selo e a periodicidade que o servidor traduziu, nunca o código cru', async () => {
    servidor(cronograma({ linhas: [linha({})] }))
    montar()
    const rodape = await screen.findByText(/Ensaio/)
    expect(rodape.textContent).toContain('Semestral')
    expect(rodape.textContent).not.toContain('MONTH')
    expect(rodape.textContent).not.toContain('INSPECAO')
  })

  it('sem PDF disponível o botão não aparece — botão que só erra é ruído', async () => {
    servidor(cronograma({ pdf_disponivel: false }))
    montar()
    await screen.findByText('Subestação')
    expect(screen.queryByText('PDF')).toBeNull()
  })

  it('com PDF disponível o botão aparece', async () => {
    servidor(cronograma({}))
    montar()
    expect(await screen.findByText('PDF')).toBeTruthy()
  })
})
