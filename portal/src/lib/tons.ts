/**
 * Os seis tons de status. NÃO invente um sétimo: a mesma régua vale no meuWatt, no app e
 * no BFF, e cor nova aqui é cor que o cliente não sabe ler.
 *
 * As chaves são EXATAMENTE as que o BFF escreve em `tom` (`bff/app/api/v1/plants.py`,
 * `UsinaOut.tom`), e as mesmas do `tailwind.config.js` (`colors.tom`). A tela monta a
 * classe a partir do valor do servidor — `text-tom-${tom}` — sem tabela de tradução no
 * meio. Um nome que o servidor mandar e que não exista aqui vira `semDados`, nunca cor
 * errada nem classe inexistente.
 */

export const TONS = ['parado', 'alerta', 'multiplos', 'tempoRuim', 'ok', 'semDados'] as const

export type Tom = (typeof TONS)[number]

/** Normaliza o que veio do servidor para um dos seis tons. Desconhecido = sem dados. */
export function tons(valor: unknown): Tom {
  return (TONS as readonly string[]).includes(String(valor)) ? (valor as Tom) : 'semDados'
}

/** Classes do Tailwind para cada tom — listadas no `safelist`, então sempre existem. */
export function classesDoTom(valor: unknown) {
  const tom = tons(valor)
  return {
    tom,
    texto: `text-tom-${tom}`,
    fundo: `bg-tom-${tom}/10`,
    borda: `border-tom-${tom}/30`,
    fill: `fill-tom-${tom}`,
    stroke: `stroke-tom-${tom}`,
  }
}
