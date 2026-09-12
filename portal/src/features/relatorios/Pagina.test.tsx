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
 * **Manutenção · relatório mensal liberado:**
 * 7. **"Nenhum relatório" dito como se fosse defeito.** A lista vem vazia hoje na maioria
 *    das usinas porque o fechamento existe e ainda NÃO foi liberado pela equipe — razão de
 *    produto, não de rede. A frase é a do servidor, que sabe qual mês foi pedido.
 * 8. **Um documento inventado.** Um mês pode ter só o executivo publicado. A tela mostra o
 *    que existe; ela não desenha a linha do técnico "vazia" nem some com o mês.
 * 9. **Três datas na mesma linha.** Só `liberado_em` sai para o cliente. `aprovado_por` é
 *    nome de funcionário da executora, e `aprovado_em`/`apurado_em` respondem "quando os
 *    números foram calculados", que não é "de quando é este documento".
 * 10. **Escolher documento por chip.** O dono odeia chip: o mês se escolhe numa lista
 *    suspensa, e o tipo do documento nem é uma escolha — são duas linhas do cartão.
 * 11. **Dois documentos com o mesmo nome.** O mensal e a consulta por período respondem à
 *    mesma pergunta em tempos diferentes. O primeiro é quem se leva à diretoria (e vem
 *    primeiro na tela); o segundo carimba o instante em que foi montado. Sem isso, quem
 *    abrisse os dois em janeiro veria números diferentes de agosto sem saber por quê.
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
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  RelatoriosMensaisOut,
} from '@/features/relatorios/api'
import Relatorios from '@/features/relatorios/Pagina'
// O PRÓPRIO texto do arquivo vizinho, lido pelo empacotador (`?raw`) e não pelo sistema de
// arquivos: um caminho montado com `process.cwd()` quebraria ao rodar o teste de outra
// pasta, e `import.meta.url` aqui não é `file:`. É assim que uma afirmação escrita no
// cabeçalho de um módulo vira uma coisa que a máquina confere.
import fonteDoRelatorioDoPeriodo from '@/features/relatorios/RelatorioManutencao.tsx?raw'

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

/**
 * Dois documentos publicados no mesmo mês, na ordem que o BFF entrega: executivo antes do
 * técnico. Os `liberado_em` são DIFERENTES de propósito — os dois PDFs saem por atos
 * distintos no meuPlano, e uma data só para ambos afirmaria algo que ninguém disse.
 */
const MENSAIS: RelatoriosMensaisOut = {
  usina: 'UFV Porto Ferreira',
  usina_id: 7,
  itens: [
    {
      id: 61,
      usina_id: 7,
      usina: 'UFV Porto Ferreira',
      competencia: '2026-08',
      tipo: 'executivo',
      liberado_em: '2026-09-05T16:18:00-03:00',
    },
    {
      id: 14,
      usina_id: 7,
      usina: 'UFV Porto Ferreira',
      competencia: '2026-08',
      tipo: 'tecnico',
      liberado_em: '2026-09-06T09:40:00-03:00',
    },
  ],
  aviso: null,
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
  mensais?: RelatoriosMensaisOut | ((url: string) => RelatoriosMensaisOut)
}) {
  const rel = opcoes.rel ?? relatorio()
  const docs = opcoes.docs ?? DOCUMENTOS
  const fichas = opcoes.fichas ?? inventario()
  const mensais = opcoes.mensais ?? MENSAIS
  const responder = (url: string) => {
    if (url.includes('/manutencao/fichas/preparo/')) {
      return Promise.resolve({ data: opcoes.preparo ?? PREPARO_PRONTO })
    }
    if (url.includes('/manutencao/fichas')) {
      return Promise.resolve({ data: typeof fichas === 'function' ? fichas(url) : fichas })
    }
    if (url.includes('/manutencao/contratos')) return Promise.resolve({ data: CONTRATOS })
    // ANTES do relatório do período, e não depois: `/manutencao/relatorios-mensais` contém
    // `/manutencao/relatorio` como pedaço, e na ordem inversa o índice do mensal receberia
    // o corpo do relatório sob demanda — a tela ficaria verde com a leitura errada.
    if (url.includes('/manutencao/relatorios-mensais')) {
      return Promise.resolve({ data: typeof mensais === 'function' ? mensais(url) : mensais })
    }
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

/**
 * O cartão do mês, a partir do rótulo da competência.
 *
 * As buscas precisam ser ESCOPADAS: a aba de Manutenção tem três blocos, e dois deles têm
 * um botão "Baixar PDF". Perguntar à tela inteira contaria o botão do vizinho e o teste
 * passaria (ou falharia) por um motivo que não é o dele.
 */
function cartaoDoMes(rotulo: HTMLElement): HTMLElement {
  const cartao = rotulo.closest('section')
  if (cartao === null) throw new Error('o rótulo do mês não está dentro de um cartão')
  return cartao as HTMLElement
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
    //
    // Cada peça é um CARTÃO com capa: o nome é o título dele, e o botão diz "Abrir PDF".
    // Antes o nome era o rótulo do botão — e três botões enfileirados não diziam que o
    // Resumo Executivo existe, só que dava para clicar nele.
    const nomes = screen
      .getAllByRole('heading', { level: 4 })
      .map((h) => h.textContent)
      .filter(
        (t) =>
          t === 'Relatório de geração' || t === 'Anexo de paradas' || t === 'Resumo executivo',
      )
    expect(nomes).toEqual(['Relatório de geração', 'Anexo de paradas', 'Resumo executivo'])
    expect(screen.getAllByRole('button', { name: 'Abrir PDF' }).length).toBe(3)
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

    // As três aparecem NOMEADAS, publicadas ou não: a peça que falta é estado, não erro.
    expect(await screen.findByText('Resumo executivo')).toBeTruthy()
    expect(screen.getByText('Relatório de geração')).toBeTruthy()
    expect(screen.getByText('Anexo de paradas')).toBeTruthy()
    // Só a publicada tem como ser aberta — as outras duas não oferecem botão morto.
    expect(screen.getAllByRole('button', { name: 'Abrir PDF' }).length).toBe(1)
    // E o rótulo da capa diz qual é qual, em vez de deixar o cliente deduzir pela ausência.
    expect(screen.getAllByText('Não publicado').length).toBe(2)
    expect(screen.getAllByText('Publicado').length).toBe(1)
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

    expect(await screen.findByText('Consultar um período')).toBeTruthy()
    expect(screen.getByText('Relatórios do mês')).toBeTruthy()
    expect(screen.getByText('Fichas do período')).toBeTruthy()
  })
})

/* ---------------------------------------------- manutenção · relatório mensal */

describe('Relatórios · Manutenção · relatório mensal liberado', () => {
  it('o documento ENTREGUE vem antes da consulta ao vivo, e cede o nome que era dele', async () => {
    servidor({})
    montar('manutencao')

    const mensal = await screen.findByText('Relatórios do mês')
    const demanda = screen.getByText('Consultar um período')
    // Ordem no DOM: quem responde "o que eu levo para a diretoria?" é o documento que a
    // equipe assinou. `compareDocumentPosition` devolve FOLLOWING quando o segundo vem
    // depois do primeiro.
    expect(mensal.compareDocumentPosition(demanda) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // O nome antigo não pode sobreviver em nenhum dos dois: dois blocos chamados "Relatório
    // de manutenção" na mesma tela é a pergunta "qual é o certo?" nascendo.
    expect(screen.queryByText('Relatório de manutenção')).toBeNull()
  })

  it('o mês publicado traz DUAS linhas — executivo primeiro, técnico depois', async () => {
    servidor({})
    montar('manutencao')

    const cartao = cartaoDoMes(await screen.findByText('Agosto de 2026'))
    const nomes = within(cartao)
      .getAllByRole('heading', { level: 4 })
      .map((h) => h.textContent)
    // Exatamente dois, nesta ordem. A ordem é a do SERVIDOR e a tela a preserva — reordenar
    // aqui criaria uma segunda régua para "qual eu leio primeiro?".
    expect(nomes).toEqual(['Relatório executivo', 'Relatório técnico'])
    expect(within(cartao).getAllByRole('button', { name: 'Baixar PDF' }).length).toBe(2)
  })

  it('mês com só um documento publicado mostra UMA linha — não inventa a que falta', async () => {
    servidor({
      mensais: { ...MENSAIS, itens: [MENSAIS.itens[0]] },
    })
    montar('manutencao')

    const cartao = cartaoDoMes(await screen.findByText('Agosto de 2026'))
    expect(within(cartao).getByText('Relatório executivo')).toBeTruthy()
    expect(within(cartao).queryByText('Relatório técnico')).toBeNull()
    expect(within(cartao).getAllByRole('button', { name: 'Baixar PDF' }).length).toBe(1)
    // E o mês continua na tela: escondê-lo faria "publicado pela metade" parecer "não
    // publicado", que são coisas diferentes.
    expect(screen.getByText('Agosto de 2026')).toBeTruthy()
  })

  it('lista vazia repete a FRASE do servidor — nada foi liberado ainda, e isso não é erro', async () => {
    const aviso = 'O fechamento de agosto de 2026 ainda não foi liberado pela equipe de manutenção.'
    servidor({ mensais: { ...MENSAIS, itens: [], aviso } })
    montar('manutencao')

    expect(await screen.findByText('Nenhum relatório publicado')).toBeTruthy()
    expect(screen.getByText(aviso)).toBeTruthy()
    // O cartão de erro tem esta frase fixa; ela não pode aparecer num vazio legítimo.
    expect(screen.queryByText('Não deu para carregar')).toBeNull()
  })

  it('a única data do cartão é `liberado_em`: quem aprovou e quando não saem para o cliente', async () => {
    servidor({})
    const { container } = montar('manutencao')

    const cartao = cartaoDoMes(await screen.findByText('Agosto de 2026'))
    const texto = cartao.textContent ?? ''
    // As duas datas de publicação, uma por documento — elas são do DOCUMENTO, e os dois
    // PDFs saem por atos distintos no meuPlano.
    expect(texto).toContain('publicado em 5 de setembro de 2026')
    expect(texto).toContain('publicado em 6 de setembro de 2026')
    // Nenhuma outra data, e nenhum nome de funcionário da executora.
    expect(texto).not.toMatch(/aprovado|apurado/i)
    expect(container.textContent ?? '').not.toContain('Liberado p/ envio')
  })

  it('nada de chip: o mês é lista suspensa e o tipo do documento não é botão de escolha', async () => {
    servidor({})
    const { container } = montar('manutencao')

    await screen.findByText('Agosto de 2026')
    // O nome do documento é texto, nunca gatilho de seleção — se virar `<button>` numa
    // fileira, viraram chips.
    for (const nome of ['Relatório executivo', 'Relatório técnico']) {
      expect(screen.getByText(nome).closest('button')).toBeNull()
    }
    // E o mês se escolhe numa lista suspensa pesquisável, cujo gatilho mostra a escolha.
    expect(screen.getByRole('button', { name: /Todos os meses publicados/ })).toBeTruthy()
    // Nenhum PDF é link comum: a sessão vai em cabeçalho, e endereço com token entra em log.
    const links = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(links.some((h) => (h ?? '').includes('/api/'))).toBe(false)
  })

  it('escolher um mês troca a leitura — e o vazio daquele mês fala daquele mês', async () => {
    const get = servidor({
      mensais: (url) =>
        url.includes('competencia=2026-07')
          ? {
              ...MENSAIS,
              itens: [],
              aviso: 'O fechamento de julho de 2026 ainda não foi liberado pela equipe.',
            }
          : MENSAIS,
    })
    montar('manutencao')

    await screen.findByText('Agosto de 2026')
    fireEvent.click(screen.getByRole('button', { name: /Todos os meses publicados/ }))
    fireEvent.click(screen.getByText('Julho de 2026'))

    expect(
      await screen.findByText('O fechamento de julho de 2026 ainda não foi liberado pela equipe.'),
    ).toBeTruthy()
    const pedidos = get.mock.calls
      .map((c) => String(c[0]))
      .filter((c) => c.includes('/manutencao/relatorios-mensais'))
    expect(pedidos.some((c) => c.includes('competencia=2026-07'))).toBe(true)
    // A usina da URL, sempre: o BFF resolve o vínculo por ela, e é a cerca de carteira.
    expect(pedidos.every((c) => c.includes('usina_id=7'))).toBe(true)
  })

  it('a aba Energia não paga pela leitura do mensal — só a aba aberta é montada', async () => {
    const get = servidor({})
    montar()

    await screen.findByText('Fechamento de agosto')
    const caminhos = get.mock.calls.map((c) => String(c[0]))
    expect(caminhos.some((c) => c.includes('/manutencao/relatorios-mensais'))).toBe(false)
  })

  it('a consulta por período carimba QUANDO foi montada e aponta o documento assinado', async () => {
    servidor({})
    montar('manutencao')

    // O carimbo separa os dois documentos no tempo: sem ele, quem abrisse ambos em janeiro
    // veria números diferentes de agosto sem ter como saber que a diferença é o tempo.
    const carimbo = await screen.findByText(/Leitura ao vivo do histórico do ativo, montada em/)
    // E aponta, no mesmo parágrafo, onde mora o documento assinado: a resposta a "qual é o
    // certo?" não pode depender de o cliente rolar a página até achar o outro bloco.
    expect(carimbo.textContent ?? '').toContain('Relatórios do mês')

    // E a frase que MENTIA sobre quem leva o documento à diretoria saiu do arquivo: ela
    // agora é do mensal liberado, que é o que a equipe assina e entrega.
    expect(fonteDoRelatorioDoPeriodo).not.toContain('leva à diretoria')
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
