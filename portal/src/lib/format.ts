/**
 * Formatação pt-BR: ponto de milhar, vírgula decimal. Regra global do produto — não
 * exiba número cru em lugar nenhum. Porte 1:1 de `app/src/lib/format.ts`, para o site e
 * o aplicativo escreverem o mesmo número do mesmo jeito.
 *
 * Nulo, indefinido e NaN viram "—" em TODAS as funções: "não sabemos" e "zero" são coisas
 * diferentes, e zero se lê como a segunda.
 */

export function numero(valor: number | null | undefined, casas = 2): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return '—'
  return valor.toLocaleString('pt-BR', {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  })
}

export function inteiro(valor: number | null | undefined): string {
  return numero(valor, 0)
}

export function porcento(valor: number | null | undefined, casas = 1): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return '—'
  return `${numero(valor, casas)}%`
}

export function moeda(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return '—'
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

/** Energia com a unidade escolhida pela ordem de grandeza: kWh abaixo de 1 MWh. */
export function energia(kwh: number | null | undefined): string {
  if (kwh === null || kwh === undefined || Number.isNaN(kwh)) return '—'
  return kwh >= 1000 ? `${numero(kwh / 1000, 1)} MWh` : `${numero(kwh, 1)} kWh`
}

export function potencia(kw: number | null | undefined): string {
  if (kw === null || kw === undefined || Number.isNaN(kw)) return '—'
  return kw >= 1000 ? `${numero(kw / 1000, 2)} MW` : `${numero(kw, 1)} kW`
}

/**
 * Duração em linguagem de gente: "3 h 20 min", "45 min", "2 d 4 h". É assim que se diz
 * quanto tempo uma usina ficou parada ou quanto durou a execução de uma OS.
 */
export function duracao(minutos: number | null | undefined): string {
  if (minutos === null || minutos === undefined || minutos < 0) return '—'
  if (minutos < 60) return `${Math.round(minutos)} min`
  const horas = Math.floor(minutos / 60)
  if (horas < 24) {
    const resto = Math.round(minutos % 60)
    return resto ? `${horas} h ${resto} min` : `${horas} h`
  }
  const dias = Math.floor(horas / 24)
  const restoH = horas % 24
  return restoH ? `${dias} d ${restoH} h` : `${dias} d`
}

const MESES = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
]

export const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

/**
 * "21 de agosto de 2026".
 *
 * Aceita as duas formas que o BFF manda, e a distinção não é preciosismo: `new Date`
 * lê **"2026-08-21" como UTC meia-noite** e `getDate()` responde em hora local. No
 * Brasil (UTC−3) isso volta três horas e imprime **20** de agosto — a data de
 * agendamento de uma OS sairia sempre um dia antes do combinado. Data pura é dia de
 * calendário, sem fuso; só o timestamp completo tem instante para converter.
 */
export function dataPorExtenso(iso: string | null | undefined): string {
  if (!iso) return '—'
  const soData = /^\d{4}-\d{2}-\d{2}$/.test(iso)
  const d = soData
    ? new Date(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))
    : new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getDate()} de ${MESES[d.getMonth()]} de ${d.getFullYear()}`
}

/** "Agosto de 2026" a partir de `YYYY-MM`. */
export function competencia(yyyyMm: string | null | undefined): string {
  if (!yyyyMm) return '—'
  const [ano, mes] = yyyyMm.split('-')
  const nome = MESES[Number(mes) - 1] ?? ''
  if (!nome) return '—'
  return `${nome.charAt(0).toUpperCase()}${nome.slice(1)} de ${ano}`
}

/** "ago/26" — o rótulo curto que cabe numa coluna de cronograma ou num eixo. */
export function competenciaCurta(yyyyMm: string | null | undefined): string {
  if (!yyyyMm) return '—'
  const [ano, mes] = yyyyMm.split('-')
  const nome = MESES_CURTOS[Number(mes) - 1]
  if (!nome) return '—'
  return `${nome}/${ano.slice(2)}`
}

export function hora(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/**
 * Dia e hora curtos, para históricos onde a data importa tanto quanto o horário.
 * Uma lista de paradas atravessa semanas: só a hora faria dois eventos de dias diferentes
 * parecerem o mesmo minuto.
 */
export function dataHora(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const dia = String(d.getDate()).padStart(2, '0')
  const mes = String(d.getMonth() + 1).padStart(2, '0')
  return `${dia}/${mes} ${hora(iso)}`
}

/** "21/08/2026" — data curta de tabela. Aceita data pura e timestamp, sem o erro de fuso. */
export function dataCurta(iso: string | null | undefined): string {
  if (!iso) return '—'
  const soData = /^\d{4}-\d{2}-\d{2}$/.test(iso)
  const d = soData
    ? new Date(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))
    : new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const dia = String(d.getDate()).padStart(2, '0')
  const mes = String(d.getMonth() + 1).padStart(2, '0')
  return `${dia}/${mes}/${d.getFullYear()}`
}

/** Tempo relativo curto, para "última atividade" e afins. */
export function quando(iso: string | null | undefined, agora = new Date()): string {
  if (!iso) return '—'
  const instante = new Date(iso).getTime()
  if (Number.isNaN(instante)) return '—'
  const min = Math.floor((agora.getTime() - instante) / 60000)
  if (min < 1) return 'agora'
  if (min < 60) return `há ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `há ${h} h`
  const d = Math.floor(h / 24)
  return d === 1 ? 'ontem' : `há ${d} dias`
}
