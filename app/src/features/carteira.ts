/**
 * Comparar as usinas da carteira — a pergunta "qual delas rende mais?".
 *
 * É uma pergunta DIFERENTE da que a lista de usinas responde. A lista diz "como cada uma
 * está agora"; aqui se pergunta qual rende mais **no período**, e essa pergunta só tem
 * resposta honesta com três coisas juntas: uma régua que sobreviva a capacidades
 * diferentes (kWh/kWp), uma janela que sobreviva a datas de entrada diferentes, e o nome
 * de quem ficou de fora.
 *
 * **A ordem vem pronta do servidor, e a tela não a recalcula.** `GET /api/v1/carteira/
 * comparativo` devolve o ranking já ordenado, com posição e empate resolvidos em
 * `bff/app/services/carteira.py:ranking` — a mesma régua que o portal usa em
 * `/comparar/energia`. Reordenar aqui por `produtividade_kwh_kwp` pareceria inofensivo e
 * produziria a segunda resposta para a mesma pergunta: empate desempatado por outro
 * critério, usina sem PR aparecendo no fim como se fosse a pior, e o celular discordando
 * do computador na frente do cliente. É o defeito mais caro deste projeto — a mesma usina
 * com -64,3 % numa tela e +101,7 % na outra — e é ele que `ordenarPeloRanking` existe
 * para não repetir.
 *
 * Os nomes de campo são os do servidor (`snake_case`), como no resto de `features/`:
 * renomear na fronteira cria um segundo vocabulário para a mesma coisa.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'

/* ------------------------------------------------------------------ formato */

/**
 * O período efetivamente comparado — e o que ele deixou de fora.
 *
 * Sem este bloco a tela mostraria um ranking de doze meses contra um de quatro sem nenhum
 * sinal de que os dois não são comparáveis. `encolhida_por` NOMEIA a usina cuja entrada
 * tardia reduziu a interseção: sem o nome, quem lê "jun a set" não tem como saber por que
 * o ano virou quatro meses.
 */
export type Janela = {
  de: string
  ate: string
  meses: string[]
  /** A interseção dos meses REALMENTE medidos por todas as usinas com dado. */
  meses_comuns: string[]
  /** "ago de 2026", "jun a set de 2026" — a frase pronta, escrita pelo servidor. */
  rotulo: string | null
  /** A interseção cobre o período inteiro. Falso = a comparação é mais estreita. */
  completa: boolean
  encolhida_por: string[]
  /** Usinas sem um único mês medido: saem da comparação em vez de virar zero. */
  fora_da_comparacao: string[]
  /** Detalhe mensal ausente. "Não sabemos" não é "não tem". */
  sem_detalhe: string[]
  comparaveis: number
  /** A explicação, quando há o que explicar. Nulo quando a janela é a pedida. */
  nota: string | null
  truncada_em_hoje: boolean
}

export type UsinaEnergia = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null

  capacidade_kwp: number | null
  /** Energia do período PEDIDO — o mesmo número de `/plants/{id}/desempenho`. */
  energia_kwh: number | null
  /** Energia só dos meses da janela comum. É esta que sustenta o ranking. */
  energia_comparavel_kwh: number | null
  /** kWh/kWp — a única régua que sobrevive a capacidades diferentes. */
  produtividade_kwh_kwp: number | null
  /** Nulo sem POA medida: 0 % de PR não é medição, é a ausência dela. */
  pr_pct: number | null
  disponibilidade_real_pct: number | null
  disponibilidade_contratual_pct: number | null
  perdas_paradas_kwh: number | null
  /** Contexto obrigatório: "rende melhor" ainda contém "teve mais sol". */
  irradiacao_hpoa: number | null
  irradiacao_ghi: number | null
  paradas_pendentes: number | null

  meses_medidos: string[]
  /** Por que esta usina não tem número. Ela fica na lista, com travessão, e fora de
   *  todo ranking — nunca como zero no fim, que é a leitura mais injusta de uma ausência. */
  motivo: string | null
}

export type TotaisEnergia = {
  /** De quantas usinas este total fala. Sem ele, "3,2 GWh" parece a carteira inteira. */
  usinas_no_total: number
  energia_kwh: number | null
  capacidade_kwp: number | null
  produtividade_kwh_kwp: number | null
  perdas_paradas_kwh: number | null
}

export type UsinaManutencao = {
  id: number
  nome: string
  contrato: string | null
  contrato_id: number | null
  previsto: number | null
  feitas: number | null
  /** Dispensa registrada com motivo. NUNCA se soma a `feitas`. */
  dispensadas: number | null
  atrasadas: number | null
  denominador: number | null
  cumprimento_pct: number | null
  /** "13 de 31" — o denominador que viaja junto com todo percentual desta família. */
  cumprimento_rotulo: string | null
  fora_da_conta: string | null
  os_em_andamento: number | null
  pendencias_abertas: number | null
  pendencias_vencidas: number | null
  pendencias_cobradas: number | null
  pendencias_criticas: number | null
  motivo: string | null
}

export type TotaisManutencao = {
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

export type ItemRanking = {
  /** 1 = melhor. Empate DIVIDE a posição (1, 1, 3): desempatar por nome coroaria uma
   *  usina pela inicial dela. */
  posicao: number
  usina_id: number
  usina: string
  valor: number
  empatado: boolean
  denominador: number | null
}

export type Ranking = {
  /** `produtividade` | `energia` | `pr` | `atrasadas` | `cumprimento` | `pendencias_vencidas` */
  chave: string
  titulo: string
  /** A pergunta que ESTE ranking responde, redigida pelo servidor. A tela nunca escreve a
   *  sua: senão "produtividade" vira "eficiência" aqui e "rendimento" no computador. */
  pergunta: string
  nota: string | null
  unidade: string | null
  ordem: string
  itens: ItemRanking[]
  /** Quem ficou de fora, com o motivo. Sem esta lista a ausência vira suspeita de erro. */
  fora: string[]
}

export type BlocoEnergia = {
  usinas: UsinaEnergia[]
  totais: TotaisEnergia
  rankings: Ranking[]
}

export type BlocoManutencao = {
  usinas: UsinaManutencao[]
  totais: TotaisManutencao
  rankings: Ranking[]
}

export type Comparativo = {
  janela: Janela
  energia: BlocoEnergia | null
  manutencao: BlocoManutencao | null
  usinas_no_escopo: number
  aviso: string | null
}

/* -------------------------------------------------------------------- leitura */

/** Qual bloco o servidor deve montar. O celular pede só `energia`: a família de Geração
 *  abre sem esperar o sistema de manutenção responder. */
export type BlocoPedido = 'energia' | 'manutencao' | 'tudo'

export function useComparativo(
  de: string,
  ate: string,
  blocos: BlocoPedido = 'energia',
  ativo = true,
): Leitura<Comparativo> {
  return fetchWithCache<Comparativo>(
    `carteira/comparativo?de=${de}&ate=${ate}&blocos=${blocos}`,
    { ativo },
  )
}

/* ---------------------------------------------------------------------- régua */

/**
 * O período pedido ao servidor a partir da data de referência da tela.
 *
 * O mês inteiro, e não "até hoje": quem trava o fim em hoje é o servidor
 * (`truncada_em_hoje`), e mandar daqui uma data que muda todo dia trocaria a chave do
 * cache do aparelho a cada abertura — a usina fica onde o sinal é ruim, e o cache é o que
 * faz a tela abrir lá.
 *
 * O dia 0 do mês seguinte é o último do mês pedido — resolve fevereiro bissexto sem
 * tabela. A data é montada com `new Date(ano, mes, dia)`, que é meia-noite LOCAL:
 * `new Date('2026-08-01')` seria meia-noite UTC e, no fuso do Brasil, voltaria julho.
 */
export function periodoDaCarteira(
  referencia: string,
  recorte: 'mes' | 'ano',
): { de: string; ate: string } {
  const [ano, mes] = referencia.split('-').map(Number)
  if (recorte === 'ano') {
    return { de: `${ano}-01-01`, ate: `${ano}-12-31` }
  }
  const ultimo = new Date(ano, mes, 0).getDate()
  const mm = String(mes).padStart(2, '0')
  return { de: `${ano}-${mm}-01`, ate: `${ano}-${mm}-${String(ultimo).padStart(2, '0')}` }
}

/**
 * O ranking de uma chave, ou `undefined`.
 *
 * Nunca "o primeiro da lista como reserva": a ordem dos rankings no envelope é do
 * servidor e pode mudar. Cair no primeiro exibiria energia absoluta sob o título de
 * produtividade — duas perguntas diferentes com a mesma cara.
 */
export function rankingDe(
  bloco: BlocoEnergia | BlocoManutencao | null | undefined,
  chave: string,
): Ranking | undefined {
  return bloco?.rankings.find((r) => r.chave === chave)
}

export type LinhaComparada<T> = {
  usina: T
  posicao: number
  empatado: boolean
  valor: number
}

/**
 * As usinas na ORDEM que o servidor decidiu, e as que ficaram fora dela.
 *
 * A ordenação não acontece aqui — ela é lida de `ranking.itens`, que já vem ordenado e com
 * empate resolvido. Uma usina que o servidor tirou do ranking (sem dado, sem capacidade,
 * sem PR) sai em `fora`, para a tela mostrar travessão com o motivo ao lado, e não um zero
 * no último lugar.
 *
 * Sem ranking nenhum, TUDO vai para `fora`: sem a régua do servidor não existe ordem
 * honesta a exibir, e inventar uma aqui é exatamente o que este módulo recusa.
 */
export function ordenarPeloRanking<T extends { id: number }>(
  usinas: T[],
  ranking: Ranking | undefined,
): { ordenadas: LinhaComparada<T>[]; fora: T[] } {
  if (!ranking) return { ordenadas: [], fora: [...usinas] }

  const porId = new Map(usinas.map((u) => [u.id, u]))
  const ordenadas: LinhaComparada<T>[] = []
  const usados = new Set<number>()

  for (const item of ranking.itens) {
    const usina = porId.get(item.usina_id)
    // Id no ranking que não está na lista: o servidor nomeia, mas a tela não tem a linha.
    // Fabricar uma com o nome do ranking daria uma usina sem capacidade nem energia.
    if (!usina || usados.has(item.usina_id)) continue
    usados.add(item.usina_id)
    ordenadas.push({
      usina,
      posicao: item.posicao,
      empatado: item.empatado,
      valor: item.valor,
    })
  }

  return { ordenadas, fora: usinas.filter((u) => !usados.has(u.id)) }
}

/**
 * A frase da janela, como o servidor a escreveu.
 *
 * Nulo quando não há rótulo — a tela então não escreve período nenhum. Inventar aqui um
 * "período completo" seria afirmar cobertura que ninguém conferiu, que é justamente o que
 * a janela comum existe para impedir.
 */
export function fraseDaJanela(janela: Janela | null | undefined): string | null {
  const rotulo = janela?.rotulo?.trim()
  if (!rotulo) return null
  const nota = janela?.nota?.trim()
  return nota ? `${rotulo} · ${nota}` : rotulo
}
