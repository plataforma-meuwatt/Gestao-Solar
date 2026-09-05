/**
 * Baixar dados — os números desta usina, do jeito que a planilha do cliente lê.
 *
 * A tela do meuWatt responde *"que colunas eu quero no arquivo?"*. Essa pergunta não tem dono
 * no portal do cliente: ninguém acorda querendo `slot:12` agrupado por skid. A pergunta que
 * tem dono é *"quero os números desta usina para trabalhar na minha planilha"* — e quem a faz
 * não é o diretor, é o contador, o analista da holding ou o engenheiro contratado, usando o
 * login do cliente. Daí sai tudo o que está desenhado aqui:
 *
 * **Três perguntas, com a resposta já preenchida.** O quê · de quando a quando · com que
 * detalhe. A tela abre respondível — usina do contexto, pacote padrão, mês corrente, detalhe
 * sugerido, estimativa calculada, botão vivo. Formulário que abre vazio obriga o cliente a
 * trabalhar antes de descobrir o que a tela faz.
 *
 * **O período usa a MESMA peça do Painel e de Paradas.** Não é só familiaridade: é o que faz a
 * conversa sobre tetos quase nunca acontecer — um mês a 15 minutos dá 31 dias (teto 92) e um
 * ano por hora dá 366 (teto 366). O caminho curto praticamente nunca esbarra.
 *
 * **A gaveta "Escolher coluna por coluna" é uma lupa sobre o padrão, não um formulário
 * paralelo.** Ela mostra o que o pacote escolhido quer dizer, aberto — nada some. Ao mexer, o
 * nome do pacote vira "Personalizado", porque continuar dizendo "Geração da usina" seria
 * mentir sobre o que vai no arquivo.
 *
 * **Nenhuma escolha é um chip.** `Combobox`, `ComboboxMulti` ou `Segmentado`, de duas a
 * quinhentas opções. A tela do meuWatt usa chips; esta não copia isso. E o que a usina não tem
 * continua na lista, desabilitado e com o motivo — a `Opcao` do design system, por construção,
 * só deixa desabilitar quem escreve o porquê.
 *
 * **A espera é honesta.** A rota do meuWatt é síncrona (o POST devolve o arquivo pronto; não
 * há job, id, nem endpoint de andamento), e o cabeçalho só chega quando o XLSX inteiro foi
 * montado — 34 s medidos no pior pedido. Então: barra INDETERMINADA e jamais uma porcentagem
 * (inventar "43 %" seria ficção), o tempo DECORRIDO à mostra, a razão da ausência escrita, um
 * `Modal` que segura a navegação de trás (o `fetch` morre com a página, e isso tem de ser dito
 * antes e não descoberto depois), Cancelar que aborta de verdade, e um corte declarado aos
 * 180 s com a saída nomeada.
 *
 * **A chave de série nunca aparece.** `slot:170` é transporte; o cliente lê "Inv 13", com o
 * número de série ao lado — que é o que ele tem na mão para conferir.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'

import {
  Aviso,
  Botao,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  Combobox,
  ComboboxMulti,
  Erro,
  Esqueleto,
  Gaveta,
  Modal,
  Num,
  opcao,
  Pagina,
  PassoPeriodo,
  Segmentado,
  Tela4Estados,
  Vazio,
  type Opcao,
} from '@/components/base'
import { baixarBlob } from '@/lib/arquivo'
import { dataCurta, inteiro } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import {
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
import {
  CLIMA,
  climaDisponivel,
  diasOferecidos,
  estimativa,
  faltamNoPacote,
  impedimento,
  janelaDo,
  montarPacote,
  motivoDoPacote,
  opcoesDePasso,
  PACOTES,
  passaDoOrcamento,
  passoSugerido,
  PERSONALIZADO,
  ROTULO_DA_ESTACAO,
  ROTULO_DO_INVERSOR,
  ROTULO_DO_SISTEMA,
  soMedidor,
  traduzirMotivo,
  vazia,
  type IdDePacote,
  type Recusa,
} from '@/features/dados/pacotes'

/* ================================================================== recorte */

/** O quarto recorte não existe em `lib/periodo`: é o intervalo de/até desta tela. */
type RecorteDaTela = Recorte | 'livre'

const RECORTES: { valor: RecorteDaTela; rotulo: string }[] = [
  { valor: 'dia', rotulo: 'Dia' },
  { valor: 'mes', rotulo: 'Mês' },
  { valor: 'ano', rotulo: 'Ano' },
  { valor: 'livre', rotulo: 'Personalizado' },
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

/* ================================================================== pedaços */

function Pergunta({
  numero,
  titulo,
  detalhe,
  children,
}: {
  numero: string
  titulo: string
  detalhe?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="border-b border-borda-fraca py-4 first:pt-0 last:border-0 last:pb-0">
      <div className="mb-2 flex items-baseline gap-2">
        <span className="text-xs text-fraco">{numero}</span>
        <h3 className="text-sm font-medium text-forte">{titulo}</h3>
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
      {detalhe ? <p className="mt-2 text-xs text-fraco">{detalhe}</p> : null}
    </div>
  )
}

function Campo({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-1.5 text-xs uppercase tracking-wide text-rotulo">{rotulo}</div>
      {children}
    </div>
  )
}

/** O que esta usina não tem, dito ONDE a escolha estaria — nunca uma seção que some. */
function NaoTem({ motivo }: { motivo: string }) {
  return <p className="text-sm text-fraco">Não entra: {motivo}.</p>
}

/**
 * A barra da espera — sem porcentagem, de propósito.
 *
 * O servidor monta o arquivo inteiro antes de responder o primeiro byte: não existe progresso
 * para mostrar. Uma barra que anda sozinha diria ao cliente que sabemos quanto falta.
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

/** De quinze em quinze minutos: "25:70" fica impossível porque não se digita horário aqui. */
const HORARIOS: Opcao[] = [
  ...Array.from({ length: 96 }, (_, i): Opcao => {
    const h = String(Math.floor(i / 4)).padStart(2, '0')
    const m = String((i % 4) * 15).padStart(2, '0')
    return { valor: `${h}:${m}`, rotulo: `${h}:${m}` }
  }),
  { valor: '23:59', rotulo: '23:59', detalhe: 'até o fim do dia' },
]

/* ================================================================== forma guardada */

type FormaGuardada = {
  pacote: string
  passo: Passo
  selecao: Selecao
  horaInicio: string
  horaFim: string
}

/**
 * A FORMA da pergunta fica guardada por usina; o PERÍODO não.
 *
 * Quem baixa a mesma planilha todo mês não quer remontar a seleção — mas reabrir a tela já
 * apontada para agosto devolveria, calado, o arquivo do mês errado. O período recomeça sempre
 * no mês corrente, à vista.
 */
const chaveDaForma = (usinaId: number) => `dados:forma:u${usinaId}`

function lerForma(usinaId: number): FormaGuardada | null {
  try {
    const cru = localStorage.getItem(chaveDaForma(usinaId))
    return cru ? (JSON.parse(cru) as FormaGuardada) : null
  } catch {
    // Armazenamento bloqueado ou JSON estragado: a tela abre no padrão, que é sempre válido.
    return null
  }
}

function gravarForma(usinaId: number, forma: FormaGuardada): void {
  try {
    localStorage.setItem(chaveDaForma(usinaId), JSON.stringify(forma))
  } catch {
    // Guardar a preferência não pode derrubar o download.
  }
}

/* ================================================================== gaveta */

/**
 * "Todas" numa lista de COLUNAS quer dizer "todas as que existem" — diferente do que quer
 * dizer numa lista de inversores, onde `null` é a regra que alcança o equipamento futuro.
 * Aqui não há equipamento futuro: as variáveis são um vocabulário fechado.
 */
function colunasEscolhidas(v: string[] | null, disponiveis: string[]): string[] {
  return v === null ? disponiveis : v
}

function Avancado({
  aberta,
  aoFechar,
  opcoes,
  selecao,
  aoTrocar,
  passo,
  horaInicio,
  horaFim,
  aoTrocarHoras,
}: {
  aberta: boolean
  aoFechar: () => void
  opcoes: OpcoesDeDados
  selecao: Selecao
  aoTrocar: (s: Selecao) => void
  passo: Passo
  horaInicio: string
  horaFim: string
  aoTrocarHoras: (inicio: string, fim: string) => void
}) {
  const series = useMemo(
    () => opcoes.skids.flatMap((s) => s.series.map((serie) => ({ serie, skid: s.nome }))),
    [opcoes],
  )
  const clima = climaDisponivel(opcoes)
  const temEstacao = clima.length > 0 || opcoes.estacao.temp_ambiente_rele
  const temDesempenho = opcoes.sistema.pr || opcoes.sistema.produtividade

  const VARS_INVERSOR: VarInversor[] = ['geracao', 'potencia', 'status', 'paradas']
  const VARS_ESTACAO: VarEstacao[] = [...CLIMA, 'temp_ambiente_rele']
  const VARS_SISTEMA: VarSistema[] = ['pr', 'produtividade']

  const estacaoDisponivel = VARS_ESTACAO.filter((x) =>
    x === 'temp_ambiente_rele' ? opcoes.estacao.temp_ambiente_rele : clima.includes(x),
  )
  const sistemaDisponivel = VARS_SISTEMA.filter((x) =>
    x === 'pr' ? opcoes.sistema.pr : opcoes.sistema.produtividade,
  )

  return (
    <Gaveta titulo="Escolher coluna por coluna" aberta={aberta} aoFechar={aoFechar}>
      <p className="mb-5 text-sm text-fraco">
        Aqui está o que o pacote escolhido quer dizer, aberto. Coluna sem marca não entra no
        arquivo; o que esta usina não mede aparece apagado, com o motivo.
      </p>

      <section className="mb-6">
        <CabecalhoCard rotulo="Inversores" />
        {series.length === 0 ? (
          <NaoTem motivo="esta usina não tem inversores cadastrados no monitoramento" />
        ) : (
          <>
            <Campo rotulo="Colunas">
              <ComboboxMulti
                opcoes={VARS_INVERSOR.map((v) => ({
                  valor: v,
                  rotulo: ROTULO_DO_INVERSOR[v],
                  // A restrição fica escrita AO LADO da opção. Escolhê-la não é proibido: o
                  // impedimento aparece embaixo, com a saída nomeada, porque o que está errado
                  // pode ser o detalhe escolhido, e não a coluna.
                  ...(v === 'status'
                    ? { detalhe: 'só sai em "cada leitura, como o equipamento mandou"' }
                    : v === 'paradas'
                      ? { detalhe: 'não sai no passo "cada leitura"' }
                      : {}),
                }))}
                valor={selecao.inversores ? selecao.inversores.variaveis : []}
                substantivo="colunas"
                rotuloTodos="todas"
                onEscolher={(v) => {
                  const variaveis = colunasEscolhidas(v, VARS_INVERSOR) as VarInversor[]
                  aoTrocar({
                    ...selecao,
                    inversores: variaveis.length
                      ? {
                          variaveis,
                          agrupamento: selecao.inversores?.agrupamento ?? 'lista',
                          series: selecao.inversores?.series ?? null,
                        }
                      : null,
                  })
                }}
                className="w-full max-w-sm"
              />
            </Campo>
            {selecao.inversores ? (
              <>
                <Campo rotulo="Como agrupar">
                  <Segmentado
                    opcoes={[
                      { valor: 'lista', rotulo: 'Uma coluna por inversor' },
                      { valor: 'skid', rotulo: 'Uma coluna por skid' },
                    ]}
                    valor={selecao.inversores.agrupamento}
                    onEscolher={(agrupamento) =>
                      aoTrocar({ ...selecao, inversores: { ...selecao.inversores!, agrupamento } })
                    }
                  />
                </Campo>
                <Campo rotulo="Quais inversores">
                  <ComboboxMulti
                    opcoes={series.map(({ serie, skid }) => ({
                      valor: serie.chave,
                      rotulo: serie.rotulo,
                      // O número de série é o que a pessoa tem na mão; a chave (`slot:170`) é
                      // transporte e não aparece em lugar nenhum da tela.
                      detalhe: serie.numero_serie ? `${skid} · série ${serie.numero_serie}` : skid,
                    }))}
                    valor={selecao.inversores.series}
                    substantivo="inversores"
                    rotuloTodos="todos"
                    notaTodos="Inclui um inversor que entre em operação no meio do período."
                    onEscolher={(v) =>
                      aoTrocar({ ...selecao, inversores: { ...selecao.inversores!, series: v } })
                    }
                    className="w-full max-w-sm"
                    larguraMenu="w-80"
                  />
                </Campo>
              </>
            ) : null}
          </>
        )}
      </section>

      <section className="mb-6">
        <CabecalhoCard rotulo="Estação e clima" />
        {!temEstacao ? (
          <NaoTem motivo="esta usina não tem estação solarimétrica com dados" />
        ) : (
          <Campo rotulo="Colunas">
            <ComboboxMulti
              opcoes={VARS_ESTACAO.map((v) =>
                opcao(
                  { valor: v, rotulo: ROTULO_DA_ESTACAO[v] },
                  v === 'temp_ambiente_rele'
                    ? opcoes.estacao.temp_ambiente_rele
                      ? null
                      : 'esta usina não tem relé de temperatura'
                    : clima.includes(v)
                      ? null
                      : 'esta estação não mede',
                ),
              )}
              valor={selecao.estacao ? selecao.estacao.variaveis : []}
              substantivo="colunas"
              rotuloTodos="todas"
              onEscolher={(v) => {
                const variaveis = colunasEscolhidas(v, estacaoDisponivel) as VarEstacao[]
                aoTrocar({ ...selecao, estacao: variaveis.length ? { variaveis } : null })
              }}
              className="w-full max-w-sm"
            />
          </Campo>
        )}
      </section>

      <section className="mb-6">
        <CabecalhoCard rotulo="Medidor de fronteira" />
        {opcoes.leitores.length === 0 ? (
          <NaoTem motivo="esta usina não tem medidor de fronteira" />
        ) : (
          <>
            <Campo rotulo="A energia medida">
              <Segmentado
                opcoes={[
                  { valor: 'nao', rotulo: 'Não entra' },
                  { valor: 'sim', rotulo: 'Entra no arquivo' },
                ]}
                valor={selecao.fronteira ? 'sim' : 'nao'}
                onEscolher={(v) =>
                  aoTrocar({
                    ...selecao,
                    fronteira:
                      v === 'sim'
                        ? {
                            variaveis: ['energia'],
                            agrupamento: selecao.fronteira?.agrupamento ?? 'leitor',
                          }
                        : null,
                  })
                }
              />
            </Campo>
            {selecao.fronteira ? (
              <Campo rotulo="Como agrupar">
                <Segmentado
                  opcoes={[
                    { valor: 'leitor', rotulo: `Um por medidor (${opcoes.leitores.length})` },
                    { valor: 'usina', rotulo: 'Somado na usina' },
                  ]}
                  valor={selecao.fronteira.agrupamento}
                  onEscolher={(agrupamento) =>
                    aoTrocar({ ...selecao, fronteira: { variaveis: ['energia'], agrupamento } })
                  }
                />
              </Campo>
            ) : null}
          </>
        )}
      </section>

      <section className="mb-6">
        <CabecalhoCard rotulo="Desempenho" />
        {!temDesempenho ? (
          <NaoTem motivo="sem estação não há irradiação, e sem irradiação não se calcula PR" />
        ) : (
          <>
            <Campo rotulo="Colunas">
              <ComboboxMulti
                opcoes={VARS_SISTEMA.map((v) =>
                  opcao(
                    { valor: v, rotulo: ROTULO_DO_SISTEMA[v] },
                    v === 'pr' && !opcoes.sistema.pr
                      ? 'sem estação não há irradiação, e sem irradiação não se calcula PR'
                      : v === 'produtividade' && !opcoes.sistema.produtividade
                        ? 'esta usina não publica produtividade'
                        : null,
                  ),
                )}
                valor={selecao.sistema ? selecao.sistema.variaveis : []}
                substantivo="colunas"
                rotuloTodos="todas"
                onEscolher={(v) => {
                  const variaveis = colunasEscolhidas(v, sistemaDisponivel) as VarSistema[]
                  aoTrocar({
                    ...selecao,
                    sistema: variaveis.length
                      ? { variaveis, agrupamento: selecao.sistema?.agrupamento ?? 'usina' }
                      : null,
                  })
                }}
                className="w-full max-w-sm"
              />
            </Campo>
            {selecao.sistema ? (
              <Campo rotulo="Como agrupar">
                <Segmentado
                  opcoes={[
                    { valor: 'usina', rotulo: 'Usina inteira' },
                    { valor: 'skid', rotulo: 'Por skid' },
                  ]}
                  valor={selecao.sistema.agrupamento}
                  onEscolher={(agrupamento) =>
                    aoTrocar({
                      ...selecao,
                      sistema: { variaveis: selecao.sistema!.variaveis, agrupamento },
                    })
                  }
                />
              </Campo>
            ) : null}
          </>
        )}
      </section>

      <section>
        <CabecalhoCard rotulo="Horário" />
        {passo === '1d' ? (
          <p className="text-sm text-fraco">
            "Um total por dia" não usa horário: cada linha é o dia inteiro.
          </p>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <div className="mb-1.5 text-xs uppercase tracking-wide text-rotulo">
                do primeiro dia, a partir de
              </div>
              <Combobox
                opcoes={HORARIOS}
                valor={horaInicio}
                onEscolher={(v) => aoTrocarHoras(v, horaFim)}
                className="w-40"
                larguraMenu="w-40"
              />
            </div>
            <div>
              <div className="mb-1.5 text-xs uppercase tracking-wide text-rotulo">
                do último dia, até
              </div>
              <Combobox
                opcoes={HORARIOS}
                valor={horaFim}
                onEscolher={(v) => aoTrocarHoras(horaInicio, v)}
                className="w-40"
                larguraMenu="w-40"
              />
            </div>
          </div>
        )}
      </section>
    </Gaveta>
  )
}

/* ================================================================== conteúdo */

function Conteudo({ usinaId, opcoes }: { usinaId: number; opcoes: OpcoesDeDados }) {
  const hoje = hojeIso()
  const guardada = useMemo(() => lerForma(usinaId), [usinaId])

  const primeiroPacote = useMemo<IdDePacote>(() => {
    const livre = PACOTES.find((p) => motivoDoPacote(p.id, opcoes) === null)
    return livre ? livre.id : 'geracao'
  }, [opcoes])

  const [pacote, setPacote] = useState<string>(guardada?.pacote ?? primeiroPacote)
  const [selecao, setSelecao] = useState<Selecao>(
    guardada?.selecao ?? montarPacote(primeiroPacote, opcoes),
  )
  const [recorte, setRecorte] = useState<RecorteDaTela>('mes')
  const [referencia, setReferencia] = useState<string>(hoje)
  const [de, setDe] = useState<string>(
    paraIso(new Date(daData(hoje).getFullYear(), daData(hoje).getMonth(), 1)),
  )
  const [ate, setAte] = useState<string>(hoje)
  const [horaInicio, setHoraInicio] = useState<string>(guardada?.horaInicio ?? '00:00')
  const [horaFim, setHoraFim] = useState<string>(guardada?.horaFim ?? '23:59')
  const [avancado, setAvancado] = useState(false)

  const { inicio, fim } = periodoDe(recorte, referencia, de, ate, hoje)
  const [passo, setPasso] = useState<Passo>(
    guardada?.passo ??
      passoSugerido(
        'mes',
        janelaDo(inicio, fim, '00:00', '23:59', '1d', false).dias,
        opcoes.limites,
      ),
  )

  const janela = janelaDo(inicio, fim, horaInicio, horaFim, passo, soMedidor(selecao))
  const conta = estimativa(selecao, opcoes, janela)
  const impede = impedimento(selecao, passo, janela, inicio, opcoes)
  const grande = passaDoOrcamento(conta, opcoes.limites)

  useEffect(() => {
    gravarForma(usinaId, { pacote, passo, selecao, horaInicio, horaFim })
  }, [usinaId, pacote, passo, selecao, horaInicio, horaFim])

  /* ---------------------------------------------------------------- baixar */

  const [baixando, setBaixando] = useState(false)
  const [decorrido, setDecorrido] = useState(0)
  const [recusa, setRecusa] = useState<Recusa | null>(null)
  const [falha, setFalha] = useState<string | null>(null)
  const controle = useRef<AbortController | null>(null)
  const cortou = useRef(false)

  useEffect(() => {
    if (!baixando) return
    const t = setInterval(() => setDecorrido((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [baixando])

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
    } catch (erro) {
      if (erro instanceof Cancelado) {
        // Desistência do cliente não é erro e não vira aviso nenhum. O corte de tempo, sim: é
        // uma decisão NOSSA, e ele precisa saber que houve e o que fazer a respeito.
        if (cortou.current) {
          setFalha(
            'O arquivo passou de três minutos e o pedido foi cortado. Peça um período menor ' +
              'ou um detalhe mais grosso — a planilha fica pronta bem mais rápido.',
          )
        }
      } else if (erro instanceof ErroDaExportacao) {
        const traduzida = traduzirMotivo(erro.motivo)
        if (traduzida) setRecusa(traduzida)
        else setFalha(erro.message)
      } else {
        setFalha('Não deu para baixar os dados.')
      }
    } finally {
      clearTimeout(corte)
      controle.current = null
      setBaixando(false)
    }
  }

  /* ---------------------------------------------------------------- render */

  const trocarPacote = (id: string) => {
    setRecusa(null)
    setPacote(id)
    setSelecao(montarPacote(id as IdDePacote, opcoes))
  }

  const trocarRecorte = (r: RecorteDaTela) => {
    setRecorte(r)
    const p = periodoDe(r, referencia, de, ate, hoje)
    setPasso(
      passoSugerido(
        r === 'livre' ? 'livre' : r,
        janelaDo(p.inicio, p.fim, '00:00', '23:59', '1d', false).dias,
        opcoes.limites,
      ),
    )
  }

  const opcoesDePacote: Opcao[] = PACOTES.map((p) => {
    const motivo = motivoDoPacote(p.id, opcoes)
    const falta = motivo ? null : faltamNoPacote(p.id, opcoes)
    return opcao(
      { valor: p.id, rotulo: p.rotulo, detalhe: falta ? `${p.detalhe} · ${falta}` : p.detalhe },
      motivo,
    )
  }).concat(
    pacote === PERSONALIZADO
      ? [
          {
            valor: PERSONALIZADO,
            rotulo: 'Personalizado',
            detalhe: 'as colunas que você escolheu na gaveta',
          },
        ]
      : [],
  )

  const diasDoSeletor = diasOferecidos(hoje, opcoes.retencao)
  const podeBaixar = !impede && !baixando && !vazia(selecao)

  return (
    <>
      <Cartao>
        <Pergunta
          numero="1."
          titulo="O que você quer levar"
          detalhe={
            pacote === PERSONALIZADO
              ? 'Você escolheu as colunas na mão. Abra a gaveta para conferir, ou volte a um pacote.'
              : undefined
          }
        >
          <Combobox
            opcoes={opcoesDePacote}
            valor={pacote}
            onEscolher={trocarPacote}
            className="w-full max-w-md"
            larguraMenu="w-[26rem]"
          />
          <Botao variante="secundario" onClick={() => setAvancado(true)}>
            Escolher coluna por coluna
          </Botao>
        </Pergunta>

        <Pergunta
          numero="2."
          titulo="De quando a quando"
          detalhe={
            <>
              {janela.dias === 1 ? '1 dia' : `${inteiro(janela.dias)} dias`}, de{' '}
              <Num>{dataCurta(inicio)}</Num> a <Num>{dataCurta(fim)}</Num>
              {passo === '1d' ? null : ` · das ${horaInicio} às ${horaFim}`}
            </>
          }
        >
          <Segmentado opcoes={RECORTES} valor={recorte} onEscolher={trocarRecorte} />
          {recorte === 'livre' ? (
            <>
              <span className="text-xs uppercase tracking-wide text-rotulo">de</span>
              <Combobox
                opcoes={diasDoSeletor.filter((o) => o.valor <= ate)}
                valor={de}
                onEscolher={setDe}
                className="w-44"
                larguraMenu="w-72"
              />
              <span className="text-xs uppercase tracking-wide text-rotulo">até</span>
              <Combobox
                opcoes={diasDoSeletor.filter((o) => o.valor >= de)}
                valor={ate}
                onEscolher={setAte}
                className="w-44"
                larguraMenu="w-72"
              />
            </>
          ) : (
            <PassoPeriodo
              rotulo={rotuloDoPeriodo(referencia, recorte)}
              aoVoltar={() => setReferencia(passoNoTempo(referencia, recorte, -1))}
              aoAvancar={() => setReferencia(passoNoTempo(referencia, recorte, 1))}
              podeAvancar={!passaDeHoje(passoNoTempo(referencia, recorte, 1), recorte)}
            />
          )}
        </Pergunta>

        <Pergunta
          numero="3."
          titulo="Com que detalhe"
          detalhe="Cada linha do arquivo é um instante deste tamanho."
        >
          <Combobox
            opcoes={opcoesDePasso(opcoes.limites)}
            valor={passo}
            onEscolher={(v) => setPasso(v as Passo)}
            className="w-full max-w-md"
            larguraMenu="w-[26rem]"
          />
        </Pergunta>
      </Cartao>

      {impede ? <Aviso>{impede.texto}</Aviso> : null}

      {/* A conta é NOSSA e aproximada — por isso o "≈", e por isso ela não impede nada. No
          limiar, o benefício da dúvida é do cliente: a palavra final é do servidor. */}
      {grande && !impede ? (
        <Aviso>
          Este pedido daria ≈ <Num>{inteiro(conta.celulas)}</Num> células — perto do que um
          arquivo aguenta, e o monitoramento pode recusar. Diminua o período, escolha menos
          detalhe, ou baixe menos inversores. Se quiser tentar assim mesmo, pode pedir.
        </Aviso>
      ) : null}

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

      {falha ? <Erro mensagem={falha} aoTentar={() => void baixar()} /> : null}

      <Cartao>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-rotulo">O arquivo</div>
            <div className="mt-1 text-sm text-corpo">
              ≈ <Num className="text-forte">{inteiro(conta.linhas)}</Num> linhas ×{' '}
              <Num className="text-forte">{inteiro(conta.colunas)}</Num> colunas
            </div>
            <p className="mt-1 text-xs text-fraco">
              Uma planilha (.xlsx) com uma aba "Leia-me" que explica cada coluna, a unidade e a
              fonte.
            </p>
          </div>
          <Botao onClick={() => void baixar()} desabilitado={!podeBaixar}>
            {baixando ? 'Preparando…' : 'Baixar planilha'}
          </Botao>
        </div>
      </Cartao>

      <Avancado
        aberta={avancado}
        aoFechar={() => setAvancado(false)}
        opcoes={opcoes}
        selecao={selecao}
        aoTrocar={(s) => {
          setSelecao(s)
          setPacote(PERSONALIZADO)
        }}
        passo={passo}
        horaInicio={horaInicio}
        horaFim={horaFim}
        aoTrocarHoras={(i, f) => {
          setHoraInicio(i)
          setHoraFim(f)
        }}
      />

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
          Não feche esta aba: o download é feito por ela, e fechá-la cancela o pedido.
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
