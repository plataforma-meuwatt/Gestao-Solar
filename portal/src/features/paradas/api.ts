/**
 * O contrato de Paradas, como o BFF o escreve (`bff/app/api/v1/paradas.py`, `ParadasOut`).
 *
 * Três coisas desta resposta mudam o desenho da tela e por isso estão anotadas campo a campo:
 *
 * **`total = null` não é zero.** Zero é "a usina não parou" — notícia boa. `null` é "nenhuma
 * das duas fontes do monitoramento respondeu". Mostrar as duas do mesmo jeito diria ao dono
 * que o mês foi tranquilo quando na verdade ninguém sabe.
 *
 * **`tempo_parado_min` e `perda_kwh` só vêm somados quando TODA linha tem o número.** O BFF
 * recusa somar pela metade (`_soma_se_todas`), porque um total menor do que foi é pior que
 * total nenhum: vira número de reunião. Nulo aqui vira "—" com a explicação ao lado.
 *
 * **`fonte` diz de onde veio.** A fonte preferida do monitoramento está fora do ar há semanas
 * e o BFF cai sozinho na reserva, que ESTIMA a energia perdida — e escreve isso em `aviso`. A
 * tela repete a frase do servidor; não é ela que decide o que é estimativa.
 *
 * O campo que nomeia o inversor de cada linha existe na resposta e NÃO é lido aqui, de
 * propósito: análise de aparelho é trabalho da equipe da Splendor, não do cliente corporativo
 * — o portal responde "quanto tempo e quanto dinheiro", não "qual peça".
 */

import type { Recorte } from '@/lib/periodo'

/** Paradas se olham por mês ou por ano; não existe "paradas do dia" no BFF. */
export type RecorteDeParadas = Extract<Recorte, 'mes' | 'ano'>

export type Parada = {
  id: number
  /** ISO 8601 com fuso. */
  inicio: string
  /** `null` = ainda em aberto. */
  fim: string | null
  /** `null` = o monitoramento não soube calcular (sem janela solar, por exemplo). */
  duracao_min: number | null
  perda_kwh: number | null
  /** `parada` | `degradacao` — código do servidor, traduzido por `rotuloDoTipo`. */
  tipo: string
  em_aberto: boolean
  /** Um dos seis tons do produto, decidido pelo servidor. */
  tom: string
}

export type ParadasOut = {
  recorte: string
  /** `YYYY-MM-DD` — a janela que o servidor de fato consultou. */
  inicio: string
  fim: string
  total: number | null
  tempo_parado_min: number | null
  perda_kwh: number | null
  em_aberto: number
  paradas: Parada[]
  fonte: string | null
  aviso: string | null
}

/**
 * A chave da leitura — que é também o caminho no BFF sem `/api/v1/` e o nome no cache.
 *
 * O período entra na chave: sem ele, voltar um mês mostraria o cache do mês seguinte até a
 * rede responder, e o dono leria o número errado nesse instante.
 */
export function chaveDeParadas(
  usinaId: number,
  recorte: RecorteDeParadas,
  referencia: string,
): string {
  return `plants/${usinaId}/paradas?recorte=${recorte}&referencia=${referencia}`
}

const ROTULO_DO_TIPO: Record<string, string> = {
  parada: 'Parada',
  degradacao: 'Degradação',
}

/**
 * O código do servidor em palavra de gente. Um valor novo (o monitoramento pode passar a
 * publicar outro) aparece como veio, em vez de sumir da tela ou virar "Parada" por engano.
 */
export function rotuloDoTipo(tipo: string): string {
  return ROTULO_DO_TIPO[tipo] ?? tipo
}
