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
  categoria: string | null
  periodicidade: string | null
  previsto_ano: number
  feitos: number
  meses: Celula[]
}

export type CronogramaOut = {
  usina: string
  usina_id: number
  contrato_id: number | null
  contrato: string | null
  /** Nulo = a equipe ainda não publicou o cronograma deste contrato (a frase vem em `aviso`). */
  status: string | null
  versao: number | null
  meses: string[]
  linhas: LinhaCronograma[]
  previsto_ano: number
  feitos_ano: number
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
 */
export function tomDaCelula(c: Celula): Tom {
  if (c.feito || c.dispensado) return 'ok'
  if (c.atrasado) return 'parado'
  if (c.estado === 'laranja') return 'alerta'
  if (c.estado === 'azul') return 'tempoRuim'
  return 'semDados'
}

