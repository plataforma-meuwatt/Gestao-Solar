/**
 * O que estes testes guardam é UMA coisa, e ela foi cobrada com todas as letras: **a tela do
 * portal oferece o que a tela do meuWatt oferece.**
 *
 * O defeito que eles fecham não é um erro de código — é um erro de PRODUTO, e por isso nenhum
 * `tsc`, `lint` ou revisão de diff o pegaria. A versão anterior desta página carregava o
 * contrato inteiro (as quatro variáveis de inversor, os dois agrupamentos, `series[]`) e
 * escondia tudo atrás de uma gaveta chamada "Escolher coluna por coluna", com cinco pacotes na
 * frente. Baixar por skid — o pedido literal do dono — exigia saber que a gaveta existia,
 * abri-la, trocar o agrupamento e marcar inversor por inversor. A capacidade estava presente e
 * praticamente ausente, e o diff que a poda produz é *menor*, não maior: ninguém apaga uma
 * linha e escreve "cortei uma variável do cliente" ao lado.
 *
 * Daí a régua destes testes ser NUMÉRICA, e não editorial:
 *
 * 1. **Os quatro cartões existem SEMPRE** — inclusive o do bloco que a usina não tem, e nesse
 *    caso com o motivo escrito. Cartão que some leva embora a única informação que interessa a
 *    quem está avaliando o que contratar.
 * 2. **As 14 linhas de variável estão na tela** (4 inversor + 7 estação + 1 fronteira + 2
 *    sistema), conferidas contra `TOTAL_DE_VARIAVEIS` — e `umidade`, que NENHUMA usina tem,
 *    aparece desabilitada com o motivo em vez de sumir. Sumir faria o cliente concluir que o
 *    portal não oferece, quando o fato é sobre o produto.
 * 3. **Os 5 passos e os 2 agrupamentos de cada um dos três blocos que têm agrupamento.**
 * 4. **Os dois horários numa grade de 5 minutos (288 posições)** — a versão anterior usava 15,
 *    o que é uma redução silenciosa —, apagados no total por dia em vez de sumirem.
 * 5. **O seletor de inversores abre AGRUPADO POR SKID**, e um toque no cabeçalho do skid marca
 *    o skid inteiro: o rótulo fechado passa a NOMEÁ-LO, e é essa lista que viaja no pedido.
 * 6. **Não sobrou gaveta nem estado "personalizado"**, e **não há chip**: a varredura é
 *    estrutural (nenhum botão-pílula, e o número de botões do estado fechado não comporta uma
 *    fileira de opções).
 *
 * E, por baixo de tudo: a chave de série (`slot:170`) é TRANSPORTE e não pode aparecer na
 * tela; o que o cliente lê é "Inv 23" com o número de série ao lado.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { OpcoesDeDados } from '@/features/dados/api'
import {
  PASSOS,
  TOTAL_DE_VARIAVEIS,
  VARIAVEIS_DA_ESTACAO,
  VARIAVEIS_DA_FRONTEIRA,
  VARIAVEIS_DO_INVERSOR,
  VARIAVEIS_DO_SISTEMA,
} from '@/features/dados/pacotes'
import BaixarDados from '@/features/dados/Pagina'

// O salvamento do arquivo não é desta tela (é `lib/arquivo`), e o jsdom não tem
// `URL.createObjectURL`. O que se prova aqui é O QUE foi pedido e o que a tela disse.
vi.mock('@/lib/arquivo', () => ({ baixarBlob: vi.fn() }))
import { baixarBlob } from '@/lib/arquivo'

const USINA = 4

/**
 * Porto Ferreira como o `GET /energia/dados/opcoes` a devolveu em 05/09/2026: 20 inversores em
 * **cinco** skids de quatro, cinco leitores, estação que mede só irradiação, relé com
 * temperatura, e `umidade: false` — que é o valor fixo que o servidor manda para toda usina.
 *
 * Os nomes são os do cadastro (`SKID-01`…`SKID-05`), e não "Skid 1": o rótulo que a tela
 * escreve é o que o cliente vai encontrar na coluna do arquivo, e inventar um mais bonito aqui
 * faria o teste passar sobre uma usina que não existe.
 */
function opcoes(parcial: Partial<OpcoesDeDados> = {}): OpcoesDeDados {
  const skids: [string, string[], string[]][] = [
    ['SKID-01', ['slot:170', 'slot:150', 'slot:151', 'slot:152'], ['Inv 13', 'Inv 12', 'Inv 14', 'Inv 11']],
    ['SKID-02', ['slot:153', 'slot:154', 'slot:155', 'slot:156'], ['Inv 23', 'Inv 22', 'Inv 24', 'Inv 21']],
    ['SKID-03', ['slot:157', 'slot:158', 'slot:159', 'slot:160'], ['Inv 33', 'Inv 32', 'Inv 34', 'Inv 31']],
    ['SKID-04', ['slot:161', 'slot:162', 'slot:163', 'slot:164'], ['Inv 43', 'Inv 42', 'Inv 44', 'Inv 41']],
    ['SKID-05', ['slot:166', 'slot:167', 'slot:168', 'slot:169'], ['Inv 52', 'Inv 51', 'Inv 54', 'Inv 53']],
  ]

  return {
    usina: { id: USINA, nome: 'Porto Ferreira', capacidade_kwp: 7402.5 },
    skids: skids.map(([nome, chaves, rotulos], i) => ({
      id: 56 + i,
      nome,
      capacidade_kwp: 1480.5,
      series: chaves.map((chave, j) => ({
        chave,
        rotulo: rotulos[j],
        numero_serie: `GR257904${2000 + i * 10 + j}`,
        capacidade_kwp: 375.06,
      })),
    })),
    estacao: {
      disponivel: true,
      colunas: {
        poa: true,
        ghi: true,
        temp_modulo: false,
        temp_ambiente: false,
        vento: false,
        umidade: false,
      },
      temp_ambiente_rele: true,
    },
    leitores: [
      { id: 14, nome: 'Leitor Concessionaria Porto Ferreira SKID 1' },
      { id: 10, nome: 'Leitor Concessionaria Porto Ferreira SKID 2' },
      { id: 11, nome: 'Leitor Concessionaria Porto Ferreira SKID 3' },
      { id: 12, nome: 'Leitor Concessionaria Porto Ferreira SKID 4' },
      { id: 13, nome: 'Leitor Concessionaria Porto Ferreira SKID 5' },
    ],
    sistema: { pr: true, produtividade: true },
    retencao: { snapshots_desde: '2026-03-06', ssu_desde: '2024-09-05' },
    limites: { native: 7, '5m': 31, '15m': 92, '1h': 366, '1d': 366, max_celulas: 2_000_000 },
    ...parcial,
  }
}

function montar(dados: OpcoesDeDados = opcoes()) {
  vi.spyOn(api, 'get').mockResolvedValue({ data: dados } as never)
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[`/usinas/${USINA}/energia/dados`]}>
        <Routes>
          <Route path="/usinas/:id/energia/dados" element={<BaixarDados />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Uma resposta de `fetch` com corpo de planilha — o bastante para passar do piso de 100 B. */
function planilha(): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'attachment; filename="dados-porto-ferreira-2026-09-5m.xlsx"' },
    blob: async () => new Blob([new Uint8Array(4096)]),
    json: async () => ({}),
  } as unknown as Response
}

async function telaPronta() {
  await screen.findByText('Começar de…')
}

/** Abre a lista suspensa cujo gatilho diz `gatilho`. */
function abrir(gatilho: string | RegExp) {
  fireEvent.click(screen.getByRole('button', { name: gatilho }))
}

/** O cartão de um bloco, pelo título dele. */
function bloco(titulo: string): HTMLElement {
  return screen.getByText(titulo).closest('section') as HTMLElement
}

/**
 * Abre a lista de colunas DAQUELE bloco.
 *
 * Pelo cartão, e não pelo texto do gatilho: "1 de 3 colunas" e "0 de 3 colunas" convivem na
 * mesma tela (a lista conta só o que é escolhível, e o `status` fica de fora fora do passo
 * nativo), então mirar pelo rótulo escolheria o bloco errado no dia em que os números batessem.
 */
function abrirColunas(titulo: string) {
  const campo = within(bloco(titulo)).getByText('Colunas').parentElement as HTMLElement
  fireEvent.click(within(campo).getAllByRole('button')[0])
}

/** Os rótulos das opções da lista suspensa aberta — ela é a única `<ul>` da tela. */
function opcoesAbertas(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('ul > li')).map((li) =>
    (li.textContent ?? '').trim(),
  )
}

describe('Baixar dados — paridade com a tela do meuWatt', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(1)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    // A conta de dias depende do "hoje": sem relógio fixo, o teste passaria hoje e falharia em
    // janeiro, sem nada ter mudado.
    vi.setSystemTime(new Date(2026, 8, 5, 12, 0, 0))
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.mocked(baixarBlob).mockClear()
    limparCache()
  })

  /* ============================================================ 1. os quatro cartões */

  it('os quatro cartões estão na tela — e o bloco que a usina não tem diz por quê', async () => {
    // Uma usina sem estação, sem medidor e sem PR: três dos quatro blocos são impossíveis.
    montar(
      opcoes({
        estacao: { disponivel: false, colunas: {}, temp_ambiente_rele: false },
        leitores: [],
        sistema: { pr: false, produtividade: false },
      }),
    )
    await telaPronta()

    // (1-4) Nenhum cartão some. Cartão ausente é informação perdida sobre o que contratar.
    expect(screen.getByText('Inversores')).toBeTruthy()
    expect(screen.getByText('Estação solarimétrica')).toBeTruthy()
    expect(screen.getByText('Medidor de fronteira')).toBeTruthy()
    expect(screen.getByText('Desempenho do sistema')).toBeTruthy()

    // (5-7) E cada ausência traz o motivo — não um cartão mudo e cinza.
    const semMedidor = screen.getByText(/Não entra: esta usina não tem medidor de fronteira/)
    expect(semMedidor.textContent!.length).toBeGreaterThan(20)
    expect(screen.getByText(/Não entra: esta usina não tem estação solarimétrica/)).toBeTruthy()
    // A cadeia inteira, e não só o último elo: é a diferença entre "o portal quebrou" e "eu
    // sei o que teria de instalar".
    expect(
      screen.getByText(/Não entra: sem estação não há irradiação, e sem irradiação/),
    ).toBeTruthy()

    // (8) Bloco impossível não oferece o "Entra no arquivo": não há o que entrar. Só o dos
    // inversores, que esta usina tem, mantém o par.
    expect(screen.getAllByRole('button', { name: 'Entra no arquivo' })).toHaveLength(1)
  })

  /* ============================================================ 2. as 14 variáveis */

  it('as 14 linhas de variável estão na tela, e a umidade aparece desabilitada', async () => {
    const { container } = montar()
    await telaPronta()

    // (9-10) As quatro do inversor.
    abrirColunas('Inversores')
    const doInversor = opcoesAbertas(container)
    expect(doInversor).toHaveLength(VARIAVEIS_DO_INVERSOR.length)
    for (const v of VARIAVEIS_DO_INVERSOR) {
      expect(doInversor.join(' | '), v.chave).toContain(v.rotulo)
    }
    fireEvent.keyDown(document, { key: 'Escape' })

    // (11-12) As SETE da estação — não as três que esta usina mede.
    abrirColunas('Estação solarimétrica')
    const daEstacao = opcoesAbertas(container)
    expect(daEstacao).toHaveLength(VARIAVEIS_DA_ESTACAO.length)
    for (const v of VARIAVEIS_DA_ESTACAO) {
      expect(daEstacao.join(' | '), v.chave).toContain(v.rotulo)
    }

    // (13-14) A umidade está VISÍVEL e DESABILITADA, com o motivo escrito ao lado. Nenhuma
    // usina a tem; sumir com a linha diria que o portal é que não oferece.
    const umidade = screen.getByRole('checkbox', { name: /Umidade do ar/ })
    expect((umidade as HTMLButtonElement).disabled).toBe(true)
    expect(umidade.textContent).toContain('nenhuma estação envia umidade')
    fireEvent.keyDown(document, { key: 'Escape' })

    // (15-16) As duas do sistema.
    abrirColunas('Desempenho do sistema')
    const doSistema = opcoesAbertas(container)
    expect(doSistema).toHaveLength(VARIAVEIS_DO_SISTEMA.length)
    for (const v of VARIAVEIS_DO_SISTEMA) {
      expect(doSistema.join(' | '), v.chave).toContain(v.rotulo)
    }
    fireEvent.keyDown(document, { key: 'Escape' })

    // (17) A única da fronteira fica escrita na cara: uma lista de uma opção só seria um
    // clique a mais para dizer a mesma coisa.
    expect(screen.getByText(VARIAVEIS_DA_FRONTEIRA[0].rotulo)).toBeTruthy()

    // (18) E a conta fecha contra a régua, que é a fonte única das linhas: se alguém apagar
    // uma "para simplificar", este número desce e o teste reprova.
    expect(TOTAL_DE_VARIAVEIS).toBe(14)
  })

  /* ============================================ 3. os 5 passos e os 3 × 2 agrupamentos */

  it('os cinco passos e os dois agrupamentos de cada um dos três blocos', async () => {
    const { container } = montar()
    await telaPronta()

    // (19-20) Os cinco detalhes, com o teto do servidor colado em cada um.
    abrir('De hora em hora')
    const passos = opcoesAbertas(container)
    expect(passos).toHaveLength(PASSOS.length)
    expect(passos).toHaveLength(5)
    // (21) O teto vem do SERVIDOR, e não de uma constante nossa que envelhece calada.
    expect(passos.join(' | ')).toContain('até 7 dias por arquivo')
    fireEvent.keyDown(document, { key: 'Escape' })

    // (22-27) Os dois agrupamentos de cada bloco, à vista — nenhum atrás de gaveta.
    expect(screen.getByRole('button', { name: 'Uma coluna por inversor' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Uma coluna por skid' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Uma coluna por leitor' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Só o total da usina' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Da usina inteira' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'De cada skid' })).toBeTruthy()
  })

  /* ============================================================ 4. os dois horários */

  it('os dois horários têm grade de 5 minutos, e o total por dia os apaga em vez de sumir', async () => {
    const { container } = montar()
    await telaPronta()

    // (28-29) 288 posições de cinco em cinco minutos (24 × 60 ÷ 5) — a tela anterior usava 15,
    // e quem quer das 07:35 às 17:20 não conseguia pedir. A 289ª é `23:59`, que existe porque
    // o horário final é inclusivo do minuto: parar em 23:55 perderia o fim do dia.
    abrir('00:00')
    const inicio = opcoesAbertas(container)
    expect(inicio.filter((t) => /^\d\d:\d\d$/.test(t))).toHaveLength(288)
    expect(inicio.join(' | ')).toContain('07:35')
    // (30) E o fim do dia continua alcançável, com o porquê escrito.
    expect(inicio.join(' | ')).toContain('até o fim do dia')
    fireEvent.keyDown(document, { key: 'Escape' })

    // (31) A mesma grade no horário final.
    abrir('23:59')
    expect(opcoesAbertas(container).filter((t) => /^\d\d:\d\d$/.test(t))).toHaveLength(288)
    fireEvent.keyDown(document, { key: 'Escape' })

    // (32-34) No total por dia o horário não se aplica — e sai do alcance sem sair da tela:
    // apagá-lo diz "existe, mas não agora"; removê-lo faria a pessoa procurar onde foi parar.
    abrir('De hora em hora')
    fireEvent.click(screen.getByRole('button', { name: /Um total por dia/ }))
    const apagado = container.querySelector('[title="No total por dia o horário não se aplica"]')
    expect(apagado).not.toBeNull()
    expect(apagado!.className).toContain('opacity-40')
    expect(apagado!.className).toContain('pointer-events-none')
    expect(screen.getByText(/não usa horário: cada linha é o dia inteiro/)).toBeTruthy()
  })

  /* ============================================================ 5. o skid */

  it('o seletor abre por skid, e um toque no cabeçalho do SKID-02 baixa o skid inteiro', async () => {
    const buscar = vi.fn().mockResolvedValue(planilha())
    vi.stubGlobal('fetch', buscar)
    const { container } = montar()
    await telaPronta()

    // (35) Ele abre AGRUPADO: um cabeçalho por skid, e cada um é um controle de três estados —
    // não um título. É o gesto que faltava e que motivou o pedido do dono.
    abrir('todos · 20 inversores')
    const cabecalhos = screen
      .getAllByRole('checkbox')
      .filter((b) => /^SKID-\d\d —/.test(b.getAttribute('aria-label') ?? ''))
    expect(cabecalhos).toHaveLength(5)

    // (36) O nome acessível diz quantos estão marcados E o que o toque vai fazer.
    expect(
      screen.getByRole('checkbox', { name: /^SKID-02 —/ }).getAttribute('aria-checked'),
    ).toBe('true')

    // Limpar tudo e marcar só o SKID-02: dois toques para o que antes eram vinte.
    fireEvent.click(screen.getByRole('button', { name: 'Limpar' }))
    fireEvent.click(screen.getByRole('checkbox', { name: /^SKID-02 —/ }))

    // (37) O rótulo fechado NOMEIA o skid: "4 de 20" não diz o que a pessoa acabou de pedir.
    expect(screen.getByRole('button', { name: /SKID-02 · 4 inversores/ })).toBeTruthy()

    // (38-40) A chave de série é transporte e não aparece em lugar nenhum — o que se lê é o
    // rótulo do inversor com o número de série ao lado, que é o que a pessoa tem na mão.
    expect(container.textContent).not.toContain('slot:')
    expect(screen.getByText('Inv 23')).toBeTruthy()
    expect(screen.getByText(/GR2579042010/)).toBeTruthy()

    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Uma coluna por skid' }))

    // (41) E a frase que o arquivo exige: a coluna continua se chamando "SKID-02" mesmo
    // somando menos inversores do que o skid tem.
    expect(screen.getByText(/o que você desmarcar também sai da soma do skid/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await waitFor(() => expect(buscar).toHaveBeenCalledTimes(1))

    // (42-43) E é essa seleção que viaja: quatro séries, agrupadas por skid.
    const corpo = JSON.parse(String((buscar.mock.calls[0][1] as RequestInit).body))
    expect(corpo.inversores.agrupamento).toBe('skid')
    expect(corpo.inversores.series).toEqual(['slot:153', 'slot:154', 'slot:155', 'slot:156'])
  })

  /* ============================================ 6. sem gaveta, sem "personalizado", sem chip */

  it('não sobrou gaveta nem estado "personalizado", e nenhuma escolha virou chip', async () => {
    const { container } = montar()
    await telaPronta()

    // (44-46) As palavras da versão anterior não existem mais na tela. Elas nomeavam a gaveta
    // e o estado que só servia para administrar a mentira de continuar dizendo "Geração da
    // usina" depois que o cliente mexia.
    expect(container.textContent).not.toMatch(/avan[çc]ado/i)
    expect(container.textContent).not.toMatch(/personalizado/i)
    expect(container.textContent).not.toMatch(/coluna por coluna/i)

    // (47) Chip é botão-pílula: proibido em todo o portal, e é exatamente a forma que a tela
    // do meuWatt usa. A varredura é estrutural, e não uma leitura de estilo.
    expect(container.querySelectorAll('[class*="rounded-full"]')).toHaveLength(0)

    // (48) E a contagem fecha o resto: uma fileira de chips para as 14 variáveis, os 5 passos,
    // os 27 atalhos e os 20 inversores passaria de sessenta botões só de opção. Com tudo
    // fechado, o que existe são os gatilhos das listas, os segmentados e os botões de ação.
    expect(container.querySelectorAll('button').length).toBeLessThan(45)

    // (49) …e mesmo assim as 20 séries continuam alcançáveis, dentro da lista suspensa.
    abrir('todos · 20 inversores')
    expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(20)
  })

  /* ============================================================ 7. o atalho preenche */

  it('o pacote PREENCHE os blocos e volta ao lugar — atalho, não modo', async () => {
    montar()
    await telaPronta()

    // (50) Abre com geração: os quatro blocos oferecem o par (esta usina tem todos), e só o
    // dos inversores está ligado — a estação ainda não entra no arquivo.
    expect(screen.getAllByRole('button', { name: 'Entra no arquivo' })).toHaveLength(4)
    expect(within(bloco('Estação solarimétrica')).getByRole('button', { name: /0 de 3 colunas/ })).toBeTruthy()

    abrir('Preencher os blocos com um começo pronto…')
    fireEvent.click(screen.getByRole('button', { name: /Geração \+ clima/ }))

    // (51) Ele preencheu os blocos À VISTA: a estação passou a entrar no arquivo (irradiação
    // nos dois planos, que é o que esta usina mede).
    expect(
      within(bloco('Estação solarimétrica')).getByRole('button', { name: '2 de 3 colunas' }),
    ).toBeTruthy()
    // (52) …e o gatilho voltou ao lugar, em vez de virar um rótulo de modo.
    expect(
      screen.getByRole('button', { name: 'Preencher os blocos com um começo pronto…' }),
    ).toBeTruthy()
    // (53) O rastro diz de onde veio…
    expect(screen.getByText(/Blocos preenchidos a partir de/)).toBeTruthy()

    // (54) …e some assim que o cliente mexe, porque o atalho preencheu e não governa.
    fireEvent.click(screen.getByRole('button', { name: 'Uma coluna por skid' }))
    expect(screen.queryByText(/Blocos preenchidos a partir de/)).toBeNull()
  })

  /* ============================================================ 8. o passo se anuncia */

  it('o auto-ajuste do passo ANUNCIA que ajustou, em vez de trocar em silêncio', async () => {
    montar()
    await telaPronta()

    // "Cada leitura" aceita 7 dias. Pedir o ano corrente (248 dias) obriga a engrossar.
    abrir('De hora em hora')
    fireEvent.click(screen.getByRole('button', { name: /Cada leitura/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Ano' }))

    // (55-57) A frase diz o número, o detalhe que não coube e o que foi escolhido no lugar.
    // Sem ela, o cliente descobre a troca ao abrir a planilha e achar uma linha por dia.
    const aviso = screen.getByText(/Ajustei para/)
    expect(aviso.textContent).toContain('248 dias')
    expect(aviso.textContent).toContain('aceita 7')
  })

  /* ============================================================ 9. o rodapé e o rastro */

  it('o rodapé conta o arquivo ABA POR ABA e o sucesso deixa rastro', async () => {
    const buscar = vi.fn().mockResolvedValue(planilha())
    vi.stubGlobal('fetch', buscar)
    montar()
    await telaPronta()

    // (58-60) A estimativa é uma conta aproximada — daí o "≈" — e vem com a legenda que evita
    // a leitura errada mais cara que este arquivo induz.
    //
    // ⛔ E ela é POR ABA. Somar as larguras dava um número que não é a largura de nada: os
    // juízes abriram a planilha e acharam 42 colunas em 4 abas onde o rodapé prometia 37, e
    // a aba mais larga tinha 22. Agora cada aba diz a sua, contando o `Início (BRT)`.
    const rodape = screen.getByText(/linhas ·/)
    expect(rodape.textContent).toContain('≈')
    expect(rodape.textContent).toContain('vazio = sem leitura, 0 = zero medido')
    expect(rodape.textContent).not.toContain('Paradas')
    // O padrão da tela é a usina inteira: 20 inversores + Usina + Início = 22 (medido).
    expect(rodape.textContent).toMatch(/Inversores\s*22 colunas/)

    // (61) Marcar "Intervalos desligados" acrescenta uma ABA ao arquivo — e ela não tem
    // número de linhas para dar, então o rodapé diz o que ela é em vez de inventar um.
    abrirColunas('Inversores')
    fireEvent.click(screen.getByRole('checkbox', { name: /Intervalos desligados/ }))
    fireEvent.keyDown(document, { key: 'Escape' })
    const comParadas = screen.getByText(/linhas ·/).textContent ?? ''
    expect(comParadas).toContain('Paradas (uma linha por parada no período)')
    // E a aba de inversores engordou uma coluna por inversor, mais o total da usina.
    expect(comParadas).toMatch(/Inversores\s*43 colunas/)

    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await waitFor(() => expect(vi.mocked(baixarBlob)).toHaveBeenCalledTimes(1))

    // (62-64) O sucesso deixa rastro com o nome e o tamanho: sem ele, um download que o
    // navegador guardou em silêncio parece um botão que não fez nada.
    const pronto = await screen.findByText(/Pronto:/)
    expect(pronto.textContent).toContain('dados-porto-ferreira-2026-09-5m.xlsx')
    expect(pronto.textContent).toContain('4 KB')
    expect(pronto.textContent).toContain('pasta de downloads')
  })

  it('erro permanente não oferece "Tentar de novo"; falha de ponte oferece', async () => {
    // DEFEITO QUE ESTE TESTE GUARDA: o 422 do Pydantic (`passo` fora da lista, data em
    // formato de gente, mais de 500 séries) sai CRU, sem o `motivo` do vocabulário fechado —
    // e o botão convidava a repetir um corpo que dará o mesmo 422 para sempre. Repetir não é
    // de graça: o balde do meuWatt é de 10/minuto para o IP inteiro do portal.
    const recusa = (status: number): Response =>
      ({
        ok: false,
        status,
        headers: { get: () => null },
        blob: async () => new Blob(),
        json: async () => ({ detail: 'passo: Input should be…' }),
      }) as unknown as Response

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(recusa(422)))
    montar()
    await telaPronta()
    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await screen.findByText('Não deu para carregar')
    expect(screen.queryByRole('button', { name: 'Tentar de novo' })).toBeNull()

    // E a ponte fora do ar continua com botão: aí repetir é exatamente a coisa certa.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(recusa(502)))
    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeTruthy(),
    )
  })

  /* ============================================================ 10. a espera */

  it('a espera não inventa porcentagem, diz que sair cancela, e cancelar CALA', async () => {
    // A rota do meuWatt é síncrona: o cabeçalho só chega com o XLSX inteiro montado (35,6 s
    // medidos no pior pedido que ele aceita), e não há job nem endpoint de andamento. Este
    // `fetch` que nunca resolve é exatamente essa situação, parada no tempo.
    let abortado = false
    const buscar = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolver, rejeitar) => {
          init.signal?.addEventListener('abort', () => {
            abortado = true
            rejeitar(new DOMException('abort', 'AbortError'))
          })
        }),
    )
    vi.stubGlobal('fetch', buscar)
    montar()
    await telaPronta()

    fireEvent.click(screen.getByRole('button', { name: 'Baixar planilha' }))
    const caixa = await screen.findByRole('dialog')

    // (65) O tempo DECORRIDO é fato; uma porcentagem seria ficção, porque não há progresso
    // para ler — o arquivo desce de uma vez, quando fica pronto.
    expect(caixa.textContent).toContain('Gerando há')
    // (66) A prova de que ninguém inventou os "43 %".
    expect(caixa.textContent).not.toMatch(/\d+\s?%/)
    // (67) E o aviso nomeia o gesto PROVÁVEL: não é fechar a aba, é clicar no menu ali à
    // esquerda — que mata o `fetch` do mesmo jeito, e sem isso se descobre depois.
    expect(caixa.textContent).toContain('Sair desta tela')

    // (68-70) Cancelar aborta de verdade, fecha a espera — e CALA: ninguém errou, e um aviso
    // vermelho aqui acusaria o cliente de um problema que ele mesmo resolveu.
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(abortado).toBe(true))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.queryByText(/Não deu para/)).toBeNull()
    expect(screen.queryByText(/Pronto:/)).toBeNull()
    expect(vi.mocked(baixarBlob)).not.toHaveBeenCalled()
  })

  /* ============================================================ 11. a retenção */

  it('a retenção é ausência de dado e mora no período, com a saída nomeada', async () => {
    montar()
    await telaPronta()

    // (65-66) A linha é permanente e troca com a seleção: o medidor guarda 24 meses, os
    // inversores e a estação guardam 6. Uma frase só seria falsa metade do tempo.
    const linha = screen.getByText(/Leitura fina de inversores e estação desde/)
    expect(linha.textContent).toContain('06/03/2026')
    expect(linha.textContent).toContain('só o total por dia')

    // (67) E o total por dia realmente não tem prazo — o servidor põe a checagem inteira de
    // retenção dentro de `step != '1d'`. É a saída que todas as frases nomeiam.
    abrir('De hora em hora')
    fireEvent.click(screen.getByRole('button', { name: /Um total por dia/ }))
    expect(screen.getByText(/O total por dia não tem prazo/)).toBeTruthy()
  })

  /* ============================================================ 12. "Ir para…" */

  it('os três atalhos e os 24 meses fechados cabem numa lista suspensa, com a retenção colada', async () => {
    const { container } = montar()
    await telaPronta()

    // (68-69) A lista absorve o que no meuWatt são quatro controles (três botões e um
    // `select`) — e é a única peça do vocabulário do portal que segura 27 opções sem chip.
    abrir('Ir para…')
    const itens = opcoesAbertas(container)
    expect(itens).toHaveLength(27)
    expect(itens.join(' | ')).toContain('Últimos 7 dias')
    // (70) O motivo da retenção viaja colado no mês, enquanto se escolhe — não depois de
    // esperar meio minuto por um 400.
    expect(itens.join(' | ')).toContain('a leitura minuto a minuto não existe mais')

    // (71) E escolher um mês fechado leva o período inteiro dele.
    fireEvent.click(screen.getByRole('button', { name: /^Agosto de 2026/ }))
    expect(screen.getByText(/31 dias, de/)).toBeTruthy()
  })

  /* ============================================================ 13. o 404 */

  it('o 404 não vira diagnóstico sobre a usina: quem escreve a frase é o servidor', async () => {
    // Este caso saiu de uma conferência no navegador, não da imaginação: o BFF que rodava na
    // máquina era um processo antigo, sem a rota nova, e respondeu o "Not Found" padrão do
    // FastAPI. A tela, que afirmava por conta própria "esta usina não está ligada ao
    // monitoramento", disse isso de Porto Ferreira — que está ligada. Um 404 tem três causas
    // (fora do escopo, sem vínculo, rota que não subiu) e a tela não sabe qual é.
    const naoEncontrado = {
      isAxiosError: true,
      response: { status: 404, data: { detail: 'Not Found' } },
    }
    vi.spyOn(api, 'get').mockRejectedValue(naoEncontrado as never)
    const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={cliente}>
        <MemoryRouter initialEntries={[`/usinas/${USINA}/energia/dados`]}>
          <Routes>
            <Route path="/usinas/:id/energia/dados" element={<BaixarDados />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    // `useLeitura` tenta de novo UMA vez antes de desistir (e o atraso é real): sem folga no
    // prazo, o que se lê aqui é o esqueleto, e não a recusa.
    const vazio = await screen.findByText(
      'Não há dados brutos para baixar nesta usina',
      {},
      { timeout: 5000 },
    )
    // (72) A frase é a DO SERVIDOR.
    expect(within(vazio.parentElement!).getByText('Not Found')).toBeTruthy()
    // (73) E a afirmação que a tela NÃO pode fazer sozinha continua não sendo feita.
    expect(screen.queryByText(/não está ligada ao monitoramento/)).toBeNull()
  })
})
