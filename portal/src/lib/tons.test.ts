/**
 * Os seis tons são um contrato com o BFF: a tela monta `text-tom-${tom}` a partir do que o
 * servidor mandou. Duas coisas têm de continuar verdadeiras, e é isto que o teste guarda:
 *
 * - **um nome desconhecido vira `semDados`** — nunca uma classe inexistente (que sairia sem
 *   cor nenhuma) nem a cor errada;
 * - **não existe um sétimo tom.** Acrescentar um aqui sem acrescentá-lo no `tailwind.config`
 *   e no BFF produz exatamente o bug silencioso acima.
 */

import { describe, expect, it } from 'vitest'

import { TONS, classesDoTom, tons } from '@/lib/tons'

describe('tons de status', () => {
  it('aceita os seis nomes que o BFF escreve', () => {
    for (const t of TONS) expect(tons(t)).toBe(t)
    expect(TONS).toHaveLength(6)
    expect([...TONS]).toEqual(['parado', 'alerta', 'multiplos', 'tempoRuim', 'ok', 'semDados'])
  })

  it('cai em semDados para qualquer coisa que não conheça', () => {
    expect(tons('x')).toBe('semDados')
    expect(tons(null)).toBe('semDados')
    expect(tons(undefined)).toBe('semDados')
    expect(tons('OK')).toBe('semDados') // caixa diferente é outro nome
  })

  it('monta as classes do Tailwind que estão na safelist', () => {
    expect(classesDoTom('parado')).toMatchObject({
      tom: 'parado',
      texto: 'text-tom-parado',
      fundo: 'bg-tom-parado/10',
      borda: 'border-tom-parado/30',
    })
    expect(classesDoTom('inventado').texto).toBe('text-tom-semDados')
  })
})
