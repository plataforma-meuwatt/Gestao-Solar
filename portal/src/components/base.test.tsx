/**
 * As duas peças novas do design system — e o defeito que cada teste guarda.
 *
 * **Opção desabilitada.** O portal precisa dizer o que ESTA usina não tem, e a ausência
 * derivada junto: "sem estação solarimétrica" e "sem estação não há irradiação, e sem
 * irradiação não se calcula PR". Até aqui toda opção do `Combobox` era clicável, e a saída
 * de quem precisou disso foi copiar o componente inteiro — está em `features/energia`, um
 * menu de meses feito à mão só para poder desabilitar. As três coisas que este arquivo
 * segura são: a opção **continua na lista** (sumir com ela faria o cliente concluir que o
 * portal não oferece, quando o fato é sobre a usina dele), **continua achável pela busca**,
 * e **o motivo aparece** — botão desabilitado sem frase é uma parede sem porta.
 *
 * O quarto guardião não é um teste, é o `tsc`: `Opcao` é uma união em que `desabilitada:
 * true` EXIGE `detalhe`. O `@ts-expect-error` lá embaixo reprova o `npm run check` no dia em
 * que alguém afrouxar o tipo — porque aí o `@ts-expect-error` fica sem erro para esperar.
 *
 * **`ComboboxMulti`.** A escolha de inversores é múltipla sobre até 500 séries, e as duas
 * saídas fáceis são proibidas: fileira de caixinhas é chip com outro nome (a tela do meuWatt
 * faz assim) e `select multiple` não se busca por teclado. O que os testes daqui protegem:
 *
 * 1. **`null` não é a mesma coisa que listar todos.** Na exportação isso decide um fato: com
 *    `series: null` o inversor comissionado no meio do período entra sozinho no arquivo; com
 *    a lista explícita, não entra. O gatilho escreve os dois estados de formas diferentes, e
 *    desmarcar um item a partir de `null` materializa a lista em vez de devolver `null`.
 * 2. **Marcar não fecha o menu.** Fechar a cada clique é o defeito que transforma escolher
 *    quatro inversores em quatro aberturas.
 * 3. **Os escolhidos sobem ao topo, mas só na ABERTURA.** Reordenar a cada clique faz o item
 *    seguinte pular para debaixo do cursor, e a pessoa marca o errado.
 * 4. **Opção desabilitada nunca entra na conta nem em "todos".** Ela é uma coisa que a usina
 *    não tem; mandá-la ao servidor dentro de uma lista explícita seria pedir o que não existe.
 * 5. **O `Combobox` de sempre não mudou** — as duas peças passaram a dividir a linha da lista,
 *    e uma escolha que não devolve valor ou não fecha o menu seria a regressão dessa fusão.
 *
 * **`ComboboxMultiAgrupado`.** A peça que decide se o pedido do dono foi atendido: "o diretor
 * é doido, ele quer sim baixar por skid". A capacidade sempre atravessou o contrato inteiro —
 * a tela, o BFF e a mw-api recebem `agrupamento: 'skid'` desde o primeiro dia —, mas escolher
 * o skid 2 custava abrir uma lista PLANA de vinte e quatro inversores e marcar oito caixas uma
 * a uma: tecnicamente presente, praticamente ausente. E a saída do meuWatt (faixa de caixinhas
 * por skid) é chip com outro nome, proibido aqui. O que os testes daqui guardam, além do que a
 * peça irmã já guarda:
 *
 * 6. **O gatilho fechado diz três verdades diferentes** — "todos · 24", "Skid 2 e Skid 3 · 16"
 *    e "9 de 24". Achatá-las numa contagem só apagaria o pedido que a pessoa fez.
 * 7. **O cabeçalho do grupo é um controle, não um título** — `role="checkbox"` de três estados,
 *    um toque marca o skid inteiro e o seguinte limpa.
 * 8. **Durante a busca ele age só sobre o que está à vista.** Um tri-estado que marcasse o
 *    grupo inteiro com três linhas na tela seria escrita cega.
 * 9. **Nenhuma pílula** — a proibição é lida do próprio arquivo, porque este defeito entra por
 *    cópia e nenhum `tsc` tem como pegá-lo.
 */

import { readFileSync } from 'node:fs'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  Combobox,
  ComboboxMulti,
  ComboboxMultiAgrupado,
  opcao,
  type GrupoDeOpcoes,
  type Opcao,
} from '@/components/base'

afterEach(cleanup)

/* ------------------------------------------------------------------ cenário */

/** Porto Ferreira tem estação; a de Pereiras não — e o PR depende dela. */
const PACOTES: Opcao[] = [
  { valor: 'geracao', rotulo: 'Geração da usina', detalhe: 'uma coluna por inversor' },
  {
    valor: 'clima',
    rotulo: 'Geração + clima',
    detalhe: 'esta usina não tem estação solarimétrica',
    desabilitada: true,
  },
  {
    valor: 'pr',
    rotulo: 'Desempenho (PR)',
    detalhe: 'sem estação não há irradiação, e sem irradiação não se calcula PR',
    desabilitada: true,
  },
  { valor: 'medidor', rotulo: 'Energia no medidor', detalhe: 'a leitura que fecha o faturamento' },
]

/** Sete para a busca aparecer (ela só surge acima de seis). */
const SETE: Opcao[] = [
  { valor: '1', rotulo: 'Inversor 1', detalhe: 'NS 1001' },
  { valor: '2', rotulo: 'Inversor 2', detalhe: 'NS 1002' },
  { valor: '3', rotulo: 'Inversor 3', detalhe: 'NS 1003' },
  { valor: '4', rotulo: 'Inversor 4', detalhe: 'NS 1004' },
  { valor: '5', rotulo: 'Inversor 5', detalhe: 'NS 1005' },
  { valor: '6', rotulo: 'Inversor 6', detalhe: 'NS 1006' },
  { valor: '7', rotulo: 'Inversor 7', detalhe: 'retirado — sem leitura no período', desabilitada: true },
]

const TRES: Opcao[] = [
  { valor: 'a', rotulo: 'Inversor A', detalhe: 'NS 1' },
  { valor: 'b', rotulo: 'Inversor B', detalhe: 'NS 2' },
  { valor: 'c', rotulo: 'Inversor C', detalhe: 'NS 3' },
]

function Unico({ opcoes, onEscolher }: { opcoes: Opcao[]; onEscolher?: (v: string) => void }) {
  const [valor, setValor] = useState<string | null>(null)
  return (
    <Combobox
      opcoes={opcoes}
      valor={valor}
      onEscolher={(v) => {
        setValor(v)
        onEscolher?.(v)
      }}
    />
  )
}

function Multi({
  opcoes,
  inicial,
  onEscolher,
}: {
  opcoes: Opcao[]
  inicial: string[] | null
  onEscolher?: (v: string[] | null) => void
}) {
  const [valor, setValor] = useState<string[] | null>(inicial)
  return (
    <ComboboxMulti
      opcoes={opcoes}
      valor={valor}
      onEscolher={(v) => {
        setValor(v)
        onEscolher?.(v)
      }}
      substantivo="inversores"
    />
  )
}

/** O gatilho é o único botão fora do menu; abrir é sempre clicar nele. */
function abrir() {
  fireEvent.click(screen.getAllByRole('button')[0])
}

function rotulosDaLista() {
  return screen
    .getAllByRole('checkbox')
    .map((b) => (b.textContent ?? '').replace(/NS \d+/, '').replace('✓', '').trim())
}

/* ------------------------------------------------------------------ desabilitada */

describe('opção desabilitada com motivo', () => {
  it('continua na lista, com o motivo escrito, e não é clicável', () => {
    const escolheu = vi.fn()
    render(<Unico opcoes={PACOTES} onEscolher={escolheu} />)
    abrir()

    // Continua na lista: sumir faria o cliente concluir que o portal não oferece.
    const clima = screen.getByRole('button', { name: /Geração \+ clima/ })
    expect(clima.hasAttribute('disabled')).toBe(true)
    expect(clima.getAttribute('aria-disabled')).toBe('true')

    // E o motivo aparece — inclusive a ausência DERIVADA, que é a que ensina algo.
    expect(screen.getByText('esta usina não tem estação solarimétrica')).toBeTruthy()
    expect(
      screen.getByText('sem estação não há irradiação, e sem irradiação não se calcula PR'),
    ).toBeTruthy()

    fireEvent.click(clima)
    expect(escolheu).not.toHaveBeenCalled()
    // O menu segue aberto: nada foi escolhido, então nada se fechou.
    expect(screen.getByRole('button', { name: /Energia no medidor/ })).toBeTruthy()
  })

  it('continua achável pela busca — inclusive pelo detalhe', () => {
    render(<Unico opcoes={SETE} />)
    abrir()

    fireEvent.change(screen.getByPlaceholderText('Buscar…'), { target: { value: 'Inversor 7' } })
    const sete = screen.getByRole('button', { name: /Inversor 7/ })
    expect(sete.hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('retirado — sem leitura no período')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Inversor 1\b/ })).toBeNull()
  })

  it('a escolha comum continua devolvendo o valor e fechando o menu', () => {
    const escolheu = vi.fn()
    render(<Unico opcoes={PACOTES} onEscolher={escolheu} />)
    abrir()

    fireEvent.click(screen.getByRole('button', { name: /Energia no medidor/ }))
    expect(escolheu).toHaveBeenCalledWith('medidor')
    expect(screen.queryByRole('list')).toBeNull()
    expect(screen.getAllByRole('button')[0].textContent).toContain('Energia no medidor')
  })

  /**
   * O guardião de tipo. Não roda nada: quem o verifica é o `tsc` do `npm run check`. Se
   * alguém trocar a união por `desabilitada?: boolean`, este `@ts-expect-error` fica sem
   * erro para esperar e o `check` reprova — que é o ponto.
   */
  it('não deixa desabilitar sem escrever o motivo (isto quem prova é o tsc)', () => {
    const semMotivo: Opcao[] = [
      // @ts-expect-error desabilitar exige `detalhe`: parede sem porta não passa no tipo.
      { valor: 'x', rotulo: 'Sem motivo', desabilitada: true },
    ]
    expect(semMotivo).toHaveLength(1)
  })

  /**
   * O construtor existe para a lista montada num `map`, em que cada item pode estar
   * indisponível por uma razão própria. Sem ele, o jeito curto de escrever é
   * `desabilitada: boolean` com `detalhe: string | undefined` — a mesma parede sem porta
   * com outra roupa. Aqui o motivo É o que desabilita, então a dupla nunca se separa.
   */
  it('opcao(): o motivo é o que desabilita, e ele toma o lugar do detalhe', () => {
    const disponivel = opcao({ valor: 'poa', rotulo: 'Irradiação', detalhe: 'W/m²' }, null)
    expect(disponivel.desabilitada).toBeUndefined()
    expect(disponivel.detalhe).toBe('W/m²')

    const fora = opcao(
      { valor: 'poa', rotulo: 'Irradiação', detalhe: 'W/m²' },
      'esta estação não mede irradiação no plano',
    )
    expect(fora.desabilitada).toBe(true)
    expect(fora.detalhe).toBe('esta estação não mede irradiação no plano')

    // E o construído chega inteiro à tela, com o motivo à vista.
    render(<Unico opcoes={[disponivel, fora]} />)
    abrir()
    expect(screen.getByText('esta estação não mede irradiação no plano')).toBeTruthy()
    expect(
      screen.getByRole('button', { name: /esta estação não mede/ }).hasAttribute('disabled'),
    ).toBe(true)
  })
})

/* ------------------------------------------------------------------ multi */

describe('ComboboxMulti', () => {
  it('escreve "todos" e "todos listados" de formas diferentes — porque são pedidos diferentes', () => {
    const { unmount } = render(<Multi opcoes={TRES} inicial={null} />)
    expect(screen.getAllByRole('button')[0].textContent).toContain('todos · 3 inversores')
    unmount()

    render(<Multi opcoes={TRES} inicial={['a', 'b', 'c']} />)
    expect(screen.getAllByRole('button')[0].textContent).toContain('3 de 3 inversores')
  })

  it('desmarcar a partir de "todos" MATERIALIZA a lista, e não devolve todos de novo', () => {
    const escolheu = vi.fn()
    render(<Multi opcoes={TRES} inicial={null} onEscolher={escolheu} />)
    abrir()

    // Com `null`, todos aparecem marcados: a pergunta da caixinha é "vai sair no arquivo?".
    for (const c of screen.getAllByRole('checkbox')) {
      expect(c.getAttribute('aria-checked')).toBe('true')
    }

    fireEvent.click(screen.getByRole('checkbox', { name: /Inversor B/ }))
    expect(escolheu).toHaveBeenCalledWith(['a', 'c'])
    expect(screen.getAllByRole('button')[0].textContent).toContain('2 de 3 inversores')
  })

  it('marcar não fecha o menu — quatro inversores não são quatro aberturas', () => {
    const escolheu = vi.fn()
    render(<Multi opcoes={TRES} inicial={[]} onEscolher={escolheu} />)
    abrir()

    fireEvent.click(screen.getByRole('checkbox', { name: /Inversor A/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /Inversor C/ }))
    expect(escolheu).toHaveBeenLastCalledWith(['a', 'c'])
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)
  })

  it('os escolhidos sobem ao topo na ABERTURA, e a lista não dança enquanto se marca', () => {
    render(<Multi opcoes={TRES} inicial={['c']} />)
    abrir()
    expect(rotulosDaLista()).toEqual(['Inversor C', 'Inversor A', 'Inversor B'])

    // Marcar A não pode reordenar: o próximo item pularia para debaixo do cursor.
    fireEvent.click(screen.getByRole('checkbox', { name: /Inversor A/ }))
    expect(rotulosDaLista()).toEqual(['Inversor C', 'Inversor A', 'Inversor B'])

    // Fechar e reabrir acomoda a lista — aí sim, e só aí.
    abrir()
    abrir()
    expect(rotulosDaLista()).toEqual(['Inversor A', 'Inversor C', 'Inversor B'])
  })

  it('a opção desabilitada fica fora da conta, de "todos" e da materialização', () => {
    const escolheu = vi.fn()
    render(<Multi opcoes={SETE} inicial={null} onEscolher={escolheu} />)

    // Sete opções, seis escolhíveis: a conta é do que dá para pedir.
    expect(screen.getAllByRole('button')[0].textContent).toContain('todos · 6 inversores')
    abrir()

    const sete = screen.getByRole('checkbox', { name: /Inversor 7/ })
    expect(sete.hasAttribute('disabled')).toBe(true)
    expect(sete.getAttribute('aria-checked')).toBe('false')

    fireEvent.click(screen.getByRole('checkbox', { name: /Inversor 1\b/ }))
    expect(escolheu).toHaveBeenCalledWith(['2', '3', '4', '5', '6'])
  })

  it('"todos" volta ao null e "Limpar" dá a lista vazia — e cada um se desliga no seu estado', () => {
    const escolheu = vi.fn()
    render(<Multi opcoes={TRES} inicial={null} onEscolher={escolheu} />)
    abrir()

    const rodape = screen.getByRole('list').parentElement as HTMLElement
    const todos = within(rodape).getByRole('button', { name: 'todos' })
    const limpar = within(rodape).getByRole('button', { name: 'Limpar' })

    // Já está em "todos": o botão não tem o que fazer, e diz isso.
    expect(todos.hasAttribute('disabled')).toBe(true)
    expect(limpar.hasAttribute('disabled')).toBe(false)

    fireEvent.click(limpar)
    expect(escolheu).toHaveBeenLastCalledWith([])
    expect(screen.getAllByRole('button')[0].textContent).toContain('0 de 3 inversores')

    fireEvent.click(within(rodape).getByRole('button', { name: 'todos' }))
    expect(escolheu).toHaveBeenLastCalledWith(null)
    expect(screen.getAllByRole('button')[0].textContent).toContain('todos · 3 inversores')
  })

  it('fecha com ESC, como a lista suspensa de sempre', () => {
    render(<Multi opcoes={TRES} inicial={null} />)
    abrir()
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('checkbox')).toBeNull()
  })
})

/* ------------------------------------------------------------------ agrupado */

/**
 * Vinte e quatro inversores em três skids — a forma de Porto Ferreira, que é a usina em que
 * o diretor pediu "baixar por skid".
 *
 * Os números de série não são enfeite: são o que a pessoa tem na mão em campo, e é por eles
 * que ela busca. O skid 3 recebe três seriais de uma faixa (53xx) e cinco de outra (59xx) de
 * propósito — é o que permite uma busca acertar **três** linhas dentro de um grupo de oito, e
 * provar que o cabeçalho age só sobre o que está à vista.
 */
const SKIDS: GrupoDeOpcoes[] = [
  {
    chave: 's1',
    rotulo: 'Skid 1',
    detalhe: '1,5 MWp',
    opcoes: Array.from({ length: 8 }, (_, i) => ({
      valor: `s1-${i + 1}`,
      rotulo: `Inv 0${i + 1}`,
      detalhe: `NS 510${i + 1}`,
    })),
  },
  {
    chave: 's2',
    rotulo: 'Skid 2',
    detalhe: '1,5 MWp',
    opcoes: Array.from({ length: 8 }, (_, i) => ({
      valor: `s2-${i + 1}`,
      rotulo: `Inv ${String(i + 9).padStart(2, '0')}`,
      detalhe: `NS 520${i + 1}`,
    })),
  },
  {
    chave: 's3',
    rotulo: 'Skid 3',
    detalhe: '1,5 MWp',
    opcoes: Array.from({ length: 8 }, (_, i) => ({
      valor: `s3-${i + 1}`,
      rotulo: `Inv ${String(i + 17).padStart(2, '0')}`,
      detalhe: i < 3 ? `NS 530${i + 1}` : `NS 590${i + 1}`,
    })),
  },
]

const TODOS_DO_SKID = (n: number) => Array.from({ length: 8 }, (_, i) => `s${n}-${i + 1}`)

function Agrupado({
  grupos = SKIDS,
  inicial,
  onEscolher,
}: {
  grupos?: GrupoDeOpcoes[]
  inicial: string[] | null
  onEscolher?: (v: string[] | null) => void
}) {
  const [valor, setValor] = useState<string[] | null>(inicial)
  return (
    <ComboboxMultiAgrupado
      grupos={grupos}
      valor={valor}
      onEscolher={(v) => {
        setValor(v)
        onEscolher?.(v)
      }}
      substantivo="inversores"
    />
  )
}

/** O cabeçalho de grupo tem `aria-label`; a linha do inversor, não. É o que os separa. */
function inversoresVisiveis() {
  return screen.getAllByRole('checkbox').filter((b) => !b.hasAttribute('aria-label'))
}

function rotulosDeInversores() {
  return inversoresVisiveis().map((b) => (b.textContent ?? '').match(/Inv \d+/)?.[0] ?? '?')
}

function cabecalho(nome: RegExp) {
  return screen.getByRole('checkbox', { name: nome })
}

describe('ComboboxMultiAgrupado — o gesto de marcar o skid inteiro', () => {
  it('o gatilho fechado diz TRÊS verdades diferentes, e não uma contagem para tudo', () => {
    // 1. "não mexi": o inversor que entrar em operação no meio do período sai no arquivo.
    const a = render(<Agrupado inicial={null} />)
    expect(screen.getAllByRole('button')[0].textContent).toContain('todos · 24 inversores')
    a.unmount()

    // 2. a união EXATA de dois skids se chama pelo nome — é o que a pessoa pediu e é o que
    //    ela vai reconhecer na planilha.
    const b = render(<Agrupado inicial={[...TODOS_DO_SKID(2), ...TODOS_DO_SKID(3)]} />)
    expect(screen.getAllByRole('button')[0].textContent).toContain('Skid 2 e Skid 3 · 16 inversores')
    b.unmount()

    // 3. um skid pela metade derruba a forma toda: nome de skid só se escreve quando é
    //    inteiramente verdade.
    render(<Agrupado inicial={[...TODOS_DO_SKID(1), 's2-1']} />)
    expect(screen.getAllByRole('button')[0].textContent).toContain('9 de 24 inversores')
  })

  it('o cabeçalho do skid pela metade é `mixed` — e os vizinhos intactos dizem `false`', () => {
    render(<Agrupado inicial={['s2-1', 's2-2', 's2-3']} />)
    abrir()

    expect(cabecalho(/Skid 2/).getAttribute('aria-checked')).toBe('mixed')
    expect(cabecalho(/Skid 1/).getAttribute('aria-checked')).toBe('false')
    expect(cabecalho(/Skid 3/).getAttribute('aria-checked')).toBe('false')
    // E o nome acessível conta a história inteira: quantos, de quantos, e o que o toque faz.
    expect(cabecalho(/Skid 2/).getAttribute('aria-label')).toBe(
      'Skid 2 — 3 de 8 inversores marcados. marcar Skid 2 inteiro.',
    )
  })

  it('UM toque marca os oito inversores do skid; o segundo limpa', () => {
    const escolheu = vi.fn()
    render(<Agrupado inicial={[]} onEscolher={escolheu} />)
    abrir()

    fireEvent.click(cabecalho(/Skid 2/))
    expect(escolheu).toHaveBeenLastCalledWith(TODOS_DO_SKID(2))
    expect(screen.getAllByRole('button')[0].textContent).toContain('Skid 2 · 8 inversores')
    expect(cabecalho(/Skid 2/).getAttribute('aria-checked')).toBe('true')

    fireEvent.click(cabecalho(/Skid 2/))
    expect(escolheu).toHaveBeenLastCalledWith([])
    expect(cabecalho(/Skid 2/).getAttribute('aria-checked')).toBe('false')
  })

  it('a ordem congela na abertura: marcar não faz o item seguinte pular para o cursor', () => {
    render(<Agrupado inicial={['s1-3']} />)
    abrir()
    expect(rotulosDeInversores().slice(0, 3)).toEqual(['Inv 03', 'Inv 01', 'Inv 02'])

    fireEvent.click(screen.getByRole('checkbox', { name: /Inv 01/ }))
    expect(rotulosDeInversores().slice(0, 3)).toEqual(['Inv 03', 'Inv 01', 'Inv 02'])

    // Fechar e reabrir acomoda — aí sim, e só aí.
    abrir()
    abrir()
    expect(rotulosDeInversores().slice(0, 3)).toEqual(['Inv 01', 'Inv 03', 'Inv 02'])
  })

  it('buscar pelo número de série mantém o cabeçalho do skid que tem e esconde os outros dois', () => {
    render(<Agrupado inicial={[]} />)
    abrir()

    fireEvent.change(screen.getByPlaceholderText('Buscar…'), { target: { value: '5203' } })
    expect(screen.queryByRole('checkbox', { name: /Skid 1/ })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: /Skid 3/ })).toBeNull()
    expect(cabecalho(/Skid 2/)).toBeTruthy()
    expect(rotulosDeInversores()).toEqual(['Inv 11'])
  })

  it('durante a busca o cabeçalho DIZ e FAZ só o que está à vista — nada de escrita cega', () => {
    const escolheu = vi.fn()
    render(<Agrupado inicial={[]} onEscolher={escolheu} />)
    abrir()

    fireEvent.change(screen.getByPlaceholderText('Buscar…'), { target: { value: '530' } })
    expect(rotulosDeInversores()).toEqual(['Inv 17', 'Inv 18', 'Inv 19'])
    expect(screen.getByText('marcar os 3 encontrados')).toBeTruthy()

    fireEvent.click(cabecalho(/Skid 3/))
    // Três, e não os oito do skid: a pessoa vê três linhas e marca três.
    expect(escolheu).toHaveBeenLastCalledWith(['s3-1', 's3-2', 's3-3'])
  })

  it('o rodapé "todos" devolve `null`, e não a lista dos vinte e quatro', () => {
    const escolheu = vi.fn()
    render(<Agrupado inicial={TODOS_DO_SKID(1)} onEscolher={escolheu} />)
    abrir()

    fireEvent.click(screen.getByRole('button', { name: 'todos' }))
    expect(escolheu).toHaveBeenLastCalledWith(null)
    expect(escolheu).not.toHaveBeenCalledWith(expect.arrayContaining(['s1-1']))
    expect(screen.getAllByRole('button')[0].textContent).toContain('todos · 24 inversores')
  })

  it('desmarcar um inversor a partir de "todos" MATERIALIZA a lista dos 23', () => {
    const escolheu = vi.fn()
    render(<Agrupado inicial={null} onEscolher={escolheu} />)
    abrir()

    fireEvent.click(screen.getByRole('checkbox', { name: /Inv 11/ }))
    expect(escolheu).toHaveBeenLastCalledWith(expect.not.arrayContaining(['s2-3']))
    expect((escolheu.mock.calls.at(-1)?.[0] as string[]).length).toBe(23)
    // E o skid 2 deixou de ser inteiro, então o gatilho volta a contar.
    expect(screen.getAllByRole('button')[0].textContent).toContain('23 de 24 inversores')
  })

  /**
   * O inversor retirado é uma coisa que a usina não tem mais. Ele continua na lista com o
   * motivo (senão o cliente conclui que o portal não oferece), mas não entra na conta, não
   * entra em "todos" e o toque no cabeçalho não o arrasta para dentro de uma lista explícita
   * — pedir ao servidor uma série que não existe é pedir um arquivo que não vem.
   */
  it('a opção desabilitada fica fora da conta e fora do toque do cabeçalho', () => {
    const comRetirado: GrupoDeOpcoes[] = [
      SKIDS[0],
      {
        ...SKIDS[1],
        opcoes: [
          ...SKIDS[1].opcoes.slice(0, 7),
          {
            valor: 's2-8',
            rotulo: 'Inv 16',
            detalhe: 'retirado — sem leitura no período',
            desabilitada: true,
          },
        ],
      },
      SKIDS[2],
    ]
    const escolheu = vi.fn()
    render(<Agrupado grupos={comRetirado} inicial={[]} onEscolher={escolheu} />)
    expect(screen.getAllByRole('button')[0].textContent).toContain('0 de 23 inversores')

    abrir()
    expect(screen.getByText('retirado — sem leitura no período')).toBeTruthy()
    fireEvent.click(cabecalho(/Skid 2/))
    expect(escolheu).toHaveBeenLastCalledWith(TODOS_DO_SKID(2).slice(0, 7))
    expect(cabecalho(/Skid 2/).getAttribute('aria-checked')).toBe('true')

    // E o SEGUNDO toque limpa. Isto é o que a primeira mutação escapada ensinou: com a
    // desabilitada dentro do alvo, "já estão todos marcados?" nunca é verdade — a lista
    // final é filtrada e parece certa, mas o cabeçalho fica travado em marcar e nunca mais
    // limpa. A lista de saída sozinha não pegava isso; o segundo toque pega.
    fireEvent.click(cabecalho(/Skid 2/))
    expect(escolheu).toHaveBeenLastCalledWith([])
  })

  /**
   * O dono odeia chip, e a proibição não é de estilo: chip não escala, não se busca por
   * teclado e some no celular. A garantia aqui é lida do PRÓPRIO arquivo, porque o defeito
   * que ela guarda entra por cópia — alguém traz a faixa de caixinhas do meuWatt junto com
   * uma classe `rounded-full`, e nenhum `tsc` tem como perceber.
   */
  it('nenhuma pílula no vocabulário: o arquivo não tem `rounded-full` nem `pill`', () => {
    // Caminho a partir da raiz do portal (a pasta em que o vitest roda): sob o
    // transformador, `import.meta.url` não é uma URL de arquivo.
    const fonte = readFileSync('src/components/base.tsx', 'utf8')
    expect(fonte).not.toMatch(/rounded-full/)
    expect(fonte).not.toMatch(/\bpill\b/i)
  })
})
