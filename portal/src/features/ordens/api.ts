/**
 * O contrato de `GET /api/v1/manutencao/ordens` — a lista de ordens de serviço da usina.
 *
 * Os tipos são o espelho de `OrdensOut`/`OrdemOut` em `bff/app/api/v1/manutencao.py`. Duas
 * coisas que vêm PRONTAS do servidor e não se recalculam aqui:
 *
 * - **`situacao` e `tom`.** "FECHADA" no meuPlano não quer dizer "encerrada": quer dizer que
 *   o técnico concluiu e o gestor ainda não conferiu — e o BFF ainda melhora a frase quando
 *   todas as tarefas estão feitas ("Executada · aguardando verificação"). Traduzir de novo na
 *   tela criaria uma segunda versão da mesma verdade, que é como duas telas do mesmo produto
 *   passam a discordar.
 * - **`em_andamento`.** Qual é "a OS de agora" é regra do servidor. Sem esse campo a tela
 *   teria de reproduzir a régua, e ela mudaria em dois lugares.
 *
 * O que fica aqui é só o que é de TELA: em que bloco a OS entra (em andamento × concluída) e
 * como se escreve a classificação.
 */

import { useLeitura, type Leitura } from '@/lib/leitura'

export type Ordem = {
  id: number
  usina: string
  /** `id` do vínculo neste sistema — é por ele que a rota navega, não pelo id do meuPlano. */
  usina_id: number
  /** Número do CONTRATO que rege a OS. **Nunca** o número da OS — ela não tem um: a
   * identidade dela é o `id`. O nome antigo (`numero`) fez o drawer da pendência imprimir
   * "OS #665" para o contrato 665, enquanto a lista chamava a mesma ordem de "OS 1016". */
  contrato_numero: number | null
  /** Rótulo pronto ("Serviços adicionais"); o código cru fica em `classificacao_codigo`. */
  classificacao_codigo?: string | null
  classificacao_tom?: string
  /** Já resolvido no servidor: objetivo → nome → título do contrato → "OS {id}". */
  objetivo: string
  classificacao: string | null
  /** Código cru do meuPlano, para auditoria. A tela mostra `situacao`. */
  status: string | null
  /** A frase pronta que a tela exibe. */
  situacao: string
  /** Um dos seis tons, decidido pelo servidor. */
  tom: string
  tecnico: string | null
  /** Nulo = o upstream não informou. ZERO é resposta legítima e não pode virar nulo. */
  tarefas: number | null
  tarefas_feitas: number | null
  agendada_para: string | null
  concluida_em: string | null
  fechada_em: string | null
  aprovada_em: string | null
  execucao_min: number | null
  resumo: string | null
}

export type OrdensOut = {
  /** Nulo = NENHUMA usina respondeu. Zero = não há OS, que é uma afirmação diferente. */
  total: number | null
  /** A OS não encerrada mais recente, escolhida pelo servidor. */
  em_andamento: Ordem | null
  ordens: Ordem[]
  usinas_com_manutencao: number
  aviso: string | null
}

/** A leitura da tela. `usinaId` nulo desliga a consulta — sem usina não há o que pedir. */
export function useOrdens(usinaId: number | null): Leitura<OrdensOut> {
  return useLeitura<OrdensOut>(`manutencao/ordens?usina_id=${usinaId}`, {
    ativo: usinaId !== null,
  })
}

/**
 * Em que bloco da tela a OS entra.
 *
 * O conjunto é o mesmo `EM_CURSO` de `bff/app/api/v1/manutencao.py` — e `FECHADA` entra nele
 * de propósito: a OS está esperando a verificação do gestor, ou seja, ainda pede algo de
 * alguém. É o estado da preventiva que o dono mais acompanha, e jogá-la em "concluídas" diria
 * que o assunto acabou.
 *
 * **Cancelada tem bloco próprio, e ele não vira aba.** A pergunta desta tela é "está sendo
 * feito?", e uma OS cancelada não está sendo feita nem foi feita — dar a ela uma aba ao lado
 * de "Em andamento" foi o que colocou duas ordens de teste ("GATE aud5", técnico "T") na
 * frente do cliente. Ela também não some calada: o rodapé conta quantas foram canceladas, e
 * o total continua batendo.
 *
 * "Outras" sobra para um estado NOVO do meuPlano — que precisa aparecer, justamente por ser
 * desconhecido daqui.
 */
export type Bloco = 'andamento' | 'concluidas' | 'outras' | 'cancelada'

/** Os blocos que viram aba, na ordem em que aparecem. */
export const BLOCOS_VISIVEIS: Bloco[] = ['andamento', 'concluidas', 'outras']

const EM_CURSO = new Set(['ABERTA', 'PROGRAMADA', 'EM_EXECUCAO', 'FECHADA'])

export function blocoDaOrdem(o: Ordem): Bloco {
  const chave = (o.status ?? '').trim().toUpperCase()
  if (EM_CURSO.has(chave)) return 'andamento'
  if (chave === 'APROVADA') return 'concluidas'
  if (chave === 'CANCELADA') return 'cancelada'
  return 'outras'
}


/**
 * A data que vale para esta OS: a de conclusão quando existe, senão a de agendamento, senão a
 * do fechamento pelo técnico. É a mesma cascata que o servidor usa para ordenar a lista — se
 * a tela escolhesse outra, a coluna de data apareceria fora de ordem.
 */
export function dataDaOrdem(o: Ordem): string | null {
  return o.concluida_em ?? o.agendada_para ?? o.fechada_em
}

/**
 * Quanto da OS já foi cumprido, em porcentagem — ou nulo quando não dá para saber.
 *
 * Sem total, sem barra: uma barra vazia se leria como "nada feito", que é uma afirmação, e
 * "não sabemos quantas tarefas tem" é outra.
 */
export function pctDeTarefas(o: Ordem): number | null {
  if (o.tarefas === null || o.tarefas_feitas === null || o.tarefas <= 0) return null
  return (o.tarefas_feitas / o.tarefas) * 100
}
