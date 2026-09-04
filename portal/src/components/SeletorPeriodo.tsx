/**
 * Escolha de período — as duas formas que o portal usa.
 *
 * `SeletorPeriodo` é o par recorte + passo (Dia | Mês | Ano, e ‹ rótulo ›): é assim que o
 * cliente anda no tempo na tela de Energia e na de Paradas. Trocar o recorte MANTÉM a
 * referência: quem estava em agosto e pede o ano continua em 2026, e não é jogado para hoje.
 *
 * `SeletorCompetencias` é o intervalo de/até em `YYYY-MM`, do relatório de manutenção: ali a
 * pergunta não é "que mês", é "de quando até quando".
 *
 * Nos dois, o futuro é bloqueado na origem — o botão de avançar apaga e o "até" não passa do
 * mês corrente. Não há leitura do que ainda não aconteceu, e deixar avançar devolveria uma
 * tela vazia que se lê como falha do portal. O BFF recusa igualmente (`referencia não pode
 * ser futura`): a guarda daqui evita a viagem, a de lá vale para qualquer cliente da API.
 *
 * ⛔ Nada de calendário nativo (`<input type="date">`): ele não fala português em todo
 * navegador, ignora os tokens da marca e, no recorte de mês, ofereceria um dia que ninguém
 * pediu. Aqui a competência se escolhe numa lista pesquisável, como toda opção do produto.
 */

import { useMemo } from 'react'

import { Combobox, PassoPeriodo, Segmentado } from '@/components/base'
import { competencia as competenciaPorExtenso } from '@/lib/format'
import {
  competenciaDe,
  hojeIso,
  passaDeHoje,
  passo,
  passoCompetencia,
  rotuloDoPeriodo,
  type Recorte,
} from '@/lib/periodo'

const RECORTES: { valor: Recorte; rotulo: string }[] = [
  { valor: 'dia', rotulo: 'Dia' },
  { valor: 'mes', rotulo: 'Mês' },
  { valor: 'ano', rotulo: 'Ano' },
]

export function SeletorPeriodo({
  recorte,
  referencia,
  onRecorte,
  onReferencia,
  recortes,
}: {
  recorte: Recorte
  /** `YYYY-MM-DD` — o dia dentro do período escolhido. */
  referencia: string
  /** Ausente quando a tela tem um recorte só (Paradas usa Mês | Ano). */
  onRecorte?: (r: Recorte) => void
  onReferencia: (iso: string) => void
  /** Subconjunto dos recortes, na ordem em que devem aparecer. */
  recortes?: Recorte[]
}) {
  const opcoes = recortes ? RECORTES.filter((r) => recortes.includes(r.valor)) : RECORTES

  return (
    <div className="flex flex-wrap items-center gap-2">
      {onRecorte && opcoes.length > 1 ? (
        <Segmentado opcoes={opcoes} valor={recorte} onEscolher={onRecorte} />
      ) : null}
      <PassoPeriodo
        rotulo={rotuloDoPeriodo(referencia, recorte)}
        aoVoltar={() => onReferencia(passo(referencia, recorte, -1))}
        aoAvancar={() => onReferencia(passo(referencia, recorte, 1))}
        podeAvancar={!passaDeHoje(passo(referencia, recorte, 1), recorte)}
      />
    </div>
  )
}

/** As competências oferecidas, do mês corrente para trás. */
function competenciasAte(quantidade: number): string[] {
  const lista: string[] = []
  let atual = competenciaDe(hojeIso())
  for (let i = 0; i < quantidade; i += 1) {
    lista.push(atual)
    atual = passoCompetencia(atual, -1)
  }
  return lista
}

/**
 * Intervalo de competências (`YYYY-MM`).
 *
 * As duas listas se limitam entre si: o "de" nunca passa do "até", e o "até" nunca fica
 * antes do "de". Impedir aqui é melhor que receber o 400 do BFF — o cliente não tem culpa de
 * uma combinação que a tela mesmo ofereceu.
 */
export function SeletorCompetencias({
  de,
  ate,
  onDe,
  onAte,
  meses = 36,
}: {
  de: string
  ate: string
  onDe: (v: string) => void
  onAte: (v: string) => void
  /** Quantos meses para trás oferecer. O BFF aceita no máximo 24 meses de janela. */
  meses?: number
}) {
  const todas = useMemo(() => competenciasAte(meses), [meses])
  const rotulo = (c: string) => ({ valor: c, rotulo: competenciaPorExtenso(c) })

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-rotulo">de</span>
      <Combobox
        opcoes={todas.filter((c) => c <= ate).map(rotulo)}
        valor={de}
        onEscolher={onDe}
        placeholder="Mês inicial"
        className="w-52"
      />
      <span className="text-xs uppercase tracking-wide text-rotulo">até</span>
      <Combobox
        opcoes={todas.filter((c) => c >= de).map(rotulo)}
        valor={ate}
        onEscolher={onAte}
        placeholder="Mês final"
        className="w-52"
      />
    </div>
  )
}
