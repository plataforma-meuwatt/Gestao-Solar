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

/**
 * Classes do Tailwind para cada tom — listadas no `safelist`, então sempre existem.
 *
 * **A escada de alfa é fechada, e é aqui que ela tem nome.** Só os degraus do `safelist` do
 * `tailwind.config.js` viram CSS: um `bg-tom-${tom}/6` montado com um alfa fora da lista não
 * emite classe nenhuma e o elemento sai sem fundo, sem erro em lugar nenhum — nem no `tsc`,
 * nem no console, nem na revisão do diff. Por isso a tela nunca escreve o alfa: ela pede o
 * papel (`fundoFraco`, `realce`, `bordaForte`), e quem sabe a correspondência é este arquivo.
 *
 * Os papéis, e onde nasceram:
 *
 * - `fundo` (/10) e `borda` (/30) — a receita do `Selo`, a mais antiga e a mais usada;
 * - `fundoFraco` (/6) — a base de cartão e faixa inteiros, onde /10 já pinta demais;
 * - `realce` (/16) — o quadrado do contador dentro de uma faixa que já usa `fundoFraco`;
 * - `bordaForte` (/40) — a borda do botão destrutivo (`Desconectar`), que precisa pesar mais
 *   que a borda de um cartão sem virar um botão vermelho chapado;
 * - `meio` (/55) — a metade de uma barra dividida, onde as duas partes são do MESMO tom e o
 *   que as separa é a intensidade (pendência vencida cheia × no prazo a meio caminho).
 */
export function classesDoTom(valor: unknown) {
  const tom = tons(valor)
  return {
    tom,
    texto: `text-tom-${tom}`,
    fundo: `bg-tom-${tom}/10`,
    borda: `border-tom-${tom}/30`,
    fundoFraco: `bg-tom-${tom}/6`,
    realce: `bg-tom-${tom}/16`,
    bordaForte: `border-tom-${tom}/40`,
    meio: `bg-tom-${tom}/55`,
    fill: `fill-tom-${tom}`,
    stroke: `stroke-tom-${tom}`,
  }
}
