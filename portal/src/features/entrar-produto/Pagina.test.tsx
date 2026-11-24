/** A janelinha do "Entrar com o GS" (24/11/2026): o passe vai só à origem da `volta` e a janela fecha; sem a página
 *  que abriu, navega como sempre. */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { seguir } from './Pagina'

const URL_COM_PASSE = 'https://app.meuplano.solar/os/1#assercao=abc.def.ghi'

function abertaPor(quem: unknown) {
  Object.defineProperty(window, 'opener', { value: quem, configurable: true, writable: true })
}

describe('seguir', () => {
  afterEach(() => {
    abertaPor(null)
    vi.restoreAllMocks()
  })

  it('na janelinha, entrega o passe só à origem da volta e fecha', () => {
    const postMessage = vi.fn()
    abertaPor({ postMessage })
    const fechar = vi.spyOn(window, 'close').mockImplementation(() => {})
    const ir = vi.fn()
    seguir(URL_COM_PASSE, 'meuplano', true, ir)
    expect(postMessage).toHaveBeenCalledWith(
      { tipo: 'gs-passe', produto: 'meuplano', assercao: 'abc.def.ghi' },
      'https://app.meuplano.solar',
    )
    expect(fechar).toHaveBeenCalled()
    expect(ir).not.toHaveBeenCalled()
  })

  it('sem a página que abriu, navega para a volta', () => {
    abertaPor(null)
    const ir = vi.fn()
    seguir(URL_COM_PASSE, 'meuplano', true, ir)
    expect(ir).toHaveBeenCalledWith(URL_COM_PASSE)
  })

  it('fora da janelinha, navega mesmo com quem abriu', () => {
    const postMessage = vi.fn()
    abertaPor({ postMessage })
    const ir = vi.fn()
    seguir(URL_COM_PASSE, 'meuplano', false, ir)
    expect(postMessage).not.toHaveBeenCalled()
    expect(ir).toHaveBeenCalledWith(URL_COM_PASSE)
  })
})

// ── a volta conferida ao abrir (24/11/2026): só o 400 do servidor esconde o formulário ──────────────────────────────
import { render, screen, waitFor } from '@testing-library/react'
import { AxiosError, type AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import EntrarNoProduto from './Pagina'

const leitura = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof import('@/lib/api')>()),
  api: { get: leitura.get, post: vi.fn() },
}))

function abrir(volta: string) {
  render(
    <MemoryRouter initialEntries={[`/entrar/meuplano?janela=1&volta=${encodeURIComponent(volta)}`]}>
      <Routes>
        <Route path="/entrar/:produto" element={<EntrarNoProduto />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('a volta conferida ao abrir', () => {
  afterEach(() => leitura.get.mockReset())

  it('volta de outro endereço: só o erro, sem o formulário de senha', async () => {
    leitura.get.mockRejectedValueOnce(
      new AxiosError('x', 'ERR_BAD_REQUEST', undefined, undefined, {
        status: 400,
        data: { detail: 'Esse endereço de volta não é do meuPlano.' },
      } as AxiosResponse),
    )
    abrir('https://evil.example.com/x')
    expect(await screen.findByText('Esse endereço de volta não é do meuPlano.')).toBeTruthy()
    expect(document.getElementById('senha')).toBeNull()
  })

  it('a rede que falhou não tranca ninguém: o formulário fica', async () => {
    leitura.get.mockRejectedValueOnce(new AxiosError('Network Error', 'ERR_NETWORK'))
    abrir('https://app.meuplano.solar/login')
    await waitFor(() => expect(leitura.get).toHaveBeenCalledWith('/api/sessao/meuplano/volta', expect.anything()))
    expect(document.getElementById('senha')).not.toBeNull()
  })
})
