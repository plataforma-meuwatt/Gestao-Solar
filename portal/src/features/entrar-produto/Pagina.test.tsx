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
