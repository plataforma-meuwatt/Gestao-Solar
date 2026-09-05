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
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * A LINHA DE TOTAL FECHA COM O CARTÃO — e é por isso que ela não é somada aqui.
 *
 * Ela já foi: o rodapé somava as doze linhas da coluna enquanto o cartão do topo somava
 * outra janela, e o cliente que conferia a tabela com o dedo achava um terceiro número. Não
 * havia um errado entre eles; havia três perguntas parecidas com três respostas.
 *
 * Agora o rodapé IMPRIME o acumulado do servidor (`medido_inversores_kwh`,
 * `projeto_proporcional_kwh`, `atingimento_pct`) — os mesmos campos dos cartões, byte a
 * byte —, a linha diz sobre que meses ele foi somado, e o mês que ficou de fora do
 * acumulado continua VISÍVEL na tabela, marcado e com o motivo escrito. O cliente quer ver
 * o ano inteiro; o que ele não pode é somar a coluna e achar outro total.
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
  NotaDaJanela,
  SemDado,
  TabelaLonga,
  capacidade,
  comSinal,
  motivoDaExclusao,
  faixaDeChaves,
  origemDoPrevisto,
  origemDoProjeto,
  previstoFoiCorrigido,
  tomDaConciliacao,
  type PontoDoPeriodo,
} from './graficos'

/**
 * O rodapé de uma tabela cujo total NÃO é a soma de tudo o que se vê.
 *
 * Duas linhas na primeira célula: o que a soma é, e sobre que meses ela foi feita. Sem a
 * segunda, o rodapé volta a ser um total que parece não bater com a coluna.
 */
function TotalDe({ titulo, janela }: { titulo: string; janela: string | null }) {
  return (
    <span className="block">
      {titulo}
      <span className="mt-0.5 block text-xs font-normal text-fraco">
        {janela === null ? 'sem meses somados' : janela}
      </span>
    </span>
  )
}

/** A marca do mês que a tabela mostra mas o acumulado não somou — com o motivo do servidor. */
function ForaDaConta({ motivo }: { motivo: string | undefined }) {
  return (
    <Selo tom="semDados">
      fora da conta{motivo === undefined ? '' : ` · ${motivoDaExclusao(motivo)}`}
    </Selo>
  )
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
  /** O motivo de cada mês excluído, para a linha dele poder dizer por que ficou de fora. */
  const motivoDoMes = new Map(p.janela.fora.map((f) => [f.mes, f.motivo]))
  /** A conciliação tem janela PRÓPRIA (depende de a fatura existir) — e a declara. */
  const conciliados = new Set(p.conciliacao.meses)
  const noAcumulado = new Set(p.janela.meses)
  const origemDaMeta = origemDoProjeto(p.projeto_origem)

  return (
    <>
      {p.aviso ? <Aviso>{p.aviso}</Aviso> : null}

      {/* ───────────────────────────────────────────────── geração */}
      <Cartao>
        <CabecalhoCard
          rotulo={`Quanto a usina gerou · ${p.rotulo}`}
          direita={
            // O período dos números, no canto do cartão: não "o ano", e sim os meses que
            // entraram nele. É a primeira das duas vezes em que a tela diz isso; a segunda
            // é a nota da janela, no pé do mesmo cartão.
            p.janela.rotulo === null
              ? p.em_curso
                ? 'ano em curso'
                : 'ano fechado'
              : `acumulado · ${p.janela.rotulo}`
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
              {/* A JANELA DO MEDIDOR, quando ela é mais curta que a da geração. Em Porto
                  Ferreira este cartão dizia 1.132,9 MWh sob o rótulo "acumulado · jun a
                  set", e a coluna somava jul+ago+set: junho está na janela e não tem
                  medidor. O acumulado de geração declara a janela dele logo abaixo; este
                  precisava declarar a sua. */}
              {p.fronteira_meses.length > 0 &&
              p.fronteira_meses.length < p.janela.meses.length ? (
                <p className="mt-2 text-xs leading-snug text-fraco">
                  Só {faixaDeChaves(p.fronteira_meses)} tem leitura de medidor — os demais
                  meses do acumulado não entram nesta soma.
                </p>
              ) : null}
            </div>
          )}

          {/* O PAR do medido: a meta dos MESMOS meses. O atingimento vem pronto do
              servidor — é o mesmo número da tela de desempenho, e recalculá-lo aqui (de
              `100 + desvio`, como já foi) é como o portal exibia 36% num lugar e 101,7% no
              outro. */}
          <Kpi
            rotulo="Projeto (PVsyst)"
            valor={energia(p.projeto_proporcional_kwh)}
            tamanho="grande"
            detalhe={
              <>
                {p.atingimento_pct === null ? (
                  'a meta dos meses somados no acumulado'
                ) : (
                  <>
                    atingimento <Num>{porcento(p.atingimento_pct)}</Num>
                  </>
                )}
                {origemDaMeta === null ? null : (
                  <span className="block">{origemDaMeta}</span>
                )}
                {/* A meta do ano INTEIRO é outra pergunta, e só aparece quando é outro
                    número — no ano fechado as duas coincidem e repeti-la seria ruído. */}
                {p.janela.parcial && p.totais.projeto_kwh !== null ? (
                  <span className="block">
                    ano inteiro <Num>{energia(p.totais.projeto_kwh)}</Num>
                  </span>
                ) : null}
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

        <NotaDaJanela janela={p.janela} />
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
                    <span className="flex flex-wrap items-center gap-2">
                      {m.rotulo}
                      {m.em_curso ? <Selo tom="tempoRuim">em curso</Selo> : null}
                      {m.futuro ? <span className="text-xs text-fraco">ainda não</span> : null}
                      {/* O mês fora do acumulado continua na tabela — o cliente quer ver o
                          ano inteiro — mas dizendo que não entrou na conta, e por quê.
                          Sem a marca, a coluna some com o total e parece defeito da tela. */}
                      {!m.no_acumulado && !m.futuro ? (
                        <ForaDaConta motivo={motivoDoMes.get(m.mes)} />
                      ) : null}
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
                  // A origem só é escrita quando NÃO é a leitura do mês: `mes_conferido` é
                  // o mesmo número da aba Mês e não precisa de nota. O `rollup_do_ano` é a
                  // rede de segurança, e os dois discordam em centésimos no upstream — num
                  // número de teor contratual, a tela tem de poder dizer qual está ali.
                  celula: (m) => (
                    <>
                      <Num>{porcento(m.disponibilidade_real_pct, 2)}</Num>
                      {m.disponibilidade_origem === 'rollup_do_ano' ? (
                        <span className="block text-[11px] font-normal text-fraco">
                          do resumo do ano
                        </span>
                      ) : null}
                    </>
                  ),
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
              // O rodapé é o MESMO acumulado dos cartões do topo, campo por campo — não uma
              // segunda soma feita aqui. É esta linha que fecha a tela consigo mesma.
              rodape={[
                <TotalDe
                  key="t-titulo"
                  titulo="Total do período"
                  janela={p.janela.rotulo}
                />,
                <Num key="t-projeto">{energia(p.projeto_proporcional_kwh)}</Num>,
                <Num key="t-medido">{energia(p.medido_inversores_kwh)}</Num>,
                <Num key="t-desvio">{comSinal(p.desvios.medido_vs_projeto_pct)}</Num>,
                <Num key="t-pr">{porcento(p.pr_pct)}</Num>,
                <Num key="t-real">{porcento(p.disponibilidade_real_pct, 2)}</Num>,
                <Num key="t-contratual">{porcento(p.disponibilidade_contratual_pct, 2)}</Num>,
                <Num key="t-perdida">{energia(p.perdida_kwh)}</Num>,
              ]}
            />
            <p className="px-3 pt-2 text-xs leading-relaxed text-fraco">
              O total soma só os meses do acumulado — os marcados como fora da conta aparecem
              na tabela mas não entram nele, e é por isso que a coluna não fecha com o rodapé.
              Onde a disponibilidade diz "do resumo do ano", a leitura daquele mês não veio e o
              número saiu do resumo anual do monitoramento; os dois podem discordar em
              centésimos.
            </p>
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
                {
                  chave: 'mes',
                  titulo: 'Mês',
                  celula: (m) => (
                    <span className="flex flex-wrap items-center gap-2">
                      {m.rotulo}
                      {/* A conferência só existe onde há os DOIS lados. O mês com só um
                          deles continua visível — e dizendo que não foi conferido. */}
                      {conciliados.has(m.mes) ? null : (
                        <Selo tom="semDados">não conferido</Selo>
                      )}
                    </span>
                  ),
                },
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
                  titulo: 'Fronteira − conta (MWh)',
                  alinhar: 'dir',
                  celula: (m) => <Num>{diferencaDoMes(m)}</Num>,
                },
              ]}
              linhas={comConta}
              chave={(m) => m.mes}
              // O rodapé é a CONCILIAÇÃO do servidor, que soma só os meses com os dois
              // lados — e não a coluna inteira. Somar um mês cuja fatura a distribuidora
              // ainda nem emitiu inventaria uma divergência do tamanho daquele mês.
              rodape={[
                <TotalDe
                  key="t-titulo"
                  titulo="Total conferido"
                  janela={faixaDeChaves(p.conciliacao.meses)}
                />,
                <Num key="t-fronteira">{numero(p.conciliacao.fronteira_mwh, 1)}</Num>,
                <Num key="t-faturado">{numero(p.conciliacao.faturado_mwh, 1)}</Num>,
                <Num key="t-delta">{numero(p.conciliacao.diferenca_mwh, 1)}</Num>,
              ]}
            />
            <div className="px-3 pt-3">
              {p.conciliacao.situacao ? (
                <Selo tom={tomDaConciliacao(p.conciliacao.situacao)}>
                  {p.conciliacao.situacao}
                  {p.conciliacao.diferenca_pct === null
                    ? ''
                    : ` · ${comSinal(p.conciliacao.diferenca_pct)}`}
                </Selo>
              ) : null}
            </div>
            <p className="px-3 pt-2 text-xs leading-relaxed text-fraco">
              Mês sem fatura na coluna é fatura ainda não emitida — situação normal enquanto a
              distribuidora não fecha a competência. O total confere só os meses com os dois
              lados; os marcados como não conferidos ficam de fora dele.
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
                  {
                    chave: 'mes',
                    titulo: 'Mês',
                    celula: (m) => (
                      <span className="flex flex-wrap items-center gap-2">
                        {m.rotulo}
                        {/* Mesma janela dos cartões: a média e o acumulado do rodapé saem
                            dos meses do acumulado, e o mês fora dele aparece marcado em vez
                            de sumir da tabela. */}
                        {noAcumulado.has(m.chave) ? null : (
                          <Selo tom="semDados">fora da conta</Selo>
                        )}
                      </span>
                    ),
                  },
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
                    /* A PARCELA do sol de projeto no plano horizontal. O cartão publicava
                       `GHI 969,5 · projeto 988,2 kWh/m²` — e o desvio de −1,9 % saía dele —
                       com esta tabela sem uma única coluna de onde os 988,2 pudessem ter
                       vindo. Total sem parcela visível é o mesmo defeito que o HPOA tinha. */
                    chave: 'ghi-proj',
                    titulo: 'GHI projeto',
                    alinhar: 'dir',
                    celula: (m) => <Num>{numero(m.ghi_projeto, 1)}</Num>,
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
                  <TotalDe
                    key="t-titulo"
                    titulo="Acumulado do período"
                    janela={p.janela.rotulo}
                  />,
                  <Num key="t-hpoa">{numero(p.meteo.hpoa, 1)}</Num>,
                  <Num key="t-hpoa-proj">{numero(p.meteo.hpoa_projeto, 1)}</Num>,
                  <Num key="t-ghi">{numero(p.meteo.ghi, 1)}</Num>,
                  <Num key="t-ghi-proj">{numero(p.meteo.ghi_projeto, 1)}</Num>,
                  <Num key="t-amb">{numero(p.meteo.t_amb_media, 1)}</Num>,
                  <Num key="t-mod">{numero(p.meteo.t_mod_media, 1)}</Num>,
                  <Num key="t-mod-max">{numero(p.meteo.t_mod_max, 1)}</Num>,
                ]}
              />
              {/* A referência de irradiação só sai quando cobre TODOS os meses do
                  acumulado. Quando ela some, some junto o desvio de sol — e é melhor não
                  ter a comparação do que tê-la com quatro meses de referência contra sete
                  de medição, que foi como esta tela já publicou "+176% de sol". */}
              {p.meteo.hpoa_projeto === null ? (
                <p className="px-3 pt-2 text-xs leading-relaxed text-fraco">
                  Sem referência de irradiação do projeto para todos os meses do acumulado, a
                  coluna de HPOA do projeto fica sem total: comparar sol medido de um período
                  com projeto de outro não é comparação.
                </p>
              ) : null}
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
 * A diferença do mês, **fronteira − conta**, em MWh e com sinal.
 *
 * É subtração de dois números que o servidor mediu — não um indicador novo. Fica em MWh de
 * propósito: um percentual precisaria escolher qual dos dois é o denominador, e essa
 * escolha é justamente o tipo de decisão que não se toma na tela.
 *
 * A ORDEM da subtração é a do servidor (`conciliacao.diferenca_mwh` = fronteira − faturado),
 * e não uma escolha daqui. Ela já foi invertida: a coluna subtraía num sentido e o rodapé
 * viria no outro, e a mesma diferença apareceria com dois sinais na mesma tabela.
 */
function diferencaDoMes(m: MesDoAno): string {
  if (m.fronteira_mwh === null || m.faturado_mwh === null) return '—'
  const delta = m.fronteira_mwh - m.faturado_mwh
  const sinal = delta < 0 ? '−' : '+'
  return `${sinal}${numero(Math.abs(delta), 1)}`
}
