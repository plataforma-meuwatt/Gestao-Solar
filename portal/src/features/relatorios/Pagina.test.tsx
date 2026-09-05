/**
 * O que este teste guarda são as três afirmações que esta tela não pode fazer por engano:
 *
 * 1. **"0 % cumprido" onde nada estava previsto.** `pct_cumprido` nulo é "—". O primeiro
 *    acusaria um contrato que não pedia nada no período — e é o número que vai à diretoria.
 * 2. **"Nada foi feito" onde o cronograma só não foi publicado.** Sem versão consolidada, o
 *    bloco do cronograma mostra a FRASE DO SERVIDOR; e os relatórios de geração continuam
 *    listados, porque são leituras independentes.
 * 3. **Total somado na tela.** As contagens vêm do servidor (que as lê do ativo, no
 *    meuPlano). O teste manda linhas que somam DIFERENTE do total de propósito: se alguém
 *    trocar o total pelo somatório das linhas, o número muda e o teste cai.
 *
 * Também guarda a diferença entre `itens: null` ("não deu para buscar") e `itens: []` ("OS
 * sem tarefas"), que desenhadas iguais mentem em direções opostas.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { DocumentosOut, Ordem, RelatorioOut } from '@/features/relatorios/api'
import Relatorios from '@/features/relatorios/Pagina'

const CONTRATOS = {
  usina: 'UFV Porto Ferreira',
  usina_id: 7,
  contratos: [
    {
      id: 665,
      numero: 665,
      titulo: 'O&M 2026',
      inicio: '2026-03-01',
      fim: '2027-02-28',
      vigente: true,
      versao_cronograma: 1,
    },
  ],
  aviso: null,
}

const ORDEM: Ordem = {
  id: 962,
  usina: 'UFV Porto Ferreira',
  usina_id: 7,
  numero: 962,
  objetivo: 'Manutenção preventiva trimestral',
  classificacao: 'PREVENTIVA',
  status: 'APROVADA',
  situacao: 'Concluída',
  tom: 'ok',
  tecnico: 'Diogo',
  tarefas: 4,
  tarefas_feitas: 4,
  agendada_para: '2026-06-10',
  concluida_em: '2026-06-11',
  fechada_em: null,
  aprovada_em: null,
  execucao_min: 180,
  resumo: null,
  itens: [
    {
      id: 11,
      nome: 'Termografia',
      grupo: 'Transformador',
      equipamento: 'Trafo 1',
      status: 'APROVADA',
      situacao: 'Executada e verificada',
      feita: true,
      natureza: 'INSPECAO',
      parecer: 'Aprovado com ressalva',
      // A cor vem do servidor (`TOM_DO_PARECER`); a tela não deduz mais do texto.
      parecer_tom: 'alerta',
      os_id: 962,
      mes_contratual: '2026-06',
      executada_em: '2026-06-11',
      descricao: null,
      observacoes: null,
      preenchimento: 100,
    },
  ],
}

function relatorio(parcial: Partial<RelatorioOut> = {}): RelatorioOut {
  return {
    usina: 'UFV Porto Ferreira',
    usina_id: 7,
    cliente: 'Eninsa',
    executora: 'Splendor O&M',
    contrato: CONTRATOS.contratos[0],
    periodo: { de: '2026-01', ate: '2026-08' },
    cronograma: null,
    ordens: [],
    em_curso: [],
    pareceres: { aprovados: 0, com_ressalva: 0, reprovados: 0, sem_parecer: 0, recorte: null },
    problemas: { total: 0, por_criticidade: [], por_os: [], recorte: null },
    pendencias: { abertas: [], concluidas: [] },
    fotos: null,
    gerado_em: '2026-09-04T12:00:00-03:00',
    aviso: null,
    ...parcial,
  }
}

const DOCUMENTOS: DocumentosOut = {
  documentos: [
    {
      id: 31,
      nome: 'Fechamento de agosto',
      usina: 'UFV Porto Ferreira',
      plant_id: 7,
      periodo: 'MENSAL',
      de: '2026-08-01',
      ate: '2026-08-31',
      publicado_em: '2026-09-01T10:00:00-03:00',
      arquivos: [
        { tipo: 'geracao', nome: 'geracao-agosto.pdf' },
        { tipo: 'paradas', nome: 'paradas-agosto.pdf' },
      ],
    },
  ],
  aviso: null,
}

/** Responde por CAMINHO: a tela faz três leituras independentes. */
function servidor(rel: RelatorioOut, docs: DocumentosOut = DOCUMENTOS) {
  const responder = (url: string) => {
    if (url.includes('/manutencao/contratos')) return Promise.resolve({ data: CONTRATOS })
    if (url.includes('/manutencao/relatorio')) return Promise.resolve({ data: rel })
    if (url.includes('/documents')) return Promise.resolve({ data: docs })
    throw new Error(`caminho inesperado: ${url}`)
  }
  return vi.spyOn(api, 'get').mockImplementation(responder as never)
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/usinas/7/relatorios']}>
        <Routes>
          <Route path="/usinas/:id/relatorios" element={<Relatorios />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('tela de Relatórios', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('pede o relatório da usina da URL, num período que nunca começa depois de terminar', async () => {
    const get = servidor(relatorio())
    montar()
    await waitFor(() => expect(get).toHaveBeenCalled())

    const caminhos = get.mock.calls.map((c) => String(c[0]))
    const pedido = caminhos.find((c) => c.includes('/manutencao/relatorio'))
    expect(pedido).toBeTruthy()
    const de = new URL(`http://x${pedido}`).searchParams
    expect(de.get('usina_id')).toBe('7')
    expect(String(de.get('de')) <= String(de.get('ate'))).toBe(true)
    // Sem escolha do cliente, o contrato é o que o servidor resolve — nada é chutado aqui.
    expect(de.get('contrato_id')).toBeNull()
    expect(caminhos.some((c) => c.includes('/documents?usina_id=7'))).toBe(true)
  })

  it('sem cronograma consolidado, repete a frase do servidor — e os relatórios de geração continuam listados', async () => {
    const aviso = 'A equipe ainda não publicou o cronograma deste contrato.'
    servidor(relatorio({ cronograma: null, aviso }))
    montar()

    expect(await screen.findByText('Cronograma não publicado')).toBeTruthy()
    expect(screen.getByText(aviso)).toBeTruthy()
    // Bloco 2, com leitura própria: a falta do cronograma não o apaga.
    expect(await screen.findByText('Fechamento de agosto')).toBeTruthy()
    expect(screen.getByText('Relatório de geração')).toBeTruthy()
    expect(screen.getByText('Anexo de paradas')).toBeTruthy()
  })

  it('percentual nulo vira "—", nunca "0 %", e os totais são os do servidor', async () => {
    servidor(
      relatorio({
        cronograma: {
          status: 'CONSOLIDATED',
          versao: 1,
          consolidado_em: '2026-03-02T10:00:00-03:00',
          // O total NÃO bate com a soma das linhas de propósito: quem manda é o servidor.
          previstas: 17,
          executadas: 9,
          dispensadas: 2,
          atrasadas: 3,
          no_prazo: 2,
          sem_ativo: 1,
          pct_cumprido: null,
          linhas: [
            {
              plan_item_id: 1,
              nome: 'Termografia',
              categoria: 'ensaio',
              previstas: 4,
              executadas: 4,
              dispensadas: 0,
              atrasadas: 0,
              no_prazo: 0,
              sem_ativo: 0,
            },
          ],
          dispensas: [{ atividade: 'Roçagem', mes: '2026-05', motivo: 'Área alagada' }],
        },
      }),
    )
    montar()

    expect(await screen.findByText('Cumprido')).toBeTruthy()
    expect(screen.queryByText('0,0%')).toBeNull()
    expect(screen.getByText('17')).toBeTruthy()
    expect(screen.getByText('Ensaio')).toBeTruthy()
    // Dispensa aparece com o motivo — feito e dispensado nunca se fundem.
    expect(screen.getByText('Área alagada')).toBeTruthy()
  })

  it('distingue "não deu para buscar as tarefas" de "ordem sem tarefas"', async () => {
    servidor(
      relatorio({
        ordens: [ORDEM, { ...ORDEM, id: 963, numero: 963, itens: null }, { ...ORDEM, id: 964, numero: 964, itens: [] }],
      }),
    )
    montar()

    expect(await screen.findByText('Não deu para buscar as tarefas desta ordem.')).toBeTruthy()
    expect(screen.getByText('Ordem sem tarefas registradas.')).toBeTruthy()
    // O parecer da ficha é colorido pela régua única (ressalva = alerta, não verde).
    const ressalva = screen.getAllByText('Aprovado com ressalva')[0]
    expect(ressalva.className).toContain('text-tom-alerta')
  })

  it('não se contradiz: quando a ordem em curso mostra ressalva, a página diz de onde vêm as contagens', async () => {
    // O caso real: "Aprovado com ressalva" na OS EM CURSO e, logo abaixo, "COM RESSALVA 0"
    // e "as fichas não registraram problema nenhum". Os números estavam certos — o recorte
    // é que era mudo, e um relatório que se contradiz não chega à diretoria.
    servidor(
      relatorio({
        ordens: [],
        em_curso: [{ ...ORDEM, id: 1016, numero: 1016, status: 'EM_EXECUCAO', situacao: 'Em execução' }],
        pareceres: {
          aprovados: 0,
          com_ressalva: 0,
          reprovados: 0,
          sem_parecer: 0,
          recorte:
            'Conta as fichas de 0 ordens encerradas no período. 1 ordem ainda em execução aparece acima e não entra nesta conta: enquanto a ordem não encerra, o parecer ainda pode mudar.',
        },
        problemas: {
          total: 0,
          por_criticidade: [],
          por_os: [],
          recorte: 'Conta as fichas de 0 ordens encerradas no período.',
        },
      }),
    )
    montar()

    // O parecer da ordem em curso continua visível...
    expect((await screen.findAllByText('Aprovado com ressalva')).length).toBeGreaterThan(0)
    // ...e a página explica por que ele não está nas contagens.
    expect(screen.getAllByText(/ainda em execução aparece acima e não entra nesta conta/).length).toBe(1)
    // A frase do vazio nomeia o recorte em vez de afirmar "o período não teve problema".
    expect(
      screen.getByText('As fichas das ordens encerradas no período não registraram problema nenhum.'),
    ).toBeTruthy()
  })

  it('nenhum PDF é link comum: os arquivos abrem por botão, com a sessão no cabeçalho', async () => {
    servidor(relatorio())
    const { container } = montar()

    await screen.findByText('Fechamento de agosto')
    const links = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(links.some((h) => (h ?? '').includes('/api/'))).toBe(false)
    expect(screen.getByText('Baixar PDF')).toBeTruthy()
  })
})
