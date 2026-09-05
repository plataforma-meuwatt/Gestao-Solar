/**
 * O que este teste guarda são as leituras que, desenhadas errado, acusam a equipe de campo de
 * algo que ela não fez:
 *
 * 1. **`itens = null` (a busca das tarefas falhou) NÃO pode virar "esta ordem não tem
 *    tarefas".** É o erro mais caro desta tela: uma falha de rede passaria a dizer, na frente
 *    do diretor, que o serviço foi cobrado sem nada executado.
 * 2. **Parecer tem três cores.** Reprovado é vermelho, ressalva é âmbar, aprovado é verde;
 *    fundir ressalva com reprovação (ou com aprovação) muda o que o laudo afirma.
 * 3. **404 é "não é sua", não é falha.** O BFF responde 404 e não 403 de propósito, e a tela
 *    tem de oferecer o caminho de volta em vez de "Tentar de novo" numa porta que não abre.
 * 4. **Duração ausente é "—", nunca zero** — e o PDF sai por botão, nunca por link com o
 *    endereço da API (token em URL entra em log).
 * 5. **A tarefa ABRE, e o botão do PDF não navega.** A linha virou link para a ficha; se o
 *    clique no botão passasse pelo link, quem quisesse o arquivo trocaria de tela. Tarefa sem
 *    `id` continua sem link e sem botão — destino inexistente não pode parecer clicável.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// O download real abre aba e fala com a rede; aqui só interessa QUE ele foi chamado, com que
// caminho, e que a tela não navegou junto.
const abrirPdfFalso = vi.hoisted(() =>
  vi.fn(async (_caminho: string, _nome: string, _opcoes?: { prazoMs?: number }) => {}),
)
vi.mock('@/lib/arquivo', () => ({ abrirPdf: abrirPdfFalso }))

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { Ordem, Tarefa } from '@/features/ordem/api'
import Pagina from '@/features/ordem/Pagina'

function tarefa(parcial: Partial<Tarefa>): Tarefa {
  return {
    id: 1,
    nome: 'Termografia',
    grupo: 'Transformador',
    equipamento: 'UFV / Subestação / TR-01',
    status: 'APROVADA',
    situacao: 'Executada e verificada',
    feita: true,
    natureza: 'INSPECAO',
    parecer: null,
    parecer_tom: null,
    os_id: 55,
    mes_contratual: '2026-08',
    executada_em: '2026-08-12',
    descricao: null,
    observacoes: null,
    preenchimento: 100,
    ...parcial,
  }
}

function resposta(parcial: Partial<Ordem>): Ordem {
  return {
    id: 55,
    usina: 'UFV Porto Ferreira',
    usina_id: 7,
    contrato_numero: 1005,
    objetivo: 'Preventiva trimestral',
    classificacao: 'Preventiva',
    classificacao_tom: 'ok',
    status: 'APROVADA',
    situacao: 'Concluída',
    tom: 'ok',
    tecnico: 'Fulano de Tal',
    tarefas: 2,
    tarefas_feitas: 2,
    agendada_para: '2026-08-12',
    concluida_em: '2026-08-12',
    fechada_em: null,
    aprovada_em: null,
    execucao_min: 180,
    resumo: null,
    itens: [tarefa({})],
    ...parcial,
  }
}

/** Onde a navegação parou — é assim que se prova que um clique levou (ou não levou) a tela. */
let caminhoAtual = ''
function Espia() {
  caminhoAtual = useLocation().pathname
  return null
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      {/* O endereço é o de verdade, com a família no meio (`/manutencao/ordens`): montar o
          teste no endereço antigo esconderia justamente o que a separação mudou. */}
      <MemoryRouter initialEntries={['/usinas/7/manutencao/ordens/55']}>
        <Espia />
        <Routes>
          <Route path="/usinas/:id/manutencao/ordens/:osId" element={<Pagina />} />
          <Route
            path="/usinas/:id/manutencao/ordens/:osId/tarefas/:taskId"
            element={<p>a ficha da tarefa</p>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Um erro do axios como o interceptor o entrega — é dele que sai a frase do servidor. */
function erroDoServidor(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })
}

describe('tela de uma ordem de serviço', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
    caminhoAtual = ''
    // O dublê é criado uma vez (hoisted) e sobrevive ao `restoreAllMocks`; sem limpar, a
    // contagem de um caso apareceria no seguinte.
    abrirPdfFalso.mockClear()
  })

  afterEach(() => {
    // Sem `globals` no vitest a árvore renderizada não se limpa sozinha, e uma asserção de
    // AUSÊNCIA passaria a falhar por um texto que é do caso anterior.
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('pergunta ao BFF a OS da URL', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({}) })
    montar()
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(String(get.mock.calls[0][0])).toBe('/api/v1/manutencao/ordens/55')
  })

  it('mostra o cabeçalho com a frase de situação do servidor, sem traduzir de novo', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({ status: 'FECHADA', situacao: 'Em verificação', tom: 'tempoRuim' }),
    })
    montar()

    expect(await screen.findByText('Preventiva trimestral')).toBeTruthy()
    expect(screen.getByText('Em verificação')).toBeTruthy()
    expect(screen.getByText('Preventiva')).toBeTruthy()
    // Número de contrato é identificador: sem separador de milhar ("nº 1.005" seria outro).
    expect(screen.getByText('nº 1005')).toBeTruthy()
    expect(screen.getByText('3 h')).toBeTruthy()
    expect(screen.queryByText('FECHADA')).toBeNull()
  })

  it('sem duração e sem contagem, escreve "—" — nunca zero', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({ execucao_min: null, tarefas: null, tarefas_feitas: null, tecnico: null }),
    })
    const { container } = montar()

    await screen.findByText('Preventiva trimestral')
    const travessoes = [...container.querySelectorAll('dd')].filter((d) => d.textContent === '—')
    // Técnico, execução, verificada e concluída-sem-data: nenhum deles vira 0.
    expect(travessoes.length).toBeGreaterThan(0)
    expect(container.textContent).not.toContain('0 de 0')
    expect(container.textContent).not.toContain('0 min')
  })

  it('itens NULO diz que não deu para buscar; itens VAZIO diz que a OS não tem tarefa', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ itens: null }) })
    montar()
    expect(
      await screen.findByText(/Não deu para carregar as tarefas desta ordem/),
    ).toBeTruthy()
    expect(screen.queryByText('Esta ordem não tem tarefas registradas.')).toBeNull()

    cleanup()
    limparCache()
    vi.restoreAllMocks()

    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ itens: [], tarefas: 0, tarefas_feitas: 0 }) })
    montar()
    expect(await screen.findByText('Esta ordem não tem tarefas registradas.')).toBeTruthy()
    expect(screen.queryByText(/Não deu para carregar as tarefas/)).toBeNull()
  })

  it('agrupa por seção, marca a feita e mostra a situação só na que ainda não foi', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({
        tarefas: 2,
        tarefas_feitas: 1,
        itens: [
          tarefa({ id: 1, nome: 'Termografia', grupo: 'Transformador', feita: true }),
          tarefa({
            id: 2,
            nome: 'Limpeza dos módulos',
            grupo: 'Módulos',
            feita: false,
            status: 'PROGRAMADA',
            situacao: 'Programada',
            parecer: null,
          }),
        ],
      }),
    })
    montar()

    expect(await screen.findByText('Transformador')).toBeTruthy()
    expect(screen.getByText('Módulos')).toBeTruthy()
    expect(screen.getByText('Programada')).toBeTruthy()
    // "Executada e verificada" não aparece na tarefa com ✓: o próprio ✓ já disse isso.
    expect(screen.queryByText('Executada e verificada')).toBeNull()
    expect(screen.getByText('1')).toBeTruthy() // contagem "1 de 2"
  })

  it('a cor do parecer é a que o servidor mandou, não uma deduzida da frase', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({
        itens: [
          tarefa({ id: 1, nome: 'Ensaio A', parecer: 'Reprovado', parecer_tom: 'parado' }),
          tarefa({
            id: 2,
            nome: 'Ensaio B',
            parecer: 'Aprovado com ressalva',
            parecer_tom: 'alerta',
          }),
          tarefa({ id: 3, nome: 'Ensaio C', parecer: 'Aprovado', parecer_tom: 'ok' }),
        ],
      }),
    })
    montar()

    expect((await screen.findByText('Reprovado')).className).toContain('text-tom-parado')
    expect(screen.getByText('Aprovado com ressalva').className).toContain('text-tom-alerta')
    expect(screen.getByText('Aprovado').className).toContain('text-tom-ok')
  })

  it('parecer sem cor conhecida sai neutro — nunca verde', async () => {
    // O defeito que a mudança consertou: esta tela tinha `return 'ok'` como fallback da régua
    // local, então um veredito novo do meuPlano chegaria ao cliente pintado de "aprovado" —
    // sobre uma ficha que ninguém tinha lido. Agora quem não sabe a cor não inventa uma.
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({
        itens: [tarefa({ id: 9, nome: 'Ensaio Z', parecer: 'Sob análise', parecer_tom: null })],
      }),
    })
    montar()

    const selo = await screen.findByText('Sob análise')
    expect(selo.className).toContain('text-tom-semDados')
    expect(selo.className).not.toContain('text-tom-ok')
  })

  it('OS de outra usina (404) vira estado vazio com o caminho de volta', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(
      erroDoServidor(404, 'Ordem de serviço não encontrada.'),
    )
    montar()

    // `useLeitura` tenta de novo uma vez antes de desistir (é o desenho dela); a espera aqui
    // cobre esse segundo de repique, senão o teste julga a tela ainda no esqueleto.
    expect(await screen.findByText('Ordem de serviço não encontrada', {}, { timeout: 5000 })).toBeTruthy()
    const volta = screen.getByText('Ver as ordens de serviço') as HTMLAnchorElement
    expect(volta.getAttribute('href')).toBe('/usinas/7/manutencao/ordens')
    // "Tentar de novo" é para rede caída; aqui insistir não abriria nada.
    expect(screen.queryByText('Tentar de novo')).toBeNull()
  })

  it('rede caída e sem cache vira erro com "Tentar de novo", não "não encontrada"', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(
      erroDoServidor(502, 'Não deu para conferir a ordem de serviço: meuPlano indisponível.'),
    )
    montar()

    expect(await screen.findByText('Tentar de novo', {}, { timeout: 5000 })).toBeTruthy()
    expect(screen.queryByText('Ordem de serviço não encontrada')).toBeNull()
  })

  it('o PDF sai por botão — nunca por link com o endereço da API', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({}) })
    const { container } = montar()

    expect(await screen.findByText('Abrir a OS em PDF')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'Ficha em PDF' }).length).toBeGreaterThan(0)
    const comApi = [...container.querySelectorAll('a')].filter((a) =>
      (a.getAttribute('href') ?? '').includes('/api/'),
    )
    expect(comApi.length).toBe(0)
  })

  it('clicar no nome da tarefa abre a ficha daquela tarefa', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({ itens: [tarefa({ id: 6710, nome: 'Termografia' })] }),
    })
    montar()

    const nome = await screen.findByText('Termografia')
    const link = nome.closest('a') as HTMLAnchorElement
    // Os TRÊS ids no endereço: a ficha precisa da usina (para o escopo), da OS e da tarefa.
    expect(link.getAttribute('href')).toBe('/usinas/7/manutencao/ordens/55/tarefas/6710')

    fireEvent.click(nome)
    expect(await screen.findByText('a ficha da tarefa')).toBeTruthy()
    expect(caminhoAtual).toBe('/usinas/7/manutencao/ordens/55/tarefas/6710')
  })

  it('clicar em "Ficha em PDF" abre o arquivo e NÃO troca de tela', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({ itens: [tarefa({ id: 6710, nome: 'Termografia' })] }),
    })
    montar()

    // Pelo PAPEL, e não pelo texto: a busca por texto já casou com um TÍTULO DE CARTÃO em vez
    // deste botão — o cartão de baixo se chamava "Ficha em PDF" e hoje se chama "A ordem em
    // PDF", mas é a busca por papel que impede o engano de voltar.
    fireEvent.click(await screen.findByRole('button', { name: 'Ficha em PDF' }))

    await waitFor(() => expect(abrirPdfFalso).toHaveBeenCalled())
    expect(abrirPdfFalso.mock.calls[0][0]).toBe('/api/v1/manutencao/ordens/55/tarefas/6710/pdf')
    // O botão é irmão do link, não filho: o clique não sobe para a navegação.
    expect(caminhoAtual).toBe('/usinas/7/manutencao/ordens/55')
    expect(screen.queryByText('a ficha da tarefa')).toBeNull()
  })

  it('tarefa sem id não vira link nem ganha botão', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: resposta({ itens: [tarefa({ id: null, nome: 'Item sem identificador' })] }),
    })
    const { container } = montar()

    const nome = await screen.findByText('Item sem identificador')
    expect(nome.closest('a')).toBeNull()
    // Sem id não há PDF de tarefa: o único botão da tela é o da OS inteira.
    expect(screen.queryByRole('button', { name: 'Ficha em PDF' })).toBeNull()
    expect(screen.getByText('Abrir a OS em PDF')).toBeTruthy()
    // E nada de "›" prometendo um destino que não existe.
    const paraTarefas = [...container.querySelectorAll('a')].filter((a) =>
      (a.getAttribute('href') ?? '').includes('/tarefas/'),
    )
    expect(paraTarefas.length).toBe(0)
  })
})
