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

/**
 * Um relatório mensal de MANUTENÇÃO que a equipe já LIBEROU ao cliente.
 *
 * É a segunda família da aba, e vem do meuPlano — não do monitoramento. Não se mistura com
 * `Relatorio`: são dois acervos, de dois sistemas, com dois ciclos de publicação. O que os
 * dois têm em comum é a **competência**, e é por ela que a tela os põe na mesma gaveta.
 *
 * **O corte não mora aqui.** Só atravessa o que o meuPlano liberou — e o degrau que lá se
 * chama "aprovado" *não* é liberado, é conversa interna. O aplicativo não conhece outra
 * porta: lê `mensais` e nada mais. Reimplementar a régua deste lado criaria uma segunda
 * resposta para "este documento pode ser mostrado?", e a errada seria a que entrega ao
 * cliente um relatório que ninguém liberou.
 */
export type RelatorioMensal = {
  /** O id **no meuPlano**. É o que `/manutencao/relatorios-mensais/{id}/pdf` aceita. */
  id: number
  /** O id do vínculo **neste sistema** — o mesmo de `Relatorio.plant_id`. */
  usina_id: number
  usina: string
  /** `YYYY-MM`, o mês fechado. Vem PRONTO do servidor: aqui não se deriva mês de data. */
  competencia: string
  /** `executivo` (o resumo da diretoria) ou `tecnico` (o laudo). Cru: valor novo chega. */
  tipo: string
  /**
   * Quando a equipe LIBEROU o documento — a única data que sai para o cliente. `aprovado_por`
   * (nome de funcionário da executora), `aprovado_em` e `apurado_em` não atravessam o BFF de
   * propósito. Nulo é ausência e vira travessão.
   */
  liberado_em: string | null
  /**
   * O peso do PDF, quando o servidor o declarar. **Medido em 06/09/2026: ele não declara** —
   * `RelatorioMensalOut` não tem o campo, e os dois documentos reais pesam 403.775 B e
   * 263.256 B do outro lado. Por isso o campo é opcional e NÃO entra em `CAMPOS_LIDOS`: não
   * há contrato a guardar enquanto ele não existir. Ausente vira travessão — nunca `0`, que
   * afirmaria arquivo vazio — e o dia em que o BFF passar a mandá-lo, a linha se preenche
   * sozinha.
   */
  bytes?: number | null
}

export type RelatoriosOut = {
  /** O nome do campo é do servidor, e o contrato não muda porque a aba mudou de rótulo. */
  documentos: Relatorio[]
  aviso: string | null
  /**
   * Os relatórios mensais de manutenção liberados. **Opcional de propósito**: um envelope
   * gravado em disco antes desta entrega não tem o campo, e o cache não tem versão — quem
   * está offline continua vendo a aba, com uma família só.
   */
  mensais?: RelatorioMensal[]
  /**
   * O que falhou na família MENSAL — e só nela. `aviso` continua sendo o da geração: juntar
   * os dois obrigaria a tela a reinterpretar prosa para saber de qual família é o motivo, que
   * foi exatamente o atalho que fez o aplicativo arrancar o prefixo "Manutenção:" com
   * expressão regular e mostrar a frase nas duas abas.
   */
  aviso_mensais?: string | null
}

export function useRelatorios(): Leitura<RelatoriosOut> {
  return fetchWithCache<RelatoriosOut>('documents', {
    // Documento, fatura e ficha não estragam com o tempo: o que foi emitido continua
    // valendo, e esconder um número desses por idade de cache seria esconder o correto.
    validadeMs: Infinity,
  })
}

/**
 * Os `tipo` da família MENSAL de manutenção. É por eles que `urlDoArquivo` sabe a que
 * acervo o documento pertence.
 *
 * **Os dois vocabulários são disjuntos, e não por acaso nosso:** o BFF declara o `tipo` da
 * geração como `Literal["geracao", "paradas", "resumo"]` — medido em 06/09/2026,
 * `GET /api/v1/documents/14/file?tipo=tecnico` responde **422**. Um `tipo` do mensal não
 * tem como significar uma peça de fechamento nem por engano, e o servidor é quem garante.
 * O teste de fonte confere a interseção vazia contra `PECAS`, para o dia em que alguém
 * quiser chamar de "tecnico" uma quarta peça de geração.
 */
export const TIPOS_DO_MENSAL = ['executivo', 'tecnico'] as const

export function ehTipoDoMensal(tipo: string): boolean {
  return (TIPOS_DO_MENSAL as readonly string[]).includes(tipo)
}

/** O nome do documento mensal — fonte única, lida também pelo cabeçalho da tela de abrir. */
export const ROTULO_DO_MENSAL = 'Relatório de manutenção'

/**
 * Endereço do PDF do relatório mensal de manutenção.
 *
 * Rota própria, e não a da geração: são dois acervos, de dois sistemas. Medida em
 * 06/09/2026 contra o BFF — 200 com `%PDF-1.4`, 403.775 B (executivo) e 263.256 B
 * (técnico), `inline` e `private, max-age=300`. **Um GET só, bytes prontos**: não há cesta
 * nem preparo em atos, como no pacote de fichas.
 */
export function urlDoRelatorioMensal(relatorioId: number): string {
  return `${baseURL}/api/v1/manutencao/relatorios-mensais/${relatorioId}/pdf`
}

/**
 * Endereço do PDF. A sessão vai em cabeçalho, nunca na URL — que entra em log.
 *
 * **Uma função para as duas famílias, e o `tipo` é o discriminador.** A alternativa seria
 * cada tela que abre um documento escolher o endereço por conta própria — e o caminho do
 * PDF já custou duas cópias com o mesmo defeito nas duas (ver `components/AbrirPdf`). Quem
 * chama continua chamando igual: a tela do documento (`app/relatorio/[id].tsx`) recebe o
 * `tipo` pela rota e não precisa saber que existem dois acervos.
 */
export function urlDoArquivo(relatorioId: number, tipo = 'geracao'): string {
  if (ehTipoDoMensal(tipo)) return urlDoRelatorioMensal(relatorioId)
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

/* ═══════════════════════════════════════════════ o cartão do relatório mensal ══ */

/**
 * Os dois relatórios de um mês são **um cartão com duas linhas** — nunca dois cartões, e
 * nunca um segmentado.
 *
 * Técnico e executivo não são "modos" nem "versões" do mesmo arquivo: são dois documentos,
 * de dois motores, com dois destinos. Mas são o fechamento **do mesmo mês da mesma usina**,
 * e separá-los em dois cartões faria o dono procurar duas vezes o que a equipe liberou uma.
 * A forma já existe e já está nesta tela: é a do fechamento de geração, cujas peças são
 * linhas dentro do cartão.
 */
export type CartaoMensal = {
  /**
   * A chave do cartão — TEXTO, e por isso jamais colide com o `id` numérico de um
   * fechamento de geração. Os dois convivem na mesma lista e na mesma gaveta, e o id do
   * meuPlano (14) e o do monitoramento (14) são números diferentes com o mesmo valor.
   */
  id: string
  usina_id: number
  usina: string
  /** `YYYY-MM` — é a gaveta, e é o que casa este cartão com o fechamento de geração. */
  competencia: string
  /** As peças na ordem que o servidor deu: executivo antes do técnico. */
  pecas: RelatorioMensal[]
}

/**
 * Agrupa os relatórios liberados em cartões de (usina × mês), **preservando a ordem do
 * servidor** — a do cartão é a da primeira peça que chegou; a das peças, a da resposta.
 *
 * O BFF já ordena competência mais recente primeiro e, dentro do mês, executivo antes do
 * técnico ("a diretoria é o destino que o próprio meuPlano declara para ele"). Reordenar
 * aqui seria uma segunda régua — e duas réguas dão duas respostas para a mesma pergunta,
 * uma no portal e outra no aplicativo.
 */
export function cartoesDoMensal(mensais: RelatorioMensal[]): CartaoMensal[] {
  const saida: CartaoMensal[] = []
  for (const m of mensais) {
    if (!m || !m.competencia || !m.tipo) continue
    const id = `manutencao-${m.usina_id}-${m.competencia}`
    const cartao = saida.find((c) => c.id === id)
    if (cartao) cartao.pecas.push(m)
    else
      saida.push({
        id,
        usina_id: m.usina_id,
        usina: m.usina,
        competencia: m.competencia,
        pecas: [m],
      })
  }
  return saida
}

/**
 * A data que o cartão carimba, rotulada "publicado".
 *
 * É a liberação mais RECENTE entre as peças — medido, as duas de Porto Ferreira saíram com
 * 1,3 s de diferença, que para quem lê é o mesmo instante. Nulo quando nenhuma peça declara
 * data: travessão, nunca uma data inventada a partir da competência.
 */
export function dataDoCartao(c: CartaoMensal): string | null {
  const datas = c.pecas.map((p) => p.liberado_em).filter((d): d is string => Boolean(d))
  if (datas.length === 0) return null
  return datas.reduce((a, b) => (a > b ? a : b))
}

/**
 * Como cada um dos dois documentos do mês se chama — **fonte única do aplicativo**, e o
 * mesmo nome que o portal escreve (`NOME_DO_TIPO_MENSAL`).
 *
 * O defeito que isto conserta foi medido na tela pelo dono (06/09/2026): as duas linhas do
 * cartão saíam com o título IDÊNTICO ("Relatório de manutenção") e a única diferença era um
 * rótulo miúdo na segunda linha — enquanto a linha vizinha, do fechamento de geração, dizia
 * "Relatório de Geração · técnico · 2,7 MB". Rolando a lista, dois títulos iguais fazem
 * procurar duas vezes o que se liberou uma vez.
 *
 * A versão CURTA existe para a folha do mês da grade do ano, onde o nome entra dentro de um
 * botão ("Abrir o Executivo") e o cabeçalho da folha já disse que se trata de manutenção.
 * São dois comprimentos do MESMO nome, num arquivo só: duas cópias dariam dois nomes.
 */
export const NOME_DO_MENSAL: Record<string, string> = {
  executivo: 'Relatório executivo',
  tecnico: 'Relatório técnico',
}

export const NOME_CURTO_DO_MENSAL: Record<string, string> = {
  executivo: 'Executivo',
  tecnico: 'Técnico',
}

/** Para quem cada um foi escrito — a frase que separa as duas linhas do cartão. */
export const DESTINO_DO_MENSAL: Record<string, string> = {
  executivo: 'O resumo do mês, para a diretoria.',
  tecnico: 'O laudo completo, com o cronograma, as ordens e as fichas do mês.',
}

/**
 * O nome da linha.
 *
 * `tipo` desconhecido cai no nome do produto ("Relatório de manutenção") em vez de sumir —
 * e o CÓDIGO CRU continua visível na segunda linha, que é onde `detalheDoMensal` o escreve.
 * Sem argumento devolve o nome do produto: é o que o cabeçalho da tela de leitura usa
 * quando ainda não sabe de qual dos dois se trata.
 */
export function rotuloDoMensal(tipo?: string): string {
  return (tipo ? NOME_DO_MENSAL[tipo] : undefined) ?? ROTULO_DO_MENSAL
}

/**
 * A segunda linha da peça mensal: **para quem ela é** — e o peso, quando ele existir.
 *
 * Antes esta linha era `público · peso` e, como o BFF não declara `bytes` nesta família,
 * saía "executivo · —": um travessão pendurado ao lado de uma vizinha que anuncia "2,7 MB".
 * Agora o público está no NOME (acima) e aqui vai a frase que diz para quem o documento foi
 * escrito — a mesma do portal, palavra por palavra.
 *
 * **O peso não virou travessão: ele saiu da promessa.** A tela não deixa de responder uma
 * pergunta que o servidor responde — ele não manda o campo, e por isso ela não fala de
 * tamanho nesta família. No dia em que `bytes` chegar, ele entra ao lado da frase sozinho.
 * Coalescer para `0 B` seguiria proibido: afirmaria arquivo vazio.
 *
 * `tipo` desconhecido sai CRU (com o peso, se vier), e não engolido num rótulo genérico: o
 * dia em que o meuPlano criar um terceiro documento, ele aparece na tela em vez de sumir.
 */
export function detalheDoMensal(m: RelatorioMensal): string {
  const destino = DESTINO_DO_MENSAL[m.tipo]
  const tamanho = m.bytes === null || m.bytes === undefined ? null : peso(m.bytes)
  if (!destino) return tamanho ? `${m.tipo} · ${tamanho}` : m.tipo
  return tamanho ? `${destino} · ${tamanho}` : destino
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

/* ═════════════════════════════════════════════════════ as duas famílias, uma lista ══ */

/**
 * O que o acervo mostra: um fechamento de GERAÇÃO ou um cartão de MANUTENÇÃO.
 *
 * União estrutural, e não um envelope `{familia, doc}`: assim `agruparPorGaveta` e
 * `recorte` continuam recebendo `Relatorio[]` sem nenhuma cerimônia, e as duas famílias
 * dividem uma régua só de gaveta, de filtro e de contagem. Uma segunda régua para a
 * família nova daria duas respostas para "de que mês é isto?" na mesma tela.
 */
export type ItemDoAcervo = Relatorio | CartaoMensal

/** Qual das duas famílias é este item. `pecas` só existe no cartão de manutenção. */
export function ehCartaoMensal(item: ItemDoAcervo): item is CartaoMensal {
  return 'pecas' in item
}

/**
 * A gaveta de qualquer item do acervo.
 *
 * O cartão de manutenção **sempre** tem competência (o BFF descarta o que chega sem ela),
 * então ela é a gaveta direto — sem passar pelo espelho `de.slice(0, 7)`, que é remendo de
 * cache antigo da outra família.
 */
export function gavetaDoItem(item: ItemDoAcervo): string {
  if (ehCartaoMensal(item)) return item.competencia || 'sem-data'
  return gavetaDoRelatorio(item)
}

export type Gaveta = { chave: string; rotulo: string; itens: ItemDoAcervo[] }

/**
 * Agrupa por período coberto **preservando a ordem do servidor** (publicação mais recente
 * primeiro). Reordenar aqui seria uma segunda régua de ordenação, e duas réguas dão duas
 * respostas para "qual é o mais novo".
 */
export function agruparPorGaveta(itens: ItemDoAcervo[]): Gaveta[] {
  const saida: Gaveta[] = []
  for (const r of itens) {
    const chave = gavetaDoItem(r)
    const gaveta = saida.find((g) => g.chave === chave)
    if (gaveta) gaveta.itens.push(r)
    else saida.push({ chave, rotulo: rotuloDaGaveta(chave), itens: [r] })
  }
  return saida
}

const MES_CHAVE = /^\d{4}-\d{2}$/

/**
 * As duas famílias numa lista só — **a ordem do servidor é preservada, nada é reordenado**.
 *
 * A espinha é a geração: a sequência de gavetas é a que o BFF entregou. O cartão de
 * manutenção entra na gaveta do seu mês, depois dos fechamentos daquele mês (que é a ordem
 * em que a tela os desenha).
 *
 * A única decisão nossa é o mês que **só** a manutenção tem — e ela existe porque a
 * alternativa está errada de forma visível: jogá-lo no fim poria setembro depois de maio.
 * Ele é ENCAIXADO entre os meses que já existem, no lugar cronológico. Não é reordenar o
 * que o servidor ordenou; é achar lugar para o que ele não tinha onde pôr. Gaveta que não
 * é mês (`ano:2026`, `sem-data`) não serve de âncora e não é movida.
 */
export function acervo(dados: RelatoriosOut | null | undefined): ItemDoAcervo[] {
  const documentos = dados?.documentos ?? []
  const cartoes = cartoesDoMensal(dados?.mensais ?? [])
  if (cartoes.length === 0) return [...documentos]

  const ordem: string[] = []
  for (const d of documentos) {
    const g = gavetaDoItem(d)
    if (!ordem.includes(g)) ordem.push(g)
  }
  for (const c of cartoes) {
    if (ordem.includes(c.competencia)) continue
    const maisAntigo = ordem.findIndex((x) => MES_CHAVE.test(x) && x < c.competencia)
    if (maisAntigo === -1) ordem.push(c.competencia)
    else ordem.splice(maisAntigo, 0, c.competencia)
  }

  const saida: ItemDoAcervo[] = []
  for (const g of ordem) {
    saida.push(...documentos.filter((d) => gavetaDoItem(d) === g))
    saida.push(...cartoes.filter((c) => c.competencia === g))
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
  visiveis: ItemDoAcervo[]
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
  itens: ItemDoAcervo[],
  usinaEscolhida: string | null,
  gavetaEscolhida: string | null,
): Recorte {
  const usinasPresentes = [...new Set(itens.map((r) => r.usina))].sort((a, b) =>
    a.localeCompare(b, 'pt-BR'),
  )
  const usina = usinaEscolhida && usinasPresentes.includes(usinaEscolhida) ? usinaEscolhida : null

  const daUsina = usina ? itens.filter((r) => r.usina === usina) : itens

  // A ordem dos períodos segue a do servidor (publicação mais recente primeiro).
  const gavetasPresentes = [...new Set(daUsina.map(gavetaDoItem))]
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
      contagem: daUsina.filter((r) => gavetaDoItem(r) === c).length,
    })),
  ]

  return {
    usina,
    gaveta,
    opcoesDeUsina,
    opcoesDeGaveta,
    visiveis: gaveta ? daUsina.filter((r) => gavetaDoItem(r) === gaveta) : daUsina,
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
export function vazioDaLista(
  aviso: string | null | undefined,
  avisoMensais?: string | null,
): Vazio {
  // As DUAS pontes contam, e cada motivo chega com a família escrita nele. Se só o mensal
  // caiu, o título ainda não pode AFIRMAR que nada foi publicado — é o mesmo defeito de
  // antes, com a outra família: não se sabe se há relatório, e dizer que não há é inventar.
  const motivos = [aviso, avisoMensais].filter((x): x is string => Boolean(x))
  if (motivos.length > 0) {
    return { titulo: 'Não deu para saber', descricao: motivos.join(' '), ponte: true }
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
  // `bytes` NÃO entra: o BFF ainda não declara peso nesta família (medido em 06/09/2026), e
  // exigir um campo que não existe daria o contrato por quebrado no dia em que ele está
  // certo — alguém "consertaria" apagando a checagem. A tela já trata a ausência.
  RelatorioMensalOut: ['id', 'usina_id', 'usina', 'competencia', 'tipo', 'liberado_em'],
  DocumentosOut: ['documentos', 'aviso', 'mensais', 'aviso_mensais'],
} as const
