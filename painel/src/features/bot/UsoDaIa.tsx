/**
 * Medidor de tokens do bot. O dono, 17/11/2026: "Quero que você instale um medidor de tokens e deixe isso para o
 * gestor" — "quero ter dados por dia, mês e tudo".
 *
 * Cada mensagem ao bot grava quantas vezes chamou a IA e os tokens que gastou (entrada, a parte dela que veio do
 * cache e saída). Aqui o total do período, e a mesma conta por dia, por mês e por pessoa. Antes de 17/11/2026 não há
 * número: o medidor nasceu nesse dia, e o cartão diz desde quando mede.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Cartao, Carregando, Erro, Vazio } from '@/components/base'
import type { UsoDoBot, UsoLinha } from '@/features/api'
import { quando } from '@/features/rotulos'
import { mensagemDeErro } from '@/lib/api'

const PERIODOS = { mes: 'Este mês', d30: '30 dias', ano: 'Este ano', tudo: 'Tudo' } as const
type Periodo = keyof typeof PERIODOS
const VISOES = { dia: 'Por dia', mes: 'Por mês', pessoa: 'Por pessoa' } as const
type Visao = keyof typeof VISOES

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function intervalo(p: Periodo): { de: string; ate: string } {
  const hoje = new Date()
  const ate = iso(hoje)
  if (p === 'mes') return { de: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), ate }
  if (p === 'd30') return { de: iso(new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate() - 29)), ate }
  if (p === 'ano') return { de: `${hoje.getFullYear()}-01-01`, ate }
  return { de: '2026-11-01', ate } // o medidor nasceu em 17/11/2026: antes não há número
}

const n = (v: number) => v.toLocaleString('pt-BR')

export function UsoDaIa({
  buscar,
  chave,
}: {
  buscar: (f: { de: string; ate: string }) => Promise<UsoDoBot>
  chave: unknown[]
}) {
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  const [visao, setVisao] = useState<Visao>('dia')
  const { data, isLoading, error } = useQuery({
    queryKey: [...chave, 'uso-da-ia', periodo],
    queryFn: () => buscar(intervalo(periodo)),
  })
  const linhas: UsoLinha[] = !data ? [] : visao === 'dia' ? data.por_dia : visao === 'mes' ? data.por_mes : data.por_pessoa
  const maior = Math.max(1, ...linhas.map((l) => l.total))

  return (
    <Cartao titulo="Uso da IA (tokens)">
      <div className="px-5 pb-5 grid gap-4">
        <div className="flex flex-wrap gap-2">
          {(Object.keys(PERIODOS) as Periodo[]).map((p) => (
            <button
              key={p}
              className={p === periodo ? 'btn-primario' : 'btn-secundario'}
              onClick={() => setPeriodo(p)}
            >
              {PERIODOS[p]}
            </button>
          ))}
        </div>
        {isLoading ? (
          <Carregando />
        ) : error ? (
          <Erro>{mensagemDeErro(error)}</Erro>
        ) : !data || !data.total.mensagens ? (
          <Vazio
            titulo="Nenhuma mensagem medida no período"
            descricao="O medidor anota cada mensagem ao bot desde 17/11/2026."
          />
        ) : (
          <>
            <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
              <Numero rotulo="Tokens no total" valor={n(data.total.total)} />
              <Numero rotulo="Entrada" valor={n(data.total.entrada)} nota={`${n(data.total.cache)} do cache`} />
              <Numero rotulo="Saída" valor={n(data.total.saida)} />
              <Numero
                rotulo="Mensagens"
                valor={n(data.total.mensagens)}
                nota={`${n(data.total.chamadas_ia)} chamadas à IA`}
              />
            </div>
            <p className="text-xs text-fraco">
              {data.de.split('-').reverse().join('/')} a {data.ate.split('-').reverse().join('/')} · medido desde{' '}
              {quando(data.medido_desde)}. Total = entrada + saída; o cache é a parte da entrada que a IA já tinha
              (sai mais barata).
            </p>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(VISOES) as Visao[]).map((v) => (
                <button key={v} className={v === visao ? 'btn-primario' : 'btn-secundario'} onClick={() => setVisao(v)}>
                  {VISOES[v]}
                </button>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-fraco">
                    <th className="py-1.5 pr-3 font-normal">{visao === 'pessoa' ? 'Pessoa' : visao === 'mes' ? 'Mês' : 'Dia'}</th>
                    <th className="py-1.5 pr-3 font-normal text-right">Mensagens</th>
                    <th className="py-1.5 pr-3 font-normal text-right">Entrada</th>
                    <th className="py-1.5 pr-3 font-normal text-right hidden sm:table-cell">Cache</th>
                    <th className="py-1.5 pr-3 font-normal text-right">Saída</th>
                    <th className="py-1.5 font-normal text-right">Total</th>
                    <th className="py-1.5 pl-3 font-normal w-1/4 hidden sm:table-cell" />
                  </tr>
                </thead>
                <tbody>
                  {linhas.map((l) => (
                    <tr key={l.chave} className="border-t border-borda">
                      <td className="py-1.5 pr-3 text-corpo">{l.rotulo}</td>
                      <td className="py-1.5 pr-3 text-right mono">{n(l.mensagens)}</td>
                      <td className="py-1.5 pr-3 text-right mono">{n(l.entrada)}</td>
                      <td className="py-1.5 pr-3 text-right mono text-fraco hidden sm:table-cell">{n(l.cache)}</td>
                      <td className="py-1.5 pr-3 text-right mono">{n(l.saida)}</td>
                      <td className="py-1.5 text-right mono text-forte">{n(l.total)}</td>
                      <td className="py-1.5 pl-3 hidden sm:table-cell">
                        <div className="h-2 rounded-full bg-superficie-alta">
                          <div className="h-2 rounded-full bg-ambar" style={{ width: `${(l.total / maior) * 100}%` }} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </Cartao>
  )
}

function Numero({ rotulo, valor, nota }: { rotulo: string; valor: string; nota?: string }) {
  return (
    <div className="rounded-campo border border-borda px-3.5 py-3">
      <p className="text-xs text-fraco">{rotulo}</p>
      <p className="mono text-lg text-forte">{valor}</p>
      {nota ? <p className="text-xs text-fraco">{nota}</p> : null}
    </div>
  )
}
