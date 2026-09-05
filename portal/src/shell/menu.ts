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
 * O ícone existe por causa do trilho: entre 768 px e 1024 px não cabe rótulo, e o ícone é a
 * única âncora. Ele é sempre acompanhado de `title`/`aria-label` com o mesmo texto do rótulo
 * — ícone sozinho e sem nome é adivinhação. É também por causa do trilho que o Painel usa
 * `Gauge` e não `Zap`: `Zap` é o ícone-cabeçalho da família, e dois iguais empilhados
 * apagariam justamente a separação que o cabeçalho existe para mostrar.
 */

import {
  AlertTriangle,
  CalendarDays,
  ClipboardList,
  FileText,
  Gauge,
  LayoutGrid,
  ListChecks,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react'

/** A que assunto a seção pertence. `geral` = serve às duas famílias. */
export type Familia = 'geracao' | 'manutencao' | 'geral'

export type ItemDeSecao = {
  /**
   * Sufixo COMPLETO do caminho depois de `/usinas/:id` — nunca vazio.
   * É ele que o seletor de usina concatena para preservar a seção ao trocar de usina.
   */
  fim: string
  rotulo: string
  icone: LucideIcon
  familia: Familia
}

/** Para onde vai quem entra numa usina sem dizer a seção. */
export const SECAO_PADRAO = '/energia'

/** As seções DE UMA USINA. A Visão geral fica fora: ela é a carteira inteira. */
export const SECOES: ItemDeSecao[] = [
  { fim: '/energia', rotulo: 'Painel', icone: Gauge, familia: 'geracao' },
  { fim: '/energia/paradas', rotulo: 'Paradas', icone: AlertTriangle, familia: 'geracao' },
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

/** As seções de uma família, na ordem do catálogo. */
export function secoesDaFamilia(familia: Familia): ItemDeSecao[] {
  return SECOES.filter((s) => s.familia === familia)
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
  const achada = [...SECOES]
    .sort((a, b) => b.fim.length - a.fim.length)
    .find((s) => caminho.includes(`${s.fim}/`) || caminho.endsWith(s.fim))
  return achada?.fim ?? SECAO_PADRAO
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
