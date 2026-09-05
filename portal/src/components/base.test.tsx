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
 */

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Combobox, ComboboxMulti, opcao, type Opcao } from '@/components/base'

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
