/**
 * Fichas do período — baixar TODOS os PDFs das tarefas, não um por clique.
 *
 * O pedido do dono é literal: *"eu fiz a inspeção de agosto de Porto Ferreira; de alguma
 * forma eu preciso conseguir baixar TODOS os PDFs das tarefas. Se eu fizer corretiva, quero
 * poder ver também. Preciso de filtros."* A OS 1016 daquele mês tem dezessete tarefas, e até
 * aqui o portal só sabia abrir uma de cada vez, na página da ordem.
 *
 * Quatro decisões que este bloco carrega, e que não devem ser "simplificadas" depois:
 *
 * **"Todos" é todos — e o cliente vê o tamanho ANTES de pedir.** Por isso o caminho tem três
 * atos, e não um botão: **inventariar** (quantas fichas o filtro pegou, quantas já têm PDF,
 * quanto pesa e em quantas partes o pacote sai), **preparar** (o meuPlano gera as que faltam,
 * fora do tempo de uma requisição) e **baixar**. Dezessete fichas frias, uma delas com
 * sessenta e uma fotos, passam de qualquer prazo de proxy — gerar dentro do clique devolveria
 * um erro genérico depois de dois minutos de espera.
 *
 * **Nada é somado aqui.** `total`, `prontas`, `bytes_estimados` e `partes` vêm do servidor,
 * que os lê do próprio acervo. Recontar as fichas das ordens na tela produziria uma segunda
 * verdade sobre quantos arquivos o ZIP tem — e o cliente não confere um pacote.
 *
 * **Mais de uma parte vira mais de um botão, numerado.** Um pacote grande sai em `parte 1 de
 * 2`, `parte 2 de 2`; oferecer só "baixar" com a primeira parte é como o cliente acabaria com
 * três fichas achando que levou dezessete.
 *
 * **Filtro que não pega nada explica o que escondeu.** O servidor manda `total_sem_filtro`
 * justamente para a tela poder dizer "o período tem 20 fichas, este filtro não pegou nenhuma"
 * em vez de "não há nada aqui", que se lê como mês sem manutenção.
 *
 * O download é disparado DENTRO do `onClick`: `baixarArquivo` monta o `<a download>` depois
 * do `fetch`, e navegador nenhum aceita um salvamento que não nasceu de um gesto.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  Aviso,
  Barra,
  Botao,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  Combobox,
  Kpi,
  Num,
  Selo,
  SeloClasse,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { SeletorCompetencias } from '@/components/SeletorPeriodo'
import { api, mensagemDeErro } from '@/lib/api'
import { baixarArquivo } from '@/lib/arquivo'
import { competencia, dataCurta, inteiro } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import { competenciaDe, hojeIso, passoCompetencia } from '@/lib/periodo'
import {
  caminhoDoPacote,
  caminhoDoPreparo,
  caminhoPreparar,
  chaveInventario,
  CLASSIFICACOES,
  SITUACOES,
  tamanhoDeArquivo,
  TODAS,
  nomeDoPacote,
  type FiltroDeFichas,
  type InventarioDeFichas,
  type OrdemDoPacote,
  type ParteDoPacote,
  type PreparoDeFichas,
} from '@/features/relatorios/api'

/** O BFF cobre no máximo 24 competências (`relatorio.MESES_MAX`), como no relatório. */
const MESES_OFERECIDOS = 24
/** Sem escolha, o recorte é o mês corrente: o caso do dono é "a inspeção de agosto". */
const MESES_PADRAO = 1
/** O inventário pergunta ao armazenamento o tamanho de cada PDF pronto: leva segundos. */
const PRAZO_DO_INVENTARIO_MS = 120_000
/** Um pacote passa de dezoito megabytes, e atravessa dois sistemas antes de chegar aqui. */
const PRAZO_DO_PACOTE_MS = 300_000
/** De quanto em quanto tempo se pergunta "quantas já ficaram prontas". */
const INTERVALO_DO_PREPARO_MS = 3_000
/** Digitar não é pedir: a busca só vira leitura quando a pessoa para de escrever. */
const ESPERA_DA_BUSCA_MS = 400

function filtroPadrao(): FiltroDeFichas {
  const ate = competenciaDe(hojeIso())
  let de = ate
  for (let i = 1; i < MESES_PADRAO; i += 1) de = passoCompetencia(de, -1)
  return { de, ate, classificacao: TODAS, situacao: TODAS, osId: null, busca: '' }
}

/** Há algum recorte além do período? É o que decide se cabe oferecer "limpar filtros". */
function temFiltro(f: FiltroDeFichas): boolean {
  return (
    f.classificacao !== TODAS || f.situacao !== TODAS || f.osId !== null || f.busca.trim() !== ''
  )
}

/**
 * As partes do pacote, sempre pelo menos uma.
 *
 * Um servidor que não calcule partes (ou que renomeie o campo) deixaria a tela SEM NENHUM
 * botão de download, sem nada quebrar e sem ninguém perceber — o pior desfecho possível para
 * a única porta de download de fichas do portal. Havendo ficha, há um pacote.
 */
function partesDo(dados: InventarioDeFichas): ParteDoPacote[] {
  const declaradas = Array.isArray(dados.partes) ? dados.partes : []
  if (declaradas.length > 0) return declaradas
  return [{ numero: 1, fichas: dados.total, bytes: dados.bytes_estimados }]
}

/* ------------------------------------------------------------------ pedaços */

function Campo({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-rotulo">{rotulo}</span>
      {children}
    </div>
  )
}

/** Uma ordem do período, com as fichas que ela gerou atrás de um clique. */
function OrdemDaLista({ o }: { o: OrdemDoPacote }) {
  const fichas = Array.isArray(o.fichas) ? o.fichas : []
  const prontas = fichas.filter((f) => f.pronta).length
  return (
    <div className="rounded-card border border-borda-fraca p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="block truncate text-sm font-medium text-forte">{o.objetivo}</span>
          <span className="mt-0.5 block text-xs text-fraco">
            OS <Num>{o.os_id}</Num>
            {o.data ? (
              <>
                {' · '}
                <Num>{dataCurta(o.data)}</Num>
              </>
            ) : null}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SeloClasse classificacao={o.classificacao} tom={o.classificacao_tom} />
          <Selo tom={o.tom}>{o.situacao}</Selo>
        </div>
      </div>

      <details className="group mt-3">
        <summary className="cursor-pointer list-none text-sm text-fraco transition hover:text-corpo">
          <span aria-hidden className="mr-1 inline-block group-open:hidden">
            ›
          </span>
          <span aria-hidden className="mr-1 hidden group-open:inline-block">
            ⌄
          </span>
          <Num>{inteiro(fichas.length)}</Num> ficha(s) nesta ordem ·{' '}
          <Num>{inteiro(prontas)}</Num> pronta(s)
        </summary>
        <ul className="mt-2">
          {fichas.map((f) => (
            <li
              key={f.task_id}
              className="flex flex-wrap items-center gap-2 border-b border-borda-fraca py-2 text-sm last:border-0"
            >
              <span className={f.pronta ? 'text-tom-ok' : 'text-fraco'} aria-hidden>
                {f.pronta ? '✓' : '○'}
              </span>
              <span className="min-w-0 flex-1 truncate text-corpo">
                {f.nome}
                {f.equipamento ? <span className="text-fraco"> · {f.equipamento}</span> : null}
              </span>
              {f.situacao ? <span className="text-xs text-fraco">{f.situacao}</span> : null}
              {/* Tamanho só de quem já existe. Nulo aqui é "ainda vai ser gerada", e um
                  "0 B" no lugar diria que o PDF saiu vazio. */}
              <Num className="text-xs text-fraco">
                {f.pronta ? tamanhoDeArquivo(f.bytes) : 'a preparar'}
              </Num>
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

/* ------------------------------------------------------------------ bloco */

export function PacoteDeFichas({ usinaId }: { usinaId: number }) {
  const [filtros, setFiltros] = useState<FiltroDeFichas>(filtroPadrao)
  const [digitado, setDigitado] = useState('')

  // A busca é a única escolha que se digita, e cada tecla seria uma leitura do inventário —
  // que mede o tamanho de cada PDF no armazenamento. Espera a pessoa parar.
  useEffect(() => {
    const t = setTimeout(() => {
      const limpo = digitado.trim()
      setFiltros((f) => (f.busca === limpo ? f : { ...f, busca: limpo }))
    }, ESPERA_DA_BUSCA_MS)
    return () => clearTimeout(t)
  }, [digitado])

  const chave = chaveInventario(usinaId, filtros)
  const inventario = useLeitura<InventarioDeFichas>(chave, { prazoMs: PRAZO_DO_INVENTARIO_MS })

  // As ordens que alimentam o seletor saem do MESMO inventário, sem o recorte de ordem: com
  // ele, escolher uma OS deixaria a lista com um item só e não haveria como trocar para
  // outra. Quando nenhuma está escolhida as duas chaves são idênticas, e o TanStack Query
  // resolve as duas leituras com uma ida à rede só.
  const paraOSeletor = useLeitura<InventarioDeFichas>(
    chaveInventario(usinaId, { ...filtros, osId: null }),
    { prazoMs: PRAZO_DO_INVENTARIO_MS },
  )

  /* --------------------------------------------------------------- preparo */

  // O preparo pertence a UM recorte. Trocado o filtro, o número de acompanhamento anterior
  // deixa de valer — mantê-lo mostraria "15 de 17" sobre um conjunto que já não é aquele.
  const [preparo, setPreparo] = useState<{ chave: string; dados: PreparoDeFichas | null }>(() => ({
    chave,
    dados: null,
  }))
  if (preparo.chave !== chave) setPreparo({ chave, dados: null })
  const iniciado = preparo.chave === chave ? preparo.dados : null

  const [preparando, setPreparando] = useState(false)
  const [erroPreparo, setErroPreparo] = useState<string | null>(null)
  const [baixando, setBaixando] = useState<number | null>(null)
  const [erroBaixa, setErroBaixa] = useState<string | null>(null)

  const preparoId = iniciado === null ? null : iniciado.preparo_id
  const andamento = useQuery({
    queryKey: ['preparo-fichas', usinaId, preparoId],
    enabled: preparoId !== null,
    // Enquanto não terminou, pergunta de novo. Terminado, para: um preparo pronto não muda
    // mais, e continuar batendo seria ruído no servidor pelo tempo que a aba ficar aberta.
    refetchInterval: (consulta) =>
      consulta.state.data?.concluido === true ? false : INTERVALO_DO_PREPARO_MS,
    queryFn: async () => {
      if (preparoId === null) throw new Error('Nenhum preparo em andamento.')
      const { data } = await api.get<PreparoDeFichas>(caminhoDoPreparo(preparoId, usinaId))
      return data
    },
  })
  const estado: PreparoDeFichas | null = andamento.data ?? iniciado

  // Terminado o preparo, o inventário na tela ainda diz "10 de 17 prontas". Uma releitura, e
  // só uma por preparo: o pedido é caro, e repeti-lo a cada render seria um laço silencioso.
  const recarregar = useRef(inventario.recarregar)
  recarregar.current = inventario.recarregar
  const jaReleu = useRef<string | null>(null)
  useEffect(() => {
    if (estado === null || !estado.concluido) return
    if (jaReleu.current === estado.preparo_id) return
    jaReleu.current = estado.preparo_id
    recarregar.current()
  }, [estado])

  function preparar() {
    setErroPreparo(null)
    setPreparando(true)
    api
      .post<PreparoDeFichas>(caminhoPreparar(usinaId, filtros))
      .then(({ data }) => setPreparo({ chave, dados: data }))
      .catch((falha) => setErroPreparo(mensagemDeErro(falha)))
      .finally(() => setPreparando(false))
  }

  function baixar(usina: string, parte: number, partes: number) {
    setErroBaixa(null)
    setBaixando(parte)
    // Chamado direto do `onClick`: é o gesto do usuário que autoriza o salvamento.
    baixarArquivo(
      caminhoDoPacote(usinaId, filtros, parte),
      nomeDoPacote(usina, filtros, parte, partes),
      { prazoMs: PRAZO_DO_PACOTE_MS },
    )
      .catch((falha) => setErroBaixa(mensagemDeErro(falha)))
      .finally(() => setBaixando(null))
  }

  /* --------------------------------------------------------------- filtros */

  const opcoesDeOrdem = useMemo(() => {
    const lidas = paraOSeletor.dados === null ? null : paraOSeletor.dados.ordens
    const ordens = Array.isArray(lidas) ? lidas : []
    return [
      { valor: TODAS, rotulo: 'Todas as ordens do período' },
      ...ordens.map((o) => ({
        valor: String(o.os_id),
        rotulo: `OS ${o.os_id} · ${o.objetivo}`,
        detalhe: o.classificacao === null ? undefined : o.classificacao,
      })),
    ]
  }, [paraOSeletor.dados])

  function limpar() {
    setDigitado('')
    setFiltros((f) => ({ ...f, classificacao: TODAS, situacao: TODAS, osId: null, busca: '' }))
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-forte">Fichas do período</h2>
        <p className="text-sm text-fraco">
          A ficha em PDF de cada tarefa executada, num pacote só. Escolha o recorte, mande
          preparar e baixe.
        </p>
      </div>

      <Cartao>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <SeletorCompetencias
            de={filtros.de}
            ate={filtros.ate}
            onDe={(de) => setFiltros((f) => ({ ...f, de }))}
            onAte={(ate) => setFiltros((f) => ({ ...f, ate }))}
            meses={MESES_OFERECIDOS}
          />
          <Campo rotulo="classificação">
            <Combobox
              opcoes={CLASSIFICACOES}
              valor={filtros.classificacao}
              onEscolher={(v) => setFiltros((f) => ({ ...f, classificacao: v }))}
              className="w-56"
            />
          </Campo>
          <Campo rotulo="situação">
            <Combobox
              opcoes={SITUACOES}
              valor={filtros.situacao}
              onEscolher={(v) => setFiltros((f) => ({ ...f, situacao: v }))}
              className="w-56"
            />
          </Campo>
          <Campo rotulo="ordem">
            <Combobox
              opcoes={opcoesDeOrdem}
              valor={filtros.osId === null ? TODAS : String(filtros.osId)}
              onEscolher={(v) =>
                setFiltros((f) => ({ ...f, osId: v === TODAS ? null : Number(v) }))
              }
              className="w-72"
              larguraMenu="w-96"
            />
          </Campo>
          <Campo rotulo="buscar">
            <input
              className="campo w-64"
              value={digitado}
              onChange={(e) => setDigitado(e.target.value)}
              placeholder="Tarefa, equipamento ou ordem…"
              aria-label="Buscar fichas por tarefa, equipamento ou ordem"
            />
          </Campo>
        </div>
      </Cartao>

      {erroPreparo === null ? null : <Aviso tom="parado">{erroPreparo}</Aviso>}
      {erroBaixa === null ? null : <Aviso tom="parado">{erroBaixa}</Aviso>}

      <Tela4Estados leitura={inventario} esqueleto={<CarregandoCartao linhas={4} />}>
        {(dados) =>
          dados.total === 0 ? (
            <Vazio
              titulo={
                temFiltro(filtros) ? 'Nenhuma ficha neste filtro' : 'Nenhuma ficha neste período'
              }
              // A frase é do SERVIDOR — ele sabe distinguir "o filtro escondeu" de "o
              // período não teve manutenção", e as duas leituras são opostas para o cliente.
              descricao={
                dados.aviso === null
                  ? `Nada foi registrado entre ${competencia(dados.de)} e ${competencia(dados.ate)}.`
                  : dados.aviso
              }
              acao={
                temFiltro(filtros) ? (
                  <Botao variante="secundario" onClick={limpar}>
                    Limpar os filtros
                    {dados.total_sem_filtro === null ? null : (
                      <>
                        {' '}
                        (<Num>{inteiro(dados.total_sem_filtro)}</Num> no período)
                      </>
                    )}
                  </Botao>
                ) : undefined
              }
            />
          ) : (
            <>
              <Cartao>
                <CabecalhoCard
                  rotulo={`${dados.usina} · ${competencia(dados.de)} a ${competencia(dados.ate)}`}
                  direita={
                    temFiltro(filtros) && dados.total_sem_filtro !== null ? (
                      <span>
                        <Num>{inteiro(dados.total_sem_filtro)}</Num> no período, sem filtro
                      </span>
                    ) : undefined
                  }
                />
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Kpi rotulo="Fichas" valor={inteiro(dados.total)} tamanho="grande" />
                  <Kpi
                    rotulo="Prontas"
                    valor={inteiro(dados.prontas)}
                    tom={dados.prontas >= dados.total ? 'ok' : 'alerta'}
                    detalhe={
                      dados.prontas >= dados.total
                        ? 'todas com PDF gerado'
                        : 'as demais são geradas no preparo'
                    }
                  />
                  <Kpi
                    rotulo="Tamanho"
                    valor={tamanhoDeArquivo(dados.bytes_estimados)}
                    detalhe={
                      dados.prontas >= dados.total
                        ? 'do pacote inteiro'
                        : 'só do que já está pronto'
                    }
                  />
                  <Kpi
                    rotulo="Arquivos"
                    valor={inteiro(partesDo(dados).length)}
                    detalhe={
                      partesDo(dados).length > 1 ? 'o pacote sai em partes' : 'um pacote só'
                    }
                  />
                </div>

                <div className="mt-5">
                  <Acoes
                    dados={dados}
                    estado={estado}
                    preparando={preparando}
                    baixando={baixando}
                    aoPreparar={preparar}
                    aoBaixar={baixar}
                  />
                </div>
              </Cartao>

              <Cartao>
                <CabecalhoCard rotulo="Ordens do período" />
                <div className="space-y-3">
                  {(Array.isArray(dados.ordens) ? dados.ordens : []).map((o) => (
                    <OrdemDaLista key={o.os_id} o={o} />
                  ))}
                </div>
              </Cartao>
            </>
          )
        }
      </Tela4Estados>
    </section>
  )
}

/* ------------------------------------------------------------------ ações */

/**
 * O que a tela oferece agora: preparar, esperar ou baixar.
 *
 * O download só aparece quando TODAS as fichas do recorte têm PDF — pelo inventário ou porque
 * o preparo terminou. Oferecê-lo antes entregaria um pacote com menos fichas do que a tela
 * acabou de prometer, que é exatamente o defeito que este bloco existe para não ter.
 */
function Acoes({
  dados,
  estado,
  preparando,
  baixando,
  aoPreparar,
  aoBaixar,
}: {
  dados: InventarioDeFichas
  estado: PreparoDeFichas | null
  preparando: boolean
  baixando: number | null
  aoPreparar: () => void
  aoBaixar: (usina: string, parte: number, partes: number) => void
}) {
  const faltam = dados.total - dados.prontas
  const terminou = estado !== null && estado.concluido && estado.estado !== 'falhou'
  const pronto = dados.prontas >= dados.total || terminou

  if (!pronto) {
    // Em andamento: o "15 de 17" que o dono pediu para poder acompanhar.
    if (estado !== null && estado.estado !== 'falhou') {
      const pct = estado.total > 0 ? (estado.prontas / estado.total) * 100 : null
      return (
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm text-corpo">
              Preparando as fichas — <Num>{inteiro(estado.prontas)}</Num> de{' '}
              <Num>{inteiro(estado.total)}</Num>
            </span>
            {estado.ja_em_andamento ? (
              <span className="text-xs text-fraco">um preparo igual já estava correndo</span>
            ) : null}
          </div>
          <Barra pct={pct} />
          {estado.conferido_no_armazenamento ? (
            // O andamento veio da CONFERÊNCIA no armazenamento: o preparo foi aberto em
            // outro servidor do meuPlano (que roda com mais de uma réplica) ou o servidor
            // reiniciou entre um pedido e outro. O número é real e sobe sozinho enquanto
            // alguém gera — mas se quem trabalhava morreu, ele para. Por isso a saída fica
            // aqui, à mão: sem ela, a barra giraria para sempre.
            <div className="space-y-2">
              <Aviso>{estado.aviso ?? 'Andamento conferido no armazenamento.'}</Aviso>
              <Botao onClick={aoPreparar} desabilitado={preparando}>
                {preparando ? 'Mandando preparar…' : 'Preparar de novo'}
              </Botao>
            </div>
          ) : (
            <p className="text-xs text-fraco">
              Pode fechar esta aba: o preparo corre no servidor e o que já foi gerado é
              reaproveitado.
            </p>
          )}
        </div>
      )
    }

    return (
      <div className="space-y-2">
        {estado !== null && estado.estado === 'falhou' && estado.erro !== null ? (
          <Aviso tom="parado">{estado.erro}</Aviso>
        ) : null}
        <Botao onClick={aoPreparar} desabilitado={preparando}>
          {preparando
            ? 'Mandando preparar…'
            : `Preparar ${inteiro(faltam)} ficha(s) que faltam`}
        </Botao>
        <p className="text-xs text-fraco">
          As <Num>{inteiro(dados.prontas)}</Num> já prontas são reaproveitadas — o preparo só
          gera o que falta.
        </p>
      </div>
    )
  }

  const partes = partesDo(dados)
  // Ficha que nem a regeração salvou. O pacote sai sem ela — e a tela DIZ isso, senão o
  // cliente volta a baixar dezessete e conferir três sem nunca ter sido avisado.
  const falhas = estado !== null && Array.isArray(estado.erros) ? estado.erros.length : 0

  return (
    <div className="space-y-2">
      {falhas > 0 ? (
        <Aviso>
          {estado !== null && estado.aviso !== null
            ? estado.aviso
            : `${inteiro(falhas)} ficha(s) não puderam ser geradas — o pacote sai sem elas.`}
        </Aviso>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {partes.map((p) => (
          <Botao
            key={p.numero}
            desabilitado={baixando !== null}
            onClick={() => aoBaixar(dados.usina, p.numero, partes.length)}
          >
            {baixando === p.numero
              ? 'Preparando o arquivo…'
              : partes.length > 1
                ? `Parte ${p.numero} de ${partes.length} · ${inteiro(p.fichas)} ficha(s) · ${tamanhoDeArquivo(p.bytes)}`
                : `Baixar ${inteiro(p.fichas)} ficha(s) · ${tamanhoDeArquivo(p.bytes)}`}
          </Botao>
        ))}
      </div>

      {partes.length > 1 ? (
        <p className="text-xs text-fraco">
          O pacote não cabe num arquivo só. Baixe as <Num>{inteiro(partes.length)}</Num> partes:
          juntas elas trazem as <Num>{inteiro(dados.total)}</Num> fichas do recorte.
        </p>
      ) : null}
    </div>
  )
}
