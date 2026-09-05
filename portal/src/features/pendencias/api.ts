/**
 * Pendências — o contrato com o BFF (`bff/app/api/v1/pendencias.py`).
 *
 * O que o dono pediu (texto de 09/2026): *"se tiver alguma PENDÊNCIA que ele cobrou a gente,
 * ele quer ver lá, a pendência, igual tem no meuPlano, mas de forma mais simples"*. O "mais
 * simples" é o recorte que o BFF já faz: etapa, situação, prazo, última atividade, o que a
 * equipe respondeu, o que ela publicou e que ordem de serviço resolve. O resto do container
 * do meuPlano (a lista de conferência interna, os cartões filhos, a conversa da equipe) não
 * chega até aqui — não é falta, é o recorte.
 *
 * Tudo o que esta tela mostra é o que o servidor mandou:
 *
 * - `situacao`/`tom` já vêm traduzidos e coloridos pelo BFF, inclusive a regra de prazo
 *   vencido (que vira `tom = 'parado'` só quando passou E a pendência não concluiu). A tela
 *   NÃO recalcula nada disso — duas réguas para a mesma cor divergem no primeiro ajuste.
 * - Os contadores (`total`, `abertas`, `concluidas`, `prazo_vencido`) também são do servidor,
 *   e ficam NULOS quando alguma usina não respondeu. Somar na tela devolveria um número
 *   parcial com cara de completo.
 * - `parecer` e `descricao` chegam como TEXTO puro: o BFF converte o HTML do editor do
 *   meuPlano antes de mandar. Nada aqui vai para o DOM como marcação.
 */

import { abrirPdf, baixarArquivo } from '@/lib/arquivo'

/** Caminho da lista (também a chave de cache — uma por usina). */
export const caminhoDaLista = (usinaId: number) => `manutencao/pendencias?usina_id=${usinaId}`

/** Caminho do detalhe de UMA pendência. */
export const caminhoDoDetalhe = (cid: number) => `manutencao/pendencias/${cid}`

export type Pendencia = {
  id: number
  /** Número global do container no meuPlano — é assim que cliente e equipe se referem a ela. */
  numero: number | null
  usina: string
  /** Id do vínculo neste sistema: é por ele que o portal navega. */
  usina_id: number
  titulo: string
  /** Marcada pela equipe como cobrada pelo cliente — o recorte padrão da tela. */
  cobrada_pelo_cliente: boolean
  /** A coluna do funil, pelo nome ("A fazer", "Em andamento"…). */
  etapa: string | null
  /** Código cru do meuPlano. A tela lê `situacao` e `tom`; isto fica para auditoria. */
  status: string | null
  situacao: string
  tom: string
  /**
   * Em qual das TRÊS colunas do quadro esta pendência mora: `aguardando`, `em_andamento`
   * ou `concluida`. **Não é `situacao` em minúsculas.** O servidor deriva a coluna só do
   * status: uma pendência com prazo vencido continua em "aguardando", pintada de vermelho
   * por `tom`. Se o kanban agrupasse pela frase, a atrasada — justo a que importa — cairia
   * numa quarta coluna e discordaria dos contadores do topo.
   */
  coluna: string
  criticidade: string | null
  criticidade_tom: string | null
  /**
   * A posição na escala de criticidade (0 crítica … 4 sem criticidade declarada), crescente.
   * Vem do servidor porque a escala é dele: remontá-la aqui poria "média" depois de "baixa"
   * na primeira ordenação alfabética, e as duas telas ordenariam a mesma lista diferente.
   */
  criticidade_rank: number
  responsavel: string | null
  aberta_em: string | null
  prazo: string | null
  ultima_atividade_em: string | null
  /**
   * `hoje` | `7d` | `30d` | `+30d` — há quanto tempo ninguém mexe, medido pelo servidor no
   * fuso da usina. Nulo quando não há atividade datada: aí a tela mostra travessão, nunca
   * "+30d", que seria uma acusação inventada a partir de um campo ausente.
   */
  faixa_parada: string | null
  concluida_em: string | null
  /** O equipamento principal (o 1º vinculado), como o card do meuPlano mostra. */
  equipamento: string | null
  /** Quantos equipamentos ao todo — o card diz "principal +N". Nulo = o servidor não contou. */
  equip_count: number | null
  /** Subitem: o id da pendência-mãe. O meuPlano permite UM nível. */
  parent_id: number | null
  child_count: number | null
  /** Quantos documentos foram PUBLICADOS ao cliente. Nulo = o servidor não contou. */
  documentos: number | null
  os_count: number | null
}

export type PendenciasOut = {
  total: number | null
  abertas: number | null
  concluidas: number | null
  prazo_vencido: number | null
  /**
   * As três colunas do quadro, contadas pelo SERVIDOR. `aguardando + em_andamento +
   * concluidas` fecha com `total` por construção — os cartões do topo e as colunas do
   * kanban descrevem o mesmo conjunto, e o cliente não pode somar as colunas e achar um
   * número diferente do cartão.
   */
  aguardando: number | null
  em_andamento: number | null
  /** O que ELE cobrou e ainda não voltou. `abertas` conta o time todo; esta, só a marca dele. */
  cobradas_abertas: number | null
  pendencias: Pendencia[]
  usinas_com_manutencao: number
  aviso: string | null
}

export type DocumentoPendencia = {
  id: number
  nome: string
  publicado_em: string | null
  /** Caminho NO BFF: o endereço do meuPlano (aberto por id) nunca chega ao navegador. */
  url: string
}

/**
 * A ordem de serviço vinculada, como a pendência a mostra.
 *
 * É um recorte do `OrdemOut` do BFF — só o que cabe numa linha de "quem resolve isto". A
 * tela da OS (`/usinas/:id/manutencao/ordens/:osId`) tem o resto.
 */
export type OrdemVinculada = {
  id: number
  usina_id: number
  /** Número do CONTRATO que rege a OS — **nunca** o número da OS (que é o `id`). */
  contrato_numero: number | null
  objetivo: string
  /** Rótulo pronto do servidor ("Serviços adicionais"), nunca o código cru. */
  classificacao: string | null
  situacao: string
  tom: string
  agendada_para: string | null
  concluida_em: string | null
  tarefas: number | null
  tarefas_feitas: number | null
}

export type PendenciaDetalhe = Pendencia & {
  /** O que foi pedido, em texto. */
  descricao: string | null
  /** O que a equipe respondeu (`parecer_html` do meuPlano, já em texto). */
  parecer: string | null
  documentos_publicados: DocumentoPendencia[]
  ordens: OrdemVinculada[]
}

/**
 * Rótulo da criticidade.
 *
 * O BFF manda o código do meuPlano (`baixa|media|alta|critica`) junto com o tom, porque a
 * escala é dele. O mapa existe só pelo acento — "media" tem de sair "Média" —, e um código
 * novo aparece como veio, capitalizado: engoli-lo deixaria a coluna vazia sem ninguém saber.
 */
export function rotuloDaCriticidade(codigo: string | null): string | null {
  if (!codigo) return null
  const mapa: Record<string, string> = {
    baixa: 'Baixa',
    media: 'Média',
    alta: 'Alta',
    critica: 'Crítica',
  }
  const chave = codigo.trim().toLowerCase()
  if (!chave) return null
  return mapa[chave] ?? `${chave.charAt(0).toUpperCase()}${chave.slice(1)}`
}

/**
 * Abre um documento publicado da pendência.
 *
 * Sempre com a sessão no CABEÇALHO (`lib/arquivo`): a rota do BFF exige `Authorization`, e a
 * saída fácil — token na query — é a proibida. PDF abre em aba (é o formato de laudo e de
 * relatório, e o cliente quer LER, não guardar); qualquer outro tipo baixa com o nome que a
 * equipe deu, porque um Blob aberto numa aba perderia esse nome.
 *
 * Chame de dentro do `onClick` — é o gesto do usuário que autoriza a aba nova.
 */
export async function abrirDocumento(doc: DocumentoPendencia): Promise<void> {
  if (/\.pdf$/i.test(doc.nome)) {
    await abrirPdf(doc.url, doc.nome)
    return
  }
  await baixarArquivo(doc.url, doc.nome)
}
