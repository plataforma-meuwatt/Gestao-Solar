/**
 * A fita dos doze meses do contrato — a resposta de "estou em dia?" numa olhada.
 *
 * Ela existe por causa de uma tela concreta: o Cronograma abria com **quinze cabeçalhos de
 * bloco cinza-chapado, recolhidos, e as doze colunas de mês vazias**. Nenhuma das 269 marcas
 * do contrato aparecia; 94 % da altura da tabela era um bloco cinza. O cliente não via nem o
 * mês que fechou 13 de 13. A matriz continua existindo (é o "X" que o dono nomeou), mas ela
 * passou a ser o detalhe, atrás de um clique — e este é o primeiro parágrafo da tela.
 *
 * **Quatro estados desenhados, e o futuro NÃO é um deles.**
 *
 * - `cumprido` — mês fechado dentro da vigência, sem nenhuma atividade atrasada (verde);
 * - `andamento` — o mês corrente, que ainda tem dias pela frente (âmbar);
 * - `atraso` — há atividade atrasada neste mês (vermelho), e isso ganha de qualquer outro
 *   estado: um mês corrente com atraso é um mês com atraso;
 * - `futuro` — **sem cor nenhuma**. Um mês que ainda não venceu não é falha, não é pendência
 *   e não é alerta; pintá-lo de qualquer cor de status é acusar o prestador por um serviço
 *   cuja data ainda não chegou. A ausência de cor é a informação.
 * - `sem-previsao` — o contrato não prevê nada ali. Também sem cor, e com a palavra escrita:
 *   um mês vazio pintado de verde diria "cumprimos", quando não havia o que cumprir.
 *
 * **A cor nunca é a única legenda.** Cada bloco imprime a palavra do estado e os números
 * ("13 de 13"), porque este quadro é lido em reunião e muitas vezes projetado — e porque um
 * percentual sem denominador é como se lê 41,9 % como se fosse do ano todo.
 *
 * Os números `previsto`/`cumprido` vêm do **recorte de vigência do meuPlano**; a contagem de
 * atrasadas vem da matriz (é a única fonte que as localiza por mês, e é a mesma que pinta a
 * célula de vermelho). Nada é somado aqui.
 */

import { Num } from '@/components/base'
import { competenciaCurta, inteiro } from '@/lib/format'
import { classesDoTom, type Tom } from '@/lib/tons'

/** Um mês da fita, já com a contagem de atrasadas que só a matriz sabe dar. */
export type MesDaFita = {
  mes: string
  /** `fechado` · `corrente` · `futuro` — o vocabulário do meuPlano, cru. */
  situacao: string | null
  previsto: number | null
  cumprido: number | null
  atrasadas: number
}

export type EstadoDoMes = 'atraso' | 'andamento' | 'cumprido' | 'futuro' | 'sem-previsao'

/**
 * O estado desenhado de um mês.
 *
 * A ordem das perguntas é a decisão: **atraso primeiro**, porque um mês corrente que já
 * acumulou atividade vencida é um mês com atraso — e esconder isso atrás de "em andamento"
 * é o tipo de eufemismo que faz o cliente descobrir o problema tarde demais.
 *
 * `sem-previsao` vem antes de `fechado` pelo motivo simétrico: um mês em que o contrato não
 * previa nada não "cumpriu" coisa alguma, e verde ali seria cumprimento fabricado.
 */
export function estadoDoMes(m: MesDaFita): EstadoDoMes {
  if (m.atrasadas > 0) return 'atraso'
  if (m.previsto === 0) return 'sem-previsao'
  if (m.situacao === 'corrente') return 'andamento'
  if (m.situacao === 'fechado') return 'cumprido'
  if (m.situacao === 'futuro') return 'futuro'
  // Situação que o meuPlano invente amanhã: sem cor e sem palpite, nunca uma cor errada.
  return 'sem-previsao'
}

/** O tom de status do estado — `null` quando o estado é, de propósito, SEM cor. */
export function tomDoEstado(estado: EstadoDoMes): Tom | null {
  if (estado === 'atraso') return 'parado'
  if (estado === 'andamento') return 'alerta'
  if (estado === 'cumprido') return 'ok'
  return null
}

const PALAVRA: Record<EstadoDoMes, string> = {
  atraso: 'com atraso',
  andamento: 'em andamento',
  cumprido: 'cumprido',
  futuro: 'ainda não venceu',
  'sem-previsao': 'sem previsão',
}

/** A frase inteira do bloco — vai no `title` e no `aria-label`. */
function frase(m: MesDaFita, estado: EstadoDoMes): string {
  const quando = competenciaCurta(m.mes)
  if (estado === 'sem-previsao') return `${quando}: o contrato não prevê atividade`
  const contagem = `${inteiro(m.cumprido)} de ${inteiro(m.previsto)} cumpridas`
  if (estado === 'atraso') {
    const n = inteiro(m.atrasadas)
    return `${quando}: ${contagem} — ${n} ${m.atrasadas === 1 ? 'atrasada' : 'atrasadas'}`
  }
  return `${quando}: ${contagem} — ${PALAVRA[estado]}`
}

export default function FitaDosMeses({ meses }: { meses: MesDaFita[] }) {
  if (meses.length === 0) return null
  return (
    <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-12">
      {meses.map((m) => {
        const estado = estadoDoMes(m)
        const tom = tomDoEstado(estado)
        const c = tom ? classesDoTom(tom) : null
        // Sem cor de status o bloco não fica invisível: ele usa a superfície do produto,
        // e usa o token PURO. O modificador de opacidade do Tailwind sobre um token
        // declarado como `rgba(...)` SUBSTITUI o alfa dele em vez de multiplicar — era o
        // que produzia o cinza chapado, cinco vezes mais claro que o token, na antiga faixa
        // de bloco desta tela. A regra que proíbe isso está em `scripts/regra0.mjs`, e é ela
        // que recusa esta linha se alguém acrescentar um `/NN` aqui.
        const moldura = c ? `${c.borda} ${c.fundo}` : 'border-borda bg-superficie'
        const barra = c ? `bg-tom-${c.tom}` : 'bg-superficie-destacada'
        const contagem = estado === 'sem-previsao' ? null : (
          <span className="mt-1.5 block text-sm text-corpo">
            <Num>{inteiro(m.cumprido)}</Num> de <Num>{inteiro(m.previsto)}</Num>
          </span>
        )
        return (
          <li
            key={m.mes}
            data-mes={m.mes}
            data-estado={estado}
            title={frase(m, estado)}
            aria-label={frase(m, estado)}
            className={`rounded-campo border px-2.5 py-2 ${moldura}`}
          >
            <span className="block text-xs uppercase tracking-wide text-rotulo">
              {competenciaCurta(m.mes)}
            </span>
            <span aria-hidden className={`mt-1.5 block h-1 rounded-barra ${barra}`} />
            {contagem}
            <span className={`mt-0.5 block text-xs ${c ? c.texto : 'text-fraco'}`}>
              {PALAVRA[estado]}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
