/**
 * O PAINEL de geração — a mesma resposta que o time de operação lê no meuWatt, recortada
 * para o cliente corporativo.
 *
 * Quatro recortes da MESMA pergunta ("gerei o que era esperado?"), em um controle
 * segmentado: **Dia**, **Mês**, **Ano** e **Unidades**. As unidades consumidoras são um
 * recorte, e não um item de menu, porque a pergunta é a mesma — só a lente muda.
 *
 * Três decisões de tela que não devem ser "simplificadas" depois:
 *
 * **Uma referência só.** Os quatro recortes andam no MESMO ponto do tempo: quem foi ver o
 * dia 12 de março e troca para Mês continua em março. Dois relógios na mesma tela fariam o
 * cliente comparar períodos diferentes sem perceber.
 *
 * **O seletor de mês pula o mês vazio.** A lista de meses com medição vem do painel ANUAL
 * (`meses_disponiveis`) — é assim que o próprio meuWatt faz, o Anual alimentando o seletor
 * do Mensal. Mês sem medição aparece na lista, mas desabilitado e dizendo por quê: sumir
 * com ele esconderia do cliente que aquele mês não foi medido, e deixá-lo clicável abriria
 * uma tela vazia que se lê como falha do portal.
 *
 * **Aqui não se gera PDF.** A aba Relatório do meuWatt (a fábrica de PDF, com os botões de
 * imprimir e salvar) ficou de fora por pedido do dono. Os três documentos consolidados —
 * Geração, Paradas e o Resumo Executivo — o cliente baixa em Relatórios, prontos, sem ter
 * de montar nada.
 *
 * Também ficaram de fora, com motivo: o ranking de causas, o detalhamento parada a parada e
 * o desvio entre inversores (não são do painel — vivem dentro do Anexo de Paradas, que
 * chega em PDF); o derating e a indisponibilidade do PVsyst (são parâmetros de ENTRADA do
 * projeto, não medição do período); e os botões de rolagem do cabeçalho, que são muleta de
 * página longa de operador.
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * CONFERÊNCIA CAMPO A CAMPO contra o dashboard de origem (05/09/2026)
 *
 * Feita bloco a bloco no código do meuWatt — `mw-fe/src/pages/DashboardPage.tsx` e
 * `mw-fe/src/components/DashboardPage/` —, e não de memória: "todas as informações" era,
 * até aqui, autoavaliação de quem construiu. Lá são cinco abas; quatro viraram os quatro
 * recortes daqui, e a quinta (Relatório) é a fábrica de PDF que o dono mandou não trazer.
 *
 *   MENSAL → Mês. Os quatro KPIs de geração (MEDIDO INVERSORES · MEDIDO FRONTEIRA ·
 *   PROJETO PVSYST · PREVISTO METEO) e os quatro de rendimento (PRODUTIVIDADE ·
 *   PERFORMANCE RATIO · DISPONIB. REAL · DISPONIB. CONTRATUAL); a caixa que explica real ×
 *   contratual e a parada ainda não classificada; o `PerdasCard` (nossos "Desvios do
 *   período"); `ConcessionariaMensal` (a conta de energia); GERAÇÃO DIÁRIA com o tracejado
 *   dos dias por vir; PERFORMANCE RATIO DIÁRIO sem barra no dia descartado; DESEMPENHO DO
 *   MÊS / ATÉ HOJE (a rosca); TOTAIS com a tendência; "Condições do mês" (HPOA · GHI ·
 *   TEMP. AMBIENTE · TEMP. MÓDULO) e TEMPERATURA DIA A DIA.
 *   ANUAL → Ano. REALIZADO YTD (e o de fronteira), META YTD e PROJETO ANUAL, os quatro de
 *   rendimento, `ConcessionariaAnual`, GERAÇÃO MENSAL, DETALHAMENTO MENSAL, a Timeline por
 *   inversor com o aviso de disponibilidade TÉCNICA × energética, "Condições do ano",
 *   TEMPERATURA POR MÊS e DETALHAMENTO METEOROLÓGICO MENSAL.
 *   DIÁRIO → Dia. GERAÇÃO DO DIA · PICO · POTÊNCIA AGORA · DISPONIBILIDADE · PR DO DIA;
 *   POTÊNCIA E IRRADIÂNCIA AO LONGO DO DIA; "Condições do dia" (HPOA agora, acumulada e
 *   GHI); UNIDADES CONSUMIDORAS · GERAÇÃO HOJE; e os eventos.
 *   MEDIDORES → Unidades. UCS ATIVAS · CAPACIDADE TOTAL · ENERGIA · MAIOR CONTRIBUINTE;
 *   GERAÇÃO POR DIA DA UC; os três rankings (geração, PR com a referência de 80 %,
 *   produtividade); DISPONIBILIDADE ENERGÉTICA POR UC; e a tabela POR UC com o faturado.
 *
 * A conferência achou UMA coisa de lá que não estava aqui, e ela foi trazida: o
 * `PerdasCard` tem um segundo modo — quando a usina declara POA/GHI de projeto, ele troca
 * as caixas de previsto por **GHI · MEDIDA vs PROJETO** e **POA · MEDIDA vs PROJETO**. É a
 * comparação que separa "o sol não veio" de "a usina não rendeu". Aqui as duas entraram
 * como linhas do cartão de desvios (`hpoa_vs_projeto_pct` e `ghi_vs_projeto_pct`),
 * convivendo com as de energia em vez de substituí-las — e o servidor compara na MESMA
 * janela do medido, senão o dia 15 de todo mês acusaria meio mês de sol contra um mês
 * inteiro de projeto.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import {
  CabecalhoCard,
  Cartao,
  PassoPeriodo,
  Pagina as Casco,
  Segmentado,
  Selo,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { SeletorPeriodo } from '@/components/SeletorPeriodo'
import { competencia } from '@/lib/format'
import {
  MESES,
  competenciaDe,
  competenciaParaIso,
  hojeIso,
  passaDeHoje,
  passo,
  rotuloDoPeriodo,
  type Recorte,
} from '@/lib/periodo'

import {
  ehUsinaAusente,
  useDia,
  usePainel,
  useUnidades,
  useUsinaDetalhe,
  type Aba,
  type RecortePainel,
  type UsinaDetalhe,
} from './api'
import { AbaAno } from './Ano'
import { AbaDia } from './Dia'
import { AbaMes } from './Mes'
import { AbaUnidades } from './Unidades'
import { Bloco, capacidade } from './graficos'

const ABAS: { valor: Aba; rotulo: string }[] = [
  { valor: 'dia', rotulo: 'Dia' },
  { valor: 'mes', rotulo: 'Mês' },
  { valor: 'ano', rotulo: 'Ano' },
  { valor: 'unidades', rotulo: 'Unidades' },
]

const RECORTES_DA_UNIDADE: { valor: RecortePainel; rotulo: string }[] = [
  { valor: 'mes', rotulo: 'No mês' },
  { valor: 'ano', rotulo: 'No ano' },
]

/* ------------------------------------------------------------------ mês */

/**
 * O seletor de mês: passo ‹ ›, lista dos doze meses do ano e o mês vazio DESABILITADO.
 *
 * `disponiveis` nulo significa "ninguém consultou" — e aí tudo o que já aconteceu fica
 * liberado, que é o comportamento honesto: travar por falta de informação seria impedir o
 * cliente de olhar um mês que talvez tenha dado.
 *
 * As setas PULAM o mês vazio quando a lista existe. Sem isso, andar para trás num ano com
 * cinco meses sem medição exigiria cinco cliques que abrem cinco telas vazias.
 */
function SeletorDeMes({
  referencia,
  onReferencia,
  disponiveis,
}: {
  referencia: string
  onReferencia: (iso: string) => void
  disponiveis: string[] | null
}) {
  const [aberto, setAberto] = useState(false)
  const caixa = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!aberto) return
    const fora = (e: MouseEvent) => {
      if (caixa.current && !caixa.current.contains(e.target as Node)) setAberto(false)
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setAberto(false)
    }
    document.addEventListener('mousedown', fora)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', fora)
      document.removeEventListener('keydown', esc)
    }
  }, [aberto])

  const conjunto = disponiveis === null ? null : new Set(disponiveis)
  const temDado = (iso: string) => conjunto === null || conjunto.has(competenciaDe(iso))

  /** O próximo mês com medição naquela direção; nulo quando não há nenhum. */
  const vizinho = (direcao: 1 | -1): string | null => {
    let candidato = passo(referencia, 'mes', direcao)
    // Doze passos cobrem um ano inteiro de meses vazios; além disso o ano muda e o painel
    // anual daquele ano é outra leitura, que a seta não tem como consultar daqui.
    for (let i = 0; i < 12; i += 1) {
      if (passaDeHoje(candidato, 'mes')) return null
      if (temDado(candidato)) return candidato
      candidato = passo(candidato, 'mes', direcao)
    }
    return null
  }

  const anterior = vizinho(-1)
  const proximo = vizinho(1)

  const ano = referencia.slice(0, 4)
  const mesesDoAno = MESES.map((_, i) => `${ano}-${String(i + 1).padStart(2, '0')}`).filter(
    (c) => !passaDeHoje(competenciaParaIso(c), 'mes'),
  )

  return (
    <div ref={caixa} className="relative flex items-center gap-2">
      <PassoPeriodo
        rotulo={rotuloDoPeriodo(referencia, 'mes')}
        aoVoltar={() => {
          if (anterior) onReferencia(anterior)
        }}
        aoAvancar={() => {
          if (proximo) onReferencia(proximo)
        }}
        podeAvancar={proximo !== null}
      />
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-label="Escolher o mês"
        className="min-h-[38px] rounded-campo border border-borda bg-superficie px-3 text-sm text-corpo hover:bg-superficie-alta"
      >
        Escolher mês ▾
      </button>

      {aberto ? (
        <div className="absolute right-0 top-full z-30 mt-1 w-64 overflow-hidden rounded-card border border-borda-forte bg-painel shadow-xl">
          <ul className="max-h-80 overflow-auto py-1">
            {mesesDoAno.map((c) => {
              const iso = competenciaParaIso(c)
              const habilitado = temDado(iso)
              const escolhido = competenciaDe(referencia) === c
              return (
                <li key={c}>
                  <button
                    type="button"
                    disabled={!habilitado}
                    onClick={() => {
                      onReferencia(iso)
                      setAberto(false)
                    }}
                    className={`block w-full px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-40 ${
                      escolhido ? 'text-ambar-texto' : 'text-corpo'
                    } ${habilitado ? 'hover:bg-superficie-alta' : ''}`}
                  >
                    <span className="block">{competencia(c)}</span>
                    {habilitado ? null : (
                      <span className="block text-xs text-fraco">sem medição neste mês</span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------ página */

export default function PainelDeEnergia() {
  const { id } = useParams<{ id: string }>()
  const idUsina = Number(id)
  const valida = Number.isFinite(idUsina) && idUsina > 0

  const [aba, setAba] = useState<Aba>('mes')
  const [recorteUnidades, setRecorteUnidades] = useState<RecortePainel>('mes')
  const [referencia, setReferencia] = useState<string>(hojeIso())

  const usina = useUsinaDetalhe(idUsina, valida)

  const painelMes = usePainel(idUsina, 'mes', referencia, valida && aba === 'mes')
  /**
   * O painel do ANO serve a duas coisas com UMA leitura: é o conteúdo da aba Ano e é a
   * fonte de `meses_disponiveis` para o seletor de mês. A chave de cache normaliza a
   * referência para 1º de janeiro (ver `referenciaDoRecorte`), então andar de agosto para
   * setembro não repete o pedido — o ano é o mesmo.
   */
  const painelAno = usePainel(idUsina, 'ano', referencia, valida && aba !== 'dia')
  const dia = useDia(idUsina, referencia, valida && aba === 'dia')
  const unidades = useUnidades(
    idUsina,
    recorteUnidades,
    referencia,
    valida && aba === 'unidades',
  )

  const disponiveis = painelAno.dados?.meses_disponiveis ?? null

  /** Qual passo de período a aba pede. As unidades herdam o do próprio recorte. */
  const recortePasso: Recorte = useMemo(() => {
    if (aba === 'dia') return 'dia'
    if (aba === 'ano') return 'ano'
    if (aba === 'mes') return 'mes'
    return recorteUnidades
  }, [aba, recorteUnidades])

  if (!valida) {
    return (
      <Casco titulo="Painel">
        <Vazio
          titulo="Usina não encontrada"
          descricao="O endereço não aponta para uma usina. Escolha uma usina na barra do topo."
        />
      </Casco>
    )
  }

  // 404 do BFF (fora do escopo, ou usina sem monitoramento): vazio que explica, nunca erro
  // vermelho com "Tentar de novo" — repetir não faz a usina aparecer.
  if (ehUsinaAusente(usina)) {
    return (
      <Casco titulo="Painel">
        <Vazio titulo="Usina não encontrada" descricao={usina.erro ?? undefined} />
      </Casco>
    )
  }

  const nome = usina.dados?.nome
  const local = [usina.dados?.cidade, usina.dados?.uf].filter(Boolean).join(', ')

  return (
    <Casco
      titulo={nome ?? 'Painel'}
      subtitulo={
        <>
          Geração de energia · Painel
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
            {/* Os controles ficam SEMPRE visíveis, inclusive enquanto a leitura chega:
                escondê-los faria o cliente perder o lugar a cada passo no tempo. */}
            <Cartao>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Segmentado opcoes={ABAS} valor={aba} onEscolher={setAba} />
                <div className="flex flex-wrap items-center gap-2">
                  {aba === 'unidades' ? (
                    <Segmentado
                      opcoes={RECORTES_DA_UNIDADE}
                      valor={recorteUnidades}
                      onEscolher={setRecorteUnidades}
                    />
                  ) : null}
                  {recortePasso === 'mes' ? (
                    <SeletorDeMes
                      referencia={referencia}
                      onReferencia={setReferencia}
                      disponiveis={disponiveis}
                    />
                  ) : (
                    <SeletorPeriodo
                      recorte={recortePasso}
                      referencia={referencia}
                      onReferencia={setReferencia}
                      recortes={[recortePasso]}
                    />
                  )}
                </div>
              </div>
              {/* O aviso da usina (do BFF) vale para todos os recortes — mora aqui, não
                  repetido em cada aba. */}
              {u.aviso ? <p className="mt-3 text-sm text-tom-alerta">{u.aviso}</p> : null}
            </Cartao>

            {aba === 'dia' ? (
              <Bloco leitura={dia} altura={280}>
                {(d) => <AbaDia dia={d} />}
              </Bloco>
            ) : null}

            {aba === 'mes' ? (
              <Bloco leitura={painelMes} altura={280}>
                {(p) => <AbaMes painel={p} />}
              </Bloco>
            ) : null}

            {aba === 'ano' ? (
              <Bloco leitura={painelAno} altura={280}>
                {(p) => <AbaAno painel={p} />}
              </Bloco>
            ) : null}

            {aba === 'unidades' ? (
              <Bloco leitura={unidades} altura={280}>
                {(dados) => <AbaUnidades unidades={dados} />}
              </Bloco>
            ) : null}

            {/* Um lembrete curto, no pé: o que esta tela NÃO faz, para o cliente não
                procurar aqui o que está em Relatórios. */}
            <Cartao>
              <CabecalhoCard rotulo="Os documentos do período" />
              <p className="text-sm text-fraco">
                Este painel mostra a operação; ele não monta documento. O relatório de geração,
                o anexo de paradas e o resumo executivo do fechamento ficam em{' '}
                <strong className="text-corpo">Relatórios</strong>, prontos para baixar.
              </p>
            </Cartao>
          </>
        )}
      </Tela4Estados>
    </Casco>
  )
}
