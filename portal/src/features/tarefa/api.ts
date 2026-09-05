/**
 * O contrato da FICHA de uma tarefa, como o BFF a devolve
 * (`bff/app/api/v1/manutencao.py`: `FichaOut`, `EquipamentoFichaOut`, `MedicaoOut`,
 * `PerguntaOut`, `FotoOut`).
 *
 * Cópia fiel do servidor, com as mesmas regras que valem no resto do portal: nada de campo
 * obrigatório onde o BFF declara `| None`, e nenhum nulo virando zero.
 *
 * Duas armadilhas do contrato, que estão nos tipos de propósito:
 *
 * **`aprovado` e `situacao` são coisas diferentes.** `aprovado` é o julgamento (sim, não, e
 * "não se aplica" quando nulo); `situacao` é o RÓTULO que o laudo imprime quando o item não é
 * julgamento e sim estado — "Não feito" num item de serviço. Eram o mesmo campo do lado do
 * meuPlano, e um item de torque com `aprovado: "Aprovado"` derrubava a ficha inteira; foi por
 * isso que a manutenção mensal dos inversores de Porto Ferreira nunca abria (04/09/2026).
 *
 * **`Ficha.fotos` é um NÚMERO** — a contagem —, não a lista. As fotos moram em
 * `equipamento.fotos` (sessão + respostas, já reunidas) e em `pergunta.fotos` (as daquela
 * resposta). Quem desenha precisa de `Array.isArray` em toda parte: durante o deploy do BFF
 * as duas formas convivem, e o cache de leitura guarda a antiga em disco.
 */

import { type Tarefa as TarefaDaOrdem } from '@/features/ordem/api'
import { useLeitura, type Leitura } from '@/lib/leitura'

/**
 * A tarefa em si (cabeçalho) e os utilitários dela vêm da tela da ordem — é o mesmo
 * `TarefaOut` do BFF, e uma segunda cópia divergiria na primeira mudança do contrato.
 */
export type { Tarefa } from '@/features/ordem/api'
export { caminhoDoPdfDaTarefa, ehNaoEncontrada } from '@/features/ordem/api'

/** Uma evidência anexada pelo técnico. A `url` é do BFF — é lá que a sessão vale. */
export type Foto = {
  id: number
  legenda: string | null
  url: string
  thumb_url: string
}

/** Um ponto medido. Ver a nota sobre `aprovado` × `situacao` no cabeçalho do módulo. */
export type LinhaMedicao = {
  ponto: string
  valor: string | null
  unidade: string | null
  alvo: string | null
  desvio: string | null
  aprovado: boolean | null
  situacao: string | null
  observacao: string | null
}

export type Medicao = {
  nome: string
  unidade: string | null
  linhas: LinhaMedicao[]
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
  /** Já vem escrito pelo meuPlano ("12/08/2026 14:30") — não é ISO para formatar aqui. */
  executado_em: string | null
  executado_por: string | null
  parecer: string | null
  parecer_motivo: string | null
  medicoes: Medicao[]
  checklist: SecaoChecklist[]
  /** TODAS as do equipamento — as da sessão e as das respostas, já reunidas pelo servidor. */
  fotos: Foto[]
}

export type Ficha = {
  id: number | null
  nome: string | null
  coletiva: boolean
  parecer: string | null
  equipamentos: EquipamentoDaFicha[]
  /** A CONTAGEM de fotos da ficha, não a lista. Ver o cabeçalho do módulo. */
  fotos: number
}

/**
 * O cabeçalho da tarefa — o que era, em que equipamento, como terminou.
 *
 * Leitura barata, separada da ficha de propósito: é ela que desenha a tela, e esperar as
 * respostas para mostrar o nome da tarefa deixaria a página em branco por segundos.
 */
export function useTarefa(
  osId: string | undefined,
  taskId: string | undefined,
): Leitura<TarefaDaOrdem> {
  return useLeitura<TarefaDaOrdem>(`manutencao/ordem-${osId ?? ''}-tarefa-${taskId ?? ''}`, {
    caminho: `/api/v1/manutencao/ordens/${osId ?? ''}/tarefas/${taskId ?? ''}`,
    // Sem os dois ids a consulta fica desligada; senão o caminho viraria `/ordens//tarefas/`.
    ativo: Boolean(osId && taskId),
  })
}

/**
 * As RESPOSTAS da tarefa.
 *
 * A leitura mais cara do portal: uma ficha coletiva de vinte inversores é montada do zero no
 * meuPlano, depois da cadeia de autorização do BFF. Com os 30 s do padrão, a ficha da
 * manutenção mensal dos inversores não abre — daí o prazo próprio, que é por chamada
 * justamente para não pendurar as outras telas quando a rede cair de verdade.
 */
export function useFicha(osId: string | undefined, taskId: string | undefined): Leitura<Ficha> {
  return useLeitura<Ficha>(`manutencao/ordem-${osId ?? ''}-ficha-${taskId ?? ''}`, {
    caminho: `/api/v1/manutencao/ordens/${osId ?? ''}/tarefas/${taskId ?? ''}/ficha`,
    ativo: Boolean(osId && taskId),
    prazoMs: 60_000,
  })
}
