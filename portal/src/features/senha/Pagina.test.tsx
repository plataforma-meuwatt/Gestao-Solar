/** O "esqueci a senha" (R12): a página diz o número do WhatsApp que a API devolve (e o e-mail só quando há
 *  remetente); a "nova senha" lê o link do fragmento, confere as duas senhas e o tira do endereço depois de gravar. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { EsqueciASenha, NovaSenha } from '@/features/senha/Pagina'
import { api } from '@/lib/api'

function montar(no: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{no}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('esqueci a senha', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    window.location.hash = ''
  })

  it('diz o número do WhatsApp do GS e só mostra o e-mail com remetente', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { whatsapp: '+55 17 99625-1058', email: false } })
    montar(<EsqueciASenha />)
    await screen.findByText('+55 17 99625-1058')
    expect(screen.queryByLabelText('E-mail da conta')).toBeNull()
  })

  it('a nova senha: confere as duas, grava pelo link e o tira do endereço', async () => {
    window.location.hash = '#t=LINK123'
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: null })
    montar(<NovaSenha />)
    fireEvent.change(screen.getByLabelText('Senha nova (8 caracteres ou mais)'), { target: { value: 'senha-nova-1' } })
    fireEvent.change(screen.getByLabelText('A mesma senha, de novo'), { target: { value: 'outra-coisa-2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gravar a senha nova' }))
    await screen.findByText('As duas senhas não são iguais.')
    expect(post).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('A mesma senha, de novo'), { target: { value: 'senha-nova-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gravar a senha nova' }))
    await screen.findByText(/Senha nova gravada/)
    expect(post).toHaveBeenCalledWith('/api/v1/auth/senha/nova', { token: 'LINK123', senha: 'senha-nova-1' })
    await waitFor(() => expect(window.location.hash).toBe(''))
  })
})
