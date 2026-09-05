/**
 * Os seis cortes da lista de Pendências — e a régua que decide o que sobra na tela.
 *
 * O defeito que este arquivo conserta: a tela abria com **18 linhas e nenhum filtro**, 15
 * delas concluídas. Oitenta e três por cento do que o cliente via era ruído, e não havia
 * como fazer a única pergunta que ele faz de verdade — *"o que está vencido?"*. Não era
 * falta de dado: `situacao`, `prazo`, `criticidade` e `faixa_parada` já vinham do servidor
 * e ninguém podia usá-los para nada.
 *
 * ## As decisões que este arquivo carrega
 *
 * **Nada de chip.** Todo corte é lista suspensa pesquisável (`Combobox`) ou campo de texto —
 * a regra da casa, e aqui ela tem razão prática: "usina" e "criticidade" nascem do dado e
 * podem ter duas ou vinte entradas; uma fileira de botõezinhos que cabia com duas some no
 * celular com vinte.
 *
 * **Opção que devolveria zero não existe.** Cada opção é contada contra as linhas que os
 * OUTROS cortes já deixaram passar, e a que zera é omitida. Oferecer "Crítica (0)" é
 * convidar o cliente a clicar num vazio; e um filtro que ele não pode desfazer sozinho
 * seria pior ainda — por isso a opção ESCOLHIDA nunca some da lista, mesmo zerada.
 *
 * **A contagem exclui o próprio eixo.** "Em andamento (4)" tem de significar *"clicando
 * aqui você vê 4"*. Contar com o próprio eixo aplicado daria (0) em toda opção não
 * escolhida — o número certo é o do recorte que resultaria, não o do atual.
 *
 * **O vermelho é do servidor; a data só estreita.** `prazo=vencidas` filtra por
 * `tom === 'parado'`, que é o veredito do BFF ("passou E não concluiu"). Só as janelas
 * FUTURAS ("vence em até 7 dias") comparam a data com o relógio do navegador — e elas
 * apenas escolhem linhas, nunca pintam nada. Duas réguas para a mesma cor divergem no
 * primeiro ajuste; para escolher o que aparece, o relógio local basta.
 *
 * **`?situacao=vencidas` é um endereço legítimo.** É o link que alguém manda dizendo "olha
 * o que está atrasado". Ele não é um sexto valor de Situação (senão haveria duas portas
 * para a mesma sala, e a tela marcaria o mesmo corte em dois lugares): entra como apelido e
 * cai no par honesto `situacao=abertas` + `prazo=vencidas`, com o Prazo marcado na tela —
 * o cliente vê exatamente por que a lista encolheu.
 */

import { Combobox, type Opcao } from '@/components/base'
import { inteiro } from '@/lib/format'
import { rotuloDaCriticidade, type Pendencia } from '@/features/pendencias/api'

/* ------------------------------------------------------------------ vocabulário */

export type Situacao = 'abertas' | 'aguardando' | 'em_andamento' | 'concluidas' | 'todas'
export type Prazo = 'todos' | 'vencidas' | 'vence7' | 'vence30' | 'sem_prazo'
export type Parada = 'todas' | 'hoje' | '7d' | '30d' | '+30d' | 'sem'
export type Segmento = 'cobradas' | 'todas'
export type Vista = 'lista' | 'kanban'

export type Filtros = {
  situacao: Situacao
  prazo: Prazo
  /** Id do vínculo, em texto — `'todas'` quando o corte está desligado. */
  usina: string
  /** Código da criticidade do meuPlano, `'sem'` para quem não tem, `'todas'` desligado. */
  criticidade: string
  parada: Parada
  busca: string
  segmento: Segmento
}

const SITUACOES: { valor: Situacao; rotulo: string }[] = [
  { valor: 'todas', rotulo: 'Todas as situações' },
  { valor: 'abertas', rotulo: 'Em aberto' },
  { valor: 'aguardando', rotulo: 'Aguardando' },
  { valor: 'em_andamento', rotulo: 'Em andamento' },
  { valor: 'concluidas', rotulo: 'Concluídas' },
]

const PRAZOS: { valor: Prazo; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Qualquer prazo' },
  { valor: 'vencidas', rotulo: 'Vencidas' },
  { valor: 'vence7', rotulo: 'Vence em até 7 dias' },
  { valor: 'vence30', rotulo: 'Vence em até 30 dias' },
  { valor: 'sem_prazo', rotulo: 'Sem prazo combinado' },
]

const PARADAS: { valor: Parada; rotulo: string }[] = [
  { valor: 'todas', rotulo: 'Qualquer atividade' },
  { valor: 'hoje', rotulo: 'Mexeram hoje' },
  { valor: '7d', rotulo: 'Há até 7 dias' },
  { valor: '30d', rotulo: 'Há até 30 dias' },
  { valor: '+30d', rotulo: 'Há mais de 30 dias' },
  { valor: 'sem', rotulo: 'Sem atividade registrada' },
]

export const FILTROS_PADRAO: Filtros = {
  situacao: 'abertas',
  prazo: 'todos',
  usina: 'todas',
  criticidade: 'todas',
  parada: 'todas',
  busca: '',
  segmento: 'todas',
}

/** Os eixos, na ordem em que aparecem na barra. `busca` é o sexto. */
export const EIXOS = ['situacao', 'prazo', 'usina', 'criticidade', 'parada', 'busca'] as const
export type Eixo = (typeof EIXOS)[number]

/* ------------------------------------------------------------------ a régua */

/** `2026-09-30` lido como data local — a mesma leitura de `dataCurta`, sem o erro de fuso. */
function comoData(iso: string | null): Date | null {
  if (!iso) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(d.getTime()) ? null : d
}

/** Dias entre hoje e o prazo. Negativo = já passou. */
function diasAte(prazo: string | null, hoje: Date): number | null {
  const d = comoData(prazo)
  if (!d) return null
  const zero = new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate())
  return Math.round((d.getTime() - zero.getTime()) / 86400000)
}

/** Sem acento e em minúsculas — para "aterramento" achar "Aterramento". */
function chave(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

/**
 * `true` quando a pendência passa NAQUELE eixo. Um eixo por função para a contagem poder
 * excluir exatamente um deles — ver o cabeçalho.
 */
const PASSA: Record<Eixo | 'segmento', (p: Pendencia, f: Filtros, hoje: Date) => boolean> = {
  situacao: (p, f) => {
    if (f.situacao === 'todas') return true
    if (f.situacao === 'abertas') return p.coluna !== 'concluida'
    if (f.situacao === 'concluidas') return p.coluna === 'concluida'
    return p.coluna === f.situacao
  },
  prazo: (p, f, hoje) => {
    if (f.prazo === 'todos') return true
    // O veredito de "venceu" é do servidor (`tom`), não uma segunda conta desta tela.
    if (f.prazo === 'vencidas') return p.tom === 'parado'
    if (f.prazo === 'sem_prazo') return p.prazo === null
    const dias = diasAte(p.prazo, hoje)
    if (dias === null || dias < 0) return false
    return f.prazo === 'vence7' ? dias <= 7 : dias <= 30
  },
  usina: (p, f) => f.usina === 'todas' || String(p.usina_id) === f.usina,
  criticidade: (p, f) => {
    if (f.criticidade === 'todas') return true
    if (f.criticidade === 'sem') return p.criticidade === null
    return (p.criticidade ?? '').trim().toLowerCase() === f.criticidade
  },
  parada: (p, f) => {
    if (f.parada === 'todas') return true
    if (f.parada === 'sem') return p.faixa_parada === null
    return p.faixa_parada === f.parada
  },
  busca: (p, f) => {
    const t = chave(f.busca.trim())
    if (!t) return true
    const numero = p.numero === null ? '' : `#${p.numero} ${p.numero}`
    return chave(`${p.titulo} ${numero} ${p.equipamento ?? ''} ${p.etapa ?? ''}`).includes(t)
  },
  segmento: (p, f) => f.segmento === 'todas' || p.cobrada_pelo_cliente,
}

const TODOS_OS_EIXOS = [...EIXOS, 'segmento'] as const

/** As linhas que sobram com TODOS os cortes aplicados. */
export function aplicar(linhas: Pendencia[], f: Filtros, hoje = new Date()): Pendencia[] {
  return linhas.filter((p) => TODOS_OS_EIXOS.every((e) => PASSA[e](p, f, hoje)))
}

/**
 * Os filtros que valem NAQUELA vista — a única diferença entre as duas.
 *
 * No QUADRO a situação não é um filtro: ela é o EIXO das colunas. Cortar por ela dentro do
 * quadro esvazia por construção as colunas que não foram escolhidas — foi o que o dono viu,
 * com duas das três dizendo "Nenhuma aqui" enquanto o cartão logo acima contava CONCLUÍDAS
 * 15. Duas afirmações sobre o mesmo conjunto, na mesma tela.
 *
 * Os outros cinco cortes (prazo, usina, criticidade, parado há, busca) valem igual nas duas
 * vistas, e por isso lista e quadro continuam falando do mesmo conjunto: o que muda é só
 * como ele é arrumado. O eixo `situacao` fica escondido da barra no quadro, senão haveria um
 * controle ligado que não faz nada.
 */
export function filtrosDaVista(f: Filtros, vista: 'lista' | 'kanban'): Filtros {
  return vista === 'kanban' && f.situacao !== 'todas' ? { ...f, situacao: 'todas' } : f
}

/** As linhas que sobram ignorando UM eixo — a base honesta da contagem de cada opção. */
function semOEixo(linhas: Pendencia[], f: Filtros, alvo: Eixo | 'segmento', hoje: Date) {
  return linhas.filter((p) => TODOS_OS_EIXOS.every((e) => e === alvo || PASSA[e](p, f, hoje)))
}

/** Quantas linhas cada valor de um eixo devolveria, se fosse o escolhido. */
function contar<T extends string>(
  linhas: Pendencia[],
  f: Filtros,
  eixo: Eixo,
  valores: T[],
  hoje: Date,
): Map<T, number> {
  const base = semOEixo(linhas, f, eixo, hoje)
  const mapa = new Map<T, number>()
  for (const v of valores) {
    const simulado = { ...f, [eixo]: v } as Filtros
    mapa.set(v, base.filter((p) => PASSA[eixo](p, simulado, hoje)).length)
  }
  return mapa
}

/**
 * As opções de um eixo, já contadas e sem as que zerariam a lista.
 *
 * A escolhida fica SEMPRE, mesmo com zero: sem ela, o cliente que chegou por um link ficaria
 * com um filtro ligado que não aparece em lugar nenhum e não sabe desligar.
 */
function opcoes<T extends string>(
  linhas: Pendencia[],
  f: Filtros,
  eixo: Eixo,
  catalogo: { valor: T; rotulo: string }[],
  escolhido: T,
  hoje: Date,
  sempre: T,
): Opcao[] {
  const contagens = contar(
    linhas,
    f,
    eixo,
    catalogo.map((o) => o.valor),
    hoje,
  )
  return catalogo
    .filter((o) => {
      const n = contagens.get(o.valor)
      return o.valor === sempre || o.valor === escolhido || (n !== undefined && n > 0)
    })
    .map((o) => {
      const n = contagens.get(o.valor)
      return {
        valor: o.valor,
        rotulo: n === undefined ? o.rotulo : `${o.rotulo} (${inteiro(n)})`,
      }
    })
}

/** O catálogo de usinas presente NO DADO — nunca uma lista fixa. */
function catalogoDeUsinas(linhas: Pendencia[]) {
  const vistas = new Map<string, string>()
  for (const p of linhas) vistas.set(String(p.usina_id), p.usina)
  return [
    { valor: 'todas', rotulo: 'Todas as usinas' },
    ...[...vistas.entries()]
      .map(([valor, rotulo]) => ({ valor, rotulo }))
      .sort((a, b) => a.rotulo.localeCompare(b.rotulo, 'pt-BR')),
  ]
}

/**
 * O catálogo de criticidades presente no dado, na ORDEM DO SERVIDOR (`criticidade_rank`).
 * Ordenar pelo rótulo poria "Média" antes de "Alta" — e a escala é do meuPlano, não nossa.
 */
function catalogoDeCriticidades(linhas: Pendencia[]) {
  const vistas = new Map<string, { rotulo: string; rank: number }>()
  for (const p of linhas) {
    const codigo = p.criticidade === null ? 'sem' : p.criticidade.trim().toLowerCase()
    if (!codigo) continue
    const rotulo =
      p.criticidade === null ? 'Sem criticidade' : (rotuloDaCriticidade(p.criticidade) ?? codigo)
    vistas.set(codigo, { rotulo, rank: p.criticidade_rank })
  }
  return [
    { valor: 'todas', rotulo: 'Qualquer criticidade' },
    ...[...vistas.entries()]
      .sort((a, b) => a[1].rank - b[1].rank)
      .map(([valor, o]) => ({ valor, rotulo: o.rotulo })),
  ]
}

/* ------------------------------------------------------------------ a URL */

function aceito<T extends string>(bruto: string | null, aceitos: readonly T[], padrao: T): T {
  return bruto && (aceitos as readonly string[]).includes(bruto) ? (bruto as T) : padrao
}

/**
 * Os filtros que o endereço descreve. Valor que não existe cai no padrão, calado — é a
 * mesma regra do resto do portal, e protege de um link truncado pelo cliente de e-mail.
 */
export function lerFiltrosDaUrl(params: URLSearchParams): Filtros {
  const cruSituacao = params.get('situacao')
  // O apelido: `?situacao=vencidas` é o link que alguém manda dizendo "olha o atrasado".
  const apelidoVencidas = cruSituacao === 'vencidas'
  return {
    situacao: apelidoVencidas
      ? 'abertas'
      : aceito(
          cruSituacao,
          SITUACOES.map((o) => o.valor),
          FILTROS_PADRAO.situacao,
        ),
    prazo: apelidoVencidas
      ? 'vencidas'
      : aceito(
          params.get('prazo'),
          PRAZOS.map((o) => o.valor),
          FILTROS_PADRAO.prazo,
        ),
    usina: params.get('usina') ?? FILTROS_PADRAO.usina,
    criticidade: params.get('criticidade') ?? FILTROS_PADRAO.criticidade,
    parada: aceito(
      params.get('parada'),
      PARADAS.map((o) => o.valor),
      FILTROS_PADRAO.parada,
    ),
    busca: params.get('busca') ?? FILTROS_PADRAO.busca,
    segmento: aceito(params.get('cobranca'), ['cobradas', 'todas'] as const, FILTROS_PADRAO.segmento),
  }
}

/** Escreve os filtros na barra de endereço. O que está no padrão não é escrito. */
export function escreverFiltros(atuais: URLSearchParams, f: Filtros): URLSearchParams {
  const p = new URLSearchParams(atuais)
  const por = (chaveUrl: string, valor: string, padrao: string) => {
    if (valor === padrao) p.delete(chaveUrl)
    else p.set(chaveUrl, valor)
  }
  por('situacao', f.situacao, FILTROS_PADRAO.situacao)
  por('prazo', f.prazo, FILTROS_PADRAO.prazo)
  por('usina', f.usina, FILTROS_PADRAO.usina)
  por('criticidade', f.criticidade, FILTROS_PADRAO.criticidade)
  por('parada', f.parada, FILTROS_PADRAO.parada)
  por('busca', f.busca.trim(), FILTROS_PADRAO.busca)
  por('cobranca', f.segmento, FILTROS_PADRAO.segmento)
  return p
}

/** `true` quando nenhum corte está ligado — o estado em que a tarja não aparece. */
export function semCorte(f: Filtros): boolean {
  return (
    f.situacao === 'todas' &&
    f.prazo === FILTROS_PADRAO.prazo &&
    f.usina === FILTROS_PADRAO.usina &&
    f.criticidade === FILTROS_PADRAO.criticidade &&
    f.parada === FILTROS_PADRAO.parada &&
    f.busca.trim() === '' &&
    f.segmento === FILTROS_PADRAO.segmento
  )
}

/** Os nomes dos cortes ligados, para a tarja dizer POR QUE a lista encolheu. */
export function cortesLigados(f: Filtros, linhas: Pendencia[]): string[] {
  const nomes: string[] = []
  const rotulo = <T extends string>(cat: { valor: T; rotulo: string }[], v: T) =>
    cat.find((o) => o.valor === v)?.rotulo ?? v
  if (f.situacao !== 'todas') nomes.push(rotulo(SITUACOES, f.situacao))
  if (f.prazo !== 'todos') nomes.push(rotulo(PRAZOS, f.prazo))
  if (f.usina !== 'todas') {
    nomes.push(linhas.find((p) => String(p.usina_id) === f.usina)?.usina ?? 'Usina')
  }
  if (f.criticidade !== 'todas') {
    nomes.push(
      f.criticidade === 'sem'
        ? 'Sem criticidade'
        : (rotuloDaCriticidade(f.criticidade) ?? f.criticidade),
    )
  }
  if (f.parada !== 'todas') nomes.push(rotulo(PARADAS, f.parada))
  if (f.busca.trim()) nomes.push(`"${f.busca.trim()}"`)
  if (f.segmento === 'cobradas') nomes.push('Cobradas por mim')
  return nomes
}

/* ------------------------------------------------------------------ a barra */

function Corte({
  eixo,
  rotulo,
  opcoes: lista,
  valor,
  aoEscolher,
}: {
  eixo: Eixo
  rotulo: string
  opcoes: Opcao[]
  valor: string
  aoEscolher: (v: string) => void
}) {
  return (
    <div data-filtro={eixo} className="min-w-0">
      <span className="mb-1 block text-xs uppercase tracking-wide text-rotulo">{rotulo}</span>
      <Combobox opcoes={lista} valor={valor} onEscolher={aoEscolher} larguraMenu="w-64" />
    </div>
  )
}

/**
 * Os seis cortes. Cada um é `Combobox` (busca-enquanto-digita a partir de 7 opções) ou,
 * no caso da busca, um campo de texto — nunca uma fileira de botõezinhos.
 */
export function BarraDeFiltros({
  linhas,
  filtros,
  aoMudar,
  hoje = new Date(),
  ocultar = [],
}: {
  linhas: Pendencia[]
  filtros: Filtros
  aoMudar: (f: Filtros) => void
  hoje?: Date
  /** Eixos que não valem nesta vista — ver `filtrosDaVista`. */
  ocultar?: Eixo[]
}) {
  const trocar = (parcial: Partial<Filtros>) => aoMudar({ ...filtros, ...parcial })
  const escondido = (e: Eixo) => ocultar.includes(e)

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {escondido('situacao') ? null : (
      <Corte
        eixo="situacao"
        rotulo="Situação"
        opcoes={opcoes(linhas, filtros, 'situacao', SITUACOES, filtros.situacao, hoje, 'todas')}
        valor={filtros.situacao}
        aoEscolher={(v) => trocar({ situacao: v as Situacao })}
      />
      )}
      <Corte
        eixo="prazo"
        rotulo="Prazo"
        opcoes={opcoes(linhas, filtros, 'prazo', PRAZOS, filtros.prazo, hoje, 'todos')}
        valor={filtros.prazo}
        aoEscolher={(v) => trocar({ prazo: v as Prazo })}
      />
      <Corte
        eixo="usina"
        rotulo="Usina"
        opcoes={opcoes(
          linhas,
          filtros,
          'usina',
          catalogoDeUsinas(linhas),
          filtros.usina,
          hoje,
          'todas',
        )}
        valor={filtros.usina}
        aoEscolher={(v) => trocar({ usina: v })}
      />
      <Corte
        eixo="criticidade"
        rotulo="Criticidade"
        opcoes={opcoes(
          linhas,
          filtros,
          'criticidade',
          catalogoDeCriticidades(linhas),
          filtros.criticidade,
          hoje,
          'todas',
        )}
        valor={filtros.criticidade}
        aoEscolher={(v) => trocar({ criticidade: v })}
      />
      <Corte
        eixo="parada"
        rotulo="Parado há"
        opcoes={opcoes(linhas, filtros, 'parada', PARADAS, filtros.parada, hoje, 'todas')}
        valor={filtros.parada}
        aoEscolher={(v) => trocar({ parada: v as Parada })}
      />
      <div data-filtro="busca" className="min-w-0">
        <span className="mb-1 block text-xs uppercase tracking-wide text-rotulo">Buscar</span>
        <input
          className="campo"
          type="search"
          placeholder="Título, nº ou equipamento"
          aria-label="Buscar por título, número ou equipamento"
          value={filtros.busca}
          onChange={(e) => trocar({ busca: e.target.value })}
        />
      </div>
    </div>
  )
}
