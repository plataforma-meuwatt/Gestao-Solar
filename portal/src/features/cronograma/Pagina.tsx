/**
 * Cronograma — O que o contrato prevê mês a mês foi feito?
 *
 * É o "X" que o dono descreveu: uma linha por atividade do contrato, doze colunas de mês, e
 * em cada cruzamento a marca do que aconteceu. A tela responde UMA pergunta — está sendo
 * feito? — e por isso não mostra medição, checklist nem equipamento: quem quiser descer até
 * o laudo abre a tarefa e, de lá, o PDF.
 *
 * Quatro decisões que não podem se perder numa refatoração:
 *
 * **Os meses são os do CONTRATO.** A ordem vem de `meses` (a âncora da vigência), então um
 * contrato que começa em março abre em "mar/26". Desenhar janeiro→dezembro entregaria um
 * cronograma que não é o que foi assinado.
 *
 * **Feito ≠ dispensado.** O X cheio é executado; o X vazado com "D" é dispensa registrada
 * com motivo. Fundir os dois faria o cliente ler "cumprido" onde a equipe registrou "não
 * precisou desta vez" — a distinção é do meuPlano e sobrevive até aqui.
 *
 * **Sem consolidação, a tela DIZ isso.** Contrato só com rascunho responde 200 com a matriz
 * vazia e a frase do servidor. Desenhar uma grade em branco seria pior que não desenhar
 * nada: lê-se como "nada foi feito", que é uma acusação — e não é o que o dado diz.
 *
 * **A célula abre.** Clicar num mês previsto mostra as tarefas por trás daquele X, com a
 * porta para a OS que as executou.
 */

import { useState, type ReactNode } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import {
  AtualizadoAs,
  Aviso,
  Botao,
  Cartao,
  Combobox,
  Esqueleto,
  Kpi,
  Modal,
  Num,
  Pagina,
  Selo,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { abrirPdf } from '@/lib/arquivo'
import { competencia, competenciaCurta, dataCurta, inteiro, porcento } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import { classesDoTom } from '@/lib/tons'
import {
  caminhoPdfCronograma,
  chaveContratos,
  chaveCronograma,
  chaveTarefasDoMes,
  rotuloDoContrato,
  tomDaCelula,
  type Celula,
  type Contrato,
  type ContratosOut,
  type CronogramaOut,
  type LinhaCronograma,
  type Tarefa,
} from '@/features/cronograma/api'

/* ------------------------------------------------------------------ a marca da célula */

/**
 * O que aconteceu naquele mês, em um símbolo.
 *
 * X cheio verde = executada · X vazado com "D" = dispensada (com motivo) · X vermelho =
 * atrasada · ponto = prevista, ainda no prazo · vazio = o contrato não prevê nada ali.
 *
 * O `title` e o `aria-label` carregam a mesma informação em palavras: cor sozinha não é
 * legenda, e este quadro é lido em reunião, muitas vezes projetado.
 */
function Marca({ celula }: { celula: Celula }) {
  const c = classesDoTom(tomDaCelula(celula))
  const caixa =
    'inline-flex h-6 w-6 items-center justify-center rounded-chip border text-xs font-semibold'

  if (celula.feito) {
    return (
      <span
        title="Executada"
        aria-label="Executada"
        className={`${caixa} ${c.texto} ${c.borda} ${c.fundo}`}
      >
        ✕
      </span>
    )
  }

  if (celula.dispensado) {
    // Vazado de propósito: a dispensa entra na conta do cumprido, mas NUNCA se veste de
    // execução. O "D" é a resposta para o que o cliente pergunta ao ver verde num mês sem
    // visita — e é por isso que o X cheio fica reservado ao que foi realmente feito.
    return (
      <span
        title="Dispensada — a equipe registrou o motivo"
        aria-label="Dispensada com motivo registrado"
        className={`relative ${caixa} border-dashed ${c.texto} ${c.borda}`}
      >
        ✕
        <span
          aria-hidden
          className={`absolute -right-1.5 -top-1.5 rounded-chip bg-fundo px-1 text-[9px] leading-[1.2] ${c.texto}`}
        >
          D
        </span>
      </span>
    )
  }

  if (celula.atrasado) {
    return (
      <span
        title="Atrasada"
        aria-label="Atrasada"
        className={`${caixa} ${c.texto} ${c.borda} ${c.fundo}`}
      >
        ✕
      </span>
    )
  }

  if (celula.previsto > 0) {
    return (
      <span
        title="Prevista"
        aria-label="Prevista"
        className={`inline-block h-2 w-2 rounded-chip bg-tom-${c.tom}`}
      />
    )
  }

  // Mês sem previsão fica VAZIO na tela. Uma marca cinza aqui se leria como "pendente".
  return <span className="sr-only">Sem previsão</span>
}

const CELULA_BASE: Celula = {
  mes: '',
  previsto: 1,
  estado: null,
  feito: false,
  dispensado: false,
  atrasado: false,
}

function Legenda() {
  const item = (celula: Celula, texto: string) => (
    <span className="inline-flex items-center gap-1.5">
      <Marca celula={celula} />
      <span>{texto}</span>
    </span>
  )
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-fraco">
      {item({ ...CELULA_BASE, estado: 'verde', feito: true }, 'executada')}
      {item({ ...CELULA_BASE, estado: 'verde_ressalva', dispensado: true }, 'dispensada')}
      {item({ ...CELULA_BASE, estado: 'vermelho', atrasado: true }, 'atrasada')}
      {item({ ...CELULA_BASE, estado: 'azul' }, 'prevista')}
      <span>célula vazia = o contrato não prevê nada no mês</span>
    </div>
  )
}

/* ------------------------------------------------------------------ tarefas de um mês */

type CelulaAberta = { planItemId: number; nome: string; mes: string }

/**
 * As tarefas por trás de UM X.
 *
 * A pergunta aqui é curta ("o que foi feito neste mês?"), por isso é modal e não página: o
 * cliente confere e volta para a grade sem perder o lugar. O detalhe do que foi medido vive
 * na tarefa e no PDF — esta lista é a ponte para a OS que executou.
 */
function TarefasDoMes({
  usinaId,
  celula,
  aoFechar,
}: {
  usinaId: number
  celula: CelulaAberta
  aoFechar: () => void
}) {
  const navigate = useNavigate()
  const leitura = useLeitura<Tarefa[]>(chaveTarefasDoMes(usinaId, celula.planItemId, celula.mes))

  return (
    <Modal titulo={`${celula.nome} · ${competencia(celula.mes)}`} aberto aoFechar={aoFechar}>
      <Tela4Estados
        leitura={leitura}
        esqueleto={
          <div className="space-y-3">
            <Esqueleto altura={14} largura="55%" />
            <Esqueleto altura={12} largura="80%" />
            <Esqueleto altura={12} largura="70%" />
          </div>
        }
      >
        {(tarefas) =>
          tarefas.length === 0 ? (
            <p className="text-sm text-fraco">
              Nenhuma tarefa registrada para esta atividade neste mês.
            </p>
          ) : (
            <ul className="space-y-3">
              {tarefas.map((t, i) => (
                <li
                  key={t.id ?? `tarefa-${i}`}
                  className="border-b border-borda-fraca pb-3 last:border-0 last:pb-0"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm text-forte">{t.nome}</p>
                      {t.equipamento ? (
                        <p className="mt-0.5 truncate text-xs text-fraco">{t.equipamento}</p>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {/* A frase da situação é do servidor; aqui só se escolhe a cor. */}
                      <Selo tom={t.feita ? 'ok' : 'semDados'}>{t.situacao}</Selo>
                      {t.parecer ? <Selo tom={t.parecer_tom ?? 'semDados'}>{t.parecer}</Selo> : null}
                    </div>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fraco">
                    {t.executada_em ? (
                      <span>
                        data <Num>{dataCurta(t.executada_em)}</Num>
                      </span>
                    ) : null}
                    {/* Zero é resposta legítima ("nada preenchido"); só o nulo some da linha. */}
                    {t.preenchimento === null ? null : (
                      <span>
                        ficha <Num>{porcento(t.preenchimento, 0)}</Num> respondida
                      </span>
                    )}
                    {t.os_id === null ? null : (
                      <button
                        type="button"
                        onClick={() => navigate(`/usinas/${usinaId}/manutencao/ordens/${t.os_id}`)}
                        className="text-ambar-texto transition hover:brightness-110"
                      >
                        ver a ordem de serviço ›
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )
        }
      </Tela4Estados>
    </Modal>
  )
}

/* ------------------------------------------------------------------ a grade */

/**
 * A matriz atividade × mês.
 *
 * Tabela escrita à mão, e não o `Tabela` de `components/base`: aqui a primeira coluna fica
 * CONGELADA enquanto os doze meses rolam na horizontal (num notebook de 13" as colunas não
 * cabem, e sem a âncora do nome o cliente perde de que atividade é a linha que está lendo).
 * A rolagem acontece DENTRO do cartão — a página nunca rola de lado.
 */
/**
 * As linhas por BLOCO, na ordem em que o servidor as mandou.
 *
 * O cronograma chegava com 94 linhas planas — "Medição do TTR", "Resistência das bobinas",
 * "Isolação CC", "Curva IV" —, que é exatamente a análise de equipamento que o dono disse
 * que o cliente corporativo não quer ver ("ele só quer saber se está sendo feito"). O X é
 * inerentemente uma matriz atividade × mês, então a linha não sai; o que muda é que ela
 * nasce RECOLHIDA sob o bloco a que pertence, com o total do bloco à mostra.
 */
function porGrupo(linhas: LinhaCronograma[]): { nome: string; linhas: LinhaCronograma[] }[] {
  const ordem: string[] = []
  const mapa = new Map<string, LinhaCronograma[]>()
  for (const l of linhas) {
    const nome = l.grupo || 'Outras atividades'
    if (!mapa.has(nome)) {
      mapa.set(nome, [])
      ordem.push(nome)
    }
    mapa.get(nome)!.push(l)
  }
  return ordem.map((nome) => ({ nome, linhas: mapa.get(nome)! }))
}

function Grade({
  dados,
  aoAbrirCelula,
}: {
  dados: CronogramaOut
  aoAbrirCelula: (celula: CelulaAberta) => void
}) {
  const fixa = 'sticky left-0 z-10 bg-painel'
  const grupos = porGrupo(dados.linhas)
  // Um bloco só não é agrupamento: abre inteiro, sem cabeçalho que não separa nada.
  const [abertos, setAbertos] = useState<Record<string, boolean>>(() =>
    grupos.length <= 1 ? Object.fromEntries(grupos.map((g) => [g.nome, true])) : {},
  )
  const alternar = (nome: string) =>
    setAbertos((atual) => ({ ...atual, [nome]: !atual[nome] }))
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[880px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-borda">
            <th
              className={`${fixa} px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-rotulo`}
            >
              Atividade
            </th>
            {/* A ordem das colunas é a do servidor: mês 1 é a âncora do contrato. */}
            {dados.meses.map((m) => (
              <th
                key={m}
                className="px-1 py-2 text-center text-xs font-medium uppercase tracking-wide text-rotulo"
              >
                {competenciaCurta(m)}
              </th>
            ))}
            <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wide text-rotulo">
              Ano
            </th>
          </tr>
        </thead>
        {grupos.map((grupo) => (
        <tbody key={grupo.nome}>
          {grupos.length > 1 ? (
            <tr className="border-b border-borda bg-superficie-alta/40">
              <td colSpan={dados.meses.length + 2} className="p-0">
                <button
                  type="button"
                  onClick={() => alternar(grupo.nome)}
                  aria-expanded={Boolean(abertos[grupo.nome])}
                  className="flex w-full items-center gap-2 px-4 py-2 text-left transition hover:bg-superficie-alta"
                >
                  <span aria-hidden className="text-fraco">
                    {abertos[grupo.nome] ? '⌄' : '›'}
                  </span>
                  <span className="text-sm font-medium text-forte">{grupo.nome}</span>
                  <span className="text-xs text-fraco">
                    <Num>{inteiro(grupo.linhas.reduce((t, l) => t + l.feitos, 0))}</Num> de{' '}
                    <Num>{inteiro(grupo.linhas.reduce((t, l) => t + l.previsto_ano, 0))}</Num> ·{' '}
                    <Num>{inteiro(grupo.linhas.length)}</Num>{' '}
                    {grupo.linhas.length === 1 ? 'atividade' : 'atividades'}
                  </span>
                </button>
              </td>
            </tr>
          ) : null}
          {(grupos.length > 1 && !abertos[grupo.nome] ? [] : grupo.linhas).map((linha: LinhaCronograma, i) => (
            <tr
              key={linha.plan_item_id ?? `linha-${i}`}
              className="border-b border-borda-fraca last:border-0"
            >
              <td className={`${fixa} max-w-[18rem] px-4 py-2`}>
                <span className="block truncate text-corpo" title={linha.nome}>
                  {linha.nome}
                </span>
                {linha.categoria || linha.periodicidade ? (
                  <span className="block truncate text-xs text-fraco">
                    {[linha.categoria, linha.periodicidade].filter(Boolean).join(' · ')}
                  </span>
                ) : null}
              </td>

              {linha.meses.map((c) => {
                // Só abre o que tem porta: sem item do plano não há como perguntar quais
                // tarefas estão atrás do X, e um clique morto é pior que nenhum.
                const planItemId = linha.plan_item_id
                const podeAbrir = planItemId !== null && (c.previsto > 0 || c.estado !== null)
                return (
                  <td key={c.mes} className="px-1 py-2 text-center">
                    {podeAbrir ? (
                      <button
                        type="button"
                        onClick={() =>
                          aoAbrirCelula({ planItemId, nome: linha.nome, mes: c.mes })
                        }
                        aria-label={`${linha.nome} em ${competencia(c.mes)}`}
                        className="rounded-campo p-1 transition hover:bg-superficie-alta"
                      >
                        <Marca celula={c} />
                      </button>
                    ) : (
                      <Marca celula={c} />
                    )}
                  </td>
                )
              })}

              <td className="px-4 py-2 text-right">
                <Num className="text-corpo">
                  {inteiro(linha.feitos)}/{inteiro(linha.previsto_ano)}
                </Num>
              </td>
            </tr>
          ))}
        </tbody>
        ))}
      </table>
    </div>
  )
}

/** A mancha da grade enquanto ela chega — nunca um spinner solto. */
function EsqueletoDaGrade() {
  return (
    <Cartao>
      <Esqueleto altura={28} largura="35%" />
      <div className="mt-5 space-y-3">
        {[0, 1, 2, 3, 4].map((i) => (
          <Esqueleto key={i} altura={16} />
        ))}
      </div>
    </Cartao>
  )
}

/* ------------------------------------------------------------------ a tela */

/** `?contrato=` da URL — o que não for id positivo vale como "não escolhido". */
function contratoDaBusca(valor: string | null): number | null {
  if (!valor) return null
  const n = Number(valor)
  return Number.isInteger(n) && n > 0 ? n : null
}

export default function Cronograma() {
  const { id } = useParams<{ id: string }>()
  const usinaId = Number(id)
  const [busca, setBusca] = useSearchParams()
  const contratoDaUrl = contratoDaBusca(busca.get('contrato'))

  const [celulaAberta, setCelulaAberta] = useState<CelulaAberta | null>(null)
  const [baixando, setBaixando] = useState(false)
  const [erroPdf, setErroPdf] = useState<string | null>(null)

  const usinaValida = Number.isInteger(usinaId) && usinaId > 0

  const contratos = useLeitura<ContratosOut>(chaveContratos(usinaId), { ativo: usinaValida })
  const cronograma = useLeitura<CronogramaOut>(chaveCronograma(usinaId, contratoDaUrl), {
    ativo: usinaValida,
  })

  if (!usinaValida) {
    return (
      <Pagina titulo="Cronograma">
        <Vazio
          titulo="Usina não encontrada"
          descricao="O endereço não aponta para uma usina válida. Escolha uma usina na barra do topo."
        />
      </Pagina>
    )
  }

  const lista: Contrato[] = contratos.dados?.contratos ?? []
  const dados = cronograma.dados
  // Sem `?contrato=` quem escolheu foi o servidor (o consolidado mais recente) — e o seletor
  // mostra a escolha dele, para o cliente saber de qual contrato é a grade que está lendo.
  const contratoEfetivo = contratoDaUrl ?? dados?.contrato_id ?? null

  const escolherContrato = (novo: number) => {
    setCelulaAberta(null)
    setErroPdf(null)
    setBusca({ contrato: String(novo) })
  }

  const baixarPdf = async () => {
    setErroPdf(null)
    setBaixando(true)
    try {
      // `abrirPdf` abre a aba no gesto do clique e só depois busca o arquivo — o bloqueador
      // de popup recusa aba aberta depois de um `await`.
      await abrirPdf(
        caminhoPdfCronograma(usinaId, contratoEfetivo),
        `Cronograma-${(dados?.usina ?? 'usina').replace(/\s+/g, '-')}.pdf`,
        { prazoMs: 180_000 },
      )
    } catch (erro) {
      setErroPdf(mensagemDeErro(erro))
    } finally {
      setBaixando(false)
    }
  }

  const seletor: ReactNode =
    lista.length > 1 ? (
      <Combobox
        opcoes={lista.map((c) => ({
          valor: String(c.id),
          rotulo: rotuloDoContrato(c),
          detalhe:
            c.versao_cronograma === null
              ? 'sem cronograma publicado'
              : `versão ${inteiro(c.versao_cronograma)} · ${dataCurta(c.inicio)} a ${dataCurta(c.fim)}`,
        }))}
        valor={contratoEfetivo === null ? null : String(contratoEfetivo)}
        onEscolher={(v) => escolherContrato(Number(v))}
        placeholder="Escolher contrato…"
        className="w-64"
      />
    ) : lista.length === 1 ? (
      // Um contrato só não é pergunta: vira rótulo.
      <span className="text-sm text-corpo">{rotuloDoContrato(lista[0])}</span>
    ) : null

  const subtitulo =
    [
      dados?.usina,
      dados?.contrato,
      dados?.versao === null || dados?.versao === undefined
        ? null
        : `versão ${inteiro(dados.versao)}`,
    ]
      .filter(Boolean)
      .join(' · ') || 'O que o contrato prevê mês a mês foi feito?'

  return (
    <Pagina
      titulo="Cronograma"
      subtitulo={subtitulo}
      acoes={
        <>
          {seletor}
          {/* Sem versão publicada não há PDF para pedir: botão que só sabe errar é ruído.
              Quem responde isso é o SERVIDOR (`pdf_disponivel`): a rota do PDF é a única
              que sabe se tem o que gerar — o JSON responde 200 com a frase e o PDF, 404 —,
              e a tela não pode deduzir o par sozinha. Sem o campo, vale `status`, que era
              a régua anterior. */}
          {(dados?.pdf_disponivel ?? Boolean(dados?.status)) ? (
            <Botao variante="secundario" onClick={() => void baixarPdf()} desabilitado={baixando}>
              {baixando ? 'Gerando PDF…' : 'PDF'}
            </Botao>
          ) : null}
        </>
      }
    >
      <div className="space-y-4">
        {erroPdf ? <Aviso tom="parado">{erroPdf}</Aviso> : null}

        {contratos.erro ? (
          <Aviso tom="semDados">
            Não deu para listar os contratos desta usina ({contratos.erro}) — a grade abaixo é a do
            contrato que o servidor escolheu.
          </Aviso>
        ) : null}

        {contratoDaUrl !== null && cronograma.erro ? (
          <Botao variante="secundario" onClick={() => setBusca({})}>
            Ver o contrato padrão
          </Botao>
        ) : null}

        <Tela4Estados leitura={cronograma} esqueleto={<EsqueletoDaGrade />}>
          {(d) =>
            // Sem versão consolidada NÃO se desenha grade: a frase é do servidor, e ela diz
            // "ainda não foi publicado" — nunca "nada foi feito".
            d.status === null || d.linhas.length === 0 ? (
              <Vazio
                titulo="Cronograma ainda não publicado"
                descricao={
                  d.aviso ?? 'A equipe ainda não publicou o cronograma consolidado deste contrato.'
                }
              />
            ) : (
              <>
                {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}
                <Cartao semPadding>
                  <div className="flex flex-wrap items-end justify-between gap-4 border-b border-borda px-5 py-4">
                    <Kpi
                      rotulo="Atividades cumpridas no ano do contrato"
                      valor={inteiro(d.feitos_ano)}
                      detalhe={
                        <>de {inteiro(d.previsto_ano)} previstas — executadas e dispensadas</>
                      }
                      tamanho="grande"
                    />
                    <div className="flex flex-col items-start gap-2 sm:items-end">
                      <AtualizadoAs
                        em={cronograma.atualizadoEm}
                        offlineDesde={cronograma.offlineDesde}
                      />
                      <Legenda />
                    </div>
                  </div>

                  <Grade dados={d} aoAbrirCelula={setCelulaAberta} />
                </Cartao>
              </>
            )
          }
        </Tela4Estados>
      </div>

      {celulaAberta ? (
        <TarefasDoMes
          usinaId={usinaId}
          celula={celulaAberta}
          aoFechar={() => setCelulaAberta(null)}
        />
      ) : null}
    </Pagina>
  )
}
