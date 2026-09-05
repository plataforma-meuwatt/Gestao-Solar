/**
 * O MÊS — a aba que o cliente corporativo abre primeiro.
 *
 * É a resposta completa a "o mês fechou como devia?", na mesma ordem do dashboard do
 * meuWatt: quanto se gerou (quatro medidas), como se rendeu (quatro indicadores), a
 * fórmula que sustenta o número contratual, os desvios, a conciliação com a conta de
 * energia, o dia a dia, o PR diário, o fechamento e as condições do mês.
 *
 * Três decisões que não devem ser "simplificadas" depois:
 *
 * **A fronteira parcial não vira perda.** Quando o medidor do ponto de entrega não cobre a
 * mesma usina que os inversores, o servidor manda `fronteira_parcial` e cala a perda. A
 * tela repete isso por escrito: o número continua sendo medição, mas a diferença para os
 * inversores NÃO é perda — chamá-la assim seria um diagnóstico inventado.
 *
 * **O previsto diz de onde veio.** O meuWatt esconde o card quando o número sai da
 * correção manual; aqui ele aparece com a procedência escrita. Esconder do cliente um
 * número que existe é pior do que mostrá-lo dizendo como foi obtido.
 *
 * **Desvio não é pintado.** O servidor não classifica desvio, e um limiar inventado aqui
 * pintaria de vermelho uma usina que o contrato considera em dia. Cor, neste produto,
 * significa estado — e estado quem decide é quem tem o dado inteiro.
 *
 * **O atingimento é IMPRESSO, não calculado.** `atingimento_pct` vem pronto, e é o mesmo
 * número que a tela de desempenho publica — mesma janela, mesma fonte, mesmo
 * arredondamento. Ele já foi refeito aqui (`100 + desvio`), e é assim que o mesmo portal
 * chegou a exibir 36% num lugar e 101,7% no outro para a mesma usina no mesmo ano. Junto
 * dele, a nota da janela diz sobre QUE período a conta foi feita — porque a pergunta
 * seguinte de quem lê um percentual é sempre "de quando?".
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

import type { Painel } from './api'
import {
  BarrasDoPeriodo,
  BarrasPr,
  BlocoMeteo,
  CartaoDesvios,
  CartaoRegra,
  NotaDaJanela,
  Rosca,
  SemDado,
  TabelaLonga,
  capacidade,
  comSinal,
  origemDoPrevisto,
  origemDoProjeto,
  previstoFoiCorrigido,
  tomDaConciliacao,
  type PontoDoPeriodo,
  type PontoPr,
} from './graficos'

export function AbaMes({ painel }: { painel: Painel }) {
  const p = painel
  const dias: PontoDoPeriodo[] = p.dias.map((d) => ({
    chave: d.data,
    rotulo: String(d.dia),
    medido: d.medido_kwh,
    projeto: d.projeto_kwh,
    futuro: d.futuro,
  }))
  const pr: PontoPr[] = p.dias
    .filter((d) => !d.futuro)
    .map((d) => ({
      chave: d.data,
      rotulo: String(d.dia),
      pr: d.pr_pct,
      descartado: d.pr_descartado,
    }))

  return (
    <>
      {p.aviso ? <Aviso>{p.aviso}</Aviso> : null}

      {/* ───────────────────────────────────────────────── geração */}
      <Cartao>
        <CabecalhoCard
          rotulo={`Quanto a usina gerou · ${p.rotulo}`}
          direita={
            p.em_curso
              ? p.dia_de_corte === null
                ? 'mês em curso'
                : `acumulado até o dia ${p.dia_de_corte}`
              : 'mês fechado'
          }
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

          {/* Sem medidor na fronteira o cartão não existe — nunca "0 MWh", e nunca o antigo
              `medido × 0,987`, que o próprio meuWatt removeu por ser um número inventado
              vestido de medição. */}
          {p.medido_fronteira_kwh === null ? null : (
            <div className="min-w-0">
              <Kpi
                rotulo="Medido (fronteira)"
                valor={energia(p.medido_fronteira_kwh)}
                tamanho="grande"
                detalhe={
                  p.fronteira_parcial ? (
                    'medição do ponto de entrega'
                  ) : p.perda_inv_fronteira_pct === null ? (
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

          {/* O número grande é a meta do MÊS INTEIRO — é ela que o cliente conhece do
              contrato. O denominador da comparação, porém, é o proporcional até o dia
              medido, e por isso ele vem escrito logo abaixo em vez de ficar implícito: sem
              essa linha, o "atingimento" do fechamento parece dividir por este número. */}
          <Kpi
            rotulo="Projeto (PVsyst)"
            valor={energia(p.projeto_kwh)}
            tamanho="grande"
            detalhe={
              <>
                {p.em_curso && p.dia_de_corte !== null && p.projeto_proporcional_kwh !== null ? (
                  <>
                    até o dia {p.dia_de_corte}{' '}
                    <Num>{energia(p.projeto_proporcional_kwh)}</Num> — é com este que o
                    medido é comparado
                  </>
                ) : (
                  'meta do projeto para o mês inteiro'
                )}
                {origemDoProjeto(p.projeto_origem) === null ? null : (
                  <span className="block">{origemDoProjeto(p.projeto_origem)}</span>
                )}
              </>
            }
          />

          {p.previsto_kwh === null ? null : (
            <Kpi
              rotulo={
                previstoFoiCorrigido(p.previsto_origem)
                  ? 'Previsto (irradiação medida)'
                  : 'Previsto'
              }
              valor={energia(p.previsto_kwh)}
              tamanho="grande"
              detalhe={origemDoPrevisto(p.previsto_origem)}
            />
          )}
        </div>

        {/* De onde saiu o acumulado — a mesma nota da aba Ano, a mesma peça. No mês ela
            costuma dizer uma linha só, e é justamente nos meses sem medição que ela evita
            a leitura de que a usina não gerou. */}
        <NotaDaJanela janela={p.janela} />
      </Cartao>

      {/* ───────────────────────────────────────────────── performance */}
      <Cartao>
        <CabecalhoCard rotulo="Como a usina rendeu" />
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

      {/* ───────────────────────────────────────────────── desvios e conta */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Cartao>
          <CabecalhoCard rotulo="Desvios do período" />
          <CartaoDesvios desvios={p.desvios} />
        </Cartao>

        <Cartao>
          <CabecalhoCard
            rotulo="Conta de energia"
            direita={`tolerância ±${numero(p.conciliacao.tolerancia_pct, 1)}%`}
          />
          {p.conciliacao.fronteira_mwh === null && p.conciliacao.faturado_mwh === null ? (
            <SemDado>
              Este mês não tem medição na fronteira nem fatura emitida para conferir.
            </SemDado>
          ) : (
            <>
              <div className="grid gap-6 sm:grid-cols-3">
                <Kpi
                  rotulo="Medido na fronteira"
                  valor={`${numero(p.conciliacao.fronteira_mwh, 1)} MWh`}
                />
                <Kpi
                  rotulo="Conta de energia"
                  valor={`${numero(p.conciliacao.faturado_mwh, 1)} MWh`}
                  detalhe={
                    p.conciliacao.faturado_mwh === null ? 'fatura ainda não emitida' : undefined
                  }
                />
                <Kpi
                  rotulo="Diferença"
                  valor={`${numero(p.conciliacao.diferenca_mwh, 1)} MWh`}
                  detalhe={
                    p.conciliacao.diferenca_pct === null ? undefined : (
                      <Num>{comSinal(p.conciliacao.diferenca_pct)}</Num>
                    )
                  }
                />
              </div>
              <div className="mt-4">
                {p.conciliacao.situacao ? (
                  <Selo tom={tomDaConciliacao(p.conciliacao.situacao)}>
                    {p.conciliacao.situacao}
                  </Selo>
                ) : p.fronteira_parcial ? (
                  <p className="text-xs text-fraco">
                    A medição da fronteira está incompleta neste período, então a conferência
                    com a distribuidora não é classificada — a diferença seria do medidor, não
                    da conta.
                  </p>
                ) : (
                  <p className="text-xs text-fraco">
                    Falta um dos dois lados para conferir. Fatura ainda não emitida é situação
                    normal no começo do mês seguinte.
                  </p>
                )}
              </div>
            </>
          )}
        </Cartao>
      </div>

      {/* ───────────────────────────────────────────────── dia a dia */}
      <Cartao>
        <CabecalhoCard rotulo="Geração dia a dia" />
        {dias.length > 0 ? (
          <BarrasDoPeriodo pontos={dias} />
        ) : (
          <SemDado>O monitoramento não devolveu geração diária para este mês.</SemDado>
        )}
      </Cartao>

      <Cartao>
        <CabecalhoCard rotulo="Performance ratio dia a dia" />
        {p.meteo.tem_estacao ? (
          pr.length > 0 ? (
            <BarrasPr
              pontos={pr}
              referencia={p.pr_pct}
              rotuloReferencia={`PR do mês (${porcento(p.pr_pct)})`}
            />
          ) : (
            <SemDado>Ainda não há dias medidos neste mês.</SemDado>
          )
        ) : (
          <SemDado>
            Esta usina não tem estação solarimétrica. Sem irradiação medida não há performance
            ratio — e desenhar zero diria que a usina não rendeu, que é outra coisa.
          </SemDado>
        )}
      </Cartao>

      {/* ───────────────────────────────────────────────── fechamento */}
      <Cartao>
        <CabecalhoCard rotulo={p.em_curso ? 'Fechamento até hoje' : 'Fechamento do mês'} />
        <div className="grid gap-6 lg:grid-cols-[auto,1fr]">
          {/* UMA casa decimal, como a tela de desempenho publica o mesmo percentual.
              Arredondar para inteiro aqui devolveria "44%" ao lado de um "44,4%" em outra
              tela do mesmo portal — a mesma pergunta com duas respostas, em miniatura. */}
          <Rosca
            pct={p.atingimento_pct}
            centro={porcento(p.atingimento_pct, 1)}
            detalhe={
              <>
                do que o projeto previa
                {p.em_curso && p.dia_de_corte !== null
                  ? ` até o dia ${p.dia_de_corte}`
                  : ' para o mês'}
                .
                {p.totais.tendencia_kwh === null ? null : (
                  <>
                    <br />
                    No ritmo atual, o mês fecha em{' '}
                    <Num className="text-ambar-texto">{energia(p.totais.tendencia_kwh)}</Num>.
                  </>
                )}
              </>
            }
          />

          <TabelaLonga
            colunas={[
              { chave: 'linha', titulo: 'Totais do mês', celula: (l: LinhaDeTotal) => l.titulo },
              {
                chave: 'valor',
                titulo: 'Energia',
                alinhar: 'dir',
                celula: (l) => <Num>{energia(l.valor)}</Num>,
              },
              {
                chave: 'contra',
                titulo: 'vs projeto',
                alinhar: 'dir',
                celula: (l) => <Num>{l.contra}</Num>,
              },
            ]}
            linhas={totaisDoMes(p)}
            chave={(l) => l.chave}
            destacar={(l) => l.chave === 'tendencia'}
          />
        </div>
      </Cartao>

      {/* ───────────────────────────────────────────────── meteorologia */}
      {p.meteo.tem_estacao ? (
        <Cartao>
          <CabecalhoCard rotulo={`Condições do mês · ${p.rotulo}`} />
          <BlocoMeteo meteo={p.meteo} rotuloDoGrafico="Irradiação e temperatura, dia a dia" />
        </Cartao>
      ) : null}
    </>
  )
}

type LinhaDeTotal = { chave: string; titulo: string; valor: number | null; contra: string }

/**
 * As duas linhas do fechamento — e elas são as MESMAS do cartão de geração lá em cima.
 *
 * O par comparado é sempre `totais.projeto_ate_hoje_kwh` × `totais.medido_kwh`, que é o par
 * de onde o servidor tirou `atingimento_pct` e `desvios.medido_vs_projeto_pct`. Quando o mês
 * está em curso, a meta do mês inteiro entra como uma TERCEIRA linha, marcada como alvo —
 * ela é o que o contrato promete, não o denominador de nada. Enquanto as duas dividiam a
 * mesma linha, a tabela trocava de referência conforme o mês estivesse aberto ou fechado.
 */
function totaisDoMes(p: Painel): LinhaDeTotal[] {
  const linhas: LinhaDeTotal[] = [
    {
      chave: 'projeto',
      titulo:
        p.em_curso && p.dia_de_corte !== null
          ? `Projeto até o dia ${p.dia_de_corte}`
          : 'Projeto (PVsyst)',
      valor: p.totais.projeto_ate_hoje_kwh,
      contra: 'referência',
    },
    {
      chave: 'medido',
      titulo: 'Medido (inversores)',
      valor: p.totais.medido_kwh,
      contra: comSinal(p.desvios.medido_vs_projeto_pct),
    },
  ]
  if (p.em_curso) {
    linhas.push({
      chave: 'alvo',
      titulo: 'Projeto do mês inteiro',
      valor: p.totais.projeto_kwh,
      contra: 'alvo',
    })
  }
  if (p.totais.tendencia_kwh !== null) {
    linhas.push({
      chave: 'tendencia',
      titulo: 'Tendência de fechamento',
      valor: p.totais.tendencia_kwh,
      contra: '—',
    })
  }
  return linhas
}
