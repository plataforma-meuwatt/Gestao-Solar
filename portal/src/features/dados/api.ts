/**
 * O contrato de "Baixar dados", como o BFF o escreve (`bff/app/api/v1/exportacao.py`).
 *
 * Duas rotas e um arquivo:
 *
 * - `GET /energia/dados/opcoes?usina_id=` → **o que ESTA usina tem** (inversores por skid,
 *   quais colunas a estação de fato coleta, medidores, PR, até onde o acervo alcança e o
 *   teto de dias de cada passo). É com isto que a tela desabilita o impossível **dizendo o
 *   motivo**, em vez de sumir com a linha e deixar o cliente concluir que o portal não
 *   oferece quando o fato é sobre a usina dele.
 * - `POST /energia/dados/arquivo?usina_id=` → o XLSX, em fluxo.
 *
 * **Por que o download não passa pelo axios.** A sessão vai no cabeçalho, e um `<a href>` não
 * manda cabeçalho — a saída fácil (token na query string) é a proibida: endereço entra em log
 * de servidor, em histórico e em relatório de erro. É a mesma razão de `lib/arquivo.ts`, e
 * daqui sai um `Blob` que aquele módulo salva (`baixarBlob`). O que ele **não** faz é POST
 * com corpo, que é o método desta rota — POST por TAMANHO DA SELEÇÃO (quinhentas chaves de
 * série não cabem numa query string), nunca por efeito: nada é criado nem alterado.
 *
 * **O `motivo` atravessa; a frase do meuWatt não.** A recusa chega achatada
 * (`{detail, motivo}`) porque a tela precisa do código no primeiro nível para escolher entre
 * "Tentar de novo" e um aviso sem botão — repetir um `muito_grande` dá exatamente o mesmo
 * resultado. Quem traduz o código em português é `pacotes.ts`; o `message` do upstream foi
 * escrito para o operador da mw-api e fala em balde, snapshots e SSU.
 *
 * **As chaves de série (`slot:170`, `inv:7`) são TRANSPORTE.** Elas viajam no pedido e nunca
 * aparecem na tela: o que o cliente lê é `rotulo` ("Inv 13") com o número de série ao lado.
 */

import { baseURL, detalheEmTexto, tokenDaSessao } from '@/lib/api'

/* ------------------------------------------------------------------ vocabulário */

/** As quatro variáveis de inversor. `status` e `paradas` só existem em alguns passos. */
export type VarInversor = 'geracao' | 'potencia' | 'status' | 'paradas'
export type VarEstacao =
  | 'poa'
  | 'ghi'
  | 'temp_modulo'
  | 'temp_ambiente'
  | 'vento'
  | 'temp_ambiente_rele'
export type VarSistema = 'pr' | 'produtividade'
/** Do mais fino ao mais grosso. O teto de dias de cada um vem do servidor, em `limites`. */
export type Passo = 'native' | '5m' | '15m' | '1h' | '1d'

/* ------------------------------------------------------------------ opções */

export type Serie = {
  /** Transporte (`slot:170`). Nunca vai para a tela. */
  chave: string
  rotulo: string
  numero_serie: string | null
  capacidade_kwp: number | null
}

export type Skid = {
  id: number | null
  nome: string
  capacidade_kwp: number | null
  series: Serie[]
}

export type EstacaoDisponivel = {
  disponivel: boolean
  /**
   * Coluna → tem dado. Dicionário aberto de propósito: a mw-api já devolve `umidade`, que
   * não é exportável, e fechá-lo num tipo faria a chave sumir em silêncio no dia em que ela
   * passasse a ser.
   */
  colunas: Record<string, boolean>
  /** A mesma grandeza de `temp_ambiente` vinda do relé — distinção de operador. */
  temp_ambiente_rele: boolean
}

export type Leitor = { id: number; nome: string | null }

export type Retencao = {
  /** Antes disto a leitura fina de inversores/estação não existe mais. `null` = não sabemos. */
  snapshots_desde: string | null
  /** Antes disto a leitura do medidor não existe mais. */
  ssu_desde: string | null
}

export type OpcoesDeDados = {
  usina: { id: number; nome: string; capacidade_kwp: number | null }
  skids: Skid[]
  estacao: EstacaoDisponivel
  leitores: Leitor[]
  sistema: { pr: boolean; produtividade: boolean }
  retencao: Retencao
  /** `native`/`5m`/`15m`/`1h`/`1d` em dias, mais `max_celulas`. */
  limites: Record<string, number>
}

/**
 * A chave da leitura — o caminho no BFF sem `/api/v1/`, e o nome no cache.
 *
 * A usina entra na chave: sem ela, trocar de usina mostraria as opções da anterior até a rede
 * responder — e o cliente marcaria uma coluna que a usina nova não tem.
 */
export function chaveDasOpcoes(usinaId: number): string {
  return `energia/dados/opcoes?usina_id=${usinaId}`
}

/* ------------------------------------------------------------------ pedido */

export type BlocoInversores = {
  variaveis: VarInversor[]
  agrupamento: 'lista' | 'skid'
  /**
   * ⛔ `null` **não** é "listei todos". Nulo é "não mexi": o inversor comissionado no meio do
   * período entra sozinho no arquivo. Uma lista explícita congela o conjunto no que a tela
   * viu. Os dois estados existem de propósito e a tela os oferece separados.
   */
  series: string[] | null
}

export type Selecao = {
  inversores: BlocoInversores | null
  estacao: { variaveis: VarEstacao[] } | null
  fronteira: { variaveis: ['energia']; agrupamento: 'leitor' | 'usina' } | null
  sistema: { variaveis: VarSistema[]; agrupamento: 'skid' | 'usina' } | null
}

export type Pedido = {
  /** `YYYY-MM-DD`, em BRT. */
  inicio: string
  fim: string
  /** `HH:MM` do primeiro e do último dia. O servidor os ignora quando o passo é `1d`. */
  hora_inicio: string
  hora_fim: string
  passo: Passo
} & Selecao

/**
 * O corpo do POST, com **bloco ausente fora do JSON**.
 *
 * `null` e "chave ausente" dão no mesmo para o Pydantic do BFF, mas a chave ausente é o que
 * diz literalmente "este bloco não entra no arquivo" — e é o formato que os testes do BFF
 * conferem. `series` segue a mesma regra por outro motivo, mais caro: uma lista vazia
 * viajaria como "nenhuma série", e o upstream devolveria um arquivo sem colunas.
 */
export function corpoDoPedido(p: Pedido): Record<string, unknown> {
  const corpo: Record<string, unknown> = {
    inicio: p.inicio,
    fim: p.fim,
    hora_inicio: p.hora_inicio,
    hora_fim: p.hora_fim,
    passo: p.passo,
  }
  if (p.inversores) {
    const bloco: Record<string, unknown> = {
      variaveis: p.inversores.variaveis,
      agrupamento: p.inversores.agrupamento,
    }
    if (p.inversores.series !== null) bloco.series = p.inversores.series
    corpo.inversores = bloco
  }
  if (p.estacao) corpo.estacao = p.estacao
  if (p.fronteira) corpo.fronteira = p.fronteira
  if (p.sistema) corpo.sistema = p.sistema
  return corpo
}

/* ------------------------------------------------------------------ o arquivo */

/**
 * A recusa que sabe QUAL foi.
 *
 * `motivo` nulo é falha de transporte (rede, proxy, ponte fora do ar): repetir pode
 * funcionar. Com motivo, é regra — e aí repetir dá o mesmo resultado.
 */
export class ErroDaExportacao extends Error {
  readonly motivo: string | null
  readonly status: number | null

  constructor(mensagem: string, motivo: string | null, status: number | null) {
    super(mensagem)
    this.name = 'ErroDaExportacao'
    this.motivo = motivo
    this.status = status
  }
}

/** Ninguém desistiu, ninguém errou: o cliente cancelou. A tela não mostra erro nenhum. */
export class Cancelado extends Error {
  constructor() {
    super('cancelado')
    this.name = 'Cancelado'
  }
}

/** O nome que o BFF mandou no `Content-Disposition`, ou o de reserva. */
export function nomeDoArquivo(cabecalho: string | null, reserva: string): string {
  if (!cabecalho) return reserva
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cabecalho)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      // Cabeçalho malformado não pode custar o download: cai no nome simples.
    }
  }
  const simples = /filename="?([^";]+)"?/i.exec(cabecalho)
  return simples ? simples[1] : reserva
}

/** Prazo de leitura. O meuWatt monta o arquivo inteiro antes de responder — medido: 34 s no
 * pior pedido que ele aceita —, e o BFF ainda pode esperar uma vaga na fila. 180 s é o corte
 * declarado: acima disso a tela desiste com uma frase, em vez de girar para sempre. */
export const PRAZO_DO_ARQUIVO_MS = 180_000

/**
 * Pede a planilha e devolve os bytes. Quem salva é `baixarBlob`, de `lib/arquivo.ts`.
 *
 * `sinal` vem de fora porque o cancelamento é do cliente: o botão "Cancelar" aborta este
 * `fetch`, e o BFF solta a vaga da fila junto (a pilha dele fecha quando o gerador é
 * fechado). Sem isso, desistir de um download deixaria a conexão pendurada até o prazo.
 */
export async function baixarDados(
  usinaId: number,
  pedido: Pedido,
  sinal?: AbortSignal,
): Promise<{ blob: Blob; nome: string }> {
  const token = tokenDaSessao()
  let resposta: Response
  try {
    resposta = await fetch(`${baseURL}/api/v1/energia/dados/arquivo?usina_id=${usinaId}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(corpoDoPedido(pedido)),
      signal: sinal,
    })
  } catch (erro) {
    if (erro instanceof DOMException && erro.name === 'AbortError') throw new Cancelado()
    throw new ErroDaExportacao('Sem conexão com o servidor.', null, null)
  }

  if (!resposta.ok) {
    let detalhe: string | null = null
    let motivo: string | null = null
    try {
      const corpo = (await resposta.json()) as { detail?: unknown; motivo?: unknown }
      detalhe = detalheEmTexto(corpo.detail)
      // O motivo vem no PRIMEIRO nível, e não dentro de `detail`: é o que permite à tela
      // escolher entre erro com "Tentar de novo" e aviso sem botão.
      motivo = typeof corpo.motivo === 'string' ? corpo.motivo : null
    } catch {
      // Corpo que não é JSON (página do proxy, por exemplo): fica a frase padrão.
    }
    if (resposta.status === 401) {
      throw new ErroDaExportacao(
        detalhe ?? 'Sua sessão expirou. Entre de novo.',
        null,
        resposta.status,
      )
    }
    throw new ErroDaExportacao(
      detalhe ?? `Não foi possível baixar os dados (erro ${resposta.status}).`,
      motivo,
      resposta.status,
    )
  }

  const blob = await resposta.blob()
  // Uma planilha de verdade tem quilobytes; um corpo de poucos bytes é uma mensagem de erro
  // que veio com status 200 por descuido de algum proxy — e viraria um XLSX que não abre.
  if (blob.size < 100) {
    throw new ErroDaExportacao('O servidor devolveu um arquivo vazio.', null, resposta.status)
  }
  return {
    blob,
    nome: nomeDoArquivo(resposta.headers.get('Content-Disposition'), 'dados.xlsx'),
  }
}
