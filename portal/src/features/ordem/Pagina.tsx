/**
 * Uma ordem de serviço — "o que foi feito nesta OS, item por item, e como terminou?".
 *
 * A lista (`/usinas/:id/manutencao/ordens`) responde "está sendo feito?". Esta responde a
 * seguinte, que é a que o cliente faz quando a fatura da manutenção chega — e só ela.
 *
 * Três decisões que moldam o desenho:
 *
 * **A situação é a frase do SERVIDOR.** `FECHADA` não quer dizer "encerrada" para quem é dono:
 * quer dizer que o técnico concluiu e o gestor ainda não conferiu. O BFF traduz isso em "Em
 * verificação" e manda o tom junto (`bff/app/api/v1/manutencao.py`, `SITUACAO`). Traduzir de
 * novo aqui criaria uma segunda verdade sobre a mesma OS.
 *
 * **Aqui não entra medição, checklist nem foto — mas a tarefa ABRE.** Esta tela continua sendo
 * o resumo ("está sendo feito?"); o detalhe de cada item mora na ficha da tarefa, uma tela
 * própria (`/usinas/:id/manutencao/ordens/:osId/tarefas/:taskId`). Até aqui a linha da tarefa
 * era uma div com um botão de PDF ao lado — a mesma queixa que o dono já tinha feito do
 * aplicativo, "as tarefas não são clicáveis, são como checklist". Agora a linha é um link e o
 * botão continua onde estava: ele deixa de ser a ÚNICA saída, não some.
 *
 * **`itens` nulo ≠ `itens` vazio.** O BFF devolve o cabeçalho da OS mesmo quando a busca das
 * tarefas falha, e nesse caso `itens` vem nulo. Dizer "esta ordem não tem tarefas" numa falha
 * de rede seria acusar a equipe de não ter feito o serviço.
 *
 * Os PDFs vão por `fetch` com a sessão em CABEÇALHO (`lib/arquivo.ts`): `<a href>` não manda
 * cabeçalho, e a saída fácil — o token na query — entra em log de servidor e em histórico.
 */

import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  Aviso,
  Botao,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  Esqueleto,
  Num,
  Pagina,
  Selo,
  SeloClasse,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { abrirPdf } from '@/lib/arquivo'
import { dataPorExtenso, duracao, inteiro } from '@/lib/format'
import {
  caminhoDaTarefa,
  caminhoDoPdfDaOrdem,
  caminhoDoPdfDaTarefa,
  ehNaoEncontrada,
  useOrdem,
  type Ordem as OrdemDeServico,
  type Tarefa,
} from '@/features/ordem/api'

/** As seções na ordem em que vieram — o BFF já ordenou por grupo e nome. */
function agrupar(itens: Tarefa[]): [string, Tarefa[]][] {
  const mapa = new Map<string, Tarefa[]>()
  for (const t of itens) {
    const secao = t.grupo ?? 'Outras'
    const atual = mapa.get(secao)
    if (atual) atual.push(t)
    else mapa.set(secao, [t])
  }
  return [...mapa.entries()]
}

export default function Ordem() {
  const { id, osId } = useParams<{ id: string; osId: string }>()
  const leitura = useOrdem(osId)

  // Qual PDF está sendo preparado, e o que deu errado no último. O erro fica NA TELA (faixa):
  // popup do navegador é proibido no produto, e um alerta some antes de ser lido.
  const [baixando, setBaixando] = useState<string | null>(null)
  const [erroPdf, setErroPdf] = useState<string | null>(null)

  // O endereço novo, com a família no meio. O antigo (`/usinas/:id/ordens`) ainda funciona por
  // redirecionamento, mas mandar o cliente para ele daria um salto visível a cada clique.
  const voltar = id ? `/usinas/${id}/manutencao/ordens` : '/'

  /**
   * Chamado direto do `onClick`: `abrirPdf` abre a aba no ato do gesto e só depois a aponta
   * para o Blob — esperar o download antes de abrir faria o bloqueador de popup derrubar
   * tudo. O prazo é folgado porque o meuPlano RENDERIZA o documento na hora do pedido.
   */
  const abrir = async (chave: string, caminho: string, nome: string) => {
    setErroPdf(null)
    setBaixando(chave)
    try {
      await abrirPdf(caminho, nome, { prazoMs: 180_000 })
    } catch (erro) {
      setErroPdf(mensagemDeErro(erro))
    } finally {
      setBaixando(null)
    }
  }

  // 404 do BFF não é falha de leitura: é "esta OS não existe ou não é sua" (`_ordem_autorizada`
  // responde 404 e não 403 de propósito, para não confirmar a existência da OS de outro
  // cliente). Um estado vazio com o caminho de volta responde melhor que "Tentar de novo", que
  // insistiria numa porta que nunca vai abrir.
  if (ehNaoEncontrada(leitura)) {
    return (
      <Pagina titulo="Ordem de serviço">
        <Vazio
          titulo="Ordem de serviço não encontrada"
          descricao="Ela pode ter sido removida, ou é de uma usina que não está liberada para a sua conta."
          acao={
            <Link
              to={voltar}
              className="inline-flex min-h-[38px] items-center rounded-campo border border-borda-forte px-3.5 text-sm font-medium text-corpo transition hover:bg-superficie-alta"
            >
              Ver as ordens de serviço
            </Link>
          }
        />
      </Pagina>
    )
  }

  return (
    <Pagina
      // Identificador não leva máscara de milhar: "OS 1.005" não é o número de OS nenhuma.
      titulo={`OS ${osId ?? ''}`}
      subtitulo={
        <span className="flex flex-wrap items-center gap-2">
          <Link to={voltar} className="text-fraco transition hover:text-corpo">
            ‹ Ordens de serviço
          </Link>
          {leitura.dados ? <span className="text-fraco">· {leitura.dados.usina}</span> : null}
        </span>
      }
    >
      <Tela4Estados
        leitura={leitura}
        esqueleto={
          <div className="space-y-4">
            <Cartao>
              <Esqueleto altura={18} largura="60%" />
              <div className="mt-4 space-y-3">
                <Esqueleto altura={12} largura="40%" />
                <Esqueleto altura={12} largura="55%" />
              </div>
            </Cartao>
            <CarregandoCartao linhas={5} />
          </div>
        }
      >
        {(o) => (
          <>
            {erroPdf ? <Aviso tom="parado">{erroPdf}</Aviso> : null}

            <Cabecalho ordem={o} />

            <Tarefas
              ordem={o}
              // Sem o `:id` da URL vale o vínculo que a própria OS declara — é o mesmo número.
              usinaId={id ?? String(o.usina_id)}
              osId={osId ?? String(o.id)}
              baixando={baixando}
              aoAbrirPdf={abrir}
            />

            <Cartao>
              {/*
                "A ordem em PDF", e não "Ficha em PDF": a ficha é de UMA tarefa e tem botão
                próprio em cada linha lá em cima. Os dois rótulos iguais na mesma tela liam-se
                como o mesmo arquivo — e chegaram a fazer a busca por texto de um teste casar
                com o título do cartão em vez do botão da tarefa.
              */}
              <CabecalhoCard rotulo="A ordem em PDF" />
              <p className="text-sm text-corpo">
                A ordem completa, com as tarefas e as fichas preenchidas pelo técnico. O arquivo
                abre em outra aba do navegador.
              </p>
              <div className="mt-4">
                <Botao
                  desabilitado={baixando !== null}
                  onClick={() =>
                    void abrir(
                      'os',
                      caminhoDoPdfDaOrdem(osId ?? o.id),
                      `OS-${o.id}-${o.usina}.pdf`.replace(/\s+/g, '-'),
                    )
                  }
                >
                  {baixando === 'os' ? 'Preparando o PDF…' : 'Abrir a OS em PDF'}
                </Botao>
              </div>
            </Cartao>
          </>
        )}
      </Tela4Estados>
    </Pagina>
  )
}

/* ------------------------------------------------------------------ cabeçalho */

function Dado({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-rotulo">{rotulo}</dt>
      <dd className="mt-0.5 truncate text-sm text-corpo">{children}</dd>
    </div>
  )
}

function Cabecalho({ ordem: o }: { ordem: OrdemDeServico }) {
  return (
    <Cartao>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="min-w-0 text-lg font-semibold leading-snug text-forte">{o.objetivo}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <SeloClasse classificacao={o.classificacao} tom={o.classificacao_tom} />
          <Selo tom={o.tom}>{o.situacao}</Selo>
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Dado rotulo="Técnico">{o.tecnico ?? '—'}</Dado>
        <Dado rotulo="Contrato">
          {/* Número de contrato é identificador: sem separador de milhar. */}
          <Num>{o.contrato_numero === null ? '—' : `nº ${o.contrato_numero}`}</Num>
        </Dado>
        <Dado rotulo="Agendada">
          <Num>{dataPorExtenso(o.agendada_para)}</Num>
        </Dado>
        <Dado rotulo="Concluída">
          {/* `end_date` é a data de conclusão; sem ela vale o carimbo de fechamento, que é o
              instante em que o técnico encerrou. Um dos dois costuma existir. */}
          <Num>{dataPorExtenso(o.concluida_em ?? o.fechada_em)}</Num>
        </Dado>
        <Dado rotulo="Verificada">
          <Num>{dataPorExtenso(o.aprovada_em)}</Num>
        </Dado>
        <Dado rotulo="Execução">
          <Num>{duracao(o.execucao_min)}</Num>
        </Dado>
      </dl>

      {o.resumo ? (
        <p className="mt-5 whitespace-pre-line border-t border-borda-fraca pt-4 text-sm text-corpo">
          {o.resumo}
        </p>
      ) : null}
    </Cartao>
  )
}

/* ------------------------------------------------------------------ tarefas */

function Tarefas({
  ordem: o,
  usinaId,
  osId,
  baixando,
  aoAbrirPdf,
}: {
  ordem: OrdemDeServico
  usinaId: string
  osId: string
  baixando: string | null
  aoAbrirPdf: (chave: string, caminho: string, nome: string) => Promise<void>
}) {
  return (
    <Cartao>
      <CabecalhoCard
        rotulo="O que foi feito"
        direita={
          // Contagem nula = o upstream não informou. `inteiro` escreve "—", nunca zero.
          o.tarefas === null ? undefined : (
            <span>
              <Num className="text-sm text-forte">{inteiro(o.tarefas_feitas)}</Num>
              {` de ${inteiro(o.tarefas)}`}
            </span>
          )
        }
      />

      {/* As duas frases que nunca podem virar uma só — ver o cabeçalho do módulo. */}
      {!Array.isArray(o.itens) ? (
        <p className="text-sm text-fraco">
          Não deu para carregar as tarefas desta ordem. O restante da ficha está acima.
        </p>
      ) : o.itens.length === 0 ? (
        <p className="text-sm text-fraco">Esta ordem não tem tarefas registradas.</p>
      ) : (
        <div className="space-y-5">
          {agrupar(o.itens).map(([secao, itens]) => (
            <section key={secao}>
              <h3 className="mb-1 text-[11px] uppercase tracking-wide text-rotulo">{secao}</h3>
              <ul>
                {itens.map((t, i) => (
                  <li key={t.id ?? `${secao}-${i}`}>
                    <ItemTarefa
                      tarefa={t}
                      usinaId={usinaId}
                      osId={osId}
                      baixando={baixando}
                      aoAbrirPdf={aoAbrirPdf}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Cartao>
  )
}

/**
 * Uma linha da lista: o link para a ficha da tarefa, com o botão do PDF ao lado.
 *
 * O botão é IRMÃO do link, não filho: clique nele não passa pelo link, e não é preciso barrar
 * a propagação de nada. Botão dentro de âncora, além de HTML inválido, é o desenho em que um
 * clique mal calculado abre a tela quando o cliente queria o arquivo.
 *
 * Tarefa sem `id` (caso raro do upstream) não vira link nem ganha botão, e também não recebe
 * o "›": destino que não existe não pode parecer clicável.
 */
function ItemTarefa({
  tarefa: t,
  usinaId,
  osId,
  baixando,
  aoAbrirPdf,
}: {
  tarefa: Tarefa
  usinaId: string
  osId: string
  baixando: string | null
  aoAbrirPdf: (chave: string, caminho: string, nome: string) => Promise<void>
}) {
  const tarefaId = t.id
  const chave = `t-${tarefaId}`

  const corpo = (
    <>
      {/* O ✓ vem do servidor (`feita`), não de comparar textos de status aqui. */}
      <span
        aria-hidden
        className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border text-[11px] leading-none ${
          t.feita ? 'border-tom-ok bg-tom-ok text-fundo' : 'border-borda-forte'
        }`}
      >
        {t.feita ? '✓' : ''}
      </span>

      <span className="min-w-0 flex-1">
        <span className={`block text-sm ${t.feita ? 'text-corpo' : 'text-fraco'}`}>{t.nome}</span>
        {t.equipamento ? (
          <span className="mt-0.5 block text-xs text-fraco">{t.equipamento}</span>
        ) : null}

        <span className="mt-1.5 flex flex-wrap items-center gap-2">
          {/* Situação só quando NÃO está feita: no item com ✓ a palavra "Executada" repete o
              que o próprio ✓ acabou de dizer. */}
          {t.feita ? null : <span className="text-xs text-rotulo">{t.situacao}</span>}
          {t.parecer ? <Selo tom={t.parecer_tom ?? 'semDados'}>{t.parecer}</Selo> : null}
        </span>
      </span>

      {tarefaId === null ? null : (
        <span aria-hidden className="mt-0.5 shrink-0 text-fraco">
          ›
        </span>
      )}
    </>
  )

  const linha = 'flex min-w-0 flex-1 items-start gap-3 text-left'

  return (
    <div className="flex items-start gap-3 border-b border-borda-fraca py-3 last:border-0">
      {tarefaId === null ? (
        <div className={linha}>{corpo}</div>
      ) : (
        <Link
          to={caminhoDaTarefa(usinaId, osId, tarefaId)}
          className={`${linha} transition hover:text-forte`}
        >
          {corpo}
        </Link>
      )}

      {tarefaId === null ? null : (
        <Botao
          variante="secundario"
          className="shrink-0 whitespace-nowrap"
          desabilitado={baixando !== null}
          onClick={() =>
            void aoAbrirPdf(chave, caminhoDoPdfDaTarefa(osId, tarefaId), `tarefa-${tarefaId}.pdf`)
          }
        >
          {baixando === chave ? 'Preparando…' : 'Ficha em PDF'}
        </Botao>
      )}
    </div>
  )
}
