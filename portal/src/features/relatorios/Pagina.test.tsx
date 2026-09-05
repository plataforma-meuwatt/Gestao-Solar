/**
 * O que este teste guarda são as afirmações que esta tela não pode fazer por engano.
 *
 * **Energia:**
 * 1. **"O portal falhou" onde o gestor apenas não enviou o fechamento.** A lista vazia é um
 *    estado desenhado, com a explicação — não o cartão de erro.
 * 2. **"Este mês não teve resumo executivo" dito por omissão.** O Resumo Executivo só existe
 *    quando o mês teve o resumo gerado no meuWatt (hoje, um em trinta e seis fechamentos).
 *    Peça ausente aparece NOMEADA, com a frase; escondê-la deixaria o cliente sem saber se
 *    ela não existe ou se a tela esqueceu de mostrá-la.
 *
 * **Manutenção:**
 * 3. **"0 % cumprido" onde nada estava previsto.** `pct_cumprido` nulo é "—". O primeiro
 *    acusaria um contrato que não pedia nada no período — e é o número que vai à diretoria.
 * 4. **"Nada foi feito" onde o cronograma só não foi publicado.** Sem versão consolidada, o
 *    bloco mostra a FRASE DO SERVIDOR; e o pacote de fichas continua funcionando, porque são
 *    leituras independentes.
 * 5. **Total somado na tela.** As contagens vêm do servidor. O teste manda linhas que somam
 *    DIFERENTE do total de propósito: trocar o total pelo somatório derruba o teste.
 * 6. **"Baixei todos e vieram três".** Com o pacote em duas partes, os dois botões numerados
 *    têm de aparecer — e o download precisa nascer DENTRO do clique, senão o navegador o
 *    bloqueia e nada acontece.
 *
 * Também guarda a diferença entre `itens: null` ("não deu para buscar") e `itens: []` ("OS
 * sem tarefas"), que desenhadas iguais mentem em direções opostas.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { baixarArquivo } from '@/lib/arquivo'
import { identificarCache, limparCache } from '@/lib/leitura'
import type {
  DocumentosOut,
  InventarioDeFichas,
  Ordem,
  PreparoDeFichas,
  RelatorioOut,
} from '@/features/relatorios/api'
import Relatorios from '@/features/relatorios/Pagina'

// O download de arquivo não passa pelo axios (a sessão vai em cabeçalho, via `fetch`), então
// é o módulo inteiro que se troca. `baixarArquivo` fica espionável para provar que o pacote
// é pedido de dentro do `onClick` — depois de um `await`, o navegador bloquearia.
vi.mock('@/lib/arquivo', () => ({
  abrirPdf: vi.fn(() => Promise.resolve()),
  baixarArquivo: vi.fn(() => Promise.resolve()),
  baixarBlob: vi.fn(),
  baixarComSessao: vi.fn(() => Promise.resolve(new Blob())),
}))

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
  contrato_numero: 665,
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

/** O fechamento COMPLETO: as três peças que o meuWatt publica. */
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
        { tipo: 'resumo', nome: 'resumo-agosto.pdf' },
      ],
    },
  ],
  aviso: null,
}

function inventario(parcial: Partial<InventarioDeFichas> = {}): InventarioDeFichas {
  return {
    usina: 'UFV Porto Ferreira',
    usina_id: 7,
    de: '2026-08',
    ate: '2026-08',
    ordens: [
      {
        os_id: 1016,
        contrato_numero: 665,
        objetivo: 'Inspeção mensal de agosto',
        classificacao: 'Preventiva',
        classificacao_codigo: 'PREVENTIVA',
        classificacao_tom: 'ok',
        situacao: 'Em execução',
        tom: 'alerta',
        status: 'EM_EXECUCAO',
        data: '2026-08-21',
        fichas: [
          {
            task_id: 6710,
            nome: 'O&M-Inversor-Mensal',
            equipamento: 'Inversor 1',
            situacao: 'Executada',
            pronta: true,
            bytes: 2_686_172,
          },
        ],
      },
    ],
    total: 17,
    prontas: 17,
    bytes_estimados: 18_364_627,
    partes: [{ numero: 1, fichas: 17, bytes: 18_364_627 }],
    total_sem_filtro: 20,
    filtros: {},
    aviso: null,
    ...parcial,
  }
}

const PREPARO_ANDANDO: PreparoDeFichas = {
  preparo_id: 'p-1',
  total: 17,
  prontas: 10,
  concluido: false,
  estado: 'andando',
  erro: null,
  erros: [],
  ja_em_andamento: false,
  expira_em: 3600,
  conferido_no_armazenamento: false,
  aviso: null,
}

const PREPARO_PRONTO: PreparoDeFichas = {
  ...PREPARO_ANDANDO,
  prontas: 17,
  concluido: true,
  estado: 'pronto',
}

/**
 * O andamento veio da CONFERÊNCIA no armazenamento: o preparo foi aberto em outro servidor
 * do meuPlano, que roda com mais de uma réplica. O número é verdadeiro; quem trabalhava pode
 * já ter morrido — por isso a saída precisa estar à mão, senão a barra gira sem fim.
 */
const PREPARO_CONFERIDO: PreparoDeFichas = {
  ...PREPARO_ANDANDO,
  prontas: 14,
  conferido_no_armazenamento: true,
  aviso:
    'Andamento conferido no armazenamento (quem está preparando é outro servidor). Se o ' +
    'número parar de subir, peça para preparar de novo.',
}

/**
 * Responde por CAMINHO: a tela faz leituras independentes, e é isso que ela guarda.
 *
 * `fichas` pode ser uma função do caminho — é assim que o teste do filtro prova que a
 * classificação escolhida chega até a query.
 */
function servidor(opcoes: {
  rel?: RelatorioOut
  docs?: DocumentosOut
  fichas?: InventarioDeFichas | ((url: string) => InventarioDeFichas)
  preparo?: PreparoDeFichas
}) {
  const rel = opcoes.rel ?? relatorio()
  const docs = opcoes.docs ?? DOCUMENTOS
  const fichas = opcoes.fichas ?? inventario()
  const responder = (url: string) => {
    if (url.includes('/manutencao/fichas/preparo/')) {
      return Promise.resolve({ data: opcoes.preparo ?? PREPARO_PRONTO })
    }
    if (url.includes('/manutencao/fichas')) {
      return Promise.resolve({ data: typeof fichas === 'function' ? fichas(url) : fichas })
    }
    if (url.includes('/manutencao/contratos')) return Promise.resolve({ data: CONTRATOS })
    if (url.includes('/manutencao/relatorio')) return Promise.resolve({ data: rel })
    if (url.includes('/documents')) return Promise.resolve({ data: docs })
    throw new Error(`caminho inesperado: ${url}`)
  }
  return vi.spyOn(api, 'get').mockImplementation(responder as never)
}

function montar(aba: 'energia' | 'manutencao' = 'energia') {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[`/usinas/7/relatorios?aba=${aba}`]}>
        <Routes>
          <Route path="/usinas/:id/relatorios" element={<Relatorios />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** O caminho de cada leitura de inventário que a tela pediu. */
function caminhosDeFichas(get: ReturnType<typeof servidor>): string[] {
  return get.mock.calls
    .map((c) => String(c[0]))
    .filter((c) => c.includes('/manutencao/fichas') && !c.includes('/preparo/'))
}

beforeEach(() => {
  localStorage.clear()
  identificarCache(7)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.mocked(baixarArquivo).mockClear()
  limparCache()
})

/* ------------------------------------------------------------------ energia */

describe('Relatórios · Energia', () => {
  it('abre em Energia e lista os três PDFs consolidados do fechamento', async () => {
    const get = servidor({})
    montar()

    expect(await screen.findByText('Fechamento de agosto')).toBeTruthy()
    // Os três, na ordem do documento — e com o NOME do cliente, nunca o do arquivo. A
    // terceira peça é o item 5 do pedido do dono; o BFF a recusava até agora.
    const nomes = screen
      .getAllByRole('button')
      .map((b) => b.textContent)
      .filter((t) => t === 'Relatório de geração' || t === 'Anexo de paradas' || t === 'Resumo executivo')
    expect(nomes).toEqual(['Relatório de geração', 'Anexo de paradas', 'Resumo executivo'])
    expect(screen.queryByText('resumo-agosto.pdf')).toBeNull()

    const caminhos = get.mock.calls.map((c) => String(c[0]))
    expect(caminhos.some((c) => c.includes('/documents?usina_id=7'))).toBe(true)
    // A aba fechada não é montada: o inventário de fichas mede o tamanho de cada PDF no
    // armazenamento, e ninguém pediu isso ao abrir a tela de geração.
    expect(caminhos.some((c) => c.includes('/manutencao/fichas'))).toBe(false)
  })

  it('peça que falta aparece nomeada, não some: o Resumo Executivo é raro por desenho', async () => {
    servidor({
      docs: {
        documentos: [
          {
            ...DOCUMENTOS.documentos[0],
            id: 36,
            nome: 'Fechamento de agosto · Pereiras',
            arquivos: [{ tipo: 'resumo', nome: 'resumo-agosto.pdf' }],
          },
        ],
        aviso: null,
      },
    })
    montar()

    expect(await screen.findByRole('button', { name: 'Resumo executivo' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Relatório de geração' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Anexo de paradas' })).toBeNull()
    expect(
      screen.getByText('Relatório de geração · não publicado neste fechamento'),
    ).toBeTruthy()
    expect(screen.getByText('Anexo de paradas · não publicado neste fechamento')).toBeTruthy()
  })

  it('lista vazia explica que o fechamento ainda não foi enviado — e não é erro', async () => {
    servidor({ docs: { documentos: [], aviso: null } })
    montar()

    expect(await screen.findByText('Nenhum fechamento publicado')).toBeTruthy()
    expect(screen.getByText(/depois que a equipe o envia/)).toBeTruthy()
    // O cartão de erro tem esta frase fixa; ela não pode aparecer num vazio legítimo.
    expect(screen.queryByText('Não deu para carregar')).toBeNull()
  })

  it('nenhum PDF é link comum: os arquivos abrem por botão, com a sessão no cabeçalho', async () => {
    servidor({})
    const { container } = montar()

    await screen.findByText('Fechamento de agosto')
    const links = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(links.some((h) => (h ?? '').includes('/api/'))).toBe(false)
  })

  it('o segmentado leva à Manutenção sem sair da usina', async () => {
    servidor({})
    montar()

    await screen.findByText('Fechamento de agosto')
    fireEvent.click(screen.getByRole('button', { name: 'Manutenção' }))

    expect(await screen.findByText('Relatório de manutenção')).toBeTruthy()
    expect(screen.getByText('Fichas do período')).toBeTruthy()
  })
})

/* -------------------------------------------------------- manutenção · relatório */

describe('Relatórios · Manutenção · relatório do período', () => {
  it('pede o relatório da usina da URL, num período que nunca começa depois de terminar', async () => {
    const get = servidor({})
    montar('manutencao')
    await waitFor(() => expect(get).toHaveBeenCalled())

    const caminhos = get.mock.calls.map((c) => String(c[0]))
    const pedido = caminhos.find((c) => c.includes('/manutencao/relatorio'))
    expect(pedido).toBeTruthy()
    const de = new URL(`http://x${pedido}`).searchParams
    expect(de.get('usina_id')).toBe('7')
    expect(String(de.get('de')) <= String(de.get('ate'))).toBe(true)
    // Sem escolha do cliente, o contrato é o que o servidor resolve — nada é chutado aqui.
    expect(de.get('contrato_id')).toBeNull()
  })

  it('sem cronograma consolidado, repete a frase do servidor — e o pacote de fichas continua de pé', async () => {
    const aviso = 'A equipe ainda não publicou o cronograma deste contrato.'
    servidor({ rel: relatorio({ cronograma: null, aviso }) })
    montar('manutencao')

    expect(await screen.findByText('Cronograma não publicado')).toBeTruthy()
    expect(screen.getByText(aviso)).toBeTruthy()
    // Leitura própria: a falta do cronograma não apaga o bloco vizinho.
    expect(await screen.findByText('Ordens do período')).toBeTruthy()
  })

  it('percentual nulo vira "—", nunca "0 %", e os totais são os do servidor', async () => {
    servidor({
      rel: relatorio({
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
    })
    montar('manutencao')

    expect(await screen.findByText('Cumprido')).toBeTruthy()
    expect(screen.queryByText('0,0%')).toBeNull()
    expect(screen.getAllByText('17').length).toBeGreaterThan(0)
    expect(screen.getByText('Ensaio')).toBeTruthy()
    // Dispensa aparece com o motivo — feito e dispensado nunca se fundem.
    expect(screen.getByText('Área alagada')).toBeTruthy()
  })

  it('distingue "não deu para buscar as tarefas" de "ordem sem tarefas"', async () => {
    servidor({
      rel: relatorio({
        ordens: [ORDEM, { ...ORDEM, id: 963, itens: null }, { ...ORDEM, id: 964, itens: [] }],
      }),
    })
    montar('manutencao')

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
    servidor({
      rel: relatorio({
        ordens: [],
        em_curso: [{ ...ORDEM, id: 1016, status: 'EM_EXECUCAO', situacao: 'Em execução' }],
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
    })
    montar('manutencao')

    // O parecer da ordem em curso continua visível...
    expect((await screen.findAllByText('Aprovado com ressalva')).length).toBeGreaterThan(0)
    // ...e a página explica por que ele não está nas contagens.
    expect(
      screen.getAllByText(/ainda em execução aparece acima e não entra nesta conta/).length,
    ).toBe(1)
    // A frase do vazio nomeia o recorte em vez de afirmar "o período não teve problema".
    expect(
      screen.getByText('As fichas das ordens encerradas no período não registraram problema nenhum.'),
    ).toBeTruthy()
  })

  it('diz de quais meses saiu a taxa de cumprimento quando o período passa da vigência', async () => {
    // O portal dava duas respostas para "está sendo feito?": "13 de 270" na aba Cronograma
    // e "cumprido 41,9%" aqui, com um denominador de dois meses sob o rótulo de doze.
    servidor({
      rel: relatorio({
        cronograma: {
          status: 'CONSOLIDATED',
          versao: 1,
          consolidado_em: '2026-03-02T10:00:00-03:00',
          previstas: 31,
          executadas: 12,
          dispensadas: 1,
          atrasadas: 2,
          no_prazo: 15,
          sem_ativo: 1,
          pct_cumprido: 41.9,
          linhas: [],
          dispensas: [],
          previstas_no_contrato: 270,
          recorte:
            'Contagem feita só sobre os 2 meses do período em que este contrato está vigente (jul/2026 a ago/2026); os outros 3 ficaram de fora. O contrato inteiro prevê 270 atividades no ano.',
        },
      }),
    })
    montar('manutencao')
    expect(await screen.findByText(/Contagem feita só sobre os 2 meses/)).toBeTruthy()
  })

  it('a identidade da OS é o id, e a classificação vem traduzida do servidor', async () => {
    // "OS #665" era o número do CONTRATO, e "SERVICOS_ADICIONAIS" chegava cru à tela.
    servidor({
      rel: relatorio({
        ordens: [
          {
            ...ORDEM,
            id: 969,
            objetivo: 'Instalação da Comunicação',
            classificacao: 'Serviços adicionais',
            contrato_numero: 665,
          },
        ],
      }),
    })
    montar('manutencao')
    // O número está num `<Num>` próprio, então a linha inteira se lê pelo pai dele.
    const linha = (await screen.findByText('969')).parentElement
    expect(linha?.textContent).toContain('OS 969')
    expect(linha?.textContent).not.toContain('#665')
    expect(screen.queryByText(/SERVICOS_ADICIONAIS/)).toBeNull()
  })
})

/* -------------------------------------------------------- manutenção · fichas */

describe('Relatórios · Manutenção · pacote de fichas', () => {
  it('inventaria o período antes de oferecer download, e mostra tamanho e quantidade', async () => {
    const get = servidor({})
    montar('manutencao')

    expect(await screen.findByText('Fichas do período')).toBeTruthy()
    expect(await screen.findByText(/Baixar 17 ficha/)).toBeTruthy()
    expect(screen.getByText('17,5 MB')).toBeTruthy()

    const pedidos = caminhosDeFichas(get)
    expect(pedidos.length).toBeGreaterThan(0)
    const q = new URL(`http://x${pedidos[0]}`).searchParams
    expect(q.get('usina_id')).toBe('7')
    expect(String(q.get('de')) <= String(q.get('ate'))).toBe(true)
    // Sem escolha, nenhum recorte extra viaja: o sentinela "todas" é ausência de filtro.
    expect(q.get('classificacao')).toBeNull()
    expect(q.get('situacao')).toBeNull()
    expect(q.get('os_id')).toBeNull()
  })

  it('com fichas por preparar, oferece Preparar e acompanha o andamento até o download', async () => {
    servidor({
      fichas: inventario({ prontas: 10 }),
      preparo: PREPARO_ANDANDO,
    })
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: PREPARO_ANDANDO } as never)
    montar('manutencao')

    const preparar = await screen.findByRole('button', { name: /Preparar 7 ficha/ })
    // Enquanto falta gerar, não há botão de baixar: um pacote parcial é pior que nenhum.
    expect(screen.queryByText(/Baixar 17 ficha/)).toBeNull()

    fireEvent.click(preparar)
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(String(post.mock.calls[0][0])).toContain('/manutencao/fichas/preparar')

    // O "10 de 17" que o dono pediu para poder acompanhar.
    const andamento = await screen.findByText(/Preparando as fichas/)
    expect(andamento.textContent).toContain('10')
    expect(andamento.textContent).toContain('17')
  })

  it('andamento conferido noutro servidor mostra o aviso e deixa a saída à mão', async () => {
    // O meuPlano roda com mais de uma réplica e o preparo vive na memória de quem o abriu.
    // Antes, o poll caído noutra instância dava 404 e a tela dizia "expirou" no meio de um
    // trabalho que ia bem; agora ela recebe o andamento real, marcado. O que ninguém pode
    // garantir é que alguém segue gerando — daí o botão, para a barra não girar para sempre.
    servidor({ fichas: inventario({ prontas: 10 }), preparo: PREPARO_CONFERIDO })
    vi.spyOn(api, 'post').mockResolvedValue({ data: PREPARO_CONFERIDO } as never)
    montar('manutencao')

    fireEvent.click(await screen.findByRole('button', { name: /Preparar 7 ficha/ }))

    const andamento = await screen.findByText(/Preparando as fichas/)
    expect(andamento.textContent).toContain('14')
    expect(screen.getByText(/outro servidor/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Preparar de novo/ })).toBeTruthy()
    // E o download continua fechado: faltam fichas, e pacote parcial é o defeito que esta
    // tela inteira existe para não ter.
    expect(screen.queryByText(/Baixar 17 ficha/)).toBeNull()
  })

  it('preparo concluído libera o download do pacote', async () => {
    servidor({ fichas: inventario({ prontas: 10 }), preparo: PREPARO_PRONTO })
    vi.spyOn(api, 'post').mockResolvedValue({ data: PREPARO_ANDANDO } as never)
    montar('manutencao')

    fireEvent.click(await screen.findByRole('button', { name: /Preparar 7 ficha/ }))
    expect(await screen.findByRole('button', { name: /Baixar 17 ficha/ })).toBeTruthy()
  })

  it('pacote em duas partes vira dois botões numerados — nada fica de fora', async () => {
    servidor({
      fichas: inventario({
        total: 30,
        prontas: 30,
        partes: [
          { numero: 1, fichas: 18, bytes: 80_000_000 },
          { numero: 2, fichas: 12, bytes: 52_000_000 },
        ],
      }),
    })
    montar('manutencao')

    expect(await screen.findByRole('button', { name: /Parte 1 de 2/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Parte 2 de 2/ })).toBeTruthy()
    expect(screen.getByText(/juntas elas trazem as/)).toBeTruthy()
  })

  it('o pacote é pedido DENTRO do clique — depois de um await o navegador bloquearia', async () => {
    servidor({})
    montar('manutencao')

    const botao = await screen.findByRole('button', { name: /Baixar 17 ficha/ })
    expect(vi.mocked(baixarArquivo)).not.toHaveBeenCalled()
    fireEvent.click(botao)
    // Sem nenhum `await` no meio: o pedido nasce do gesto, não de uma promessa resolvida.
    expect(vi.mocked(baixarArquivo)).toHaveBeenCalledTimes(1)

    const [caminho, nome] = vi.mocked(baixarArquivo).mock.calls[0]
    expect(String(caminho)).toContain('/api/v1/manutencao/fichas/pacote')
    expect(String(caminho)).toContain('parte=1')
    // Nome sem acento e sem espaço: ele atravessa sistema de arquivos e cabeçalho HTTP.
    // A competência é a do mês corrente (o recorte padrão), por isso o padrão e não o literal.
    expect(String(nome)).toMatch(/^fichas-ufv-porto-ferreira-\d{4}-\d{2}\.zip$/)
  })

  it('escolher Corretiva muda o caminho da leitura e a contagem na tela', async () => {
    const get = servidor({
      fichas: (url) =>
        url.includes('classificacao=CORRETIVA')
          ? inventario({ total: 6, prontas: 6, partes: [{ numero: 1, fichas: 6, bytes: 3_000_000 }] })
          : inventario(),
    })
    montar('manutencao')

    await screen.findByRole('button', { name: /Baixar 17 ficha/ })

    fireEvent.click(screen.getByText('Todas as classificações'))
    fireEvent.click(screen.getByRole('button', { name: 'Corretiva' }))

    expect(await screen.findByRole('button', { name: /Baixar 6 ficha/ })).toBeTruthy()
    expect(caminhosDeFichas(get).some((c) => c.includes('classificacao=CORRETIVA'))).toBe(true)
  })

  it('filtro que não pega nada diz quanto o período tem, e oferece limpar', async () => {
    servidor({
      fichas: (url) =>
        url.includes('classificacao=CORRETIVA')
          ? inventario({
              total: 0,
              prontas: 0,
              ordens: [],
              partes: [],
              bytes_estimados: null,
              aviso: 'Nenhuma ficha neste filtro.',
            })
          : inventario(),
    })
    montar('manutencao')

    await screen.findByRole('button', { name: /Baixar 17 ficha/ })
    fireEvent.click(screen.getByText('Todas as classificações'))
    fireEvent.click(screen.getByRole('button', { name: 'Corretiva' }))

    expect(await screen.findByText('Nenhuma ficha neste filtro')).toBeTruthy()
    // A frase é do servidor, e o total sem filtro impede a leitura "mês sem manutenção".
    expect(screen.getByText('Nenhuma ficha neste filtro.')).toBeTruthy()
    const limpar = screen.getByRole('button', { name: /Limpar os filtros/ })
    expect(limpar.textContent).toContain('20')

    fireEvent.click(limpar)
    expect(await screen.findByRole('button', { name: /Baixar 17 ficha/ })).toBeTruthy()
  })
})
