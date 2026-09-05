/**
 * O contrato do Cronograma, como o BFF o entrega.
 *
 * Espelha `bff/app/api/v1/manutencao.py` (`ContratosOut`, `CronogramaOut`, `TarefaOut`) —
 * nada é calculado aqui. As duas leituras que sustentam a tela:
 *
 * - `GET /api/v1/manutencao/contratos?usina_id=` — o seletor de contrato, com a versão
 *   CONSOLIDADA de cada um (`versao_cronograma` nulo = a equipe ainda não publicou);
 * - `GET /api/v1/manutencao/cronograma?usina_id=&contrato_id=` — a matriz. Só a versão
 *   consolidada chega aqui: o BFF lê a rota de cliente do meuPlano, que não serve rascunho.
 *
 * Duas coisas que a tela NÃO pode reinventar, e por isso viram tipo e não regra local:
 *
 * **Os meses vêm na ordem do contrato.** `meses` é a lista de 12 rótulos "YYYY-MM" a partir
 * da ÂNCORA da vigência — um contrato que começa em março abre em "mar/26". Desenhar
 * janeiro→dezembro produziria um cronograma que não é o do contrato.
 *
 * **Feito ≠ dispensado.** O meuPlano distingue `verde` (executado) de `verde_ressalva`
 * (dispensado com motivo registrado) de propósito, e apagar a diferença era exatamente o
 * risco que ele recusou correr — o cliente leria "cumprido" onde a equipe registrou "não
 * precisou desta vez". Aqui as duas chegam em campos separados (`feito`, `dispensado`) e são
 * desenhadas com marcas diferentes.
 */

import type { Tom } from '@/lib/tons'

/* ------------------------------------------------------------------ contratos */

export type Contrato = {
  /** Id do container no meuPlano — é o `contrato_id` que as rotas aceitam. */
  id: number
  numero: number | null
  titulo: string | null
  inicio: string | null
  fim: string | null
  /** Nulo = o meuPlano não soube dizer (contrato sem vigência cadastrada). */
  vigente: boolean | null
  /** Versão do cronograma CONSOLIDADO. Nulo = só rascunho, ou nenhum. */
  versao_cronograma: number | null
}

export type ContratosOut = {
  usina: string
  usina_id: number
  contratos: Contrato[]
  aviso: string | null
}

/* ------------------------------------------------------------------ cronograma */

export type Celula = {
  /** "YYYY-MM" — o mesmo rótulo da coluna. */
  mes: string
  /** Quantas ocorrências o contrato prevê neste mês. 0 = mês vazio na matriz. */
  previsto: number
  /** `cell_status` cru do meuPlano: verde | verde_ressalva | azul | laranja | vermelho. */
  estado: string | null
  feito: boolean
  dispensado: boolean
  atrasado: boolean
}

export type LinhaCronograma = {
  /** Sem ele a célula é uma marca sem porta: é por ele que se abrem as tarefas do mês. */
  plan_item_id: number | null
  nome: string
  /** Selo JÁ em português ("Ensaio", "Inspeção") — o código cru fica em `categoria_codigo`. */
  categoria: string | null
  categoria_codigo?: string | null
  /** "Semestral", "A cada 5 meses" — nunca "6/MONTH". */
  periodicidade: string | null
  /**
   * O bloco sob o qual a linha aparece na tela ("Subestação", "CFTV"). O servidor sempre
   * manda algo; agrupar é o que transforma 94 linhas de ensaio — a análise de equipamento
   * que o cliente disse não querer — em "está sendo feito?" com o detalhe atrás de um clique.
   */
  grupo: string
  previsto_ano: number
  feitos: number
  meses: Celula[]
}

/**
 * Um dos doze meses, já CLASSIFICADO pelo meuPlano.
 *
 * `situacao` é o vocabulário do recorte de vigência: **`fechado`** (mês vencido dentro da
 * vigência — entra na cobrança), **`corrente`** (o mês em curso, que ainda tem dias pela
 * frente) e **`futuro`** (não se cobra o que ainda não venceu). A tela NÃO deduz nada disso
 * do relógio: um contrato que começou em agosto tem meses de 2027 no fim da fita, e adivinhar
 * a âncora aqui era exatamente como se chegava a duas respostas para a mesma pergunta.
 *
 * `previsto` e `cumprido` podem ser nulos — o servidor não disse. ZERO é resposta ("o
 * contrato não prevê nada neste mês"), e converter ausência em zero fabrica um número.
 */
export type MesEstado = {
  mes: string
  situacao: string | null
  previsto: number | null
  cumprido: number | null
}

export type CronogramaOut = {
  usina: string
  usina_id: number
  contrato_id: number | null
  contrato: string | null
  /** O servidor diz se a rota irmã do PDF tem o que gerar — botão que só erra é ruído. */
  pdf_disponivel?: boolean
  /** Nulo = a equipe ainda não publicou o cronograma deste contrato (a frase vem em `aviso`). */
  status: string | null
  versao: number | null
  meses: string[]
  linhas: LinhaCronograma[]
  /**
   * Σ do ANO INTEIRO do contrato — inclusive os meses que ainda não venceram. Responde
   * "o que foi combinado", não "está sendo feito?". Fica na tela como CONTEXTO pequeno,
   * nunca como o número grande: foi dividir por um ano que ainda não aconteceu que produziu
   * "13 de 270" (4,8 %) numa tela e "41,9 %" na outra, para a mesma usina — que não tinha
   * uma única atividade atrasada.
   */
  previsto_ano: number
  feitos_ano: number

  /* ── o recorte de vigência, calculado no meuPlano e apenas repassado ────────────── */
  //
  // Nada disto é recalculado aqui. O BFF já não refaz a conta (o teste de lá prova); se a
  // tela refizesse, nasceria a TERCEIRA resposta para "está sendo feito?".

  /** Até que mês a conta olha ("YYYY-MM"). Percentual sem a janela é metade da frase. */
  mes_referencia?: string | null
  /** O denominador honesto: o previsto nos meses que JÁ venceram dentro da vigência. */
  previsto_ate_hoje?: number | null
  cumprido_ate_hoje?: number | null
  /** 0–100, como o meuPlano calculou. Nulo = ele não informou. */
  pct_ate_hoje?: number | null
  /** Σ de células dos 12 meses — o "270" que a aba Cronograma do meuPlano também mostra. */
  previsto_no_contrato?: number | null
  /** Os 12 meses classificados. Vazio = servidor antigo; a tela não inventa a classificação. */
  meses_estado?: MesEstado[]

  aviso: string | null
}

/* ------------------------------------------------------------------ tarefas do mês */

export type Tarefa = {
  id: number | null
  nome: string
  grupo: string | null
  equipamento: string | null
  status: string | null
  /** A frase que o servidor escreveu ("Executada e verificada"). A tela não traduz nada. */
  situacao: string
  feita: boolean
  natureza: string | null
  parecer: string | null
  /**
   * A COR do parecer, escrita pelo servidor (`TOM_DO_PARECER`, em `manutencao.py`). Nulo =
   * sem parecer, ou parecer que o servidor não sabe classificar; nos dois casos o texto sai
   * sem cor, nunca com uma cor chutada.
   */
  parecer_tom: string | null
  /** A OS que executou a tarefa — é para onde a linha do modal leva. */
  os_id: number | null
  mes_contratual: string | null
  executada_em: string | null
  descricao: string | null
  observacoes: string | null
  preenchimento: number | null
}

/* ------------------------------------------------------------------ caminhos */

export const chaveContratos = (usinaId: number) => `manutencao/contratos?usina_id=${usinaId}`

export const chaveCronograma = (usinaId: number, contratoId: number | null) =>
  `manutencao/cronograma?usina_id=${usinaId}` +
  (contratoId === null ? '' : `&contrato_id=${contratoId}`)

export const chaveTarefasDoMes = (usinaId: number, planItemId: number, mes: string) =>
  `manutencao/cronograma/tarefas?usina_id=${usinaId}&plan_item_id=${planItemId}&mes=${mes}`

/**
 * O PDF do cronograma. Caminho completo porque ele NÃO passa pelo axios: o download vai por
 * `lib/arquivo.ts` (fetch + Blob), com a sessão no cabeçalho — token em URL entra em log de
 * servidor e em histórico do navegador.
 */
export const caminhoPdfCronograma = (usinaId: number, contratoId: number | null) =>
  `/api/v1/manutencao/cronograma/pdf?usina_id=${usinaId}` +
  (contratoId === null ? '' : `&contrato_id=${contratoId}`)

/* ------------------------------------------------------------------ rótulos e cor */

/** O nome do contrato para o seletor: título, senão o número, senão o id. */
export function rotuloDoContrato(c: Contrato): string {
  if (c.titulo) return c.titulo
  if (c.numero !== null) return `Contrato ${c.numero}`
  return `Contrato #${c.id}`
}

/**
 * O tom da célula a partir do `cell_status` do meuPlano.
 *
 * A tradução mora aqui porque o BFF repassa o estado CRU (a cor lá é conformidade calculada
 * contra o histórico do ativo, e ele não escolhe paleta). São os seis tons do produto, e nada
 * mais: um estado que o meuPlano invente amanhã cai em `semDados` — nunca em cor errada.
 *
 * **`azul` (prevista, ainda no prazo) NÃO é `tempoRuim`.** No vocabulário de cor deste
 * produto o azul-claro significa UMA coisa — perda por clima — e ele é lido assim nas telas
 * de energia, no app e no painel. Emprestá-lo para "o contrato prevê isto e o mês ainda não
 * chegou" ensinava ao cliente que a marca azul do cronograma tem a ver com o tempo. Uma
 * atividade que ainda não venceu não é falha nem intercorrência: é ausência de fato, e
 * ausência tem cor neutra (`semDados`).
 */
export function tomDaCelula(c: Celula): Tom {
  if (c.feito || c.dispensado) return 'ok'
  if (c.atrasado) return 'parado'
  if (c.estado === 'laranja') return 'alerta'
  return 'semDados'
}


/* ------------------------------------------------------------------ derivações da matriz */

/*
 * As quatro funções abaixo NÃO produzem número novo: contam as marcas que o servidor já
 * mandou, na matriz que a tela desenha. Vivem aqui, e não dentro dos componentes, por dois
 * motivos — são testáveis sem montar React, e ficam num lugar só, de modo que a faixa de
 * veredito, a fita dos meses e as listas do mês nunca discordem entre si.
 *
 * A fronteira é deliberada: **`previsto` e `cumprido` de cada mês vêm de `meses_estado`**
 * (é o recorte de vigência do meuPlano, e refazê-lo aqui criaria a terceira resposta para
 * "está sendo feito?"); **as ATRASADAS saem da matriz**, porque é a única fonte que as
 * localiza por mês — e é a MESMA fonte que pinta a célula de vermelho, então a faixa e a
 * grade concordam por construção, não por coincidência.
 */

/** Quantas células atrasadas em cada mês. Mês sem atraso simplesmente não entra no mapa. */
export function atrasadasPorMes(linhas: LinhaCronograma[]): Map<string, number> {
  const mapa = new Map<string, number>()
  for (const linha of linhas) {
    for (const celula of linha.meses) {
      if (!celula.atrasado) continue
      const atual = mapa.get(celula.mes)
      mapa.set(celula.mes, atual === undefined ? 1 : atual + 1)
    }
  }
  return mapa
}

/** Σ de células atrasadas na matriz inteira — o número da faixa de veredito. */
export function totalAtrasadas(linhas: LinhaCronograma[]): number {
  let total = 0
  for (const linha of linhas) {
    for (const celula of linha.meses) if (celula.atrasado) total += 1
  }
  return total
}

export type Atrasada = { mes: string; nome: string; grupo: string; planItemId: number | null }

/**
 * A atividade atrasada MAIS ANTIGA, varrendo os meses na ordem do contrato.
 *
 * "3 atrasadas" é um número; "a mais antiga é a Termografia da subestação, de agosto" é a
 * frase que faz alguém agir. A varredura é por mês primeiro, e não por linha, exatamente
 * porque a pergunta é *desde quando*.
 */
export function primeiraAtrasada(dados: CronogramaOut): Atrasada | null {
  for (const mes of dados.meses) {
    for (const linha of dados.linhas) {
      const celula = linha.meses.find((c) => c.mes === mes)
      if (celula && celula.atrasado) {
        return { mes, nome: linha.nome, grupo: linha.grupo, planItemId: linha.plan_item_id }
      }
    }
  }
  return null
}

export type ItemDoMes = {
  planItemId: number | null
  nome: string
  grupo: string
  celula: Celula
}

/**
 * As duas listas do mês de referência: o que já foi × o que ainda está previsto.
 *
 * Dispensada entra em `feitas` porque é isso que o meuPlano conta como cumprido — mas a
 * célula viaja junto para a tela poder ESCREVER "dispensada" ao lado. Fundir os dois no
 * texto seria dizer ao cliente que houve visita onde a equipe registrou "não precisou".
 */
export function atividadesDoMes(
  dados: CronogramaOut,
  mes: string,
): { feitas: ItemDoMes[]; previstas: ItemDoMes[] } {
  const feitas: ItemDoMes[] = []
  const previstas: ItemDoMes[] = []
  for (const linha of dados.linhas) {
    const celula = linha.meses.find((c) => c.mes === mes)
    if (!celula) continue
    const item: ItemDoMes = {
      planItemId: linha.plan_item_id,
      nome: linha.nome,
      grupo: linha.grupo,
      celula,
    }
    if (celula.feito || celula.dispensado) feitas.push(item)
    else if (celula.previsto > 0) previstas.push(item)
  }
  return { feitas, previstas }
}

/**
 * Qual mês a tela está chamando de "agora".
 *
 * O servidor manda `mes_referencia`; o `corrente` de `meses_estado` é a reserva. Nunca o
 * relógio do navegador: os meses são os do CONTRATO, e um contrato assinado em agosto de
 * 2026 tem meses de 2027 na fita — deduzir "hoje" aqui apontaria para a coluna errada, e
 * apontar para a coluna errada é pior que não apontar.
 */
export function mesDeReferencia(dados: CronogramaOut): string | null {
  if (dados.mes_referencia) return dados.mes_referencia
  const corrente = (dados.meses_estado ?? []).find((m) => m.situacao === 'corrente')
  return corrente ? corrente.mes : null
}
