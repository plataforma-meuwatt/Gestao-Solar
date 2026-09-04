/**
 * O que a tela de Energia lê do BFF — e nada além disso.
 *
 * Cinco leituras, todas do mesmo assunto ("quanto esta usina gerou e era para gerar"):
 *
 * - `plants/{id}` — quem é a usina, como está agora e quanto gerou hoje;
 * - `plants/{id}/desempenho?recorte=mes|ano` — medido × esperado do PROJETO (a meta cadastrada
 *   no meuWatt), com PR, disponibilidade e perda por parada;
 * - `plants/{id}/geracao?recorte=mes|ano` — a série de barras do período escolhido;
 * - `plants/{id}/curva?dia=` — a potência do dia, com irradiação quando há estação;
 * - `plants/{id}/historico?meses=24` — a série longa, contra a meta e contra o ano anterior.
 *
 * Os tipos são o espelho dos schemas do BFF (`bff/app/api/v1/plants.py`), com uma regra que
 * atravessa todos: **`null` é ausência, e ausência não é zero.** Onde o BFF escreve
 * `float | None`, aqui é `number | null`, e a tela imprime "—". Coalescer nulo para zero
 * transformaria "não medimos" em "não gerou" no meio de uma reunião de contrato.
 *
 * O que NÃO está aqui é tão deliberado quanto o que está: equipamento, relé, string e
 * comparativo são análise de manutenção, trabalho da equipe. O cliente corporativo pediu
 * energia; a ficha do aparelho continua no lugar dela, para quem a executa.
 */

import { useLeitura, type Leitura } from '@/lib/leitura'
import type { Recorte } from '@/lib/periodo'

/* ------------------------------------------------------------------ tipos */

/**
 * A usina como o portal a mostra.
 *
 * É um subconjunto declarado do `UsinaDetalheOut` do BFF: os campos de contagem de aparelho
 * existem na resposta e ficam de fora do tipo de propósito — o que não é lido aqui não pode
 * escapar para a tela por descuido.
 */
export type UsinaDetalhe = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
  capacidade_kwp: number | null
  /** Nulo = sem comunicação. "Não sabemos" ≠ "não está gerando". */
  potencia_kw: number | null
  energia_hoje_kwh: number | null
  disponibilidade_pct: number | null
  /** Quanto da capacidade está em uso agora, 0–100. Nulo quando falta um dos dois. */
  pct_capacidade: number | null
  /** Um dos seis tons, já decidido pelo servidor. */
  tom: string
  situacao: string
  fora_da_janela_solar: boolean
  tem_meuwatt: boolean
  tem_meuplano: boolean
  aviso: string | null
}

export type MesDesempenho = {
  /** `YYYY-MM`. */
  mes: string
  energia_kwh: number | null
  esperado_projeto_kwh: number | null
  disponibilidade_contratual_pct: number | null
  perdas_kwh: number | null
}

export type Desempenho = {
  recorte: string
  inicio: string
  fim: string
  energia_kwh: number | null
  /** A meta do PROJETO (PVsyst) somada no período. Nulo = ninguém cadastrou. */
  esperado_projeto_kwh: number | null
  pct_do_projeto: number | null
  pr_pct: number | null
  disponibilidade_real_pct: number | null
  disponibilidade_contratual_pct: number | null
  /** Zero aqui é medição legítima (houve dado, não houve perda); nulo é ausência. */
  perdas_paradas_kwh: number | null
  /** Só no recorte `ano`: um item por mês, com o esperado ao lado. */
  meses: MesDesempenho[]
  tom: string
  situacao: string
  aviso: string | null
}

export type PontoGeracao = {
  /** `YYYY-MM-DD` no recorte mês, `YYYY-MM` no recorte ano. */
  chave: string
  /** Rótulo curto pronto para o eixo ("07", "Jul"). */
  rotulo: string
  kwh: number
}

export type Geracao = {
  recorte: string
  inicio: string
  fim: string
  total_kwh: number | null
  pontos: PontoGeracao[]
  aviso: string | null
}

export type PontoDaCurva = {
  hora: string
  kw: number
  /** Irradiação no plano dos módulos, W/m². Nulo quando a usina não tem estação. */
  poa: number | null
}

export type Curva = {
  dia: string
  pontos: PontoDaCurva[]
  pico_kw: number | null
  pico_poa: number | null
  /** `false` faz a tela DIZER que não há estação, em vez de desenhar curva rasteira. */
  tem_estacao: boolean
  aviso: string | null
}

export type MesHistorico = {
  mes: string
  energia_kwh: number | null
  esperado_projeto_kwh: number | null
  /** O mesmo mês do ano anterior — a régua do diretor quando não há meta cadastrada. */
  ano_anterior_kwh: number | null
  perdas_kwh: number | null
}

export type Historico = {
  inicio: string
  fim: string
  meses: MesHistorico[]
  aviso: string | null
}

/* ------------------------------------------------------------------ leituras */

/**
 * A chave de cache carrega o período.
 *
 * Assim voltar para agosto reabre agosto na hora, com o que já foi lido, e a rede só confirma.
 * Sem o período na chave, andar no tempo sobrescreveria o cache a cada passo e o caminho de
 * volta ficaria vazio — que é o oposto do que o cache existe para fazer.
 */
export function useUsinaDetalhe(id: number, ativo = true): Leitura<UsinaDetalhe> {
  return useLeitura<UsinaDetalhe>(`plants/${id}`, { ativo })
}

export function useDesempenho(
  id: number,
  recorte: 'mes' | 'ano',
  referencia: string,
  ativo = true,
): Leitura<Desempenho> {
  return useLeitura<Desempenho>(
    `plants/${id}/desempenho?recorte=${recorte}&referencia=${referencia}`,
    { ativo },
  )
}

export function useGeracao(
  id: number,
  recorte: Recorte,
  referencia: string,
  ativo = true,
): Leitura<Geracao> {
  return useLeitura<Geracao>(`plants/${id}/geracao?recorte=${recorte}&referencia=${referencia}`, {
    // O recorte `dia` não tem série de geração (é a curva); a leitura fica desligada em vez de
    // pedir ao BFF um recorte que ele recusa com 400.
    ativo: ativo && recorte !== 'dia',
  })
}

export function useCurva(id: number, dia: string, ativo = true): Leitura<Curva> {
  return useLeitura<Curva>(`plants/${id}/curva?dia=${dia}`, { ativo })
}

/**
 * Os últimos 24 meses.
 *
 * Prazo maior porque, lá atrás, isto vira várias leituras de um ano civil no meuWatt (o teto
 * de 366 dias do upstream) mais o ano anterior da comparação. Com o prazo padrão, a série
 * longa seria a única coisa da tela a falhar por tempo, e justamente na primeira abertura.
 */
export function useHistorico(id: number, meses = 24, ativo = true): Leitura<Historico> {
  return useLeitura<Historico>(`plants/${id}/historico?meses=${meses}`, {
    ativo,
    prazoMs: 60_000,
  })
}

/* ------------------------------------------------------------------ ausência */

/**
 * A usina não existe para este cliente — ou não é monitorada.
 *
 * Os dois casos vêm do BFF como 404 com frase própria (`_usina_no_escopo` e
 * `_usina_monitorada`, em `bff/app/api/v1/plants.py`), e os dois pedem a MESMA tela: um vazio
 * que explica, não um erro vermelho com "Tentar de novo" — tentar de novo não vai fazer a
 * usina aparecer, e o botão só empurra o cliente a repetir o que não pode dar certo.
 *
 * Quem decide é o STATUS, não a frase. A primeira versão casava o texto do `detail`, e isso
 * pendurava a tela na prosa do BFF: bastava reescrever "Esta usina não está ligada ao
 * monitoramento." — como aconteceu quando os nomes dos produtos saíram das mensagens do
 * cliente — para a tela cair no erro genérico, sem nada quebrar e sem ninguém notar.
 * `Leitura.status` nasceu deste caso.
 */
export function ehUsinaAusente(leitura: Leitura<unknown>): boolean {
  return leitura.dados === null && leitura.status === 404
}
