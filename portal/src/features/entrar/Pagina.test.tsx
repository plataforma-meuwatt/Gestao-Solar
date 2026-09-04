/**
 * O que este teste guarda é o caminho de entrada inteiro — a única porta do portal.
 *
 * Três coisas que já quebraram em produtos parecidos e que aqui ficam presas:
 *
 * 1. **O motivo da recusa é o do servidor.** Uma frase genérica escrita na tela esconderia
 *    "conta desativada" atrás de "senha inválida", e o cliente ligaria para o suporte errado.
 * 2. **Depois de entrar, vai-se para onde se queria ir** (`state.de`). Sem isso, um link
 *    favoritado da pendência sempre cairia na Visão geral, e a pessoa teria de procurar de
 *    novo o que já tinha achado.
 * 3. **Sessão viva não fica presa na tela de entrada.** É o caso do token de OUTRO produto
 *    guardado no navegador: a tela segue adiante, o BFF recusa a leitura com 401 e o store
 *    derruba a sessão — uma volta, nunca um laço.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

import Entrar from '@/features/entrar/Pagina'
import { api } from '@/lib/api'
import { useAuth, type Usuario } from '@/store/auth'

const usuario: Usuario = {
  id: 7,
  nome: 'Cliente de Teste',
  apelido: 'cliente',
  email: null,
  empresa: 'Usina Boa',
  tem_meuwatt: true,
  tem_meuplano: true,
  nivel_acesso: 1,
  usinas: 2,
  trocar_senha: false,
}

/** Erro no formato do axios — é o que `mensagemDeErro` sabe abrir. */
function recusaDoBff(detail: unknown, status = 401) {
  return Object.assign(new Error('Request failed'), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })
}

/** Onde o roteador parou, para o teste ler. */
function Sonda() {
  const local = useLocation()
  return <div data-testid="onde">{local.pathname}</div>
}

function montar(de?: string) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/entrar', state: de ? { de } : undefined }]}>
      <Routes>
        <Route path="/entrar" element={<Entrar />} />
        <Route path="*" element={<Sonda />} />
      </Routes>
    </MemoryRouter>,
  )
}

function preencher(apelido: string, senha: string) {
  fireEvent.change(screen.getByLabelText('Apelido'), { target: { value: apelido } })
  fireEvent.change(screen.getByLabelText('Senha'), { target: { value: senha } })
}

describe('tela de entrada do portal', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuth.setState({ token: null, expiraEm: null, usuario: null, erro: null, entrando: false })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('entra pela porta do cliente e vai para o endereço que a pessoa tentou abrir', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'tok', usuario } })
    montar('/usinas/3/cronograma')

    preencher('cliente', 'senha-certa')
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }))

    await waitFor(() => expect(screen.getByTestId('onde').textContent).toBe('/usinas/3/cronograma'))
    expect(post).toHaveBeenCalledWith('/api/v1/auth/login', {
      apelido: 'cliente',
      senha: 'senha-certa',
    })
  })

  it('sem destino guardado, entra na Visão geral', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'tok', usuario } })
    montar()

    preencher('cliente', 'senha-certa')
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }))

    await waitFor(() => expect(screen.getByTestId('onde').textContent).toBe('/'))
  })

  it('senha errada mostra o motivo que o servidor escreveu, e não sai da tela', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(recusaDoBff('Apelido ou senha inválidos.'))
    montar('/usinas/3/cronograma')

    preencher('cliente', 'errada')
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }))

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Apelido ou senha inválidos.'))
    expect(screen.queryByTestId('onde')).toBeNull()
    // O apelido continua digitado: refazê-lo por causa da senha é o atrito que faz desistir.
    expect((screen.getByLabelText('Apelido') as HTMLInputElement).value).toBe('cliente')
  })

  it('recusa de validação (422, lista) também vira frase — nunca um objeto na tela', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(
      recusaDoBff([{ loc: ['body', 'senha'], msg: 'Field required' }], 422),
    )
    montar()

    preencher('cliente', 'x')
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }))

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('senha: Field required'))
  })

  it('com sessão viva não fica presa na entrada (o token de outro produto sai pelo 401)', () => {
    useAuth.setState({ token: 'tok-de-outro-produto', expiraEm: null, usuario })
    montar('/usinas/3/pendencias')

    expect(screen.getByTestId('onde').textContent).toBe('/usinas/3/pendencias')
  })

  it('o botão só libera com apelido e senha preenchidos', () => {
    montar()
    const botao = screen.getByRole('button', { name: 'Entrar' }) as HTMLButtonElement

    expect(botao.disabled).toBe(true)
    preencher('cliente', '')
    expect(botao.disabled).toBe(true)
    preencher('cliente', 'senha')
    expect(botao.disabled).toBe(false)
  })

  it('o apelido é sempre minúsculo enquanto se digita', () => {
    montar()
    const campo = screen.getByLabelText('Apelido') as HTMLInputElement

    fireEvent.change(campo, { target: { value: 'Renan.Marquezini' } })

    expect(campo.value).toBe('renan.marquezini')
  })

  it('diz como recuperar o acesso e não oferece caminho para o painel do gestor', () => {
    const { container } = montar()

    expect(screen.getByText(/senha provisória ao seu gestor de conta/i)).toBeTruthy()
    // Nenhum link: a recuperação é por telefone com o gestor, não por uma porta do outro site.
    expect(container.querySelectorAll('a').length).toBe(0)
  })
})
