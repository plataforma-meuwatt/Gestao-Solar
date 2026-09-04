/**
 * A leitura em quatro estados é a regra que mais se perde numa refatoração, porque o caminho
 * feliz continua funcionando. O teste guarda os três casos que doem:
 *
 * 1. **rede caída COM cache** → a tela mostra o dado velho e diz que é velho (`offlineDesde`).
 *    Esconder o cache custaria a única informação que o cliente tem; mostrá-lo sem o selo
 *    faria dado de ontem se ler como dado de agora;
 * 2. **rede caída SEM cache** → erro de verdade, e nada inventado;
 * 3. **401/403** → o cache é APAGADO e o erro sobe. Servir cache numa sessão expirada mostra
 *    a usina de quem já não tem direito a ela, e o pior é que parece funcionando.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { AxiosError, AxiosHeaders } from 'axios'
import { createElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { gravarCache, identificarCache, lerCache, limparCache, useLeitura } from '@/lib/leitura'

type Carteira = { usinas: number }

function erroDeRede(status?: number): AxiosError {
  const config = { headers: new AxiosHeaders() }
  const erro = new AxiosError('falhou', 'ERR', config)
  if (status) {
    erro.response = {
      status,
      statusText: '',
      data: {},
      headers: {},
      config,
    } as AxiosError['response']
  }
  return erro
}

function envolver() {
  // `retry: false` aqui não mascara nada: quem decide a repetição é o próprio `useLeitura`
  // (que já recusa repetir erro de sessão). Desligar no cliente do teste só evita esperar o
  // atraso exponencial do TanStack.
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: cliente }, children)
}

describe('useLeitura', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    limparCache()
  })

  it('mostra o cache e assume que está velho quando a rede falha', async () => {
    gravarCache<Carteira>('resumo', { usinas: 3 })
    vi.spyOn(api, 'get').mockRejectedValue(erroDeRede())

    const { result } = renderHook(() => useLeitura<Carteira>('resumo'), { wrapper: envolver() })

    // O cache é lido de forma síncrona: não há piscar de vazio antes da rede responder.
    expect(result.current.dados).toEqual({ usinas: 3 })
    expect(result.current.carregando).toBe(false)

    // Prazo folgado: erro de rede (≠ sessão) ainda tem uma repetição, com atraso do TanStack.
    await waitFor(() => expect(result.current.offlineDesde).toMatch(/^\d{2}:\d{2}$/), {
      timeout: 4000,
    })
    expect(result.current.dados).toEqual({ usinas: 3 })
    expect(result.current.erro).toBeNull()
  })

  it('sem cache e sem rede, é erro — e não uma tela vazia', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(erroDeRede())

    const { result } = renderHook(() => useLeitura<Carteira>('resumo'), { wrapper: envolver() })

    await waitFor(() => expect(result.current.erro).not.toBeNull(), { timeout: 4000 })
    expect(result.current.dados).toBeNull()
    expect(result.current.offlineDesde).toBeUndefined()
  })

  it('grava o que veio da rede e informa a hora da leitura', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { usinas: 5 } })

    const { result } = renderHook(() => useLeitura<Carteira>('resumo'), { wrapper: envolver() })

    await waitFor(() => expect(result.current.dados).toEqual({ usinas: 5 }))
    expect(result.current.atualizadoEm).toMatch(/^\d{2}:\d{2}$/)
    expect(lerCache<Carteira>('resumo')?.dados).toEqual({ usinas: 5 })
  })

  it('apaga o cache quando a sessão morre (401)', async () => {
    gravarCache<Carteira>('resumo', { usinas: 3 })
    vi.spyOn(api, 'get').mockRejectedValue(erroDeRede(401))

    const { result } = renderHook(() => useLeitura<Carteira>('resumo'), { wrapper: envolver() })

    await waitFor(() => expect(result.current.dados).toBeNull())
    expect(lerCache<Carteira>('resumo')).toBeNull()
    expect(result.current.erro).not.toBeNull()
  })

  it('separa o cache por conta — ler o de outro usuário não é possível', () => {
    gravarCache<Carteira>('resumo', { usinas: 3 })
    identificarCache(99)
    expect(lerCache<Carteira>('resumo')).toBeNull()
    identificarCache(7)
    expect(lerCache<Carteira>('resumo')?.dados).toEqual({ usinas: 3 })
  })

  /**
   * O `status` separa "não é seu / não existe" de "a rede caiu" — duas telas diferentes: a
   * primeira é um vazio com o caminho de volta (insistir nunca vai abrir aquela porta), a
   * segunda é um erro com "Tentar de novo". Sem ele, três telas do portal reconheciam o 404
   * pela FRASE do BFF e ficavam presas à prosa dele.
   */
  it('entrega o status da recusa: 404 é "não existe", e não "a rede caiu"', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(erroDeRede(404))

    const { result } = renderHook(() => useLeitura<Carteira>('ordem-9'), { wrapper: envolver() })

    await waitFor(() => expect(result.current.erro).not.toBeNull(), { timeout: 4000 })
    expect(result.current.status).toBe(404)
  })

  it('rede que nem chegou ao servidor não tem status', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(erroDeRede())

    const { result } = renderHook(() => useLeitura<Carteira>('ordem-9'), { wrapper: envolver() })

    await waitFor(() => expect(result.current.erro).not.toBeNull(), { timeout: 4000 })
    expect(result.current.status).toBeNull()
  })

  it('com cache na tela, o status fica nulo: ali o que vale é a faixa de offline', async () => {
    // Um 404 depois de a tela já estar desenhada não pode transformá-la em "não encontrada"
    // e apagar o que o cliente está lendo.
    gravarCache<Carteira>('resumo', { usinas: 3 })
    vi.spyOn(api, 'get').mockRejectedValue(erroDeRede(404))

    const { result } = renderHook(() => useLeitura<Carteira>('resumo'), { wrapper: envolver() })

    await waitFor(() => expect(result.current.offlineDesde).toBeTruthy(), { timeout: 4000 })
    expect(result.current.dados).toEqual({ usinas: 3 })
    expect(result.current.status).toBeNull()
  })

  it('leitura que deu certo não tem status', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { usinas: 5 } })

    const { result } = renderHook(() => useLeitura<Carteira>('resumo'), { wrapper: envolver() })

    await waitFor(() => expect(result.current.dados).not.toBeNull())
    expect(result.current.status).toBeNull()
  })
})
