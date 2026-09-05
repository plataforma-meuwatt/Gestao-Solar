/**
 * As rotas do portal, e sobretudo o que acontece com os endereços ANTIGOS.
 *
 * A separação entre Geração de energia e Manutenção mudou o endereço de cinco telas. O que
 * este teste guarda é o que o cliente já tem guardado: o favorito do cronograma, o link da
 * ordem de serviço colado num e-mail, a rota que o próprio BFF manda nas faixas de atenção da
 * Visão geral (`atencao[].rota`, que o portal não controla). Todos continuam funcionando — e
 * o `replace` impede que o botão Voltar caia no endereço velho e redirecione de novo, o que
 * prenderia quem tenta voltar.
 *
 * O caminho novo é montado à mão nesses redirecionamentos, e não com `..` relativo: em rotas
 * irmãs sob um layout sem caminho próprio, o `..` do react-router sobe até a RAIZ e mandaria
 * o cliente para a Visão geral. É um erro que compila, roda e só aparece na tela.
 *
 * A rede fica fora do ar de propósito: aqui o que se afere é o roteador, não a leitura. Cada
 * tela tem o teste dela.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'

import { App } from '@/App'
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
  usinas: 3,
  trocar_senha: false,
}

function abrir(endereco: string) {
  window.history.replaceState({}, '', endereco)
  return render(<App />)
}

describe('rotas do portal', () => {
  beforeEach(() => {
    localStorage.clear()
    // Prazo longe: `renovar()` não fala com o servidor, e a sessão não cai no meio do teste.
    useAuth.setState({
      token: 'token-de-teste',
      expiraEm: '2099-01-01T00:00:00.000Z',
      usuario,
      erro: null,
      entrando: false,
    })
    vi.spyOn(api, 'get').mockRejectedValue(new Error('sem rede neste teste'))
    vi.spyOn(api, 'post').mockRejectedValue(new Error('sem rede neste teste'))
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    window.history.replaceState({}, '', '/')
  })

  it('a raiz da usina é o Painel', async () => {
    abrir('/usinas/3')
    await waitFor(() => expect(window.location.pathname).toBe('/usinas/3/energia'))
  })

  it('os endereços antigos levam ao lugar novo, com o assunto no meio', async () => {
    const casos: [string, string][] = [
      ['/usinas/3/paradas', '/usinas/3/energia/paradas'],
      ['/usinas/3/cronograma', '/usinas/3/manutencao/cronograma'],
      ['/usinas/3/ordens', '/usinas/3/manutencao/ordens'],
      ['/usinas/3/ordens/12', '/usinas/3/manutencao/ordens/12'],
      ['/usinas/3/pendencias', '/usinas/3/manutencao/pendencias'],
      ['/usinas/3/pendencias/44', '/usinas/3/manutencao/pendencias/44'],
    ]
    for (const [antigo, novo] of casos) {
      abrir(antigo)
      await waitFor(() => expect(window.location.pathname).toBe(novo))
      cleanup()
    }
  })

  it('o que vinha depois do endereço não se perde no caminho', async () => {
    abrir('/usinas/3/relatorios?contrato=8')
    await waitFor(() => expect(window.location.pathname).toBe('/usinas/3/relatorios'))
    expect(window.location.search).toBe('?contrato=8')

    cleanup()
    abrir('/usinas/3/pendencias/44?aba=documentos')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/usinas/3/manutencao/pendencias/44'),
    )
    expect(window.location.search).toBe('?aba=documentos')
  })

  it('os endereços novos ficam onde estão', async () => {
    const proprios = [
      '/usinas/3/energia',
      '/usinas/3/energia/paradas',
      '/usinas/3/manutencao/cronograma',
      '/usinas/3/manutencao/ordens/12/tarefas/99',
      '/usinas/3/relatorios',
    ]
    for (const endereco of proprios) {
      abrir(endereco)
      // Sem espera: um redirecionamento indevido acontece já na primeira renderização.
      await waitFor(() => expect(window.location.pathname).toBe(endereco))
      cleanup()
    }
  })

  it('endereço desconhecido vai para a carteira, e não para uma tela em branco', async () => {
    abrir('/usinas/3/inventado')
    await waitFor(() => expect(window.location.pathname).toBe('/'))
  })

  it('as duas famílias aparecem no menu, com nome — inclusive no trilho de ícones', async () => {
    const { findAllByText } = abrir('/usinas/3/energia')
    // Duas vezes cada: a barra larga escreve o nome, e o trilho estreito o carrega escondido
    // ao lado do ícone-cabeçalho (leitor de tela e `title`) — ícone anônimo é adivinhação.
    expect((await findAllByText('Geração de energia')).length).toBeGreaterThan(1)
    expect((await findAllByText('Manutenção')).length).toBeGreaterThan(1)
  })

  it('a seção acesa é a da tela, e não a do prefixo', async () => {
    const rasa = abrir('/usinas/3/energia/paradas')
    // Sem casamento exato, "Painel" (`/energia`) ficaria aceso junto com "Paradas".
    for (const item of await rasa.findAllByLabelText('Paradas')) {
      expect(item.getAttribute('aria-current')).toBe('page')
    }
    for (const item of await rasa.findAllByLabelText('Painel')) {
      expect(item.getAttribute('aria-current')).toBeNull()
    }
    cleanup()

    // E a seção continua acesa nas telas mais fundas dela.
    const funda = abrir('/usinas/3/manutencao/ordens/12/tarefas/99')
    for (const item of await funda.findAllByLabelText('Ordens de serviço')) {
      expect(item.getAttribute('aria-current')).toBe('page')
    }
  })

  it('sem sessão, qualquer endereço cai na entrada', async () => {
    useAuth.setState({ token: null, usuario: null, expiraEm: null })
    abrir('/usinas/3/manutencao/ordens/12')
    await waitFor(() => expect(window.location.pathname).toBe('/entrar'))
  })
})
