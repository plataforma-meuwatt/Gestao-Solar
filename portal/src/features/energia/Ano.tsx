/**
 * O ANO — o acumulado, mês a mês, e o tempo de pé de cada inversor.
 *
 * É a mesma pergunta do Mês numa escala maior, com dois blocos que só existem aqui: o
 * DETALHAMENTO MENSAL (a tabela que o cliente leva para a reunião) e a LINHA DO TEMPO por
 * inversor.
 *
 * A linha do tempo vem com um aviso que NÃO é enfeite e não pode ser removido para "limpar
 * a tela": ali a disponibilidade é TÉCNICA (quanto tempo o inversor ficou de pé) e os
 * cartões acima medem disponibilidade ENERGÉTICA (quanta energia se perdeu). Os dois
 * percentuais não batem, e publicá-los lado a lado sem dizer isso entregaria ao cliente
 * dois números contraditórios num documento de teor contratual. A frase vem escrita do
 * servidor, junto do dado.
 *
 * A disponibilidade de cada mês desta tabela é a MESMA que a aba Mês publica para aquele
 * mês: o BFF confere mês a mês em vez de usar o acumulado do monitoramento, justamente
 * porque os dois discordavam em pontos percentuais. Aqui não se recalcula nada.
 */

import {
  Aviso,
  CabecalhoCard,
  Cartao,
  Kpi,
  Num,
  Selo,
} from '@/components/base'
import { energia, numero, porcento } from '@/lib/format'

import type { MesDoAno, Painel } from './api'
import {
  BarrasDoPeriodo,
  BlocoMeteo,
  CartaoDesvios,
  CartaoRegra,
  LinhaDoTempo,
  SemDado,
  TabelaLonga,
  capacidade,
  comSinal,
  type PontoDoPeriodo,
} from './graficos'

/** Soma o que houver; nulo quando NENHUM mês tem o número — soma de nada não é zero. */
function soma(valores: (number | null)[]): number | null {
  const numeros = valores.filter((v): v is number => typeof v === 'number')
  return numeros.length > 0 ? numeros.reduce((a, b) => a + b, 0) : null
}

export function AbaAno({ painel }: { painel: Painel }) {
  const p = painel
  const meses: PontoDoPeriodo[] = p.meses.map((m) => ({
    chave: m.mes,
    rotulo: m.rotulo,
    medido: m.medido_kwh,
    projeto: m.projeto_kwh,
    futuro: m.futuro,
  }))
  const comConta = p.meses.filter(
    (m) => m.fronteira_mwh !== null || m.faturado_mwh !== null,
  )

  return (
    <>
      {p.aviso ? <Aviso>{p.aviso}</Aviso> : null}

      {/* ───────────────────────────────────────────────── geração */}
      <Cartao>
        <CabecalhoCard
          rotulo={`Quanto a usina gerou · ${p.rotulo}`}
          direita={p.em_curso ? 'acumulado do ano até hoje' : 'ano fechado'}
        />
        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            rotulo="Medido (inversores)"
            valor={energia(p.medido_inversores_kwh)}
            tamanho="grande"
            detalhe={
              p.produtividade_kwh_kwp === null ? undefined : (
                <>
                  <Num>{numero(p.produtividade_kwh_kwp, 1)}</Num> kWh por kWp instalado
                </>
              )
            }
          />

          {p.medido_fronteira_kwh === null ? null : (
            <div className="min-w-0">
              <Kpi
                rotulo="Medido (fronteira)"
                valor={energia(p.medido_fronteira_kwh)}
                tamanho="grande"
                detalhe={
                  p.fronteira_parcial || p.perda_inv_fronteira_pct === null ? (
                    'medição do ponto de entrega'
                  ) : (
                    <>
                      perda até a fronteira <Num>{porcento(p.perda_inv_fronteira_pct)}</Num>
                    </>
                  )
                }
              />
              {p.fronteira_parcial ? (
                <p className="mt-2 text-xs leading-snug text-tom-alerta">
                  O medidor do ponto de entrega não cobre o mesmo conjunto que os inversores
                  neste período. O número é medição de verdade, mas a diferença entre os dois
                  não é perda.
                </p>
              ) : null}
            </div>
          )}

          <Kpi
            rotulo="Projeto (PVsyst)"
            valor={energia(p.projeto_kwh)}
            tamanho="grande"
            detalhe={
              p.desvios.medido_vs_projeto_pct === null ? (
                'meta do projeto no período medido'
              ) : (
                <>
                  atingimento <Num>{porcento(100 + p.desvios.medido_vs_projeto_pct, 0)}</Num>
                </>
              )
            }
          />

          {p.previsto_kwh === null ? null : (
            <Kpi
              rotulo="Previsto (irradiação medida)"
              valor={energia(p.previsto_kwh)}
              tamanho="grande"
              detalhe={
                p.previsto_origem === 'manual_corrigido'
                  ? 'da meta mensal digitada no projeto, corrigida pela irradiação medida'
                  : 'da meta diária do projeto, corrigida pela irradiação medida'
              }
            />
          )}
        </div>
      </Cartao>

      {/* ───────────────────────────────────────────────── performance */}
      <Cartao>
        <CabecalhoCard rotulo="Como a usina rendeu no ano" />
        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            rotulo="Produtividade"
            valor={`${numero(p.produtividade_kwh_kwp, 1)} kWh/kWp`}
            detalhe={`instalados ${capacidade(p.capacidade_kwp)}`}
          />
          <Kpi
            rotulo="Performance ratio"
            valor={porcento(p.pr_pct)}
            detalhe={p.pr_pct === null ? 'sem irradiação medida no período' : undefined}
          />
          <Kpi rotulo="Disponibilidade real" valor={porcento(p.disponibilidade_real_pct, 2)} />
          <div className="min-w-0">
            <Kpi
              rotulo="Disponibilidade contratual"
              valor={porcento(p.disponibilidade_contratual_pct, 2)}
            />
            {p.paradas_pendentes > 0 ? (
              <div className="mt-2">
                <Selo tom="alerta">
                  {p.paradas_pendentes === 1
                    ? '1 parada ainda sem causa classificada'
                    : `${p.paradas_pendentes} paradas ainda sem causa classificada`}
                </Selo>
              </div>
            ) : null}
          </div>
        </div>

        <div className="mt-5">
          <CartaoRegra
            regra={p.regra}
            perdida={p.perdida_kwh}
            perdidaExterna={p.perdida_externa_kwh}
          />
        </div>
      </Cartao>

      {/* ───────────────────────────────────────────────── desvios */}
      <Cartao>
        <CabecalhoCard rotulo="Desvios do ano" />
        <CartaoDesvios desvios={p.desvios} />
      </Cartao>

      {/* ───────────────────────────────────────────────── barras mensais */}
      <Cartao>
        <CabecalhoCard rotulo="Geração mês a mês" />
        {meses.length > 0 ? (
          <BarrasDoPeriodo pontos={meses} />
        ) : (
          <SemDado>O monitoramento não devolveu geração mensal para este ano.</SemDado>
        )}
      </Cartao>

      {/* ───────────────────────────────────────────────── detalhamento */}
      <Cartao semPadding>
        <div className="p-5 pb-0">
          <CabecalhoCard rotulo="Detalhamento mensal" />
        </div>
        {p.meses.length === 0 ? (
          <div className="px-5 pb-5">
            <SemDado>Sem meses medidos neste ano.</SemDado>
          </div>
        ) : (
          <div className="px-2 pb-3">
            <TabelaLonga<MesDoAno>
              colunas={[
                {
                  chave: 'mes',
                  titulo: 'Mês',
                  celula: (m) => (
                    <span className="flex items-center gap-2">
                      {m.rotulo}
                      {m.em_curso ? <Selo tom="tempoRuim">em curso</Selo> : null}
                      {m.futuro ? <span className="text-xs text-fraco">ainda não</span> : null}
                    </span>
                  ),
                },
                {
                  chave: 'projeto',
                  titulo: 'Projeto',
                  alinhar: 'dir',
                  celula: (m) => <Num>{energia(m.projeto_kwh)}</Num>,
                },
                {
                  chave: 'medido',
                  titulo: 'Medido',
                  alinhar: 'dir',
                  celula: (m) => <Num>{energia(m.medido_kwh)}</Num>,
                },
                {
                  chave: 'desvio',
                  titulo: 'vs projeto',
                  alinhar: 'dir',
                  celula: (m) => <Num>{comSinal(m.desvio_vs_projeto_pct)}</Num>,
                },
                {
                  chave: 'pr',
                  titulo: 'PR',
                  alinhar: 'dir',
                  celula: (m) => <Num>{porcento(m.pr_pct)}</Num>,
                },
                {
                  chave: 'real',
                  titulo: 'Disp. real',
                  alinhar: 'dir',
                  celula: (m) => <Num>{porcento(m.disponibilidade_real_pct, 2)}</Num>,
                },
                {
                  chave: 'contratual',
                  titulo: 'Disp. contratual',
                  alinhar: 'dir',
                  celula: (m) => <Num>{porcento(m.disponibilidade_contratual_pct, 2)}</Num>,
                },
                {
                  chave: 'perdida',
                  titulo: 'Perdida',
                  alinhar: 'dir',
                  celula: (m) => <Num>{energia(m.perdida_kwh)}</Num>,
                },
              ]}
              linhas={p.meses}
              chave={(m) => m.mes}
              destacar={(m) => m.em_curso}
              rodape={[
                'Total do período',
                <Num key="t-projeto">{energia(soma(p.meses.map((m) => m.projeto_kwh)))}</Num>,
                <Num key="t-medido">{energia(soma(p.meses.map((m) => m.medido_kwh)))}</Num>,
                <Num key="t-desvio">{comSinal(p.desvios.medido_vs_projeto_pct)}</Num>,
                <Num key="t-pr">{porcento(p.pr_pct)}</Num>,
                <Num key="t-real">{porcento(p.disponibilidade_real_pct, 2)}</Num>,
                <Num key="t-contratual">{porcento(p.disponibilidade_contratual_pct, 2)}</Num>,
                <Num key="t-perdida">{energia(p.perdida_kwh)}</Num>,
              ]}
            />
          </div>
        )}
      </Cartao>

      {/* ───────────────────────────────────────────────── conta de energia */}
      <Cartao semPadding>
        <div className="p-5 pb-0">
          <CabecalhoCard
            rotulo="Conta de energia, mês a mês"
            direita={`tolerância ±${numero(p.conciliacao.tolerancia_pct, 1)}%`}
          />
        </div>
        {comConta.length === 0 ? (
          <div className="px-5 pb-5">
            <SemDado>
              Este ano não tem medição na fronteira nem fatura emitida para conferir.
            </SemDado>
          </div>
        ) : (
          <div className="px-2 pb-3">
            <TabelaLonga<MesDoAno>
              colunas={[
                { chave: 'mes', titulo: 'Mês', celula: (m) => m.rotulo },
                {
                  chave: 'fronteira',
                  titulo: 'Fronteira (MWh)',
                  alinhar: 'dir',
                  celula: (m) => <Num>{numero(m.fronteira_mwh, 1)}</Num>,
                },
                {
                  chave: 'faturado',
                  titulo: 'Conta (MWh)',
                  alinhar: 'dir',
                  celula: (m) => <Num>{numero(m.faturado_mwh, 1)}</Num>,
                },
                {
                  chave: 'delta',
                  titulo: 'Diferença (MWh)',
                  alinhar: 'dir',
                  celula: (m) => <Num>{diferencaDoMes(m)}</Num>,
                },
              ]}
              linhas={comConta}
              chave={(m) => m.mes}
              rodape={[
                'Total do período',
                <Num key="t-fronteira">
                  {numero(soma(comConta.map((m) => m.fronteira_mwh)), 1)}
                </Num>,
                <Num key="t-faturado">{numero(soma(comConta.map((m) => m.faturado_mwh)), 1)}</Num>,
                <Num key="t-delta">{'—'}</Num>,
              ]}
            />
            <p className="px-3 pt-2 text-xs text-fraco">
              Mês sem fatura na coluna é fatura ainda não emitida — situação normal enquanto a
              distribuidora não fecha a competência.
            </p>
          </div>
        )}
      </Cartao>

      {/* ───────────────────────────────────────────────── meteorologia */}
      {p.meteo.tem_estacao ? (
        <Cartao>
          <CabecalhoCard rotulo={`Condições do ano · ${p.rotulo}`} />
          <BlocoMeteo meteo={p.meteo} rotuloDoGrafico="Irradiação e temperatura, mês a mês" />

          {p.meteo.pontos.length > 0 ? (
            <div className="mt-5">
              <CabecalhoCard rotulo="Detalhamento meteorológico" />
              <TabelaLonga
                colunas={[
                  { chave: 'mes', titulo: 'Mês', celula: (m) => m.rotulo },
                  {
                    chave: 'hpoa',
                    titulo: 'HPOA',
                    alinhar: 'dir',
                    celula: (m) => <Num>{numero(m.hpoa, 1)}</Num>,
                  },
                  {
                    chave: 'hpoa-proj',
                    titulo: 'HPOA projeto',
                    alinhar: 'dir',
                    celula: (m) => <Num>{numero(m.hpoa_projeto, 1)}</Num>,
                  },
                  {
                    chave: 'ghi',
                    titulo: 'GHI',
                    alinhar: 'dir',
                    celula: (m) => <Num>{numero(m.ghi, 1)}</Num>,
                  },
                  {
                    chave: 't-amb',
                    titulo: 'T. ambiente',
                    alinhar: 'dir',
                    celula: (m) => <Num>{numero(m.t_amb, 1)}</Num>,
                  },
                  {
                    chave: 't-mod',
                    titulo: 'T. módulo',
                    alinhar: 'dir',
                    celula: (m) => <Num>{numero(m.t_mod, 1)}</Num>,
                  },
                  {
                    chave: 't-mod-max',
                    titulo: 'T. módulo máx.',
                    alinhar: 'dir',
                    celula: (m) => <Num>{numero(m.t_mod_max, 1)}</Num>,
                  },
                ]}
                linhas={p.meteo.pontos}
                chave={(m) => m.chave}
                rodape={[
                  'Acumulado do período',
                  <Num key="t-hpoa">{numero(p.meteo.hpoa, 1)}</Num>,
                  <Num key="t-hpoa-proj">{numero(p.meteo.hpoa_projeto, 1)}</Num>,
                  <Num key="t-ghi">{numero(p.meteo.ghi, 1)}</Num>,
                  <Num key="t-amb">{numero(p.meteo.t_amb_media, 1)}</Num>,
                  <Num key="t-mod">{numero(p.meteo.t_mod_media, 1)}</Num>,
                  <Num key="t-mod-max">{numero(p.meteo.t_mod_max, 1)}</Num>,
                ]}
              />
            </div>
          ) : null}
        </Cartao>
      ) : null}

      {/* ───────────────────────────────────────────────── tempo de pé */}
      {p.disponibilidade_tecnica ? (
        <Cartao>
          <CabecalhoCard
            rotulo="Tempo de pé, inversor por inversor"
            direita={`${p.disponibilidade_tecnica.primeiro_dia} a ${p.disponibilidade_tecnica.ultimo_dia}`}
          />
          {/* O aviso vem do servidor e é obrigatório: é ele que impede o cliente de ler dois
              percentuais contraditórios de disponibilidade na mesma tela. */}
          <div className="mb-4">
            <Aviso tom="semDados">{p.disponibilidade_tecnica.aviso}</Aviso>
          </div>
          <LinhaDoTempo inversores={p.disponibilidade_tecnica.inversores} />
        </Cartao>
      ) : null}
    </>
  )
}

/**
 * A diferença do mês entre a conta e a fronteira, em MWh e com sinal.
 *
 * É subtração de dois números que o servidor mediu — não um indicador novo. Fica em MWh de
 * propósito: um percentual precisaria escolher qual dos dois é o denominador, e essa
 * escolha é justamente o tipo de decisão que não se toma na tela.
 */
function diferencaDoMes(m: MesDoAno): string {
  if (m.fronteira_mwh === null || m.faturado_mwh === null) return '—'
  const delta = m.faturado_mwh - m.fronteira_mwh
  const sinal = delta < 0 ? '−' : '+'
  return `${sinal}${numero(Math.abs(delta), 1)}`
}
