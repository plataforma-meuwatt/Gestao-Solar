/**
 * O quadro de pendências do CLIENTE — três colunas, e nenhuma delas se arrasta.
 *
 * ## Por que é somente leitura
 *
 * O cliente é leitor. Alça de arrasto, cursor de agarrar e alvo de soltura prometem um poder
 * que ele não tem: quem move uma pendência de coluna é a equipe, no meuPlano, e o movimento
 * carrega decisão de operação. Um quadro que parece arrastável e recusa o gesto é pior do que
 * um quadro que nunca prometeu — por isso aqui não há `draggable`, não há `onDragStart`, não
 * há `onDrop`, e nenhuma biblioteca de arrastar-e-soltar entra nesta tela.
 *
 * ## Por que as colunas são por SITUAÇÃO, e não por etapa
 *
 * O funil do meuPlano tem etapas que a equipe cria e renomeia ("A fazer", "Aguardando peça",
 * "Com o cliente"). Colunas por etapa fariam três coisas ruins de uma vez: vazariam o
 * processo interno para o portal do cliente, mudariam sozinhas no dia em que alguém
 * renomeasse uma coluna, e variariam de usina para usina. As três SITUAÇÕES
 * (`aguardando · em andamento · concluída`) são vocabulário estável, já traduzido e colorido
 * pelo BFF, e a coluna vem pronta em `coluna` — que o servidor deriva só do status, para a
 * pendência com prazo vencido continuar em "Aguardando", vermelha, e não sumir numa quarta
 * coluna. A etapa não se perde: continua escrita em cada card.
 *
 * ## Por que a ordem dentro da coluna é nossa
 *
 * O `display_order` do meuPlano é a mão do time — diz o que a equipe pretende pegar primeiro,
 * e não diz nada ao cliente. Aqui a ordem responde à pergunta dele: **vencidas primeiro**,
 * depois **o prazo mais próximo**, e por fim **quem teve atividade mais recente**. Quem não
 * tem prazo vai depois de quem tem, e não para o topo por um vazio ordenado como zero.
 *
 * ## No celular ele vira lista
 *
 * As três colunas empilham (`grid-cols-1`), o que no telefone é exatamente uma lista com
 * cabeçalhos — a degradação que o quadro precisa, sem uma segunda árvore de DOM escondida
 * atrás de um `hidden`, que duplicaria cada card e cada contagem.
 */

import { useState } from 'react'

import { Botao, Cartao, Num, Selo } from '@/components/base'
import { dataCurta, inteiro, quando } from '@/lib/format'
import { rotuloDaCriticidade, type Pendencia } from '@/features/pendencias/api'

/** Quantas concluídas aparecem antes do "ver todas": o resto da coluna é histórico. */
export const TETO_DA_CONCLUIDA = 5

export const COLUNAS: { chave: string; titulo: string; tom: string }[] = [
  { chave: 'aguardando', titulo: 'Aguardando', tom: 'alerta' },
  { chave: 'em_andamento', titulo: 'Em andamento', tom: 'ok' },
  { chave: 'concluida', titulo: 'Concluída', tom: 'semDados' },
]

/** `2026-09-30` como número comparável. Sem prazo = `null`, e vai para o fim. */
function prazoOrdenavel(p: Pendencia): number | null {
  if (!p.prazo) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(p.prazo)
  if (!m) return null
  return Number(`${m[1]}${m[2]}${m[3]}`)
}

function atividadeOrdenavel(p: Pendencia): number | null {
  const iso = p.ultima_atividade_em ?? p.aberta_em
  if (!iso) return null
  const t = new Date(iso).getTime()
  return Number.isNaN(t) ? null : t
}

/**
 * Vencidas → prazo mais próximo → atividade mais recente.
 *
 * "Vencida" é o veredito do servidor (`tom === 'parado'`), não uma segunda conta desta tela:
 * o card fica vermelho e o card fica em cima pela MESMA razão, então os dois nunca discordam.
 */
export function ordenar(linhas: Pendencia[]): Pendencia[] {
  return [...linhas].sort((a, b) => {
    const venceuA = a.tom === 'parado' ? 0 : 1
    const venceuB = b.tom === 'parado' ? 0 : 1
    if (venceuA !== venceuB) return venceuA - venceuB

    const pa = prazoOrdenavel(a)
    const pb = prazoOrdenavel(b)
    if (pa !== pb) {
      if (pa === null) return 1
      if (pb === null) return -1
      return pa - pb
    }

    const aa = atividadeOrdenavel(a)
    const ab = atividadeOrdenavel(b)
    if (aa === ab) return 0
    if (aa === null) return 1
    if (ab === null) return -1
    return ab - aa
  })
}

function Card({ p, aoAbrir }: { p: Pendencia; aoAbrir: (p: Pendencia) => void }) {
  const criticidade = rotuloDaCriticidade(p.criticidade)
  return (
    <button
      type="button"
      // `data-card` marca o cartão para o teste poder contar o que a coluna mostra sem
      // confundir com o botão "Ver todas" que vive na mesma coluna.
      data-card="pendencia"
      onClick={() => aoAbrir(p)}
      className="block w-full rounded-card border border-borda bg-superficie px-3 py-3 text-left transition hover:bg-superficie-alta"
    >
      <div className="flex items-start justify-between gap-2">
        <Num className="text-xs text-fraco">{p.numero === null ? '—' : `#${p.numero}`}</Num>
        <Selo tom={p.tom}>{p.situacao}</Selo>
      </div>

      <p className="mt-1.5 text-sm font-medium text-forte" title={p.titulo}>
        {p.titulo}
      </p>

      {p.equipamento ? (
        <p className="mt-0.5 truncate text-xs text-fraco" title={p.equipamento}>
          {p.equipamento}
          {p.equip_count !== null && p.equip_count > 1 ? ` +${inteiro(p.equip_count - 1)}` : ''}
        </p>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-fraco">
        {/* A etapa continua à vista: as colunas são por situação, e o funil da equipe é
            informação legítima — só não é o eixo do quadro. */}
        {p.etapa ? <span className="truncate">{p.etapa}</span> : null}
        {criticidade && p.criticidade_tom ? <Selo tom={p.criticidade_tom}>{criticidade}</Selo> : null}
        {p.cobrada_pelo_cliente ? <span>cobrada por você</span> : null}
      </div>

      <div className="mt-2 flex items-baseline justify-between gap-2 text-xs">
        <span className={p.tom === 'parado' ? 'text-tom-parado' : 'text-fraco'}>
          Prazo <Num>{dataCurta(p.prazo)}</Num>
        </span>
        <span className="text-fraco">{quando(p.ultima_atividade_em ?? p.aberta_em)}</span>
      </div>
    </button>
  )
}

function Coluna({
  titulo,
  tom,
  linhas,
  aoAbrir,
  recolhivel,
}: {
  titulo: string
  tom: string
  linhas: Pendencia[]
  aoAbrir: (p: Pendencia) => void
  recolhivel: boolean
}) {
  const [tudo, setTudo] = useState(false)
  const escondendo = recolhivel && !tudo && linhas.length > TETO_DA_CONCLUIDA
  const visiveis = escondendo ? linhas.slice(0, TETO_DA_CONCLUIDA) : linhas

  return (
    <section className="min-w-0" aria-label={titulo}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full bg-tom-${tom}`} aria-hidden />
          <h3 className="text-sm font-medium text-forte">{titulo}</h3>
        </div>
        <Num className="text-xs text-fraco">{inteiro(linhas.length)}</Num>
      </div>

      <div className="space-y-2 rounded-card bg-afundado p-2">
        {visiveis.length === 0 ? (
          // Coluna vazia diz que está vazia. Um retângulo mudo se lê como tela quebrada.
          <p className="px-1 py-4 text-center text-xs text-fraco">Nenhuma aqui.</p>
        ) : (
          visiveis.map((p) => <Card key={p.id} p={p} aoAbrir={aoAbrir} />)
        )}

        {escondendo ? (
          <Botao variante="discreto" onClick={() => setTudo(true)} className="w-full">
            {`Ver todas as ${inteiro(linhas.length)}`}
          </Botao>
        ) : null}
      </div>
    </section>
  )
}

/**
 * O quadro. Recebe as linhas JÁ FILTRADAS — o filtro é da página, e o quadro e a lista
 * mostram exatamente o mesmo conjunto; alternar a vista nunca muda o que se vê, só como.
 */
export function Kanban({
  linhas,
  aoAbrir,
}: {
  linhas: Pendencia[]
  aoAbrir: (p: Pendencia) => void
}) {
  return (
    <Cartao>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {COLUNAS.map((c) => (
          <Coluna
            key={c.chave}
            titulo={c.titulo}
            tom={c.tom}
            linhas={ordenar(linhas.filter((p) => p.coluna === c.chave))}
            aoAbrir={aoAbrir}
            // Só a de concluídas recolhe: é a única que cresce sem parar e cujo conteúdo
            // é histórico. Recolher "Aguardando" esconderia justamente a cobrança em pé.
            recolhivel={c.chave === 'concluida'}
          />
        ))}
      </div>
    </Cartao>
  )
}
