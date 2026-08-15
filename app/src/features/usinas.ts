/**
 * As usinas do dono, como o BFF as entrega.
 *
 * Os nomes de campo são os do servidor (`snake_case`), de propósito: renomear na fronteira
 * cria um segundo vocabulário para a mesma coisa, e é ele que faz alguém procurar
 * `capacidadeKwp` no `plants.py` e não achar. O contrato está em
 * `docs/CONTRATO_API.md` § Usinas.
 */

import { fetchWithCache, type Leitura } from '@/lib/cache'
import type { Tom } from '@/theme/tokens'

export type Usina = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
  capacidade_kwp: number | null

  /** Nulo é "sem comunicação", e a tela mostra travessão. Zero é "não gerou" — de noite,
   *  o esperado. Desenhar os dois igual é o erro que este campo existe para evitar. */
  potencia_kw: number | null
  energia_hoje_kwh: number | null
  disponibilidade_pct: number | null
  pct_capacidade: number | null

  /** Chave de `tons`, decidida pelo servidor: a regra de cor não é da tela. */
  tom: Tom
  situacao: string

  /** Todos os inversores mudos — vem do estado deles, não da potência. */
  sem_comunicacao: boolean
  /** Quantos estão mudos, mesmo sem serem todos. Sem isto, mudez parcial fica invisível. */
  inversores_mudos: number | null
  /** Quantos estão em falha — o que decide a faixa vermelha. */
  inversores_parados: number | null
  /** Quantos pedem atenção sem estar parados: alarme do fabricante ou código de falha. */
  inversores_alerta: number | null
  /** Fora da janela solar: nada é defeito, e a tela não deve alarmar. */
  fora_da_janela_solar: boolean

  tem_meuwatt: boolean
  tem_meuplano: boolean
  aviso: string | null
}

export type UsinasOut = {
  usinas: Usina[]
  total_kwp: number
  potencia_agora_kw: number | null
  energia_hoje_kwh: number | null
  atualizado_em: string
  aviso: string | null
}

export type UsinaDetalhe = Usina & {
  /** Do meuPlano. Nulo = não deu para consultar; zero = não há ordem aberta. */
  ordens_abertas: number | null
  ordens_recentes: string[]

  /** Do meuWatt. Mesma regra: nulo é "não sabemos", não "nenhum". */
  inversores: number | null
  inversores_parados: number | null
  alertas_ativos: number | null
}

export function useUsinas(): Leitura<UsinasOut> {
  return fetchWithCache<UsinasOut>('plants')
}

export function useUsina(id: string | undefined): Leitura<UsinaDetalhe> {
  // Cada usina tem seu próprio cache — a chave entra no nome do arquivo. Sem `id` a
  // consulta fica desligada, senão a rota viraria `/plants/undefined`.
  return fetchWithCache<UsinaDetalhe>(`plants/${id ?? ''}`, { ativo: Boolean(id) })
}

/**
 * Geração por recorte — `Mês` (um ponto por dia) e `Ano` (um ponto por mês).
 *
 * Vem de `GET /api/v1/plants/{id}/geracao?recorte=`, que por sua vez soma a série
 * `chart_data.daily_generation` do meuWatt. `total_kwh` nulo significa que o
 * monitoramento não respondeu — a tela mostra "sem dados", nunca zero, porque zero
 * é uma medição legítima (usina parada o período inteiro) e confundir as duas
 * coisas é o que faz o dono achar que perdeu geração.
 */
export type PontoGeracao = {
  /** `YYYY-MM-DD` no recorte mês, `YYYY-MM` no ano. */
  chave: string
  /** Rótulo curto do eixo ("07", "Jul"). */
  rotulo: string
  kwh: number
}

export type Geracao = {
  recorte: 'mes' | 'ano'
  inicio: string
  fim: string
  total_kwh: number | null
  pontos: PontoGeracao[]
  aviso: string | null
}

export function useGeracao(
  id: string | undefined,
  recorte: 'mes' | 'ano',
  ativo: boolean,
  /** Qualquer dia dentro do período desejado; o BFF deriva o mês ou o ano dela. */
  referencia?: string,
): Leitura<Geracao> {
  // `ativo` desliga a consulta enquanto o recorte não está na tela: abrir a usina
  // não deve disparar três chamadas para o usuário ver uma.
  const ref = referencia ? `&referencia=${referencia}` : ''
  return fetchWithCache<Geracao>(`plants/${id ?? ''}/geracao?recorte=${recorte}${ref}`, {
    ativo: Boolean(id) && ativo,
  })
}

/**
 * Curva do dia: potência da usina a cada 5 minutos e, quando há estação, a irradiação
 * no plano dos módulos.
 *
 * `tem_estacao` vem do servidor porque só lá dá para decidir com honestidade: o upstream
 * devolve `poa: 0` tanto para usina sem sensor quanto para meia-noite, e o app sozinho
 * desenharia uma linha rasteira que parece medição de um sensor que não existe.
 */
export type PontoCurva = {
  hora: string
  kw: number
  poa: number | null
}

export type CurvaUsina = {
  dia: string
  pontos: PontoCurva[]
  pico_kw: number | null
  pico_poa: number | null
  tem_estacao: boolean
  aviso: string | null
}

export function useCurva(
  id: string | undefined,
  dia: string,
  ativo: boolean,
): Leitura<CurvaUsina> {
  return fetchWithCache<CurvaUsina>(`plants/${id ?? ''}/curva?dia=${dia}`, {
    ativo: Boolean(id) && ativo,
  })
}
