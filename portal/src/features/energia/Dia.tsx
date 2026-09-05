/**
 * O DIA — a operação de uma data, do jeito que o operador a lê pela manhã.
 *
 * Cinco números no alto, a curva de potência contra a irradiância, as condições do dia, o
 * quadro por unidade consumidora e a lista de eventos.
 *
 * O que a sobreposição da curva mostra — e é o motivo de ela existir — é o DESCOLAMENTO:
 * sol firme com potência caindo é problema; as duas caindo juntas é nuvem. Uma curva
 * sozinha não distingue os dois casos.
 *
 * **Dia sem incidente não é dia sem dado.** A lista vazia sai em verde, dizendo "operação
 * sem incidentes" — misturá-la com o cinza de "não conseguimos ler" faria o cliente
 * concluir que a equipe não trabalhou quando o que houve foi rede.
 *
 * **PR descartado não é PR zero.** Quando o monitoramento descarta a leitura do dia, o
 * cartão escreve "descartada" e não desenha percentual nenhum.
 */

import {
  Aviso,
  Barra,
  CabecalhoCard,
  Cartao,
  GraficoLinha,
  Kpi,
  Num,
  Selo,
  Tabela,
  Vazio,
} from '@/components/base'
import { duracao, numero, porcento, potencia } from '@/lib/format'
import { energia } from '@/lib/format'

import type { Dia, EventoDoDia } from './api'
import { Faisca, SemDado, capacidade } from './graficos'

export function AbaDia({ dia }: { dia: Dia }) {
  const d = dia

  return (
    <>
      {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}

      {/* ───────────────────────────────────────────────── números do dia */}
      <Cartao>
        <CabecalhoCard rotulo="A operação do dia" />
        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-5">
          <Kpi rotulo="Gerado no dia" valor={energia(d.gerado_kwh)} tamanho="grande" />
          <Kpi
            rotulo="Pico de potência"
            valor={potencia(d.pico_kw)}
            tamanho="grande"
            detalhe={d.pico_hora ? `às ${d.pico_hora}` : undefined}
          />
          <Kpi
            rotulo="Potência agora"
            valor={potencia(d.potencia_agora_kw)}
            tamanho="grande"
            detalhe={
              d.inversores_gerando === null || d.inversores_total === null ? undefined : (
                <>
                  <Num>{d.inversores_gerando}</Num> de <Num>{d.inversores_total}</Num> inversores
                  gerando
                </>
              )
            }
          />
          <Kpi
            rotulo="Disponibilidade"
            valor={porcento(d.disponibilidade_pct, 2)}
            tamanho="grande"
          />
          {/* Descartada ≠ zero: a leitura existiu e o monitoramento a recusou. Escrever 0%
              aqui diria "a usina não rendeu", que é uma afirmação sobre a usina, não sobre
              o sensor. */}
          <Kpi
            rotulo="Performance ratio"
            valor={d.pr_descartado ? '—' : porcento(d.pr_pct)}
            tamanho="grande"
            detalhe={
              d.pr_descartado ? (
                <span className="text-tom-alerta">leitura descartada pelo monitoramento</span>
              ) : d.pr_pct === null ? (
                'sem irradiação medida'
              ) : undefined
            }
          />
        </div>
      </Cartao>

      {/* ───────────────────────────────────────────────── curva */}
      <Cartao>
        <CabecalhoCard rotulo="Potência e irradiância ao longo do dia" />
        {d.curva.length >= 2 ? (
          <>
            <GraficoLinha pontos={d.curva} />
            {!d.tem_estacao ? (
              <p className="mt-2 text-xs text-fraco">
                Esta usina não tem estação solarimétrica — só a potência é medida.
              </p>
            ) : null}
          </>
        ) : (
          <SemDado>Sem leitura de potência neste dia.</SemDado>
        )}
      </Cartao>

      {/* ───────────────────────────────────────────────── meteorologia */}
      {d.tem_estacao ? (
        <Cartao>
          <CabecalhoCard rotulo="Condições do dia" />
          <div className="grid gap-6 sm:grid-cols-3">
            <Kpi rotulo="Irradiância agora" valor={`${numero(d.hpoa_agora, 0)} W/m²`} />
            <Kpi
              rotulo="HPOA acumulada"
              valor={`${numero(d.hpoa_acumulada, 2)} kWh/m²`}
              detalhe="no plano dos módulos"
            />
            <Kpi
              rotulo="GHI acumulada"
              valor={`${numero(d.ghi_acumulada, 2)} kWh/m²`}
              detalhe="no plano horizontal"
            />
          </div>
        </Cartao>
      ) : null}

      {/* ───────────────────────────────────────────────── unidades */}
      <Cartao>
        <CabecalhoCard
          rotulo="Unidades consumidoras hoje"
          direita={d.ucs.length > 0 ? `${d.ucs.length} unidades` : undefined}
        />
        {d.ucs.length === 0 ? (
          <SemDado>O monitoramento não devolveu unidades consumidoras nesta usina.</SemDado>
        ) : (
          <div className="divide-y divide-borda-fraca">
            {d.ucs.map((u) => (
              <div key={u.indice} className="flex flex-wrap items-center gap-4 py-3 first:pt-0">
                <div className="min-w-[12rem] flex-1">
                  <div className="truncate text-sm text-forte">{u.nome}</div>
                  <div className="text-xs text-fraco">
                    {capacidade(u.kwp)} · <Num>{u.inversores}</Num>{' '}
                    {u.inversores === 1 ? 'inversor' : 'inversores'}
                  </div>
                </div>

                <div className="w-40">
                  <Num className="text-sm text-corpo">{potencia(u.potencia_agora_kw)}</Num>
                  {/* Barra só existe com percentual: uma barra vazia se lê como zero, e
                      "não sabemos quanto da capacidade está em uso" não é "nada em uso". */}
                  {u.pct_capacidade === null ? null : (
                    <div className="mt-1">
                      <Barra pct={u.pct_capacidade} tom="ok" />
                    </div>
                  )}
                </div>

                <div className="w-32">
                  <Faisca valores={u.faisca} />
                </div>

                <Num className="w-28 text-right text-sm text-corpo">{energia(u.energia_kwh)}</Num>

                <div className="w-24 text-right">
                  <Selo tom={u.total > 0 && u.ok === u.total ? 'ok' : 'alerta'}>
                    {u.ok} de {u.total} ok
                  </Selo>
                </div>
              </div>
            ))}
          </div>
        )}
        {d.faisca_horas.length >= 2 ? (
          <p className="mt-3 text-[11px] text-fraco">
            O traço cobre de {d.faisca_horas[0]} a {d.faisca_horas[d.faisca_horas.length - 1]}, em
            fatias de 15 minutos. Fatia sem leitura fica sem traço.
          </p>
        ) : null}
      </Cartao>

      {/* ───────────────────────────────────────────────── eventos */}
      <Cartao semPadding>
        <div className="p-5 pb-3">
          <CabecalhoCard
            rotulo="Eventos do dia"
            direita={d.eventos.length > 0 ? `${d.eventos.length} no dia` : undefined}
          />
        </div>
        <div className="px-2 pb-3">
          <Tabela<EventoDoDia>
            colunas={[
              { titulo: 'Hora', celula: (e) => <Num>{e.hora}</Num> },
              { titulo: 'Inversor', celula: (e) => e.inversor },
              { titulo: 'Evento', celula: (e) => e.evento },
              {
                titulo: 'Duração',
                alinhar: 'dir',
                celula: (e) => <Num>{duracao(e.duracao_min)}</Num>,
              },
              {
                titulo: 'Situação',
                celula: (e) =>
                  e.em_curso ? (
                    <Selo tom="parado">Em curso</Selo>
                  ) : e.resolvido_em ? (
                    <Selo tom="ok">Resolvido às {e.resolvido_em}</Selo>
                  ) : (
                    <Selo tom="semDados">Sem registro de fim</Selo>
                  ),
              },
            ]}
            linhas={d.eventos}
            chave={(e) => `${e.hora}-${e.inversor}-${e.evento}`}
            vazio={
              <div className="px-3 pb-3">
                <Vazio
                  tom="ok"
                  titulo="Operação sem incidentes"
                  descricao="Nenhum evento foi registrado nesta usina neste dia."
                />
              </div>
            }
          />
        </div>
      </Cartao>
    </>
  )
}
