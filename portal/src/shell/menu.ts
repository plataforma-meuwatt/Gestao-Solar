/**
 * O menu do portal — o "catálogo" de navegação, em DUAS famílias.
 *
 * Fonte única do que existe: a barra larga (com texto), o trilho estreito (só ícone) e a
 * gaveta do celular leem TODOS daqui. Sem isso, uma seção nova entraria em um dos três e
 * sumiria nos outros, dependendo do tamanho do monitor de quem testou.
 *
 * **Geração de energia e Manutenção são assuntos diferentes, com donos diferentes na empresa
 * do cliente.** Quem cobra geração não abre ordem de serviço; quem acompanha manutenção não
 * discute performance ratio. Antes as seis seções eram uma fileira só, e "Paradas" — que é
 * perda de ENERGIA — ficava encostada em "Cronograma". Agora cada família tem cabeçalho
 * próprio, e Relatórios fica sozinho embaixo porque guarda as duas.
 *
 * **A URL nomeia a família** (`/energia/...`, `/manutencao/...`). Link colado em e-mail tem de
 * dizer de que assunto se trata, e menu separado com endereço misturado é separação de
 * fachada. Por isso nenhum `fim` é vazio — a tela de energia mora em `/energia`, não na raiz
 * da usina, e quem chegar pela raiz é redirecionado (ver `App.tsx`).
 *
 * **Dois itens não são de usina nenhuma.** Os comparativos (`/comparar/energia` e
 * `/comparar/manutencao`) são da CARTEIRA: a pergunta "qual gera mais" e "qual está mais
 * atrasada" não tem resposta dentro de uma usina. Eles ficam marcados com `carteira: true`,
 * abrem a família a que pertencem (é lá que quem pergunta está olhando) e o endereço deles
 * NÃO carrega `:id`. Quem monta o endereço de uma entrada é `paraDaSecao` — concatenar
 * `/usinas/${id}` à mão manda o cliente para uma rota que só existe como redirecionamento.
 *
 * O ícone existe por causa do trilho: entre 768 px e 1024 px não cabe rótulo, e o ícone é a
 * única âncora. Ele é sempre acompanhado de `title`/`aria-label` com o mesmo texto do rótulo
 * — ícone sozinho e sem nome é adivinhação. É também por causa do trilho que o Painel usa
 * `Gauge` e não `Zap`: `Zap` é o ícone-cabeçalho da família, e dois iguais empilhados
 * apagariam justamente a separação que o cabeçalho existe para mostrar.
 */

import {
  AlertTriangle,
  ArrowLeftRight,
  CalendarDays,
  ClipboardList,
  Download,
  FileText,
  Gauge,
  LayoutGrid,
  ListChecks,
  Scale,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react'

/** A que assunto a seção pertence. `geral` = serve às duas famílias. */
export type Familia = 'geracao' | 'manutencao' | 'geral'

export type ItemDeSecao = {
  /**
   * O caminho da entrada.
   *
   * Nas seções DE UMA USINA é o sufixo COMPLETO depois de `/usinas/:id` — nunca vazio, e é
   * ele que o seletor de usina concatena para preservar a seção ao trocar de usina.
   *
   * Nos itens de CARTEIRA (`carteira: true`) é o caminho INTEIRO, a partir da raiz: eles não
   * pertencem a usina nenhuma. Use sempre `paraDaSecao` para montar o endereço, nunca a
   * concatenação à mão — foi ela que obrigou este campo a ter dois significados.
   */
  fim: string
  rotulo: string
  icone: LucideIcon
  familia: Familia
  /**
   * A entrada é da CARTEIRA (todas as usinas), não de uma usina.
   *
   * Os dois comparativos são disso: a pergunta "qual gera mais / qual está mais atrasada"
   * não tem resposta dentro de uma usina, e por isso o endereço deles não carrega `:id`.
   * Eles entram na família porque é lá que quem faz a pergunta está olhando — quem cobra
   * kWh não abre ordem de serviço —, mas o contexto é a carteira inteira.
   */
  carteira?: boolean
}

/** Para onde vai quem entra numa usina sem dizer a seção. */
export const SECAO_PADRAO = '/energia'

/** As seções DE UMA USINA. A Visão geral fica fora: ela é a carteira inteira. */
export const SECOES: ItemDeSecao[] = [
  {
    fim: '/comparar/energia',
    // Rótulo CURTO porque o item vive sob o cabeçalho "Comparar usinas", que já diz o
    // resto: na barra estreita "Comparar manutenção" saía truncado em "Comparar manuten…".
    rotulo: 'Geração',
    icone: ArrowLeftRight,
    familia: 'geracao',
    carteira: true,
  },
  { fim: '/energia', rotulo: 'Painel', icone: Gauge, familia: 'geracao' },
  { fim: '/energia/paradas', rotulo: 'Paradas', icone: AlertTriangle, familia: 'geracao' },
  // O único rótulo que é VERBO, e de propósito: as três irmãs da família são leituras
  // (Painel, Paradas, Geração), e daqui se sai com um ARQUIVO, não com um número na tela. Não
  // mora em Relatórios porque aquela tela é a única de família `geral` justamente por guardar
  // as duas — e a exportação é só geração (não há uma linha de manutenção no contrato do
  // meuWatt). Também não é entrada de carteira: a rota do monitoramento existe POR usina.
  { fim: '/energia/dados', rotulo: 'Baixar dados', icone: Download, familia: 'geracao' },
  {
    fim: '/comparar/manutencao',
    rotulo: 'Manutenção das usinas',
    icone: Scale,
    familia: 'manutencao',
    carteira: true,
  },
  { fim: '/manutencao/cronograma', rotulo: 'Cronograma', icone: CalendarDays, familia: 'manutencao' },
  {
    fim: '/manutencao/ordens',
    rotulo: 'Ordens de serviço',
    icone: ClipboardList,
    familia: 'manutencao',
  },
  { fim: '/manutencao/pendencias', rotulo: 'Pendências', icone: ListChecks, familia: 'manutencao' },
  { fim: '/relatorios', rotulo: 'Relatórios', icone: FileText, familia: 'geral' },
]

export type GrupoDeSecoes = {
  familia: Familia
  /** Cabeçalho na barra larga e na gaveta. `null` = grupo sem cabeçalho, só um separador. */
  nome: string | null
  /** Ícone-cabeçalho do trilho estreito, onde o nome não cabe. `null` = só o separador. */
  icone: LucideIcon | null
}

/**
 * A ordem dos grupos na navegação.
 *
 * Relatórios não ganha cabeçalho: o grupo teria uma linha só, com o mesmo nome do item — um
 * rótulo que repete o que está logo abaixo é ruído. O separador basta para dizer "isto não é
 * manutenção".
 */
export const GRUPOS: GrupoDeSecoes[] = [
  { familia: 'geracao', nome: 'Geração de energia', icone: Zap },
  { familia: 'manutencao', nome: 'Manutenção', icone: Wrench },
  { familia: 'geral', nome: null, icone: null },
]

export const VISAO_GERAL = { para: '/', rotulo: 'Visão geral', icone: LayoutGrid }

/** As entradas de uma família, na ordem do catálogo — carteira e usina juntas. */
export function secoesDaFamilia(familia: Familia): ItemDeSecao[] {
  return SECOES.filter((s) => s.familia === familia)
}

/** Só as seções DE UMA USINA — as que o sufixo de `/usinas/:id` alcança. */
export function secoesDaUsina(): ItemDeSecao[] {
  return SECOES.filter((s) => !s.carteira)
}

/**
 * Só as entradas de CARTEIRA, na ordem do catálogo.
 *
 * Elas ganharam bloco próprio na navegação: postas sob o cabeçalho "Esta usina", diziam que
 * a comparação era daquela usina — quando ela é justamente das outras seis. E o bloco existe
 * mesmo sem usina escolhida, porque nenhuma das duas precisa de uma.
 */
export function secoesDaCarteira(): ItemDeSecao[] {
  return SECOES.filter((s) => s.carteira)
}

/**
 * O endereço de uma entrada do menu.
 *
 * Item de carteira vale por si (`/comparar/energia`); seção de usina é o sufixo colado no
 * `/usinas/:id`. A regra mora AQUI, e não em cada lugar que desenha a navegação, porque a
 * barra larga, o trilho de ícones e a gaveta do celular montam o mesmo endereço três vezes —
 * e uma delas ia acabar montando errado.
 *
 * Sem usina, a seção de usina não tem para onde ir: devolve `null`, e quem desenha a esconde.
 * É o que já acontece hoje na Visão geral, onde nenhuma seção de usina aparece.
 */
export function paraDaSecao(secao: ItemDeSecao, usinaId: number | string | null): string | null {
  if (secao.carteira) return secao.fim
  return usinaId === null || usinaId === '' ? null : `/usinas/${usinaId}${secao.fim}`
}

/**
 * Qual seção o caminho atual representa — o sufixo, não o rótulo.
 *
 * Comparação do mais específico para o menos: `/usinas/3/energia/paradas` é "Paradas" e não
 * "Painel"; `/usinas/3/manutencao/ordens/12/tarefas/99` é "Ordens de serviço". Ordenar por
 * tamanho é o que impede o prefixo de engolir o filho — e é o que faz o seletor de usina
 * PRESERVAR a seção ao trocar de usina.
 *
 * Caminho que não é de seção nenhuma (a raiz da usina, um endereço antigo) cai no padrão
 * explícito: mandar para a raiz da usina devolveria o cliente a um redirecionamento em vez de
 * à tela que ele estava vendo.
 */
export function sufixoDaSecao(caminho: string): string {
  // A carteira é resolvida ANTES — e não como último recurso. `/comparar/energia` termina
  // em `/energia`, então a busca pelas seções de usina o reconheceria como "Painel" e
  // devolveria a resposta certa pelo caminho errado: no dia em que o Painel mudasse de
  // sufixo, o comparativo de energia passaria a mandar o cliente para outra família sem
  // nada quebrar. Aqui a intenção fica escrita.
  const carteira = [...SECOES]
    .filter((s) => s.carteira)
    .sort((a, b) => b.fim.length - a.fim.length)
    .find((s) => caminho === s.fim || caminho.startsWith(`${s.fim}/`))
  if (carteira) {
    // O cliente estava vendo a CARTEIRA e escolheu uma usina. O sufixo do comparativo não
    // serve — colado num `/usinas/:id` daria um endereço que só existe como
    // redirecionamento. Ele vai para a primeira seção da MESMA família, que é a tela mais
    // próxima da pergunta que estava fazendo: de "Comparar manutenção" cai no Cronograma
    // daquela usina, e não no painel de energia dela.
    const irma = secoesDaUsina().find((s) => s.familia === carteira.familia)
    if (irma) return irma.fim
  }

  const daUsina = [...secoesDaUsina()]
    .sort((a, b) => b.fim.length - a.fim.length)
    .find((s) => caminho.includes(`${s.fim}/`) || caminho.endsWith(s.fim))
  return daUsina?.fim ?? SECAO_PADRAO
}

/**
 * A seção precisa de casamento EXATO para se destacar no menu?
 *
 * Sim quando outra seção mora debaixo dela: sem isso, "Painel" (`/energia`) ficaria aceso
 * enquanto o cliente lê "Paradas" (`/energia/paradas`), porque um é prefixo do outro. Não nos
 * demais — "Ordens de serviço" TEM de continuar acesa na ficha de uma tarefa, que é uma tela
 * mais funda da mesma seção.
 */
export function casamentoExato(fim: string): boolean {
  return SECOES.some((s) => s.fim !== fim && s.fim.startsWith(`${fim}/`))
}

/** O caminho é de um comparativo de carteira? Usado por quem precisa esconder a usina. */
export function ehDaCarteira(caminho: string): boolean {
  return SECOES.some((s) => s.carteira && (caminho === s.fim || caminho.startsWith(`${s.fim}/`)))
}
