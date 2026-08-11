/**
 * Formatação pt-BR: ponto de milhar, vírgula decimal. Regra global do produto — não
 * exiba número cru em lugar nenhum.
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
 * Duração em linguagem de gente: "3 h 20 min", "45 min", "2 d 4 h". É assim que a tela
 * de equipamento diz há quanto tempo ele está parado.
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

export function dataPorExtenso(iso: string): string {
  const d = new Date(iso)
  return `${d.getDate()} de ${MESES[d.getMonth()]} de ${d.getFullYear()}`
}

export function competencia(yyyyMm: string): string {
  const [ano, mes] = yyyyMm.split('-')
  const nome = MESES[Number(mes) - 1] ?? ''
  return `${nome.charAt(0).toUpperCase()}${nome.slice(1)} de ${ano}`
}

export function hora(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** Tempo relativo curto, para a lista de notificações. */
export function quando(iso: string, agora = new Date()): string {
  const min = Math.floor((agora.getTime() - new Date(iso).getTime()) / 60000)
  if (min < 1) return 'agora'
  if (min < 60) return `há ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `há ${h} h`
  const d = Math.floor(h / 24)
  return d === 1 ? 'ontem' : `há ${d} dias`
}
