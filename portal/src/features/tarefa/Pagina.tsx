/**
 * UMA TAREFA da ordem de serviço — o que foi medido, o que foi respondido e as FOTOS.
 *
 * O dono, olhando a OS 1016: *"tem as tarefas, porém elas não são clicáveis, são como
 * checklist. Eu preciso ABRIR as tarefas e ver as respostas delas"* — e, depois: *"as tarefas
 * não aparece foto em nenhuma"*. Esta é a tela que responde às duas frases. O PDF continua
 * sendo o laudo; isto é a leitura, e as duas saem da MESMA fonte no meuPlano, então não
 * divergem.
 *
 * Três decisões que moldam o desenho:
 *
 * **Duas leituras, não uma.** O cabeçalho é barato e a ficha é a leitura mais cara do portal
 * (uma coletiva de vinte inversores é montada do zero no meuPlano). A tela abre com o
 * cabeçalho e as respostas chegam em seguida; se a ficha falhar e o cabeçalho vier, a página
 * NÃO morre — ela diz que não deu para carregar as respostas e aponta o PDF, que continua
 * disponível.
 *
 * **Cada foto aparece uma vez só.** `equipamento.fotos` já soma as da sessão com as das
 * respostas. Desenhar as duas listas sem deduplicar mostraria cada evidência duas vezes; não
 * percorrer as perguntas mostraria zero — foi o defeito real, com 61 fotos guardadas nas
 * respostas de um checklist. Aqui a foto da resposta fica JUNTO da pergunta (é o que deixa
 * claro o que ela prova) e o rodapé do equipamento leva só as que não têm pergunta dona.
 *
 * **O estado vem na frente do valor.** Num item de serviço o que importa é "Não feito", não o
 * "1" que está no lugar da medida — e "Não feito" não é reprovação: `situacao` é rótulo,
 * `aprovado` é julgamento, e são campos diferentes de propósito.
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
  Vazio,
} from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { abrirPdf } from '@/lib/arquivo'
import { competencia, dataPorExtenso } from '@/lib/format'
import { Fotos } from '@/features/tarefa/Fotos'
import {
  caminhoDoPdfDaTarefa,
  ehNaoEncontrada,
  useFicha,
  useTarefa,
  type EquipamentoDaFicha,
  type Ficha,
  type Medicao,
  type SecaoChecklist,
  type Tarefa,
} from '@/features/tarefa/api'

/**
 * A cor de um parecer da FICHA.
 *
 * O cabeçalho da tarefa recebe `parecer_tom` PRONTO do servidor e usa aquele — é a régua do
 * produto. A ficha ainda não manda tom por equipamento (ver a pendência registrada na
 * entrega), então aqui a cor é deduzida, e com uma regra que **nunca inventa verde**:
 * desconhecido sai neutro. Foi exatamente o contrário disso (um `return 'ok'` de fallback)
 * que fazia a tela da ordem pintar de "aprovado" um veredito que ninguém tinha lido.
 */
function tomDoParecer(parecer: string | null): string {
  if (!parecer) return 'semDados'
  if (/reprov/i.test(parecer)) return 'parado'
  if (/ressalva/i.test(parecer)) return 'alerta'
  if (/aprov/i.test(parecer)) return 'ok'
  return 'semDados'
}

export default function TarefaDaOrdem() {
  const { id, osId, taskId } = useParams<{ id: string; osId: string; taskId: string }>()
  const leitura = useTarefa(osId, taskId)
  const ficha = useFicha(osId, taskId)

  const [baixando, setBaixando] = useState(false)
  const [erroPdf, setErroPdf] = useState<string | null>(null)

  const voltar = id && osId ? `/usinas/${id}/manutencao/ordens/${osId}` : '/'

  /**
   * Chamado direto do `onClick`: `abrirPdf` abre a aba no ato do gesto e só depois a aponta
   * para o Blob — esperar o download antes de abrir faria o bloqueador de popup derrubar
   * tudo. O prazo é folgado porque o meuPlano RENDERIZA o documento na hora do pedido.
   */
  const abrir = async () => {
    if (!osId || !taskId) return
    setErroPdf(null)
    setBaixando(true)
    try {
      await abrirPdf(caminhoDoPdfDaTarefa(osId, Number(taskId)), `tarefa-${taskId}.pdf`, {
        prazoMs: 180_000,
      })
    } catch (erro) {
      setErroPdf(mensagemDeErro(erro))
    } finally {
      setBaixando(false)
    }
  }

  // 404 não é falha de leitura: é "esta tarefa não é desta ordem, ou não é sua" (o BFF
  // responde 404 e não 403 de propósito, para não confirmar a existência da tarefa de outro
  // cliente). Um estado vazio com o caminho de volta responde melhor que "Tentar de novo",
  // que insistiria numa porta que nunca vai abrir.
  if (ehNaoEncontrada(leitura)) {
    return (
      <Pagina titulo="Tarefa">
        <Vazio
          titulo="Tarefa não encontrada"
          descricao="Ela pode ter sido removida da ordem de serviço, ou é de uma usina que não está liberada para a sua conta."
          acao={
            <Link
              to={voltar}
              className="inline-flex min-h-[38px] items-center rounded-campo border border-borda-forte px-3.5 text-sm font-medium text-corpo transition hover:bg-superficie-alta"
            >
              Ver a ordem de serviço
            </Link>
          }
        />
      </Pagina>
    )
  }

  const t = leitura.dados

  return (
    <Pagina
      titulo="Tarefa"
      subtitulo={
        <span className="flex flex-wrap items-center gap-2">
          <Link to={voltar} className="text-fraco transition hover:text-corpo">
            ‹ Ordem de serviço {osId ?? ''}
          </Link>
          {t?.grupo ? <span className="text-fraco">· {t.grupo}</span> : null}
        </span>
      }
    >
      <div className="space-y-4">
        {erroPdf ? <Aviso tom="parado">{erroPdf}</Aviso> : null}

        {leitura.carregando && !t ? (
          <CarregandoCartao linhas={4} />
        ) : t === null ? (
          // Sem cabeçalho não há tela: aqui é rede caída de verdade, e insistir resolve.
          <Cartao className="border-tom-parado/40">
            <p className="text-sm font-medium text-tom-parado">Não deu para carregar</p>
            <p className="mt-1 text-sm text-corpo">
              {leitura.erro ?? 'O servidor não devolveu dados.'}
            </p>
            <div className="mt-4">
              <Botao variante="secundario" onClick={leitura.recarregar}>
                Tentar de novo
              </Botao>
            </div>
          </Cartao>
        ) : (
          <>
            <Cabecalho tarefa={t} />
            {t.descricao || t.observacoes ? <Registro tarefa={t} /> : null}
            <Respostas leitura={ficha} />
          </>
        )}

        <Cartao>
          <CabecalhoCard
            rotulo="Ficha em PDF"
            direita={
              // ZERO é resposta ("nada respondido ainda"); nulo é "não informado" e some.
              typeof t?.preenchimento === 'number' ? (
                <span>
                  <Num>{t.preenchimento}</Num>% respondida
                </span>
              ) : undefined
            }
          />
          <p className="text-sm text-corpo">
            O documento que vale como laudo, com as medições, as respostas e as fotos desta
            tarefa. Abre em outra aba do navegador.
          </p>
          <div className="mt-4">
            <Botao desabilitado={baixando || !taskId} onClick={() => void abrir()}>
              {baixando ? 'Preparando o PDF…' : 'Abrir a ficha em PDF'}
            </Botao>
          </div>
        </Cartao>
      </div>
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

function Cabecalho({ tarefa: t }: { tarefa: Tarefa }) {
  return (
    <Cartao>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold leading-snug text-forte">{t.nome}</h2>
          {t.equipamento ? <p className="mt-1 text-sm text-fraco">{t.equipamento}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Selo tom={t.feita ? 'ok' : 'semDados'}>{t.situacao}</Selo>
          {/* A cor do parecer da TAREFA vem pronta do servidor — aqui não se deduz nada. */}
          {t.parecer ? <Selo tom={t.parecer_tom ?? 'semDados'}>{t.parecer}</Selo> : null}
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Dado rotulo="Natureza">
          {t.natureza === 'INSPECAO' ? 'Inspeção' : t.natureza === 'SERVICO' ? 'Serviço' : '—'}
        </Dado>
        <Dado rotulo="Executada">
          <Num>{dataPorExtenso(t.executada_em)}</Num>
        </Dado>
        <Dado rotulo="Mês do contrato">
          <Num>{competencia(t.mes_contratual)}</Num>
        </Dado>
        <Dado rotulo="Ordem de serviço">
          <Num>{t.os_id === null ? '—' : t.os_id}</Num>
        </Dado>
      </dl>
    </Cartao>
  )
}

/** O que a tarefa pedia e o que o técnico anotou — sem os dois, o cartão não existe. */
function Registro({ tarefa: t }: { tarefa: Tarefa }) {
  return (
    <Cartao>
      <CabecalhoCard rotulo="Registro do técnico" />
      {t.descricao ? (
        <>
          <p className="text-[11px] uppercase tracking-wide text-rotulo">O que era para fazer</p>
          <p className="mt-1 whitespace-pre-line text-sm text-corpo">{t.descricao}</p>
        </>
      ) : null}
      {t.observacoes ? (
        <div className={t.descricao ? 'mt-4' : ''}>
          <p className="text-[11px] uppercase tracking-wide text-rotulo">Observações</p>
          <p className="mt-1 whitespace-pre-line text-sm text-corpo">{t.observacoes}</p>
        </div>
      ) : null}
    </Cartao>
  )
}

/* ------------------------------------------------------------------ respostas */

function Respostas({
  leitura,
}: {
  leitura: { dados: Ficha | null; carregando: boolean; erro: string | null }
}) {
  if (leitura.carregando && !leitura.dados) {
    return (
      <Cartao>
        <Esqueleto altura={14} largura="35%" />
        <div className="mt-4 space-y-3">
          <Esqueleto altura={12} largura="90%" />
          <Esqueleto altura={12} largura="70%" />
          <Esqueleto altura={78} />
        </div>
      </Cartao>
    )
  }

  // A ficha caiu, mas o cabeçalho está na tela: a página não morre, e o caminho que
  // funciona fica escrito. Chamar isto de erro da tela seria esconder o resto do que veio.
  if (!leitura.dados) {
    return (
      <Cartao>
        <CabecalhoCard rotulo="Respostas" />
        <p className="text-sm text-fraco">
          Não deu para carregar as respostas agora. A ficha em PDF, abaixo, continua
          disponível.
        </p>
      </Cartao>
    )
  }

  const equipamentos = Array.isArray(leitura.dados.equipamentos) ? leitura.dados.equipamentos : []
  if (equipamentos.length === 0) {
    return (
      <Cartao>
        <CabecalhoCard rotulo="Respostas" />
        <p className="text-sm text-fraco">Nada foi registrado nesta ficha ainda.</p>
      </Cartao>
    )
  }

  return (
    <>
      {equipamentos.map((e, i) => (
        <BlocoEquipamento key={`${e.equipamento}-${i}`} equipamento={e} />
      ))}
    </>
  )
}

/** Um equipamento da ficha: o que foi medido e o que foi respondido nele. */
function BlocoEquipamento({ equipamento: e }: { equipamento: EquipamentoDaFicha }) {
  const medicoes = Array.isArray(e.medicoes) ? e.medicoes : []
  const checklist = Array.isArray(e.checklist) ? e.checklist : []

  // `e.fotos` traz TUDO (sessão + respostas). Aqui ficam só as que não têm pergunta dona,
  // para nenhuma evidência aparecer duas vezes na mesma tela.
  const daPergunta = new Set(
    checklist.flatMap((sec) =>
      (Array.isArray(sec.perguntas) ? sec.perguntas : []).flatMap((p) =>
        Array.isArray(p.fotos) ? p.fotos.map((f) => f.id) : [],
      ),
    ),
  )
  const soltas = Array.isArray(e.fotos) ? e.fotos.filter((f) => !daPergunta.has(f.id)) : []

  const identidade = [e.modelo, e.fabricante, e.numero_serie ? `nº ${e.numero_serie}` : null]
    .filter(Boolean)
    .join(' · ')
  const autoria = [e.executado_por, e.executado_em].filter(Boolean).join(' · ')

  return (
    <Cartao>
      <CabecalhoCard
        rotulo={e.equipamento}
        direita={
          e.parecer ? <Selo tom={tomDoParecer(e.parecer)}>{e.parecer}</Selo> : undefined
        }
      />

      {identidade ? <p className="text-xs text-fraco">{identidade}</p> : null}
      {autoria ? <p className="mt-0.5 text-xs text-fraco">{autoria}</p> : null}
      {e.parecer_motivo ? <p className="mt-2 text-sm text-corpo">{e.parecer_motivo}</p> : null}

      {medicoes.map((m, i) => (
        <BlocoMedicao key={`${m.nome}-${i}`} medicao={m} />
      ))}

      {checklist.map((sec, i) => (
        <BlocoChecklist key={`${sec.nome}-${i}`} secao={sec} />
      ))}

      {medicoes.length === 0 && checklist.length === 0 ? (
        <p className="text-sm text-fraco">Nada foi registrado nesta ficha ainda.</p>
      ) : null}

      {/* AS FOTOS DA SESSÃO. As que pendem de uma RESPOSTA aparecem junto da pergunta, acima
          — separá-las é o que deixa claro o que cada foto está provando. */}
      <Fotos fotos={soltas} titulo={soltas.length === 1 ? 'Foto' : 'Fotos'} />
    </Cartao>
  )
}

/** Uma medição: cada ponto com o que foi lido. */
function BlocoMedicao({ medicao: m }: { medicao: Medicao }) {
  const linhas = Array.isArray(m.linhas) ? m.linhas : []
  return (
    <section className="mt-4">
      <h3 className="text-[11px] uppercase tracking-wide text-rotulo">
        {m.nome}
        {m.unidade ? <span className="ml-1 normal-case text-fraco">({m.unidade})</span> : null}
      </h3>

      <ul className="mt-1">
        {linhas.map((l, i) => (
          <li
            key={`${l.ponto}-${i}`}
            className="flex items-start justify-between gap-3 border-b border-borda-fraca py-1.5 last:border-0"
          >
            {/* Um item de torque ou de serviço não tem "ponto": o nome da medição já é o
                assunto, e um travessão à esquerda de cada linha não diz nada. */}
            <span className="min-w-0 flex-1 text-sm text-corpo">
              {l.ponto && l.ponto !== '—' ? l.ponto : m.nome}
              {l.observacao ? (
                <span className="mt-0.5 block text-xs text-fraco">{l.observacao}</span>
              ) : null}
            </span>

            <span className="shrink-0 text-right">
              {/*
               * O ESTADO na frente do valor. Num item de serviço o que importa é "Não feito",
               * não o "1" que está no lugar da medida — e o rótulo NÃO é veredito: a cor só
               * aparece quando `aprovado` diz alguma coisa.
               */}
              {l.situacao ? (
                <span
                  className={`text-sm font-medium ${
                    l.aprovado === false
                      ? 'text-tom-parado'
                      : l.aprovado === true
                        ? 'text-tom-ok'
                        : 'text-rotulo'
                  }`}
                >
                  {l.situacao}
                </span>
              ) : (
                // Valor ausente vira "—". Zero é medição e aparece como zero.
                <Num className="text-sm text-forte">
                  {l.valor ?? '—'}
                  {l.valor && l.unidade ? ` ${l.unidade}` : ''}
                </Num>
              )}

              {l.situacao === null && l.aprovado === false ? (
                <span className="mt-0.5 block text-[11px] font-medium text-tom-parado">
                  reprovado
                </span>
              ) : null}

              {l.alvo ? (
                <span className="mt-0.5 block text-[11px] text-fraco">
                  alvo <Num>{l.alvo}</Num>
                  {l.desvio ? (
                    <>
                      {' · desvio '}
                      <Num>{l.desvio}</Num>
                    </>
                  ) : null}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Uma seção do checklist: a pergunta, o que foi respondido e a foto daquela resposta. */
function BlocoChecklist({ secao }: { secao: SecaoChecklist }) {
  const perguntas = Array.isArray(secao.perguntas) ? secao.perguntas : []
  return (
    <section className="mt-4">
      <h3 className="text-[11px] uppercase tracking-wide text-rotulo">{secao.nome}</h3>
      <ul className="mt-1">
        {perguntas.map((p, i) => (
          <li key={`${p.pergunta}-${i}`} className="border-b border-borda-fraca py-2 last:border-0">
            <p className="text-sm text-corpo">{p.pergunta}</p>
            {/* A polaridade é do meuPlano: `problema` já diz se ESTA resposta é a ruim. */}
            <p
              className={`mt-0.5 text-sm font-medium ${
                p.problema ? 'text-tom-parado' : 'text-forte'
              }`}
            >
              {p.resposta ?? '—'}
            </p>
            {p.observacao ? <p className="mt-0.5 text-xs text-fraco">{p.observacao}</p> : null}
            <Fotos fotos={p.fotos} />
          </li>
        ))}
      </ul>
    </section>
  )
}
