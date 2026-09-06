/**
 * O relatório mensal de manutenção — **o documento que o cliente leva à diretoria**.
 *
 * É o fechamento do mês: apurado no meuPlano, conferido, aprovado e LIBERADO pela equipe de
 * manutenção. Um mês publicado traz dois documentos, e eles não são duas versões da mesma
 * coisa — são dois PDFs, escritos por dois motores, para dois leitores: o **executivo** (o
 * resumo de cinco minutos, e por isso o primeiro) e o **técnico** (o laudo, com o cronograma,
 * as ordens e as fichas). Nada aqui se chama "modo" ou "versão".
 *
 * **Por que este bloco vem ANTES de "Consultar um período".** A pergunta do título da tela é
 * "o que eu levo para a diretoria?", e quem responde a ela é o documento que a equipe
 * assinou e entregou — não uma leitura montada agora. O bloco vizinho continua valendo (é a
 * única resposta possível para "e setembro, como vai?", porque setembro ainda não fechou),
 * mas passa a se chamar pelo que é.
 *
 * **Os dois não se contradizem — mas podem divergir com o tempo, e a tela diz isso.** As
 * contas saem da MESMA apuração no meuPlano; a diferença é que este documento congelou no
 * fechamento e o outro relê o ativo a cada abertura. Um cliente que abra os dois em janeiro
 * verá números diferentes de agosto, e o carimbo de cada um (aqui, "publicado em"; lá,
 * "montado agora") é o que explica que a diferença é o TEMPO.
 *
 * **O corte é do servidor, inteiro.** Aqui só chega o que a equipe LIBEROU — nem o que está
 * apenas aprovado, que ainda pode voltar para revisão. O portal não conhece outra porta e
 * não reimplementa régua nenhuma: se um rascunho um dia aparecer nesta lista, é defeito do
 * upstream, não escolha desta tela.
 *
 * **Vazio nasce com frase.** A lista vem vazia hoje na maioria das usinas, e a razão é de
 * produto (o fechamento existe e ainda não foi liberado), não de rede. Quem sabe o porquê é
 * o BFF, que sabe qual mês foi pedido — a tela repete a frase dele em vez de escrever a
 * sua, que seria um palpite.
 *
 * **Nada de link comum.** O PDF sai por `fetch` + Bearer + blob (`abrirPdf`), como todo
 * arquivo deste portal: token em endereço entra em log e em histórico.
 */

import { useMemo, useState } from 'react'

import { Aviso, Botao, CabecalhoCard, Cartao, Combobox, Tela4Estados, Vazio } from '@/components/base'
import { competencia, dataPorExtenso } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import { competenciaDe, hojeIso, passoCompetencia } from '@/lib/periodo'
import {
  caminhoPdfDoRelatorioMensal,
  chaveRelatoriosMensais,
  nomeDoPdfDoRelatorioMensal,
  DETALHE_DO_TIPO_MENSAL,
  NOME_DO_TIPO_MENSAL,
  type RelatorioMensal as Mensal,
  type RelatoriosMensaisOut,
} from '@/features/relatorios/api'
import { useBaixarPdf } from '@/features/relatorios/RelatorioManutencao'

/**
 * O sentinela do seletor: "todos os meses". Não é a ausência de escolha — é uma escolha
 * legítima, e é a inicial. Um `Combobox` com valor nulo apareceria com o texto de
 * espera-reservada, como se ninguém tivesse decidido nada.
 */
const TODOS = 'todos'

/** Quantos meses o seletor oferece para trás. Um ano cobre o ciclo de um contrato de O&M. */
const MESES_OFERECIDOS = 12

/**
 * O prazo do PDF. Generoso de propósito: o documento é montado no meuPlano a cada pedido
 * (medido lá: 0,9 s a 2,9 s, e a primeira chamada de uma sessão fria já passou disso), e um
 * tempo-limite que dispare antes da resposta acusaria a internet do cliente por um arquivo
 * que estava vindo.
 */
const PRAZO_DO_PDF_MS = 120_000

/** As competências de hoje para trás, do mês corrente ao mais antigo oferecido. */
function competenciasAte(quantas: number): string[] {
  const lista: string[] = []
  let mes = competenciaDe(hojeIso())
  for (let i = 0; i < quantas; i += 1) {
    lista.push(mes)
    mes = passoCompetencia(mes, -1)
  }
  return lista
}

/**
 * Os relatórios agrupados pelo mês que fecham, **preservando a ordem do servidor**.
 *
 * Um `Map` porque ele guarda a ordem de inserção: percorrer a lista como veio já entrega os
 * meses do mais recente para o mais antigo e, dentro de cada um, o executivo antes do
 * técnico. Reordenar aqui seria escrever pela segunda vez uma regra que já existe — e é
 * assim que duas telas do mesmo produto passam a discordar.
 */
function porCompetencia(itens: Mensal[]): [string, Mensal[]][] {
  const mapa = new Map<string, Mensal[]>()
  for (const item of itens) {
    const lista = mapa.get(item.competencia)
    if (lista) lista.push(item)
    else mapa.set(item.competencia, [item])
  }
  return Array.from(mapa.entries())
}

type Baixador = ReturnType<typeof useBaixarPdf>

/**
 * Uma LINHA do cartão — um documento.
 *
 * A data é uma só, e é `liberado_em`, rotulada "publicado". Ela vive na linha (e não no
 * cabeçalho do mês) porque é do DOCUMENTO: o executivo e o técnico do mesmo mês podem ter
 * sido entregues em momentos diferentes, e uma data só para os dois afirmaria uma coisa que
 * ninguém disse. As outras três que o meuPlano guarda — quem aprovou, quando aprovou e
 * quando apurou — não chegam a este portal: a primeira é nome de funcionário da executora,
 * e as outras respondem "quando os números foram calculados", que não é a pergunta "de
 * quando é este documento".
 */
function LinhaDoRelatorio({
  r,
  usina,
  pdf,
}: {
  r: Mensal
  usina: string
  pdf: Baixador
}) {
  const marca = `mensal-${r.id}`
  // Tipo que este portal não conhece aparece com o código cru do servidor. Sumir da tela
  // por ser novo é o defeito: o dia em que o meuPlano criar um terceiro documento, ele tem
  // de estar aqui — ainda que sem nome bonito.
  const nome = NOME_DO_TIPO_MENSAL[r.tipo] ?? r.tipo
  const detalhe = DETALHE_DO_TIPO_MENSAL[r.tipo] ?? null

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <h4 className="truncate text-sm font-medium text-forte">{nome}</h4>
        {detalhe === null ? null : <p className="mt-0.5 text-xs text-fraco">{detalhe}</p>}
        <p className="mt-0.5 text-xs text-fraco">publicado em {dataPorExtenso(r.liberado_em)}</p>
      </div>
      <Botao
        variante="secundario"
        desabilitado={pdf.baixando !== null}
        onClick={() =>
          pdf.baixar(
            marca,
            caminhoPdfDoRelatorioMensal(r.id),
            nomeDoPdfDoRelatorioMensal(usina, r.tipo, r.competencia),
            PRAZO_DO_PDF_MS,
          )
        }
      >
        {pdf.baixando === marca ? 'Abrindo…' : 'Baixar PDF'}
      </Botao>
    </div>
  )
}

/** O cartão de um mês publicado: o cabeçalho é a competência, e dentro vêm os documentos. */
function CartaoDoMes({
  mes,
  itens,
  usina,
  pdf,
}: {
  mes: string
  itens: Mensal[]
  usina: string
  pdf: Baixador
}) {
  return (
    <Cartao>
      <CabecalhoCard rotulo={competencia(mes)} />
      <div className="divide-y divide-borda">
        {itens.map((r) => (
          <LinhaDoRelatorio key={r.id} r={r} usina={usina} pdf={pdf} />
        ))}
      </div>
    </Cartao>
  )
}

export function RelatorioMensal({ usinaId }: { usinaId: number }) {
  // `null` = todos os meses, e é o começo: o cliente que abre a tela quer ver o que existe,
  // não escolher um mês para depois descobrir que não há nada nele.
  const [mes, setMes] = useState<string | null>(null)
  const pdf = useBaixarPdf()

  const leitura = useLeitura<RelatoriosMensaisOut>(chaveRelatoriosMensais(usinaId, mes))

  const opcoes = useMemo(
    () => [
      { valor: TODOS, rotulo: 'Todos os meses publicados' },
      ...competenciasAte(MESES_OFERECIDOS).map((c) => ({ valor: c, rotulo: competencia(c) })),
    ],
    [],
  )

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-forte">Relatórios do mês</h2>
        <p className="text-sm text-fraco">
          O fechamento que a equipe de manutenção aprovou e entregou. Cada mês publicado traz o
          relatório executivo e o técnico.
        </p>
      </div>

      <Cartao>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-rotulo">mês</span>
          {/* Lista suspensa pesquisável, nunca uma fileira de botões: escolher opção neste
              produto se faz assim, com 2 opções ou com 200. */}
          <Combobox
            opcoes={opcoes}
            valor={mes ?? TODOS}
            onEscolher={(v) => setMes(v === TODOS ? null : v)}
            placeholder="Escolher mês…"
            className="w-64"
          />
        </div>
      </Cartao>

      {/* A falha do download é FAIXA na tela: popup nativo é proibido, e um clique que não
          responde nada se lê como portal quebrado. */}
      {pdf.erro === null ? null : <Aviso tom="parado">{pdf.erro}</Aviso>}

      <Tela4Estados leitura={leitura}>
        {(dados) =>
          dados.itens.length === 0 ? (
            <Vazio
              titulo="Nenhum relatório publicado"
              // A frase é do SERVIDOR — só ele sabe se o mês pedido não existe ou se o
              // fechamento dele ainda não saiu da equipe. Escrever a nossa aqui mandaria o
              // cliente procurar o problema no lugar errado.
              descricao={
                dados.aviso ??
                'Assim que a equipe de manutenção liberar o fechamento de um mês, ele aparece aqui.'
              }
            />
          ) : (
            <div className="space-y-4">
              {porCompetencia(dados.itens).map(([competenciaDoMes, doMes]) => (
                <CartaoDoMes
                  key={competenciaDoMes}
                  mes={competenciaDoMes}
                  itens={doMes}
                  usina={dados.usina}
                  pdf={pdf}
                />
              ))}
            </div>
          )
        }
      </Tela4Estados>
    </section>
  )
}
