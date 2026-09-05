/**
 * Cronograma — O que o contrato prevê mês a mês foi feito?
 *
 * É o "X" que o dono descreveu: uma linha por atividade do contrato, doze colunas de mês, e
 * em cada cruzamento a marca do que aconteceu. A tela responde UMA pergunta — está sendo
 * feito? — e por isso não mostra medição, checklist nem equipamento: quem quiser descer até
 * o laudo abre a tarefa e, de lá, o PDF.
 *
 * **A matriz deixou de ser a primeira coisa.** Ela abria com quinze cabeçalhos de bloco
 * cinza-chapado, recolhidos, e as doze colunas de mês vazias: 94 % da altura da tabela era
 * um bloco cinza e nenhuma das 269 marcas do contrato aparecia — nem o mês que fechou 13 de
 * 13. Agora a tela responde na ordem em que o cliente pergunta: **o veredito** ("em dia" ou
 * a atrasada mais antiga), **a fita dos doze meses**, **o que está acontecendo neste mês** e,
 * por último, **a matriz inteira atrás de um clique**, como UM bloco. O "X" não saiu; ele
 * virou o detalhe, que é o lugar dele.
 *
 * Cinco decisões que não podem se perder numa refatoração:
 *
 * **Os meses são os do CONTRATO.** A ordem vem de `meses` (a âncora da vigência), então um
 * contrato que começa em março abre em "mar/26". Desenhar janeiro→dezembro entregaria um
 * cronograma que não é o que foi assinado — e é por isso que "hoje" também vem do servidor
 * (`mes_referencia`), nunca do relógio do navegador.
 *
 * **O número grande é o "até aqui".** `cumprido_ate_hoje / previsto_ate_hoje` — o recorte de
 * vigência, calculado no meuPlano. O total do ano (`previsto_no_contrato`) fica como contexto
 * pequeno, e não como denominador: foi dividir por um ano que ainda não aconteceu que fez a
 * mesma usina, sem uma única atividade atrasada, aparecer como "13 de 270" (4,8 %) numa tela
 * e "41,9 %" na outra. A tela não faz aritmética nenhuma com estes campos.
 *
 * **Feito ≠ dispensado.** O X cheio é executado; o X vazado com "D" é dispensa registrada
 * com motivo. Fundir os dois faria o cliente ler "cumprido" onde a equipe registrou "não
 * precisou desta vez" — a distinção é do meuPlano e sobrevive até aqui.
 *
 * **Sem consolidação, a tela DIZ isso.** Contrato só com rascunho responde 200 com a matriz
 * vazia e a frase do servidor. Desenhar uma grade em branco seria pior que não desenhar
 * nada: lê-se como "nada foi feito", que é uma acusação — e não é o que o dado diz.
 *
 * **A célula abre.** Clicar num mês previsto — na grade ou nas listas do mês — mostra as
 * tarefas por trás daquele X, com a porta para a OS que as executou.
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
  FaixaAtencao,
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
import FitaDosMeses, { type MesDaFita } from '@/features/cronograma/FitaDosMeses'
import {
  atividadesDoMes,
  atrasadasPorMes,
  caminhoPdfCronograma,
  chaveContratos,
  chaveCronograma,
  chaveTarefasDoMes,
  mesDeReferencia,
  primeiraAtrasada,
  rotuloDoContrato,
  tomDaCelula,
  totalAtrasadas,
  type Celula,
  type Contrato,
  type ContratosOut,
  type CronogramaOut,
  type ItemDoMes,
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

  // Mês sem previsão fica VAZIO — na tela E na leitura por voz. A marca cinza se leria
  // como "pendente"; e o texto invisível "Sem previsão", que estava aqui, repetia dez vezes
  // por linha numa atividade semestral, enchendo a grade de ruído sem acrescentar nada que
  // a legenda ("célula vazia = o contrato não prevê nada no mês") já não diga uma vez só.
  return null
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
  // Um bloco só não é agrupamento: abre inteiro, sem cabeçalho que não separa nada. E o
  // bloco que TEM movimento (algo executado, dispensado ou atrasado) abre sozinho: quinze
  // cabeçalhos cinza fechados sobre doze colunas vazias foi exatamente o que o dono viu, e
  // esconder justo as linhas que respondem "o que foi feito?" é o pior corte possível. O
  // bloco parado continua recolhido — ele é contexto, não notícia.
  const [abertos, setAbertos] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      grupos.map((g) => [
        g.nome,
        grupos.length <= 1 ||
          g.linhas.some(
            (l) => l.feitos > 0 || l.meses.some((c) => c.atrasado || c.dispensado),
          ),
      ]),
    ),
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
            <tr className="border-b border-borda bg-superficie-alta">
              <td colSpan={dados.meses.length + 2} className="p-0">
                <button
                  type="button"
                  onClick={() => alternar(grupo.nome)}
                  aria-expanded={Boolean(abertos[grupo.nome])}
                  className="flex w-full items-center gap-2 px-4 py-2 text-left transition hover:bg-superficie-destacada"
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

/* ------------------------------------------------------------------ o veredito */

/**
 * A primeira frase da tela: **estou em dia?**
 *
 * "13 de 270" não responde isso — foi exatamente esse par que fez a mesma usina, sem uma
 * única atividade atrasada, parecer 4,8 % cumprida. A pergunta do cliente é binária, e a
 * resposta binária mora nas atividades ATRASADAS, que independem do tamanho do contrato.
 *
 * Quando há atraso, o número sozinho não move ninguém: a faixa nomeia a mais antiga e o mês
 * dela, e clicar abre as tarefas daquele X. Quando não há, a faixa diz isso com todas as
 * letras — silêncio se leria como "a tela não sabe".
 */
function Veredito({
  dados,
  aoAbrirCelula,
}: {
  dados: CronogramaOut
  aoAbrirCelula: (celula: CelulaAberta) => void
}) {
  const atrasadas = totalAtrasadas(dados.linhas)
  if (atrasadas === 0) {
    return (
      <FaixaAtencao
        tom="ok"
        titulo="Em dia — nenhuma atividade atrasada"
        detalhe={
          dados.mes_referencia
            ? `Conferido até ${competencia(dados.mes_referencia)}. O que ainda não venceu não é cobrança.`
            : 'Nenhuma atividade do contrato passou do mês previsto.'
        }
      />
    )
  }

  const maisAntiga = primeiraAtrasada(dados)
  const planItemId = maisAntiga === null ? null : maisAntiga.planItemId
  const abrir =
    maisAntiga !== null && planItemId !== null
      ? () => aoAbrirCelula({ planItemId, nome: maisAntiga.nome, mes: maisAntiga.mes })
      : undefined

  return (
    <FaixaAtencao
      tom="parado"
      titulo={`${inteiro(atrasadas)} ${atrasadas === 1 ? 'atividade atrasada' : 'atividades atrasadas'}`}
      detalhe={
        maisAntiga ? (
          <>
            A mais antiga é <strong className="font-medium">{maisAntiga.nome}</strong>, prevista
            para {competencia(maisAntiga.mes)}.
          </>
        ) : undefined
      }
      aoAbrir={abrir}
    />
  )
}

/* ------------------------------------------------------------------ a fita dos meses */

/**
 * Os doze meses prontos para a fita.
 *
 * `previsto`/`cumprido`/`situacao` são do SERVIDOR (`meses_estado`, o recorte de vigência do
 * meuPlano). As ATRASADAS vêm da matriz, porque é a única fonte que as localiza por mês — e
 * é a mesma fonte que pinta a célula de vermelho, então a fita e a grade concordam por
 * construção. Sem `meses_estado` a fita simplesmente não existe: classificar mês em
 * fechado/corrente/futuro aqui seria adivinhar a âncora do contrato pelo relógio.
 */
function fitaDosMeses(dados: CronogramaOut): MesDaFita[] {
  const estados = dados.meses_estado ?? []
  if (estados.length === 0) return []
  const atrasos = atrasadasPorMes(dados.linhas)
  return estados.map((m) => {
    const n = atrasos.get(m.mes)
    return {
      mes: m.mes,
      situacao: m.situacao,
      previsto: m.previsto,
      cumprido: m.cumprido,
      atrasadas: n === undefined ? 0 : n,
    }
  })
}

/* ------------------------------------------------------------------ as listas do mês */

/** Uma linha das duas listas do mês — abre as mesmas tarefas que a célula da grade abriria. */
function LinhaDoMes({
  item,
  aoAbrirCelula,
}: {
  item: ItemDoMes
  aoAbrirCelula: (celula: CelulaAberta) => void
}) {
  const planItemId = item.planItemId
  const conteudo = (
    <>
      <Marca celula={item.celula} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-corpo">{item.nome}</span>
        <span className="block truncate text-xs text-fraco">
          {item.grupo}
          {item.celula.dispensado ? ' · dispensada com motivo' : ''}
          {item.celula.atrasado ? ' · atrasada' : ''}
        </span>
      </span>
    </>
  )
  if (planItemId === null) {
    // Sem item de plano não há como perguntar quais tarefas estão atrás do X: a linha fica,
    // porque o dado é verdadeiro, mas não finge ser um botão. Clique morto é pior que texto.
    return <li className="flex items-start gap-3 py-2">{conteudo}</li>
  }
  return (
    <li>
      <button
        type="button"
        onClick={() => aoAbrirCelula({ planItemId, nome: item.nome, mes: item.celula.mes })}
        className="flex w-full items-start gap-3 rounded-campo px-1 py-2 text-left transition hover:bg-superficie-alta"
      >
        {conteudo}
      </button>
    </li>
  )
}

/**
 * O agora, em duas colunas: **o que já foi feito** × **o que ainda está previsto** no mês de
 * referência.
 *
 * É a única parte da tela que o cliente usa sem abrir nada: as poucas atividades do mês
 * corrente cabem na tela, ao contrário das 94 linhas do contrato inteiro.  O mês vem do
 * SERVIDOR (`mes_referencia`) — deduzi-lo do relógio apontaria para a coluna errada num
 * contrato que não começa em janeiro.
 *
 * Lista vazia não some: ela diz por que está vazia. "Nada previsto para este mês" é uma
 * resposta legítima do contrato, e um espaço em branco no lugar dela se lê como falha.
 */
function ListasDoMes({
  dados,
  mes,
  aoAbrirCelula,
}: {
  dados: CronogramaOut
  mes: string
  aoAbrirCelula: (celula: CelulaAberta) => void
}) {
  const { feitas, previstas } = atividadesDoMes(dados, mes)
  const coluna = (titulo: string, itens: ItemDoMes[], vazio: string) => (
    <Cartao>
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-rotulo">{titulo}</h2>
        <span className="text-xs text-fraco">
          <Num>{inteiro(itens.length)}</Num>
        </span>
      </div>
      {itens.length === 0 ? (
        <p className="py-2 text-sm text-fraco">{vazio}</p>
      ) : (
        <ul className="divide-y divide-borda-fraca">
          {itens.map((item, i) => (
            <LinhaDoMes
              key={item.planItemId === null ? `sem-plano-${i}` : item.planItemId}
              item={item}
              aoAbrirCelula={aoAbrirCelula}
            />
          ))}
        </ul>
      )}
    </Cartao>
  )
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {coluna(
        `Feito em ${competencia(mes)}`,
        feitas,
        'Nada registrado neste mês ainda — executadas e dispensadas apareceriam aqui.',
      )}
      {coluna(
        `Previsto para ${competencia(mes)}`,
        previstas,
        'Nada previsto para este mês neste contrato.',
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ a matriz, recolhida */

/**
 * A matriz inteira, atrás de um clique, como UM bloco.
 *
 * Ela nasce FECHADA de propósito. Aberta, são 94 linhas de ensaio — "Medição do TTR",
 * "Resistência das bobinas", "Isolação CC" —, que é a análise de equipamento que o dono
 * disse que o cliente corporativo não quer ver de saída. Fechada, quem precisa do "X"
 * continua a um clique dele, e quem só quer saber se está sendo feito já leu a resposta três
 * blocos acima.
 *
 * Fechada quer dizer NÃO MONTADA — sem tabela no DOM, e não uma tabela escondida por CSS.
 * São mais de mil células que o navegador montaria antes de a primeira frase aparecer.
 */
function MatrizInteira({
  dados,
  aoAbrirCelula,
}: {
  dados: CronogramaOut
  aoAbrirCelula: (celula: CelulaAberta) => void
}) {
  // ABERTA por padrão. Fechada, a tela ficava com um veredito, um número e um botão — e o
  // cliente que quer "ver o que foi feito" tinha de descobrir que havia mais um clique. O
  // botão continua, para recolher quando a grade atrapalha.
  const [aberta, setAberta] = useState(true)
  const linhas = dados.linhas.length
  return (
    <Cartao semPadding>
      <button
        type="button"
        onClick={() => setAberta((v) => !v)}
        aria-expanded={aberta}
        className="flex w-full items-center gap-2 px-5 py-4 text-left transition hover:bg-superficie-alta"
      >
        <span aria-hidden className="text-fraco">
          {aberta ? '⌄' : '›'}
        </span>
        {/* Rótulo ESTÁVEL: quem diz o estado é o chevron e o `aria-expanded`. Um título que
            troca de palavra ao abrir some do olho de quem procurava a seção pelo nome. */}
        <span className="text-sm font-medium text-forte">Cronograma inteiro</span>
        <span className="text-xs text-fraco">
          <Num>{inteiro(linhas)}</Num> {linhas === 1 ? 'atividade' : 'atividades'} ·{' '}
          <Num>{inteiro(dados.meses.length)}</Num> meses
        </span>
      </button>
      {aberta ? (
        <div className="border-t border-borda">
          <div className="px-5 py-3">
            <Legenda />
          </div>
          <Grade dados={dados} aoAbrirCelula={aoAbrirCelula} />
        </div>
      ) : null}
    </Cartao>
  )
}

/* ------------------------------------------------------------------ o número grande */

/**
 * O número grande — e de QUE JANELA ele fala.
 *
 * Há duas perguntas parecidas e elas não são a mesma: "quanto já foi cumprido do que já
 * VENCEU" (o recorte de vigência, `cumprido_ate_hoje / previsto_ate_hoje`, calculado no
 * meuPlano) e "quanto já foi cumprido do ANO INTEIRO" (`feitos_ano / previsto_ano`, a soma
 * da matriz que está logo abaixo na tela). A primeira é a boa, e é a que o cartão mostra
 * quando o servidor a publica.
 *
 * O que este bloco resolve é o outro caso. Enquanto o recorte não chega, a tela escrevia um
 * travessão — com 94 linhas, 269 células e 13 X verdes na mão, logo abaixo. Travessão é para
 * ausência de dado, não para dado que ainda não foi resumido: agora ela responde pela
 * matriz, e o rótulo TROCA junto ("no ano", não "até aqui"), porque um número respondendo a
 * outra pergunta com o rótulo da primeira é exatamente como nasceram os dois números
 * discordantes que este projeto já pagou caro.
 *
 * A tela continua sem dividir nada: `pct_ate_hoje` é do servidor, e no caso do ano nenhum
 * percentual é impresso — inventá-lo aqui daria uma terceira resposta.
 */
type ResumoDoTopo = {
  rotulo: string
  valor: string
  detalhe: ReactNode
}

function resumoDoTopo(d: CronogramaOut): ResumoDoTopo {
  const cumprido = d.cumprido_ate_hoje
  const previsto = d.previsto_ate_hoje
  const total =
    d.previsto_no_contrato === null || d.previsto_no_contrato === undefined
      ? d.previsto_ano
      : d.previsto_no_contrato

  if (cumprido !== null && cumprido !== undefined) {
    return {
      rotulo: 'Atividades cumpridas até aqui',
      valor:
        previsto === null || previsto === undefined
          ? inteiro(cumprido)
          : `${inteiro(cumprido)} de ${inteiro(previsto)}`,
      detalhe: (
        <>
          <span className="block">
            {d.mes_referencia ? `até ${competencia(d.mes_referencia)} · ` : ''}
            executadas e dispensadas
          </span>
          <span className="block">
            <Num>{inteiro(total)}</Num> previstas no contrato
            {d.pct_ate_hoje === null || d.pct_ate_hoje === undefined ? null : (
              <>
                {' · '}
                <Num>{porcento(d.pct_ate_hoje, 1)}</Num> do que já venceu
              </>
            )}
          </span>
        </>
      ),
    }
  }

  return {
    rotulo: 'Atividades cumpridas no ano',
    valor: `${inteiro(d.feitos_ano)} de ${inteiro(d.previsto_ano)}`,
    detalhe: (
      <>
        <span className="block">somadas da grade inteira, o ano do contrato</span>
        <span className="block">
          inclui os meses que ainda nem venceram — o servidor não publicou o recorte por
          vigência deste contrato
        </span>
      </>
    ),
  }
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
          {(d) => {
            const fita = fitaDosMeses(d)
            const resumo = resumoDoTopo(d)
            const agora = mesDeReferencia(d)
            // Sem versão consolidada NÃO se desenha grade: a frase é do servidor, e ela diz
            // "ainda não foi publicado" — nunca "nada foi feito".
            return d.status === null || d.linhas.length === 0 ? (
              <Vazio
                titulo="Cronograma ainda não publicado"
                descricao={
                  d.aviso ?? 'A equipe ainda não publicou o cronograma consolidado deste contrato.'
                }
              />
            ) : (
              <>
                {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}

                <Veredito dados={d} aoAbrirCelula={setCelulaAberta} />

                <Cartao>
                  <div className="flex flex-wrap items-end justify-between gap-4">
                    <Kpi
                      rotulo={resumo.rotulo}
                      valor={resumo.valor}
                      detalhe={resumo.detalhe}
                      tamanho="grande"
                    />
                    <AtualizadoAs
                      em={cronograma.atualizadoEm}
                      offlineDesde={cronograma.offlineDesde}
                    />
                  </div>

                  {fita.length > 0 ? (
                    <div className="mt-5">
                      <FitaDosMeses meses={fita} />
                    </div>
                  ) : (
                    <p className="mt-4 text-sm text-fraco">
                      O servidor ainda não publicou o recorte por mês deste contrato: o
                      número acima é a soma da grade inteira, que está logo abaixo.
                    </p>
                  )}
                </Cartao>

                {agora === null ? null : (
                  <ListasDoMes dados={d} mes={agora} aoAbrirCelula={setCelulaAberta} />
                )}

                <MatrizInteira dados={d} aoAbrirCelula={setCelulaAberta} />
              </>
            )
          }}
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
