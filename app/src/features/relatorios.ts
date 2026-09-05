/**
 * Relatórios publicados para as usinas desta pessoa — e as réguas da aba.
 *
 * O módulo se chamava `documentos`. O nome mudou junto com a aba, mas **a chave de cache
 * não**: `'documents'` é o caminho do BFF sem `/api/v1/`, por convenção declarada em
 * `lib/cache.ts`, e vira nome de arquivo em disco (`u12__documents.json`). Trocá-la para
 * acompanhar um rótulo órfã o cache de todo celular já instalado — na tela de quem está
 * no campo, que é justamente quem depende dele.
 *
 * A filtragem por escopo acontece no BFF, e não aqui: o Portal do Cliente do meuWatt
 * devolve as usinas todas quando quem chama é administrador — e o BFF chama com um token
 * que costuma ser. Ver `bff/app/api/v1/documents.py`.
 *
 * **Este arquivo não importa nada do React Native** de propósito: as réguas abaixo são
 * texto e aritmética, e é assim que `tests/relatorios.test.ts` consegue exercitá-las no
 * Node sem subir um aparelho.
 */

import { baseURL } from '@/lib/api'
import { fetchWithCache, type Leitura } from '@/lib/cache'

/* ═════════════════════════════════════════════════════════════ o que o BFF manda ══ */

export type ArquivoDoRelatorio = {
  /** `geracao` · `paradas` · `resumo` — o vocabulário é do meuWatt. */
  tipo: string
  nome: string
  /**
   * O peso do PDF, como o monitoramento o declara. **Nulo é ausência** e vira travessão:
   * nunca `0`, que afirmaria arquivo vazio.
   *
   * Existe porque a diferença medida é de sessenta vezes — o Resumo Executivo de Pereiras
   * tem 43.238 B e o Relatório de Geração de Porto Ferreira tem 2.686.172 B. Quem está no
   * 3G entre duas usinas precisa saber se são dois segundos ou dois minutos ANTES do toque.
   */
  bytes: number | null
}

export type Relatorio = {
  id: number
  nome: string
  usina: string
  /** `id` do vínculo neste sistema. É por ele que a tela do ano casa usina com fechamento. */
  plant_id: number | null
  /** `DIÁRIO` · `SEMANAL` · `MENSAL` · `ANUAL` — o vocabulário é do meuWatt. */
  periodo: string
  de: string
  ate: string
  publicado_em: string
  /**
   * O mês COBERTO, `YYYY-MM`, decidido pelo servidor a partir de `de`. Nulo no ANUAL.
   *
   * Não é `publicado_em`: medido hoje, os fechamentos 35 e 36 cobrem **agosto** e foram
   * publicados em **05/09**. Agrupar pelo campo com que a lista vem ordenada poria agosto
   * na gaveta de setembro, e o dono não acharia o relatório do mês que foi procurar.
   */
  competencia: string | null
  /** O ano coberto, só no ANUAL. Exatamente um dos dois campos vem preenchido. */
  ano: number | null
  arquivos: ArquivoDoRelatorio[]
}

export type RelatoriosOut = {
  /** O nome do campo é do servidor, e o contrato não muda porque a aba mudou de rótulo. */
  documentos: Relatorio[]
  aviso: string | null
}

export function useRelatorios(): Leitura<RelatoriosOut> {
  return fetchWithCache<RelatoriosOut>('documents')
}

/** Endereço do PDF. A sessão vai em cabeçalho, nunca na URL — que entra em log. */
export function urlDoArquivo(relatorioId: number, tipo = 'geracao'): string {
  return `${baseURL}/api/v1/documents/${relatorioId}/file?tipo=${encodeURIComponent(tipo)}`
}

/* ══════════════════════════════════════════════════════════════════ as peças ══ */

export type Publico = 'tecnico' | 'executivo'

/**
 * As peças de um fechamento — **fonte única**.
 *
 * Este mapa vivia duplicado em dois arquivos (a aba e a tela de abrir), com duas entradas
 * cada, enquanto o acervo já tinha três: o Resumo Executivo de Pereiras aparecia na lista
 * com o nome de arquivo cru do upstream (`Resumo Executivo - Pereiras - Agosto 2026.pdf`)
 * ao lado de linhas que diziam "Relatório de Geração", e como "Documento" na tela de abrir.
 * Duas cópias é o mesmo que duas respostas.
 *
 * O `publico` é a resposta ao pedido do dono ("técnico e executivo") no único lugar em que
 * ela existe hoje: as peças de geração são leitura de engenharia, o Resumo é o material que
 * vai à diretoria. É classificação nossa, declarada aqui e em lugar nenhum mais.
 */
export const PECAS: Record<string, { rotulo: string; publico: Publico }> = {
  geracao: { rotulo: 'Relatório de Geração', publico: 'tecnico' },
  paradas: { rotulo: 'Anexo de Paradas', publico: 'tecnico' },
  resumo: { rotulo: 'Resumo Executivo', publico: 'executivo' },
}

export const ROTULO_DO_PUBLICO: Record<Publico, string> = {
  tecnico: 'técnico',
  executivo: 'executivo',
}

/** O nome da peça. Peça que o produto ainda não conhece cai no nome do upstream. */
export function rotuloDaPeca(arquivo: ArquivoDoRelatorio): string {
  return PECAS[arquivo.tipo]?.rotulo ?? arquivo.nome
}

/**
 * Peso do arquivo em pt-BR, ou travessão.
 *
 * Base 1000, que é a que o servidor usa ao declarar `size_bytes` e a que aparece em toda
 * lista de arquivo — o objetivo aqui é o dono decidir se toca no 3G, não bater com o
 * gerenciador de arquivos do aparelho.
 */
export function peso(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes) || bytes < 0) return '—'
  if (bytes < 1000) return `${bytes} B`
  if (bytes < 1_000_000) return `${Math.round(bytes / 1000)} KB`
  return `${(bytes / 1_000_000).toLocaleString('pt-BR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} MB`
}

/** A segunda linha da peça: para quem ela é, e quanto pesa. */
export function detalheDaPeca(arquivo: ArquivoDoRelatorio): string {
  const publico = PECAS[arquivo.tipo]?.publico
  const tamanho = peso(arquivo.bytes)
  return publico ? `${ROTULO_DO_PUBLICO[publico]} · ${tamanho}` : tamanho
}

/* ═══════════════════════════════════════════════════════════════ o eixo do mês ══ */

/**
 * A gaveta a que este relatório pertence.
 *
 * `competencia` vem do servidor; `de.slice(0, 7)` é o espelho para quem ainda tem em disco
 * uma resposta gravada antes de o campo existir. **Fatia de string, nunca `new Date`**:
 * `new Date('2026-08-01')` é meia-noite UTC e, no Brasil, o mês responde julho — o
 * relatório de agosto cairia na gaveta de julho, silenciosamente.
 *
 * ANUAL não tem mês: ele cobre doze, e trancá-lo em janeiro o esconderia dos outros onze.
 */
export function mesDoRelatorio(r: Relatorio): string | null {
  if (r.periodo.trim().toUpperCase() === 'ANUAL') return null
  if (r.competencia) return r.competencia
  return r.de ? r.de.slice(0, 7) : null
}

/** A chave da gaveta: o mês, ou o ano quando o documento é ANUAL. */
export function gavetaDoRelatorio(r: Relatorio): string {
  const mes = mesDoRelatorio(r)
  if (mes) return mes
  const ano = r.ano ?? (r.de ? Number(r.de.slice(0, 4)) : null)
  return ano ? `ano:${ano}` : 'sem-data'
}

const MESES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]

/** "Agosto de 2026" · "Ano de 2026" · "Sem período". */
export function rotuloDaGaveta(chave: string): string {
  if (chave.startsWith('ano:')) return `Ano de ${chave.slice(4)}`
  if (chave === 'sem-data') return 'Sem período'
  const [ano, mes] = chave.split('-')
  return `${MESES[Number(mes) - 1] ?? chave} de ${ano}`
}

export type Gaveta = { chave: string; rotulo: string; itens: Relatorio[] }

/**
 * Agrupa por período coberto **preservando a ordem do servidor** (publicação mais recente
 * primeiro). Reordenar aqui seria uma segunda régua de ordenação, e duas réguas dão duas
 * respostas para "qual é o mais novo".
 */
export function agruparPorGaveta(itens: Relatorio[]): Gaveta[] {
  const saida: Gaveta[] = []
  for (const r of itens) {
    const chave = gavetaDoRelatorio(r)
    const gaveta = saida.find((g) => g.chave === chave)
    if (gaveta) gaveta.itens.push(r)
    else saida.push({ chave, rotulo: rotuloDaGaveta(chave), itens: [r] })
  }
  return saida
}

/* ═══════════════════════════════════════════════════════════════════ o recorte ══ */

/**
 * Uma opção de filtro. A forma é a mesma do `Opcao` de `components/EscolhaEmLista`, mas
 * o tipo é declarado aqui: importar o componente arrastaria o React Native para dentro de
 * um módulo que precisa rodar no Node, e a régua é o que se testa.
 */
export type OpcaoDeFiltro = { valor: string | null; rotulo: string; contagem: number }

export type Recorte = {
  /** A usina que vale — já grampeada contra o que existe no acervo. */
  usina: string | null
  /** O período que vale, `YYYY-MM` ou `ano:2026`. Idem. */
  gaveta: string | null
  opcoesDeUsina: OpcaoDeFiltro[]
  opcoesDeGaveta: OpcaoDeFiltro[]
  visiveis: Relatorio[]
  /**
   * O que foi largado no caminho, e por quê — para a tela DIZER, em vez de mostrar uma
   * escolha que não é a que está desenhada.
   */
  ajuste: string | null
}

/**
 * Quem filtra o quê, e por que a tela nunca fica vazia por filtro.
 *
 * As opções saem dos PRÓPRIOS relatórios, nunca da carteira de usinas: quem tem sete
 * usinas mas fechamento em cinco não pode receber duas opções que levam a lugar nenhum.
 * Nenhuma opção nasce com contagem zero — a lista encolhe e cresce com o acervo.
 *
 * O grampo é o mesmo padrão da aba Manutenção: escolha que aponta para algo que sumiu do
 * acervo é ignorada, e não esvazia a tela para sempre.
 *
 * E há um vazio que o grampo simples **não** pega: usina e período existem, mas a
 * combinação não (Porto Ferreira existe, maio existe, "Porto Ferreira em maio" não). Por
 * isso o período é contado DENTRO da usina escolhida e grampeado contra ela — a escolha
 * larga o mês, a tela diz que largou, e o dono continua vendo relatório em vez de um
 * vazio mudo.
 */
export function recorte(
  itens: Relatorio[],
  usinaEscolhida: string | null,
  gavetaEscolhida: string | null,
): Recorte {
  const usinasPresentes = [...new Set(itens.map((r) => r.usina))].sort((a, b) =>
    a.localeCompare(b, 'pt-BR'),
  )
  const usina = usinaEscolhida && usinasPresentes.includes(usinaEscolhida) ? usinaEscolhida : null

  const daUsina = usina ? itens.filter((r) => r.usina === usina) : itens

  // A ordem dos períodos segue a do servidor (publicação mais recente primeiro).
  const gavetasPresentes = [...new Set(daUsina.map(gavetaDoRelatorio))]
  const gaveta =
    gavetaEscolhida && gavetasPresentes.includes(gavetaEscolhida) ? gavetaEscolhida : null

  let ajuste: string | null = null
  if (usinaEscolhida && !usina) {
    ajuste = `${usinaEscolhida} não tem relatório publicado — mostrando todas as usinas.`
  } else if (gavetaEscolhida && !gaveta) {
    const quando = rotuloDaGaveta(gavetaEscolhida).toLowerCase()
    ajuste = usina
      ? `Não há relatório de ${usina} em ${quando} — mostrando todos os períodos desta usina.`
      : `Não há relatório de ${quando} — mostrando todos os períodos.`
  }

  const opcoesDeUsina: OpcaoDeFiltro[] = [
    { valor: null, rotulo: 'Todas as usinas', contagem: itens.length },
    ...usinasPresentes.map((u) => ({
      valor: u,
      rotulo: u,
      contagem: itens.filter((r) => r.usina === u).length,
    })),
  ]

  const opcoesDeGaveta: OpcaoDeFiltro[] = [
    { valor: null, rotulo: 'Todos os períodos', contagem: daUsina.length },
    ...gavetasPresentes.map((c) => ({
      valor: c,
      rotulo: rotuloDaGaveta(c),
      contagem: daUsina.filter((r) => gavetaDoRelatorio(r) === c).length,
    })),
  ]

  return {
    usina,
    gaveta,
    opcoesDeUsina,
    opcoesDeGaveta,
    visiveis: gaveta ? daUsina.filter((r) => gavetaDoRelatorio(r) === gaveta) : daUsina,
    ajuste,
  }
}

/* ══════════════════════════════════════════════════════════ as três ausências ══ */

export type Vazio = { titulo: string; descricao: string; ponte: boolean }

/**
 * A ausência tem TRÊS caras, e a tela tinha um texto para duas delas.
 *
 * 1. **Nada publicado** — o acervo é vazio e o servidor não reclamou de nada.
 * 2. **A ponte caiu** (`aviso` preenchido: nenhuma usina ligada ao monitoramento, ou o
 *    meuWatt fora do ar). Aqui o título antigo — "Nenhum relatório publicado" — era uma
 *    **afirmação falsa**: quando o monitoramento não responde, não se sabe se há relatório
 *    algum. Título e corpo se contradiziam no mesmo cartão.
 * 3. **Fechamento sem arquivo** (`frasePecaAusente`, dentro do cartão): esta nem passa por
 *    aqui, porque a lista NÃO está vazia. É o caso que acontece hoje em quatro dos seis
 *    fechamentos.
 */
export function vazioDaLista(aviso: string | null | undefined): Vazio {
  if (aviso) {
    return { titulo: 'Não deu para saber', descricao: aviso, ponte: true }
  }
  return {
    titulo: 'Nenhum relatório publicado',
    descricao: 'Quando a equipe publicar um relatório das suas usinas, ele aparece aqui.',
    ponte: false,
  }
}

/**
 * O fechamento existe e não tem peça nenhuma.
 *
 * "Sem arquivo anexado." é verdade e não é resposta: o dono lê "o aplicativo não baixou".
 * São duas causas do outro lado — ninguém anexou ainda, ou o fechamento foi reaberto e as
 * peças saíram —, e o upstream não as distingue. A frase diz as duas e diz de quem é a
 * ação, que é o que falta para o dono saber o que fazer.
 *
 * Curta de propósito: hoje QUATRO dos seis fechamentos estão assim, um embaixo do outro.
 * Um parágrafo repetido quatro vezes na mesma rolagem deixa de ser lido.
 */
export function frasePecaAusente(): string {
  return 'Nenhum PDF anexado a este fechamento — ou os arquivos foram retirados. Quem publica é a equipe.'
}

/* ══════════════════════════════════════════════════════════════════ o subtítulo ══ */

/**
 * O subtítulo da aba conta o que está na tela.
 *
 * O texto que havia — "relatórios publicados pelas suas usinas" — era mobília: repetia o
 * título com mais palavras e não dizia nada sobre o acervo.
 */
export function subtituloDaAba(r: Recorte): string {
  const n = r.visiveis.length
  const quantos = `${n} ${n === 1 ? 'relatório' : 'relatórios'}`
  if (r.gaveta) return `${quantos} · ${rotuloDaGaveta(r.gaveta).toLowerCase()}`
  if (r.usina) return `${quantos} · ${r.usina}`
  const usinas = new Set(r.visiveis.map((x) => x.usina)).size
  return `${quantos} · ${usinas} ${usinas === 1 ? 'usina' : 'usinas'}`
}

/* ══════════════════════════════════════════════════════════════════ o contrato ══ */

/**
 * Os campos que esta aba LÊ do BFF, para o teste de contrato conferir contra os modelos
 * Pydantic. É a família de teste que teria pegado "Contrato nº undefined" no minuto da
 * renomeação — e o cache em disco faz esse tipo de defeito piscar em vez de estourar.
 */
export const CAMPOS_LIDOS = {
  DocumentoOut: [
    'id',
    'nome',
    'usina',
    'plant_id',
    'periodo',
    'de',
    'ate',
    'publicado_em',
    'competencia',
    'ano',
    'arquivos',
  ],
  ArquivoOut: ['tipo', 'nome', 'bytes'],
  DocumentosOut: ['documentos', 'aviso'],
} as const
