/**
 * Energia da usina — UMA pergunta: **gerei o que era esperado?**
 *
 * A tela é a resposta em três alturas, de cima para baixo:
 *
 * 1. **De relance** — o que a usina faz agora, hoje, no mês e no ano, cada período contra a
 *    meta do projeto (o PVsyst cadastrado no meuWatt). Sem meta, o portal DIZ "sem meta
 *    cadastrada": inventar régua é pior que não ter régua.
 * 2. **Por que** — PR, disponibilidade real e contratual e a energia perdida em paradas, com
 *    o caminho para a lista de paradas do período.
 * 3. **Como foi** — a curva do dia (com irradiação quando há estação), as barras do mês ou do
 *    ano com o esperado sobreposto, e os últimos 24 meses contra a meta e contra o ano
 *    anterior.
 *
 * Duas decisões que não devem ser "simplificadas" depois:
 *
 * **Uma referência só.** Dia, Mês e Ano andam no MESMO ponto do tempo: quem foi ver o dia 12
 * de março e troca para Mês continua em março. Dois relógios na mesma tela fariam o cliente
 * comparar períodos diferentes sem perceber.
 *
 * **Ausência nunca vira zero.** Todo número passa pelos formatadores de `lib/format`, que
 * escrevem "—" para nulo, e ponto sem leitura não vira barra rasteira no gráfico. "Não
 * medimos" e "não gerou" são afirmações diferentes, e a segunda vale dinheiro numa reunião de
 * contrato.
 *
 * Fora do escopo por desenho: aparelho a aparelho, relé, string e comparativo interno. Isso é
 * análise de manutenção — trabalho da equipe, na ferramenta da equipe. Aqui o cliente
 * corporativo vê energia.
 */

import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  Aviso,
  Barra,
  Botao,
  CabecalhoCard,
  Cartao,
  Esqueleto,
  GraficoBarras,
  GraficoHistorico,
  GraficoLinha,
  Kpi,
  LinhaNavegacao,
  Num,
  Pagina,
  Selo,
  Tela4Estados,
  Vazio,
  type MesDoHistorico,
  type PontoBarra,
} from '@/components/base'
import { SeletorPeriodo } from '@/components/SeletorPeriodo'
import { competenciaCurta, energia, numero, porcento, potencia } from '@/lib/format'
import { hojeIso, rotuloDoPeriodo, type Recorte } from '@/lib/periodo'
import type { Leitura } from '@/lib/leitura'
import {
  ehUsinaAusente,
  useCurva,
  useDesempenho,
  useGeracao,
  useHistorico,
  useUsinaDetalhe,
  type Desempenho,
  type UsinaDetalhe,
} from './api'

/**
 * Capacidade instalada — kWp abaixo de 1 MWp, MWp acima.
 *
 * `potencia()` de `lib/format` não serve: ela escreveria "3,00 MW" onde a unidade é MWp, e
 * potência instantânea e capacidade instalada são grandezas que ninguém deve confundir numa
 * tela que compara as duas lado a lado. Se uma segunda tela precisar disto, sobe para
 * `lib/format`.
 */
function capacidade(kwp: number | null): string {
  if (kwp === null) return '—'
  return kwp >= 1000 ? `${numero(kwp / 1000, 2)} MWp` : `${numero(kwp, 1)} kWp`
}

/**
 * Um bloco que depende da própria leitura: esqueleto, erro com "Tentar de novo", conteúdo.
 *
 * O quarto estado (offline) fica no nível da PÁGINA — quando a rede cai, cai para todas as
 * leituras ao mesmo tempo, e repetir o selo em cada cartão viraria ruído sobre o mesmo fato.
 */
function Bloco<T>({
  leitura,
  altura = 200,
  children,
}: {
  leitura: Leitura<T>
  altura?: number
  children: (dados: T) => ReactNode
}) {
  if (leitura.carregando) return <Esqueleto altura={altura} />
  if (leitura.dados === null) {
    return (
      <div>
        <p className="text-sm text-tom-parado">
          {leitura.erro ?? 'O servidor não devolveu dados para este período.'}
        </p>
        <div className="mt-3">
          <Botao variante="secundario" onClick={leitura.recarregar}>
            Tentar de novo
          </Botao>
        </div>
      </div>
    )
  }
  return <>{children(leitura.dados)}</>
}

/**
 * O KPI de um período contra a meta do projeto.
 *
 * O tom e a frase (`Dentro do esperado`, `Sem meta de projeto cadastrada`) vêm do SERVIDOR —
 * a régua de 95%/85% é a mesma do BFF, do aplicativo e do meuWatt, e recalculá-la aqui criaria
 * uma segunda verdade sobre a mesma usina.
 */
function KpiDoPeriodo({
  rotulo,
  periodo,
  leitura,
}: {
  rotulo: string
  periodo: string
  leitura: Leitura<Desempenho>
}) {
  if (leitura.carregando) {
    return (
      <div>
        <div className="text-xs uppercase tracking-wide text-rotulo">{rotulo}</div>
        <div className="mt-2">
          <Esqueleto altura={34} largura="70%" />
        </div>
      </div>
    )
  }

  const d = leitura.dados
  if (d === null) {
    return (
      <Kpi
        rotulo={rotulo}
        valor="—"
        tamanho="grande"
        detalhe={<span className="text-tom-parado">{leitura.erro ?? 'Não deu para ler.'}</span>}
      />
    )
  }

  return (
    <div className="min-w-0">
      <Kpi
        rotulo={rotulo}
        valor={energia(d.energia_kwh)}
        tamanho="grande"
        detalhe={
          d.pct_do_projeto === null ? (
            periodo
          ) : (
            <>
              {periodo} · esperado <Num>{energia(d.esperado_projeto_kwh)}</Num>
            </>
          )
        }
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Selo tom={d.tom}>
          {d.pct_do_projeto === null ? d.situacao : `${porcento(d.pct_do_projeto)} do projeto`}
        </Selo>
        {d.pct_do_projeto === null ? null : (
          <span className="text-xs text-fraco">{d.situacao}</span>
        )}
      </div>
    </div>
  )
}

export default function Usina() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const idUsina = Number(id)
  const valida = Number.isFinite(idUsina) && idUsina > 0

  // Uma referência só para os três recortes — ver o cabeçalho do arquivo.
  const [recorte, setRecorte] = useState<Recorte>('dia')
  const [referencia, setReferencia] = useState<string>(hojeIso())

  const usina = useUsinaDetalhe(idUsina, valida)
  const mes = useDesempenho(idUsina, 'mes', referencia, valida)
  const ano = useDesempenho(idUsina, 'ano', referencia, valida)
  const geracao = useGeracao(idUsina, recorte, referencia, valida)
  const curva = useCurva(idUsina, referencia, valida && recorte === 'dia')
  const historico = useHistorico(idUsina, 24, valida)

  /**
   * As barras do período.
   *
   * No recorte MÊS cada barra é um dia, e o esperado NÃO é sobreposto: a meta do projeto é
   * mensal, e reparti-la por dia inventaria uma expectativa diária que ninguém cadastrou.
   *
   * No recorte ANO o eixo vem dos meses do desempenho (que já traz a meta de cada um), e a
   * altura de cada barra é o medido do mesmo mês. Mês sem leitura fica NULO — sem barra, e
   * não uma barra no chão.
   */
  const barras: PontoBarra[] = useMemo(() => {
    const pontos = geracao.dados?.pontos ?? []
    if (recorte !== 'ano') {
      return pontos.map((p) => ({ rotulo: p.rotulo, valor: p.kwh }))
    }
    const medido = new Map(pontos.map((p) => [p.chave, p.kwh]))
    const meses = ano.dados?.meses ?? []
    if (meses.length === 0) {
      return pontos.map((p) => ({ rotulo: p.rotulo, valor: p.kwh }))
    }
    return meses.map((m) => ({
      rotulo: competenciaCurta(m.mes),
      valor: medido.get(m.mes) ?? m.energia_kwh,
      esperado: m.esperado_projeto_kwh,
    }))
  }, [recorte, geracao.dados, ano.dados])

  const serieLonga: MesDoHistorico[] = useMemo(
    () =>
      (historico.dados?.meses ?? []).map((m) => ({
        mes: m.mes,
        rotulo: competenciaCurta(m.mes),
        medido: m.energia_kwh,
        esperado: m.esperado_projeto_kwh,
        anoAnterior: m.ano_anterior_kwh,
      })),
    [historico.dados],
  )

  if (!valida) {
    return (
      <Pagina titulo="Energia">
        <Vazio
          titulo="Usina não encontrada"
          descricao="O endereço não aponta para uma usina. Escolha uma usina na barra do topo."
        />
      </Pagina>
    )
  }

  // 404 do BFF (fora do escopo, ou usina sem monitoramento): vazio que explica, nunca erro
  // vermelho com "Tentar de novo" — repetir não faz a usina aparecer.
  if (ehUsinaAusente(usina)) {
    return (
      <Pagina titulo="Energia">
        <Vazio titulo="Usina não encontrada" descricao={usina.erro ?? undefined} />
      </Pagina>
    )
  }

  const nome = usina.dados?.nome
  const local = [usina.dados?.cidade, usina.dados?.uf].filter(Boolean).join(', ')
  const periodoMes = rotuloDoPeriodo(referencia, 'mes')
  const periodoAno = rotuloDoPeriodo(referencia, 'ano')

  return (
    <Pagina
      titulo={nome ?? 'Energia'}
      subtitulo={
        <>
          Energia
          {local ? ` · ${local}` : ''}
          {/* A capacidade só entra quando o cadastro tem: "— kWp" no subtítulo é ruído. */}
          {usina.dados && usina.dados.capacidade_kwp !== null
            ? ` · ${capacidade(usina.dados.capacidade_kwp)}`
            : ''}
        </>
      }
      acoes={usina.dados ? <Selo tom={usina.dados.tom}>{usina.dados.situacao}</Selo> : null}
    >
      <Tela4Estados leitura={usina}>
        {(u: UsinaDetalhe) => (
          <>
            {u.aviso ? <Aviso>{u.aviso}</Aviso> : null}

            <Cartao>
              <CabecalhoCard
                rotulo="Gerou o esperado?"
                direita={u.fora_da_janela_solar ? 'fora da janela solar' : undefined}
              />
              <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
                <div className="min-w-0">
                  <Kpi
                    rotulo="Agora"
                    valor={potencia(u.potencia_kw)}
                    tamanho="grande"
                    detalhe={`de ${capacidade(u.capacidade_kwp)}`}
                  />
                  {/* A barra só existe quando HÁ percentual: uma barra vazia se lê como zero,
                      e "não sabemos quanto da capacidade está em uso" não é "nada em uso". */}
                  {u.pct_capacidade === null ? null : (
                    <div className="mt-3 max-w-[12rem]">
                      <div className="mb-1 text-xs text-fraco">
                        <Num>{porcento(u.pct_capacidade, 0)}</Num> da capacidade
                      </div>
                      <Barra pct={u.pct_capacidade} tom={u.tom} />
                    </div>
                  )}
                </div>

                {/* "Hoje" é HOJE, e não o dia escolhido no seletor: é o único número desta
                    faixa que não anda no tempo, e o rótulo diz isso. O dia escolhido tem a
                    curva logo abaixo — é lá que se olha um dia passado. */}
                <Kpi
                  rotulo="Hoje"
                  valor={energia(u.energia_hoje_kwh)}
                  tamanho="grande"
                  detalhe={
                    u.disponibilidade_pct === null ? undefined : (
                      <>
                        disponibilidade <Num>{porcento(u.disponibilidade_pct)}</Num>
                      </>
                    )
                  }
                />

                <KpiDoPeriodo rotulo="No mês" periodo={periodoMes} leitura={mes} />
                <KpiDoPeriodo rotulo="No ano" periodo={periodoAno} leitura={ano} />
              </div>
            </Cartao>

            <Cartao>
              <CabecalhoCard rotulo={`Qualidade · ${periodoMes}`} />
              <Bloco leitura={mes} altura={120}>
                {(d) => (
                  <>
                    {d.aviso ? (
                      <div className="mb-3">
                        <Aviso>{d.aviso}</Aviso>
                      </div>
                    ) : null}
                    <div className="grid gap-6 sm:grid-cols-3">
                      <Kpi
                        rotulo="Performance ratio"
                        valor={porcento(d.pr_pct)}
                        detalhe={d.pr_pct === null ? 'sem irradiação medida' : undefined}
                      />
                      <Kpi rotulo="Disponibilidade real" valor={porcento(d.disponibilidade_real_pct)} />
                      <Kpi
                        rotulo="Disponibilidade contratual"
                        valor={porcento(d.disponibilidade_contratual_pct)}
                      />
                    </div>
                    <div className="mt-4">
                      <LinhaNavegacao
                        titulo="Energia perdida em paradas"
                        detalhe="ver as paradas do período"
                        valor={energia(d.perdas_paradas_kwh)}
                        tomValor={
                          d.perdas_paradas_kwh !== null && d.perdas_paradas_kwh > 0
                            ? 'parado'
                            : undefined
                        }
                        aoAbrir={() => navigate(`/usinas/${idUsina}/paradas`)}
                      />
                    </div>
                  </>
                )}
              </Bloco>
            </Cartao>

            <Cartao>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-rotulo">
                  Como foi o período
                </h2>
                {/* Os controles ficam SEMPRE visíveis, inclusive enquanto a leitura chega:
                    escondê-los faria o cliente perder o lugar a cada passo no tempo. */}
                <SeletorPeriodo
                  recorte={recorte}
                  referencia={referencia}
                  onRecorte={setRecorte}
                  onReferencia={setReferencia}
                />
              </div>

              {recorte === 'dia' ? (
                <Bloco leitura={curva} altura={240}>
                  {(c) => (
                    <>
                      {c.aviso ? (
                        <div className="mb-3">
                          <Aviso>{c.aviso}</Aviso>
                        </div>
                      ) : null}
                      {c.pontos.length >= 2 ? (
                        <>
                          <GraficoLinha pontos={c.pontos} />
                          <div className="mt-2 flex flex-wrap gap-4 text-xs text-fraco">
                            <span>
                              pico de potência <Num>{potencia(c.pico_kw)}</Num>
                            </span>
                            {c.tem_estacao ? (
                              <span>
                                pico de irradiação <Num>{numero(c.pico_poa, 0)}</Num> W/m²
                              </span>
                            ) : (
                              <span>
                                Esta usina não tem estação solarimétrica — só a potência é medida.
                              </span>
                            )}
                          </div>
                        </>
                      ) : (
                        <p className="text-sm text-fraco">
                          Sem leitura de potência neste dia.
                        </p>
                      )}
                    </>
                  )}
                </Bloco>
              ) : (
                <Bloco leitura={geracao} altura={240}>
                  {(g) => (
                    <>
                      {g.aviso ? (
                        <div className="mb-3">
                          <Aviso>{g.aviso}</Aviso>
                        </div>
                      ) : null}
                      <div className="mb-3">
                        <Kpi
                          rotulo={recorte === 'ano' ? `Total de ${periodoAno}` : `Total de ${periodoMes}`}
                          valor={energia(g.total_kwh)}
                        />
                      </div>
                      {barras.length > 0 ? (
                        <GraficoBarras pontos={barras} />
                      ) : (
                        <p className="text-sm text-fraco">
                          O monitoramento não devolveu geração para este período.
                        </p>
                      )}
                    </>
                  )}
                </Bloco>
              )}
            </Cartao>

            <Cartao>
              <CabecalhoCard rotulo="Últimos 24 meses" />
              <Bloco leitura={historico} altura={240}>
                {(h) => (
                  <>
                    {h.aviso ? (
                      <div className="mb-3">
                        <Aviso>{h.aviso}</Aviso>
                      </div>
                    ) : null}
                    {serieLonga.length > 0 ? (
                      <GraficoHistorico meses={serieLonga} />
                    ) : (
                      <p className="text-sm text-fraco">Sem histórico para esta usina.</p>
                    )}
                  </>
                )}
              </Bloco>
            </Cartao>
          </>
        )}
      </Tela4Estados>
    </Pagina>
  )
}
