/**
 * O formatador é o único lugar do portal que decide como um número aparece — e o teste
 * cobre exatamente as decisões que se perdem numa refatoração distraída:
 *
 * - **ausência vira "—", nunca zero.** "Não medimos" e "gerou zero" são afirmações
 *   diferentes, e a segunda custa caro numa reunião de contrato;
 * - **pt-BR de verdade** (ponto de milhar, vírgula decimal);
 * - **data pura não anda para trás.** `new Date('2026-08-21')` é meia-noite UTC e, no fuso
 *   do Brasil, imprime 20 de agosto — a data de uma OS sairia sempre um dia antes.
 */

import { describe, expect, it } from 'vitest'

import {
  competencia,
  competenciaCurta,
  dataCurta,
  dataPorExtenso,
  duracao,
  energia,
  inteiro,
  numero,
  porcento,
  potencia,
  quando,
} from '@/lib/format'

describe('números em pt-BR', () => {
  it('escreve com vírgula decimal e ponto de milhar', () => {
    expect(numero(29.87)).toBe('29,87')
    expect(numero(13800, 0)).toBe('13.800')
    expect(inteiro(1234)).toBe('1.234')
    expect(porcento(97.4)).toBe('97,4%')
  })

  it('devolve travessão para ausência — nunca zero', () => {
    expect(numero(null)).toBe('—')
    expect(numero(undefined)).toBe('—')
    expect(numero(Number.NaN)).toBe('—')
    expect(inteiro(null)).toBe('—')
    expect(porcento(null)).toBe('—')
    expect(energia(null)).toBe('—')
    expect(potencia(null)).toBe('—')
    expect(duracao(null)).toBe('—')
  })

  it('não confunde zero com ausência', () => {
    expect(numero(0)).toBe('0,00')
    expect(energia(0)).toBe('0,0 kWh')
  })
})

describe('energia e potência escolhem a unidade pela ordem de grandeza', () => {
  it('passa de kWh para MWh em 1000', () => {
    expect(energia(13800)).toBe('13,8 MWh')
    expect(energia(999)).toBe('999,0 kWh')
  })

  it('passa de kW para MW em 1000', () => {
    expect(potencia(2450)).toBe('2,45 MW')
    expect(potencia(870.4)).toBe('870,4 kW')
  })
})

describe('duração em linguagem de gente', () => {
  it('escreve minutos, horas e dias', () => {
    expect(duracao(45)).toBe('45 min')
    expect(duracao(200)).toBe('3 h 20 min')
    expect(duracao(180)).toBe('3 h')
    expect(duracao(52 * 60)).toBe('2 d 4 h')
  })
})

describe('datas', () => {
  it('lê data pura como dia de calendário, sem voltar um dia pelo fuso', () => {
    expect(dataPorExtenso('2026-08-21')).toBe('21 de agosto de 2026')
    expect(dataCurta('2026-08-21')).toBe('21/08/2026')
  })

  it('escreve competência por extenso e curta', () => {
    expect(competencia('2026-08')).toBe('Agosto de 2026')
    expect(competenciaCurta('2026-08')).toBe('ago/26')
    expect(competencia(null)).toBe('—')
  })

  it('mede o tempo relativo a partir de uma referência fixa', () => {
    const agora = new Date('2026-08-21T12:00:00Z')
    expect(quando('2026-08-21T11:30:00Z', agora)).toBe('há 30 min')
    expect(quando('2026-08-20T12:00:00Z', agora)).toBe('ontem')
    expect(quando(null, agora)).toBe('—')
  })
})
