/**
 * O menu do portal, numa lista só — o "catálogo" de navegação.
 *
 * Fonte única do que existe: a barra larga (com texto), o trilho estreito (só ícone) e a
 * gaveta do celular leem TODOS daqui. Sem isso, uma seção nova entraria em um dos três e
 * sumiria nos outros, dependendo do tamanho do monitor de quem testou.
 *
 * A ordem é a das perguntas que o cliente faz, e não a da complexidade interna: primeiro
 * quanto gerei (Energia), depois o que me atrapalhou (Paradas), depois se a manutenção está
 * sendo feita (Cronograma, Ordens), o que eu cobrei (Pendências) e o que levo para a
 * diretoria (Relatórios).
 *
 * O ícone existe por causa do trilho: entre 768 px e 1024 px não cabe rótulo, e o ícone é a
 * única âncora. Ele é sempre acompanhado de `title`/`aria-label` com o mesmo texto do rótulo
 * — ícone sozinho e sem nome é adivinhação.
 */

import {
  AlertTriangle,
  CalendarDays,
  ClipboardList,
  FileText,
  LayoutGrid,
  ListChecks,
  Zap,
  type LucideIcon,
} from 'lucide-react'

export type ItemDeSecao = {
  /** Sufixo do caminho depois de `/usinas/:id`. Vazio = a própria tela de Energia. */
  fim: string
  rotulo: string
  icone: LucideIcon
}

/** As seções DE UMA USINA. A Visão geral fica fora: ela é a carteira inteira. */
export const SECOES: ItemDeSecao[] = [
  { fim: '', rotulo: 'Energia', icone: Zap },
  { fim: '/paradas', rotulo: 'Paradas', icone: AlertTriangle },
  { fim: '/cronograma', rotulo: 'Cronograma', icone: CalendarDays },
  { fim: '/ordens', rotulo: 'Ordens de serviço', icone: ClipboardList },
  { fim: '/pendencias', rotulo: 'Pendências', icone: ListChecks },
  { fim: '/relatorios', rotulo: 'Relatórios', icone: FileText },
]

export const VISAO_GERAL = { para: '/', rotulo: 'Visão geral', icone: LayoutGrid }

/**
 * Qual seção o caminho atual representa.
 *
 * Comparação do mais específico para o menos: `/usinas/3/ordens/12` é a seção "Ordens de
 * serviço", e `/usinas/3` é "Energia". Ordenar por tamanho evita que `''` (Energia) case com
 * tudo — e é o que faz o seletor de usina PRESERVAR a seção ao trocar de usina.
 */
export function secaoDoCaminho(caminho: string): string {
  const achada = [...SECOES]
    .filter((s) => s.fim)
    .sort((a, b) => b.fim.length - a.fim.length)
    .find((s) => caminho.includes(`${s.fim}/`) || caminho.endsWith(s.fim))
  return achada?.fim ?? ''
}
