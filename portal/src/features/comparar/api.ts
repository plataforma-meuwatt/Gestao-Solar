/**
 * O contrato dos dois comparativos de carteira — o espelho, em TypeScript, do
 * `ComparativoOut` do BFF (`bff/app/api/v1/carteira.py`).
 *
 * `GET /api/v1/carteira/comparativo?de&ate&blocos=energia|manutencao`. Uma leitura por
 * família: quem abre "Comparar usinas" não espera as cinco idas por usina que a manutenção
 * custa, e quem abre "Comparar manutenção" não espera o monitoramento. É o mesmo corte que
 * o menu já faz — quem cobra kWh não abre ordem de serviço.
 *
 * **Não existe parâmetro de usina.** O conjunto comparado é sempre o escopo de quem está
 * logado; um id vindo daqui não acrescentaria usina nenhuma — e não poderia, porque só o
 * nome de uma usina alheia já seria vazamento.
 *
 * **Todo número é `number | null`, e o `null` é informação.** Nulo é "não deu para ler" ou
 * "não existe medição"; zero é medição. Num RANKING a diferença é a mais cara do portal: um
 * zero fabricado no fim da lista é uma acusação, e parece um número. Por isso a usina sem PR
 * sai do ranking de PR — vai para `fora`, com o motivo escrito — em vez de aparecer com
 * 0 %. A tela nunca inventa o número que falta e nunca refaz o que o servidor já calculou:
 * ordenação, janela comum e percentual em dia vêm prontos de `services/carteira.py`, e
 * repeti-los aqui criaria a segunda resposta para a mesma pergunta.
 */

import { competenciaCurta, inteiro } from '@/lib/format'
import { daData, paraIso, type Recorte } from '@/lib/periodo'
import { useLeitura, type Leitura } from '@/lib/leitura'

/* ------------------------------------------------------------------ janela */

/**
 * O período efetivamente comparado — e o que ele deixou de fora.
 *
 * Sem este bloco a tela mostraria um ranking de doze meses contra um de quatro sem nenhum
 * sinal de que os dois não são comparáveis.
 */
export type JanelaOut = {
  de: string
  ate: string
  /** Todos os meses do período pedido, em ordem (`YYYY-MM`). */
  meses: string[]
  /** A interseção dos meses REALMENTE medidos por todas as usinas com dado. */
  meses_comuns: string[]
  /** "ago de 2026", "jun a set de 2026" — a frase pronta que a tela carimba. */
  rotulo: string | null
  /** A interseção cobre o período inteiro. Falso = a comparação é mais estreita. */
  completa: boolean
  /**
   * Quem tirou mês da interseção, da mordida maior para a menor. É o NOME que impede o
   * cliente de ler "jun a set" e concluir que o portal perdeu dados: com ele, entende que
   * uma usina entrou depois.
   */
  encolhida_por: string[]
  /** Usinas sem UM mês medido no período: saem da comparação em vez de virar zero. */
  fora_da_comparacao: string[]
  /** Usinas cujo detalhe mensal não veio. "Não sabemos" não é "não tem". */
  sem_detalhe: string[]
  /**
   * Quantas usinas a janela cobre — o "de N" dos totais. Só tem sentido com
   * `cobertura_conferida`: sem o bloco de energia ninguém foi perguntar ao monitoramento
   * que meses cada usina mediu, e o zero significa "não perguntei", não "nenhuma".
   */
  comparaveis: number
  /**
   * Alguém REALMENTE conferiu a cobertura mês a mês. Falso = a janela é a pedida, e a tela
   * NÃO pode escrever "N de M usinas entram nesta comparação" — foi assim que o rodapé de
   * manutenção passou a dizer "0 de 7" embaixo de uma tabela com usina ranqueada em 1º.
   */
  cobertura_conferida: boolean
  /** A frase pronta do servidor, quando há o que explicar. */
  nota: string | null
  /** `ate` foi travado em hoje: pedir o mês em curso é legítimo, fingir que mediu o futuro não. */
  truncada_em_hoje: boolean
}

/* ------------------------------------------------------------------ ranking */

export type ItemRankingOut = {
  /** 1 = melhor. Empate DIVIDE a posição (1, 1, 3): desempatar por nome coroaria a inicial. */
  posicao: number
  usina_id: number
  usina: string
  valor: number
  empatado: boolean
  /** O "de N" que acompanha percentual. Nulo nos rankings que não são percentuais. */
  denominador: number | null
}

export type RankingOut = {
  /** `produtividade` | `energia` | `pr` | `atraso` | `cumprimento` | `pendencias_vencidas`. */
  chave: string
  titulo: string
  /** A pergunta que ESTE ranking responde, na voz do cliente — redigida no servidor. */
  pergunta: string
  /** A frase que desarma a leitura errada deste ranking. */
  nota: string | null
  unidade: string | null
  /** `desc` = maior primeiro. Em atraso e pendências vencidas, menos é melhor (`asc`). */
  ordem: string
  itens: ItemRankingOut[]
  /** Quem ficou DE FORA, com o motivo. Sem esta lista a ausência vira suspeita de erro. */
  fora: string[]
}

/* ------------------------------------------------------------------ energia */

export type UsinaEnergiaOut = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null

  capacidade_kwp: number | null
  /** Energia do PERÍODO PEDIDO — o mesmo número de `/desempenho` e o que `/resumo` soma. */
  energia_kwh: number | null
  /** Só dos meses da JANELA COMUM. É esta que alimenta o ranking. */
  energia_comparavel_kwh: number | null
  /** kWh/kWp — a única régua que sobrevive a capacidades diferentes. */
  produtividade_kwh_kwp: number | null
  /** Nulo sem POA medida: 0 % de PR não é medição, é a ausência dela. */
  pr_pct: number | null
  disponibilidade_real_pct: number | null
  disponibilidade_contratual_pct: number | null
  /** Zero é legítimo (houve dado, não houve perda). Nulo é "não houve dado". */
  perdas_paradas_kwh: number | null
  /** Contexto obrigatório do ranking: "rende melhor" ainda contém "teve mais sol". */
  irradiacao_hpoa: number | null
  irradiacao_ghi: number | null
  paradas_pendentes: number | null

  meses_medidos: string[]
  /** Por que esta usina não tem número. Ela continua na lista, com travessão. */
  motivo: string | null
}

export type TotaisEnergiaOut = {
  /** De quantas usinas este total fala. Sem ele, "3,2 GWh" parece a carteira inteira. */
  usinas_no_total: number
  /** Σ do período PEDIDO, de todas as usinas com medição — outra pergunta que a manchete. */
  energia_kwh: number | null
  /** Σ da capacidade de TODAS as usinas, inclusive as que ficaram fora da comparação. */
  capacidade_kwp: number | null
  /** Σ energia da JANELA COMUM, só das `usinas_no_total`. É o numerador da produtividade. */
  energia_comparavel_kwh: number | null
  /** Σ capacidade das MESMAS usinas do numerador. É o denominador da produtividade. */
  capacidade_comparavel_kwp: number | null
  produtividade_kwh_kwp: number | null
  perdas_paradas_kwh: number | null
}

export type BlocoEnergiaOut = {
  usinas: UsinaEnergiaOut[]
  totais: TotaisEnergiaOut
  rankings: RankingOut[]
}

/* --------------------------------------------------------------- manutenção */

export type UsinaManutencaoOut = {
  id: number
  nome: string
  contrato: string | null
  contrato_id: number | null

  /** Σ das ocorrências previstas nos meses da janela. Nulo não é "nada previsto". */
  previsto: number | null
  feitas: number | null
  /** Dispensa registrada com motivo. NUNCA se soma a `feitas`. */
  dispensadas: number | null
  atrasadas: number | null
  /** `feitas + dispensadas + atrasadas` — o denominador que a tela imprime ao lado. */
  denominador: number | null
  cumprimento_pct: number | null
  /** "13 de 31", montado no servidor. Sozinho, 41,9 % não quer dizer nada. */
  cumprimento_rotulo: string | null
  /** "18 ainda no prazo — fora da conta." Nulo quando nada foi excluído. */
  fora_da_conta: string | null

  os_em_andamento: number | null
  pendencias_abertas: number | null
  pendencias_vencidas: number | null
  pendencias_cobradas: number | null
  /**
   * Das abertas, as de criticidade `critica`.
   *
   * Não é "urgente": a ordem de serviço que chega a este BFF não tem campo de prioridade, e
   * o servidor escolheu a criticidade da pendência em vez de inventar um. A tela repete a
   * palavra do servidor pelo mesmo motivo.
   */
  pendencias_criticas: number | null

  /** "Cronograma não publicado neste contrato" — o travessão vem com o porquê. */
  motivo: string | null
}

export type TotaisManutencaoOut = {
  usinas_no_total: number
  previsto: number | null
  feitas: number | null
  dispensadas: number | null
  atrasadas: number | null
  denominador: number | null
  cumprimento_pct: number | null
  cumprimento_rotulo: string | null
  os_em_andamento: number | null
  pendencias_abertas: number | null
  pendencias_vencidas: number | null
}

export type BlocoManutencaoOut = {
  usinas: UsinaManutencaoOut[]
  totais: TotaisManutencaoOut
  rankings: RankingOut[]
}

export type ComparativoOut = {
  janela: JanelaOut
  energia: BlocoEnergiaOut | null
  manutencao: BlocoManutencaoOut | null
  /** Quantas usinas o escopo desta pessoa tem — o "de N" de tudo o que está acima. */
  usinas_no_escopo: number
  aviso: string | null
}

/* ------------------------------------------------------------------ período */

/**
 * Mês ou ano — nunca um intervalo de datas livre.
 *
 * Não é preciosismo de interface. As datas que este comparativo manda são as MESMAS que
 * `/plants/{id}/desempenho` monta, e é isso que faz a leitura cair na entrada de cache de
 * 10 min já quente do monitoramento. Um seletor de datas livre produziria uma janela
 * diferente a cada abertura — sete `miss` de uma vez, numa tela que já faz uma ida por usina.
 */
export const RECORTES_ACEITOS = ['mes', 'ano'] as const

/** `YYYY-MM-DD` de verdade. Endereço truncado pelo cliente de e-mail cai no padrão. */
export const dataIso = (v: string) =>
  /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v))

/**
 * O período escolhido traduzido no par `de`/`ate` que o BFF espera.
 *
 * O início é sempre o primeiro dia do recorte, e o fim o último — não o dia em que o cliente
 * está. Assim a chave do cache é uma por mês (ou por ano), e não uma por dia de consulta:
 * abrir a mesma tela hoje e amanhã não repete sete idas ao monitoramento. O fim no futuro
 * não é problema: o servidor trava em hoje e DIZ que travou (`truncada_em_hoje`).
 */
export function intervaloDe(referencia: string, recorte: Recorte): { de: string; ate: string } {
  const d = daData(referencia)
  if (recorte === 'ano') {
    return { de: paraIso(new Date(d.getFullYear(), 0, 1)), ate: paraIso(new Date(d.getFullYear(), 11, 31)) }
  }
  // Dia 0 do mês seguinte = último dia deste mês, sem tabela de 28/30/31 nem bissexto.
  return {
    de: paraIso(new Date(d.getFullYear(), d.getMonth(), 1)),
    ate: paraIso(new Date(d.getFullYear(), d.getMonth() + 1, 0)),
  }
}

/**
 * O rodapé fixo dos dois comparativos: de que janela esta comparação está falando.
 *
 * As frases moram aqui, e não em cada tela, porque é O QUE ELAS DIZEM que pode divergir — e
 * duas telas dizendo coisas diferentes sobre a mesma janela é o defeito que este projeto já
 * pagou caro. O desenho da lista fica em cada página; a afirmação, não.
 *
 * A ordem é a da leitura: primeiro o período comparado, depois por que ele encolheu (com o
 * NOME de quem o encolheu — sem ele o cliente conclui que o portal perdeu dados), depois
 * quem ficou de fora e por fim a nota que o próprio servidor redigiu.
 */
export function frasesDaJanela(janela: JanelaOut, usinasNoEscopo: number): string[] {
  const frases: string[] = []
  const comuns = janela.meses_comuns.length
  const pedidos = janela.meses.length

  if (janela.rotulo) {
    frases.push(
      janela.completa
        ? `Comparação de ${janela.rotulo} — o período inteiro que você pediu.`
        : `Comparação de ${janela.rotulo}: ${inteiro(comuns)} dos ${inteiro(pedidos)} meses do período, os únicos que todas as usinas mediram.`,
    )
  }
  if (janela.encolhida_por.length > 0) {
    frases.push(
      `O período foi encolhido por ${janela.encolhida_por.join(', ')} — ${
        janela.encolhida_por.length === 1 ? 'ela não mediu' : 'elas não mediram'
      } todos os meses que as outras mediram (entrada mais recente ou buraco de medição).`,
    )
  }
  if (janela.fora_da_comparacao.length > 0) {
    frases.push(
      `Fora da comparação, por não ter medição nenhuma no período: ${janela.fora_da_comparacao.join(', ')}.`,
    )
  }
  if (janela.sem_detalhe.length > 0) {
    frases.push(
      `Sem detalhe mensal, então a cobertura não foi conferida: ${janela.sem_detalhe.join(', ')}. Não saber não é o mesmo que não ter — por isso continuam na conta.`,
    )
  }
  if (janela.truncada_em_hoje) {
    frases.push('O período ainda está em curso: o fim foi travado em hoje.')
  }
  // A frase do "de N" SÓ existe quando a cobertura foi conferida de verdade. Com
  // `blocos=manutencao` ninguém foi ao monitoramento perguntar que meses cada usina mediu:
  // o campo fica no default e a frase dizia "0 de 7 usinas entram nesta comparação" logo
  // abaixo de uma tabela com Porto Ferreira em 1º. Quem conta a população da manutenção é o
  // cabeçalho dela ("N de M com cronograma publicado"), que sai dos totais do próprio bloco.
  if (janela.cobertura_conferida) {
    frases.push(
      `${inteiro(janela.comparaveis)} de ${inteiro(usinasNoEscopo)} usinas da sua carteira entram nesta comparação.`,
    )
  }
  if (janela.nota) frases.push(janela.nota)
  return frases
}

/** Os meses da janela comum, por extenso — para a tela mostrar de onde saiu o recorte. */
export function mesesDaJanela(janela: JanelaOut): string {
  return janela.meses_comuns.map((m) => competenciaCurta(m)).join(' · ')
}

/* ------------------------------------------------------------------ leitura */

/**
 * Prazo próprio do comparativo, pelo mesmo motivo da carteira da Visão geral: são sete
 * usinas contra dois upstreams e, com o padrão de 30 s, a tela cairia em "a conexão demorou
 * demais" com o servidor respondendo 200 do outro lado.
 */
const PRAZO_DA_CARTEIRA_MS = 120_000

/**
 * O comparativo de UMA família, num período.
 *
 * `de`/`ate` são `YYYY-MM-DD` e entram na chave do cache: cada período guarda o seu, então
 * andar para trás e voltar não repete a viagem, e o período aberto ontem reabre na hora —
 * com o selo de offline em cima — quando a rede estiver fora.
 */
export function useComparativo(
  bloco: 'energia' | 'manutencao',
  de: string,
  ate: string,
): Leitura<ComparativoOut> {
  return useLeitura<ComparativoOut>(
    `carteira/comparativo?de=${de}&ate=${ate}&blocos=${bloco}`,
    { prazoMs: PRAZO_DA_CARTEIRA_MS },
  )
}

/* ------------------------------------------- ordenação, a partir do servidor */

const porNome = (a: { nome: string }, b: { nome: string }) => a.nome.localeCompare(b.nome, 'pt-BR')

/**
 * As linhas na ordem do ranking escolhido — e as sem número no fim.
 *
 * A ORDEM é a que o servidor mandou (`ranking.itens`, já com empate dividindo posição); a
 * tela só casa por id. Reordenar por valor aqui criaria a segunda régua para a mesma
 * pergunta — e a régua da tela não sabe que valor ausente NÃO é zero. O caso concreto: o
 * ranking de energia é por `energia_comparavel_kwh` (só os meses da janela comum), e ordenar
 * pela coluna `energia_kwh` que está na tela daria um pódio diferente do que o servidor
 * publicou, na mesma tela, sem nada quebrar.
 *
 * **A lista abre sempre pelo MAIOR valor** — uma direção de leitura só, nas seis réguas. Não
 * é uma segunda ordenação: é a mesma lista do servidor, lida da ponta que a pergunta procura
 * ("qual está mais atrasada", "qual gera mais"), e quem está na frente de quem nunca muda.
 *
 * Por que uma direção fixa, e não "1º primeiro": o `posicao` do servidor NÃO tem um sentido
 * único. Em `atraso` e `pendencias_vencidas` ele marca 1º para a MELHOR situação (menos
 * atrasadas, menos vencidas); em `cumprimento` ele marca 1º para a PIOR (menor percentual) —
 * as três são construídas com o mesmo `maior_e_melhor=False`, e o significado de "melhor"
 * vira com a polaridade da métrica. Seguir o posto deixaria a resposta de "qual está mais
 * atrasada" no rodapé da tabela, onde ninguém olha, e ainda assim não daria consistência.
 * Com o maior sempre no topo, a régua de leitura é a mesma nas seis, e a legenda que
 * acompanha o posto (`legendaDoPosto`) diz o que ele significa naquela — em vez de a tela
 * afirmar quem é "melhor", que é justamente o que ela não pode saber.
 *
 * Quem não está no ranking vem depois, em ordem alfabética: não tem número para ordenar, e
 * jogá-lo no fim com um zero seria exatamente a mentira que o `fora` do servidor existe para
 * evitar. Na tela essa linha aparece com travessão e o motivo ao lado.
 */
export function naOrdemDoRanking<T extends { id: number; nome: string }>(
  linhas: T[],
  ranking: RankingOut | null,
): { ranqueadas: T[]; semNumero: T[] } {
  if (!ranking) return { ranqueadas: [...linhas].sort(porNome), semNumero: [] }
  const ranqueado = new Set(ranking.itens.map((i) => i.usina_id))
  // `sort` estável sobre a lista JÁ ordenada pelo servidor: empate mantém a ordem que ele
  // publicou, e nunca se inventa um desempate.
  const naOrdem =
    ranking.ordem === 'asc' ? [...ranking.itens].reverse() : [...ranking.itens]
  const ranqueadas = naOrdem
    .map((i) => linhas.find((l) => l.id === i.usina_id))
    .filter((l): l is T => l !== undefined)
  const semNumero = linhas.filter((l) => !ranqueado.has(l.id)).sort(porNome)
  return { ranqueadas, semNumero }
}

/**
 * O que o posto significa neste ranking — só quando ele não é óbvio.
 *
 * A frase é FACTUAL e derivada de `ordem`: "1º é o menor valor" / "1º é o maior valor". Ela
 * não diz quem é melhor, porque a tela não pode saber — em `atraso` o menor valor é a melhor
 * situação e em `cumprimento` é a pior, e as duas chegam com o mesmo `ordem: 'asc'`. Onde o
 * topo da lista JÁ é o 1º não há o que explicar, e a frase seria ruído.
 */
export function legendaDoPosto(ranking: RankingOut | null): string | null {
  if (!ranking || ranking.ordem !== 'asc') return null
  return 'A lista abre pelo maior valor; o posto é o do ranking do servidor, em que 1º é o menor.'
}

/** A posição de cada usina num ranking, para a tela carimbar o posto sem recontar nada. */
export function posicoesDo(ranking: RankingOut | null): Map<number, ItemRankingOut> {
  return new Map((ranking?.itens ?? []).map((i) => [i.usina_id, i]))
}

/**
 * O ranking pedido na URL, ou o primeiro da lista.
 *
 * O primeiro NÃO é escolha da tela: o servidor entrega produtividade à frente de energia
 * de propósito ("abrir por energia entregaria todo dia o mesmo pódio, o das usinas
 * maiores"), e atraso à frente de cumprimento. Escolher aqui um padrão próprio desfaria
 * essa decisão sem ninguém notar.
 */
export function rankingEscolhido(rankings: RankingOut[], chave: string): RankingOut | null {
  return rankings.find((r) => r.chave === chave) ?? rankings[0] ?? null
}
