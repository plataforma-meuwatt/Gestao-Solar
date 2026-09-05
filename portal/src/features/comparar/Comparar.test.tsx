/**
 * Os dois comparativos de carteira — e os defeitos que cada teste guarda.
 *
 * Comparar usinas é a tela mais fácil de mentir do portal inteiro, porque toda mentira aqui
 * tem cara de número: uma usina que entrou em operação em maio, comparada com uma que mede
 * desde janeiro, "gera menos"; uma usina sem PR cadastrado, ordenada como zero, "tem o pior
 * PR da carteira"; um percentual de cumprimento sem denominador vira "41,9 %" numa tela e
 * "13 de 270" na outra — que foi exatamente o que aconteceu nesta semana.
 *
 * O que os testes daqui protegem, em uma frase cada:
 *
 * 1. **A ordem é a do servidor.** O ranking de energia é por `energia_comparavel_kwh` (só os
 *    meses da janela comum) e a tabela mostra `energia_kwh` (o período pedido) — os dois
 *    números são diferentes de propósito. Se a tela ordenasse pela coluna que desenha, o
 *    pódio publicado e a lista discordariam na mesma tela, sem nada quebrar.
 * 2. **Ausência nunca é zero.** A usina sem PR sai do ranking de PR, aparece com travessão e
 *    é nomeada na lista de fora, com o motivo. Nenhum "0,0 %" para ela em lugar nenhum.
 * 3. **O total é o do servidor.** A tela não soma coluna: somar aqui daria a segunda resposta
 *    para a mesma pergunta, que é a lição mais cara deste projeto.
 * 4. **O rodapé é fixo e NOMEIA quem encolheu a janela.** Sem o nome, o cliente lê "mai a set"
 *    e conclui que o portal perdeu dados.
 * 5. **Todo percentual sai com o denominador ao lado**, e usina sem cronograma fica fora dos
 *    totais — cujo cabeçalho diz de quantas usinas fala.
 * 6. **Dispensado nunca funde com feito.**
 * 7. **O período viaja na URL e vira `de`/`ate` de mês ou ano inteiro** — nunca "hoje", que
 *    faria uma chave de cache por dia de consulta e sete `miss` a cada abertura.
 * 8. **Nada de chip.** A escolha da régua é uma lista suspensa; uma fileira de botões
 *    mostraria as três opções ao mesmo tempo, e é isso que o teste procura.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '@/App'
import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import { useAuth, type Usuario } from '@/store/auth'
import CompararEnergia from '@/features/comparar/Energia'
import CompararManutencao from '@/features/comparar/Manutencao'
import type {
  ComparativoOut,
  JanelaOut,
  RankingOut,
  UsinaEnergiaOut,
  UsinaManutencaoOut,
} from '@/features/comparar/api'

/* ------------------------------------------------------------------ cenário */

/**
 * A janela é INCOMPLETA de propósito em quase todo o arquivo.
 *
 * Uma carteira real quase nunca tem sete usinas medindo os mesmos doze meses — e é justamente
 * no caso incompleto que a tela precisa dizer de que recorte está falando.
 */
const JANELA: JanelaOut = {
  de: '2026-01-01',
  ate: '2026-09-05',
  meses: [
    '2026-01', '2026-02', '2026-03', '2026-04',
    '2026-05', '2026-06', '2026-07', '2026-08', '2026-09',
  ],
  meses_comuns: ['2026-05', '2026-06', '2026-07', '2026-08', '2026-09'],
  rotulo: 'mai a set de 2026',
  completa: false,
  encolhida_por: ['Porto Ferreira'],
  fora_da_comparacao: ['Marília'],
  sem_detalhe: [],
  comparaveis: 6,
  cobertura_conferida: true,
  nota: 'A comparação usa 5 dos 9 meses do período — os únicos medidos por todas.',
  truncada_em_hoje: true,
}

/** Uma usina de energia. `energia_kwh` = capacidade × produtividade, para o cenário fechar. */
function usinaE(parcial: Partial<UsinaEnergiaOut> & { id: number; nome: string }): UsinaEnergiaOut {
  return {
    cidade: null,
    uf: null,
    capacidade_kwp: null,
    energia_kwh: null,
    energia_comparavel_kwh: null,
    produtividade_kwh_kwp: null,
    pr_pct: null,
    disponibilidade_real_pct: null,
    disponibilidade_contratual_pct: null,
    perdas_paradas_kwh: null,
    irradiacao_hpoa: null,
    irradiacao_ghi: null,
    paradas_pendentes: null,
    meses_medidos: [],
    motivo: null,
    ...parcial,
  }
}

const USINAS_E: UsinaEnergiaOut[] = [
  usinaE({
    id: 1, nome: 'Pirapozinho', cidade: 'Pirapozinho', uf: 'SP',
    capacidade_kwp: 1000, energia_kwh: 450000, energia_comparavel_kwh: 200000,
    produtividade_kwh_kwp: 450, pr_pct: 83.5,
    disponibilidade_real_pct: 99.1, disponibilidade_contratual_pct: 99.6,
    perdas_paradas_kwh: 4100, irradiacao_hpoa: 1180.4, irradiacao_ghi: 1090.2,
  }),
  usinaE({
    id: 2, nome: 'Porto Ferreira', cidade: 'Descalvado', uf: 'SP',
    capacidade_kwp: 300, energia_kwh: 128040, energia_comparavel_kwh: 40000,
    produtividade_kwh_kwp: 426.8, pr_pct: 82.1,
    disponibilidade_real_pct: 98.4, disponibilidade_contratual_pct: 99.2,
    perdas_paradas_kwh: 2000, irradiacao_hpoa: 1160.0, irradiacao_ghi: 1070.0,
    paradas_pendentes: 3,
  }),
  usinaE({
    id: 3, nome: 'Ibitinga', cidade: 'Ibitinga', uf: 'SP',
    capacidade_kwp: 500, energia_kwh: 200000, energia_comparavel_kwh: 150000,
    produtividade_kwh_kwp: 400, pr_pct: 80,
    disponibilidade_real_pct: 97.8, disponibilidade_contratual_pct: 98.9,
    perdas_paradas_kwh: 5000, irradiacao_hpoa: 1150.0, irradiacao_ghi: 1060.0,
  }),
  usinaE({
    id: 4, nome: 'Bauru', cidade: 'Bauru', uf: 'SP',
    capacidade_kwp: 400, energia_kwh: 160000, energia_comparavel_kwh: 120000,
    produtividade_kwh_kwp: 400, pr_pct: 79.5,
    disponibilidade_real_pct: 99, disponibilidade_contratual_pct: 99.4,
    perdas_paradas_kwh: 1200, irradiacao_hpoa: 1145.0, irradiacao_ghi: 1055.0,
  }),
  // A usina SEM PR: mede energia, mas o período não tem irradiância. O upstream devolveria
  // `0.0` de PR por construção, e é aqui que o portal recusa transformar isso em ranking.
  usinaE({
    id: 5, nome: 'Descalvado', cidade: 'Descalvado', uf: 'SP',
    capacidade_kwp: 250, energia_kwh: 97500, energia_comparavel_kwh: 90000,
    produtividade_kwh_kwp: 390, pr_pct: null,
    disponibilidade_real_pct: 98.2, disponibilidade_contratual_pct: 98.7,
    perdas_paradas_kwh: 800, irradiacao_hpoa: null, irradiacao_ghi: null,
  }),
  usinaE({
    id: 6, nome: 'Itápolis', cidade: 'Itápolis', uf: 'SP',
    capacidade_kwp: 800, energia_kwh: 300000, energia_comparavel_kwh: 250000,
    produtividade_kwh_kwp: 375, pr_pct: 78,
    disponibilidade_real_pct: 96.5, disponibilidade_contratual_pct: 98,
    perdas_paradas_kwh: 9000, irradiacao_hpoa: 1130.0, irradiacao_ghi: 1040.0,
  }),
  // A sétima: sem monitoramento. Continua na lista, com o motivo — nunca com zero.
  usinaE({
    id: 7, nome: 'Marília', cidade: 'Marília', uf: 'SP',
    motivo: 'Esta usina não está ligada ao monitoramento.',
  }),
]

/** Σ do PERÍODO PEDIDO — a linha secundária do cartão, nunca a manchete. */
const SOMA_DA_COLUNA = USINAS_E.reduce((t, u) => t + (u.energia_kwh === null ? 0 : u.energia_kwh), 0)

/**
 * Σ da JANELA COMUM — a manchete, a coluna "Energia" e o numerador da produtividade, os três
 * saídos do MESMO conjunto. Foi a mistura das duas somas que fez o cartão imprimir energia de
 * um período, capacidade de outra população e a razão de uma terceira: quem dividisse os dois
 * números impressos achava 536,6 com 380,1 escrito ao lado.
 */
const SOMA_COMPARAVEL = USINAS_E.reduce(
  (t, u) => t + (u.energia_comparavel_kwh === null ? 0 : u.energia_comparavel_kwh),
  0,
)
/** A capacidade das MESMAS usinas do numerador acima. */
const CAPACIDADE_COMPARAVEL = USINAS_E.reduce(
  (t, u) => t + (u.energia_comparavel_kwh === null || u.capacidade_kwp === null ? 0 : u.capacidade_kwp),
  0,
)

/** Os nomes por id — as duas famílias falam das MESMAS usinas, com os mesmos ids. */
const NOMES: Record<number, string> = {
  1: 'Pirapozinho',
  2: 'Porto Ferreira',
  3: 'Ibitinga',
  4: 'Bauru',
  5: 'Descalvado',
  6: 'Itápolis',
  7: 'Marília',
}

function item(
  posicao: number,
  id: number,
  valor: number,
  empatado = false,
  denominador: number | null = null,
) {
  return { posicao, usina_id: id, usina: NOMES[id], valor, empatado, denominador }
}

const RANK_PRODUTIVIDADE: RankingOut = {
  chave: 'produtividade',
  titulo: 'Produtividade',
  pergunta: 'Qual usina rende melhor?',
  nota: 'Energia dividida pela capacidade instalada. Ainda contém o sol de cada lugar.',
  unidade: 'kWh/kWp',
  ordem: 'desc',
  itens: [
    item(1, 1, 450),
    item(2, 2, 426.8),
    item(3, 3, 400, true),
    item(3, 4, 400, true),
    item(5, 5, 390),
    item(6, 6, 375),
  ],
  fora: ['Marília — Esta usina não está ligada ao monitoramento.'],
}

/**
 * O ranking de energia é por `energia_comparavel_kwh`, e por isso a ordem dele NÃO é a da
 * coluna `energia_kwh` que a tabela desenha. É a diferença que denuncia uma tela que ordena
 * sozinha: por `energia_kwh` o topo seria Pirapozinho; por comparável, é Itápolis.
 */
const RANK_ENERGIA: RankingOut = {
  chave: 'energia',
  titulo: 'Energia gerada',
  pergunta: 'Qual usina gera mais?',
  nota: 'Volume absoluto: a usina maior gera mais por ser maior.',
  unidade: 'kWh',
  ordem: 'desc',
  itens: [
    item(1, 6, 250000),
    item(2, 1, 200000),
    item(3, 3, 150000),
    item(4, 4, 120000),
    item(5, 5, 90000),
    item(6, 2, 40000),
  ],
  fora: ['Marília — Esta usina não está ligada ao monitoramento.'],
}

const RANK_PR: RankingOut = {
  chave: 'pr',
  titulo: 'Performance Ratio',
  pergunta: 'Qual usina converte melhor o sol que recebeu?',
  nota: 'Sem POA medida não há PR — a usina sai do ranking, não vai para o fim dele.',
  unidade: '%',
  ordem: 'desc',
  itens: [item(1, 1, 83.5), item(2, 2, 82.1), item(3, 3, 80), item(4, 4, 79.5), item(5, 6, 78)],
  fora: [
    'Descalvado — sem PR (o período não tem irradiância medida)',
    'Marília — Esta usina não está ligada ao monitoramento.',
  ],
}

/* ---------------------------------------------------------- manutenção */

function usinaM(
  parcial: Partial<UsinaManutencaoOut> & { id: number; nome: string },
): UsinaManutencaoOut {
  return {
    contrato: null,
    contrato_id: null,
    previsto: null,
    feitas: null,
    dispensadas: null,
    atrasadas: null,
    denominador: null,
    cumprimento_pct: null,
    cumprimento_rotulo: null,
    fora_da_conta: null,
    os_em_andamento: null,
    pendencias_abertas: null,
    pendencias_vencidas: null,
    pendencias_cobradas: null,
    pendencias_criticas: null,
    motivo: null,
    ...parcial,
  }
}

const USINAS_M: UsinaManutencaoOut[] = [
  usinaM({
    id: 3, nome: 'Ibitinga', contrato: 'Contrato de O&M 701', contrato_id: 701,
    previsto: 49, feitas: 13, dispensadas: 4, atrasadas: 14, denominador: 31,
    cumprimento_pct: 41.9, cumprimento_rotulo: '13 de 31',
    fora_da_conta: '18 ainda no prazo — fora da conta.',
    os_em_andamento: 3, pendencias_abertas: 7, pendencias_vencidas: 3,
    pendencias_cobradas: 2, pendencias_criticas: 1,
  }),
  usinaM({
    id: 1, nome: 'Pirapozinho', contrato: 'Contrato de O&M 655', contrato_id: 655,
    previsto: 40, feitas: 20, dispensadas: 2, atrasadas: 6, denominador: 28,
    cumprimento_pct: 71.4, cumprimento_rotulo: '20 de 28',
    os_em_andamento: 1, pendencias_abertas: 4, pendencias_vencidas: 1,
    pendencias_cobradas: 0, pendencias_criticas: 0,
  }),
  usinaM({
    id: 4, nome: 'Bauru', contrato: 'Contrato de O&M 712', contrato_id: 712,
    previsto: 20, feitas: 8, dispensadas: 1, atrasadas: 3, denominador: 12,
    cumprimento_pct: 66.7, cumprimento_rotulo: '8 de 12',
    os_em_andamento: 0, pendencias_abertas: 2, pendencias_vencidas: 0,
    pendencias_cobradas: 0, pendencias_criticas: 0,
  }),
  usinaM({
    id: 6, nome: 'Itápolis', contrato: 'Contrato de O&M 733', contrato_id: 733,
    previsto: 12, feitas: 5, dispensadas: 0, atrasadas: 2, denominador: 7,
    cumprimento_pct: 71.4, cumprimento_rotulo: '5 de 7',
    os_em_andamento: 1, pendencias_abertas: 1, pendencias_vencidas: 0,
    pendencias_cobradas: 0, pendencias_criticas: 0,
  }),
  usinaM({
    id: 5, nome: 'Descalvado', contrato: 'Contrato de O&M 744', contrato_id: 744,
    previsto: 10, feitas: 6, dispensadas: 0, atrasadas: 2, denominador: 8,
    cumprimento_pct: 75, cumprimento_rotulo: '6 de 8',
    os_em_andamento: 0, pendencias_abertas: 0, pendencias_vencidas: 0,
    pendencias_cobradas: 0, pendencias_criticas: 0,
  }),
  // Porto Ferreira é o caso da lição: 13 de 13 no recorte de vigência, ZERO atrasadas — e
  // 18 ocorrências ainda no prazo declaradas fora da conta.
  usinaM({
    id: 2, nome: 'Porto Ferreira', contrato: 'Contrato de O&M 698', contrato_id: 698,
    previsto: 31, feitas: 13, dispensadas: 0, atrasadas: 0, denominador: 13,
    cumprimento_pct: 100, cumprimento_rotulo: '13 de 13',
    fora_da_conta: '18 ainda no prazo — fora da conta.',
    os_em_andamento: 2, pendencias_abertas: 5, pendencias_vencidas: 2,
    pendencias_cobradas: 1, pendencias_criticas: 1,
  }),
  // A usina SEM cronograma publicado: travessão e motivo, fora de todo total.
  usinaM({
    id: 7, nome: 'Marília', motivo: 'Cronograma não publicado neste contrato.',
  }),
]

/** `maior_e_melhor=False` no servidor: 1º = MENOS atrasadas = melhor situação. */
const RANK_ATRASO: RankingOut = {
  chave: 'atraso',
  titulo: 'Atividades atrasadas',
  pergunta: 'Qual usina está mais atrasada na manutenção?',
  nota: 'Contagem absoluta, que não depende do tamanho do contrato.',
  unidade: null,
  ordem: 'asc',
  itens: [
    item(1, 2, 0),
    item(2, 6, 2, true),
    item(2, 5, 2, true),
    item(4, 4, 3),
    item(5, 1, 6),
    item(6, 3, 14),
  ],
  fora: ['Marília — sem cronograma consolidado'],
}

const RANK_CUMPRIMENTO: RankingOut = {
  chave: 'cumprimento',
  titulo: 'Cumprimento do cronograma',
  pergunta: 'Que fatia do que já era cobrável foi executada?',
  nota: 'Executadas sobre executadas + dispensadas + atrasadas. O que ainda está no prazo fica fora da conta.',
  unidade: '%',
  ordem: 'asc',
  itens: [
    item(1, 3, 41.9, false, 31),
    item(2, 4, 66.7, false, 12),
    item(3, 1, 71.4, true, 28),
    item(3, 6, 71.4, true, 7),
    item(5, 5, 75, false, 8),
    item(6, 2, 100, false, 13),
  ],
  fora: ['Marília — sem cronograma consolidado'],
}

const RANK_VENCIDAS: RankingOut = {
  chave: 'pendencias_vencidas',
  titulo: 'Pendências com prazo vencido',
  pergunta: 'Onde o prazo combinado já passou?',
  nota: null,
  unidade: 'pendências',
  ordem: 'asc',
  itens: [
    item(1, 4, 0, true), item(1, 6, 0, true), item(1, 5, 0, true),
    item(4, 1, 1), item(5, 2, 2), item(6, 3, 3),
  ],
  fora: ['Marília — as pendências não responderam'],
}

/* ------------------------------------------------------------ respostas */

function respostaEnergia(parcial: Partial<ComparativoOut> = {}): ComparativoOut {
  return {
    janela: JANELA,
    energia: {
      usinas: USINAS_E,
      totais: {
        usinas_no_total: 6,
        energia_kwh: SOMA_DA_COLUNA,
        capacidade_kwp: 3250,
        energia_comparavel_kwh: SOMA_COMPARAVEL,
        capacidade_comparavel_kwp: CAPACIDADE_COMPARAVEL,
        produtividade_kwh_kwp: 261.5,
        perdas_paradas_kwh: 22100,
      },
      rankings: [RANK_PRODUTIVIDADE, RANK_ENERGIA, RANK_PR],
    },
    manutencao: null,
    usinas_no_escopo: 7,
    aviso: null,
    ...parcial,
  }
}

function respostaManutencao(parcial: Partial<ComparativoOut> = {}): ComparativoOut {
  return {
    janela: JANELA,
    energia: null,
    manutencao: {
      usinas: USINAS_M,
      totais: {
        usinas_no_total: 6,
        previsto: 162,
        feitas: 65,
        dispensadas: 7,
        atrasadas: 27,
        denominador: 99,
        cumprimento_pct: 65.7,
        cumprimento_rotulo: '65 de 99',
        os_em_andamento: 7,
        pendencias_abertas: 19,
        pendencias_vencidas: 6,
      },
      rankings: [RANK_ATRASO, RANK_CUMPRIMENTO, RANK_VENCIDAS],
    },
    usinas_no_escopo: 7,
    aviso: null,
    ...parcial,
  }
}

/** O servidor: uma resposta por bloco, escolhida pela URL pedida. */
function servidor(energia = respostaEnergia(), manutencao = respostaManutencao()) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: unknown) => {
    const caminho = String(url)
    if (caminho.includes('blocos=manutencao')) return { data: manutencao } as never
    return { data: energia } as never
  })
}

function montar(Tela: () => JSX.Element, endereco = '/comparar/energia') {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[endereco]}>
        <Routes>
          <Route path="/comparar/energia" element={<Tela />} />
          <Route path="/comparar/manutencao" element={<Tela />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Os nomes de usina na ordem em que a tabela os desenhou. */
function nomesDasLinhas(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('tbody tr')).map((tr) => {
    const primeiro = tr.querySelector('td:nth-child(2) span')
    return primeiro ? (primeiro.textContent ?? '') : ''
  })
}

/**
 * A linha de UMA usina, pelo NOME — não por `textContent.includes`.
 *
 * A cidade de Porto Ferreira é Descalvado, que também é o nome de outra usina do cenário:
 * procurar pelo texto da linha inteira devolvia a linha errada, e o teste passava a afirmar
 * coisas sobre a usina vizinha. É o mesmo tropeço que a tela cometeria ao casar por nome em
 * vez de por id.
 */
function linhaDe(container: HTMLElement, nome: string): HTMLElement {
  const linhas = Array.from(container.querySelectorAll('tbody tr'))
  const achada = linhas.find(
    (tr) => (tr.querySelector('td:nth-child(2) span')?.textContent ?? '') === nome,
  )
  if (!achada) throw new Error(`linha de ${nome} não encontrada`)
  return achada as HTMLElement
}

beforeEach(() => {
  localStorage.clear()
  identificarCache(7)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  limparCache()
})

/* =================================================================== energia */

describe('Comparar usinas · energia', () => {
  it('lista as sete usinas ordenadas por produtividade, da maior para a menor', async () => {
    servidor()
    const { container } = montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')

    const nomes = nomesDasLinhas(container)
    expect(nomes).toHaveLength(7)
    expect(nomes).toEqual([
      'Pirapozinho',   // 450
      'Porto Ferreira', // 426,8
      'Ibitinga',      // 400 (empate)
      'Bauru',         // 400 (empate)
      'Descalvado',    // 390
      'Itápolis',      // 375
      'Marília',       // sem número: no fim, com o motivo
    ])
  })

  it('a ordem é a do SERVIDOR: a lista sai na sequência que o ranking publicou', async () => {
    servidor()
    const { container } = montar(CompararEnergia, '/comparar/energia?ordenar=energia')
    await screen.findByText('Qual usina gera mais?')

    // Byte a byte a ordem do `RANK_ENERGIA`, não uma ordenação refeita aqui.
    expect(nomesDasLinhas(container).slice(0, 2)).toEqual(['Itápolis', 'Pirapozinho'])
  })

  it('a coluna Energia mostra o MESMO número que o ranking usou para ordenar', async () => {
    // O defeito que este teste guarda: a coluna imprimia `energia_kwh` (período pedido)
    // enquanto o ranking ao lado ordenava por `energia_comparavel_kwh` (janela comum). A
    // linha de Pirapozinho saía "450,0 MWh / 1.000,0 kWp" com "200,0 kWh/kWp" ao lado — e
    // 450000/1000 dá 450, não 200. A divisão que o leitor faz de cabeça tem de fechar.
    servidor()
    const { container } = montar(CompararEnergia, '/comparar/energia?ordenar=energia')
    await screen.findByText('Qual usina gera mais?')

    const celulas = linhaDe(container, 'Pirapozinho').querySelectorAll('td')
    const energia = celulas[3].textContent ?? ''
    expect(energia).toContain('200,0 MWh')
    expect(energia).not.toContain('450,0 MWh')
  })

  it('usina sem PR sai do ranking de PR: travessão, motivo — e nunca 0 %', async () => {
    servidor()
    const { container } = montar(CompararEnergia, '/comparar/energia?ordenar=pr')
    await screen.findByText('Qual usina converte melhor o sol que recebeu?')

    const nomes = nomesDasLinhas(container)
    // Descalvado não está no ranking; vem depois dos ranqueados, junto de Marília.
    expect(nomes.slice(0, 5)).toEqual([
      'Pirapozinho', 'Porto Ferreira', 'Ibitinga', 'Bauru', 'Itápolis',
    ])
    expect(nomes.slice(5).sort()).toEqual(['Descalvado', 'Marília'])
    // E o motivo aparece escrito, para a ausência não virar suspeita de erro da tela.
    expect(
      screen.getByText('Descalvado — sem PR (o período não tem irradiância medida)'),
    ).toBeTruthy()

    // A célula de PR de Descalvado é um travessão — nunca um percentual. É esta a acusação
    // barata que o teste guarda: "0 %" ali se leria como "o pior PR da carteira".
    const pr = linhaDe(container, 'Descalvado').querySelectorAll('td')[4]
    expect(pr.textContent).toBe('—')
    expect(pr.textContent).not.toMatch(/%/)
  })

  it('a usina sem monitoramento fica na lista com o motivo, nunca com zero', async () => {
    servidor()
    const { container } = montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')

    const marilia = linhaDe(container, 'Marília')
    expect(marilia.textContent).toContain('Esta usina não está ligada ao monitoramento.')
    expect(marilia.textContent).not.toContain('0,0')
  })

  it('o total de energia é o do servidor, e ele bate com a soma da coluna', async () => {
    servidor()
    montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')

    // A manchete é a soma da JANELA COMUM, e ela fecha com a coluna que está logo abaixo.
    expect(SOMA_COMPARAVEL).toBe(850000)
    expect(screen.getByText('850,0 MWh')).toBeTruthy()
  })

  it('o total do período INTEIRO aparece, mas rotulado — nunca no lugar da manchete', async () => {
    servidor()
    const { container } = montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')

    // As duas somas convivem porque respondem a perguntas diferentes; o que não pode é uma
    // delas ficar sem dizer de que período é.
    expect(SOMA_DA_COLUNA).toBe(1335540)
    const texto = container.textContent ?? ''
    expect(texto).toContain('No período inteiro que você pediu')
    expect(texto).toContain('1.335,5 MWh')
  })

  it('a tela NÃO soma a coluna: quando o servidor manda outro total, é o dele que aparece', async () => {
    // Guarda o defeito mais caro do projeto — dois números para a mesma pergunta. Se a tela
    // somasse por conta própria, este teste mostraria 1.335,5 e não 900,0.
    const alterada = respostaEnergia()
    alterada.energia!.totais.energia_comparavel_kwh = 900000
    servidor(alterada)
    montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')

    expect(screen.getByText('900,0 MWh')).toBeTruthy()
    expect(screen.queryByText('850,0 MWh')).toBeNull()
  })

  it('o cabeçalho do total diz de quantas usinas ele fala', async () => {
    servidor()
    const { container } = montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')
    // "6 de 7 usinas com medição": sem o "de N", 1,3 GWh parece a carteira inteira.
    expect(container.textContent).toContain('usinas com medição')
    expect(container.textContent).toContain('6')
    expect(container.textContent).toContain('7')
  })

  it('o rodapé nomeia a janela comum E a usina que a encolheu', async () => {
    servidor()
    const { container } = montar(CompararEnergia)
    await screen.findByText('A janela desta comparação')

    const texto = container.textContent ?? ''
    expect(texto).toContain('mai a set de 2026')
    expect(texto).toContain('5 dos 9 meses')
    // O NOME é o que impede o cliente de concluir que o portal perdeu dados.
    expect(texto).toContain('encolhido por Porto Ferreira')
    expect(texto).toContain('Fora da comparação')
    expect(texto).toContain('Marília')
    expect(texto).toContain('travado em hoje')
  })

  it('a irradiação viaja junto — "rende melhor" ainda contém "teve mais sol"', async () => {
    servidor()
    const { container } = montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')
    expect(container.textContent).toContain('Irradiação')
    expect(container.textContent).toContain('1.180,4')
  })

  it('empate divide a posição e a tela mostra o sinal', async () => {
    servidor()
    const { container } = montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')

    const ibitinga = linhaDe(container, 'Ibitinga')
    const bauru = linhaDe(container, 'Bauru')
    expect(within(ibitinga).getByText('3º')).toBeTruthy()
    expect(within(bauru).getByText('3º')).toBeTruthy()
    // Sem o sinal, dois "3º" seguidos se leem como erro de contagem da tela.
    expect(within(ibitinga).getByText('=')).toBeTruthy()
  })

  it('a pergunta escrita na tela é a que o servidor redigiu', async () => {
    servidor()
    montar(CompararEnergia)
    // Se cada tela escrevesse a sua, "produtividade" viraria "eficiência" numa e
    // "rendimento" noutra, e o cliente acharia que são três números.
    expect(await screen.findByText('Qual usina rende melhor?')).toBeTruthy()
    expect(
      screen.getByText(/Energia dividida pela capacidade instalada/),
    ).toBeTruthy()
  })

  it('pede só o bloco de energia, e num período de mês inteiro', async () => {
    const get = servidor()
    montar(CompararEnergia, '/comparar/energia?em=2026-08-17')
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(0))

    const url = String(get.mock.calls[0][0])
    expect(url).toContain('blocos=energia')
    expect(url).not.toContain('blocos=manutencao')
    // Do primeiro ao ÚLTIMO dia: uma chave de cache por mês, não por dia de consulta —
    // senão abrir a mesma tela amanhã repetiria sete idas ao monitoramento.
    expect(url).toContain('de=2026-08-01')
    expect(url).toContain('ate=2026-08-31')
  })

  it('o recorte de ano vira o ano inteiro no pedido', async () => {
    const get = servidor()
    montar(CompararEnergia, '/comparar/energia?recorte=ano&em=2026-08-17')
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(0))

    const url = String(get.mock.calls[0][0])
    expect(url).toContain('de=2026-01-01')
    expect(url).toContain('ate=2026-12-31')
  })

  it('uma régua que o portal nunca ouviu falar é selecionável pela URL', async () => {
    // Quem diz que réguas existem é o SERVIDOR. Enquanto a validação era uma lista de
    // chaves escrita no portal, uma régua nova aparecia na lista suspensa e, ao ser
    // escolhida, caía de volta na padrão — sem erro, sem explicação, e só com um deploy do
    // portal para consertar.
    const comReguaNova = respostaEnergia()
    comReguaNova.energia!.rankings = [
      ...comReguaNova.energia!.rankings,
      {
        ...RANK_PR,
        chave: 'disponibilidade',
        titulo: 'Disponibilidade',
        pergunta: 'Qual usina ficou mais tempo de pé?',
      },
    ]
    servidor(comReguaNova)
    montar(CompararEnergia, '/comparar/energia?ordenar=disponibilidade')

    expect(await screen.findByText('Qual usina ficou mais tempo de pé?')).toBeTruthy()
    expect(screen.queryByText('Qual usina rende melhor?')).toBeNull()
  })

  it('chave de régua sem sentido cai na padrão, sem tela vazia', async () => {
    servidor()
    montar(CompararEnergia, '/comparar/energia?ordenar=%20%3Cscript%3E')
    expect(await screen.findByText('Qual usina rende melhor?')).toBeTruthy()
  })

  it('carteira de uma usina só não vira comparação', async () => {
    servidor(respostaEnergia({ usinas_no_escopo: 1 }))
    montar(CompararEnergia)
    expect(await screen.findByText('Comparar exige mais de uma usina')).toBeTruthy()
  })

  it('a régua se escolhe numa lista suspensa — não numa fileira de chips', async () => {
    servidor()
    montar(CompararEnergia)
    await screen.findByText('Qual usina rende melhor?')

    // Com chips, as três réguas estariam na tela ao mesmo tempo, como BOTÕES irmãos. É isso
    // que se conta aqui — e não a presença do texto, porque "Energia gerada" também é o
    // rótulo de um KPI do cartão de cima.
    const botoesDeRegua = () =>
      screen
        .getAllByRole('button')
        .map((b) => b.textContent ?? '')
        .filter((t) => /Produtividade|Energia gerada|Performance Ratio/.test(t))

    expect(botoesDeRegua()).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: /Ordenar por/ }))
    // Abertas, aparecem com a PERGUNTA de cada uma como detalhe — a régua se escolhe pelo
    // que ela responde, não pelo jargão.
    await waitFor(() => expect(botoesDeRegua()).toHaveLength(4)) // o gatilho + as três opções
    expect(screen.getByText('Qual usina gera mais?')).toBeTruthy()
  })
})

/* ================================================================ manutenção */

describe('Comparar manutenção', () => {
  it('abre pela usina MAIS atrasada, que é o que a pergunta procura', async () => {
    servidor()
    const { container } = montar(CompararManutencao, '/comparar/manutencao')
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    const nomes = nomesDasLinhas(container)
    expect(nomes).toHaveLength(7)
    // O servidor ordena com 1º = MELHOR (menos atrasadas); a lista é lida da outra ponta,
    // senão a resposta à pergunta impressa ficaria no rodapé da tabela.
    expect(nomes[0]).toBe('Ibitinga') // 14 atrasadas
    expect(nomes[1]).toBe('Pirapozinho') // 6
    expect(nomes[2]).toBe('Bauru') // 3
    expect(nomes[6]).toBe('Marília') // sem cronograma: no fim, com o motivo
    // E a legenda existe, para o "6º" no topo não parecer erro de contagem da tela. Ela é
    // FACTUAL ("1º é o menor"), e não interpretativa: em `atraso` o menor é a melhor
    // situação, em `cumprimento` é a pior, e as duas chegam com o mesmo `ordem: 'asc'`.
    expect(screen.getByText(/o posto é o do ranking do servidor, em que 1º é o menor/)).toBeTruthy()
  })

  it('todo percentual traz o denominador ao lado', async () => {
    servidor()
    const { container } = montar(CompararManutencao)
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    // Foi a falta disto que produziu "13 de 270" numa tela e "41,9 %" na outra.
    const ibitinga = linhaDe(container, 'Ibitinga')
    expect(ibitinga.textContent).toContain('41,9%')
    expect(ibitinga.textContent).toContain('13 de 31')
    // No total, idem.
    expect(container.textContent).toContain('65,7%')
    expect(container.textContent).toContain('65 de 99')
  })

  it('o que ainda está no prazo é DECLARADO fora da conta', async () => {
    servidor()
    const { container } = montar(CompararManutencao)
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    const porto = linhaDe(container, 'Porto Ferreira')
    // 13 de 13 e zero atrasadas — com as 18 ocorrências futuras ditas em voz alta. É o
    // recorte de vigência que impede o "13 de 270" de voltar.
    expect(porto.textContent).toContain('13 de 13')
    expect(porto.textContent).toContain('18 ainda no prazo')
  })

  it('dispensado nunca funde com feito', async () => {
    servidor()
    const { container } = montar(CompararManutencao)
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    const ibitinga = linhaDe(container, 'Ibitinga')
    // 13 executadas e 4 dispensadas aparecem separadas; somadas dariam 17, e "foi feito" e
    // "foi dispensado" são afirmações diferentes.
    expect(ibitinga.textContent).toContain('13')
    expect(ibitinga.textContent).toContain('4 dispensada(s)')
    expect(ibitinga.textContent).not.toContain('17')
  })

  it('usina sem cronograma sai com travessão, com o motivo — e fora do total', async () => {
    servidor()
    const { container } = montar(CompararManutencao)
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    const marilia = linhaDe(container, 'Marília')
    expect(marilia.textContent).toContain('Cronograma não publicado neste contrato.')
    expect(marilia.textContent).toContain('—')
    // "0 atrasadas" numa usina sem cronograma se leria como "está tudo em dia".
    expect(marilia.textContent).not.toMatch(/\b0\b/)

    // Cada célula sem número CARREGA o motivo: passar o mouse sobre o travessão diz por
    // quê. Sem isso o cliente vê quatro traços na linha e não tem nenhuma explicação ali —
    // e é essa a diferença entre "não temos o dado" e "a tela está quebrada".
    const cumprimento = marilia.querySelectorAll('td')[3]
    expect(cumprimento.querySelector('[title]')?.getAttribute('title')).toBe(
      'Cronograma não publicado neste contrato.',
    )
    // E o cabeçalho do total diz de quantas usinas ele fala.
    expect(container.textContent).toContain('usinas com cronograma publicado')
  })

  it('a barra some quando não há denominador — não vira uma barra vazia', async () => {
    servidor()
    const { container } = montar(CompararManutencao)
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    const linhas = Array.from(container.querySelectorAll('tbody tr'))
    // Seis com cronograma têm barra; Marília, não — a célula inteira dela é o travessão.
    expect(linhas.filter((tr) => tr.querySelector('.rounded-barra'))).toHaveLength(6)
    expect(linhaDe(container, 'Marília').querySelector('.rounded-barra')).toBeNull()
  })

  it('contagem faltando com denominador presente também não vira barra', async () => {
    // O outro lado do mesmo cuidado: o denominador chegou, mas uma das três contagens não.
    // Desenhar a fatia que falta com largura zero representaria "não sabemos" como "não
    // houve", e o desenho passaria a afirmar mais do que o número ao lado dele.
    const torta = respostaManutencao()
    torta.manutencao!.usinas = torta.manutencao!.usinas.map((u) =>
      u.id === 4 ? { ...u, feitas: null } : u,
    )
    servidor(respostaEnergia(), torta)
    const { container } = montar(CompararManutencao)
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    const bauru = linhaDe(container, 'Bauru')
    expect(bauru.querySelector('.rounded-barra')).toBeNull()
    // E o percentual, que o servidor calculou, continua na tela com o denominador.
    expect(bauru.textContent).toContain('8 de 12')
  })

  it('o rodapé avisa que "em curso" é foto de hoje, não do período', async () => {
    servidor()
    const { container } = montar(CompararManutencao)
    await screen.findByText('A janela desta comparação')

    const texto = container.textContent ?? ''
    expect(texto).toContain('situação de HOJE, não do período comparado')
    expect(texto).toContain('só os meses da janela em que o contrato existe')
    // As frases da janela são as MESMAS do comparativo de energia.
    expect(texto).toContain('mai a set de 2026')
    expect(texto).toContain('encolhido por Porto Ferreira')
  })

  it('pede só o bloco de manutenção', async () => {
    const get = servidor()
    montar(CompararManutencao, '/comparar/manutencao')
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(0))

    const url = String(get.mock.calls[0][0])
    expect(url).toContain('blocos=manutencao')
    expect(url).not.toContain('blocos=energia')
  })

  it('trocar de régua para cumprimento mantém o denominador de cada linha', async () => {
    servidor()
    const { container } = montar(CompararManutencao, '/comparar/manutencao?ordenar=cumprimento')
    await screen.findByText('Que fatia do que já era cobrável foi executada?')

    // A direção de leitura é a MESMA das seis réguas — o maior valor no topo. Aqui isso põe
    // Porto Ferreira (100 %) à frente, e é de propósito: o servidor manda `ordem: 'asc'` em
    // `cumprimento`, em `atraso` e em `pendencias_vencidas`, mas o `posicao` 1 significa a
    // MELHOR situação nas duas últimas e a PIOR nesta. Seguir o posto daria três direções de
    // leitura na mesma tela; seguir o valor dá uma só, e a legenda diz o que o posto é.
    const nomes = nomesDasLinhas(container)
    expect(nomes[0]).toBe('Porto Ferreira')
    expect(nomes[nomes.length - 2]).toBe('Ibitinga')
    // O denominador continua ao lado de cada percentual, que é o que este teste guarda.
    expect(container.textContent).toContain('13 de 31')
    expect(container.textContent).toContain('13 de 13')
  })
})

/* ============================================================ menu e rotas */

describe('os dois comparativos no menu e nas rotas', () => {
  const usuario: Usuario = {
    id: 7,
    nome: 'Cliente de Teste',
    apelido: 'cliente',
    email: null,
    empresa: 'Carteira Boa',
    tem_meuwatt: true,
    tem_meuplano: true,
    nivel_acesso: 1,
    usinas: 7,
    trocar_senha: false,
  }

  function abrir(endereco: string) {
    window.history.replaceState({}, '', endereco)
    return render(<App />)
  }

  beforeEach(() => {
    useAuth.setState({
      token: 'token-de-teste',
      expiraEm: '2099-01-01T00:00:00.000Z',
      usuario,
      erro: null,
      entrando: false,
    })
    // A rede fica fora do ar: aqui o que se afere é a navegação, não a leitura.
    vi.spyOn(api, 'get').mockRejectedValue(new Error('sem rede neste teste'))
    vi.spyOn(api, 'post').mockRejectedValue(new Error('sem rede neste teste'))
  })

  it('aparecem nas três larguras — barra, trilho e gaveta', async () => {
    const { container } = abrir('/usinas/7/energia')
    // O trilho (w-16, só ícone) e a barra (w-56, com rótulo) são desenhados juntos: quem os
    // esconde é o CSS por largura, e no jsdom os dois estão no documento.
    await waitFor(() => expect(container.querySelectorAll('nav').length).toBeGreaterThanOrEqual(2))

    const navs = Array.from(container.querySelectorAll('nav'))
    const trilho = navs.find((n) => n.className.includes('w-16'))!
    const barra = navs.find((n) => n.className.includes('w-56'))!
    for (const lugar of [trilho, barra]) {
      expect(within(lugar as HTMLElement).getByLabelText('Geração')).toBeTruthy()
      expect(within(lugar as HTMLElement).getByLabelText('Manutenção das usinas')).toBeTruthy()
    }

    // A gaveta do celular lê a MESMA lista — abrir e conferir é o que impede um item novo de
    // existir em duas larguras e sumir na terceira.
    fireEvent.click(screen.getByLabelText('Abrir menu'))
    // Dois elementos se chamam "Fechar menu": o fundo escuro e o X. O que interessa é o
    // que está DENTRO da gaveta.
    const fechar = await screen.findAllByLabelText('Fechar menu')
    const aside = fechar.map((e) => e.closest('aside')).find((a): a is HTMLElement => a !== null)!
    expect(within(aside).getByLabelText('Geração')).toBeTruthy()
    expect(within(aside).getByLabelText('Manutenção das usinas')).toBeTruthy()
  })

  it('cada comparativo abre no PRIMEIRO lugar da sua família', async () => {
    const { container } = abrir('/usinas/7/energia')
    await waitFor(() => expect(container.querySelectorAll('nav').length).toBeGreaterThanOrEqual(2))

    const barra = Array.from(container.querySelectorAll('nav')).find((n) =>
      n.className.includes('w-56'),
    )!
    const rotulos = Array.from(barra.querySelectorAll('a')).map((a) => a.getAttribute('aria-label'))
    expect(rotulos.indexOf('Comparar usinas')).toBeLessThan(rotulos.indexOf('Painel'))
    expect(rotulos.indexOf('Comparar manutenção')).toBeLessThan(rotulos.indexOf('Cronograma'))
  })

  it('o endereço de carteira abre a tela, sem usina no caminho', async () => {
    abrir('/comparar/energia')
    expect(await screen.findByText('Qual gera mais, e qual rende melhor?')).toBeTruthy()
    expect(window.location.pathname).toBe('/comparar/energia')
  })

  it('endereço com usina no meio cai no de carteira, com a query intacta', async () => {
    // A navegação lateral ainda monta as entradas como `/usinas/${id}${fim}`; sem este
    // redirecionamento os dois itens levariam a uma tela em branco. Um link colado num
    // e-mail nesse formato também continua funcionando.
    abrir('/usinas/7/comparar/manutencao?ordenar=cumprimento')
    await screen.findByText(
      'Qual usina está mais atrasada — e quanto do combinado já foi feito?',
    )
    await waitFor(() => expect(window.location.pathname).toBe('/comparar/manutencao'))
    expect(window.location.search).toBe('?ordenar=cumprimento')
  })

  it('ranking com UMA colocada não dá medalha a ninguém', async () => {
    // O DEFEITO que o dono viu: em setembro, a única usina com cronograma publicado
    // recebia "1º" no ranking de atraso enquanto o ranking de cumprimento ao lado voltava
    // com ZERO posições e a coluna inteira em travessão. Um pódio de uma pessoa não é
    // classificação — classificar exige alguém para ficar atrás.
    const so_uma = respostaManutencao()
    so_uma.manutencao!.rankings = [
      { ...RANK_ATRASO, itens: [RANK_ATRASO.itens[0]] },
      ...so_uma.manutencao!.rankings.slice(1),
    ]
    // O 2º argumento é o da MANUTENÇÃO: o 1º é a energia, e passar no lugar errado deixaria
    // a tela lendo a resposta padrão de seis colocadas.
    servidor(respostaEnergia(), so_uma)
    const { container } = montar(CompararManutencao, '/comparar/manutencao')
    await screen.findByText('Qual usina está mais atrasada na manutenção?')

    const POSTO = '[title="Posição no ranking do servidor"]'
    expect(container.querySelectorAll(POSTO)).toHaveLength(0)
    // E a legenda do posto sai junto: ela explicaria uma coluna que não existe — e ainda
    // escreveria "1º" numa tela que acabou de decidir não dar medalha a ninguém.
    expect(container.textContent).not.toContain('1º é o menor')

    // E o contraste: com duas ou mais, o posto volta.
    cleanup()
    servidor()
    const cheio = montar(CompararManutencao, '/comparar/manutencao')
    await screen.findByText('Qual usina está mais atrasada na manutenção?')
    await waitFor(() =>
      expect(cheio.container.querySelectorAll(POSTO).length).toBeGreaterThan(1),
    )
  })
})
