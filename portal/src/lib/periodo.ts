/**
 * Datas de período — dia, mês, ano e competência (`YYYY-MM`).
 *
 * As datas viajam como `YYYY-MM-DD` e são construídas com `new Date(ano, mes, dia)`, que é
 * meia-noite LOCAL. `new Date('2026-08-15')` seria meia-noite UTC e, no fuso do Brasil,
 * voltaria 15 de agosto como dia 14 — o clássico erro de um dia a menos.
 *
 * **Futuro é bloqueado na origem.** Não há leitura do que ainda não aconteceu, e deixar
 * avançar devolveria uma tela de "sem dados" que se lê como falha do portal. O BFF também
 * recusa (`referencia não pode ser futura`) — as duas guardas existem de propósito: a
 * daqui evita a viagem, a de lá vale para qualquer cliente da API.
 */

export type Recorte = 'dia' | 'mes' | 'ano'

export const MESES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]
export const MESES_CURTOS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

/** `YYYY-MM-DD` → Date na meia-noite local. */
export function daData(iso: string): Date {
  const [a, m, d] = iso.split('-').map(Number)
  return new Date(a, m - 1, d)
}

/** Date → `YYYY-MM-DD`, sem passar por UTC. */
export function paraIso(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function hojeIso(): string {
  return paraIso(new Date())
}

/** `YYYY-MM` do dia informado (ou de hoje). */
export function competenciaDe(iso: string = hojeIso()): string {
  return iso.slice(0, 7)
}

/** `YYYY-MM` → primeiro dia do mês em `YYYY-MM-DD`. */
export function competenciaParaIso(yyyyMm: string): string {
  return `${yyyyMm}-01`
}

/** Rótulo do período escolhido, no formato que cada recorte pede. */
export function rotuloDoPeriodo(iso: string, recorte: Recorte): string {
  const d = daData(iso)
  if (recorte === 'ano') return String(d.getFullYear())
  if (recorte === 'mes') return `${MESES[d.getMonth()]} de ${d.getFullYear()}`
  if (iso === hojeIso()) return 'Hoje'
  return `${String(d.getDate()).padStart(2, '0')} de ${MESES_CURTOS[d.getMonth()]} de ${d.getFullYear()}`
}

/** Anda um passo no recorte. Passo de mês/ano preserva o dia 1 para não estourar mês curto. */
export function passo(iso: string, recorte: Recorte, direcao: 1 | -1): string {
  const d = daData(iso)
  if (recorte === 'dia') return paraIso(new Date(d.getFullYear(), d.getMonth(), d.getDate() + direcao))
  if (recorte === 'mes') return paraIso(new Date(d.getFullYear(), d.getMonth() + direcao, 1))
  return paraIso(new Date(d.getFullYear() + direcao, 0, 1))
}

/** O período escolhido contém uma data futura? */
export function passaDeHoje(iso: string, recorte: Recorte, hoje = new Date()): boolean {
  const d = daData(iso)
  if (recorte === 'ano') return d.getFullYear() > hoje.getFullYear()
  if (recorte === 'mes') {
    return (
      d.getFullYear() > hoje.getFullYear() ||
      (d.getFullYear() === hoje.getFullYear() && d.getMonth() > hoje.getMonth())
    )
  }
  return paraIso(d) > paraIso(hoje)
}

/** Passo de competência: `2026-08` → `2026-09` (ou `2026-07`). */
export function passoCompetencia(yyyyMm: string, direcao: 1 | -1): string {
  return competenciaDe(passo(competenciaParaIso(yyyyMm), 'mes', direcao))
}

/** Quantos meses de `de` até `ate`, inclusive. `2026-01`→`2026-12` = 12. */
export function mesesEntre(de: string, ate: string): number {
  const [a1, m1] = de.split('-').map(Number)
  const [a2, m2] = ate.split('-').map(Number)
  return (a2 - a1) * 12 + (m2 - m1) + 1
}
