/**
 * O contrato das duas leituras da tela de Relatórios.
 *
 * São dois documentos com origens diferentes, e por isso dois blocos independentes:
 *
 * - **Relatório de manutenção** (`/api/v1/manutencao/relatorio`) — nasceu para esta tela: o
 *   BFF pede ao meuPlano o agregado lido do próprio ATIVO (cronograma cumprido, OSs
 *   encerradas, pareceres, problemas, dispensas, pendências) e traduz para o vocabulário do
 *   portal. O PDF (`/relatorio/pdf`) é gerado do MESMO JSON lá — tela e documento não
 *   divergem.
 * - **Relatórios de geração** (`/api/v1/documents`) — os fechamentos que a equipe publica
 *   pelo meuWatt, com o PDF de geração e o anexo de paradas.
 *
 * Os tipos abaixo espelham `bff/app/api/v1/relatorio.py` e `documents.py` campo a campo,
 * inclusive os nulos: `pct_cumprido` nulo é "nada estava previsto", **não** "0 % cumprido",
 * e `itens: null` numa OS é "não deu para buscar as tarefas", **não** "OS sem tarefas". A
 * tela precisa das duas distinções para não afirmar o que ninguém disse.
 *
 * As chaves de leitura carregam a query string de propósito: elas são o nome no cache
 * (`useLeitura`), então trocar de contrato ou de período troca de leitura em vez de sujar a
 * anterior.
 */


/* ------------------------------------------------------------------ contratos */

/** Um contrato de O&M — o mesmo formato que o seletor da aba Cronograma usa. */
export type Contrato = {
  /** id do container no meuPlano: é o `contrato_id` que as rotas do portal recebem. */
  id: number
  numero: number | null
  titulo: string | null
  inicio: string | null
  fim: string | null
  vigente: boolean | null
  /** Versão do cronograma CONSOLIDADO. Nulo = a equipe ainda não publicou nenhuma. */
  versao_cronograma: number | null
}

export type ContratosOut = {
  usina: string
  usina_id: number
  contratos: Contrato[]
  aviso: string | null
}

/* ------------------------------------------------------------------ relatório */

export type LinhaDoCronograma = {
  plan_item_id: number | null
  nome: string
  /** `ensaio` | `servico` | `checklist` — a espécie da linha, como no cronograma. */
  categoria: string | null
  previstas: number
  executadas: number
  dispensadas: number
  atrasadas: number
  /** Previsto e ainda dentro do prazo — não é atraso. */
  no_prazo: number
  /** Previsto num item que não cobre equipamento nenhum. Sem ele o total não fecharia. */
  sem_ativo: number
}

export type Dispensa = { atividade: string; mes: string; motivo: string | null }

export type CronogramaDoRelatorio = {
  status: string | null
  versao: number | null
  consolidado_em: string | null
  previstas: number
  executadas: number
  dispensadas: number
  atrasadas: number
  no_prazo: number
  sem_ativo: number
  /** Percentual (0–100) calculado no meuPlano. NULO quando nada estava previsto. */
  pct_cumprido: number | null
  linhas: LinhaDoCronograma[]
  dispensas: Dispensa[]
}

export type TarefaDaOrdem = {
  id: number | null
  nome: string
  grupo: string | null
  equipamento: string | null
  status: string | null
  situacao: string
  feita: boolean
  natureza: string | null
  /** Já em português ("Aprovado", "Aprovado com ressalva", "Reprovado"). */
  parecer: string | null
  /**
   * A COR do parecer, escrita pelo servidor (`TOM_DO_PARECER`, em `manutencao.py`). Nulo =
   * sem parecer, ou parecer que o servidor não sabe classificar; nos dois casos o texto sai
   * sem cor, nunca com uma cor chutada.
   */
  parecer_tom: string | null
  os_id: number | null
  mes_contratual: string | null
  executada_em: string | null
  descricao: string | null
  observacoes: string | null
  preenchimento: number | null
}

export type Ordem = {
  id: number
  usina: string
  usina_id: number
  numero: number | null
  objetivo: string
  classificacao: string | null
  status: string | null
  situacao: string
  /** Um dos seis tons — escrito pelo servidor, não deduzido aqui. */
  tom: string
  tecnico: string | null
  tarefas: number | null
  tarefas_feitas: number | null
  agendada_para: string | null
  concluida_em: string | null
  fechada_em: string | null
  aprovada_em: string | null
  execucao_min: number | null
  resumo: string | null
  /** `null` = não deu para buscar; `[]` = OS sem tarefas. Frases diferentes na tela. */
  itens: TarefaDaOrdem[] | null
}

export type Pareceres = {
  aprovados: number
  com_ressalva: number
  reprovados: number
  sem_parecer: number
  /**
   * De onde saem estas contagens, escrito pelo servidor.
   *
   * O agregado conta as fichas das ordens ENCERRADAS; a ordem ainda em execução aparece na
   * lista acima e não entra. Enquanto isso ficava implícito, a mesma página exibia um
   * "Aprovado com ressalva" na OS em curso e "COM RESSALVA 0" logo abaixo — e um relatório
   * que se contradiz não chega à diretoria.
   */
  recorte: string | null
}

export type FaixaDeCriticidade = {
  criticidade: string
  rotulo: string
  total: number
  tom: string
}

export type ProblemasDaOrdem = {
  os_id: number | null
  objetivo: string
  total: number
  urgentes: number
  tom: string
}

export type Problemas = {
  total: number
  /** Sempre as quatro faixas, do mais grave para o menos — a ordem vem do servidor. */
  por_criticidade: FaixaDeCriticidade[]
  por_os: ProblemasDaOrdem[]
  /** Mesmo recorte dos pareceres (ver `Pareceres.recorte`). */
  recorte: string | null
}

export type PendenciaDoRelatorio = {
  id: number | null
  numero: number | null
  titulo: string
  status: string | null
  situacao: string
  tom: string
  cobrada_pelo_cliente: boolean
  prazo: string | null
  /** Aproximada: o meuPlano não carimba a conclusão da pendência. A tela diz "por volta de". */
  concluida_em: string | null
}

export type PendenciasDoRelatorio = {
  abertas: PendenciaDoRelatorio[]
  concluidas: PendenciaDoRelatorio[]
}

export type RelatorioOut = {
  usina: string
  usina_id: number
  cliente: string | null
  executora: string | null
  contrato: Contrato | null
  periodo: { de: string; ate: string }
  /** Nulo = sem contrato ou sem cronograma consolidado; o porquê vem em `aviso`. */
  cronograma: CronogramaDoRelatorio | null
  ordens: Ordem[]
  em_curso: Ordem[]
  pareceres: Pareceres
  problemas: Problemas
  pendencias: PendenciasDoRelatorio
  fotos: number | null
  gerado_em: string
  aviso: string | null
}

/* ------------------------------------------------------------------ documentos */

export type ArquivoDoDocumento = {
  /** `geracao` (Relatório de Geração) ou `paradas` (Anexo de Paradas). */
  tipo: string
  nome: string
}

export type Documento = {
  id: number
  nome: string
  usina: string
  plant_id: number | null
  /** `DIÁRIO` · `SEMANAL` · `MENSAL` · `ANUAL` — vocabulário do meuWatt. */
  periodo: string
  de: string
  ate: string
  publicado_em: string
  arquivos: ArquivoDoDocumento[]
}

export type DocumentosOut = { documentos: Documento[]; aviso: string | null }

/* ------------------------------------------------------------------ endereços */

export function chaveContratos(usinaId: number): string {
  return `manutencao/contratos?usina_id=${usinaId}`
}

/** `contrato_id` só viaja quando o cliente escolheu: ausente, o BFF resolve o padrão. */
function consultaDoRelatorio(
  usinaId: number,
  de: string,
  ate: string,
  contratoId: number | null,
): string {
  const partes = [`usina_id=${usinaId}`, `de=${de}`, `ate=${ate}`]
  if (contratoId !== null) partes.push(`contrato_id=${contratoId}`)
  return partes.join('&')
}

export function chaveRelatorio(
  usinaId: number,
  de: string,
  ate: string,
  contratoId: number | null,
): string {
  return `manutencao/relatorio?${consultaDoRelatorio(usinaId, de, ate, contratoId)}`
}

export function caminhoPdfDoRelatorio(
  usinaId: number,
  de: string,
  ate: string,
  contratoId: number | null,
): string {
  return `/api/v1/manutencao/relatorio/pdf?${consultaDoRelatorio(usinaId, de, ate, contratoId)}`
}

export function nomeDoPdfDoRelatorio(usina: string, de: string, ate: string): string {
  return `Relatorio-manutencao-${usina}-${de}-${ate}.pdf`.replace(/[\\/\s]+/g, '-')
}

export function chaveDocumentos(usinaId: number): string {
  return `documents?usina_id=${usinaId}`
}

export function caminhoDoArquivo(documentoId: number, tipo: string): string {
  return `/api/v1/documents/${documentoId}/file?tipo=${encodeURIComponent(tipo)}`
}

/* ------------------------------------------------------------------ rótulos */

/** Nome do contrato para o seletor. Sem título, vale o número; sem número, o id. */
export function rotuloDoContrato(c: Contrato): string {
  if (c.titulo) return c.numero === null ? c.titulo : `#${c.numero} · ${c.titulo}`
  return c.numero === null ? `Contrato ${c.id}` : `Contrato #${c.numero}`
}

/** `geracao` → "Relatório de geração". O tipo é do meuWatt; o nome é do cliente. */
export const NOME_DO_ARQUIVO: Record<string, string> = {
  geracao: 'Relatório de geração',
  paradas: 'Anexo de paradas',
}

/** `ensaio` → "Ensaio". Espécie da linha do cronograma — texto, nunca cor: cor é estado. */
export const NOME_DA_CATEGORIA: Record<string, string> = {
  ensaio: 'Ensaio',
  servico: 'Serviço',
  checklist: 'Checklist',
  inspecao: 'Inspeção',
}

