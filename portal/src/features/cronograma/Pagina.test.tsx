/**
 * O cronograma é o artefato que o dono nomeou ("ele quer ver o CRONOGRAMA com o X"), e a
 * frase seguinte é o limite: *"e olha lá — ele só quer saber se está sendo feito"*. Depois
 * ele olhou a tela pronta e disse: *"tá CINZA que horrível"*.
 *
 * O que estava na tela quando ele falou isso: quinze cabeçalhos de bloco cinza-chapado,
 * recolhidos, doze colunas de mês vazias, e o cartão "13 de 270 previstas". Nenhuma das 269
 * marcas do contrato aparecia — nem as 13 do mês que fechou 13 de 13 — e o número grande
 * dividia por um ano que ainda não tinha acontecido.
 *
 * Os defeitos que cada bloco de teste guarda estão na docstring de cada `it`. Os quatro que
 * motivaram o trabalho:
 *
 * 1. **O cinza.** A faixa de bloco pedia o token `bg-superficie-alta` com o modificador de
 *    opacidade `40` e recebia `rgba(255,255,255,0.4)`: o modificador SUBSTITUI o alfa de um
 *    token declarado como `rgba(...)` em vez de multiplicá-lo — cinco vezes o alfa do token
 *    e três vezes o da superfície mais clara do design system. Nenhum `tsc` pega isso;
 *    agora `scripts/regra0.mjs` pega (inclusive esta frase, se ela citasse a classe).
 * 2. **A matriz na frente.** Ela virou o detalhe, atrás de um clique, e nasce NÃO MONTADA.
 * 3. **O denominador.** O número grande é o recorte de vigência do servidor; o total do
 *    contrato desceu para contexto pequeno. É a diferença entre "13 de 13" e "13 de 270".
 * 4. **A cor do "previsto".** Ela era `tempoRuim`, que neste produto significa UMA coisa:
 *    perda por clima.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import { estadoDoMes, tomDoEstado, type MesDaFita } from '@/features/cronograma/FitaDosMeses'
import {
  tomDaCelula,
  type Celula,
  type CronogramaOut,
  type LinhaCronograma,
  type MesEstado,
} from '@/features/cronograma/api'
import Cronograma from '@/features/cronograma/Pagina'

/** Os doze meses do contrato de Porto Ferreira: âncora em agosto, não em janeiro. */
const MESES = [
  '2026-08', '2026-09', '2026-10', '2026-11', '2026-12', '2027-01',
  '2027-02', '2027-03', '2027-04', '2027-05', '2027-06', '2027-07',
]

const VAZIA: Omit<Celula, 'mes'> = {
  previsto: 0,
  estado: null,
  feito: false,
  dispensado: false,
  atrasado: false,
}

/** Doze células; só os meses citados no mapa fogem do "o contrato não prevê nada aqui". */
function celulas(mapa: Record<string, Partial<Celula>>): Celula[] {
  return MESES.map((mes) => ({ mes, ...VAZIA, ...(mapa[mes] ?? {}) }))
}

function linha(parcial: Partial<LinhaCronograma>): LinhaCronograma {
  return {
    plan_item_id: 1,
    nome: 'Medição do TTR',
    categoria: 'Ensaio',
    categoria_codigo: 'ensaio',
    periodicidade: 'Semestral',
    grupo: 'Subestação',
    previsto_ano: 2,
    feitos: 1,
    meses: celulas({
      '2026-08': { previsto: 1, estado: 'verde', feito: true },
      '2026-09': { previsto: 1, estado: 'azul' },
    }),
    ...parcial,
  }
}

function mes(m: string, parcial: Partial<MesEstado>): MesEstado {
  return { mes: m, situacao: 'futuro', previsto: 22, cumprido: 0, ...parcial }
}

/** O recorte de vigência como o meuPlano o publica: agosto fechado, setembro em curso. */
const MESES_ESTADO: MesEstado[] = MESES.map((m) => {
  if (m === '2026-08') return mes(m, { situacao: 'fechado', previsto: 13, cumprido: 13 })
  if (m === '2026-09') return mes(m, { situacao: 'corrente', previsto: 18, cumprido: 0 })
  return mes(m, {})
})

function cronograma(parcial: Partial<CronogramaOut> = {}): CronogramaOut {
  return {
    usina: 'Porto Ferreira',
    usina_id: 7,
    contrato_id: 698,
    contrato: 'O&M 2026',
    pdf_disponivel: true,
    status: 'CONSOLIDATED',
    versao: 1,
    meses: MESES,
    linhas: [
      linha({}),
      linha({
        plan_item_id: 2,
        nome: 'Limpeza do quadro',
        grupo: 'CFTV',
        meses: celulas({
          '2026-08': { previsto: 1, estado: 'verde_ressalva', dispensado: true },
          '2026-09': { previsto: 1, estado: 'azul' },
        }),
      }),
    ],
    previsto_ano: 269,
    feitos_ano: 13,
    mes_referencia: '2026-09',
    previsto_ate_hoje: 13,
    cumprido_ate_hoje: 13,
    pct_ate_hoje: 100,
    previsto_no_contrato: 270,
    meses_estado: MESES_ESTADO,
    aviso: null,
    ...parcial,
  }
}

function servidor(dados: CronogramaOut) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: unknown) => {
    if (String(url).includes('/manutencao/contratos')) {
      return {
        data: {
          usina: 'Porto Ferreira',
          usina_id: 7,
          contratos: [
            {
              id: 698, numero: 698, titulo: 'O&M 2026', inicio: '2026-08-01',
              fim: '2027-07-31', vigente: true, versao_cronograma: 1,
            },
          ],
          aviso: null,
        },
      } as never
    }
    return { data: dados } as never
  })
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/usinas/7/cronograma']}>
        <Routes>
          <Route path="/usinas/:id/cronograma" element={<Cronograma />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/**
 * Espera a matriz — que nasce ABERTA desde que o dono recusou o clique a mais.
 *
 * Continua existindo como funcao para o dia em que a decisao virar de novo: o corpo muda
 * aqui, e os testes que a chamam seguem valendo.
 */
async function abrirMatriz() {
  await screen.findByText('Cronograma inteiro')
  await waitFor(() => expect(screen.getByText('Atividade')).toBeTruthy())
}

describe('tela de Cronograma', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  /* ---------------------------------------------------------------- a fita */

  it('monta os doze meses do contrato como blocos, e não como uma tabela vazia', async () => {
    // O DEFEITO: a tela abria pela matriz, cujas doze colunas de mês vinham VAZIAS porque as
    // 94 linhas nasciam recolhidas sob os blocos. O cliente não via marca nenhuma — nem as
    // do mês que fechou completo. A fita é a resposta antes de qualquer clique.
    servidor(cronograma())
    const { container } = montar()
    await screen.findByText('Cronograma inteiro')
    expect(container.querySelectorAll('[data-mes]').length).toBe(12)
  })

  it('a matriz nasce ABERTA — e recolher DESMONTA, nunca esconde por CSS', async () => {
    // O DEFEITO que o dono viu: com a matriz fechada, a tela inteira era um veredito, um
    // número e um botão; quem foi ver "o que foi feito" precisava descobrir mais um clique.
    // O que se mantém do desenho anterior é a outra metade da regra: recolhido tem de
    // significar NÃO MONTADO — mil células escondidas por CSS custam o mesmo que mostradas.
    servidor(cronograma())
    const { container } = montar()
    await screen.findByText('Cronograma inteiro')
    expect(container.querySelectorAll('table').length).toBe(1)
    expect(container.querySelectorAll('td').length).toBeGreaterThan(0)

    screen.getByText('Cronograma inteiro').click()
    await waitFor(() => expect(container.querySelectorAll('table').length).toBe(0))
    expect(container.querySelectorAll('td').length).toBe(0)
  })

  it('agosto sai como mês fechado e cumprido, com 13 de 13 escrito', async () => {
    // O DEFEITO: o mês que fechou 13 de 13 não aparecia em lugar nenhum da tela. A cor
    // sozinha também não bastaria — o quadro é lido projetado em reunião, então o bloco
    // imprime os números.
    servidor(cronograma())
    const { container } = montar()
    await screen.findByText('Cronograma inteiro')
    const ago = container.querySelector('[data-mes="2026-08"]')
    expect(ago?.getAttribute('data-estado')).toBe('cumprido')
    expect(ago?.textContent).toContain('13 de 13')
    expect(ago?.outerHTML).toContain('tom-ok')
  })

  it('setembro, o mês em curso, sai como "em andamento" — nunca como falha', async () => {
    // O DEFEITO a evitar: pintar de vermelho, ou de qualquer cor de cobrança, um mês que
    // ainda tem dias pela frente. Quem classifica é o servidor (`situacao`), não o relógio.
    servidor(cronograma())
    const { container } = montar()
    await screen.findByText('Cronograma inteiro')
    const set = container.querySelector('[data-mes="2026-09"]')
    expect(set?.getAttribute('data-estado')).toBe('andamento')
    expect(set?.textContent).toContain('em andamento')
    expect(set?.textContent).toContain('0 de 18')
  })

  it('mês futuro fica SEM cor de status: não venceu, logo não é falha', async () => {
    // O DEFEITO: qualquer cor de status num mês que ainda não chegou acusa o prestador por
    // um serviço cuja data não venceu. A ausência de cor é a informação.
    servidor(cronograma())
    const { container } = montar()
    await screen.findByText('Cronograma inteiro')
    const futuro = container.querySelector('[data-mes="2027-03"]')
    expect(futuro?.getAttribute('data-estado')).toBe('futuro')
    expect(futuro?.outerHTML).not.toMatch(/tom-(parado|alerta|multiplos|tempoRuim|ok)/)
  })

  it('mês com atraso vence "em andamento" na fita', () => {
    // O DEFEITO: um mês corrente que já acumulou atividade vencida sairia "em andamento" —
    // o eufemismo que faz o cliente descobrir o problema tarde.
    const m: MesDaFita = {
      mes: '2026-09', situacao: 'corrente', previsto: 18, cumprido: 2, atrasadas: 3,
    }
    expect(estadoDoMes(m)).toBe('atraso')
    expect(tomDoEstado('atraso')).toBe('parado')
  })

  it('mês sem previsão não vira "cumprido" só por estar fechado', () => {
    // O DEFEITO: verde num mês em que o contrato não previa nada é cumprimento fabricado.
    const m: MesDaFita = {
      mes: '2026-12', situacao: 'fechado', previsto: 0, cumprido: 0, atrasadas: 0,
    }
    expect(estadoDoMes(m)).toBe('sem-previsao')
    expect(tomDoEstado('sem-previsao')).toBeNull()
    expect(tomDoEstado('futuro')).toBeNull()
  })

  it('sem o recorte do servidor a fita não existe — a tela não classifica mês sozinha', async () => {
    // O DEFEITO: deduzir fechado/corrente/futuro do relógio do navegador. Os meses são os do
    // CONTRATO (este começa em agosto e termina em julho de 2027); adivinhar a âncora aqui
    // apontaria para a coluna errada, que é pior do que não apontar.
    servidor(cronograma({ meses_estado: [] }))
    const { container } = montar()
    await screen.findByText(/ainda não publicou o recorte por mês/)
    expect(container.querySelectorAll('[data-mes]').length).toBe(0)
  })

  /* ---------------------------------------------------------------- o veredito */

  it('sem atrasada, a tela DIZ que está em dia', async () => {
    // O DEFEITO: a tela não respondia a pergunta do cliente em lugar nenhum. Silêncio se lê
    // como "a tela não sabe", e um cartão "13 de 270" se lê como acusação.
    servidor(cronograma())
    montar()
    expect(await screen.findByText('Em dia — nenhuma atividade atrasada')).toBeTruthy()
  })

  it('com atraso, a faixa conta quantas e nomeia a mais antiga', async () => {
    // O DEFEITO: "3 atrasadas" é um número; "a mais antiga é a Termografia, de agosto" é a
    // frase que faz alguém agir. A varredura é por MÊS primeiro — a pergunta é desde quando.
    servidor(
      cronograma({
        // A ordem das linhas é DE PROPÓSITO a inversa da cronológica: a atrasada de setembro
        // vem primeiro na matriz, a de agosto depois. Quem varrer linha a linha (em vez de
        // mês a mês) devolve a de setembro e a faixa mente sobre "desde quando".
        linhas: [
          linha({
            plan_item_id: 10,
            nome: 'Limpeza do quadro',
            grupo: 'CFTV',
            meses: celulas({ '2026-09': { previsto: 1, estado: 'vermelho', atrasado: true } }),
          }),
          linha({
            plan_item_id: 9,
            nome: 'Termografia da subestação',
            meses: celulas({ '2026-08': { previsto: 1, estado: 'vermelho', atrasado: true } }),
          }),
        ],
      }),
    )
    montar()
    expect(await screen.findByText('2 atividades atrasadas')).toBeTruthy()
    const detalhe = screen.getByText(/A mais antiga é/)
    expect(detalhe.textContent).toContain('Termografia da subestação')
    expect(detalhe.textContent).toContain('Agosto de 2026')
    expect(detalhe.textContent).not.toContain('Limpeza do quadro')
    expect(detalhe.textContent).not.toContain('Setembro de 2026')
    expect(screen.queryByText('Em dia — nenhuma atividade atrasada')).toBeNull()
  })

  /* ---------------------------------------------------------------- o número grande */

  it('o número grande é o "até aqui", com o total do contrato só como contexto', async () => {
    // O DEFEITO que custou caro: dividir por um ano que ainda não aconteceu. A mesma usina,
    // sem uma única atividade atrasada, aparecia como "13 de 270" (4,8 %) numa tela e
    // "41,9 %" na outra. O 270 continua na tela — mas como contexto, nunca como denominador.
    servidor(cronograma())
    montar()
    expect(await screen.findByText('13 de 13')).toBeTruthy()
    expect(screen.getByText('Atividades cumpridas até aqui')).toBeTruthy()
    expect(screen.getByText(/previstas no contrato/).textContent).toContain('270')
    expect(screen.queryByText('13 de 270')).toBeNull()
  })

  it('sem recorte publicado o número responde pela MATRIZ — e o rótulo troca junto', async () => {
    // O DEFEITO que o dono viu: com 94 linhas, 269 células e 13 X verdes já na resposta, o
    // cartão escrevia um travessão. Travessão é para ausência de dado, não para dado que
    // ainda não foi resumido pelo servidor.
    //
    // E a metade que impede a troca de virar uma segunda mentira: "13 de 269" responde a
    // OUTRA pergunta que "13 de 31" (o ano inteiro × o que já venceu), então o RÓTULO muda
    // com o número e a tela escreve que a conta inclui mês que nem venceu. Nenhum percentual
    // é impresso aqui — inventá-lo daria a terceira resposta.
    servidor(
      cronograma({ cumprido_ate_hoje: null, previsto_ate_hoje: null, pct_ate_hoje: null }),
    )
    const { container } = montar()
    await screen.findByText('Cronograma inteiro')

    expect(screen.getByText('13 de 269')).toBeTruthy()
    expect(screen.getByText('Atividades cumpridas no ano')).toBeTruthy()
    expect(screen.queryByText('Atividades cumpridas até aqui')).toBeNull()
    expect(container.textContent).toContain('ainda nem venceram')
    expect(screen.queryByText('0 de 0')).toBeNull()
  })

  it('com o recorte publicado, o número grande é o do SERVIDOR — nunca a soma da matriz', async () => {
    // O outro lado da regra acima: publicado o recorte, quem manda é ele. Se a tela caísse
    // na matriz por descuido, "13 de 31" viraria "13 de 269" e o cliente leria 4,8 % onde o
    // Relatório de manutenção do meuPlano diz 41,9 %.
    servidor(cronograma({ previsto_ate_hoje: 31, cumprido_ate_hoje: 13, pct_ate_hoje: 41.9 }))
    montar()
    await screen.findByText('Cronograma inteiro')

    expect(screen.getByText('13 de 31')).toBeTruthy()
    expect(screen.getByText('Atividades cumpridas até aqui')).toBeTruthy()
    expect(screen.queryByText('13 de 269')).toBeNull()
  })

  /* ---------------------------------------------------------------- as listas do mês */

  it('as duas listas do mês saem no mês que o SERVIDOR indicou', async () => {
    // O DEFEITO: usar o relógio do navegador para achar "este mês". Num contrato ancorado em
    // agosto de 2026 isso aponta para a coluna errada — e o cliente lê a lista de outro mês.
    servidor(cronograma())
    montar()
    expect(await screen.findByText('Previsto para Setembro de 2026')).toBeTruthy()
    expect(screen.getByText('Feito em Setembro de 2026')).toBeTruthy()
    // As duas atividades previstas para setembro aparecem pelo nome, sem abrir nada. Vale
    // `getAllByText` porque a matriz agora nasce aberta e o mesmo nome está lá embaixo — o
    // que este teste guarda é a LISTA responder pelo mês do servidor, não a unicidade.
    expect(screen.getAllByText('Medição do TTR').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Limpeza do quadro').length).toBeGreaterThan(0)
  })

  it('lista vazia diz POR QUE está vazia', async () => {
    // O DEFEITO: espaço em branco no lugar da lista se lê como falha da tela. "Nada previsto
    // para este mês" é uma resposta legítima do contrato e precisa estar escrita.
    servidor(cronograma())
    montar()
    expect(await screen.findByText(/Nada registrado neste mês ainda/)).toBeTruthy()
  })

  it('dispensada aparece nas feitas, mas com a palavra "dispensada" escrita', async () => {
    // O DEFEITO: fundir executado com dispensado faria o cliente ler "houve visita" onde a
    // equipe registrou "não precisou desta vez". Ela conta como cumprida e é rotulada.
    servidor(cronograma({ mes_referencia: '2026-08' }))
    montar()
    expect(await screen.findByText('Feito em Agosto de 2026')).toBeTruthy()
    expect(screen.getByText(/dispensada com motivo/)).toBeTruthy()
  })

  /* ---------------------------------------------------------------- a cor */

  it('"prevista" não usa o tom de perda climática', async () => {
    // O DEFEITO: `cell_status = 'azul'` virava `tempoRuim`, que neste produto significa UMA
    // coisa — perda por clima — e é lido assim nas telas de energia, no app e no painel.
    // Uma atividade que ainda não venceu é ausência de fato, e ausência tem cor neutra.
    expect(tomDaCelula({ mes: '2026-09', ...VAZIA, previsto: 1, estado: 'azul' })).not.toBe(
      'tempoRuim',
    )
    servidor(cronograma())
    const { container } = montar()
    await abrirMatriz()
    expect(container.querySelector('.bg-tom-tempoRuim')).toBeNull()
    expect(container.querySelector('.text-tom-tempoRuim')).toBeNull()
    expect(container.querySelector('.border-tom-tempoRuim\\/30')).toBeNull()
  })

  it('o cabeçalho de bloco da matriz usa o token puro, não o alfa trocado', async () => {
    // O DEFEITO: o token `bg-superficie-alta` com um modificador de opacidade emite
    // `rgba(255,255,255,0.4)` — o modificador SUBSTITUI o alfa do token em vez de
    // multiplicá-lo. Era cinco vezes o alfa declarado (0,08) e mais de três vezes o da
    // superfície mais clara do design system (0,12): o "cinza que horrível". A asserção
    // abaixo recusa QUALQUER modificador na faixa; `scripts/regra0.mjs` recusa no repo
    // inteiro, e é por isso que nem este comentário pode escrever a classe por extenso.
    servidor(cronograma())
    const { container } = montar()
    await abrirMatriz()
    const faixas = Array.from(container.querySelectorAll('tr')).filter((tr) =>
      tr.className.includes('bg-superficie-alta'),
    )
    expect(faixas.length).toBeGreaterThan(0)
    for (const tr of faixas) expect(tr.className).not.toContain('bg-superficie-alta/')
  })

  /* ---------------------------------------------------------------- o que já valia */

  it('o bloco COM movimento abre sozinho; o bloco parado continua recolhido', async () => {
    // As duas metades da mesma regra. O DEFEITO original era despejar 94 linhas de ensaio de
    // uma vez — a análise de equipamento que o cliente disse não querer —, e por isso o
    // agrupamento fica. O DEFEITO novo era o oposto: quinze cabeçalhos cinza fechados sobre
    // doze colunas vazias, escondendo justamente as linhas que respondem "o que foi feito?".
    // Quem tem execução, dispensa ou atraso abre; quem está parado é contexto e espera.
    servidor(
      cronograma({
        linhas: [
          linha({}),
          linha({
            plan_item_id: 9,
            nome: 'Roçada do pátio',
            grupo: 'Depósito',
            feitos: 0,
            meses: celulas({ '2027-03': { previsto: 1, estado: 'azul' } }),
          }),
        ],
      }),
    )
    const { container } = montar()
    await abrirMatriz()
    const tabela = container.querySelector('table')
    expect(tabela?.textContent).toContain('Subestação')
    expect(tabela?.textContent).toContain('Depósito')

    // Subestação tem um X verde: abre sozinha, e o nome da atividade está à vista.
    expect(tabela?.textContent).toContain('Medição do TTR')
    // Depósito não tem nada feito, dispensado nem atrasado: continua recolhido.
    expect(tabela?.textContent).not.toContain('Roçada do pátio')

    const bloco = Array.from(tabela?.querySelectorAll('button') ?? []).find((b) =>
      b.textContent?.includes('Depósito'),
    )
    bloco?.click()
    await waitFor(() =>
      expect(container.querySelector('table')?.textContent).toContain('Roçada do pátio'),
    )
  })

  it('mostra o selo e a periodicidade que o servidor traduziu, nunca o código cru', async () => {
    // O DEFEITO: "INSPECAO", "ensaio" e "6/MONTH" chegavam à tela de um cliente corporativo.
    servidor(cronograma({ linhas: [linha({})] }))
    montar()
    await abrirMatriz()
    const rodape = screen.getByText(/Ensaio/)
    expect(rodape.textContent).toContain('Semestral')
    expect(rodape.textContent).not.toContain('MONTH')
    expect(rodape.textContent).not.toContain('INSPECAO')
  })

  it('sem PDF disponível o botão não aparece — botão que só erra é ruído', async () => {
    servidor(cronograma({ pdf_disponivel: false }))
    montar()
    await screen.findByText('Cronograma inteiro')
    expect(screen.queryByText('PDF')).toBeNull()
  })

  it('com PDF disponível o botão aparece', async () => {
    servidor(cronograma())
    montar()
    expect(await screen.findByText('PDF')).toBeTruthy()
  })

  it('sem cronograma publicado a tela repete a frase do servidor, e não desenha grade', async () => {
    // O DEFEITO: grade em branco se lê como "nada foi feito", que é uma acusação — e não é o
    // que o dado diz. Quem escreve a frase é o servidor.
    servidor(
      cronograma({
        status: null,
        linhas: [],
        meses_estado: [],
        aviso: 'A equipe ainda não publicou o cronograma consolidado deste contrato.',
      }),
    )
    const { container } = montar()
    expect(await screen.findByText('Cronograma ainda não publicado')).toBeTruthy()
    expect(container.querySelectorAll('td').length).toBe(0)
    expect(screen.queryByText('Cronograma inteiro')).toBeNull()
  })
})
