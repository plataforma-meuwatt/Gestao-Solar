/**
 * As regras de LEITURA da manutenção — puras, sem rede, sem React, sem React Native.
 *
 * Existem por dois motivos.
 *
 * **O primeiro é o defeito que criou este arquivo.** O BFF renomeou `OrdemOut.numero` para
 * `contrato_numero` (o campo nunca foi o número da OS — é o número do CONTRATO que a rege) e
 * a tela do aplicativo continuou lendo `o.numero`. O guarda que existia era
 * `o.numero !== null`, e `undefined !== null` é **verdadeiro**: toda ordem de serviço passou
 * a imprimir **"Contrato nº undefined"** para o dono. Pior: o cache em disco fez o defeito
 * aparecer e sumir conforme a leitura viesse do arquivo antigo ou da rede. O aplicativo era
 * o único consumidor do BFF sem um teste sequer, então nada avisou.
 *
 * **O segundo é a tradução duplicada.** Cada tela tinha a sua cópia das funções que
 * traduziam o código da classificação e escolhiam a cor dela e a do parecer — telas
 * decidindo sozinhas o texto e o tom de um dado que o servidor JÁ manda pronto
 * (`classificacao`, `classificacao_tom`, `parecer_tom`). Duas cópias divergem; três
 * divergem mais rápido. Aqui não há tradução
 * nenhuma: só as regras de MONTAGEM da tela (agrupar, marcar, filtrar), que são desenho e
 * não vocabulário.
 *
 * Nada aqui faz conta com número que o servidor mediu. O recorte de vigência do cronograma,
 * por exemplo, é **repassado** — foi refazer essa divisão que produziu "13 de 270" numa tela
 * e "41,9 %" na outra, para a mesma usina sem uma única atividade atrasada.
 *
 * Pendências mora neste arquivo de propósito: no aplicativo elas são parte da família
 * Manutenção (a entrada é a aba Manutenção), e a régua de filtro é irmã da do cronograma.
 */

import type { Tom } from '@/theme/tokens'

/* ══════════════════════════════════════════════════════════════════════════
 * Guardas contra vocabulário novo do servidor
 * ═════════════════════════════════════════════════════════════════════════ */

const TONS: readonly string[] = [
  'parado',
  'alerta',
  'multiplos',
  'tempoRuim',
  'ok',
  'semDados',
]

/**
 * O tom que o servidor mandou, quando é um dos seis. Qualquer outra coisa vira `semDados`.
 *
 * NÃO é tradução: a decisão de cor continua sendo do BFF. É só a rede de proteção para o dia
 * em que ele ganhar um sétimo tom — a tela mostra o texto em cinza em vez de estourar num
 * `tons[t]` que devolve `undefined` e derruba o `StyleSheet`.
 */
export function tomValido(t: string | null | undefined): Tom {
  return TONS.includes(t ?? '') ? (t as Tom) : 'semDados'
}

/**
 * O rótulo da linha "Contrato" da OS — ou `null` quando não há contrato.
 *
 * **É este o guarda que faltava.** `undefined` (campo ausente, campo renomeado, cache de uma
 * versão anterior do aplicativo) e `null` (o servidor disse que não há) resultam os dois em
 * `null`, e a linha inteira não é desenhada. `NaN` também: veio de um JSON estragado, e
 * "Contrato nº NaN" é a mesma mentira com outro nome.
 */
export function rotuloDoContrato(numero: number | null | undefined): string | null {
  if (typeof numero !== 'number' || !Number.isFinite(numero)) return null
  return `nº ${numero}`
}

/* ══════════════════════════════════════════════════════════════════════════
 * Cronograma — a marca de cada célula
 * ═════════════════════════════════════════════════════════════════════════ */

/** Só o que a tela precisa saber de uma célula para escolher a marca. */
export type CelulaLida = {
  estado: string | null
  feito: boolean
  dispensado: boolean
  atrasado: boolean
  previsto: number
}

/**
 * As SEIS marcas de uma célula do cronograma.
 *
 * `alerta` é a que faltava. O meuPlano tem cinco `cell_status` — `verde` (feito),
 * `verde_ressalva` (dispensado com motivo), `vermelho` (atrasado), **`laranja`** (venceu o
 * mês mas ainda está dentro da janela de tolerância) e `azul` (previsto, no prazo). O BFF
 * repassa os cinco em `estado`, mas só transforma três em booleano — `laranja` não tem
 * booleano nenhum. A tela caía no `previsto > 0` e desenhava o MESMO ponto cinza do "no
 * prazo": a atividade que passou do mês e ainda pode ser salva ficava indistinguível da que
 * nem venceu, que é justamente a diferença que faz alguém ligar para o prestador hoje.
 */
export type Marca = 'feito' | 'dispensado' | 'atrasado' | 'alerta' | 'previsto' | 'vazio'

/**
 * A marca da célula. **A ordem dos testes é a regra**, não estilo:
 *
 * 1. `feito` antes de tudo;
 * 2. `dispensado` (`verde_ressalva`) NUNCA cai no ramo de feito — apagar essa diferença era
 *    o risco de produto que o meuPlano recusou correr, e não vamos reintroduzi-lo na última
 *    tela da cadeia;
 * 3. `atrasado` (vermelho);
 * 4. `laranja` — o estado sem booleano, lido do campo cru;
 * 5. `previsto > 0` — combinado e ainda no prazo;
 * 6. mês em que o contrato não pede nada.
 */
export function marcaDaCelula(c: CelulaLida): Marca {
  if (c.feito) return 'feito'
  if (c.dispensado) return 'dispensado'
  if (c.atrasado) return 'atrasado'
  if ((c.estado ?? '').trim().toLowerCase() === 'laranja') return 'alerta'
  if (c.previsto > 0) return 'previsto'
  return 'vazio'
}

/** O tom de cada marca. Único lugar onde a cor da célula é decidida. */
export const TOM_DA_MARCA: Record<Marca, Tom> = {
  feito: 'ok',
  dispensado: 'ok',
  atrasado: 'parado',
  alerta: 'alerta',
  previsto: 'semDados',
  vazio: 'semDados',
}

/* ══════════════════════════════════════════════════════════════════════════
 * Cronograma — os blocos
 * ═════════════════════════════════════════════════════════════════════════ */

/** O mínimo que uma linha precisa ter para entrar num bloco. */
export type LinhaAgrupavel = {
  grupo: string
  previsto_ano: number
  feitos: number
  meses: CelulaLida[]
}

export type Bloco<L extends LinhaAgrupavel> = {
  grupo: string
  linhas: L[]
  /** Σ do previsto do ano das linhas do bloco. */
  previsto_ano: number
  /** Σ do cumprido (feito + dispensado — a mesma conta que o BFF faz por linha). */
  feitos: number
  /** Quantas células vermelhas o bloco tem. É o que o cabeçalho fechado precisa gritar. */
  atrasos: number
  /** Quantas células laranja — venceu o mês, ainda dá tempo. */
  alertas: number
}

/**
 * As linhas do cronograma agrupadas pelo `grupo` que o servidor já manda.
 *
 * O contrato de Porto Ferreira tem **94 linhas**. Noventa e quatro linhas de altura fixa numa
 * grade de doze colunas é a análise equipamento a equipamento que o dono disse que o cliente
 * NÃO quer ver — e foi exatamente o que a captura de tela mostrou: quinze faixas cinzas
 * chapadas e nenhum número legível. Agrupadas e RECOLHIDAS, viram quinze blocos que respondem
 * "está sendo feito?" de relance, com o detalhe atrás de um toque.
 *
 * A ordem é a de PRIMEIRA APARIÇÃO, e não alfabética: o servidor já ordenou as linhas por
 * grupo e nome, e reordenar aqui produziria uma segunda ordem para a mesma lista.
 */
export function agruparCronograma<L extends LinhaAgrupavel>(linhas: L[]): Bloco<L>[] {
  const blocos: Bloco<L>[] = []
  const porNome = new Map<string, Bloco<L>>()
  for (const l of linhas) {
    // Grupo em branco não vira bloco anônimo: o BFF já garante "Outras atividades", e um
    // bloco com título vazio é uma faixa que ninguém sabe o que é.
    const nome = l.grupo.trim() || 'Outras atividades'
    let bloco = porNome.get(nome)
    if (!bloco) {
      bloco = { grupo: nome, linhas: [], previsto_ano: 0, feitos: 0, atrasos: 0, alertas: 0 }
      porNome.set(nome, bloco)
      blocos.push(bloco)
    }
    bloco.linhas.push(l)
    bloco.previsto_ano += l.previsto_ano
    bloco.feitos += l.feitos
    for (const cel of l.meses) {
      const marca = marcaDaCelula(cel)
      if (marca === 'atrasado') bloco.atrasos += 1
      else if (marca === 'alerta') bloco.alertas += 1
    }
  }
  return blocos
}

/* ══════════════════════════════════════════════════════════════════════════
 * Cronograma — o recorte de vigência, REPASSADO
 * ═════════════════════════════════════════════════════════════════════════ */

/** O que a tela precisa do cronograma para escrever a frase do recorte. */
export type CronogramaComRecorte = {
  mes_referencia: string | null
  previsto_ate_hoje: number | null
  cumprido_ate_hoje: number | null
  pct_ate_hoje: number | null
  previsto_no_contrato: number | null
}

export type Recorte = {
  /** 0–100, exatamente como o meuPlano calculou. Nulo = ele não informou. */
  pct: number | null
  /** "13 de 31" — o denominador impresso ao lado do percentual. Nulo se faltar um dos dois. */
  fracao: string | null
  /** "YYYY-MM" até onde a conta olha. */
  ate: string | null
  /** Σ de X dos 12 meses. É o "270" — o outro número, com o outro rótulo. */
  noContrato: number | null
}

/**
 * O recorte de vigência do cronograma, **sem uma única operação aritmética**.
 *
 * Percentual sem a janela de onde saiu é metade da frase, e foi a metade que faltava: a mesma
 * usina aparecia como "13 de 270" (4,8 %) numa tela e "41,9 %" na outra, sem nenhuma
 * atividade atrasada, porque uma dividia pelo ano inteiro e a outra só pelos meses já
 * vencidos dentro da vigência. A conta tem UM dono — o meuPlano, ao lado da régua que o
 * Relatório de manutenção já usa —, e este arquivo só repassa o resultado com o denominador
 * colado nele.
 *
 * Devolve `null` quando o servidor não mandou recorte nenhum: a tela mostra travessão, e não
 * um "0 %" que ninguém mediu.
 */
export function recorteDoCronograma(c: CronogramaComRecorte): Recorte | null {
  const temAlgo =
    c.mes_referencia !== null || c.previsto_ate_hoje !== null || c.pct_ate_hoje !== null
  if (!temAlgo) return null
  const cumprido = c.cumprido_ate_hoje
  const previsto = c.previsto_ate_hoje
  return {
    pct: c.pct_ate_hoje,
    fracao: cumprido !== null && previsto !== null ? `${cumprido} de ${previsto}` : null,
    ate: c.mes_referencia,
    noContrato: c.previsto_no_contrato,
  }
}

/* ══════════════════════════════════════════════════════════════════════════
 * Pendências — os recortes da lista
 * ═════════════════════════════════════════════════════════════════════════ */

/**
 * As situações que a lista oferece, todas derivadas de **`coluna`** — o campo do servidor
 * cujo vocabulário é fixo e documentado (`aguardando` · `em_andamento` · `concluida`).
 *
 * Deliberadamente NÃO existe uma opção "Prazo vencido": a régua de vencimento (prazo passado
 * E não concluída, com `extra.previsao_conclusao` na frente de `end_date`) mora no BFF, e
 * remontá-la aqui a partir da data crua criaria a segunda régua — o defeito que fez o cartão
 * marcar zero com linhas vermelhas logo abaixo. O vencimento chega pronto no `tom` e na
 * `situacao` de cada linha, e o total no contador `prazo_vencido`.
 */
export const SITUACOES = [
  { chave: 'abertas', rotulo: 'Em aberto', colunas: ['aguardando', 'em_andamento'] },
  { chave: 'aguardando', rotulo: 'Aguardando', colunas: ['aguardando'] },
  { chave: 'andamento', rotulo: 'Em andamento', colunas: ['em_andamento'] },
  { chave: 'concluidas', rotulo: 'Concluídas', colunas: ['concluida'] },
  { chave: 'todas', rotulo: 'Todas', colunas: null },
] as const

export type ChaveSituacao = (typeof SITUACOES)[number]['chave']

/** A situação com que a tela abre: o que ainda não terminou. */
export const SITUACAO_INICIAL: ChaveSituacao = 'abertas'

/** O segmentado do topo — NUNCA uma fileira de chips. */
export const RECORTES = ['Cobradas por mim', 'Todas as compartilhadas'] as const

/** O mínimo que uma pendência precisa ter para ser filtrada. */
export type PendenciaFiltravel = {
  usina: string
  coluna: string
  cobrada_pelo_cliente: boolean
}

/**
 * Com qual aba a lista abre.
 *
 * "Cobradas por mim" é o recorte que interessa ao cliente — o que ELE pediu e ainda não
 * voltou. Mas abrir nele quando o cliente não cobrou nada seria abrir numa tela vazia por
 * causa de um filtro que ele não escolheu, que é a lei que este produto mais repete. Sem
 * cobrança em aberto (ou sem o servidor ter contado), a lista abre em "Todas".
 */
export function recorteInicial(cobradasAbertas: number | null | undefined): number {
  return typeof cobradasAbertas === 'number' && cobradasAbertas > 0 ? 0 : 1
}

/** As colunas que a situação escolhida aceita. `null` = todas. */
function colunasDe(chave: ChaveSituacao): readonly string[] | null {
  return SITUACOES.find((s) => s.chave === chave)?.colunas ?? null
}

export type FiltroPendencias = {
  /** Nome da usina, ou `null` para todas. */
  usina: string | null
  situacao: ChaveSituacao
  /** `true` = só as que levam a marca do cliente. */
  soCobradas: boolean
}

/**
 * A lista filtrada, **na ordem em que o servidor mandou**.
 *
 * A ordem é do BFF (última atividade primeiro, sem data no fim) e não é reordenada aqui: a
 * tela e a tabela do portal têm de listar a mesma coisa na mesma ordem, senão "a terceira da
 * lista" quer dizer duas pendências diferentes em dois aparelhos.
 */
export function filtrarPendencias<P extends PendenciaFiltravel>(
  itens: P[],
  f: FiltroPendencias,
): P[] {
  const colunas = colunasDe(f.situacao)
  return itens.filter(
    (p) =>
      (f.usina === null || p.usina === f.usina)
      && (colunas === null || colunas.includes(p.coluna))
      && (!f.soCobradas || p.cobrada_pelo_cliente),
  )
}

/**
 * Quantas linhas cada situação teria, **respeitando os OUTROS filtros ativos**.
 *
 * É o que permite oferecer só o que existe: uma opção "Concluídas (0)" ainda pode ser
 * escolhida, mas o usuário sabe de antemão para onde vai — e nenhuma opção some da lista,
 * porque uma opção que desaparece é pior do que uma que avisa que está vazia.
 */
export function contarPorSituacao<P extends PendenciaFiltravel>(
  itens: P[],
  f: Omit<FiltroPendencias, 'situacao'>,
): Record<ChaveSituacao, number> {
  const saida = {} as Record<ChaveSituacao, number>
  for (const s of SITUACOES) {
    saida[s.chave] = filtrarPendencias(itens, { ...f, situacao: s.chave }).length
  }
  return saida
}

/**
 * A frase de "está vazio por causa do filtro, e é aqui que estão as outras".
 *
 * Devolve `null` quando há linhas para mostrar. Quando não há, diz **quantas existem no
 * recorte mais largo** — em vez de deixar o dono achando que a usina dele não tem pendência
 * nenhuma quando o que ele fez foi deixar um filtro ligado.
 */
export function vazioPorFiltro<P extends PendenciaFiltravel>(
  itens: P[],
  f: FiltroPendencias,
): string | null {
  if (filtrarPendencias(itens, f).length > 0) return null
  if (itens.length === 0) return null
  const semRecorte = filtrarPendencias(itens, { usina: null, situacao: 'todas', soCobradas: false })
  const quantas = semRecorte.length
  return quantas === 1
    ? 'Nada com estes filtros. Há 1 pendência compartilhada nas suas usinas.'
    : `Nada com estes filtros. Há ${quantas} pendências compartilhadas nas suas usinas.`
}

/* ══════════════════════════════════════════════════════════════════════════
 * O CONTRATO: que campo cada tela lê, de que rota
 * ═════════════════════════════════════════════════════════════════════════ */

/**
 * Os campos que o aplicativo lê, rota por rota — a lista que o teste de contrato confere
 * contra os modelos Pydantic do BFF.
 *
 * **É esta tabela que impede o "Contrato nº undefined" de voltar.** Quando o BFF renomear um
 * campo, o teste falha na hora, com o nome da rota e do campo — em vez de o dono descobrir
 * pela tela, semanas depois, e de forma intermitente porque o cache em disco ainda servia a
 * resposta antiga.
 *
 * Só entram os campos que a tela realmente usa: uma lista que copia o modelo inteiro passa a
 * falhar quando o BFF apaga um campo que ninguém lia, e um teste que falha por nada é um
 * teste que alguém desliga.
 */
export const CAMPOS_LIDOS: readonly {
  rota: string
  arquivo: 'manutencao' | 'pendencias'
  modelo: string
  campos: readonly string[]
}[] = [
  {
    rota: 'GET /api/v1/manutencao',
    arquivo: 'manutencao',
    modelo: 'ManutencaoOut',
    campos: ['total', 'ordens', 'usinas_com_manutencao', 'aviso'],
  },
  {
    rota: 'GET /api/v1/manutencao',
    arquivo: 'manutencao',
    modelo: 'OrdemAtendidaOut',
    campos: [
      'id', 'usina', 'objetivo', 'classificacao', 'status', 'fechada_em', 'aprovada_em',
      'tecnico', 'execucao_min', 'tarefas', 'tarefas_feitas', 'resumo',
    ],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens',
    arquivo: 'manutencao',
    modelo: 'OrdensOut',
    campos: ['total', 'em_andamento', 'ordens', 'usinas_com_manutencao', 'aviso'],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens/{so_id}',
    arquivo: 'manutencao',
    modelo: 'OrdemOut',
    campos: [
      'id', 'usina', 'usina_id',
      // o campo do defeito: era `numero`, e a tela imprimia "nº undefined"
      'contrato_numero',
      'objetivo', 'classificacao', 'classificacao_codigo', 'classificacao_tom',
      'status', 'situacao', 'tom', 'tecnico', 'tarefas', 'tarefas_feitas',
      'agendada_para', 'concluida_em', 'fechada_em', 'aprovada_em', 'execucao_min',
      'resumo', 'itens',
    ],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens/{so_id}/tarefas/{task_id}',
    arquivo: 'manutencao',
    modelo: 'TarefaOut',
    campos: [
      'id', 'nome', 'grupo', 'equipamento', 'status', 'situacao', 'feita', 'natureza',
      'parecer', 'parecer_tom', 'os_id', 'mes_contratual', 'executada_em',
      'descricao', 'observacoes', 'preenchimento',
    ],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens/{so_id}/tarefas/{task_id}/ficha',
    arquivo: 'manutencao',
    modelo: 'FichaOut',
    campos: ['id', 'nome', 'coletiva', 'parecer', 'equipamentos', 'fotos'],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens/{so_id}/tarefas/{task_id}/ficha',
    arquivo: 'manutencao',
    modelo: 'EquipamentoFichaOut',
    campos: [
      'equipamento', 'modelo', 'fabricante', 'numero_serie', 'executado_em',
      'executado_por', 'parecer', 'parecer_motivo', 'medicoes', 'checklist', 'fotos',
    ],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens/{so_id}/tarefas/{task_id}/ficha',
    arquivo: 'manutencao',
    modelo: 'LinhaMedicaoOut',
    campos: ['ponto', 'valor', 'unidade', 'alvo', 'desvio', 'aprovado', 'situacao', 'observacao'],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens/{so_id}/tarefas/{task_id}/ficha',
    arquivo: 'manutencao',
    modelo: 'PerguntaOut',
    campos: ['pergunta', 'resposta', 'problema', 'observacao', 'fotos'],
  },
  {
    rota: 'GET /api/v1/manutencao/ordens/{so_id}/tarefas/{task_id}/ficha',
    arquivo: 'manutencao',
    modelo: 'FotoOut',
    campos: ['id', 'legenda', 'url', 'thumb_url'],
  },
  {
    rota: 'GET /api/v1/manutencao/cronograma',
    arquivo: 'manutencao',
    modelo: 'CronogramaOut',
    campos: [
      'usina', 'usina_id', 'contrato_id', 'contrato', 'status', 'versao', 'meses', 'linhas',
      'previsto_ano', 'feitos_ano',
      // o recorte de vigência, repassado inteiro — nenhum deles é recalculado aqui
      'mes_referencia', 'previsto_ate_hoje', 'cumprido_ate_hoje', 'pct_ate_hoje',
      'previsto_no_contrato', 'meses_estado',
      'pdf_disponivel', 'aviso',
    ],
  },
  {
    rota: 'GET /api/v1/manutencao/cronograma',
    arquivo: 'manutencao',
    modelo: 'LinhaCronogramaOut',
    // `grupo` é o campo que transforma 94 linhas em 15 blocos
    campos: ['plan_item_id', 'nome', 'categoria', 'periodicidade', 'grupo', 'previsto_ano', 'feitos', 'meses'],
  },
  {
    rota: 'GET /api/v1/manutencao/cronograma',
    arquivo: 'manutencao',
    modelo: 'CelulaOut',
    // `estado` é o campo cru de onde sai o laranja, que não tem booleano próprio
    campos: ['mes', 'previsto', 'estado', 'feito', 'dispensado', 'atrasado'],
  },
  {
    rota: 'GET /api/v1/manutencao/cronograma',
    arquivo: 'manutencao',
    modelo: 'MesEstadoOut',
    campos: ['mes', 'situacao', 'previsto', 'cumprido'],
  },
  {
    rota: 'GET /api/v1/manutencao/cronograma/tarefas',
    arquivo: 'manutencao',
    modelo: 'TarefaOut',
    campos: ['id', 'nome', 'equipamento', 'situacao', 'feita', 'os_id'],
  },
  {
    rota: 'GET /api/v1/manutencao/pendencias',
    arquivo: 'pendencias',
    modelo: 'PendenciasOut',
    campos: [
      'total', 'abertas', 'concluidas', 'prazo_vencido', 'aguardando', 'em_andamento',
      'cobradas_abertas', 'pendencias', 'usinas_com_manutencao', 'aviso',
    ],
  },
  {
    rota: 'GET /api/v1/manutencao/pendencias',
    arquivo: 'pendencias',
    modelo: 'PendenciaOut',
    campos: [
      'id', 'numero', 'usina', 'usina_id', 'titulo', 'cobrada_pelo_cliente', 'etapa',
      'status', 'situacao', 'tom', 'coluna', 'criticidade', 'criticidade_tom',
      'criticidade_rank', 'responsavel', 'aberta_em', 'prazo', 'ultima_atividade_em',
      'faixa_parada', 'concluida_em', 'equipamento', 'equip_count', 'documentos', 'os_count',
    ],
  },
]
