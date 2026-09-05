/**
 * O que estes testes guardam — o print que o dono mandou, linha por linha.
 *
 * A tela de Pendências abria com **18 linhas, 15 delas concluídas e nenhum filtro**. Oitenta
 * e três por cento do que o cliente via era histórico, e a única pergunta que ele faz de
 * verdade — *"o que está vencido?"* — não tinha como ser feita. Cada teste abaixo prende uma
 * peça da correção:
 *
 * 1. **A tela abre recortada e DIZ que recortou.** Com as 18 pendências reais ela mostra 3 e
 *    a tarja escreve "Mostrando 3 de 18". Sem a tarja, o cliente que abrisse a tela leria
 *    "só há 3 pendências" — que é falso, e é a leitura mais cara que este portal induz.
 * 2. **Nenhum chip.** A regra da casa é lista suspensa pesquisável; uma fileira de botõezinhos
 *    cabe com duas opções e some no celular com vinte. Aqui se prova pela estrutura: as
 *    opções vivem dentro de um menu fechado, não soltas no corpo da tela.
 * 3. **Os cartões do topo NÃO encolhem com o filtro.** Se encolhessem, "Prazo vencido: 0"
 *    passaria a significar "nenhuma vencida neste recorte" — outra frase, e a perigosa.
 * 4. **O quadro é de leitura.** Zero `draggable`, zero manipulador de arrasto, zero
 *    biblioteca de arrastar-e-soltar: o cliente não move pendência, e prometer o gesto é
 *    pior do que nunca tê-lo oferecido.
 * 5. **A coluna do quadro vem do servidor (`coluna`), não da frase.** A pendência com prazo
 *    vencido tem `situacao = "Prazo vencido"` e continua morando em "Aguardando" — se a tela
 *    agrupasse pela frase, ela cairia numa quarta coluna e sumiria do quadro.
 * 6. **Filtro nunca deixa a tela muda.** O recorte vazio mostra a frase e o botão que o
 *    desfaz.
 * 7. **A URL descreve a tela.** `?vista=kanban&situacao=vencidas` reabre exatamente o que a
 *    pessoa que mandou o link estava vendo.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import { aplicar, escreverFiltros, lerFiltrosDaUrl, FILTROS_PADRAO } from '@/features/pendencias/Filtros'
import { ordenar, TETO_DA_CONCLUIDA } from '@/features/pendencias/Kanban'
import type { Pendencia, PendenciasOut } from '@/features/pendencias/api'
import Pendencias from '@/features/pendencias/Pagina'

/** O relógio das telas. Congelado para "vence em até 7 dias" ter uma resposta só. */
const HOJE = new Date(2026, 8, 5, 12, 0, 0)

function pendencia(parcial: Partial<Pendencia> & { id: number }): Pendencia {
  return {
    numero: 1000 + parcial.id,
    usina: 'Porto Ferreira',
    usina_id: 7,
    titulo: `Pendência ${parcial.id}`,
    cobrada_pelo_cliente: false,
    etapa: 'A fazer',
    status: 'ABERTO',
    situacao: 'Aguardando',
    tom: 'alerta',
    coluna: 'aguardando',
    criticidade: null,
    criticidade_tom: null,
    criticidade_rank: 4,
    responsavel: null,
    aberta_em: '2026-08-01T12:00:00Z',
    prazo: null,
    ultima_atividade_em: '2026-09-01T12:00:00Z',
    faixa_parada: '7d',
    concluida_em: null,
    equipamento: null,
    equip_count: null,
    parent_id: null,
    child_count: null,
    documentos: null,
    os_count: null,
    ...parcial,
  }
}

/** A pendência vencida: `tom` e `situacao` são o veredito do BFF, não conta desta tela. */
const VENCIDA = pendencia({
  id: 1,
  titulo: 'Trocar o disjuntor queimado',
  equipamento: 'QGBT 3',
  equip_count: 2,
  situacao: 'Prazo vencido',
  tom: 'parado',
  coluna: 'aguardando',
  prazo: '2026-08-20',
  criticidade: 'critica',
  criticidade_tom: 'parado',
  criticidade_rank: 0,
  cobrada_pelo_cliente: true,
  faixa_parada: '+30d',
  ultima_atividade_em: '2026-07-20T12:00:00Z',
})

const NO_PRAZO = pendencia({
  id: 2,
  titulo: 'Reapertar a conexão do inversor 4',
  prazo: '2026-09-08',
  criticidade: 'alta',
  criticidade_tom: 'multiplos',
  criticidade_rank: 1,
  faixa_parada: 'hoje',
  ultima_atividade_em: '2026-09-05T09:00:00Z',
})

const ANDANDO = pendencia({
  id: 3,
  titulo: 'Roçada do perímetro',
  status: 'EM_ANDAMENTO',
  situacao: 'Em andamento',
  tom: 'ok',
  coluna: 'em_andamento',
  etapa: 'Em execução',
  prazo: '2026-10-20',
  faixa_parada: '30d',
  ultima_atividade_em: '2026-08-15T12:00:00Z',
})

/** As 15 concluídas — o histórico que sozinho ocupava 83 % da tela. */
const CONCLUIDAS = Array.from({ length: 15 }, (_, i) =>
  pendencia({
    id: 100 + i,
    titulo: `Serviço encerrado ${i + 1}`,
    status: 'CONCLUIDO',
    situacao: 'Concluída',
    tom: 'semDados',
    coluna: 'concluida',
    etapa: 'Concluído',
    prazo: '2026-07-10',
    concluida_em: '2026-07-09T12:00:00Z',
    ultima_atividade_em: `2026-07-${String(i + 1).padStart(2, '0')}T12:00:00Z`,
    faixa_parada: '+30d',
  }),
)

const TODAS = [VENCIDA, NO_PRAZO, ANDANDO, ...CONCLUIDAS]

function resposta(parcial: Partial<PendenciasOut> = {}): PendenciasOut {
  return {
    total: 18,
    abertas: 3,
    concluidas: 15,
    prazo_vencido: 1,
    aguardando: 2,
    em_andamento: 1,
    cobradas_abertas: 1,
    pendencias: TODAS,
    usinas_com_manutencao: 1,
    aviso: null,
    ...parcial,
  }
}

function servidor(dados: PendenciasOut) {
  return vi.spyOn(api, 'get').mockImplementation(async () => ({ data: dados }) as never)
}

function montar(busca = '') {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[`/usinas/7/manutencao/pendencias${busca}`]}>
        <Routes>
          <Route path="/usinas/:id/manutencao/pendencias" element={<Pendencias />} />
          <Route path="/usinas/:id/manutencao/pendencias/:cid" element={<Pendencias />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Texto da tela com espaços normalizados — a tarja é montada de vários elementos. */
function texto(el: HTMLElement): string {
  return (el.textContent ?? '').replace(/\s+/g, ' ')
}

/**
 * O CÓDIGO do quadro, lido do disco.
 *
 * Duas das regras deste item não deixam rastro no DOM quando são quebradas de leve — uma
 * biblioteca de arrastar-e-soltar importada mas ainda não ligada, um `onDrop` num contêiner
 * vazio. Ler a fonte é o único jeito de a proibição valer antes de o defeito aparecer na
 * tela do cliente.
 */
const FONTE_DO_KANBAN = readFileSync(
  resolve(process.cwd(), 'src/features/pendencias/Kanban.tsx'),
  'utf8',
)

/**
 * O código SEM os comentários.
 *
 * A proibição tem de valer para o que roda, não para o que se escreve sobre ele: o próprio
 * cabeçalho do `Kanban.tsx` explica por que não há `draggable` nem `onDrop`, e conferir a
 * fonte crua reprovaria o arquivo por causa da explicação. Um teste que só se satisfaz
 * quando ninguém pode nomear a regra é um teste que obriga a apagar a razão dela.
 */
const CODIGO_DO_KANBAN = FONTE_DO_KANBAN.replace(/\/\*[\s\S]*?\*\//g, '').replace(
  /\/\/.*$/gm,
  '',
)

describe('tela de Pendências', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(HOJE)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    limparCache()
  })

  /* ---------------------------------------------------------------- o recorte */

  it('abre em "Em aberto": 3 linhas das 18, e a tarja diz de quantas', async () => {
    servidor(resposta())
    const { container } = montar()

    await screen.findByText('Trocar o disjuntor queimado')
    expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
    expect(texto(container)).toMatch(/Mostrando 3 de 18/)
    // E as 15 concluídas ficam fora — que é o ponto todo do recorte padrão.
    expect(screen.queryByText('Serviço encerrado 1')).toBeNull()
  })

  it('a tarja nomeia o corte que encolheu a lista, e não só o número', async () => {
    servidor(resposta())
    const { container } = montar()
    await screen.findByText('Trocar o disjuntor queimado')
    expect(texto(container)).toMatch(/Mostrando 3 de 18 · Em aberto/)
  })

  it('sem corte nenhum a tarja some — não há o que explicar', async () => {
    servidor(resposta())
    const { container } = montar('?situacao=todas')
    await screen.findByText('Trocar o disjuntor queimado')
    expect(container.querySelectorAll('tbody tr')).toHaveLength(18)
    expect(texto(container)).not.toMatch(/Mostrando/)
  })

  it('"Limpar filtros" mostra as 18 — não volta ao padrão recortado', async () => {
    servidor(resposta())
    const { container } = montar('?criticidade=critica')
    await screen.findByText('Trocar o disjuntor queimado')

    fireEvent.click(screen.getByRole('button', { name: 'Limpar filtros' }))
    await waitFor(() => expect(container.querySelectorAll('tbody tr')).toHaveLength(18))
  })

  /* ---------------------------------------------------------------- os seis cortes */

  it('há seis cortes, e são os seis pedidos', async () => {
    servidor(resposta())
    const { container } = montar()
    await screen.findByText('Trocar o disjuntor queimado')

    const eixos = [...container.querySelectorAll('[data-filtro]')].map((e) =>
      e.getAttribute('data-filtro'),
    )
    expect(eixos).toEqual(['situacao', 'prazo', 'usina', 'criticidade', 'parada', 'busca'])
  })

  it('nenhum chip: as opções vivem num menu fechado, não soltas na tela', async () => {
    servidor(resposta())
    const { container } = montar()
    await screen.findByText('Trocar o disjuntor queimado')

    // Um corte em chips renderizaria a lista inteira de opções o tempo todo. Fechado, o
    // Combobox não tem `ul` nenhum no corpo — só o botão que o abre.
    expect(container.querySelectorAll('[data-filtro] ul')).toHaveLength(0)

    // E nenhum rótulo de opção de criticidade aparece como botão avulso.
    const proibidos = new Set(['Crítica', 'Alta', 'Média', 'Baixa', 'Vencidas'])
    const chips = [...container.querySelectorAll('button')].filter((b) =>
      proibidos.has((b.textContent ?? '').trim()),
    )
    expect(chips).toHaveLength(0)
  })

  it('cada opção leva a contagem do que ela devolveria', async () => {
    servidor(resposta())
    const { container } = montar()
    await screen.findByText('Trocar o disjuntor queimado')

    const situacao = container.querySelector('[data-filtro="situacao"] button')
    expect(situacao?.textContent).toContain('Em aberto (3)')

    fireEvent.click(situacao as Element)
    const menu = container.querySelector('[data-filtro="situacao"] ul') as HTMLElement
    expect(texto(menu)).toMatch(/Todas as situações \(18\)/)
    expect(texto(menu)).toMatch(/Concluídas \(15\)/)
  })

  it('opção que devolveria zero não é oferecida', async () => {
    servidor(resposta())
    // Com a criticidade "crítica" ligada sobra UMA pendência, e ela está em "Aguardando".
    // Logo "Em andamento" e "Concluídas" levariam a lugar nenhum — e um caminho que só
    // devolve o vazio não pode estar aberto na tela.
    const { container } = montar('?criticidade=critica&situacao=todas')
    await screen.findByText('Trocar o disjuntor queimado')

    fireEvent.click(container.querySelector('[data-filtro="situacao"] button') as Element)
    const menu = container.querySelector('[data-filtro="situacao"] ul') as HTMLElement
    expect(texto(menu)).toMatch(/Aguardando \(1\)/)
    expect(texto(menu)).not.toMatch(/Concluídas/)
    expect(texto(menu)).not.toMatch(/Em andamento/)
    expect(texto(menu)).not.toMatch(/\(0\)/)
  })

  it('mas a opção ESCOLHIDA fica, mesmo zerada — senão o cliente não a desliga', async () => {
    servidor(resposta())
    const { container } = montar('?criticidade=critica&situacao=concluidas')
    await screen.findByText('Nenhuma pendência com os filtros escolhidos')

    // O recorte devolve zero; o corte que o causou continua nomeado, e desligável.
    const gatilho = container.querySelector('[data-filtro="situacao"] button') as HTMLElement
    expect(gatilho.textContent).toContain('Concluídas (0)')
  })

  it('a busca recorta por título e por número', () => {
    expect(aplicar(TODAS, { ...FILTROS_PADRAO, busca: 'disjuntor' }, HOJE)).toHaveLength(1)
    // Sem acento acha com acento: o cliente digita "rocada".
    expect(aplicar(TODAS, { ...FILTROS_PADRAO, busca: 'rocada' }, HOJE)).toHaveLength(1)
    expect(aplicar(TODAS, { ...FILTROS_PADRAO, busca: '#1001' }, HOJE)).toHaveLength(1)
  })

  it('"vencidas" é o veredito do servidor, não uma segunda conta da tela', () => {
    // A concluída também tem prazo no passado (10/07). Se esta tela recalculasse "venceu"
    // comparando datas, ela entraria — e o portal cobraria de novo o que já foi resolvido.
    const so = aplicar(TODAS, { ...FILTROS_PADRAO, situacao: 'todas', prazo: 'vencidas' }, HOJE)
    expect(so.map((p) => p.id)).toEqual([VENCIDA.id])
  })

  it('as janelas futuras de prazo contam a partir de hoje', () => {
    const f = { ...FILTROS_PADRAO, situacao: 'todas' as const }
    // 08/09 está dentro de 7 dias de 05/09; 20/10 não, mas cabe em 30? Não: são 45 dias.
    expect(aplicar(TODAS, { ...f, prazo: 'vence7' }, HOJE).map((p) => p.id)).toEqual([NO_PRAZO.id])
    expect(aplicar(TODAS, { ...f, prazo: 'vence30' }, HOJE).map((p) => p.id)).toEqual([NO_PRAZO.id])
    // Sem prazo combinado é um estado, não um vazio: tem de ser filtrável.
    expect(aplicar(TODAS, { ...f, prazo: 'sem_prazo' }, HOJE)).toHaveLength(0)
  })

  it('o segmento "Cobradas por mim" continua, e já não é o padrão', async () => {
    servidor(resposta())
    const { container } = montar()
    await screen.findByText('Trocar o disjuntor queimado')

    const botao = screen.getByRole('button', { name: /Cobradas por mim/ })
    expect(botao.textContent).toContain('1 abertas')
    // Padrão = todas: abrir com dois recortes empilhados esconderia a maior parte sem dizer.
    expect(container.querySelectorAll('tbody tr')).toHaveLength(3)

    fireEvent.click(botao)
    await waitFor(() => expect(container.querySelectorAll('tbody tr')).toHaveLength(1))
    expect(texto(container)).toMatch(/Cobradas por mim/)
  })

  /* ---------------------------------------------------------------- os cartões do topo */

  it('os cartões do topo descrevem o conjunto inteiro e dizem isso por escrito', async () => {
    servidor(resposta())
    const { container } = montar('?criticidade=critica')
    await screen.findByText('Trocar o disjuntor queimado')

    // A lista mostra 1; os cartões continuam falando das 18.
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    const cartoes = container.querySelector('section') as HTMLElement
    expect(texto(cartoes)).toMatch(/Abertas\s*3/)
    expect(texto(cartoes)).toMatch(/Concluídas\s*15/)
    expect(texto(cartoes)).toMatch(/Total compartilhado\s*18/)
    expect(texto(cartoes)).toMatch(/os filtros abaixo recortam a lista, não os cartões/)
  })

  /* ---------------------------------------------------------------- o quadro */

  it('o quadro tem três colunas, por situação', async () => {
    servidor(resposta())
    const { container } = montar('?vista=kanban&situacao=todas')
    await screen.findByText('Trocar o disjuntor queimado')

    const colunas = [...container.querySelectorAll('section[aria-label]')].map((s) =>
      s.getAttribute('aria-label'),
    )
    expect(colunas).toEqual(['Aguardando', 'Em andamento', 'Concluída'])
  })

  it('o quadro não se arrasta: nem no DOM, nem no código', async () => {
    servidor(resposta())
    const { container } = montar('?vista=kanban&situacao=todas')
    await screen.findByText('Trocar o disjuntor queimado')

    expect(container.querySelectorAll('[draggable]')).toHaveLength(0)
    expect(container.querySelectorAll('[data-rbd-draggable-id]')).toHaveLength(0)
    for (const proibido of ['draggable', 'onDragStart', 'onDragOver', 'onDrop', 'dnd-kit']) {
      expect(CODIGO_DO_KANBAN).not.toContain(proibido)
    }
  })

  it('a coluna vem de `coluna`, não da frase: a vencida fica em "Aguardando"', async () => {
    servidor(resposta())
    const { container } = montar('?vista=kanban&situacao=todas')
    await screen.findByText('Trocar o disjuntor queimado')

    const aguardando = container.querySelector('section[aria-label="Aguardando"]') as HTMLElement
    expect(texto(aguardando)).toContain('Trocar o disjuntor queimado')
    expect(texto(aguardando)).toContain('Prazo vencido')
  })

  it('a coluna Concluída abre recolhida em 5, com o botão que mostra as 15', async () => {
    servidor(resposta())
    const { container } = montar('?vista=kanban&situacao=todas')
    await screen.findByText('Trocar o disjuntor queimado')

    const concluida = container.querySelector('section[aria-label="Concluída"]') as HTMLElement
    expect(concluida.querySelectorAll('[data-card="pendencia"]')).toHaveLength(TETO_DA_CONCLUIDA)

    const verTodas = screen.getByRole('button', { name: 'Ver todas as 15' })
    fireEvent.click(verTodas)
    await waitFor(() =>
      expect(concluida.querySelectorAll('[data-card="pendencia"]')).toHaveLength(15),
    )
  })

  it('a vencida vem primeiro; sem prazo vai para o fim, e não para o topo', () => {
    const semPrazo = pendencia({ id: 9, prazo: null, ultima_atividade_em: '2026-09-04T12:00:00Z' })
    const ordem = ordenar([ANDANDO, semPrazo, VENCIDA, NO_PRAZO]).map((p) => p.id)
    expect(ordem).toEqual([VENCIDA.id, NO_PRAZO.id, ANDANDO.id, semPrazo.id])
  })

  it('os cinco cortes comuns valem igual nas duas vistas', async () => {
    // O que continua verdadeiro: prazo, usina, criticidade, parado há e busca recortam o
    // mesmo conjunto nas duas — trocar de vista não pode mudar de quem se está falando.
    servidor(resposta())
    const lista = montar('?prazo=vencidas')
    await screen.findByText('Trocar o disjuntor queimado')
    expect(lista.container.querySelectorAll('tbody tr')).toHaveLength(1)
    cleanup()

    const quadro = montar('?vista=kanban&prazo=vencidas')
    await screen.findByText('Trocar o disjuntor queimado')
    expect(quadro.container.querySelectorAll('[data-card="pendencia"]')).toHaveLength(1)
  })

  it('no QUADRO a situação não recorta: ela é o eixo das colunas', async () => {
    // O DEFEITO que o dono viu: o quadro abria em "Em aberto" e duas das três colunas
    // diziam "Nenhuma aqui" enquanto o cartão logo acima contava CONCLUÍDAS 15 — duas
    // afirmações sobre o mesmo conjunto, na mesma tela. Filtrar pela situação dentro de um
    // quadro cujas colunas SÃO a situação esvazia as outras por construção.
    servidor(resposta())
    const lista = montar('?situacao=abertas')
    await screen.findByText('Trocar o disjuntor queimado')
    expect(lista.container.querySelectorAll('tbody tr')).toHaveLength(3)
    cleanup()

    const quadro = montar('?vista=kanban&situacao=abertas')
    await screen.findByText('Trocar o disjuntor queimado')
    // O quadro mostra TODAS — inclusive as concluídas que o corte tirava da lista. São 8
    // cartões porque a coluna Concluída recolhe em 5, com o "Ver todas as 15" ao pé.
    expect(quadro.container.querySelectorAll('[data-card="pendencia"]')).toHaveLength(8)
    expect(quadro.container.textContent).toContain('Ver todas as 15')
    // E o controle que não faz nada some da barra: os outros cinco continuam lá.
    expect(quadro.container.querySelector('[data-filtro="situacao"]')).toBeNull()
    expect(quadro.container.querySelector('[data-filtro="prazo"]')).toBeTruthy()
  })

  it('voltar do quadro para a lista devolve o corte por situação inteiro', async () => {
    // O corte pedido continua guardado na URL: o quadro o ignora, não o apaga. Sem isto,
    // uma ida ao quadro apagaria em silêncio o filtro que a pessoa tinha escolhido.
    servidor(resposta())
    const quadro = montar('?vista=kanban&situacao=concluidas')
    await screen.findByText('Trocar o disjuntor queimado')
    expect(quadro.container.querySelectorAll('[data-card="pendencia"]')).toHaveLength(8)
    cleanup()

    const lista = montar('?situacao=concluidas')
    await screen.findByText('Serviço encerrado 1')
    expect(lista.container.querySelectorAll('tbody tr')).toHaveLength(15)
  })

  it('no celular o quadro empilha — uma coluna, que é uma lista', () => {
    expect(CODIGO_DO_KANBAN).toContain('grid-cols-1 gap-4 md:grid-cols-3')
  })

  /* ---------------------------------------------------------------- a URL */

  it('?vista=kanban&situacao=vencidas reabre a mesma tela', async () => {
    servidor(resposta())
    const { container } = montar('?vista=kanban&situacao=vencidas')
    await screen.findByText('Trocar o disjuntor queimado')

    // Quadro, e só o que está vencido.
    expect(container.querySelectorAll('section[aria-label]')).toHaveLength(3)
    expect(container.querySelectorAll('[data-card="pendencia"]')).toHaveLength(1)
    // E o corte aparece marcado no eixo certo, para o cliente saber desligá-lo.
    expect(container.querySelector('[data-filtro="prazo"] button')?.textContent).toContain(
      'Vencidas',
    )
  })

  it('o apelido `situacao=vencidas` vira o par honesto, sem uma segunda porta', () => {
    const f = lerFiltrosDaUrl(new URLSearchParams('situacao=vencidas'))
    expect(f.situacao).toBe('abertas')
    expect(f.prazo).toBe('vencidas')
  })

  it('valor inventado na URL cai no padrão, calado', () => {
    const f = lerFiltrosDaUrl(new URLSearchParams('situacao=amanha&prazo=nunca&parada=sempre'))
    expect(f.situacao).toBe(FILTROS_PADRAO.situacao)
    expect(f.prazo).toBe(FILTROS_PADRAO.prazo)
    expect(f.parada).toBe(FILTROS_PADRAO.parada)
  })

  it('o padrão não é escrito na barra de endereço', () => {
    const p = escreverFiltros(new URLSearchParams('vista=kanban'), {
      ...FILTROS_PADRAO,
      criticidade: 'alta',
    })
    expect(p.get('criticidade')).toBe('alta')
    expect(p.get('situacao')).toBeNull()
    expect(p.get('prazo')).toBeNull()
    // O que não é filtro sobrevive: limpar um corte não pode derrubar a vista escolhida.
    expect(p.get('vista')).toBe('kanban')
  })

  /* ---------------------------------------------------------------- os vazios */

  it('filtro que zeraria a lista mostra a frase, e não a tela muda', async () => {
    servidor(resposta())
    const { container } = montar('?busca=zzzz')
    await screen.findByText('Nenhuma pendência com os filtros escolhidos')

    expect(container.querySelectorAll('tbody tr')).toHaveLength(0)
    expect(texto(container)).toMatch(/Mostrando 0 de 18/)
    expect(screen.getAllByRole('button', { name: 'Limpar filtros' }).length).toBeGreaterThan(0)
  })

  it('tudo concluído é boa notícia, e a frase diz isso', async () => {
    servidor(resposta({ pendencias: CONCLUIDAS, total: 15, abertas: 0, concluidas: 15 }))
    montar()
    await screen.findByText('Nenhuma pendência em aberto')
    expect(screen.getByRole('button', { name: 'Ver as 15 compartilhadas' })).toBeTruthy()
  })

  it('usina sem nenhuma pendência compartilhada não ganha barra de filtros', async () => {
    servidor(resposta({ pendencias: [], total: 0, abertas: 0, concluidas: 0, prazo_vencido: 0 }))
    const { container } = montar()
    await screen.findByText('Nenhuma pendência compartilhada nesta usina')
    // Filtrar o nada é ruído: os seis cortes não existem quando não há o que cortar.
    expect(container.querySelectorAll('[data-filtro]')).toHaveLength(0)
  })
})
