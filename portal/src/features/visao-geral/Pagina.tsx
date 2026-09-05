/**
 * Visão geral — **Como está minha carteira este mês?**
 *
 * É a primeira tela que o cliente corporativo abre, e ela responde cinco perguntas numa
 * olhada: gerei o que o projeto prometia? tem algo parado? a manutenção anda? e o que eu
 * cobrei da equipe, andou? Tudo de UMA leitura (`GET /api/v1/resumo`), que o BFF monta
 * chamando por dentro as mesmas funções das abas — o número daqui é, por construção, o
 * mesmo que a tela da usina mostra depois.
 *
 * Decisões que sustentam o desenho:
 *
 * **A régua de cor mora no servidor.** O tom e a frase ("Dentro do esperado", "Bem abaixo do
 * esperado", "Sem meta de projeto cadastrada") vêm prontos em `tom`/`situacao`. A tela não
 * compara percentual com limiar nenhum: repetir a régua aqui a faria divergir do resumo do
 * BFF no dia em que alguém mudasse um dos dois lados. Por isso a coluna de percentual da
 * tabela é texto simples — quem colore é o selo de situação, que é dado.
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
  AtualizadoAs,
  Aviso,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  FaixaAtencao,
  GraficoBarras,
  Kpi,
  Num,
  Pagina,
  Selo,
  Tabela,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { SeletorPeriodo } from '@/components/SeletorPeriodo'
import { competencia, duracao, energia, hora, inteiro, porcento, potencia } from '@/lib/format'
import { competenciaDe, competenciaParaIso, hojeIso } from '@/lib/periodo'
import {
  useResumo,
  useResumoManutencao,
  type ResumoOut,
  type UsinaResumo,
} from '@/features/visao-geral/api'

/** O mês corrente, ancorado no dia 1 — uma chave de cache por mês, não por dia. */
const mesCorrente = () => competenciaParaIso(competenciaDe(hojeIso()))

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
function manutencaoDe(
  segunda: ResumoOut | null,
  id: number,
): UsinaResumo | undefined {
  return segunda?.usinas.find((u) => u.id === id)
}

/**
 * Uma célula da 2ª onda: ponto pulsante enquanto ela não chegou, o número depois.
 *
 * O ponto existe para não escrever "—" no lugar de "ainda estou perguntando": um traço se lê
 * como "não há", e o cliente concluiria "nenhuma OS em andamento" antes de o servidor ter
 * respondido. Nulo depois da resposta continua "—", que é a régua de sempre.
 */
function DaSegundaOnda({ pronta, valor }: { pronta: boolean; valor: number | null | undefined }) {
  if (!pronta) {
    return (
      <span
        aria-label="carregando"
        title="Carregando a manutenção desta usina"
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-borda align-middle"
      />
    )
  }
  return <Num>{inteiro(valor ?? null)}</Num>
}

export default function VisaoGeral() {
  const navigate = useNavigate()
  const [referencia, setReferencia] = useState(mesCorrente)
  const leitura = useResumo(referencia)
  // A segunda onda corre SOZINHA, em paralelo: a tela não a espera para desenhar. Ver o
  // porquê em `api.ts` — a chamada única levava 22 s e esta é a primeira tela do portal.
  const manutencao = useResumoManutencao(referencia)

  return (
    <Pagina
      titulo="Visão geral"
      subtitulo="Como está minha carteira este mês?"
      acoes={
        <SeletorPeriodo recorte="mes" referencia={referencia} onReferencia={setReferencia} />
      }
    >
      <Tela4Estados
        leitura={leitura}
        esqueleto={
          <div className="space-y-4">
            <CarregandoCartao linhas={2} />
            <CarregandoCartao linhas={5} />
          </div>
        }
      >
        {(d) =>
          d.usinas.length === 0 ? (
            <Vazio
              titulo="Nenhuma usina para mostrar"
              // O aviso do servidor explica o vazio quando existe (escopo sem usina, leitura
              // do meuWatt fora do ar). Sem ele, a frase neutra — jamais um número inventado.
              descricao={
                d.aviso ??
                'Não há usina liberada para a sua conta. Fale com o seu gestor de conta para liberar o acesso.'
              }
            />
          ) : (
            <>
              {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}

              {d.atencao.length > 0 ? (
                <div className="space-y-2">
                  {d.atencao.map((a, i) => (
                    <FaixaAtencao
                      key={`${a.rota}-${a.titulo}-${i}`}
                      tom={a.tom}
                      titulo={a.titulo}
                      detalhe={a.detalhe}
                      aoAbrir={() => navigate(a.rota)}
                    />
                  ))}
                </div>
              ) : null}

              {/* 1 — a carteira em energia: o que gerei contra o que o projeto prometia */}
              <Cartao>
                <CabecalhoCard
                  rotulo={`Energia · ${competencia(d.referencia_mes)}`}
                  direita={<AtualizadoAs em={hora(d.atualizado_em)} />}
                />
                <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
                  <Kpi
                    rotulo="Energia no mês"
                    valor={energia(d.energia_mes_kwh)}
                    tamanho="grande"
                    detalhe={
                      <>
                        <Num>{inteiro(d.usinas_com_dado)}</Num> de{' '}
                        <Num>{inteiro(d.usinas.length)}</Num>{' '}
                        {d.usinas.length === 1 ? 'usina com leitura' : 'usinas com leitura'}
                      </>
                    }
                  />
                  <Kpi
                    rotulo="Esperado do projeto"
                    valor={energia(d.esperado_mes_kwh)}
                    detalhe="meta cadastrada no monitoramento"
                  />
                  <Kpi
                    rotulo="% do esperado"
                    valor={porcento(d.pct_do_esperado, 1)}
                    tom={d.tom}
                    detalhe={<Selo tom={d.tom}>{d.situacao}</Selo>}
                  />
                  <Kpi rotulo="Potência agora" valor={potencia(d.potencia_agora_kw)} />
                </div>

                {/*
                  A carteira desenhada: uma barra por usina, com o esperado do projeto
                  sobreposto. Esta era a tela mais fraca do portal em desenho — só números
                  em fonte monoespaçada e uma tabela —, justo a que o cliente abre primeiro
                  e a que mais deveria parecer um painel. Os gráficos já existiam; faltava
                  usá-los aqui. Ponto sem leitura não vira barra (regra do componente), e
                  uma carteira de uma usina só não ganha gráfico: comparar uma coisa com
                  ela mesma não é comparação.
                */}
                {d.usinas.length > 1 ? (
                  <div className="mt-6 border-t border-borda-fraca pt-5">
                    <GraficoBarras
                      pontos={d.usinas.map((u) => ({
                        rotulo: u.nome,
                        valor: u.energia_mes_kwh,
                        esperado: u.esperado_mes_kwh,
                      }))}
                    />
                  </div>
                ) : null}
              </Cartao>

              {/* 2 — uma linha por usina; a linha inteira abre a usina (a URL vira o contexto) */}
              <Cartao semPadding>
                <div className="px-5 pt-5">
                  <CabecalhoCard
                    rotulo="Usinas"
                    direita="clique numa linha para abrir a usina"
                    className="mb-2"
                  />
                </div>
                <div className="px-2 pb-2">
                  <Tabela<UsinaResumo>
                    linhas={d.usinas}
                    chave={(u) => u.id}
                    aoClicar={(u) => navigate(`/usinas/${u.id}`)}
                    colunas={[
                      {
                        titulo: 'Usina',
                        celula: (u) => (
                          // A largura é PRESA de propósito. Numa tabela de largura
                          // automática, `truncate` corta o desenho mas não o cálculo: o
                          // navegador reserva a largura do texto inteiro, e o aviso
                          // ("A equipe ainda não publicou o cronograma deste contrato")
                          // levava esta coluna a 996 px de 1110 — empurrando energia,
                          // esperado e % para fora da tela, atrás de uma rolagem lateral
                          // que ninguém procura. O número é o que o cliente vem ver.
                          <div className="min-w-0 max-w-[17rem]">
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
                        celula: (u) => <Selo tom={u.tom}>{u.situacao}</Selo>,
                      },
                      {
                        // Medido e esperado na MESMA célula: eram duas colunas, e a tabela
                        // chegava a nove — uma acima do teto de oito da revisão de
                        // simplicidade. Aqui os dois se leem juntos, que é como a pergunta
                        // é feita ("gerei o que o projeto prometia?").
                        titulo: 'Energia no mês',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            <Num>{energia(u.energia_mes_kwh)}</Num>
                            <span className="block text-xs text-fraco">
                              {u.esperado_mes_kwh === null ? (
                                'sem meta'
                              ) : (
                                <>
                                  de <Num>{energia(u.esperado_mes_kwh)}</Num>
                                </>
                              )}
                            </span>
                          </>
                        ),
                      },
                      {
                        titulo: '% do esperado',
                        alinhar: 'dir',
                        celula: (u) => <Num>{porcento(u.pct, 0)}</Num>,
                      },
                      {
                        titulo: 'Paradas',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            <Num>{inteiro(u.paradas_mes)}</Num>
                            {/* o tempo parado só aparece quando houve parada: "0 min" embaixo
                                de "0" é ruído, e some sozinho no mês limpo */}
                            {typeof u.tempo_parado_min === 'number' && u.tempo_parado_min > 0 ? (
                              <span className="block text-xs text-fraco">
                                <Num>{duracao(u.tempo_parado_min)}</Num> parada
                              </span>
                            ) : null}
                          </>
                        ),
                      },
                      {
                        titulo: 'Atrasados',
                        alinhar: 'dir',
                        celula: (u) => (
                          <DaSegundaOnda
                            pronta={manutencao.dados !== null}
                            valor={manutencaoDe(manutencao.dados, u.id)?.manutencao?.atrasados}
                          />
                        ),
                      },
                      {
                        titulo: 'OS em andamento',
                        alinhar: 'dir',
                        celula: (u) => (
                          <DaSegundaOnda
                            pronta={manutencao.dados !== null}
                            valor={
                              manutencaoDe(manutencao.dados, u.id)?.manutencao?.os_em_andamento
                            }
                          />
                        ),
                      },
                      {
                        titulo: 'Pendências abertas',
                        alinhar: 'dir',
                        celula: (u) => (
                          <DaSegundaOnda
                            pronta={manutencao.dados !== null}
                            valor={manutencaoDe(manutencao.dados, u.id)?.pendencias_abertas}
                          />
                        ),
                      },
                    ]}
                  />
                </div>
              </Cartao>

              <div className="grid gap-4 lg:grid-cols-2">
                {/* 3 — a manutenção está sendo feita? (chega na 2ª onda) */}
                <Cartao>
                  <CabecalhoCard rotulo="Manutenção" />
                  {manutencao.dados === null ? (
                    <CarregandoCartao linhas={1} />
                  ) : manutencao.dados.manutencao ? (
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
                        detalhe="no cronograma do contrato"
                      />
                    </div>
                  ) : (
                    <p className="text-sm text-fraco">
                      Não deu para ler a manutenção das suas usinas agora. O detalhe de cada
                      usina está na coluna de aviso da tabela acima.
                    </p>
                  )}
                </Cartao>

                {/* 4 — o que eu cobrei da equipe andou? */}
                <Cartao>
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
            </>
          )
        }
      </Tela4Estados>
    </Pagina>
  )
}
