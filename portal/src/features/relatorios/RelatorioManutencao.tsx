/**
 * O relatório de manutenção do período — o documento que o cliente leva à diretoria.
 *
 * A pergunta é uma só: **neste período, o contrato foi cumprido?** Tudo o que está aqui
 * responde a ela — o cronograma cumprido, as OSs encerradas, o parecer das fichas, os
 * problemas que elas acharam, o que foi dispensado e com que motivo, e as pendências que o
 * cliente cobrou.
 *
 * Três regras que este arquivo respeita e que não devem ser "simplificadas" depois:
 *
 * **Nada é somado aqui.** As contagens do cronograma, dos pareceres e dos problemas vêm do
 * BFF, que as recebe do meuPlano — onde elas saem do histórico do ATIVO, não de contar
 * tarefas. Somar as linhas para conferir o total produziria uma segunda verdade sobre a
 * mesma pergunta, e o cliente veria números diferentes na tela e no PDF sem saber em qual
 * acreditar. As cinco parcelas (executadas + dispensadas + atrasadas + no prazo + sem ativo)
 * fecham `previstas` porque o servidor as fecha — a tela só as mostra.
 *
 * **`pct_cumprido` nulo é "—".** "Nada estava previsto" não é "0 % cumprido": o segundo
 * acusaria um contrato que não pedia nada naquele período.
 *
 * **Feito ≠ dispensado.** As duas contagens andam separadas do começo ao fim, como no
 * cronograma; fundi-las apagaria a diferença entre uma inspeção executada e uma inspeção
 * que a equipe declarou fora do escopo com um motivo.
 *
 * O período é escolhido em competências (`YYYY-MM`), e o "de" nunca passa do "até" porque a
 * lista não oferece essa combinação — melhor que receber o 400 do BFF por uma escolha que a
 * própria tela ofereceu.
 */

import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  Aviso,
  Botao,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  Combobox,
  Kpi,
  Num,
  Selo,
  Tabela,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { SeletorCompetencias } from '@/components/SeletorPeriodo'
import { mensagemDeErro } from '@/lib/api'
import { abrirPdf } from '@/lib/arquivo'
import {
  competencia,
  competenciaCurta,
  dataCurta,
  duracao,
  inteiro,
  porcento,
} from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import { competenciaDe, hojeIso, passoCompetencia } from '@/lib/periodo'
import {
  caminhoPdfDoRelatorio,
  chaveContratos,
  chaveRelatorio,
  nomeDoPdfDoRelatorio,
  rotuloDoContrato,
  NOME_DA_CATEGORIA,
  type Contrato,
  type ContratosOut,
  type Ordem,
  type PendenciaDoRelatorio,
  type RelatorioOut,
  type TarefaDaOrdem,
} from '@/features/relatorios/api'

/** O BFF cobre no máximo 24 competências num relatório só (`relatorio.MESES_MAX`). */
const MESES_OFERECIDOS = 24
/** Sem escolha, o relatório é dos últimos 12 meses — o que se leva a uma reunião anual. */
const MESES_PADRAO = 12
/** O agregado do meuPlano lê o cronograma, as OSs e as fichas do período: leva segundos. */
const PRAZO_DO_RELATORIO_MS = 120_000

function periodoPadrao(): { de: string; ate: string } {
  const ate = competenciaDe(hojeIso())
  let de = ate
  for (let i = 1; i < MESES_PADRAO; i += 1) de = passoCompetencia(de, -1)
  return { de, ate }
}

/**
 * Abrir um PDF com a sessão no cabeçalho, com estado de espera e de falha.
 *
 * Exportado porque os dois blocos da tela baixam documento — o relatório de manutenção e os
 * relatórios de geração publicados. A falha vira faixa na tela: popup nativo do navegador é
 * proibido, e um clique que não responde nada se lê como portal quebrado.
 */
export function useBaixarPdf() {
  const [baixando, setBaixando] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  function baixar(marca: string, caminho: string, nome: string, prazoMs?: number) {
    setErro(null)
    setBaixando(marca)
    // Chamado direto do `onClick`: é o gesto do usuário que autoriza a aba nova.
    abrirPdf(caminho, nome, prazoMs === undefined ? {} : { prazoMs })
      .catch((falha) => setErro(mensagemDeErro(falha)))
      .finally(() => setBaixando(null))
  }

  return { baixando, erro, baixar }
}

/* ------------------------------------------------------------------ pedaços */

function Secao({
  titulo,
  direita,
  children,
}: {
  titulo: string
  direita?: ReactNode
  children: ReactNode
}) {
  return (
    <Cartao>
      <CabecalhoCard rotulo={titulo} direita={direita} />
      {children}
    </Cartao>
  )
}

function Linha({ rotulo, valor }: { rotulo: string; valor: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs uppercase tracking-wide text-rotulo">{rotulo}</div>
      <div className="truncate text-sm text-corpo">{valor}</div>
    </div>
  )
}

function TarefaDaLista({ t }: { t: TarefaDaOrdem }) {
  // A cor vem do servidor: deduzi-la aqui era o que fazia cada tela pintar o mesmo
  // parecer de um jeito. Sem cor conhecida, o texto sai neutro.
  const tom = t.parecer_tom ?? 'semDados'
  return (
    <li className="flex flex-wrap items-center gap-2 border-b border-borda-fraca py-2 text-sm last:border-0">
      <span className={t.feita ? 'text-tom-ok' : 'text-fraco'} aria-hidden>
        {t.feita ? '✓' : '○'}
      </span>
      <span className="min-w-0 flex-1 truncate text-corpo">
        {t.nome}
        {t.equipamento ? <span className="text-fraco"> · {t.equipamento}</span> : null}
      </span>
      {t.feita ? null : <span className="text-xs text-fraco">{t.situacao}</span>}
      {t.parecer ? <Selo tom={tom}>{t.parecer}</Selo> : null}
    </li>
  )
}

function CartaoDaOrdem({ o, aoAbrir }: { o: Ordem; aoAbrir: () => void }) {
  const quando = o.concluida_em ?? o.aprovada_em ?? o.fechada_em ?? o.agendada_para
  return (
    <div className="rounded-card border border-borda-fraca p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <button type="button" onClick={aoAbrir} className="min-w-0 text-left">
          <span className="block truncate text-sm font-medium text-forte hover:text-ambar-texto">
            {o.objetivo}
          </span>
          <span className="mt-0.5 block text-xs text-fraco">
            {o.numero === null ? `OS ${o.id}` : `OS #${o.numero}`}
            {o.classificacao ? ` · ${o.classificacao}` : ''}
            {o.tecnico ? ` · ${o.tecnico}` : ''}
          </span>
        </button>
        <div className="flex items-center gap-2">
          <Selo tom={o.tom}>{o.situacao}</Selo>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Linha rotulo="Data" valor={<Num>{dataCurta(quando)}</Num>} />
        <Linha rotulo="Execução" valor={<Num>{duracao(o.execucao_min)}</Num>} />
        <Linha
          rotulo="Tarefas"
          valor={
            <Num>
              {inteiro(o.tarefas_feitas)} de {inteiro(o.tarefas)}
            </Num>
          }
        />
        <Linha rotulo="Resumo" valor={o.resumo ?? '—'} />
      </div>

      {o.itens === null ? (
        // Nulo ≠ vazio: o servidor não conseguiu buscar as tarefas desta OS. Dizer "sem
        // tarefas" aqui afirmaria que a equipe não fez nada.
        <p className="mt-3 text-sm text-fraco">Não deu para buscar as tarefas desta ordem.</p>
      ) : o.itens.length === 0 ? (
        <p className="mt-3 text-sm text-fraco">Ordem sem tarefas registradas.</p>
      ) : (
        <ul className="mt-3">
          {o.itens.map((t, i) => (
            <TarefaDaLista key={t.id === null ? `${o.id}-${i}` : t.id} t={t} />
          ))}
        </ul>
      )}
    </div>
  )
}

function PendenciasDaLista({
  titulo,
  itens,
  aoAbrir,
  vazio,
}: {
  titulo: string
  itens: PendenciaDoRelatorio[]
  aoAbrir: (p: PendenciaDoRelatorio) => void
  vazio: string
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-medium text-corpo">{titulo}</h3>
        {/* Contagem do que está na lista — o servidor manda os itens, não um total à parte. */}
        <Num className="text-sm text-fraco">{inteiro(itens.length)}</Num>
      </div>
      {itens.length === 0 ? (
        <p className="text-sm text-fraco">{vazio}</p>
      ) : (
        <ul>
          {itens.map((p) => (
            <li key={p.id === null ? p.titulo : p.id}>
              <button
                type="button"
                onClick={() => aoAbrir(p)}
                className="flex w-full flex-wrap items-center gap-2 border-b border-borda-fraca py-2 text-left text-sm last:border-0 hover:text-forte"
              >
                <Num className="text-xs text-fraco">
                  {p.numero === null ? '—' : `#${p.numero}`}
                </Num>
                <span className="min-w-0 flex-1 truncate text-corpo">{p.titulo}</span>
                {p.cobrada_pelo_cliente ? (
                  <span className="text-xs text-ambar-texto">cobrada por você</span>
                ) : null}
                {p.prazo ? (
                  <Num className="text-xs text-fraco">prazo {dataCurta(p.prazo)}</Num>
                ) : null}
                {p.concluida_em ? (
                  <Num className="text-xs text-fraco">
                    concluída por volta de {dataCurta(p.concluida_em)}
                  </Num>
                ) : null}
                <Selo tom={p.tom}>{p.situacao}</Selo>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ bloco */

export function RelatorioManutencao({ usinaId }: { usinaId: number }) {
  const navigate = useNavigate()
  const [periodo, setPeriodo] = useState(periodoPadrao)
  const [contratoEscolhido, setContratoEscolhido] = useState<number | null>(null)
  const pdf = useBaixarPdf()

  const contratos = useLeitura<ContratosOut>(chaveContratos(usinaId))
  const relatorio = useLeitura<RelatorioOut>(
    chaveRelatorio(usinaId, periodo.de, periodo.ate, contratoEscolhido),
    { prazoMs: PRAZO_DO_RELATORIO_MS },
  )

  const lista: Contrato[] = contratos.dados?.contratos ?? []
  // Sem escolha do cliente, o seletor mostra o contrato que o SERVIDOR resolveu — é o
  // mesmo padrão da aba Cronograma, e ler o que está valendo vale mais do que um campo
  // vazio que parece "nenhum contrato".
  const contratoNaTela = contratoEscolhido ?? relatorio.dados?.contrato?.id ?? null
  const opcoes = useMemo(
    () =>
      lista.map((c) => ({
        valor: String(c.id),
        rotulo: rotuloDoContrato(c),
        detalhe:
          c.versao_cronograma === null
            ? 'sem cronograma publicado'
            : `cronograma v${c.versao_cronograma}`,
      })),
    [lista],
  )

  const nomeDaUsina = relatorio.dados?.usina ?? contratos.dados?.usina ?? 'usina'

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-forte">Relatório de manutenção</h2>
          <p className="text-sm text-fraco">
            O que a equipe executou no período, contra o que o contrato previa.
          </p>
        </div>
        <Botao
          variante="secundario"
          desabilitado={pdf.baixando !== null}
          onClick={() =>
            pdf.baixar(
              'relatorio',
              caminhoPdfDoRelatorio(usinaId, periodo.de, periodo.ate, contratoEscolhido),
              nomeDoPdfDoRelatorio(nomeDaUsina, periodo.de, periodo.ate),
              PRAZO_DO_RELATORIO_MS,
            )
          }
        >
          {pdf.baixando === 'relatorio' ? 'Preparando o PDF…' : 'Baixar PDF'}
        </Botao>
      </div>

      <Cartao>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-rotulo">contrato</span>
            {opcoes.length === 0 ? (
              // Sem contrato conhecido não há o que escolher; o relatório explica o que falta.
              <span className="text-sm text-fraco">
                {contratos.erro === null ? 'Nenhum contrato cadastrado' : 'Não deu para ler os contratos'}
              </span>
            ) : opcoes.length === 1 ? (
              <span className="text-sm text-corpo">{opcoes[0].rotulo}</span>
            ) : (
              <Combobox
                opcoes={opcoes}
                valor={contratoNaTela === null ? null : String(contratoNaTela)}
                onEscolher={(v) => setContratoEscolhido(Number(v))}
                placeholder="Escolher contrato…"
                className="w-64"
              />
            )}
          </div>

          <SeletorCompetencias
            de={periodo.de}
            ate={periodo.ate}
            onDe={(de) => setPeriodo((p) => ({ ...p, de }))}
            onAte={(ate) => setPeriodo((p) => ({ ...p, ate }))}
            meses={MESES_OFERECIDOS}
          />
        </div>
        {/* O aviso é do servidor (usina sem meuPlano, upstream fora do ar): a tela repete a
            frase dele em vez de escrever a sua, que seria um palpite sobre o que faltou. */}
        {contratos.dados?.aviso ? (
          <div className="mt-3">
            <Aviso>{contratos.dados.aviso}</Aviso>
          </div>
        ) : null}
      </Cartao>

      {pdf.erro === null ? null : <Aviso tom="parado">{pdf.erro}</Aviso>}

      <Tela4Estados
        leitura={relatorio}
        esqueleto={
          <div className="space-y-4">
            <CarregandoCartao linhas={4} />
            <CarregandoCartao linhas={5} />
          </div>
        }
      >
        {(dados) => <Conteudo dados={dados} usinaId={usinaId} navegar={navigate} />}
      </Tela4Estados>
    </section>
  )
}

function Conteudo({
  dados,
  usinaId,
  navegar,
}: {
  dados: RelatorioOut
  usinaId: number
  navegar: (para: string) => void
}) {
  const c = dados.cronograma

  return (
    <div className="space-y-4">
      <Cartao>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Linha rotulo="Usina" valor={dados.usina} />
          <Linha rotulo="Cliente" valor={dados.cliente ?? '—'} />
          <Linha rotulo="Executora" valor={dados.executora ?? '—'} />
          <Linha
            rotulo="Período"
            valor={`${competencia(dados.periodo.de)} a ${competencia(dados.periodo.ate)}`}
          />
        </div>
      </Cartao>

      {/* Aviso do servidor que não é sobre o cronograma (quando é, ele explica o Vazio). */}
      {dados.aviso !== null && c !== null ? <Aviso>{dados.aviso}</Aviso> : null}

      {/* ---------------------------------------------------- cronograma */}
      {c === null ? (
        <Vazio
          titulo="Cronograma não publicado"
          // A frase é do SERVIDOR: ele sabe se falta contrato ou falta consolidar, e o
          // cliente não pode ler "sem cronograma" como "nada foi feito".
          descricao={dados.aviso ?? 'A equipe ainda não publicou o cronograma deste contrato.'}
        />
      ) : (
        <Secao
          titulo="Cronograma cumprido"
          direita={
            c.versao === null ? undefined : (
              <span>
                versão <Num>{inteiro(c.versao)}</Num>
              </span>
            )
          }
        >
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Kpi
              rotulo="Previstas"
              valor={inteiro(c.previstas)}
              detalhe={
                <>
                  no prazo <Num>{inteiro(c.no_prazo)}</Num> · sem ativo{' '}
                  <Num>{inteiro(c.sem_ativo)}</Num>
                </>
              }
            />
            <Kpi rotulo="Executadas" valor={inteiro(c.executadas)} tom="ok" />
            {/* Dispensada não é executada: a contagem anda separada, como no cronograma. */}
            <Kpi rotulo="Dispensadas" valor={inteiro(c.dispensadas)} />
            <Kpi
              rotulo="Atrasadas"
              valor={inteiro(c.atrasadas)}
              // Cor só quando há atraso — é o único estado desta linha que pede reação.
              tom={c.atrasadas > 0 ? 'parado' : undefined}
            />
            <Kpi rotulo="Cumprido" valor={porcento(c.pct_cumprido)} tamanho="grande" />
          </div>

          <div className="mt-5">
            <Tabela
              colunas={[
                {
                  titulo: 'Atividade',
                  celula: (l) => (
                    <div className="min-w-0">
                      <span className="block truncate text-corpo">{l.nome}</span>
                      {l.categoria === null ? null : (
                        <span className="block text-xs text-fraco">
                          {NOME_DA_CATEGORIA[l.categoria] ?? l.categoria}
                        </span>
                      )}
                    </div>
                  ),
                },
                { titulo: 'Previstas', alinhar: 'dir', celula: (l) => <Num>{inteiro(l.previstas)}</Num> },
                { titulo: 'Executadas', alinhar: 'dir', celula: (l) => <Num>{inteiro(l.executadas)}</Num> },
                { titulo: 'Dispensadas', alinhar: 'dir', celula: (l) => <Num>{inteiro(l.dispensadas)}</Num> },
                {
                  titulo: 'Atrasadas',
                  alinhar: 'dir',
                  celula: (l) => (
                    <Num className={l.atrasadas > 0 ? 'text-tom-parado' : ''}>{inteiro(l.atrasadas)}</Num>
                  ),
                },
                { titulo: 'No prazo', alinhar: 'dir', celula: (l) => <Num>{inteiro(l.no_prazo)}</Num> },
                { titulo: 'Sem ativo', alinhar: 'dir', celula: (l) => <Num>{inteiro(l.sem_ativo)}</Num> },
              ]}
              linhas={c.linhas}
              chave={(l) => (l.plan_item_id === null ? l.nome : l.plan_item_id)}
              vazio={
                <p className="text-sm text-fraco">
                  O contrato não previa nenhuma atividade nos meses escolhidos.
                </p>
              }
            />
          </div>

          {c.dispensas.length === 0 ? null : (
            <div className="mt-6">
              <h3 className="mb-2 text-sm font-medium text-corpo">Dispensas do período</h3>
              <Tabela
                colunas={[
                  { titulo: 'Atividade', celula: (d) => d.atividade },
                  { titulo: 'Mês', celula: (d) => <Num>{competenciaCurta(d.mes)}</Num> },
                  { titulo: 'Motivo', celula: (d) => d.motivo ?? '—' },
                ]}
                linhas={c.dispensas}
                chave={(d) => `${d.atividade}-${d.mes}`}
              />
            </div>
          )}
        </Secao>
      )}

      {/* ---------------------------------------------------- ordens */}
      <Secao
        titulo="Ordens encerradas no período"
        direita={
          <span>
            <Num>{inteiro(dados.ordens.length)}</Num> no período
          </span>
        }
      >
        {dados.ordens.length === 0 ? (
          <p className="text-sm text-fraco">Nenhuma ordem de serviço foi encerrada neste período.</p>
        ) : (
          <div className="space-y-3">
            {dados.ordens.map((o) => (
              <CartaoDaOrdem
                key={o.id}
                o={o}
                aoAbrir={() => navegar(`/usinas/${usinaId}/ordens/${o.id}`)}
              />
            ))}
          </div>
        )}
      </Secao>

      {dados.em_curso.length === 0 ? null : (
        <Secao titulo="Em curso agora">
          <div className="space-y-3">
            {dados.em_curso.map((o) => (
              <CartaoDaOrdem
                key={o.id}
                o={o}
                aoAbrir={() => navegar(`/usinas/${usinaId}/ordens/${o.id}`)}
              />
            ))}
          </div>
        </Secao>
      )}

      {/* ---------------------------------------------------- pareceres */}
      <Secao
        titulo="Pareceres das fichas"
        direita={
          dados.fotos === null ? undefined : (
            <span>
              <Num>{inteiro(dados.fotos)}</Num> fotos anexadas
            </span>
          )
        }
      >
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Kpi rotulo="Aprovados" valor={inteiro(dados.pareceres.aprovados)} tom="ok" />
          <Kpi rotulo="Com ressalva" valor={inteiro(dados.pareceres.com_ressalva)} tom="alerta" />
          <Kpi rotulo="Reprovados" valor={inteiro(dados.pareceres.reprovados)} tom="parado" />
          <Kpi rotulo="Sem parecer" valor={inteiro(dados.pareceres.sem_parecer)} tom="semDados" />
        </div>
        {/* O recorte vem escrito do servidor: é ele que impede a página de exibir um
            "Aprovado com ressalva" na OS em curso e "COM RESSALVA 0" logo abaixo. */}
        {dados.pareceres.recorte ? (
          <p className="mt-3 text-xs text-fraco">{dados.pareceres.recorte}</p>
        ) : null}
      </Secao>

      {/* ---------------------------------------------------- problemas */}
      <Secao
        titulo="Problemas encontrados"
        direita={
          <span>
            <Num>{inteiro(dados.problemas.total)}</Num> no total
          </span>
        }
      >
        {dados.problemas.total === 0 ? (
          <p className="text-sm text-fraco">
            As fichas das ordens encerradas no período não registraram problema nenhum.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {dados.problemas.por_criticidade.map((f) => (
                <Selo key={f.criticidade} tom={f.tom}>
                  {f.rotulo}: <Num>{inteiro(f.total)}</Num>
                </Selo>
              ))}
            </div>

            {dados.problemas.por_os.length === 0 ? null : (
              <div className="mt-4">
                <Tabela
                  colunas={[
                    { titulo: 'Ordem de serviço', celula: (p) => p.objetivo },
                    { titulo: 'Problemas', alinhar: 'dir', celula: (p) => <Num>{inteiro(p.total)}</Num> },
                    { titulo: 'Urgentes', alinhar: 'dir', celula: (p) => <Num>{inteiro(p.urgentes)}</Num> },
                    { titulo: '', alinhar: 'dir', celula: (p) => <Selo tom={p.tom}>{p.urgentes > 0 ? 'urgente' : 'atenção'}</Selo> },
                  ]}
                  linhas={dados.problemas.por_os}
                  chave={(p) => (p.os_id === null ? p.objetivo : p.os_id)}
                  aoClicar={(p) =>
                    p.os_id === null ? undefined : navegar(`/usinas/${usinaId}/ordens/${p.os_id}`)
                  }
                />
              </div>
            )}
          </>
        )}
        {dados.problemas.recorte ? (
          <p className="mt-3 text-xs text-fraco">{dados.problemas.recorte}</p>
        ) : null}
      </Secao>

      {/* ---------------------------------------------------- pendências */}
      <Secao titulo="Pendências compartilhadas">
        <div className="grid gap-6 lg:grid-cols-2">
          <PendenciasDaLista
            titulo="Abertas ao fim do período"
            itens={dados.pendencias.abertas}
            vazio="Nenhuma pendência aberta."
            aoAbrir={(p) =>
              navegar(
                p.id === null
                  ? `/usinas/${usinaId}/pendencias`
                  : `/usinas/${usinaId}/pendencias/${p.id}`,
              )
            }
          />
          <PendenciasDaLista
            titulo="Concluídas no período"
            itens={dados.pendencias.concluidas}
            vazio="Nenhuma pendência foi concluída no período."
            aoAbrir={(p) =>
              navegar(
                p.id === null
                  ? `/usinas/${usinaId}/pendencias`
                  : `/usinas/${usinaId}/pendencias/${p.id}`,
              )
            }
          />
        </div>
      </Secao>
    </div>
  )
}
