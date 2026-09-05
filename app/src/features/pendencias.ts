/**
 * Pendências — o que a equipe deve ao dono da usina, e o que ele mesmo cobrou.
 *
 * A aba Manutenção responde "a manutenção contratada está sendo feita?". Esta lista responde
 * a outra metade: **"e o que ficou pendente?"**. São as pendências que a equipe marcou como
 * compartilháveis no meuPlano — o mesmo corte do portal, feito no servidor (duas cercas: a do
 * meuPlano e a do BFF), nunca aqui.
 *
 * No celular ela é **lista**, não quadro. O kanban do portal é leitura de mouse: colunas lado
 * a lado numa tela de 390 px viram três colunas ilegíveis, e arrastar — que é o gesto que um
 * quadro promete — o cliente não pode fazer em lugar nenhum, porque ele é leitor.
 *
 * Os campos vêm com o nome do servidor, como no resto do aplicativo. `situacao`, `tom`,
 * `coluna`, `criticidade_tom` e `criticidade_rank` são DECISÕES do BFF: frase, cor, em que
 * coluna a pendência mora e onde ela entra na escala. A tela não reinterpreta nenhuma —
 * foi remontar a régua de prazo do lado errado que fez o cartão "Prazo vencido" marcar zero
 * com linhas vermelhas logo abaixo.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'

export type Pendencia = {
  id: number
  /** Número GLOBAL do contêiner no meuPlano — é como a equipe e o cliente se referem a ela. */
  numero: number | null
  usina: string
  /** `id` do vínculo NESTE sistema. */
  usina_id: number
  titulo: string
  /** Marcada pela equipe como cobrada pelo cliente. É o recorte que abre a tela. */
  cobrada_pelo_cliente: boolean
  /** A coluna do funil, pelo nome ("A fazer", "Em andamento", "Parado"…). */
  etapa: string | null
  /** Código cru, para auditoria. A tela lê `situacao` e `tom`. */
  status: string | null
  situacao: string
  tom: string
  /**
   * `aguardando` · `em_andamento` · `concluida`. Deriva SÓ do status, e é por ela que a
   * lista filtra: `situacao` vira "Prazo vencido" quando a data passa, e filtrar pela frase
   * faria a pendência atrasada sumir de todos os recortes.
   */
  coluna: string
  criticidade: string | null
  criticidade_tom: string | null
  /** 0 = crítica … 4 = sem criticidade declarada. Ordenar por ela é crescente. */
  criticidade_rank: number
  responsavel: string | null
  aberta_em: string | null
  /** O prazo combinado, já resolvido no servidor (previsão de conclusão antes de `end_date`). */
  prazo: string | null
  ultima_atividade_em: string | null
  /** `hoje` | `7d` | `30d` | `+30d`. Nulo = sem atividade datada — a tela mostra travessão. */
  faixa_parada: string | null
  concluida_em: string | null
  /** O equipamento principal; `equip_count` diz quantos há ao todo. */
  equipamento: string | null
  equip_count: number | null
  /** Quantos documentos PUBLICADOS ao cliente. Nulo = o servidor não contou. */
  documentos: number | null
  os_count: number | null
}

export type PendenciasOut = {
  /**
   * Nulos quando ALGUMA usina não respondeu: um total parcial parece completo e não é.
   * Zero é "nenhuma pendência", que é outra coisa — e por isso nenhum deles vira `0` aqui.
   */
  total: number | null
  abertas: number | null
  concluidas: number | null
  prazo_vencido: number | null
  aguardando: number | null
  em_andamento: number | null
  /** O que ELE cobrou e ainda não voltou. É o contador que decide com que aba a tela abre. */
  cobradas_abertas: number | null
  pendencias: Pendencia[]
  usinas_com_manutencao: number
  aviso: string | null
}

/**
 * As pendências compartilhadas. Sem `usinaId`, as de todas as usinas da pessoa.
 *
 * A usina entra na CHAVE do cache e não só na query: com uma chave só, trocar de usina
 * mostraria a lista da anterior por um instante — e no modo offline, para sempre.
 */
export function usePendencias(usinaId?: number): Leitura<PendenciasOut> {
  const chave = usinaId ? `manutencao/pendencias-${usinaId}` : 'manutencao/pendencias'
  return fetchWithCache<PendenciasOut>(chave, {
    caminho: usinaId
      ? `/api/v1/manutencao/pendencias?usina_id=${usinaId}`
      : '/api/v1/manutencao/pendencias',
  })
}
