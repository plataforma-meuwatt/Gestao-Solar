/**
 * O que este teste prende é o ciclo da senha provisória — o único lugar do portal em que a
 * tela decide se a pessoa navega ou não.
 *
 * 1. **Com a marca de pé, a página é só o formulário e a frase.** Se os cartões normais
 *    aparecessem, a pessoa clicaria no menu, seria trazida de volta pelo guarda de rota e não
 *    entenderia por quê.
 * 2. **Recusa do servidor é a frase do servidor, e o bloqueio continua.** "A senha atual não
 *    confere" tem de chegar inteira: uma mensagem genérica manda o cliente ligar para o
 *    suporte errado.
 * 3. **Depois do 204 a marca cai — inclusive quando a releitura do perfil falha.** O 204 é a
 *    prova de que a senha mudou; manter o bloqueio deixaria a pessoa presa numa tela de troca
 *    de senha que já foi trocada.
 * 4. **Sair não deixa rastro.** Token e cache de leitura vão embora juntos: é a mesma pessoa
 *    com duas contas no mesmo computador, e a usina de uma não é assunto da outra.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Conta from '@/features/conta/Pagina'
import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import { useAuth, type Usuario } from '@/store/auth'

const USUARIO: Usuario = {
  id: 7,
  nome: 'Cliente de Teste',
  apelido: 'cliente',
  email: 'cliente@empresa.com.br',
  empresa: 'Empresa Boa',
  tem_meuwatt: true,
  tem_meuplano: true,
  nivel_acesso: 1,
  usinas: 2,
  trocar_senha: false,
}

const USINAS = {
  usinas: [
    { id: 3, nome: 'UFV Porto Ferreira', cidade: 'Porto Ferreira', uf: 'SP' },
    { id: 4, nome: 'UFV Itatiba', cidade: null, uf: null },
  ],
}

/** Erro no formato do axios — é o que `mensagemDeErro` sabe abrir. */
function recusaDoBff(detail: unknown, status = 400) {
  return Object.assign(new Error('Request failed'), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })
}

/**
 * O `api.get` da tela atende dois caminhos: o perfil (a revalidação da abertura) e a lista de
 * usinas. `perfis` é consumido em ordem — assim um teste faz a SEGUNDA leitura do perfil
 * falhar sem mexer na primeira.
 */
function responder(perfis: Array<Usuario | Error>) {
  let i = 0
  return vi.spyOn(api, 'get').mockImplementation(((caminho: string) => {
    if (String(caminho).includes('/auth/eu')) {
      const proximo = perfis[Math.min(i, perfis.length - 1)]
      i += 1
      return proximo instanceof Error ? Promise.reject(proximo) : Promise.resolve({ data: proximo })
    }
    return Promise.resolve({ data: USINAS })
  }) as never)
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/conta']}>
        <Conta />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function preencher(atual: string, nova: string, repetida: string) {
  fireEvent.change(screen.getByLabelText('Senha atual'), { target: { value: atual } })
  fireEvent.change(screen.getByLabelText('Senha nova'), { target: { value: nova } })
  fireEvent.change(screen.getByLabelText('Repita a senha nova'), { target: { value: repetida } })
}

const botaoTrocar = () => screen.getByRole('button', { name: /Trocar senha/ }) as HTMLButtonElement

describe('tela Minha conta', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
    useAuth.setState({ token: 'tok', expiraEm: null, usuario: USUARIO, erro: null, entrando: false })
  })

  afterEach(() => {
    // Sem `globals` no vitest a árvore renderizada não se limpa sozinha, e uma asserção de
    // ausência passaria a falhar por causa da tela do teste anterior.
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('mostra os dados da conta e as usinas concedidas, com cidade e estado', async () => {
    responder([USUARIO])
    montar()

    expect(await screen.findByText('UFV Porto Ferreira')).toBeTruthy()
    expect(screen.getByText('Porto Ferreira, SP')).toBeTruthy()
    // Usina cadastrada sem cidade nem estado não inventa lugar nenhum.
    expect(screen.getByText('—')).toBeTruthy()
    expect(screen.getByText('2 usinas')).toBeTruthy()
    expect(screen.getByText('cliente@empresa.com.br')).toBeTruthy()
  })

  it('sem usina concedida, explica em vez de mostrar uma tabela vazia', async () => {
    let i = 0
    vi.spyOn(api, 'get').mockImplementation(((caminho: string) => {
      i += 1
      return String(caminho).includes('/auth/eu')
        ? Promise.resolve({ data: USUARIO })
        : Promise.resolve({ data: { usinas: [] } })
    }) as never)
    montar()

    expect(await screen.findByText(/ainda não liberou nenhuma usina/i)).toBeTruthy()
    expect(i).toBeGreaterThan(0)
  })

  it('revalida o cadastro ao abrir a tela, em vez de confiar na cópia do login', async () => {
    const get = responder([{ ...USUARIO, empresa: 'Empresa Renomeada' }])
    montar()

    await waitFor(() => expect(screen.getByText('Empresa Renomeada')).toBeTruthy())
    expect(get.mock.calls.some((c) => String(c[0]).includes('/api/v1/auth/eu'))).toBe(true)
  })

  it('com senha provisória, a página é só a frase e o formulário', async () => {
    useAuth.setState({ usuario: { ...USUARIO, trocar_senha: true } })
    responder([{ ...USUARIO, trocar_senha: true }])
    montar()

    expect(screen.getByText(/senha foi criada pelo gestor da conta e é provisória/i)).toBeTruthy()
    expect(screen.getByLabelText('Senha atual')).toBeTruthy()
    // Nada do resto: nem os dados, nem as usinas.
    expect(screen.queryByText('Seus dados')).toBeNull()
    expect(screen.queryByText('Usinas que você enxerga')).toBeNull()
    await waitFor(() => expect(screen.queryByText('UFV Porto Ferreira')).toBeNull())
  })

  it('senha atual errada mostra o motivo do servidor e o bloqueio continua de pé', async () => {
    useAuth.setState({ usuario: { ...USUARIO, trocar_senha: true } })
    responder([{ ...USUARIO, trocar_senha: true }])
    vi.spyOn(api, 'post').mockRejectedValue(recusaDoBff('A senha atual não confere.'))
    montar()

    preencher('errada', 'senha-nova-boa', 'senha-nova-boa')
    fireEvent.click(botaoTrocar())

    expect(await screen.findByText('A senha atual não confere.')).toBeTruthy()
    expect(useAuth.getState().usuario?.trocar_senha).toBe(true)
    expect(screen.queryByText('Usinas que você enxerga')).toBeNull()
  })

  it('204 troca a senha, libera o portal e confirma na tela', async () => {
    useAuth.setState({ usuario: { ...USUARIO, trocar_senha: true } })
    responder([{ ...USUARIO, trocar_senha: true }, { ...USUARIO, trocar_senha: false }])
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 204, data: '' })
    montar()

    preencher('provisoria', 'senha-nova-boa', 'senha-nova-boa')
    fireEvent.click(botaoTrocar())

    expect(await screen.findByText('Senha trocada. Use a senha nova no próximo acesso.')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/api/v1/auth/trocar-senha', {
      senha_atual: 'provisoria',
      senha_nova: 'senha-nova-boa',
    })
    expect(useAuth.getState().usuario?.trocar_senha).toBe(false)
    // Liberado: os cartões normais voltam à tela.
    expect(screen.getByText('Usinas que você enxerga')).toBeTruthy()
  })

  it('se o perfil não puder ser relido depois do 204, a marca cai mesmo assim', async () => {
    useAuth.setState({ usuario: { ...USUARIO, trocar_senha: true } })
    responder([{ ...USUARIO, trocar_senha: true }, new Error('rede fora')])
    vi.spyOn(api, 'post').mockResolvedValue({ status: 204, data: '' })
    montar()

    preencher('provisoria', 'senha-nova-boa', 'senha-nova-boa')
    fireEvent.click(botaoTrocar())

    await waitFor(() => expect(useAuth.getState().usuario?.trocar_senha).toBe(false))
  })

  it('o botão só libera com uma senha nova válida — e diz o que falta', async () => {
    responder([USUARIO])
    montar()

    expect(botaoTrocar().disabled).toBe(true)

    preencher('atual', 'curta', 'curta')
    expect(botaoTrocar().disabled).toBe(true)
    expect(screen.getByText('A senha nova precisa de pelo menos 8 caracteres.')).toBeTruthy()

    preencher('senha-repetida', 'senha-repetida', 'senha-repetida')
    expect(botaoTrocar().disabled).toBe(true)
    expect(screen.getByText('A senha nova precisa ser diferente da atual.')).toBeTruthy()

    preencher('atual', 'senha-nova-boa', 'senha-nova-bob')
    expect(botaoTrocar().disabled).toBe(true)
    expect(screen.getByText('A repetição não confere com a senha nova.')).toBeTruthy()

    preencher('atual', 'senha-nova-boa', 'senha-nova-boa')
    expect(botaoTrocar().disabled).toBe(false)
  })

  it('Sair derruba a sessão e não deixa cache de leitura para a conta seguinte', async () => {
    responder([USUARIO])
    montar()

    await waitFor(() => expect(localStorage.getItem('leitura:u7:plants')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Sair' }))

    expect(useAuth.getState().token).toBeNull()
    expect(Object.keys(localStorage).some((k) => k.startsWith('leitura:'))).toBe(false)
    expect(localStorage.getItem('gs_portal_sessao')).toBeNull()
  })

  it('não mostra de que sistema veio cada informação — o cliente acessa um portal só', async () => {
    responder([USUARIO])
    const { container } = montar()

    await screen.findByText('UFV Porto Ferreira')
    const texto = container.textContent ?? ''
    expect(/meuwatt|meuplano/i.test(texto)).toBe(false)
  })
})
