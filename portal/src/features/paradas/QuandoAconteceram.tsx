/**
 * Quando as paradas aconteceram — uma barra por dia do período.
 *
 * **É o que a tabela esconde.** Vinte e quatro linhas de "19 min · 0,1 kWh · Resolvida" são
 * quase idênticas e se leem como uma parede: o cliente conclui "a usina vive parando". O
 * desenho por dia responde outra coisa, e é a que importa — as vinte e quatro caem em três
 * dias, o que é um evento, não um padrão. Mesma informação, leitura oposta.
 *
 * Três regras, e as três vêm da REGRA 0:
 *
 * **Dia sem parada é um traço de 1px, não uma barra de altura zero.** As duas se pareceriam
 * na tela, mas "não houve parada" e "houve uma parada de duração desprezível" são
 * afirmações diferentes — e é a primeira que é a boa notícia.
 *
 * **Parada sem duração não entra na altura.** O BFF já recusa somar pela metade (o total do
 * cartão vem nulo quando alguma veio sem o tempo); repetir a soma aqui com as que têm faria
 * o desenho afirmar um número menor do que o real. O dia que tem parada sem duração ganha a
 * marca de "houve parada" e o `title` diz que o tempo não foi informado.
 *
 * **Dia que ainda não aconteceu não é dia sem parada.** Os dias futuros do mês corrente
 * saem numa região hachurada e nomeada, e não como trinta traços vazios enfileirados:
 * trinta marcas de "nada aqui" é ruído; uma região que se explica é informação.
 *
 * A agregação é do CLIENTE, e isso é legítimo: ela não cria medição nenhuma, só junta por
 * dia o que o servidor mandou parada a parada. O que ela nunca faz é preencher lacuna.
 */

import { duracao, inteiro } from '@/lib/format'
import type { Parada } from '@/features/paradas/api'

type Dia = {
  /** `YYYY-MM-DD` — a chave, e o que vai no `title`. */
  dia: string
  /** O número do dia no mês, para o eixo. */
  numero: number
  /** Quantas paradas começaram neste dia. */
  quantas: number
  /** Minutos somados das que têm duração. Nulo quando NENHUMA delas tem. */
  minutos: number | null
  /** Alguma parada deste dia veio sem duração — a barra mente para menos. */
  incompleto: boolean
  /** O dia ainda não aconteceu. */
  futuro: boolean
}

/** `2026-09-04T13:21:00Z` → `2026-09-04`, no fuso de quem lê. */
function diaDe(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  const mes = String(d.getMonth() + 1).padStart(2, '0')
  const dia = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mes}-${dia}`
}

/** Os dias do período, do primeiro ao último, com o que caiu em cada um. */
function montarDias(paradas: Parada[], inicio: string, fim: string, hoje: string): Dia[] {
  const de = new Date(`${inicio.slice(0, 10)}T12:00:00`)
  const ate = new Date(`${fim.slice(0, 10)}T12:00:00`)
  if (Number.isNaN(de.getTime()) || Number.isNaN(ate.getTime())) return []

  const porDia = new Map<string, Parada[]>()
  for (const p of paradas) {
    const chave = diaDe(p.inicio)
    const lista = porDia.get(chave)
    if (lista) lista.push(p)
    else porDia.set(chave, [p])
  }

  const dias: Dia[] = []
  // Teto de segurança: o recorte "ano" traria 365 barras de 2px, ilegíveis. Quem passa
  // disso cai fora do desenho, e o componente devolve vazio (ver `QuandoAconteceram`).
  for (let d = new Date(de); d <= ate && dias.length <= 366; d.setDate(d.getDate() + 1)) {
    const mes = String(d.getMonth() + 1).padStart(2, '0')
    const numero = d.getDate()
    const chave = `${d.getFullYear()}-${mes}-${String(numero).padStart(2, '0')}`
    const doDia = porDia.get(chave) ?? []
    const comDuracao = doDia.filter((p) => p.duracao_min !== null)
    dias.push({
      dia: chave,
      numero,
      quantas: doDia.length,
      minutos: comDuracao.length
        ? comDuracao.reduce((soma, p) => soma + (p.duracao_min as number), 0)
        : null,
      incompleto: doDia.length > comDuracao.length,
      futuro: chave > hoje,
    })
  }
  return dias
}

export function QuandoAconteceram({
  paradas,
  inicio,
  fim,
  hoje,
}: {
  paradas: Parada[]
  inicio: string
  fim: string
  hoje: string
}) {
  const dias = montarDias(paradas, inicio, fim, hoje)
  // Mais que um mês e meio de barras vira serrilhado sem leitura. O recorte "ano" tem a
  // tabela, que responde a mesma pergunta sem prometer um desenho que não se lê.
  if (dias.length === 0 || dias.length > 45) return null

  const passados = dias.filter((d) => !d.futuro)
  const futuros = dias.filter((d) => d.futuro)
  // Só os dias COM tempo entram na escala. Tratar o dia sem duração informada como zero
  // funcionaria para o cálculo, mas escreveria na tela a afirmação de que ele não teve
  // parada — e é a linha que a REGRA 0 existe para não deixar ninguém cruzar sem perceber.
  const medidos = passados.map((d) => d.minutos).filter((m): m is number => m !== null)
  const maximo = medidos.length ? Math.max(...medidos) : 0
  const ALTURA = 120

  return (
    <div>
      <div className="flex items-end gap-[3px]" style={{ height: ALTURA }}>
        {passados.map((d) => {
          const altura = maximo > 0 && d.minutos !== null ? (d.minutos / maximo) * ALTURA : 0
          const titulo =
            d.quantas === 0
              ? `Dia ${d.numero}: nenhuma parada`
              : `Dia ${d.numero}: ${inteiro(d.quantas)} ${
                  d.quantas === 1 ? 'parada' : 'paradas'
                } · ${d.incompleto ? 'alguma sem o tempo informado' : duracao(d.minutos)}`
          return (
            <div key={d.dia} title={titulo} className="flex flex-1 items-end justify-center">
              {d.quantas === 0 ? (
                // O traço: o dia existe e não teve parada. Uma barra de altura zero diria
                // o mesmo desenho para "não houve" e para "houve e durou quase nada".
                <span aria-hidden className="h-px w-full bg-borda-forte" />
              ) : (
                <span
                  aria-hidden
                  className="w-full rounded-t-[2px] bg-tom-alerta"
                  style={{ height: Math.max(3, altura) }}
                />
              )}
            </div>
          )
        })}
        {futuros.length > 0 ? (
          <div
            className="flex items-end self-stretch rounded-[3px]"
            style={{
              flex: futuros.length,
              backgroundImage:
                'repeating-linear-gradient(135deg, rgba(255,255,255,.035) 0 6px, transparent 6px 12px)',
            }}
          >
            <span className="mono w-full px-2 pb-1 text-center text-[calc(11px_+_var(--passo-tipo))] text-fraco">
              {futuros.length === 1
                ? `dia ${futuros[0].numero} · ainda não aconteceu`
                : `dias ${futuros[0].numero} a ${futuros[futuros.length - 1].numero} · ainda não aconteceram`}
            </span>
          </div>
        ) : null}
      </div>

      <div aria-hidden className="mt-1 h-px w-full bg-borda-forte" />

      {/* O eixo só a cada três dias: um rótulo por dia vira uma faixa cinza ilegível. */}
      <div className="mt-1.5 flex gap-[3px]">
        {passados.map((d, i) => (
          <span key={d.dia} className="mono flex-1 text-center text-[calc(10px_+_var(--passo-tipo))] text-fraco">
            {i % 3 === 0 ? d.numero : ''}
          </span>
        ))}
        {futuros.length > 0 ? <span style={{ flex: futuros.length }} /> : null}
      </div>
    </div>
  )
}
