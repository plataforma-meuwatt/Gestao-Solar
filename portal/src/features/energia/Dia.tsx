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
 *
 * **A estação é um APARELHO, não uma leitura.** Existir (`tem_estacao`, que vem do cadastro)
 * e ter medido hoje (`estacao_com_leitura`) são duas perguntas, e a tela responde as duas
 * separadas. Enquanto eram uma só, um pedido às 3h da manhã fazia esta página afirmar "esta
 * usina não tem estação solarimétrica" sobre a mesma usina que na véspera mediu 7,1 kWh/m².
 * E quando o cadastro não pôde ser lido (`estacao_indefinida`), a tela não afirma nem uma
 * coisa nem outra: diz que não houve leitura, que é o que se sabe.
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

/**
 * O que a tela pode AFIRMAR sobre a estação solarimétrica desta usina.
 *
 * Três respostas, e só a primeira nega o aparelho — e ela exige o cadastro, nunca a
 * ausência de sol num dia. `null` significa "há estação e ela mediu": não há o que dizer.
 */
function recadoDaEstacao(d: Dia): string | null {
  if (d.estacao_com_leitura) return null
  if (d.estacao_indefinida) {
    return 'Não houve leitura de irradiância neste dia — e o cadastro dos aparelhos não pôde ser consultado agora.'
  }
  if (d.tem_estacao) {
    return 'A estação solarimétrica desta usina ainda não registrou leitura neste dia.'
  }
  return 'Esta usina não tem estação solarimétrica — só a potência é medida.'
}

export function AbaDia({ dia }: { dia: Dia }) {
  const d = dia
  const recadoEstacao = recadoDaEstacao(d)

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
                // Sem PR, o motivo é a estação — e o motivo certo depende de o aparelho
                // existir. "Sem irradiação medida" para todos os casos dizia a mesma coisa
                // para uma usina sem sensor e para uma manhã em que ainda não deu sol.
                (recadoEstacao ?? 'o monitoramento não devolveu o PR deste dia')
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
            {recadoEstacao === null ? null : (
              <p className="mt-2 text-xs text-fraco">{recadoEstacao}</p>
            )}
          </>
        ) : (
          <SemDado>Sem leitura de potência neste dia.</SemDado>
        )}
      </Cartao>

      {/* ───────────────────────────────────────────────── meteorologia */}
      {/* O bloco depende da LEITURA, não do cadastro: uma estação que existe e ainda não
          mediu renderia três travessões em fila, que não informam nada e ocupam o lugar do
          que informa. Quem diz que ela existe é o recado embaixo da curva. */}
      {d.estacao_com_leitura ? (
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
