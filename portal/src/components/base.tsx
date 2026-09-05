/**
 * O vocabulário visual do portal. Toda tela é montada com estas peças, e só com elas.
 *
 * Princípios herdados de `docs/PROMPT_DESIGNER.md`, que valem aqui como valem no aplicativo:
 * cada tela responde UMA pergunta; número grande com contexto pequeno; cor só significa
 * estado (seis tons, nenhum a mais); nada de "chips" para escolher opção — lista suspensa
 * pesquisável (`Combobox`) ou controle segmentado (`Segmentado`); número sempre em pt-BR e
 * em fonte mono com `tabular-nums`, para não tremer quando o valor atualiza.
 *
 * O que muda do aplicativo para cá: o portal é lido num monitor, por alguém sentado. Há mais
 * largura, então tabela é uma peça de primeira classe (`Tabela`) — no celular ela viraria
 * cartão. O resto é o mesmo desenho, para quem usa os dois reconhecer o produto.
 *
 * ⛔ Nenhum hexadecimal aqui: as cores vêm das classes do `tailwind.config.js`, que são os
 * tokens de `app/src/theme/tokens.ts`. Cor literal no componente é cor que sai do lugar
 * quando a marca muda.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { numero } from '@/lib/format'
import { classesDoTom, tons, type Tom } from '@/lib/tons'

/* ------------------------------------------------------------------ número */

/**
 * Todo número da tela passa por aqui.
 *
 * `font-mono` com `tabular-nums` não é preciosismo: com fonte proporcional os dígitos têm
 * larguras diferentes, e um valor que se atualiza sozinho (potência agora, energia do dia)
 * faz a linha inteira dançar a cada leitura.
 */
export function Num({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono tabular-nums ${className}`}>{children}</span>
}

/* ------------------------------------------------------------------ página */

/**
 * O casco de uma tela: título grande, subtítulo, ações à direita.
 *
 * O cabeçalho é grande de propósito — quem abre o portal precisa saber, de relance, em que
 * usina está e o que esta tela responde.
 */
export function Pagina({
  titulo,
  subtitulo,
  acoes,
  children,
}: {
  titulo: string
  subtitulo?: ReactNode
  acoes?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-forte">{titulo}</h1>
          {subtitulo ? <div className="mt-1 text-sm text-fraco">{subtitulo}</div> : null}
        </div>
        {acoes ? <div className="flex flex-wrap items-center gap-2">{acoes}</div> : null}
      </header>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------ cartão */

export function Cartao({
  children,
  className = '',
  semPadding = false,
}: {
  children: ReactNode
  className?: string
  semPadding?: boolean
}) {
  return (
    <section
      className={`rounded-card border border-borda bg-superficie ${semPadding ? '' : 'p-5'} ${className}`}
    >
      {children}
    </section>
  )
}

export function CabecalhoCard({
  rotulo,
  direita,
  className = '',
}: {
  rotulo: ReactNode
  direita?: ReactNode
  className?: string
}) {
  return (
    <div className={`mb-3 flex items-center justify-between gap-3 ${className}`}>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-rotulo">{rotulo}</h2>
      {direita ? <div className="text-xs text-fraco">{direita}</div> : null}
    </div>
  )
}

/* ------------------------------------------------------------------ KPI */

/**
 * O número que responde a pergunta da tela.
 *
 * `valor` é string já formatada (os helpers de `lib/format` devolvem "—" para nulo): quem
 * decide como se escreve um número é o formatador, não o componente.
 */
export function Kpi({
  rotulo,
  valor,
  unidade,
  detalhe,
  tamanho = 'normal',
  tom,
}: {
  rotulo?: string
  valor: string
  unidade?: string
  detalhe?: ReactNode
  tamanho?: 'normal' | 'grande'
  tom?: Tom | string
}) {
  const cor = tom ? classesDoTom(tom).texto : 'text-forte'
  return (
    <div className="min-w-0">
      {rotulo ? <div className="text-xs uppercase tracking-wide text-rotulo">{rotulo}</div> : null}
      <div className="mt-1 flex items-baseline gap-1.5">
        <Num className={`${tamanho === 'grande' ? 'text-4xl' : 'text-2xl'} font-semibold ${cor}`}>
          {valor}
        </Num>
        {unidade ? <span className="text-sm text-fraco">{unidade}</span> : null}
      </div>
      {detalhe ? <div className="mt-1 text-xs text-fraco">{detalhe}</div> : null}
    </div>
  )
}

/* ------------------------------------------------------------------ selo */

/** Chip de estado: fundo a 10%, borda a 33%, texto na cor cheia — a receita da marca. */
export function Selo({ tom: valor, children }: { tom: Tom | string; children: ReactNode }) {
  const c = classesDoTom(valor)
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-chip border px-2 py-0.5 text-xs font-medium ${c.texto} ${c.borda} ${c.fundo}`}
    >
      {children}
    </span>
  )
}

/**
 * O selo da classificação — rótulo e tom vêm PRONTOS do servidor.
 *
 * Havia duas cópias deste par de funções no portal (`ordens/api.ts` e `ordem/Pagina.tsx`) e
 * a tela de Relatórios não usava nenhuma: a mesma OS saía "Serviços adicionais" na lista e
 * "SERVICOS_ADICIONAIS" no relatório. Traduzir é do BFF, onde já moram `situacao` e
 * `parecer`; aqui só se desenha. `classificacao_tom` pode não vir de um servidor antigo —
 * daí o `semDados`, que é a ausência de cor, nunca uma cor errada.
 */
export function SeloClasse({
  classificacao,
  tom,
}: {
  classificacao: string | null
  tom?: string
}) {
  return <Selo tom={tom ?? 'semDados'}>{classificacao ?? 'sem classificação'}</Selo>
}

/* ------------------------------------------------------------------ botões */

export function Botao({
  children,
  onClick,
  variante = 'primario',
  desabilitado = false,
  tipo = 'button',
  className = '',
}: {
  children: ReactNode
  onClick?: () => void
  variante?: 'primario' | 'secundario' | 'discreto'
  desabilitado?: boolean
  tipo?: 'button' | 'submit'
  className?: string
}) {
  const estilo =
    variante === 'primario'
      ? 'bg-ambar text-fundo hover:brightness-95'
      : variante === 'secundario'
        ? 'border border-borda-forte text-corpo hover:bg-superficie-alta'
        : 'text-fraco hover:text-corpo'
  return (
    <button
      type={tipo}
      onClick={onClick}
      disabled={desabilitado}
      className={`min-h-[38px] rounded-campo px-3.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${estilo} ${className}`}
    >
      {children}
    </button>
  )
}

/* ------------------------------------------------------------------ estados */

/** Esqueleto — nunca um spinner solto: a mancha do conteúdo que vai chegar. */
export function Esqueleto({ altura = 20, largura = '100%' }: { altura?: number; largura?: string }) {
  return (
    <div
      className="animate-pulse rounded-campo bg-superficie-alta"
      style={{ height: altura, width: largura }}
    />
  )
}

export function CarregandoCartao({ linhas = 3 }: { linhas?: number }) {
  return (
    <Cartao>
      <Esqueleto altura={14} largura="35%" />
      <div className="mt-4 space-y-3">
        {Array.from({ length: linhas }).map((_, i) => (
          <Esqueleto key={i} altura={12} largura={`${90 - i * 12}%`} />
        ))}
      </div>
    </Cartao>
  )
}

/**
 * Vazio ≠ erro ≠ sem dados.
 *
 * "Não há OS nesta usina" é uma afirmação; "não conseguimos ler" é outra. Misturar as duas
 * faz o cliente concluir que a equipe não trabalhou quando o que houve foi rede.
 *
 * `tom` existe porque nem todo vazio é neutro: "nenhuma parada no período" é uma BOA
 * notícia, e sair na mesma cor apagada de "não deu para ler" desperdiça a única coisa que
 * o cliente queria saber. Sem `tom` o cartão fica neutro, que é o certo para a maioria —
 * pintar de verde um "nada encontrado" que ninguém pediu seria mentir na outra direção.
 */
export function Vazio({
  titulo,
  descricao,
  acao,
  tom,
}: {
  titulo: string
  descricao?: string
  acao?: ReactNode
  tom?: string
}) {
  const c = tom ? classesDoTom(tom) : null
  return (
    <Cartao className={c ? `text-center ${c.borda}` : 'text-center'}>
      <p className={c ? `text-sm font-medium ${c.texto}` : 'text-sm font-medium text-corpo'}>{titulo}</p>
      {descricao ? <p className="mx-auto mt-1 max-w-md text-sm text-fraco">{descricao}</p> : null}
      {acao ? <div className="mt-4">{acao}</div> : null}
    </Cartao>
  )
}

export function Erro({ mensagem, aoTentar }: { mensagem: string; aoTentar?: () => void }) {
  return (
    <Cartao className="border-tom-parado/40">
      <p className="text-sm font-medium text-tom-parado">Não deu para carregar</p>
      <p className="mt-1 text-sm text-corpo">{mensagem}</p>
      {aoTentar ? (
        <div className="mt-4">
          <Botao variante="secundario" onClick={aoTentar}>
            Tentar de novo
          </Botao>
        </div>
      ) : null}
    </Cartao>
  )
}

/** Faixa de aviso — o que o SERVIDOR disse, não o que a tela achou. */
export function Aviso({ tom: valor = 'alerta', children }: { tom?: Tom | string; children: ReactNode }) {
  const c = classesDoTom(valor)
  return (
    <div className={`rounded-card border px-4 py-3 text-sm ${c.borda} ${c.fundo} ${c.texto}`}>
      {children}
    </div>
  )
}

/**
 * O selo de "está velho": aparece quando a tela mostra cache porque a rede falhou.
 *
 * Sem ele, dado de ontem se lê como dado de agora — e essa é a leitura mais cara que este
 * portal pode induzir.
 */
export function SeloOffline({ desde }: { desde: string }) {
  return (
    <Aviso tom="semDados">
      Sem conexão com o servidor — mostrando o que foi lido às <Num>{desde}</Num>.
    </Aviso>
  )
}

/**
 * A hora da última leitura boa — e, quando a rede caiu, a hora do que está na tela.
 *
 * Vive no rodapé e no canto dos cartões. É a diferença entre "o portal está mostrando o
 * agora" e "o portal está mostrando o que deu para ler"; sem ela, as duas situações têm
 * exatamente a mesma aparência.
 */
export function AtualizadoAs({ em, offlineDesde }: { em?: string; offlineDesde?: string }) {
  if (offlineDesde) {
    return (
      <span className="text-xs text-tom-semDados">
        sem conexão — dados de <Num>{offlineDesde}</Num>
      </span>
    )
  }
  if (!em) return null
  return (
    <span className="text-xs text-fraco">
      atualizado às <Num>{em}</Num>
    </span>
  )
}

/**
 * A faixa que chama o cliente para uma ação — parada em curso, prazo vencido, OS em
 * execução.
 *
 * O texto vem do SERVIDOR (`atencao.titulo` / `atencao.detalhe`): quem sabe o que merece
 * destaque é quem tem o dado inteiro, não a tela. Clicável quando há para onde ir; sem
 * `aoAbrir` continua sendo um aviso legítimo, e não um botão morto.
 */
export function FaixaAtencao({
  tom: valor = 'alerta',
  titulo,
  detalhe,
  aoAbrir,
}: {
  tom?: Tom | string
  titulo: string
  detalhe?: ReactNode
  aoAbrir?: () => void
}) {
  const c = classesDoTom(valor)
  const conteudo = (
    <>
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-chip ${c.fundo} border ${c.borda}`} />
      <span className="min-w-0">
        <span className={`block text-sm font-medium ${c.texto}`}>{titulo}</span>
        {detalhe ? <span className="mt-0.5 block text-sm text-corpo">{detalhe}</span> : null}
      </span>
      {aoAbrir ? (
        <span aria-hidden className="ml-auto self-center text-fraco">
          ›
        </span>
      ) : null}
    </>
  )
  const classe = `flex w-full items-start gap-3 rounded-card border px-4 py-3 text-left ${c.borda} ${c.fundo}`
  return aoAbrir ? (
    <button type="button" onClick={aoAbrir} className={`${classe} transition hover:brightness-125`}>
      {conteudo}
    </button>
  ) : (
    <div className={classe}>{conteudo}</div>
  )
}

/**
 * Linha de navegação com um valor à direita — "Pendências … 3 abertas ›".
 *
 * A seta só aparece quando há destino. Seta sem clique é a promessa que o portal não cumpre,
 * e o cliente fica tentando abrir o que não abre.
 */
export function LinhaNavegacao({
  titulo,
  detalhe,
  valor,
  tomValor,
  aoAbrir,
}: {
  titulo: string
  detalhe?: ReactNode
  valor?: ReactNode
  tomValor?: Tom | string
  aoAbrir?: () => void
}) {
  const cor = tomValor ? classesDoTom(tomValor).texto : 'text-corpo'
  const conteudo = (
    <>
      <span className="min-w-0">
        <span className="block truncate text-sm text-corpo">{titulo}</span>
        {detalhe ? <span className="block truncate text-xs text-fraco">{detalhe}</span> : null}
      </span>
      <span className="ml-auto flex items-center gap-2">
        {valor !== undefined && valor !== null ? (
          <Num className={`text-sm ${cor}`}>{valor}</Num>
        ) : null}
        {aoAbrir ? (
          <span aria-hidden className="text-fraco">
            ›
          </span>
        ) : null}
      </span>
    </>
  )
  const classe =
    'flex w-full items-center gap-3 border-b border-borda-fraca py-3 text-left last:border-0'
  return aoAbrir ? (
    <button type="button" onClick={aoAbrir} className={`${classe} hover:text-forte`}>
      {conteudo}
    </button>
  ) : (
    <div className={classe}>{conteudo}</div>
  )
}

/* ------------------------------------------------------------------ segmentado */

/** Controle segmentado: a escolha entre poucas opções fixas. Nunca uma fileira de chips. */
export function Segmentado<T extends string | number>({
  opcoes,
  valor,
  onEscolher,
}: {
  opcoes: { valor: T; rotulo: string }[]
  valor: T
  onEscolher: (v: T) => void
}) {
  return (
    <div className="inline-flex rounded-campo bg-afundado p-1">
      {opcoes.map((o) => (
        <button
          key={String(o.valor)}
          type="button"
          onClick={() => onEscolher(o.valor)}
          className={`min-h-[32px] rounded-[9px] px-3 text-sm transition ${
            o.valor === valor
              ? 'bg-superficie-destacada font-medium text-forte'
              : 'text-fraco hover:text-corpo'
          }`}
        >
          {o.rotulo}
        </button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ combobox */

/**
 * Uma opção da lista suspensa.
 *
 * `desabilitada` existe porque o portal precisa dizer o que **esta** usina não tem — "sem
 * estação solarimétrica", e a ausência derivada "sem estação não há irradiação, e sem
 * irradiação não se calcula PR". Sumir com a linha faria o cliente concluir que o portal
 * não oferece, quando o fato é sobre a usina dele.
 *
 * O tipo é uma união de propósito: **não dá para desabilitar sem escrever o motivo**, que
 * viaja no `detalhe`. Botão desabilitado sem frase é uma parede sem porta — e essa é a
 * espécie de defeito que o `tsc` pode pegar em vez de a revisão de diff deixar passar.
 */
export type Opcao =
  | { valor: string; rotulo: string; detalhe?: string; desabilitada?: false }
  | { valor: string; rotulo: string; detalhe: string; desabilitada: true }

/**
 * Monta a opção decidindo o estado: **o que desabilita é o próprio motivo**.
 *
 * Existe para a lista que se monta num `map`, em que cada item pode estar indisponível por
 * uma razão diferente — sem isto, o jeito curto de escrever é `desabilitada: boolean` com
 * `detalhe: string | undefined`, que é a mesma parede sem porta com outra roupa (e é o que
 * o tipo acima recusa, de propósito). Aqui não há como desabilitar sem dizer por quê: o
 * motivo é o argumento que desabilita.
 *
 * `motivo` nulo ou vazio devolve a opção normal, com o `detalhe` que ela já tinha.
 */
export function opcao(
  base: { valor: string; rotulo: string; detalhe?: string },
  motivo?: string | null,
): Opcao {
  return motivo ? { ...base, detalhe: motivo, desabilitada: true } : base
}

/**
 * Fechar por clique-fora e por ESC — o comportamento é o mesmo nas duas listas suspensas,
 * e duas cópias divergiriam no dia em que uma delas ganhasse um ajuste.
 */
function useFechaFora(aberto: boolean, setAberto: (v: boolean) => void) {
  const caixa = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!aberto) return
    const fora = (e: MouseEvent) => {
      if (caixa.current && !caixa.current.contains(e.target as Node)) setAberto(false)
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setAberto(false)
    }
    document.addEventListener('mousedown', fora)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', fora)
      document.removeEventListener('keydown', esc)
    }
  }, [aberto, setAberto])
  return caixa
}

/** Filtra por rótulo E por detalhe: o número de série é o que a pessoa tem na mão. */
function filtrar(opcoes: Opcao[], busca: string) {
  const t = busca.trim().toLowerCase()
  if (!t) return opcoes
  return opcoes.filter(
    (o) => o.rotulo.toLowerCase().includes(t) || (o.detalhe ?? '').toLowerCase().includes(t),
  )
}

/**
 * A linha da lista, nas duas peças.
 *
 * A opção desabilitada continua na lista, continua achável pela busca e continua legível —
 * o que ela perde é o clique. É um `<button disabled>` de verdade, e não um `onClick`
 * omitido: a garantia tem de ser estrutural, senão volta no primeiro refactor.
 */
function LinhaDeOpcao({
  opcao,
  marcada,
  comMarca,
  aoTocar,
}: {
  opcao: Opcao
  marcada: boolean
  comMarca: boolean
  aoTocar?: () => void
}) {
  const desabilitada = opcao.desabilitada === true
  const conteudo = (
    <>
      {comMarca ? (
        <span aria-hidden className="w-4 shrink-0 text-ambar-texto">
          {marcada ? '✓' : ''}
        </span>
      ) : null}
      <span className="min-w-0 flex-1">
        <span className="block truncate">{opcao.rotulo}</span>
        {opcao.detalhe ? (
          <span className="block truncate text-xs text-fraco">{opcao.detalhe}</span>
        ) : null}
      </span>
    </>
  )
  const base = 'flex w-full items-start gap-2 px-3 py-2 text-left text-sm'
  if (desabilitada) {
    return (
      <button
        type="button"
        disabled
        aria-disabled
        {...(comMarca ? { role: 'checkbox', 'aria-checked': false } : {})}
        className={`${base} cursor-not-allowed text-fraco`}
      >
        {conteudo}
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={aoTocar}
      {...(comMarca ? { role: 'checkbox', 'aria-checked': marcada } : {})}
      className={`${base} hover:bg-superficie-alta ${marcada ? 'text-ambar-texto' : 'text-corpo'}`}
    >
      {conteudo}
    </button>
  )
}

/** A caixa de busca só aparece quando a lista é grande o bastante para se procurar nela. */
const BUSCA_A_PARTIR_DE = 6

/**
 * Lista suspensa PESQUISÁVEL — a única forma de escolher entre muitas opções neste produto.
 *
 * A regra vem do meuPlano e vale aqui: chip não escala (cinco usinas cabem, vinte não), não
 * se busca por teclado e some no celular. Com busca, a mesma peça serve para 2 e para 200.
 */
export function Combobox({
  opcoes,
  valor,
  onEscolher,
  placeholder = 'Escolher…',
  className = '',
  larguraMenu = 'w-72',
}: {
  opcoes: Opcao[]
  valor: string | null
  onEscolher: (v: string) => void
  placeholder?: string
  className?: string
  larguraMenu?: string
}) {
  const [aberto, setAberto] = useState(false)
  const [busca, setBusca] = useState('')
  const caixa = useFechaFora(aberto, setAberto)

  const escolhida = opcoes.find((o) => o.valor === valor) ?? null
  const filtradas = useMemo(() => filtrar(opcoes, busca), [opcoes, busca])

  return (
    <div ref={caixa} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => {
          setAberto((v) => !v)
          setBusca('')
        }}
        className="flex min-h-[38px] w-full items-center justify-between gap-2 rounded-campo border border-borda bg-superficie px-3 text-sm text-corpo hover:bg-superficie-alta"
      >
        <span className="truncate">{escolhida ? escolhida.rotulo : placeholder}</span>
        <span aria-hidden className="text-fraco">
          ▾
        </span>
      </button>

      {aberto ? (
        <div
          className={`absolute z-30 mt-1 ${larguraMenu} max-w-[90vw] overflow-hidden rounded-card border border-borda-forte bg-painel shadow-xl`}
        >
          {opcoes.length > BUSCA_A_PARTIR_DE ? (
            <input
              autoFocus
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              placeholder="Buscar…"
              className="w-full border-b border-borda bg-transparent px-3 py-2 text-sm text-corpo outline-none placeholder:text-fraco"
            />
          ) : null}
          <ul className="max-h-72 overflow-auto py-1">
            {filtradas.length === 0 ? (
              <li className="px-3 py-2 text-sm text-fraco">Nada encontrado.</li>
            ) : (
              filtradas.map((o) => (
                <li key={o.valor}>
                  <LinhaDeOpcao
                    opcao={o}
                    marcada={o.valor === valor}
                    comMarca={false}
                    aoTocar={() => {
                      onEscolher(o.valor)
                      setAberto(false)
                    }}
                  />
                </li>
              ))
            )}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

/**
 * A MESMA lista suspensa pesquisável, com múltipla escolha — para quando a pergunta é
 * "quais destes?" e a resposta pode ter 1 ou 500 itens (os inversores de uma usina).
 *
 * Existe porque as duas saídas fáceis são proibidas aqui: fileira de caixinhas não escala e
 * é chip com outro nome (a tela do meuWatt faz assim; não se copia isso), e
 * `select multiple` não fala português em todo navegador nem se busca por teclado.
 *
 * **`valor === null` é "não mexi", e não é a mesma coisa que listar todos.** Na exportação
 * de dados isso decide um fato: com `series: null` o inversor comissionado no meio do
 * período entra sozinho no arquivo; com a lista explícita, não entra. Por isso o gatilho
 * escreve as duas de formas diferentes — "todos · 20 inversores" (a regra) contra "20 de 20
 * inversores" (a lista) — e desmarcar um item a partir de `null` MATERIALIZA a lista, que é
 * o que a pessoa acabou de dizer que queria.
 *
 * `[]` é o terceiro estado, "nenhum". Se ele é um pedido válido, quem decide é a tela — uma
 * peça do design system não sabe se a lista vazia é um filtro legítimo ou um pedido quebrado.
 */
export function ComboboxMulti({
  opcoes,
  valor,
  onEscolher,
  substantivo = 'itens',
  rotuloTodos = 'todos',
  notaTodos,
  className = '',
  larguraMenu = 'w-72',
}: {
  opcoes: Opcao[]
  /** `null` = "não mexi" (todos, inclusive o que aparecer depois). `[]` = nenhum. */
  valor: string[] | null
  onEscolher: (v: string[] | null) => void
  /** O plural do que se escolhe: "4 de 20 **inversores**". */
  substantivo?: string
  /** O gênero muda com o substantivo: "todas · 7 usinas". */
  rotuloTodos?: string
  /** Uma frase curta dizendo o que "todos" significa nesta tela. */
  notaTodos?: string
  className?: string
  larguraMenu?: string
}) {
  const [aberto, setAberto] = useState(false)
  const [busca, setBusca] = useState('')
  const caixa = useFechaFora(aberto, setAberto)

  // Só o que é escolhível entra na conta e em "todos": uma opção desabilitada é uma coisa
  // que esta usina não tem, e ela nunca pode entrar numa lista explícita enviada ao servidor.
  const disponiveis = useMemo(() => opcoes.filter((o) => o.desabilitada !== true), [opcoes])
  const total = disponiveis.length
  const marcados = useMemo(() => new Set(valor === null ? [] : valor), [valor])
  const estaMarcada = (v: string) => valor === null || marcados.has(v)

  // A ordem se fixa na ABERTURA do menu, não a cada clique: com os escolhidos subindo ao
  // topo em tempo real, o item seguinte pula para debaixo do cursor e a pessoa marca o
  // errado. Aqui a lista se acomoda quando ela fecha e abre de novo.
  const ordemDeAbertura = useRef<Set<string>>(new Set())
  const abrir = () => {
    ordemDeAbertura.current = new Set(valor === null ? disponiveis.map((o) => o.valor) : valor)
    setBusca('')
    setAberto(true)
  }

  const filtradas = useMemo(() => filtrar(opcoes, busca), [opcoes, busca])
  // `valor` está nas dependências de propósito, embora a ordem não dependa dele: quem segura
  // a ordem é a FOTO da abertura, e não o memo deixar de recalcular. Sem ele aqui, a
  // estabilidade viria de uma dependência esquecida — e a lista voltaria a dançar no dia em
  // que alguém (ou o corretor automático do lint) completasse a lista.
  const ordenadas = useMemo(() => {
    const peso = (o: Opcao) => (ordemDeAbertura.current.has(o.valor) ? 0 : 1)
    return [...filtradas].sort((a, b) => peso(a) - peso(b))
  }, [filtradas, aberto, valor])

  const alternar = (v: string) => {
    if (valor === null) {
      // Materializa: "todos menos este" é uma lista, e é exatamente o que ela acabou de pedir.
      onEscolher(disponiveis.filter((o) => o.valor !== v).map((o) => o.valor))
      return
    }
    onEscolher(marcados.has(v) ? valor.filter((x) => x !== v) : [...valor, v])
  }

  const gatilho =
    valor === null
      ? `${rotuloTodos} · ${total} ${substantivo}`
      : `${valor.length} de ${total} ${substantivo}`

  return (
    <div ref={caixa} className={`relative ${className}`}>
      <button
        type="button"
        aria-expanded={aberto}
        onClick={() => (aberto ? setAberto(false) : abrir())}
        className="flex min-h-[38px] w-full items-center justify-between gap-2 rounded-campo border border-borda bg-superficie px-3 text-sm text-corpo hover:bg-superficie-alta"
      >
        <span className="truncate">{gatilho}</span>
        <span aria-hidden className="text-fraco">
          ▾
        </span>
      </button>

      {aberto ? (
        <div
          className={`absolute z-30 mt-1 ${larguraMenu} max-w-[90vw] overflow-hidden rounded-card border border-borda-forte bg-painel shadow-xl`}
        >
          {opcoes.length > BUSCA_A_PARTIR_DE ? (
            <input
              autoFocus
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              placeholder="Buscar…"
              className="w-full border-b border-borda bg-transparent px-3 py-2 text-sm text-corpo outline-none placeholder:text-fraco"
            />
          ) : null}
          <ul className="max-h-72 overflow-auto py-1">
            {ordenadas.length === 0 ? (
              <li className="px-3 py-2 text-sm text-fraco">Nada encontrado.</li>
            ) : (
              ordenadas.map((o) => (
                <li key={o.valor}>
                  <LinhaDeOpcao
                    opcao={o}
                    marcada={estaMarcada(o.valor)}
                    comMarca
                    aoTocar={() => alternar(o.valor)}
                  />
                </li>
              ))
            )}
          </ul>
          <div className="border-t border-borda px-3 py-2">
            <div className="flex items-center gap-3">
              <button
                type="button"
                disabled={valor === null}
                onClick={() => onEscolher(null)}
                className="text-sm text-ambar-texto disabled:cursor-not-allowed disabled:text-fraco"
              >
                {rotuloTodos}
              </button>
              <button
                type="button"
                disabled={valor !== null && valor.length === 0}
                onClick={() => onEscolher([])}
                className="text-sm text-fraco hover:text-corpo disabled:cursor-not-allowed"
              >
                Limpar
              </button>
            </div>
            {notaTodos ? <p className="mt-1 text-xs text-fraco">{notaTodos}</p> : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------ período */

/**
 * O passo de período: ‹ rótulo ›.
 *
 * O botão de avançar fica desabilitado no presente — não há leitura do que ainda não
 * aconteceu, e deixar avançar devolveria uma tela vazia que se lê como falha do portal.
 */
export function PassoPeriodo({
  rotulo,
  aoVoltar,
  aoAvancar,
  podeAvancar,
}: {
  rotulo: string
  aoVoltar: () => void
  aoAvancar: () => void
  podeAvancar: boolean
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-campo border border-borda bg-superficie px-1">
      <button
        type="button"
        onClick={aoVoltar}
        aria-label="Período anterior"
        className="min-h-[36px] px-2 text-fraco hover:text-corpo"
      >
        ‹
      </button>
      <span className="min-w-[9rem] text-center text-sm text-corpo">{rotulo}</span>
      <button
        type="button"
        onClick={aoAvancar}
        disabled={!podeAvancar}
        aria-label="Próximo período"
        className="min-h-[36px] px-2 text-fraco hover:text-corpo disabled:opacity-30"
      >
        ›
      </button>
    </div>
  )
}

/* ------------------------------------------------------------------ tabela */

/**
 * Tabela — peça de primeira classe no portal (no celular ela vira cartão; aqui há largura).
 *
 * `aoClicar` na linha inteira: no desktop o alvo é o mouse, e uma linha inteira clicável é
 * mais fácil de acertar que um link no meio dela.
 */
export function Tabela<T>({
  colunas,
  linhas,
  chave,
  aoClicar,
  vazio,
}: {
  colunas: { titulo: string; alinhar?: 'esq' | 'dir'; celula: (item: T) => ReactNode }[]
  linhas: T[]
  chave: (item: T) => string | number
  aoClicar?: (item: T) => void
  vazio?: ReactNode
}) {
  if (linhas.length === 0 && vazio) return <>{vazio}</>
  return <TabelaRolavel colunas={colunas} linhas={linhas} chave={chave} aoClicar={aoClicar} />
}

/**
 * A tabela dentro do contêiner que rola — e que AVISA que rola.
 *
 * Separada só para poder ter estado: o contêiner tem `overflow-x-auto` e, quando as colunas
 * não cabem, o navegador corta a última no meio da palavra sem nenhum sinal. A tabela de
 * Comparar manutenção tem oito colunas e transborda até num monitor de 1500 px: o cabeçalho
 * saía "Cl…" e lia como defeito de renderização, não como "role para o lado".
 *
 * O aviso é medido, nunca presumido: `scrollWidth > clientWidth + 1` (o +1 absorve o
 * arredondamento de sub-pixel do zoom), refeito a cada `resize` e sempre que as linhas
 * mudam. Sem transbordo não há sombra nenhuma — decoração permanente ensinaria o olho a
 * ignorá-la justo quando ela significasse alguma coisa. A sombra some ao chegar ao fim da
 * rolagem, que é o que confirma ao leitor que não há mais coluna escondida.
 */
function TabelaRolavel<T>({
  colunas,
  linhas,
  chave,
  aoClicar,
}: {
  colunas: { titulo: string; alinhar?: 'esq' | 'dir'; celula: (item: T) => ReactNode }[]
  linhas: T[]
  chave: (item: T) => string | number
  aoClicar?: (item: T) => void
}) {
  const caixa = useRef<HTMLDivElement | null>(null)
  const [sombra, setSombra] = useState<{ esq: boolean; dir: boolean }>({
    esq: false,
    dir: false,
  })

  useEffect(() => {
    const el = caixa.current
    if (!el) return
    const medir = () => {
      const sobra = el.scrollWidth - el.clientWidth - el.scrollLeft
      setSombra({ esq: el.scrollLeft > 1, dir: sobra > 1 })
    }
    medir()
    el.addEventListener('scroll', medir, { passive: true })
    window.addEventListener('resize', medir)
    return () => {
      el.removeEventListener('scroll', medir)
      window.removeEventListener('resize', medir)
    }
  }, [colunas.length, linhas.length])

  return (
    <div className="relative">
      {sombra.esq ? (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 z-10 w-6 bg-gradient-to-r from-fundo to-transparent"
        />
      ) : null}
      {sombra.dir ? (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-0 z-10 w-6 bg-gradient-to-l from-fundo to-transparent"
        />
      ) : null}
      <div
        ref={caixa}
        className="overflow-x-auto"
        role={sombra.dir || sombra.esq ? 'region' : undefined}
        aria-label={
          sombra.dir || sombra.esq
            ? 'Tabela mais larga que a tela — role para o lado para ver todas as colunas'
            : undefined
        }
        tabIndex={sombra.dir || sombra.esq ? 0 : undefined}
      >
      {/*
        `min-w-max` em vez de largura fixa: com `min-w-[640px]` a tabela sempre cabia no
        cartão, e o navegador ESPREMIA as colunas para caber. A de Pendências, com sete,
        a 1440 px reduzia a última a um caractere — o cabeçalho "Última atividade" saía
        como um "A" partido e a coluna ficava ilegível SEM barra de rolagem, porque nada
        transbordava. Agora a tabela nunca fica menor que o conteúdo e o contêiner rola;
        `w-full` mantém o preenchimento quando sobra espaço. Quem pode ter texto longo é
        a célula, e ela se limita com `max-w` (ver a coluna "Pendência").
      */}
      <table className="w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="border-b border-borda">
            {colunas.map((c) => (
              <th
                key={c.titulo}
                className={`whitespace-nowrap px-3 py-2 text-xs font-medium uppercase tracking-wide text-rotulo ${
                  c.alinhar === 'dir' ? 'text-right' : 'text-left'
                }`}
              >
                {c.titulo}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {linhas.map((item) => (
            <tr
              key={chave(item)}
              onClick={aoClicar ? () => aoClicar(item) : undefined}
              className={`border-b border-borda-fraca last:border-0 ${
                aoClicar ? 'cursor-pointer hover:bg-superficie-alta' : ''
              }`}
            >
              {colunas.map((c) => (
                <td
                  key={c.titulo}
                  className={`px-3 py-3 align-middle text-corpo ${c.alinhar === 'dir' ? 'text-right' : ''}`}
                >
                  {c.celula(item)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ barra */

/** Progresso simples — tarefas feitas de uma OS, por exemplo. */
export function Barra({ pct, tom: valor = 'ok' }: { pct: number | null; tom?: Tom | string }) {
  // `bg-tom-X` cheio (sem opacidade) está na safelist do Tailwind — a classe existe sempre.
  const largura = pct === null ? 0 : Math.max(0, Math.min(100, pct))
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-barra bg-afundado">
      <div className={`h-full bg-tom-${tons(valor)}`} style={{ width: `${largura}%` }} />
    </div>
  )
}

/* ------------------------------------------------------------------ modal */

/**
 * Caixa modal — o detalhe curto que interrompe de propósito (as tarefas de um mês do
 * cronograma, por exemplo). Para o detalhe longo, use a `Gaveta`.
 *
 * Fecha no ESC e no clique fora, e **prende o foco** enquanto está aberta. O painel do
 * gestor não faz isso, e a consequência é real: com Tab o foco escapa para os links de trás,
 * e quem navega por teclado (ou por leitor de tela) fica "digitando" numa tela que não está
 * vendo. O fundo vem do token `painel`, não de um hexadecimal solto.
 */
export function Modal({
  titulo,
  aberto,
  aoFechar,
  children,
  largura = 'max-w-2xl',
}: {
  titulo: string
  aberto: boolean
  aoFechar: () => void
  children: ReactNode
  largura?: string
}) {
  const caixa = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!aberto) return
    const antes = document.activeElement as HTMLElement | null

    const foco = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        aoFechar()
        return
      }
      if (e.key !== 'Tab' || !caixa.current) return
      const alvos = caixa.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (alvos.length === 0) return
      const primeiro = alvos[0]
      const ultimo = alvos[alvos.length - 1]
      if (e.shiftKey && document.activeElement === primeiro) {
        e.preventDefault()
        ultimo.focus()
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault()
        primeiro.focus()
      }
    }

    document.addEventListener('keydown', foco)
    // O foco entra na caixa; ao fechar, volta para quem a abriu — senão a leitura recomeça
    // do topo da página a cada vez.
    caixa.current?.focus()
    return () => {
      document.removeEventListener('keydown', foco)
      antes?.focus?.()
    }
  }, [aberto, aoFechar])

  if (!aberto) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto p-4 sm:p-8">
      <button
        type="button"
        aria-label="Fechar"
        onClick={aoFechar}
        className="fixed inset-0 cursor-default bg-black/55"
      />
      <div
        ref={caixa}
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
        tabIndex={-1}
        className={`relative w-full ${largura} rounded-card border border-borda-forte bg-painel shadow-xl outline-none`}
      >
        <header className="flex items-center justify-between gap-3 border-b border-borda px-5 py-4">
          <h2 className="truncate text-base font-semibold text-forte">{titulo}</h2>
          <Botao variante="discreto" onClick={aoFechar}>
            Fechar
          </Botao>
        </header>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ gaveta */

/**
 * Gaveta lateral — o detalhe sem perder a lista de trás.
 *
 * É o desenho certo para a pendência: o cliente percorre a lista, abre uma, fecha e continua
 * de onde estava. Uma página inteira o faria perder o lugar a cada item.
 */
export function Gaveta({
  titulo,
  aberta,
  aoFechar,
  children,
}: {
  titulo: string
  aberta: boolean
  aoFechar: () => void
  children: ReactNode
}) {
  useEffect(() => {
    if (!aberta) return
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') aoFechar()
    }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [aberta, aoFechar])

  if (!aberta) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        aria-label="Fechar"
        onClick={aoFechar}
        className="flex-1 cursor-default bg-black/55"
      />
      <aside className="flex h-full w-full max-w-xl flex-col border-l border-borda-forte bg-painel">
        <header className="flex items-center justify-between gap-3 border-b border-borda px-5 py-4">
          <h2 className="truncate text-base font-semibold text-forte">{titulo}</h2>
          <Botao variante="discreto" onClick={aoFechar}>
            Fechar
          </Botao>
        </header>
        <div className="flex-1 overflow-auto px-5 py-4">{children}</div>
      </aside>
    </div>
  )
}

/* ------------------------------------------------------------------ 4 estados */

/**
 * Os quatro estados de uma leitura, desenhados sempre do mesmo jeito.
 *
 * Toda tela do portal desenha carregando, vazio, erro e offline — a regra não é
 * negociável, e repeti-la à mão em dez telas garante que uma delas esqueça o quarto. Aqui
 * a `Leitura` entra e sai a tela certa:
 *
 * - sem nada na mão → esqueleto;
 * - sem nada e com falha → erro com "Tentar de novo";
 * - com cache e rede caída → o conteúdo, com o selo de offline em cima (nunca esconder o
 *   dado velho: escondê-lo custaria a única informação que o cliente tem);
 * - com dado → o conteúdo.
 *
 * `vazio` é opcional porque "vazio" é decisão de cada tela: uma lista sem itens pode ser
 * "nenhuma parada no período" (boa notícia) ou "nada a mostrar" (aviso).
 */
export function Tela4Estados<T>({
  leitura,
  children,
  esqueleto,
}: {
  leitura: {
    dados: T | null
    carregando: boolean
    erro: string | null
    offlineDesde?: string
    recarregar: () => void
  }
  children: (dados: T) => ReactNode
  esqueleto?: ReactNode
}) {
  if (leitura.carregando) return <>{esqueleto ?? <CarregandoCartao />}</>
  if (leitura.dados === null) {
    return (
      <Erro
        mensagem={leitura.erro ?? 'O servidor não devolveu dados.'}
        aoTentar={leitura.recarregar}
      />
    )
  }
  return (
    <div className="space-y-4">
      {leitura.offlineDesde ? <SeloOffline desde={leitura.offlineDesde} /> : null}
      {children(leitura.dados)}
    </div>
  )
}

/* ------------------------------------------------------------------ gráficos */

export type PontoBarra = { rotulo: string; valor: number | null; esperado?: number | null }

/**
 * Barras de energia, com o esperado do projeto sobreposto.
 *
 * Duas decisões que vêm do aplicativo e não devem ser "simplificadas":
 *
 * **Ponto sem leitura NÃO vira barra rasteira.** Ele fica vazio. Barra no zero se lê como
 * "a usina não gerou", que é uma afirmação diferente de "não medimos" — e é o erro mais caro
 * que este portal pode cometer.
 *
 * **O esperado é uma marca, não uma segunda barra.** A pergunta é "cheguei lá?", e duas
 * barras lado a lado transformam isso em comparação de tamanhos.
 */
export function GraficoBarras({
  pontos,
  altura = 200,
  unidade = 'kWh',
}: {
  pontos: PontoBarra[]
  altura?: number
  unidade?: string
}) {
  const [marcado, setMarcado] = useState<number | null>(null)
  if (pontos.length === 0) return null

  const valores = pontos.flatMap((p) => [p.valor, p.esperado ?? null]).filter((v): v is number => typeof v === 'number')
  const maximo = valores.length ? Math.max(...valores) : 0
  const alturaDe = (v: number | null) => (maximo > 0 && typeof v === 'number' ? (v / maximo) * altura : 0)
  const lido = marcado !== null ? pontos[marcado] : null

  return (
    <div>
      <div className="mb-2 h-5 text-xs text-corpo">
        {lido ? (
          <>
            {lido.rotulo} · <Num>{numero(lido.valor, 1)}</Num> {unidade}
            {typeof lido.esperado === 'number' ? (
              <span className="text-fraco">
                {' '}
                · esperado <Num>{numero(lido.esperado, 1)}</Num>
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-fraco">passe o mouse numa barra para ver o valor</span>
        )}
      </div>

      <div className="flex items-end gap-1" style={{ height: altura }}>
        {pontos.map((p, i) => (
          <div
            key={`${p.rotulo}-${i}`}
            onMouseEnter={() => setMarcado(i)}
            onMouseLeave={() => setMarcado(null)}
            className="relative flex flex-1 cursor-default items-end justify-center"
            style={{ height: altura }}
          >
            {typeof p.valor === 'number' ? (
              <div
                className={`w-full rounded-t-[3px] ${marcado === i ? 'bg-ambar' : 'bg-ambar/70'}`}
                style={{ height: Math.max(2, alturaDe(p.valor)) }}
              />
            ) : null}
            {typeof p.esperado === 'number' && maximo > 0 ? (
              <div
                className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-fraco"
                style={{ bottom: alturaDe(p.esperado) }}
              />
            ) : null}
          </div>
        ))}
      </div>

      <div className="mt-2 flex gap-1">
        {pontos.map((p, i) => (
          <div key={`r-${p.rotulo}-${i}`} className="flex-1 text-center text-[10px] text-fraco">
            {i % Math.max(1, Math.ceil(pontos.length / 12)) === 0 ? p.rotulo : ''}
          </div>
        ))}
      </div>
    </div>
  )
}

export type PontoCurva = { hora: string; kw: number | null; poa?: number | null }

/**
 * A curva do dia: potência e, quando a usina tem estação, irradiação junto.
 *
 * O que a sobreposição mostra — e é o motivo de existir — é o DESCOLAMENTO: sol firme com
 * potência caindo é problema; as duas caindo juntas é nuvem. Uma curva sozinha não distingue
 * os dois casos. Cada grandeza tem a sua escala, em lados opostos, porque juntá-las na mesma
 * faria a irradiação sumir contra uma usina de 3 MW.
 */
export function GraficoLinha({ pontos, altura = 220 }: { pontos: PontoCurva[]; altura?: number }) {
  const [largura, setLargura] = useState(0)
  const caixa = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const medir = () => setLargura(caixa.current?.clientWidth ?? 0) // regra0: largura medida do layout, não dado da API
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, [])

  if (pontos.length < 2) return null

  const kws = pontos.map((p) => p.kw).filter((v): v is number => typeof v === 'number')
  const poas = pontos.map((p) => p.poa).filter((v): v is number => typeof v === 'number')
  const temPoa = poas.length > 0
  const kwMax = Math.max(...kws, 0.001)
  const poaMax = temPoa ? Math.max(...poas, 0.001) : 1

  const x = (i: number) => (i / (pontos.length - 1)) * largura
  const yKw = (v: number) => altura - (v / kwMax) * altura
  const yPoa = (v: number) => altura - (v / poaMax) * altura

  // Lacuna: a linha PARA e recomeça. Ligar os dois lados desenharia uma reta atravessando o
  // buraco, que é interpolação inventada — proibida pela REGRA 0.
  const caminho = (pega: (p: PontoCurva) => number | null | undefined, escala: (v: number) => number) => {
    let d = ''
    let aberto = false
    pontos.forEach((p, i) => {
      const v = pega(p)
      if (typeof v !== 'number') {
        aberto = false
        return
      }
      d += `${aberto ? 'L' : 'M'}${x(i).toFixed(1)} ${escala(v).toFixed(1)} ` // regra0: coordenada de SVG, não número de tela
      aberto = true
    })
    return d.trim()
  }

  const marcas = [0, 0.25, 0.5, 0.75, 1]

  return (
    <div>
      <div className="flex gap-2">
        <div className="flex w-12 flex-col justify-between text-right" style={{ height: altura }}>
          {[...marcas].reverse().map((f) => (
            <Num key={`kw-${f}`} className="text-[10px] text-fraco">
              {numero(kwMax * f, kwMax >= 100 ? 0 : 1)}
            </Num>
          ))}
        </div>

        <div ref={caixa} className="flex-1" style={{ height: altura }}>
          {largura > 0 ? (
            <svg width={largura} height={altura}>
              {marcas.map((f) => (
                <line
                  key={`g-${f}`}
                  x1={0}
                  y1={altura - f * altura}
                  x2={largura}
                  y2={altura - f * altura}
                  className="stroke-borda-fraca"
                  strokeWidth={0.5}
                />
              ))}
              {temPoa ? (
                <path
                  d={caminho((p) => p.poa, yPoa)}
                  className="stroke-fraco"
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  fill="none"
                />
              ) : null}
              <path d={caminho((p) => p.kw, yKw)} className="stroke-ambar" strokeWidth={2} fill="none" />
            </svg>
          ) : null}
        </div>

        {temPoa ? (
          <div className="flex w-12 flex-col justify-between" style={{ height: altura }}>
            {[...marcas].reverse().map((f) => (
              <Num key={`poa-${f}`} className="text-[10px] text-fraco">
                {numero(poaMax * f, 0)}
              </Num>
            ))}
          </div>
        ) : null}
      </div>

      <div className="mt-2 flex justify-between text-[10px] text-fraco">
        <span>{pontos[0].hora}</span>
        <span>{pontos[pontos.length - 1].hora}</span>
      </div>

      <div className="mt-1 flex gap-4 text-[11px] text-fraco">
        <span>— potência (kW, esquerda)</span>
        {temPoa ? <span>- - irradiação POA (W/m², direita)</span> : null}
      </div>
    </div>
  )
}

export type MesDoHistorico = {
  /** `YYYY-MM`. O rótulo curto é derivado aqui; a chave crua serve de identidade. */
  mes: string
  rotulo: string
  medido: number | null
  esperado: number | null
  anoAnterior: number | null
}

/**
 * O histórico longo: 24 meses de energia medida, contra o esperado do projeto e contra o
 * mesmo mês do ano passado.
 *
 * As três séries respondem perguntas diferentes e por isso têm formas diferentes: a barra é
 * o que a usina fez; o traço cheio é o que o projeto prometia (`esperado`); o traço claro é
 * o ano anterior — a régua que o diretor usa quando não há PVsyst cadastrado.
 *
 * Mês sem leitura fica VAZIO. Uma barra no chão diria que a usina não gerou naquele mês, e
 * essa afirmação vale dinheiro numa reunião de contrato.
 */
export function GraficoHistorico({
  meses,
  altura = 220,
  unidade = 'kWh',
}: {
  meses: MesDoHistorico[]
  altura?: number
  unidade?: string
}) {
  const [marcado, setMarcado] = useState<number | null>(null)
  if (meses.length === 0) return null

  const valores = meses
    .flatMap((m) => [m.medido, m.esperado, m.anoAnterior])
    .filter((v): v is number => typeof v === 'number')
  const maximo = valores.length ? Math.max(...valores) : 0
  const alturaDe = (v: number | null) =>
    maximo > 0 && typeof v === 'number' ? (v / maximo) * altura : 0
  const lido = marcado !== null ? meses[marcado] : null
  const passoRotulo = Math.max(1, Math.ceil(meses.length / 12))

  return (
    <div>
      <div className="mb-2 min-h-[1.25rem] text-xs text-corpo">
        {lido ? (
          <>
            {lido.rotulo} · <Num>{numero(lido.medido, 1)}</Num> {unidade}
            {typeof lido.esperado === 'number' ? (
              <span className="text-fraco">
                {' '}
                · esperado <Num>{numero(lido.esperado, 1)}</Num>
              </span>
            ) : null}
            {typeof lido.anoAnterior === 'number' ? (
              <span className="text-fraco">
                {' '}
                · ano anterior <Num>{numero(lido.anoAnterior, 1)}</Num>
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-fraco">passe o mouse num mês para ver os valores</span>
        )}
      </div>

      <div className="flex items-end gap-1" style={{ height: altura }}>
        {meses.map((m, i) => (
          <div
            key={m.mes}
            onMouseEnter={() => setMarcado(i)}
            onMouseLeave={() => setMarcado(null)}
            className="relative flex flex-1 cursor-default items-end justify-center"
            style={{ height: altura }}
          >
            {typeof m.medido === 'number' ? (
              <div
                className={`w-full rounded-t-[3px] ${marcado === i ? 'bg-ambar' : 'bg-ambar/70'}`}
                style={{ height: Math.max(2, alturaDe(m.medido)) }}
              />
            ) : null}
            {typeof m.anoAnterior === 'number' && maximo > 0 ? (
              <div
                className="pointer-events-none absolute left-0 right-0 border-t border-dotted border-fraco/60"
                style={{ bottom: alturaDe(m.anoAnterior) }}
              />
            ) : null}
            {typeof m.esperado === 'number' && maximo > 0 ? (
              <div
                className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-forte/60"
                style={{ bottom: alturaDe(m.esperado) }}
              />
            ) : null}
          </div>
        ))}
      </div>

      <div className="mt-2 flex gap-1">
        {meses.map((m, i) => (
          <div key={`r-${m.mes}`} className="flex-1 text-center text-[10px] text-fraco">
            {i % passoRotulo === 0 ? m.rotulo : ''}
          </div>
        ))}
      </div>

      <div className="mt-1 flex flex-wrap gap-4 text-[11px] text-fraco">
        <span>▮ medido</span>
        <span>- - esperado do projeto</span>
        <span>· · · mesmo mês do ano anterior</span>
      </div>
    </div>
  )
}

export { tons }
