/**
 * Manutenção — o histórico do que já foi feito, vindo do meuPlano.
 *
 * As outras telas olham para a frente: o que está em aberto, o que está agendado. Esta
 * olha para trás, que é como o dono confere se o contrato de O&M está sendo cumprido.
 */

import { baseURL, tokenDaSessao } from '@/lib/api'
import { fetchWithCache, type Leitura } from '@/lib/cache'
import type { Tom } from '@/theme/tokens'

export type OrdemAtendida = {
  id: number | null
  usina: string
  /** O que o serviço era. O BFF já resolve entre `objetivo`, `name` e o título do container. */
  objetivo: string
  classificacao: string | null
  status: string | null
  fechada_em: string | null
  aprovada_em: string | null
  tecnico: string | null
  execucao_min: number | null
  tarefas: number | null
  tarefas_feitas: number | null
  resumo: string | null
}

export type ManutencaoOut = {
  /** Nulo = nenhuma usina respondeu. Zero é "nenhuma OS concluída", que é diferente. */
  total: number | null
  ordens: OrdemAtendida[]
  usinas_com_manutencao: number
  aviso: string | null
}

export function useManutencao(): Leitura<ManutencaoOut> {
  return fetchWithCache<ManutencaoOut>('manutencao')
}


/* ══════════════════════════════════════════════════════════════════════════════
 * A manutenção que está acontecendo
 * ═════════════════════════════════════════════════════════════════════════════
 *
 * O histórico acima responde "o que já foi feito". Isto responde o resto: o que está
 * acontecendo AGORA, o que tem dentro de cada OS, e se o cronograma do contrato está
 * sendo cumprido. Contrato em `docs/CONTRATO_API.md` § Manutenção.
 *
 * Os nomes de campo são os do servidor, como no resto do app — renomear na fronteira
 * cria um segundo vocabulário para a mesma coisa.
 */

export type Tarefa = {
  id: number | null
  nome: string
  /** Seção da lista: o TIPO do item do plano ("Transformador", "Inversor"). */
  grupo: string | null
  /** Qual dos cinco trafos: "Skid 04 > Trafo Skid 4 > Transformador a seco". */
  equipamento: string | null
  status: string | null
  situacao: string
  /** O ✓ da tela. `REALIZADA` ou `APROVADA` no meuPlano. */
  feita: boolean
  /** INSPECAO | SERVICO — separa "olhar" de "trabalhar". */
  natureza: string | null
  /** Só quando existe ficha respondida. Tarefa de serviço não tem parecer. */
  parecer: string | null
  /** A OS que executa a tarefa (a tela da tarefa é `/tarefa/{id}?os={os_id}`). */
  os_id?: number | null
  mes_contratual: string | null
  executada_em: string | null
  /** O que a tarefa pedia. Só o detalhe traz. */
  descricao?: string | null
  /** O que o técnico anotou na execução. */
  observacoes?: string | null
  /** Quanto da ficha está respondido (0-100). Zero é resposta, não ausência. */
  preenchimento?: number | null
}

export type Ordem = {
  id: number
  usina: string
  /** `id` do vínculo NESTE sistema — é por ele que se navega, não pelo id do meuPlano. */
  usina_id: number
  numero: number | null
  objetivo: string
  classificacao: string | null
  /** Código cru do meuPlano, para auditoria. A tela mostra `situacao`. */
  status: string | null
  /** A frase pronta: "Executada · aguardando verificação". Decidida no servidor. */
  situacao: string
  tom: Tom
  tecnico: string | null
  tarefas: number | null
  tarefas_feitas: number | null
  agendada_para: string | null
  concluida_em: string | null
  fechada_em: string | null
  aprovada_em: string | null
  execucao_min: number | null
  resumo: string | null
  /** Só o detalhe traz. `null` na lista = não foi buscado; `null` no detalhe = não deu. */
  itens: Tarefa[] | null
}

export type OrdensOut = {
  total: number | null
  /** A OS não encerrada mais recente, já escolhida pelo servidor. */
  em_andamento: Ordem | null
  ordens: Ordem[]
  usinas_com_manutencao: number
  aviso: string | null
}

export type Celula = {
  mes: string
  previsto: number
  /** `cell_status` do meuPlano, repassado. Os booleanos abaixo poupam conhecê-lo. */
  estado: string | null
  /** Executado de fato (`verde`). Dispensa NÃO entra aqui — ver `dispensado`. */
  feito: boolean
  /** Dispensado com motivo registrado (`verde_ressalva`). Não é o mesmo que feito. */
  dispensado: boolean
  atrasado: boolean
}

export type LinhaCronograma = {
  /** O item do plano desta linha — é por ele que se abre o que está atrás do X. */
  plan_item_id: number | null
  nome: string
  categoria: string | null
  periodicidade: string | null
  previsto_ano: number
  /** Conta feitos E dispensados: o dispensado saiu da conta do mês por decisão. */
  feitos: number
  meses: Celula[]
}

export type CronogramaOut = {
  usina: string
  usina_id: number
  /** DRAFT | CONSOLIDATED. Só o consolidado é o combinado com o cliente. */
  status: string | null
  versao: number | null
  /** 12 × "YYYY-MM". O mês 1 é a âncora do CONTRATO, não janeiro. */
  meses: string[]
  linhas: LinhaCronograma[]
  previsto_ano: number
  feitos_ano: number
  aviso: string | null
}

/** Todas as OS — abertas e encerradas. Sem `usinaId`, as de todas as usinas. */
export function useOrdens(usinaId?: number): Leitura<OrdensOut> {
  // A usina entra na CHAVE do cache, não só na query: com uma chave só, trocar de usina
  // mostraria o cache da anterior por um instante — e no modo offline, para sempre.
  const chave = usinaId ? `manutencao/ordens-${usinaId}` : 'manutencao/ordens'
  return fetchWithCache<OrdensOut>(chave, {
    caminho: usinaId ? `/api/v1/manutencao/ordens?usina_id=${usinaId}` : '/api/v1/manutencao/ordens',
  })
}

export function useOrdem(id: string | number | undefined): Leitura<Ordem> {
  // Sem `id` a consulta fica desligada, senão a rota viraria `/ordens/undefined`.
  return fetchWithCache<Ordem>(`manutencao/ordem-${id ?? ''}`, {
    caminho: `/api/v1/manutencao/ordens/${id ?? ''}`,
    ativo: Boolean(id),
  })
}

/* ── A FICHA RESPONDIDA ─────────────────────────────────────────────────────
 * O que o técnico registrou, equipamento por equipamento. Vem da MESMA fonte do PDF no
 * meuPlano — tela e laudo não podem divergir. O PDF continua existindo: ele é o documento;
 * isto é a leitura.
 */

export type LinhaMedicao = {
  ponto: string
  valor: string | null
  unidade: string | null
  alvo: string | null
  desvio: string | null
  /** Tri-estado: true aprovado, false reprovado, null "não se aplica"/não julgado. */
  aprovado: boolean | null
  /**
   * O rótulo que o laudo imprime quando o item é ESTADO e não julgamento — "Não feito" num
   * item de serviço, por exemplo. Vinha no mesmo campo de `aprovado`, e um texto onde se
   * esperava sim/não derrubava a ficha inteira antes de desenhar qualquer coisa.
   */
  situacao: string | null
  observacao: string | null
}

export type Medicao = {
  nome: string
  unidade: string | null
  linhas: LinhaMedicao[]
}

/** Uma evidência anexada pelo técnico. A `url` é do BFF — é lá que a sessão vale. */
export type Foto = {
  id: number
  legenda: string | null
  url: string
  thumb_url: string
}

export type PerguntaChecklist = {
  pergunta: string
  resposta: string | null
  /** A resposta É o problema — a régua de polaridade é do meuPlano, não daqui. */
  problema: boolean
  observacao: string | null
  /** As fotos DAQUELA resposta: numa inspeção, é aqui que a evidência mora. */
  fotos: Foto[]
}

export type SecaoChecklist = { nome: string; perguntas: PerguntaChecklist[] }

export type EquipamentoDaFicha = {
  equipamento: string
  modelo: string | null
  fabricante: string | null
  numero_serie: string | null
  executado_em: string | null
  executado_por: string | null
  parecer: string | null
  parecer_motivo: string | null
  medicoes: Medicao[]
  checklist: SecaoChecklist[]
  /** Todas as do equipamento — as da sessão e as das respostas, já reunidas. */
  fotos: Foto[]
}

export type Ficha = {
  id: number | null
  nome: string | null
  coletiva: boolean
  parecer: string | null
  equipamentos: EquipamentoDaFicha[]
  fotos: number
}

/** As respostas da tarefa. Separada de `useTarefa` porque é mais cara: a tela abre com o
 *  cabeçalho na hora e a ficha chega em seguida, em vez de tudo esperar tudo. */
export function useFicha(
  osId: string | number | undefined,
  tarefaId: string | number | undefined,
): Leitura<Ficha> {
  return fetchWithCache<Ficha>(`manutencao/ordem-${osId ?? ''}-ficha-${tarefaId ?? ''}`, {
    caminho: `/api/v1/manutencao/ordens/${osId ?? ''}/tarefas/${tarefaId ?? ''}/ficha`,
    ativo: Boolean(osId && tarefaId),
    // A leitura mais cara do aplicativo: uma ficha coletiva de vinte inversores é montada
    // do zero no meuPlano, depois de três chamadas de autorização. Com os 12 s de sempre, a
    // ficha da manutenção mensal dos inversores nunca abria.
    prazoMs: 60000,
  })
}

/** UMA tarefa da OS. O dono precisa abrir o item e ler o que foi feito — a lista mostra
 *  nome e ✓, e isso não responde "o que o técnico registrou aqui?". */
export function useTarefa(
  osId: string | number | undefined,
  tarefaId: string | number | undefined,
): Leitura<Tarefa> {
  return fetchWithCache<Tarefa>(`manutencao/ordem-${osId ?? ''}-tarefa-${tarefaId ?? ''}`, {
    caminho: `/api/v1/manutencao/ordens/${osId ?? ''}/tarefas/${tarefaId ?? ''}`,
    ativo: Boolean(osId && tarefaId),
  })
}

export function useCronograma(usinaId: string | number | undefined): Leitura<CronogramaOut> {
  return fetchWithCache<CronogramaOut>(`manutencao/cronograma-${usinaId ?? ''}`, {
    caminho: `/api/v1/manutencao/cronograma?usina_id=${usinaId ?? ''}`,
    ativo: Boolean(usinaId),
  })
}

/** As tarefas por trás de UM X do cronograma (atividade × mês). Sem cache de disco: é uma
 *  consulta pontual, feita no toque, e guardar isso encheria o cache com uma entrada por
 *  célula tocada. */
export async function tarefasDaCelula(
  usinaId: number,
  planItemId: number,
  mes: string,
): Promise<Tarefa[]> {
  const r = await fetch(
    `${baseURL}/api/v1/manutencao/cronograma/tarefas?usina_id=${usinaId}` +
      `&plan_item_id=${planItemId}&mes=${encodeURIComponent(mes)}`,
    { headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` } },
  )
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as Tarefa[]
}

/* Os PDFs não passam pelo cache: são baixados com a sessão em CABEÇALHO, nunca na URL —
 * token em query entra em log de servidor e em histórico. Ver `components/AbrirPdf`. */

export function urlDoPdfDaOrdem(id: number): string {
  return `${baseURL}/api/v1/manutencao/ordens/${id}/pdf`
}

/** O PDF de UMA tarefa: a ficha respondida, sem as outras dezenas de páginas da OS. */
export function urlDoPdfDaTarefa(osId: number, tarefaId: number): string {
  return `${baseURL}/api/v1/manutencao/ordens/${osId}/tarefas/${tarefaId}/pdf`
}

export function urlDoPdfDoCronograma(usinaId: number): string {
  return `${baseURL}/api/v1/manutencao/cronograma/pdf?usina_id=${usinaId}`
}
