/**
 * O contrato das leituras da tela de Relatórios — duas famílias, quatro origens.
 *
 * **Energia** é uma leitura só:
 *
 * - **Fechamentos publicados** (`/api/v1/documents`) — o que a equipe publica pelo meuWatt.
 *   Cada fechamento carrega até TRÊS peças: `geracao`, `paradas` e `resumo` (o Resumo
 *   Executivo). A terceira só existe quando o mês teve uma geração de IA concluída lá, então
 *   peça ausente é ESTADO NORMAL desta tela, nunca erro.
 *
 * **Manutenção** tem três:
 *
 * - **Relatório do período** (`/api/v1/manutencao/relatorio`) — o agregado que o BFF pede ao
 *   meuPlano, lido do próprio ATIVO (cronograma cumprido, OSs encerradas, pareceres,
 *   problemas, dispensas, pendências). O PDF (`/relatorio/pdf`) sai do MESMO JSON lá — tela e
 *   documento não divergem.
 * - **Contratos** (`/api/v1/manutencao/contratos`) — o seletor do relatório.
 * - **Fichas do período** (`/api/v1/manutencao/fichas*`) — o pacote de PDFs das tarefas, em
 *   três atos: inventariar, preparar e baixar. Ver o bloco no fim deste arquivo.
 *
 * Os tipos espelham `bff/app/api/v1/relatorio.py`, `documents.py` e `pacotes.py` campo a
 * campo, inclusive os nulos: `pct_cumprido` nulo é "nada estava previsto", **não** "0 %
 * cumprido"; `itens: null` numa OS é "não deu para buscar as tarefas", **não** "OS sem
 * tarefas"; e `bytes` nulo numa ficha é "ainda não foi gerada", **não** "arquivo vazio". A
 * tela precisa das três distinções para não afirmar o que ninguém disse.
 *
 * As chaves de leitura carregam a query string de propósito: elas são o nome no cache
 * (`useLeitura`), então trocar de contrato, de período ou de filtro troca de leitura em vez
 * de sujar a anterior.
 */

import { inteiro, numero } from '@/lib/format'


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
  /**
   * A frase que reconcilia este bloco com a aba Cronograma. O portal dava DUAS respostas
   * para "está sendo feito?": "13 de 270 previstas" lá e "cumprido 41,9%" sobre 31 aqui —
   * porque o período pedido começava antes da vigência do contrato. Nula quando não há
   * diferença a explicar; aviso que aparece sempre ninguém lê.
   */
  recorte?: string | null
  /** Σ de X do contrato inteiro — o denominador da aba Cronograma, para conferir a conta. */
  previstas_no_contrato?: number | null
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
  /** Número do CONTRATO que rege a OS — **nunca** o número da OS (que é o `id`). */
  contrato_numero: number | null
  objetivo: string
  /** Rótulo pronto do servidor ("Serviços adicionais"), nunca o código cru. */
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
  /**
   * `geracao` (Relatório de Geração), `paradas` (Anexo de Paradas) ou `resumo` (Resumo
   * Executivo). São as três peças que o meuWatt publica (`_FILE_KINDS`); o BFF as libera uma
   * a uma numa lista fechada, e por isso o tipo aqui é `string` e não uma união: um quarto
   * kind que apareça amanhã deve ser LISTADO na tela (com o nome cru, se preciso), não sumir.
   */
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

/* ------------------------------------------------------------------ fichas */

/** Uma ficha do pacote — o PDF de UMA tarefa. Espelha `FichaOut` em `pacotes.py`. */
export type FichaDoPacote = {
  task_id: number
  nome: string
  equipamento: string | null
  /** Situação da tarefa, já traduzida pelo servidor. Nula = o upstream não disse. */
  situacao: string | null
  /** O PDF já existe e está válido. Falso = será gerado no preparo. */
  pronta: boolean
  /** Tamanho do PDF pronto. **Nulo ≠ zero**: nulo é "ainda não existe". */
  bytes: number | null
}

/** As fichas agrupadas pela ordem de serviço que as gerou. */
export type OrdemDoPacote = {
  os_id: number
  contrato_numero: number | null
  objetivo: string
  /** Rótulo pronto ("Serviços adicionais") — o código cru fica em `classificacao_codigo`. */
  classificacao: string | null
  classificacao_codigo: string | null
  classificacao_tom: string
  situacao: string
  tom: string
  status: string | null
  /** A data pela qual a OS entrou no período — a régua é do meuPlano, não daqui. */
  data: string | null
  fichas: FichaDoPacote[]
}

/** Um arquivo do pacote. Mais de uma parte quando o total não cabe num ZIP só. */
export type ParteDoPacote = { numero: number; fichas: number; bytes: number | null }

export type InventarioDeFichas = {
  usina: string
  usina_id: number
  de: string
  ate: string
  ordens: OrdemDoPacote[]
  /** Quantas fichas o filtro pegou. Zero é resposta legítima, não falha. */
  total: number
  /** Quantas já têm PDF. `prontas < total` = o botão da tela é "Preparar". */
  prontas: number
  /** Soma dos tamanhos CONHECIDOS. Nulo = nada pronto ainda — "0 MB" mentiria. */
  bytes_estimados: number | null
  partes: ParteDoPacote[]
  /** Quantas fichas há no período SEM filtro — é o que deixa a tela vazia se explicar. */
  total_sem_filtro: number | null
  filtros: Record<string, unknown>
  aviso: string | null
}

/** O andamento da geração das fichas que faltavam — o "14 de 17" da tela. */
export type PreparoDeFichas = {
  preparo_id: string
  total: number
  prontas: number
  concluido: boolean
  /** `andando` · `pronto` · `falhou`. Concluído sozinho não separa "terminou" de "parou". */
  estado: string
  /** O que interrompeu o preparo inteiro. Diferente de `erros`, que são fichas soltas. */
  erro: string | null
  /** Ficha que nem a regeração salvou. O pacote sai sem ela, e a tela diz qual. */
  erros: Record<string, unknown>[]
  ja_em_andamento: boolean
  expira_em: number | null
  aviso: string | null
}

/**
 * O recorte que o cliente escolheu — os cinco filtros do pedido, num objeto só.
 *
 * `classificacao` e `situacao` guardam o sentinela `todas` em vez de `null` porque o valor
 * também é o do seletor: um combobox com valor nulo aparece com o texto de placeholder, e
 * "Todas as classificações" é uma escolha legítima, não a ausência de uma.
 */
export type FiltroDeFichas = {
  /** Competências `YYYY-MM`, inclusive nas duas pontas. */
  de: string
  ate: string
  classificacao: string
  situacao: string
  /** Uma ordem específica, quando o cliente escolheu uma. */
  osId: number | null
  busca: string
}

export const TODAS = 'todas'

/**
 * As classificações que o BFF aceita (`CLASSIFICACOES`, em `pacotes.py`).
 *
 * Lista fechada dos dois lados: o valor vai para a query do meuPlano com a credencial de
 * serviço, e texto livre daqui seria um parâmetro nosso alimentando a rota dele.
 * "Se eu fizer corretiva, quero poder ver também" — daí a corretiva ter entrada própria.
 */
export const CLASSIFICACOES: { valor: string; rotulo: string }[] = [
  { valor: TODAS, rotulo: 'Todas as classificações' },
  { valor: 'PREVENTIVA', rotulo: 'Preventiva' },
  { valor: 'CORRETIVA', rotulo: 'Corretiva' },
  { valor: 'SERVICOS_ADICIONAIS', rotulo: 'Serviços adicionais' },
]

/** A pergunta do cliente é "o que já foi entregue" × "o que ainda anda", não o status cru. */
export const SITUACOES: { valor: string; rotulo: string }[] = [
  { valor: TODAS, rotulo: 'Encerradas e em curso' },
  { valor: 'encerradas', rotulo: 'Só as encerradas' },
  { valor: 'em_curso', rotulo: 'Só as em curso' },
]

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

/**
 * A query das três rotas de ficha — inventário, preparo e pacote leem o MESMO recorte.
 *
 * Uma função só porque o pacote precisa sair exatamente do filtro que foi inventariado: se a
 * query do download divergisse da do inventário por um parâmetro, a tela prometeria dezessete
 * fichas e o arquivo traria outra coisa — e ninguém confere um ZIP.
 *
 * O sentinela `todas` NÃO viaja: ele é a ausência de filtro, e mandá-lo faria o BFF recusar
 * um valor que a própria tela ofereceu.
 */
function consultaDeFichas(usinaId: number, f: FiltroDeFichas): string {
  const partes = [`usina_id=${usinaId}`, `de=${f.de}`, `ate=${f.ate}`]
  if (f.classificacao !== TODAS) partes.push(`classificacao=${encodeURIComponent(f.classificacao)}`)
  if (f.situacao !== TODAS) partes.push(`situacao=${encodeURIComponent(f.situacao)}`)
  if (f.osId !== null) partes.push(`os_id=${f.osId}`)
  const busca = f.busca.trim()
  if (busca) partes.push(`busca=${encodeURIComponent(busca)}`)
  return partes.join('&')
}

export function chaveInventario(usinaId: number, f: FiltroDeFichas): string {
  return `manutencao/fichas?${consultaDeFichas(usinaId, f)}`
}

export function caminhoPreparar(usinaId: number, f: FiltroDeFichas): string {
  return `/api/v1/manutencao/fichas/preparar?${consultaDeFichas(usinaId, f)}`
}

/**
 * O acompanhamento do preparo. `usina_id` viaja junto de propósito: sem ele, trocar o número
 * do preparo devolveria o andamento (e os ids de tarefa) do pacote de outro cliente.
 */
export function caminhoDoPreparo(preparoId: string, usinaId: number): string {
  return `/api/v1/manutencao/fichas/preparo/${encodeURIComponent(preparoId)}?usina_id=${usinaId}`
}

export function caminhoDoPacote(usinaId: number, f: FiltroDeFichas, parte: number): string {
  return `/api/v1/manutencao/fichas/pacote?${consultaDeFichas(usinaId, f)}&parte=${parte}`
}

/**
 * As marcas de acento que a decomposição `NFD` separa da letra ("ã" → "a" + til).
 *
 * Montada a partir de texto, e não escrita como literal: um intervalo de caracteres
 * combinantes dentro de `/.../` é invisível em qualquer revisão — cola errado, some num
 * `git diff` e ninguém enxerga. Tirá-las ANTES de trocar o resto por hífen é o que faz
 * "Ribeirão" virar `ribeirao`, e não `ribeira-o`.
 */
const ACENTOS = new RegExp('[\\u0300-\\u036f]', 'g')

/**
 * `fichas-porto-ferreira-2026-08.zip`, ou `…-2026-01_2026-08-parte2de4.zip`.
 *
 * O BFF manda o mesmo nome no `Content-Disposition`, mas quem baixa aqui é o `fetch` + Blob
 * (a sessão vai em cabeçalho), e nesse caminho o nome do arquivo é o que ESTA função escreve.
 * Sem acento e sem espaço pela mesma razão de lá: o nome atravessa sistema de arquivos e
 * cabeçalho HTTP, e "Ribeirão Bonito" já derrubou uma resposta inteira antes do CORS.
 */
export function nomeDoPacote(
  usina: string,
  f: FiltroDeFichas,
  parte: number,
  partes: number,
): string {
  const limpo =
    usina
      .normalize('NFD')
      .replace(ACENTOS, '')
      .replace(/[^A-Za-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .toLowerCase() || 'usina'
  const periodo = f.de === f.ate ? f.de : `${f.de}_${f.ate}`
  const sufixo = partes > 1 ? `-parte${parte}de${partes}` : ''
  return `fichas-${limpo}-${periodo}${sufixo}.zip`
}

/* ------------------------------------------------------------------ rótulos */

/**
 * "18,4 MB" — o tamanho de um arquivo, em pt-BR.
 *
 * Nulo é "—", nunca "0 MB": o segundo se lê como pacote vazio, e é exatamente o que a tela
 * mostraria enquanto nenhuma ficha foi gerada ainda.
 */
export function tamanhoDeArquivo(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '—'
  if (bytes < 1024) return `${inteiro(bytes)} B`
  if (bytes < 1024 * 1024) return `${numero(bytes / 1024, 0)} KB`
  return `${numero(bytes / (1024 * 1024), 1)} MB`
}

/** Nome do contrato para o seletor. Sem título, vale o número; sem número, o id. */
export function rotuloDoContrato(c: Contrato): string {
  if (c.titulo) return c.numero === null ? c.titulo : `#${c.numero} · ${c.titulo}`
  return c.numero === null ? `Contrato ${c.id}` : `Contrato #${c.numero}`
}

/**
 * As três peças de um fechamento, na ordem em que se leem.
 *
 * A ordem é a do documento: primeiro o relatório de geração, depois o anexo que detalha as
 * paradas daquele mês, e por fim o deck que a diretoria abre. Ela também é a ordem dos
 * botões — e dos espaços vazios, quando uma peça não foi publicada.
 */
export const PECAS_DO_FECHAMENTO = ['geracao', 'paradas', 'resumo'] as const

/**
 * `geracao` → "Relatório de geração". O tipo é do meuWatt; o nome é do cliente.
 *
 * O `resumo` entrou quando o BFF passou a liberar a terceira peça (`_FILE_KINDS` da mw-api
 * sempre teve as três; a lista fechada do BFF é que tinha duas). Um kind desconhecido cai no
 * nome que o servidor mandou — some da tela nunca.
 */
export const NOME_DO_ARQUIVO: Record<string, string> = {
  geracao: 'Relatório de geração',
  paradas: 'Anexo de paradas',
  resumo: 'Resumo executivo',
}

/** `ensaio` → "Ensaio". Espécie da linha do cronograma — texto, nunca cor: cor é estado. */
export const NOME_DA_CATEGORIA: Record<string, string> = {
  ensaio: 'Ensaio',
  servico: 'Serviço',
  checklist: 'Checklist',
  inspecao: 'Inspeção',
}

