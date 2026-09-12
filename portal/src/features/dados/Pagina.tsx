/**
 * Baixar dados — a MESMA tela de Downloads do meuWatt, no vocabulário do portal.
 *
 * A versão anterior desta página não cortou o CONTRATO — `api.ts` e o BFF sempre carregaram as
 * quatro variáveis de inversor, os dois agrupamentos e `series[]`. O que ela cortou foi a
 * VISIBILIDADE: abria com uma lista de cinco pacotes e escondia os quatro blocos atrás de uma
 * gaveta chamada "Escolher coluna por coluna". Para quem quer baixar POR SKID — que é o pedido
 * literal do dono — a capacidade estava tecnicamente presente e praticamente ausente: era
 * preciso saber que a gaveta existia, abri-la, trocar o agrupamento e marcar inversor por
 * inversor numa lista plana, porque não havia gesto nenhum para "o skid 2 inteiro".
 *
 * Agora os quatro blocos estão na tela, como no meuWatt, e o pacote virou o que ele sempre
 * deveria ter sido: um **preenchedor**. "Começar de…" preenche os cartões à vista e volta ao
 * lugar — atalho, não modo. Com isso morreram juntos a gaveta e o estado pseudo-
 * "personalizado", que só existia para administrar a mentira de continuar dizendo "Geração da
 * usina" quando já não era isso: a edição agora está DESENHADA, e a tela não precisa de um
 * rótulo para confessá-la.
 *
 * **O que muda em relação ao meuWatt é o vocabulário visual, e só.** Lá a escolha é uma
 * fileira de chips e de caixinhas; aqui chip é proibido (a regra vem do meuPlano e vale para 2
 * e para 200 opções): tudo é `Combobox`, `ComboboxMulti`, `ComboboxMultiAgrupado` ou
 * `Segmentado`. Nenhuma linha foi podada — as 14 variáveis, os 5 passos, os 2 agrupamentos de
 * cada bloco que tem agrupamento e os dois horários atravessaram inteiros.
 *
 * **Esta tela não guarda vocabulário nenhum.** As 14 linhas, os motivos de cada ausência, os
 * agrupamentos e as contas moram em `pacotes.ts`, que se prova sem montar tela; o controle
 * agrupado por skid mora em `components/base.tsx`, com o resto do vocabulário. Aqui fica só a
 * montagem — que é o que uma tela deve ser.
 *
 * **O que a usina não tem NÃO SOME.** Nem a linha (a `Opcao` do design system, por construção,
 * não deixa desabilitar sem escrever o porquê — o `tsc` pega isso, e não a revisão de diff),
 * nem o cartão: um bloco ausente vira um cartão com a contagem zerada e a frase no lugar da
 * escolha. Cartão que some é informação perdida; cartão presente e explicado é um cliente que
 * sabe o que teria de instalar para ter aquilo. `umidade` é o caso extremo e por isso está
 * aqui: nenhuma estação a envia, e mesmo assim ela aparece — desabilitada, com o motivo.
 *
 * **Os três limites do servidor têm três naturezas, e três tratamentos:** teto de dias IMPEDE
 * antes da viagem, com a conta feita e a saída nomeada; retenção é ausência de dado e por isso
 * mora colada ao PERÍODO, na linha permanente logo abaixo dele; orçamento de células é
 * estimativa nossa e NUNCA veta — no limiar o benefício da dúvida é do cliente.
 *
 * **O auto-ajuste do passo ANUNCIA que ajustou.** Escolher "este mês" com o detalhe em "cada
 * leitura" (que aceita 7 dias) engrossa o passo sozinho — e mudança calada é a que se descobre
 * depois, dentro do arquivo.
 *
 * **A espera é governada por um fato, não por uma escolha de estilo:** a rota do meuWatt é
 * síncrona, o cabeçalho só chega com o XLSX inteiro montado (35,6 s medidos no pior pedido que
 * ele aceita) e não existe job nem endpoint de andamento. Daí a barra INDETERMINADA (inventar
 * "43 %" seria ficção), o tempo DECORRIDO à mostra (fato, não previsão), o `Modal` que segura
 * a navegação de trás — porque o gesto provável não é fechar a aba, é clicar no menu ali à
 * esquerda — e o corte declarado aos 180 s. Cancelar é decisão legítima e CALA; o corte é
 * decisão nossa e FALA.
 *
 * **O sucesso deixa rastro, e o rastro morre ao trocar de usina.** É o `fix c23b330` do
 * meuWatt: a confirmação da usina anterior sobrevivendo à troca afirma que existe um arquivo
 * desta que não existe.
 *
 * **A chave de série nunca aparece.** `slot:170` é transporte; o cliente lê "Inv 13" com o
 * número de série ao lado, que é o que ele tem na mão para conferir.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'

import {
  Aviso,
  Botao,
  CarregandoCartao,
  Cartao,
  Combobox,
  ComboboxMulti,
  ComboboxMultiAgrupado,
  Erro,
  Esqueleto,
  Modal,
  Num,
  opcao,
  Pagina,
  PassoPeriodo,
  Segmentado,
  Tela4Estados,
  Vazio,
  type GrupoDeOpcoes,
  type Opcao,
} from '@/components/base'
import { baixarBlob } from '@/lib/arquivo'
import { dataCurta, inteiro } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import {
  competenciaDe,
  daData,
  hojeIso,
  paraIso,
  passo as passoNoTempo,
  passaDeHoje,
  rotuloDoPeriodo,
  type Recorte,
} from '@/lib/periodo'
import {
  baixarDados,
  Cancelado,
  chaveDasOpcoes,
  ErroDaExportacao,
  PRAZO_DO_ARQUIVO_MS,
  type OpcoesDeDados,
  type Passo,
  type Selecao,
  type VarEstacao,
  type VarInversor,
  type VarSistema,
} from '@/features/dados/api'
import { gravarForma, lerForma, type Descartado } from '@/features/dados/forma'
import {
  AGRUPAMENTO_DA_FRONTEIRA,
  AGRUPAMENTO_DO_INVERSOR,
  AGRUPAMENTO_DO_SISTEMA,
  ajustarPasso,
  avisoDeOrcamento,
  diasOferecidos,
  estimativa,
  impedimento,
  janelaDo,
  linhaDeRetencao,
  montarPacote,
  motivoDaFronteira,
  motivoDeRetencao,
  motivoDoPacote,
  opcoesDaEstacao,
  opcoesDaFronteira,
  opcoesDePasso,
  opcoesDoInversor,
  opcoesDoSistema,
  PACOTES,
  passoSugerido,
  rodapeDaFronteira,
  soMedidor,
  traduzirMotivo,
  vazia,
  AVISO_DA_SOMA_POR_SKID,
  type IdDePacote,
  type Recusa,
} from '@/features/dados/pacotes'

/* ================================================================== período */

/** O quarto recorte não existe em `lib/periodo`: é o intervalo de/até desta tela. */
type RecorteDaTela = Recorte | 'livre'

/**
 * "Escolher datas", e não "Personalizado".
 *
 * O nome importa: "personalizado" era como a versão anterior chamava o estado em que a seleção
 * deixava de ter nome, e reaproveitá-lo aqui devolveria a mesma confusão com outra roupa — o
 * cliente leria "personalizado" e procuraria o que tinha personalizado.
 */
const RECORTES: { valor: RecorteDaTela; rotulo: string }[] = [
  { valor: 'dia', rotulo: 'Dia' },
  { valor: 'mes', rotulo: 'Mês' },
  { valor: 'ano', rotulo: 'Ano' },
  { valor: 'livre', rotulo: 'Escolher datas' },
]

/**
 * O período em `YYYY-MM-DD`, com o fim preso em hoje.
 *
 * Não há leitura do que ainda não aconteceu: pedir até 31 de dezembro em setembro devolveria
 * um arquivo com quatro meses de linhas vazias, que se lê como usina parada.
 */
function periodoDe(
  recorte: RecorteDaTela,
  referencia: string,
  de: string,
  ate: string,
  hoje: string,
): { inicio: string; fim: string } {
  if (recorte === 'livre') return { inicio: de, fim: ate > hoje ? hoje : ate }
  const d = daData(referencia)
  if (recorte === 'dia') {
    const dia = referencia > hoje ? hoje : referencia
    return { inicio: dia, fim: dia }
  }
  const inicio =
    recorte === 'mes'
      ? paraIso(new Date(d.getFullYear(), d.getMonth(), 1))
      : paraIso(new Date(d.getFullYear(), 0, 1))
  const ultimo =
    recorte === 'mes'
      ? paraIso(new Date(d.getFullYear(), d.getMonth() + 1, 0))
      : paraIso(new Date(d.getFullYear(), 11, 31))
  return { inicio, fim: ultimo > hoje ? hoje : ultimo }
}

/**
 * Os atalhos de período numa lista só — os três do meuWatt mais os 24 meses fechados.
 *
 * O `Combobox` é a única peça do vocabulário do portal que segura 24 opções sem virar uma
 * parede de chips, e ele absorve as duas coisas que no meuWatt são controles separados (três
 * botões e um `<select>`). O motivo da retenção viaja colado no mês, enquanto se escolhe.
 */
function atalhosDePeriodo(
  hoje: string,
  retencao: OpcoesDeDados['retencao'],
  apenasMedidor: boolean,
): Opcao[] {
  const d = daData(hoje)
  const lista: Opcao[] = [
    { valor: 'atalho:ontem', rotulo: 'Ontem' },
    { valor: 'atalho:7d', rotulo: 'Últimos 7 dias' },
    { valor: 'atalho:mes', rotulo: 'Este mês', detalhe: 'do dia 1 até hoje' },
  ]
  for (let i = 1; i <= 24; i += 1) {
    const iso = paraIso(new Date(d.getFullYear(), d.getMonth() - i, 1))
    const rotulo = rotuloDoPeriodo(iso, 'mes')
    lista.push({
      valor: `mes:${competenciaDe(iso)}`,
      rotulo: `${rotulo.charAt(0).toUpperCase()}${rotulo.slice(1)}`,
      detalhe: motivoDeRetencao(iso, retencao, apenasMedidor) ?? 'mês fechado',
    })
  }
  return lista
}

/* ================================================================== horário */

/**
 * A grade de cinco minutos — a mesma do meuWatt (`<TimePicker step={300}>`).
 *
 * São 288 posições no dia (24 × 60 ÷ 5). A versão anterior desta tela usava quinze minutos, o
 * que é uma redução silenciosa: quem quer a janela das 07:35 às 17:20 não conseguia pedi-la.
 *
 * `23:59` é a 289ª e existe à parte, com o motivo escrito: o horário final é INCLUSIVO DO
 * MINUTO, então parar em `23:55` deixaria os últimos quatro minutos do dia fora do arquivo — e
 * "até o fim do dia" é justamente o padrão com que a tela abre.
 */
const GRADE_DE_5_MIN: Opcao[] = Array.from({ length: 288 }, (_, i): Opcao => {
  const h = String(Math.floor(i / 12)).padStart(2, '0')
  const m = String((i % 12) * 5).padStart(2, '0')
  return { valor: `${h}:${m}`, rotulo: `${h}:${m}` }
})

const HORARIOS: Opcao[] = [
  ...GRADE_DE_5_MIN,
  { valor: '23:59', rotulo: '23:59', detalhe: 'até o fim do dia' },
]

const HORA_INICIO_PADRAO = '00:00'
const HORA_FIM_PADRAO = '23:59'

/* ================================================================== pedaços */

function Rotulo({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-xs uppercase tracking-wide text-rotulo">{children}</div>
}

function Campo({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="mb-3 last:mb-0">
      <Rotulo>{rotulo}</Rotulo>
      {children}
    </div>
  )
}

function EtapaDaTela({
  numero,
  titulo,
  children,
}: {
  numero: string
  titulo: string
  children: ReactNode
}) {
  return (
    <Cartao>
      <div className="mb-3 flex items-baseline gap-2">
        <span className="text-xs text-fraco">{numero}</span>
        <h2 className="text-sm font-medium text-forte">{titulo}</h2>
      </div>
      {children}
    </Cartao>
  )
}

/**
 * O agrupamento: `Segmentado` com o rótulo dizendo no que a coluna vira, e o detalhe da opção
 * escolhida logo abaixo.
 *
 * O `Segmentado` não mostra `detalhe`, e a régua escreve um para cada opção ("cada coluna é a
 * soma dos inversores marcados daquele skid"). Deixá-lo de fora perderia a explicação; jogá-lo
 * num `title` esconderia-a de quem não tem mouse. Ele fica na tela, do jeito que se lê.
 */
function Agrupamento({
  opcoes,
  valor,
  onEscolher,
}: {
  opcoes: Opcao[]
  valor: string
  onEscolher: (v: string) => void
}) {
  const escolhida = opcoes.find((o) => o.valor === valor)
  return (
    <>
      <Segmentado
        opcoes={opcoes.map((o) => ({ valor: o.valor, rotulo: o.rotulo }))}
        valor={valor}
        onEscolher={onEscolher}
      />
      {escolhida?.detalhe ? (
        <p className="mt-1.5 text-xs text-fraco">{escolhida.detalhe}</p>
      ) : null}
    </>
  )
}

/**
 * A barra da espera — sem porcentagem, de propósito.
 *
 * O servidor monta o arquivo inteiro antes de responder o primeiro byte: não existe progresso
 * para ler. Uma barra que anda sozinha diria ao cliente que sabemos quanto falta.
 */
function BarraIndeterminada() {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-barra bg-afundado">
      <div className="h-full w-1/3 animate-pulse bg-tom-ok" />
    </div>
  )
}

/** `0:38` — o tempo que já se passou. É fato, não previsão. */
function decorridoEmTexto(segundos: number): string {
  const m = Math.floor(segundos / 60)
  const s = segundos % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** `312 KB` — o tamanho do que desceu, para o cliente reconhecer o arquivo na pasta dele. */
function tamanhoEmTexto(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${inteiro(Math.round(bytes / (1024 * 1024)))} MB`
  return `${inteiro(Math.round(bytes / 1024))} KB`
}

/**
 * O cartão de um bloco — e ele existe MESMO quando a usina não tem o bloco.
 *
 * Um cartão que some leva embora a única informação que interessa a quem está avaliando o que
 * contratar. O que a ausência muda é o miolo: no lugar da escolha entra a frase, e o "Entra no
 * arquivo" desaparece porque não há o que entrar.
 */
function CartaoDeBloco({
  titulo,
  contagem,
  motivo,
  ligado,
  aoLigar,
  children,
}: {
  titulo: string
  contagem: string
  motivo: string | null
  ligado: boolean
  aoLigar: (v: boolean) => void
  children: ReactNode
}) {
  return (
    <Cartao>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-medium text-forte">{titulo}</h2>
          <p className="mt-0.5 text-xs text-fraco">{motivo ? `Não entra: ${motivo}.` : contagem}</p>
        </div>
        {motivo ? null : (
          <Segmentado
            opcoes={[
              { valor: 'nao', rotulo: 'Não entra' },
              { valor: 'sim', rotulo: 'Entra no arquivo' },
            ]}
            valor={ligado ? 'sim' : 'nao'}
            onEscolher={(v) => aoLigar(v === 'sim')}
          />
        )}
      </div>
      {motivo ? null : children}
    </Cartao>
  )
}

/** As chaves que a lista permite marcar — o que "todas" quer dizer nesta usina, neste passo. */
function escolhiveis(opcoes: Opcao[]): string[] {
  return opcoes.filter((o) => o.desabilitada !== true).map((o) => o.valor)
}

/* ================================================================== conteúdo */

function Conteudo({ usinaId, opcoes }: { usinaId: number; opcoes: OpcoesDeDados }) {
  const hoje = hojeIso()
  const guardada = useMemo(() => lerForma(usinaId, opcoes), [usinaId, opcoes])

  /** O primeiro atalho que esta usina consegue entregar — a tela nunca abre sem nada marcado. */
  const primeiroPacote = useMemo<IdDePacote>(() => {
    const livre = PACOTES.find((p) => motivoDoPacote(p.id, opcoes) === null)
    return livre ? livre.id : 'geracao'
  }, [opcoes])

  const [selecao, setSelecao] = useState<Selecao>(
    guardada.forma ? guardada.forma.selecao : montarPacote(primeiroPacote, opcoes),
  )
  const [descartados, setDescartados] = useState<Descartado[]>(guardada.descartados)
  const [preenchidoDe, setPreenchidoDe] = useState<string | null>(null)

  const [recorte, setRecorte] = useState<RecorteDaTela>('mes')
  const [referencia, setReferencia] = useState<string>(hoje)
  const [de, setDe] = useState<string>(
    paraIso(new Date(daData(hoje).getFullYear(), daData(hoje).getMonth(), 1)),
  )
  const [ate, setAte] = useState<string>(hoje)
  const [horaInicio, setHoraInicio] = useState<string>(
    guardada.forma ? guardada.forma.horaInicio : HORA_INICIO_PADRAO,
  )
  const [horaFim, setHoraFim] = useState<string>(
    guardada.forma ? guardada.forma.horaFim : HORA_FIM_PADRAO,
  )

  const { inicio, fim } = periodoDe(recorte, referencia, de, ate, hoje)
  const [passo, setPasso] = useState<Passo>(
    guardada.forma
      ? guardada.forma.passo
      : passoSugerido(
          'mes',
          janelaDo(inicio, fim, HORA_INICIO_PADRAO, HORA_FIM_PADRAO, '1d', false).dias,
          opcoes.limites,
        ).passo,
  )
  const [avisoDoPasso, setAvisoDoPasso] = useState<string | null>(null)

  const apenasMedidor = soMedidor(selecao)
  const janela = janelaDo(inicio, fim, horaInicio, horaFim, passo, apenasMedidor)
  const conta = estimativa(selecao, opcoes, janela, passo)
  const impede = impedimento(selecao, passo, janela, inicio, opcoes)
  const orcamento = avisoDeOrcamento(conta, opcoes.limites)

  useEffect(() => {
    gravarForma(usinaId, { passo, selecao, horaInicio, horaFim })
  }, [usinaId, passo, selecao, horaInicio, horaFim])

  /* ---------------------------------------------------------------- baixar */

  const [baixando, setBaixando] = useState(false)
  const [decorrido, setDecorrido] = useState(0)
  const [recusa, setRecusa] = useState<Recusa | null>(null)
  const [falha, setFalha] = useState<{ texto: string; repetivel: boolean } | null>(null)
  const [pronto, setPronto] = useState<{ nome: string; bytes: number } | null>(null)
  const controle = useRef<AbortController | null>(null)
  const cortou = useRef(false)

  useEffect(() => {
    if (!baixando) return
    const t = setInterval(() => setDecorrido((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [baixando])

  // O `fix c23b330` do meuWatt: a confirmação da usina anterior não pode sobreviver à troca de
  // usina — ela afirmaria que existe um arquivo DESTA que não existe.
  useEffect(() => {
    setPronto(null)
    setRecusa(null)
    setFalha(null)
  }, [usinaId])

  // A aba pode ser levada a outra tela pelo menu de trás — e o `fetch` morre com a página. O
  // aborto no desmonte pelo menos solta a vaga da fila do BFF em vez de deixá-la pendurada.
  useEffect(() => () => controle.current?.abort(), [])

  const cancelar = () => {
    cortou.current = false
    controle.current?.abort()
  }

  async function baixar() {
    if (baixando) return
    setRecusa(null)
    setFalha(null)
    setPronto(null)
    setDecorrido(0)
    cortou.current = false
    const controlador = new AbortController()
    controle.current = controlador
    const corte = setTimeout(() => {
      cortou.current = true
      controlador.abort()
    }, PRAZO_DO_ARQUIVO_MS)
    setBaixando(true)
    try {
      const { blob, nome } = await baixarDados(
        usinaId,
        { inicio, fim, hora_inicio: horaInicio, hora_fim: horaFim, passo, ...selecao },
        controlador.signal,
      )
      baixarBlob(blob, nome)
      setPronto({ nome, bytes: blob.size })
    } catch (erro) {
      if (erro instanceof Cancelado) {
        // Desistir é decisão legítima e não vira aviso nenhum. O CORTE, sim: é decisão nossa,
        // e quem esperou três minutos precisa saber o que houve e o que fazer a respeito.
        if (cortou.current) {
          setFalha({
            texto:
              'O arquivo passou de três minutos e o pedido foi cortado. Peça um período menor ' +
              'ou um detalhe mais grosso — a planilha fica pronta bem mais rápido.',
            // Sem botão: a frase acima pede para MUDAR o pedido, e um "Tentar de novo" ao lado
            // convidaria a esperar outros três minutos pelo mesmo corte.
            repetivel: false,
          })
        }
      } else if (erro instanceof ErroDaExportacao) {
        const traduzida = traduzirMotivo(erro.motivo)
        if (traduzida) setRecusa(traduzida)
        // ⛔ Recusa SEM motivo ainda pode ser permanente, e aí o botão mente. O caso real é o
        // 422 do Pydantic (`passo` fora da lista, data em formato de gente, mais de 500
        // séries): ele sai cru, sem o `motivo` do vocabulário fechado, e o mesmo corpo dará o
        // mesmo 422 para sempre. 5xx e falha de transporte, sim, valem outra tentativa.
        else setFalha({ texto: erro.message, repetivel: erro.status === null || erro.status >= 500 })
      } else {
        setFalha({ texto: 'Não deu para baixar os dados.', repetivel: true })
      }
    } finally {
      clearTimeout(corte)
      controle.current = null
      setBaixando(false)
    }
  }

  /* ---------------------------------------------------------------- edição */

  /** Qualquer edição de bloco apaga o rastro do atalho: ele preencheu, não governa. */
  const trocar = (s: Selecao) => {
    setSelecao(s)
    setPreenchidoDe(null)
    setDescartados([])
    setRecusa(null)
  }

  const comecarDe = (id: string) => {
    const pacote = PACOTES.find((p) => p.id === id)
    if (!pacote) return
    setSelecao(montarPacote(pacote.id, opcoes))
    setPreenchidoDe(pacote.rotulo)
    setDescartados([])
    setRecusa(null)
  }

  const aplicarPeriodo = (r: RecorteDaTela, ref: string, novoDe: string, novoAte: string) => {
    setRecorte(r)
    setReferencia(ref)
    setDe(novoDe)
    setAte(novoAte)
    const p = periodoDe(r, ref, novoDe, novoAte, hoje)
    const dias = janelaDo(p.inicio, p.fim, HORA_INICIO_PADRAO, HORA_FIM_PADRAO, '1d', false).dias
    const ajuste = ajustarPasso(passo, dias, opcoes.limites)
    setPasso(ajuste.passo)
    setAvisoDoPasso(ajuste.aviso)
  }

  const irPara = (v: string) => {
    const d = daData(hoje)
    if (v === 'atalho:ontem') {
      const ontem = paraIso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - 1))
      aplicarPeriodo('livre', referencia, ontem, ontem)
      return
    }
    if (v === 'atalho:7d') {
      aplicarPeriodo(
        'livre',
        referencia,
        paraIso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - 6)),
        hoje,
      )
      return
    }
    if (v === 'atalho:mes') {
      aplicarPeriodo('mes', hoje, de, ate)
      return
    }
    const [ano, mes] = v.slice(4).split('-').map(Number)
    aplicarPeriodo('mes', paraIso(new Date(ano, mes - 1, 1)), de, ate)
  }

  /* ---------------------------------------------------------------- blocos */

  const nInversores = opcoes.skids.reduce((t, s) => t + s.series.length, 0)
  const linhasDoInversor = opcoesDoInversor(opcoes, passo)
  const linhasDaEstacao = opcoesDaEstacao(opcoes)
  const linhasDaFronteira = opcoesDaFronteira(opcoes)
  const linhasDoSistema = opcoesDoSistema(opcoes, passo)
  const semEstacao = escolhiveis(linhasDaEstacao).length === 0
  const semSistema = opcoes.sistema.pr === false && opcoes.sistema.produtividade === false

  /**
   * Os skids viram grupos da lista suspensa — e a capacidade já chega formatada em pt-BR.
   *
   * Formatar número não é trabalho do componente do vocabulário: `inteiro` devolve "—" quando
   * o cadastro não tem a capacidade, e é isso que o cliente deve ler, não um zero.
   */
  const gruposDeInversores: GrupoDeOpcoes[] = useMemo(
    () =>
      opcoes.skids.map((s) => ({
        chave: String(s.id ?? s.nome),
        rotulo: s.nome,
        detalhe: `${inteiro(s.capacidade_kwp)} kWp`,
        opcoes: s.series.map((serie) => ({
          valor: serie.chave,
          rotulo: serie.rotulo,
          // O número de série é o que a pessoa tem na mão; a chave (`slot:170`) é transporte
          // e não aparece em lugar nenhum da tela.
          ...(serie.numero_serie ? { detalhe: `série ${serie.numero_serie}` } : {}),
        })),
      })),
    [opcoes],
  )

  const diasDoSeletor = diasOferecidos(hoje, opcoes.retencao, apenasMedidor)
  const podeBaixar = !impede && !baixando && !vazia(selecao)
  const ehDiario = passo === '1d'
  const retencao = linhaDeRetencao(selecao, opcoes.retencao, passo)

  return (
    <>
      <EtapaDaTela numero="1." titulo="Começar de…">
        <div className="flex flex-wrap items-center gap-3">
          <Combobox
            opcoes={PACOTES.map((p) =>
              opcao(
                { valor: p.id, rotulo: p.rotulo, detalhe: p.detalhe },
                motivoDoPacote(p.id, opcoes),
              ),
            )}
            valor={null}
            onEscolher={comecarDe}
            placeholder="Preencher os blocos com um começo pronto…"
            className="w-full max-w-md"
            larguraMenu="w-[26rem]"
          />
          <p className="text-xs text-fraco">
            É um atalho: preenche os quatro blocos abaixo e volta ao lugar. Tudo continua
            editável.
          </p>
        </div>
        {preenchidoDe ? (
          <p className="mt-2 text-xs text-tom-ok">
            Blocos preenchidos a partir de “{preenchidoDe}”. Ajuste o que quiser abaixo.
          </p>
        ) : null}
        {descartados.length > 0 ? (
          <div className="mt-3">
            <Aviso tom="semDados">
              O que estava guardado desta usina mudou:{' '}
              {descartados.map((d) => d.motivo).join(' · ')}.
            </Aviso>
          </div>
        ) : null}
      </EtapaDaTela>

      <EtapaDaTela numero="2." titulo="De quando a quando">
        <div className="flex flex-wrap items-center gap-2">
          <Segmentado
            opcoes={RECORTES}
            valor={recorte}
            onEscolher={(r) => aplicarPeriodo(r, referencia, de, ate)}
          />
          {recorte === 'livre' ? (
            <>
              <span className="text-xs uppercase tracking-wide text-rotulo">de</span>
              <Combobox
                opcoes={diasDoSeletor.filter((o) => o.valor <= ate)}
                valor={de}
                onEscolher={(v) => aplicarPeriodo('livre', referencia, v, ate)}
                className="w-44"
                larguraMenu="w-72"
              />
              <span className="text-xs uppercase tracking-wide text-rotulo">até</span>
              <Combobox
                opcoes={diasDoSeletor.filter((o) => o.valor >= de)}
                valor={ate}
                onEscolher={(v) => aplicarPeriodo('livre', referencia, de, v)}
                className="w-44"
                larguraMenu="w-72"
              />
            </>
          ) : (
            <PassoPeriodo
              rotulo={rotuloDoPeriodo(referencia, recorte)}
              aoVoltar={() =>
                aplicarPeriodo(recorte, passoNoTempo(referencia, recorte, -1), de, ate)
              }
              aoAvancar={() =>
                aplicarPeriodo(recorte, passoNoTempo(referencia, recorte, 1), de, ate)
              }
              podeAvancar={!passaDeHoje(passoNoTempo(referencia, recorte, 1), recorte)}
            />
          )}
          <Combobox
            opcoes={atalhosDePeriodo(hoje, opcoes.retencao, apenasMedidor)}
            valor={null}
            onEscolher={irPara}
            placeholder="Ir para…"
            className="w-48"
            larguraMenu="w-72"
          />
        </div>
        <p className="mt-2 text-xs text-fraco">
          {janela.dias === 1 ? '1 dia' : `${inteiro(janela.dias)} dias`}, de{' '}
          <Num>{dataCurta(inicio)}</Num> a <Num>{dataCurta(fim)}</Num>
          {ehDiario ? null : ` · das ${horaInicio} às ${horaFim}`}
        </p>
        {/* A retenção é ausência de DADO, e por isso mora aqui, no período — não no rodapé,
            junto de coisas que falam do arquivo. A frase troca com a seleção porque os dois
            acervos têm prazos diferentes (o medidor guarda 24 meses; o resto, 6). */}
        <p className="mt-1 text-xs text-fraco">
          {ehDiario
            ? 'O total por dia não tem prazo: ele existe para todo o histórico da usina.'
            : retencao
              ? `${retencao} Antes disso, só o total por dia.`
              : 'O monitoramento não informou até onde o acervo fino alcança nesta usina.'}
        </p>
      </EtapaDaTela>

      <EtapaDaTela numero="3." titulo="Horário do primeiro e do último dia">
        <div
          className={ehDiario ? 'pointer-events-none opacity-40' : ''}
          title={ehDiario ? 'No total por dia o horário não se aplica' : undefined}
        >
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <Rotulo>do primeiro dia, a partir de</Rotulo>
              <Combobox
                opcoes={HORARIOS}
                valor={horaInicio}
                onEscolher={setHoraInicio}
                className="w-40"
                larguraMenu="w-40"
              />
            </div>
            <div>
              <Rotulo>do último dia, até</Rotulo>
              <Combobox
                opcoes={HORARIOS}
                valor={horaFim}
                onEscolher={setHoraFim}
                className="w-40"
                larguraMenu="w-40"
              />
            </div>
            {horaInicio !== HORA_INICIO_PADRAO || horaFim !== HORA_FIM_PADRAO ? (
              // Voltar ao dia inteiro é uma AÇÃO, não uma opção a escolher — por isso `Botao`.
              <Botao
                variante="secundario"
                onClick={() => {
                  setHoraInicio(HORA_INICIO_PADRAO)
                  setHoraFim(HORA_FIM_PADRAO)
                }}
              >
                Dias inteiros
              </Botao>
            ) : null}
          </div>
        </div>
        <p className="mt-2 text-xs text-fraco">
          {ehDiario
            ? '"Um total por dia" não usa horário: cada linha é o dia inteiro.'
            : 'Em horário de Brasília. O horário final é inclusivo do minuto: 23:59 fecha o dia.'}
        </p>
      </EtapaDaTela>

      <EtapaDaTela numero="4." titulo="Com que detalhe">
        <Combobox
          opcoes={opcoesDePasso(opcoes.limites)}
          valor={passo}
          onEscolher={(v) => {
            setPasso(v as Passo)
            setAvisoDoPasso(null)
          }}
          className="w-full max-w-md"
          larguraMenu="w-[26rem]"
        />
        <p className="mt-2 text-xs text-fraco">
          Cada linha do arquivo é um instante deste tamanho.
        </p>
        {/* Ajuste automático que se anuncia: trocar o detalhe em silêncio é a mudança que só
            se descobre ao abrir a planilha. */}
        {avisoDoPasso ? <p className="mt-1 text-xs text-tom-alerta">{avisoDoPasso}</p> : null}
      </EtapaDaTela>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* ---------------------------------------------------------- inversores */}
        <CartaoDeBloco
          titulo="Inversores"
          contagem={`${inteiro(nInversores)} inversores em ${inteiro(opcoes.skids.length)} skids`}
          motivo={
            nInversores === 0 ? 'esta usina não tem inversores cadastrados no monitoramento' : null
          }
          ligado={!!selecao.inversores}
          aoLigar={(v) =>
            trocar({
              ...selecao,
              inversores: v ? { variaveis: ['geracao'], agrupamento: 'lista', series: null } : null,
            })
          }
        >
          <Campo rotulo="Colunas">
            <ComboboxMulti
              opcoes={linhasDoInversor}
              valor={selecao.inversores ? selecao.inversores.variaveis : []}
              substantivo="colunas"
              rotuloTodos="todas"
              onEscolher={(v) => {
                const variaveis = (v === null ? escolhiveis(linhasDoInversor) : v) as VarInversor[]
                trocar({
                  ...selecao,
                  inversores: variaveis.length
                    ? {
                        variaveis,
                        agrupamento: selecao.inversores ? selecao.inversores.agrupamento : 'lista',
                        series: selecao.inversores ? selecao.inversores.series : null,
                      }
                    : null,
                })
              }}
              className="w-full max-w-sm"
            />
          </Campo>
          <Campo rotulo="Como agrupar">
            <Agrupamento
              opcoes={AGRUPAMENTO_DO_INVERSOR}
              valor={selecao.inversores ? selecao.inversores.agrupamento : 'lista'}
              onEscolher={(v) =>
                trocar({
                  ...selecao,
                  inversores: {
                    variaveis: selecao.inversores ? selecao.inversores.variaveis : ['geracao'],
                    agrupamento: v === 'skid' ? 'skid' : 'lista',
                    series: selecao.inversores ? selecao.inversores.series : null,
                  },
                })
              }
            />
          </Campo>
          <Campo rotulo="Quais inversores">
            <ComboboxMultiAgrupado
              grupos={gruposDeInversores}
              valor={selecao.inversores ? selecao.inversores.series : null}
              substantivo="inversores"
              rotuloTodos="todos"
              notaTodos="Inclui um inversor que entre em operação no meio do período."
              notaVazio="Sem nenhum inversor marcado não há arquivo: marque ao menos um, ou volte a “todos”."
              larguraMenu="w-96"
              onEscolher={(series) =>
                trocar({
                  ...selecao,
                  inversores: {
                    variaveis: selecao.inversores ? selecao.inversores.variaveis : ['geracao'],
                    agrupamento: selecao.inversores ? selecao.inversores.agrupamento : 'lista',
                    series,
                  },
                })
              }
              className="w-full max-w-sm"
            />
          </Campo>
          {selecao.inversores && selecao.inversores.agrupamento === 'skid' ? (
            <p className="text-xs text-fraco">{AVISO_DA_SOMA_POR_SKID}.</p>
          ) : null}
        </CartaoDeBloco>

        {/* ---------------------------------------------------------- estação */}
        <CartaoDeBloco
          titulo="Estação solarimétrica"
          contagem={
            opcoes.estacao.disponivel
              ? 'irradiação ao vivo; os demais sensores só onde o registrador foi importado'
              : 'sem estação — só o relé de temperatura'
          }
          motivo={semEstacao ? 'esta usina não tem estação solarimétrica com dados' : null}
          ligado={!!selecao.estacao}
          aoLigar={(v) =>
            trocar({
              ...selecao,
              estacao: v ? { variaveis: escolhiveis(linhasDaEstacao) as VarEstacao[] } : null,
            })
          }
        >
          <Campo rotulo="Colunas">
            <ComboboxMulti
              opcoes={linhasDaEstacao}
              valor={selecao.estacao ? selecao.estacao.variaveis : []}
              substantivo="colunas"
              rotuloTodos="todas"
              onEscolher={(v) => {
                const variaveis = (v === null ? escolhiveis(linhasDaEstacao) : v) as VarEstacao[]
                trocar({ ...selecao, estacao: variaveis.length ? { variaveis } : null })
              }}
              className="w-full max-w-sm"
            />
          </Campo>
        </CartaoDeBloco>

        {/* ---------------------------------------------------------- fronteira */}
        <CartaoDeBloco
          titulo="Medidor de fronteira"
          contagem={`${inteiro(opcoes.leitores.length)} ${
            opcoes.leitores.length === 1 ? 'leitor' : 'leitores'
          } · energia por intervalo (kWh)`}
          motivo={motivoDaFronteira(opcoes)}
          ligado={!!selecao.fronteira}
          aoLigar={(v) =>
            trocar({
              ...selecao,
              fronteira: v ? { variaveis: ['energia'], agrupamento: 'leitor' } : null,
            })
          }
        >
          {/* A única coluna do bloco, e por isso escrita na cara — como no meuWatt, onde ela é
              uma caixa marcada que não se desmarca. Uma lista de uma opção só seria um clique
              a mais para dizer a mesma coisa; escondê-la faria o cartão parecer sem conteúdo. */}
          <Campo rotulo="Colunas">
            {linhasDaFronteira.map((l) => (
              <p key={l.valor} className="text-sm text-corpo">
                {l.rotulo}
                {l.detalhe ? <span className="ml-2 text-xs text-fraco">{l.detalhe}</span> : null}
              </p>
            ))}
          </Campo>
          <Campo rotulo="Como agrupar">
            <Agrupamento
              opcoes={AGRUPAMENTO_DA_FRONTEIRA}
              valor={selecao.fronteira ? selecao.fronteira.agrupamento : 'leitor'}
              onEscolher={(v) =>
                trocar({
                  ...selecao,
                  fronteira: { variaveis: ['energia'], agrupamento: v === 'usina' ? 'usina' : 'leitor' },
                })
              }
            />
          </Campo>
          {rodapeDaFronteira(opcoes) ? (
            <p className="text-xs text-fraco">{rodapeDaFronteira(opcoes)}</p>
          ) : null}
        </CartaoDeBloco>

        {/* ---------------------------------------------------------- sistema */}
        <CartaoDeBloco
          titulo="Desempenho do sistema"
          contagem="PR e produtividade calculadas por intervalo (razão de somas)"
          motivo={
            semSistema ? 'sem estação não há irradiação, e sem irradiação não se calcula PR' : null
          }
          ligado={!!selecao.sistema}
          aoLigar={(v) => {
            const variaveis = escolhiveis(linhasDoSistema) as VarSistema[]
            trocar({
              ...selecao,
              sistema:
                v && variaveis.length
                  ? {
                      variaveis,
                      agrupamento: selecao.sistema ? selecao.sistema.agrupamento : 'usina',
                    }
                  : null,
            })
          }}
        >
          <Campo rotulo="Colunas">
            <ComboboxMulti
              opcoes={linhasDoSistema}
              valor={selecao.sistema ? selecao.sistema.variaveis : []}
              substantivo="colunas"
              rotuloTodos="todas"
              onEscolher={(v) => {
                const variaveis = (v === null ? escolhiveis(linhasDoSistema) : v) as VarSistema[]
                trocar({
                  ...selecao,
                  sistema: variaveis.length
                    ? {
                        variaveis,
                        agrupamento: selecao.sistema ? selecao.sistema.agrupamento : 'usina',
                      }
                    : null,
                })
              }}
              className="w-full max-w-sm"
            />
          </Campo>
          <Campo rotulo="Como agrupar">
            <Agrupamento
              opcoes={AGRUPAMENTO_DO_SISTEMA}
              valor={selecao.sistema ? selecao.sistema.agrupamento : 'usina'}
              onEscolher={(v) =>
                trocar({
                  ...selecao,
                  sistema: {
                    variaveis: selecao.sistema
                      ? selecao.sistema.variaveis
                      : (escolhiveis(linhasDoSistema) as VarSistema[]),
                    agrupamento: v === 'skid' ? 'skid' : 'usina',
                  },
                })
              }
            />
          </Campo>
        </CartaoDeBloco>
      </div>

      {/* A conta é NOSSA e aproximada — por isso o "≈", e por isso ela não impede nada. No
          limiar, o benefício da dúvida é do cliente: a palavra final é do servidor. */}
      {orcamento && !impede ? <Aviso>{orcamento}</Aviso> : null}

      {recusa ? (
        <Aviso tom={recusa.espera ? 'semDados' : 'alerta'}>
          <div>{recusa.texto}</div>
          {recusa.espera ? (
            <div className="mt-3">
              <Botao variante="secundario" onClick={() => void baixar()}>
                Tentar de novo
              </Botao>
            </div>
          ) : null}
        </Aviso>
      ) : null}

      {falha ? (
        <Erro
          mensagem={falha.texto}
          aoTentar={falha.repetivel ? () => void baixar() : undefined}
        />
      ) : null}

      {/*
        O TRILHO DO ARQUIVO, grudento no pé da tela.

        Com quatro cartões de configuração acima, a estimativa e o botão sairiam do campo de
        visão justamente enquanto se mexe no que os muda — e o defeito que isso produzia é o
        que o handoff descreve: configurar 22 colunas no escuro e só o Excel revelar o
        resultado. Aqui o tamanho do arquivo é lido no mesmo gesto em que se muda a fonte.

        Os dois números ganham corpo de 34px (a medida que o redesenho reserva para o
        "quanto") e o resto desce para legenda. Não é um `Kpi` de propósito: aquela peça é a
        dos fatos MEDIDOS, e isto é uma conta aproximada — daí o "≈" na frente.

        O que NÃO está aqui, e por quê: o desenho pedia uma prévia das primeiras colunas com
        três linhas de exemplo. Linha de exemplo é dado inventado na tela, que é o que a
        REGRA 0 proíbe — e numa tela cujo produto final é uma planilha de medições, três
        valores fabricados seriam confundidos com a amostra real do arquivo.
      */}
      <div className="sticky bottom-2 z-10 rounded-card border border-ambar/28 bg-painel px-5 py-4 shadow-xl backdrop-blur-[18px]">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div className="min-w-0 flex-1">
            {impede ? (
              <span className="text-sm text-tom-alerta">{impede.texto}</span>
            ) : (
              <>
                <div className="rotulo-secao">O arquivo que vai sair</div>
                <div className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1">
                  <span className="mono text-[34px] font-semibold leading-none text-forte">
                    {/* O "≈" fica pequeno e colado: a 34px ele vira um glifo solto que
                        disputa com o número, e o que se lê é o número. */}
                    <span className="mr-1 align-[0.18em] text-[calc(16px_+_var(--passo-tipo))] font-normal text-fraco">≈</span>
                    {inteiro(conta.linhas)}
                    <span className="ml-2 text-[calc(15px_+_var(--passo-tipo))] font-normal text-fraco">linhas</span>
                  </span>
                  {/* Uma largura POR ABA, e não uma soma. Somar dava "37 colunas" num caderno
                      cuja aba mais larga tem 22 — número que o cliente não tem onde conferir
                      e que o Leia-me do próprio arquivo desmente linha a linha. */}
                  {conta.abas.map((aba) => (
                    <span key={aba.nome} className="text-[calc(13px_+_var(--passo-tipo))] text-fraco">
                      {aba.nome}{' '}
                      {aba.colunas === null ? (
                        <>({aba.nota})</>
                      ) : (
                        <>
                          <Num className="text-[calc(15px_+_var(--passo-tipo))] text-corpo">{inteiro(aba.colunas)}</Num>{' '}
                          colunas
                          {aba.nota ? `, ${aba.nota}` : ''}
                        </>
                      )}
                    </span>
                  ))}
                </div>
                {/* A regra do produto, no lugar onde ela é lida: ao lado do arquivo, e não
                    como texto solto no pé da página. É a diferença entre uma célula vazia e
                    uma célula com zero — e é a leitura mais cara de errar numa planilha. */}
                <p className="mono mt-2 text-[calc(11.5px_+_var(--passo-tipo))] text-fraco">
                  Vazio = sem leitura. 0 = zero medido.
                </p>
              </>
            )}
            {pronto ? (
              <div className="mt-2 text-sm text-tom-ok">
                Pronto: <Num>{pronto.nome}</Num> ({tamanhoEmTexto(pronto.bytes)}) — o navegador
                salvou na sua pasta de downloads.
              </div>
            ) : null}
          </div>
          <Botao onClick={() => void baixar()} desabilitado={!podeBaixar}>
            {baixando ? 'Gerando…' : 'Baixar planilha'}
          </Botao>
        </div>
      </div>

      <Modal titulo="Preparando a planilha" aberto={baixando} aoFechar={cancelar}>
        <BarraIndeterminada />
        <p className="mt-4 text-sm text-corpo">
          Gerando há <Num>{decorridoEmTexto(decorrido)}</Num>.
        </p>
        <p className="mt-2 text-sm text-fraco">
          O arquivo é montado inteiro no monitoramento e desce de uma vez — por isso não há
          porcentagem para mostrar. Um mês a cada 15 minutos costuma levar menos de um minuto.
        </p>
        <p className="mt-2 text-sm text-fraco">
          Sair desta tela ou fechar a aba cancela o pedido: o download é feito por ela.
        </p>
        <div className="mt-4">
          <Botao variante="secundario" onClick={cancelar}>
            Cancelar
          </Botao>
        </div>
      </Modal>
    </>
  )
}

/* ================================================================== página */

function EsqueletoDaTela() {
  return (
    <div className="space-y-4">
      <Cartao>
        <div className="space-y-5">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i}>
              <Esqueleto altura={12} largura="22%" />
              <div className="mt-2">
                <Esqueleto altura={38} largura="60%" />
              </div>
            </div>
          ))}
        </div>
      </Cartao>
      <CarregandoCartao linhas={2} />
    </div>
  )
}

export default function BaixarDados() {
  const { id } = useParams<{ id: string }>()
  const usinaId = Number(id)
  const usinaValida = Number.isFinite(usinaId) && usinaId > 0

  const leitura = useLeitura<OpcoesDeDados>(chaveDasOpcoes(usinaId), { ativo: usinaValida })

  return (
    <Pagina
      titulo="Baixar dados"
      subtitulo="Os números desta usina, do jeito que a sua planilha lê."
    >
      {!usinaValida ? (
        <Vazio
          titulo="Escolha uma usina"
          descricao="Selecione a usina na barra do topo para baixar os dados dela."
        />
      ) : leitura.status === 404 ? (
        // 404 não é "a rede caiu": insistir nunca vai abrir esta porta. Mas ele também não é
        // UMA coisa só — pode ser a usina fora do escopo, a usina sem vínculo com o
        // monitoramento, ou a rota que ainda não subiu. Este último aconteceu na conferência
        // de 05/09/2026: o BFF local era um processo antigo, sem a rota nova, e a tela
        // afirmava "esta usina não está ligada ao monitoramento" sobre uma usina que está.
        // Por isso o título vale para os três casos e a FRASE é a do SERVIDOR — inventar um
        // diagnóstico sobre a usina do cliente a partir de um deploy velho é o defeito mais
        // caro que esta tela pode cometer, porque ele soa verdadeiro.
        <Vazio
          titulo="Não há dados brutos para baixar nesta usina"
          descricao={leitura.erro ?? 'O monitoramento não reconheceu esta usina.'}
        />
      ) : (
        <Tela4Estados leitura={leitura} esqueleto={<EsqueletoDaTela />}>
          {(dados) =>
            dados.skids.length === 0 &&
            !dados.estacao.disponivel &&
            dados.leitores.length === 0 ? (
              <Vazio
                titulo="Esta usina ainda não tem equipamento cadastrado no monitoramento"
                descricao="Sem inversor, estação ou medidor não há série nenhuma para exportar."
              />
            ) : (
              <Conteudo usinaId={usinaId} opcoes={dados} />
            )
          }
        </Tela4Estados>
      )}
    </Pagina>
  )
}
