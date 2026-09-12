/**
 * Visão geral — **Como está minha carteira este mês?**
 *
 * É a primeira tela que o cliente corporativo abre, e ela responde cinco perguntas numa
 * olhada: gerei o que o projeto prometia? tem algo parado? a manutenção anda? e o que eu
 * cobrei da equipe, andou? Tudo de UMA leitura (`GET /api/v1/resumo`), que o BFF monta
 * chamando por dentro as mesmas funções das abas — o número daqui é, por construção, o
 * mesmo que a tela da usina mostra depois.
 *
 * **A ordem é a resposta.** Cabeçalho → veredito → exceções → gráfico → tabela → manutenção.
 * Antes as faixas de atenção vinham primeiro e não havia veredito: a tela abria com sete
 * tarjas iguais dizendo "bem abaixo do esperado", ocupando a primeira dobra inteira, e o
 * número que resume a carteira só aparecia depois delas, do tamanho de um KPI qualquer.
 * Quem abria não sabia se o mês estava bom — sabia que havia sete avisos.
 *
 * Decisões que sustentam o desenho:
 *
 * **A régua de cor mora no servidor.** O tom e a frase ("Dentro do esperado", "Bem abaixo do
 * esperado", "Sem meta de projeto cadastrada") vêm prontos em `tom`/`situacao`. A tela não
 * compara percentual com limiar nenhum: repetir a régua aqui a faria divergir do resumo do
 * BFF no dia em que alguém mudasse um dos dois lados.
 *
 * **Desvio não é pintado.** O que falta para a meta sai em `forte`, com a palavra "faltam"
 * na frente — nunca em vermelho. O servidor não classifica desvio, e um limiar inventado
 * aqui acusaria de vermelho uma usina que o contrato considera em dia.
 *
 * **Nada de zero onde faltou dado.** Todo número passa por `lib/format`, que escreve "—"
 * para nulo. Uma usina com o meuPlano fora do ar aparece com "—" e o aviso do servidor ao
 * lado do nome, nunca com "0 OS em andamento" — que se leria como "ninguém está trabalhando".
 *
 * **O mês é o eixo.** A referência anda de mês em mês (‹ ›, futuro bloqueado) e é sempre o
 * dia 1: assim a chave do cache é uma por mês, e não uma por dia de consulta.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  Aviso,
  Barra,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  FaixaAtencao,
  GraficoBarras,
  Kpi,
  Num,
  Pagina,
  Regua,
  Selo,
  Tabela,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { SeletorPeriodo } from '@/components/SeletorPeriodo'
import { competencia, duracao, energia, hora, inteiro, numero, porcento, potencia } from '@/lib/format'
import { competenciaDe, competenciaParaIso, hojeIso } from '@/lib/periodo'
import {
  useResumo,
  useResumoManutencao,
  type AtencaoResumo,
  type ResumoOut,
  type UsinaResumo,
} from '@/features/visao-geral/api'

/** O mês corrente, ancorado no dia 1 — uma chave de cache por mês, não por dia. */
const mesCorrente = () => competenciaParaIso(competenciaDe(hojeIso()))

/**
 * A espécie de faixa que NÃO vira tarja: ela vira a frase do veredito.
 *
 * "Seis usinas ficaram bem abaixo do esperado" é a explicação do percentual grande, não um
 * alerta à parte — posta como tarja, ela repetia em vermelho o que o número já dizia, e
 * empurrava para baixo as duas exceções que realmente pedem ação.
 */
const NO_VEREDITO = 'abaixo_do_esperado'

/**
 * Soma o que existe; nulo quando NADA existe.
 *
 * A mesma regra do `_somar` do BFF, e pelo mesmo motivo: somar só as usinas que responderam
 * e apresentar o total como se fosse da carteira inteira mente para baixo. Com nenhuma
 * leitura, o resultado é ausência — e a tela escreve "—".
 */
function somar(valores: (number | null)[]): number | null {
  const comDado = valores.filter((v): v is number => v !== null)
  return comDado.length ? comDado.reduce((a, b) => a + b, 0) : null
}

/** Cidade e UF, quando o cadastro tem. Usina sem cidade não ganha vírgula solta. */
function local(u: UsinaResumo): string | null {
  const partes = [u.cidade, u.uf].filter(Boolean)
  return partes.length ? partes.join(', ') : null
}

/**
 * A usina da 2ª onda, casada por id — ou `undefined` enquanto a manutenção não chegou.
 *
 * `undefined` e "veio nulo" são coisas diferentes na tela: o primeiro vira "carregando" e o
 * segundo vira "—" com o aviso do servidor. Trocar um pelo outro faria a carteira dizer
 * "nenhum atrasado" antes de ter perguntado.
 */
function manutencaoDe(segunda: ResumoOut | null, id: number): UsinaResumo | undefined {
  return segunda?.usinas.find((u) => u.id === id)
}

/**
 * A coluna "Manutenção": três contadores numa célula.
 *
 * Eram três colunas — Atrasados, OS em andamento, Pendências abertas —, e com elas a tabela
 * chegava a oito: a de usina ficava presa em 17rem e o nome saía truncado num monitor de
 * 1500 px. Os três se leem juntos ("0 atrasados · 1 OS · 6 pend.") porque respondem à mesma
 * pergunta, e o que é vencido sai na cor do problema.
 */
function CelulaManutencao({ pronta, usina }: { pronta: boolean; usina: UsinaResumo | undefined }) {
  if (!pronta) {
    return (
      <span
        aria-label="carregando"
        title="Carregando a manutenção desta usina"
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-borda align-middle"
      />
    )
  }
  const atrasados = usina?.manutencao?.atrasados
  const os = usina?.manutencao?.os_em_andamento
  const pendencias = usina?.pendencias_abertas
  return (
    <span className="mono whitespace-nowrap text-[calc(12.5px_+_var(--passo-tipo))] text-corpo">
      <span className={atrasados ? 'text-tom-parado' : undefined}>
        {inteiro(atrasados === undefined ? null : atrasados)} atrasados
      </span>
      {' · '}
      {inteiro(os === undefined ? null : os)} OS
      {' · '}
      {inteiro(pendencias === undefined ? null : pendencias)} pend.
    </span>
  )
}

export default function VisaoGeral() {
  const navigate = useNavigate()
  const [referencia, setReferencia] = useState(mesCorrente)
  const leitura = useResumo(referencia)
  // A segunda onda corre SOZINHA, em paralelo: a tela não a espera para desenhar. Ver o
  // porquê em `api.ts` — a chamada única levava 22 s e esta é a primeira tela do portal.
  const manutencao = useResumoManutencao(referencia)

  return (
    <Tela4Estados
      leitura={leitura}
      esqueleto={
        <Pagina titulo="Visão geral" subtitulo="Como está minha carteira este mês?">
          <div className="space-y-4">
            <CarregandoCartao linhas={2} />
            <CarregandoCartao linhas={5} />
          </div>
        </Pagina>
      }
    >
      {(d) => {
        const capacidade = somar(d.usinas.map((u) => u.capacidade_kwp))
        // Faltam N para a meta: a diferença entre dois números do servidor, escrita como a
        // subtração que é. Só existe quando os DOIS existem — com um lado nulo não há
        // diferença a afirmar, e inventá-la seria o coalescer para zero que a REGRA 0 proíbe.
        const faltam =
          d.esperado_mes_kwh !== null && d.energia_mes_kwh !== null
            ? Math.max(0, d.esperado_mes_kwh - d.energia_mes_kwh)
            : null
        // As faixas das DUAS ondas. A primeira só enxerga energia e paradas; atividade
        // atrasada e pendência vencida nascem na segunda, e sem juntá-las a tela mostrava
        // "Tiete tem 2 paradas em aberto" e calava as 4 pendências vencidas que o rodapé,
        // dois cartões abaixo, contava em vermelho.
        const atencao = [...d.atencao, ...(manutencao.dados?.atencao ?? [])]
        const noVeredito = atencao.filter((a) => a.especie === NO_VEREDITO)
        const excecoes = atencao.filter((a) => a.especie !== NO_VEREDITO)

        return (
          <Pagina
            rotulo={
              <>
                A carteira · {inteiro(d.usinas.length)}{' '}
                {d.usinas.length === 1 ? 'usina' : 'usinas'}
                {capacidade === null ? null : <> · {numero(capacidade / 1000, 1)} MWp</>}
              </>
            }
            titulo="Visão geral"
            acoes={
              <>
                <span className="mono text-[calc(11px_+_var(--passo-tipo))] text-fraco">
                  atualizado {hora(d.atualizado_em)}
                </span>
                <SeletorPeriodo recorte="mes" referencia={referencia} onReferencia={setReferencia} />
              </>
            }
          >
            {d.usinas.length === 0 ? (
              <Vazio
                titulo="Nenhuma usina para mostrar"
                // O aviso do servidor explica o vazio quando existe (escopo sem usina,
                // leitura do meuWatt fora do ar). Sem ele, a frase neutra — jamais um
                // número inventado.
                descricao={
                  d.aviso ??
                  'Não há usina liberada para a sua conta. Fale com o seu gestor de conta para liberar o acesso.'
                }
              />
            ) : (
              <div className="space-y-4">
                {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}

                {/* 1 — O VEREDITO: um número responde a pergunta da tela. */}
                <Cartao className="p-7">
                  <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_1px_340px]">
                    <div className="min-w-0">
                      <div className="rotulo-secao mb-3">
                        O combinado × o entregue · {competencia(d.referencia_mes)}
                      </div>

                      <div className="flex flex-wrap items-end gap-4">
                        <Kpi
                          valor={porcento(d.pct_do_esperado, 1).replace('%', '')}
                          unidade="%"
                          tamanho="veredito"
                          tom={d.tom}
                        />
                        <div className="pb-2">
                          <p className="text-[calc(15px_+_var(--passo-tipo))] font-semibold text-forte">{d.situacao}</p>
                          {faltam === null ? null : (
                            <p className="mt-0.5 text-[calc(13.5px_+_var(--passo-tipo))] text-fraco">
                              faltam <Num className="text-corpo">{energia(faltam)}</Num> para a
                              meta do mês
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="mt-5">
                        <Regua
                          pct={d.pct_do_esperado}
                          meio={<>{energia(d.energia_mes_kwh)} medidos</>}
                          fim={<>alvo {energia(d.esperado_mes_kwh)}</>}
                        />
                      </div>

                      {/* A frase de leitura é o TEXTO DO SERVIDOR das faixas que saíram do
                          bloco de exceções. A tela não escreve diagnóstico: ela muda o
                          lugar em que o diagnóstico do BFF aparece. */}
                      {noVeredito.length > 0 ? (
                        <div className="mt-6 max-w-[560px] space-y-1">
                          {noVeredito.map((a) => (
                            <p key={a.especie} className="text-[calc(13.5px_+_var(--passo-tipo))] leading-relaxed text-corpo">
                              {a.titulo}
                              {a.detalhe ? (
                                <span className="text-fraco"> — {a.detalhe}</span>
                              ) : null}
                            </p>
                          ))}
                        </div>
                      ) : null}
                    </div>

                    <div aria-hidden className="hidden bg-borda lg:block" />

                    <div className="flex flex-col gap-4">
                      <Kpi
                        rotulo="Potência agora"
                        valor={potencia(d.potencia_agora_kw).replace(' kW', '')}
                        unidade="kW"
                        tamanho="grande"
                      />
                      <div className="border-t border-borda-fraca pt-4">
                        <Kpi
                          rotulo="Paradas no mês"
                          valor={inteiro(somar(d.usinas.map((u) => u.paradas_mes)))}
                          tamanho="grande"
                          // O tempo total, e não a energia perdida: `/resumo` não traz perda
                          // em kWh por usina, e estimá-la aqui seria número derivado
                          // apresentado como medição. Quem tem a perda é a tela de Paradas.
                          detalhe={
                            <>
                              <Num>{duracao(somar(d.usinas.map((u) => u.tempo_parado_min)))}</Num>{' '}
                              somadas
                            </>
                          }
                        />
                      </div>
                      <div className="border-t border-borda-fraca pt-4">
                        <Kpi
                          rotulo="Leitura da carteira"
                          valor={inteiro(d.usinas_com_dado)}
                          unidade={`de ${inteiro(d.usinas.length)} ${
                            d.usinas.length === 1 ? 'usina' : 'usinas'
                          }`}
                          tamanho="grande"
                          detalhe={
                            d.usinas_com_dado < d.usinas.length ? (
                              <span className="text-tom-alerta">
                                {d.usinas
                                  .filter((u) => u.energia_mes_kwh === null)
                                  .map((u) => u.nome)
                                  .join(' · ')}{' '}
                                sem leitura de energia no mês
                              </span>
                            ) : null
                          }
                        />
                      </div>
                    </div>
                  </div>
                </Cartao>

                {/* 2 — AS EXCEÇÕES: só o que é excepcional ganha faixa. */}
                {excecoes.length > 0 ? (
                  <div className="grid gap-4 lg:grid-cols-2">
                    {excecoes.map((a: AtencaoResumo) => (
                      <FaixaAtencao
                        key={a.especie}
                        tom={a.tom}
                        titulo={a.titulo}
                        detalhe={a.detalhe}
                        contagem={a.contagem}
                        acao={a.acao}
                        aoAbrir={() => navigate(a.rota)}
                      />
                    ))}
                  </div>
                ) : null}

                {/* 3 — QUEM puxou a carteira. Uma usina só não ganha gráfico: comparar uma
                    coisa com ela mesma não é comparação. */}
                {d.usinas.length > 1 ? (
                  <Cartao className="p-7">
                    <CabecalhoCard
                      rotulo="Medido × projeto, por usina"
                      pergunta="Quem puxou a carteira para baixo"
                      direita={
                        <span className="flex items-center gap-4">
                          <span className="flex items-center gap-2">
                            <span className="h-[11px] w-[11px] rounded-[2px] bg-ambar" />
                            medido
                          </span>
                          <span className="flex items-center gap-2">
                            <span className="h-[11px] w-[11px] rounded-[2px] bg-superficie-destacada" />
                            projeto
                          </span>
                        </span>
                      }
                    />
                    <GraficoBarras
                      altura={170}
                      pontos={d.usinas.map((u) => ({
                        rotulo: u.nome,
                        valor: u.energia_mes_kwh,
                        esperado: u.esperado_mes_kwh,
                      }))}
                    />
                  </Cartao>
                ) : null}

                {/* 4 — uma linha por usina; a linha inteira abre a usina */}
                <Cartao semPadding>
                  <div className="px-6 pt-6">
                    <CabecalhoCard
                      rotulo="Usinas"
                      direita="clique numa linha para abrir a usina"
                      className="mb-2"
                    />
                  </div>
                  <div className="px-3 pb-3">
                    <Tabela<UsinaResumo>
                      linhas={d.usinas}
                      chave={(u) => u.id}
                      aoClicar={(u) => navigate(`/usinas/${u.id}`)}
                      tomDaLinha={(u) => u.tom}
                      colunas={[
                        {
                          titulo: 'Usina',
                          largura: '250px',
                          celula: (u) => (
                            // A largura é PRESA, e não só declarada na coluna: a tabela é
                            // `min-w-max`, então `truncate` corta o desenho mas não o
                            // cálculo — o navegador reserva a largura do texto inteiro. O
                            // aviso de UFV Leme ("Esta usina não está ligada ao
                            // monitoramento", duas vezes) levava a coluna a quase mil pixels
                            // e empurrava Paradas e Manutenção para fora da tela.
                            <div className="w-[250px] min-w-0 max-w-[250px]">
                              <span className="block truncate font-medium text-forte">{u.nome}</span>
                              {local(u) ? (
                                <span className="block truncate text-xs text-fraco">{local(u)}</span>
                              ) : null}
                              {u.aviso ? (
                                <span
                                  title={u.aviso}
                                  className="mt-0.5 block truncate text-xs text-tom-alerta"
                                >
                                  {u.aviso}
                                </span>
                              ) : null}
                            </div>
                          ),
                        },
                        {
                          titulo: 'Situação',
                          largura: '150px',
                          celula: (u) => <Selo tom={u.tom}>{u.situacao}</Selo>,
                        },
                        {
                          // A comparação como COMPARADOR: a barra diz de relance quanto do
                          // projeto a usina entregou, e os dois números embaixo dizem de
                          // quanto. Eram duas colunas de número — medido e % do esperado —
                          // e nenhuma das duas se lia sem a outra.
                          titulo: 'Medido contra o projeto',
                          largura: 'minmax(0,1fr)',
                          celula: (u) => (
                            <div className="min-w-[140px]">
                              <Barra pct={u.pct} tom={u.tom} />
                              <span className="mono mt-1.5 block text-[calc(11.5px_+_var(--passo-tipo))] text-fraco">
                                {u.esperado_mes_kwh === null ? (
                                  <>{energia(u.energia_mes_kwh)} · sem meta de projeto</>
                                ) : (
                                  <>
                                    {energia(u.energia_mes_kwh)} de {energia(u.esperado_mes_kwh)}
                                  </>
                                )}
                              </span>
                            </div>
                          ),
                        },
                        {
                          titulo: 'Paradas',
                          alinhar: 'dir',
                          largura: '150px',
                          celula: (u) => (
                            <>
                              <Num>{inteiro(u.paradas_mes)}</Num>
                              {/* o tempo parado só aparece quando houve parada: "0 min"
                                  embaixo de "0" é ruído, e some sozinho no mês limpo */}
                              {typeof u.tempo_parado_min === 'number' && u.tempo_parado_min > 0 ? (
                                <span className="block text-xs text-fraco">
                                  <Num>{duracao(u.tempo_parado_min)}</Num> parada
                                </span>
                              ) : null}
                            </>
                          ),
                        },
                        {
                          titulo: 'Manutenção',
                          alinhar: 'dir',
                          largura: '190px',
                          celula: (u) => (
                            <CelulaManutencao
                              pronta={manutencao.dados !== null}
                              usina={manutencaoDe(manutencao.dados, u.id)}
                            />
                          ),
                        },
                      ]}
                    />
                  </div>
                </Cartao>

                {/* 5 — o rodapé da 2ª onda */}
                <div className="grid gap-4 lg:grid-cols-2">
                  <Cartao className="p-6">
                    <CabecalhoCard rotulo="Manutenção" />
                    {manutencao.dados === null ? (
                      <CarregandoCartao linhas={1} />
                    ) : manutencao.dados.manutencao ? (
                      <>
                        <div className="grid grid-cols-3 gap-4">
                          <Kpi
                            rotulo="OS em andamento"
                            valor={inteiro(manutencao.dados.manutencao.os_em_andamento)}
                          />
                          <Kpi
                            rotulo="Concluídas no mês"
                            valor={inteiro(manutencao.dados.manutencao.os_concluidas_mes)}
                          />
                          <Kpi
                            rotulo="Atrasados"
                            valor={inteiro(manutencao.dados.manutencao.atrasados_total)}
                          />
                        </div>
                        {/* Sem cronograma publicado não há previsto, e sem previsto não
                            existe atraso a cobrar: "0 atrasados" ali não é manutenção em
                            dia, é ausência de contrato consolidado. */}
                        <SemCronograma usinas={manutencao.dados.usinas} />
                      </>
                    ) : (
                      <p className="text-sm text-fraco">
                        Não deu para ler a manutenção das suas usinas agora. O detalhe de cada
                        usina está na coluna de aviso da tabela acima.
                      </p>
                    )}
                  </Cartao>

                  <Cartao className="p-6">
                    <CabecalhoCard rotulo="Pendências" />
                    {manutencao.dados === null ? (
                      <CarregandoCartao linhas={1} />
                    ) : manutencao.dados.pendencias ? (
                      <div className="grid grid-cols-3 gap-4">
                        <Kpi rotulo="Abertas" valor={inteiro(manutencao.dados.pendencias.abertas)} />
                        <Kpi
                          rotulo="Prazo vencido"
                          valor={inteiro(manutencao.dados.pendencias.prazo_vencido)}
                          tom={manutencao.dados.pendencias.prazo_vencido ? 'parado' : undefined}
                        />
                        <Kpi
                          rotulo="Cobradas por mim"
                          valor={inteiro(manutencao.dados.pendencias.cobradas_abertas)}
                          detalhe="abertas que você pediu"
                        />
                      </div>
                    ) : (
                      <p className="text-sm text-fraco">
                        Não deu para ler as pendências das suas usinas agora.
                      </p>
                    )}
                  </Cartao>
                </div>
              </div>
            )}
          </Pagina>
        )
      }}
    </Tela4Estados>
  )
}

/**
 * Quantos contratos ainda não publicaram o cronograma.
 *
 * É a frase que impede a leitura errada do "0 atrasados" ao lado: o contador de atrasados só
 * enxerga o que foi previsto, e um contrato sem cronograma consolidado não prevê nada. Sem
 * esta linha, a carteira com seis contratos por publicar parecia a carteira mais em dia da
 * empresa. `previsto_ate_mes` nulo é o sinal de "não publicado" — é o que o BFF devolve
 * quando não há versão consolidada.
 */
function SemCronograma({ usinas }: { usinas: UsinaResumo[] }) {
  const sem = usinas.filter((u) => u.manutencao !== null && u.manutencao.previsto_ate_mes === null)
  if (sem.length === 0) return null
  return (
    <p className="mt-4 border-t border-borda-fraca pt-3 text-[calc(12.5px_+_var(--passo-tipo))] leading-relaxed text-fraco">
      <Num className="text-tom-alerta">{inteiro(sem.length)}</Num> de{' '}
      <Num>{inteiro(usinas.length)}</Num> contratos ainda não publicaram o cronograma — sem ele
      não há atraso a cobrar.
    </p>
  )
}
