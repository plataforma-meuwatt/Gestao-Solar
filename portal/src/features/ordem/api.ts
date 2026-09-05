/**
 * O contrato de UMA ordem de serviço, como o BFF a devolve
 * (`bff/app/api/v1/manutencao.py`: `OrdemOut`, `TarefaOut`).
 *
 * Os tipos são cópia fiel do servidor, com uma regra: **nada de campo obrigatório onde o BFF
 * declara `| None`**. Cada nulo aqui é uma afirmação diferente de zero — `execucao_min` nulo é
 * "o meuPlano não cronometrou", e escrever `0` no lugar diria que a equipe não gastou tempo
 * nenhum. É a REGRA 0 do produto, e ela começa no tipo.
 *
 * O caso mais caro é `itens`: **`null` é "não deu para buscar as tarefas"** (o BFF devolve o
 * cabeçalho mesmo quando a chamada de tarefas falha — ver `detalhar_ordem`) e **`[]` é "esta
 * OS não tem tarefa registrada"**. Duas frases na tela, porque são duas situações; fundi-las
 * faria o cliente ler uma falha de rede como serviço não executado.
 */

import { useLeitura, type Leitura } from '@/lib/leitura'

/** Uma tarefa dentro da OS — o item que o técnico marca como feito. */
export type Tarefa = {
  id: number | null
  /** O que fazer ("Termografia"). O BFF já resolveu a cascata de nomes do meuPlano. */
  nome: string
  /** Seção da lista: o TIPO do item do plano ("Transformador"), como a própria OS agrupa. */
  grupo: string | null
  /** Onde. Vem com o caminho na árvore, que é o que distingue cinco trafos de mesmo nome. */
  equipamento: string | null
  status: string | null
  /** A frase do servidor ("Executada e verificada") — nunca o código cru. */
  situacao: string
  /** Concluída pelo técnico. Decidido no BFF a partir de REALIZADA/APROVADA. */
  feita: boolean
  natureza: string | null
  /** "Aprovado" · "Aprovado com ressalva" · "Reprovado". Só existe com ficha respondida. */
  parecer: string | null
  /**
   * A COR do parecer, escrita pelo servidor (`TOM_DO_PARECER`). Nulo = sem parecer, ou
   * parecer que o servidor não sabe classificar — nos dois casos o texto sai sem cor.
   * Deduzir a cor da frase aqui era o que fazia esta tela pintar de VERDE um veredito novo
   * que ninguém tinha lido.
   */
  parecer_tom: string | null
  os_id: number | null
  mes_contratual: string | null
  executada_em: string | null
  descricao: string | null
  observacoes: string | null
  preenchimento: number | null
}

/** Uma OS como o dono da usina a lê. */
export type Ordem = {
  id: number
  usina: string
  /** Id do vínculo NESTE sistema — é por ele que a URL do portal navega. */
  usina_id: number
  /** Número do CONTRATO que rege a OS — **nunca** o número da OS, que é o `id`. */
  contrato_numero: number | null
  objetivo: string
  /** Rótulo pronto do servidor ("Serviços adicionais"), com o código cru ao lado. */
  classificacao: string | null
  classificacao_codigo?: string | null
  classificacao_tom?: string
  status: string | null
  /** A frase que a tela mostra ("Em verificação"). */
  situacao: string
  /** Um dos seis tons, escrito pelo servidor. */
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
  /** `null` = não deu para buscar; `[]` = a OS não tem tarefas. Ver o cabeçalho do módulo. */
  itens: Tarefa[] | null
}

/**
 * A OS pedida, com as tarefas dentro.
 *
 * A OS entra na CHAVE do cache: com uma chave só, abrir a OS seguinte mostraria a anterior
 * por um instante — e, sem rede, para sempre.
 */
export function useOrdem(osId: string | undefined): Leitura<Ordem> {
  return useLeitura<Ordem>(`manutencao/ordem-${osId ?? ''}`, {
    caminho: `/api/v1/manutencao/ordens/${osId ?? ''}`,
    // Sem `osId` a consulta fica desligada; senão o caminho viraria `/ordens/`.
    ativo: Boolean(osId),
  })
}

/**
 * O endereço da FICHA de uma tarefa — a tela, não o arquivo.
 *
 * É rota do portal (`/usinas/:id/manutencao/ordens/:osId/tarefas/:taskId`), e por isso leva a
 * usina: o `:id` da URL é o vínculo NESTE sistema (`Ordem.usina_id`), não a usina do meuPlano.
 * Sai daqui, e não escrito à mão na tela, porque o endereço nomeia a família ("manutencao") —
 * montá-lo em cada ponto de uso é o que faz um deles envelhecer sozinho depois de uma
 * reorganização de menu.
 */
export function caminhoDaTarefa(
  usinaId: string | number,
  osId: string | number,
  tarefaId: number,
): string {
  return `/usinas/${usinaId}/manutencao/ordens/${osId}/tarefas/${tarefaId}`
}

/**
 * Os PDFs não passam pelo cache nem pelo axios: são baixados com a sessão em CABEÇALHO
 * (`lib/arquivo.ts`). Aqui saem só os caminhos — `baseURL` é assunto do downloader.
 */
export function caminhoDoPdfDaOrdem(osId: string | number): string {
  return `/api/v1/manutencao/ordens/${osId}/pdf`
}

/** O PDF de UMA tarefa: a ficha respondida, sem as outras dezenas de páginas da OS. */
export function caminhoDoPdfDaTarefa(osId: string | number, tarefaId: number): string {
  return `/api/v1/manutencao/ordens/${osId}/tarefas/${tarefaId}/pdf`
}

/**
 * O erro é "esta OS não é sua / não existe"?
 *
 * As duas situações pedem telas diferentes: "não encontrada" é um estado vazio com o caminho
 * de volta — insistir nunca vai abrir aquela porta —, enquanto rede caída é um erro com
 * "Tentar de novo". Quem decide é o STATUS. A primeira versão casava a FRASE dos dois 404 do
 * `_ordem_autorizada` ("Ordem de serviço não encontrada."), e isso prendia a tela à prosa do
 * BFF: um ponto final a mais e o vazio viraria erro genérico, sem nada quebrar e sem ninguém
 * notar. `Leitura.status` nasceu deste caso.
 */
export function ehNaoEncontrada(leitura: Leitura<unknown>): boolean {
  return leitura.dados === null && leitura.status === 404
}
