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
  /** Número do CONTRATO que rege a OS (não o número da OS). Nulo em OS sem contrato. */
  numero: number | null
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
 * O terceiro bloco existe para não ESCONDER OS: uma cancelada não é "em andamento" nem
 * "concluída", e com dois blocos ela simplesmente sumiria da tela — o cliente contaria menos
 * ordens do que o total que o servidor mandou, sem nada explicando a diferença.
 */
export type Bloco = 'andamento' | 'concluidas' | 'outras'

const EM_CURSO = new Set(['ABERTA', 'PROGRAMADA', 'EM_EXECUCAO', 'FECHADA'])

export function blocoDaOrdem(o: Ordem): Bloco {
  const chave = (o.status ?? '').trim().toUpperCase()
  if (EM_CURSO.has(chave)) return 'andamento'
  if (chave === 'APROVADA') return 'concluidas'
  return 'outras'
}

/**
 * A classificação chega em caixa alta com underscore ("SERVICOS_ADICIONAIS").
 *
 * O tom não é decoração: corretiva é conserto (algo quebrou), preventiva é rotina cumprida —
 * ler a diferença de relance é metade do valor desta tela. Mesma régua do aplicativo
 * (`app/src/app/(tabs)/manutencao.tsx`), para quem usa os dois ler a mesma cor.
 */
export function tomDaClasse(c: string | null): string {
  const v = (c ?? '').toUpperCase()
  if (v.includes('CORRETIVA')) return 'alerta'
  if (v.includes('PREVENTIVA')) return 'ok'
  return 'semDados'
}

export function rotuloDaClasse(c: string | null): string {
  if (!c) return 'sem classificação'
  const limpo = c.replace(/_/g, ' ').toLowerCase()
  return limpo.charAt(0).toUpperCase() + limpo.slice(1)
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
