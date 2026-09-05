/**
 * O casco do portal: barra superior com a usina, navegação lateral, rodapé com a hora.
 *
 * A decisão que organiza tudo: **a usina é o contexto, não uma tela.** O cliente escolhe a
 * usina uma vez, no alto, e as seções (Painel, Paradas, Cronograma, Ordens, Pendências,
 * Relatórios) são recortes daquela usina. Trocar de usina mantém a MESMA seção — quem estava
 * comparando o cronograma de uma continua no cronograma da outra, que é exatamente o que um
 * diretor com cinco usinas faz.
 *
 * A Visão geral é a exceção: é a carteira inteira, e por isso vive fora do contexto de usina.
 * Quem tem uma usina só não a vê — carteira de um item é a própria usina, e um item de menu
 * que leva de volta ao mesmo lugar é ruído.
 *
 * Navegação lateral e não abas: são seis seções e um monitor largo — abas no topo espremeriam
 * os rótulos e obrigariam a abreviar. À esquerda elas cabem por extenso, que é o que um
 * portal corporativo pede.
 *
 * **Duas famílias, não uma fileira.** Geração de energia e Manutenção respondem perguntas
 * diferentes e têm donos diferentes na empresa do cliente, então cada uma tem cabeçalho
 * próprio (a lista e os grupos vivem em `shell/menu.ts`). A separação tem de sobreviver às
 * TRÊS larguras — era no trilho de ícones, justamente onde não cabe rótulo, que ela sumia:
 * lá cada família ganha um ícone-cabeçalho com o nome no `title` e um separador.
 *
 * **Três larguras, uma navegação só**: a partir de 1024 px a barra mostra ícone e rótulo;
 * entre 768 px e 1024 px vira um trilho de ícones (com o nome no `title`, nunca ícone
 * anônimo); abaixo de 768 px ela sai da tela e o botão "Menu" abre a gaveta. O painel do
 * gestor é desktop-only porque é ferramenta de escritório; este portal é aberto por um
 * diretor que pode estar num notebook pequeno ou num tablet, em reunião.
 */

import { Component, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Menu as IconeMenu, UserRound, X, type LucideIcon } from 'lucide-react'
import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'

import { AtualizadoAs, Cartao, Erro } from '@/components/base'
import { useLeitura } from '@/lib/leitura'
import { GRUPOS, SECAO_PADRAO, VISAO_GERAL, casamentoExato, secoesDaFamilia } from '@/shell/menu'
import { SeletorUsina, type UsinasOut } from '@/shell/SeletorUsina'
import { useAuth } from '@/store/auth'
import { useUsina } from '@/store/usina'

/**
 * Limite de erro por rota.
 *
 * Um erro de renderização numa tela não pode apagar o portal inteiro: sem isto o React
 * desmonta a árvore toda e o cliente fica com a página branca — sem menu, sem como voltar e
 * sem saber o que aconteceu. Aqui a falha fica dentro do `main`, com a navegação de pé, e o
 * estado se limpa sozinho quando o caminho muda (a `chave`).
 */
class LimiteDeErro extends Component<
  { chave: string; children: ReactNode },
  { mensagem: string | null }
> {
  state: { mensagem: string | null } = { mensagem: null }

  static getDerivedStateFromError(erro: unknown) {
    return { mensagem: erro instanceof Error ? erro.message : 'Erro inesperado na tela.' }
  }

  componentDidUpdate(anterior: { chave: string }) {
    if (anterior.chave !== this.props.chave && this.state.mensagem) {
      this.setState({ mensagem: null })
    }
  }

  render() {
    if (this.state.mensagem) {
      return (
        <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
          <Erro mensagem={this.state.mensagem} aoTentar={() => window.location.reload()} />
        </div>
      )
    }
    return <>{this.props.children}</>
  }
}

/** Uma entrada da navegação, nas três formas (barra, trilho e gaveta). */
function Link({
  para,
  rotulo,
  Icone,
  fim,
  soIcone,
  aoNavegar,
}: {
  para: string
  rotulo: string
  Icone: LucideIcon
  fim?: boolean
  soIcone?: boolean
  aoNavegar?: () => void
}) {
  return (
    <NavLink
      to={para}
      end={fim}
      onClick={aoNavegar}
      title={rotulo}
      aria-label={rotulo}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-campo px-3 py-2 text-sm transition ${
          soIcone ? 'justify-center' : ''
        } ${isActive ? 'bg-superficie-alta font-medium text-forte' : 'text-fraco hover:text-corpo'}`
      }
    >
      <Icone size={18} aria-hidden />
      {soIcone ? null : <span className="truncate">{rotulo}</span>}
    </NavLink>
  )
}

export function Layout() {
  const navigate = useNavigate()
  const local = useLocation()
  const { id } = useParams<{ id: string }>()
  const usuario = useAuth((s) => s.usuario)
  const sair = useAuth((s) => s.sair)
  const usinaEscolhida = useUsina((s) => s.id)
  const escolher = useUsina((s) => s.escolher)
  const carregar = useUsina((s) => s.carregar)
  const [gaveta, setGaveta] = useState(false)

  const { dados, atualizadoEm, offlineDesde } = useLeitura<UsinasOut>('plants')
  const usinas = useMemo(() => dados?.usinas ?? [], [dados])

  // A lembrança é por conta: trocar de usuário no mesmo computador não herda a usina do outro.
  useEffect(() => {
    carregar(usuario?.id ?? null)
  }, [carregar, usuario?.id])

  // A URL manda: quando ela traz uma usina, é ela que passa a ser a lembrada.
  const daUrl = id ? Number(id) : null
  useEffect(() => {
    if (daUrl && daUrl !== usinaEscolhida) escolher(daUrl, usuario?.id ?? null)
  }, [daUrl, usinaEscolhida, escolher, usuario?.id])

  // Uma usina só: a carteira É a usina, e o portal abre direto nela. Com duas ou mais, a
  // Visão geral responde a primeira pergunta ("como está tudo?") e continua sendo a raiz.
  const usinaUnica = usinas.length === 1 ? usinas[0].id : null
  useEffect(() => {
    if (usinaUnica && local.pathname === '/') {
      navigate(`/usinas/${usinaUnica}${SECAO_PADRAO}`, { replace: true })
    }
  }, [usinaUnica, local.pathname, navigate])

  // Fecha a gaveta ao navegar: no celular ela cobre a tela, e deixá-la aberta esconderia
  // justamente o que o cliente acabou de pedir.
  useEffect(() => {
    setGaveta(false)
  }, [local.pathname])

  const atual = daUrl ?? usinaEscolhida ?? usinaUnica

  const navegacao = (soIcone: boolean, aoNavegar?: () => void) => (
    <>
      {usinaUnica ? null : (
        <div className={soIcone ? 'mb-3' : 'mb-4'}>
          <Link
            para={VISAO_GERAL.para}
            rotulo={VISAO_GERAL.rotulo}
            Icone={VISAO_GERAL.icone}
            fim
            soIcone={soIcone}
            aoNavegar={aoNavegar}
          />
        </div>
      )}

      {atual ? (
        <>
          {soIcone ? null : (
            <p className="px-3 pb-2 text-[11px] uppercase tracking-wide text-rotulo">Esta usina</p>
          )}
          {GRUPOS.map((grupo, i) => {
            const itens = secoesDaFamilia(grupo.familia)
            if (itens.length === 0) return null
            const CabecalhoIcone = grupo.icone
            return (
              <div
                key={grupo.familia}
                className={i === 0 ? '' : 'mt-3 border-t border-borda-fraca pt-3'}
              >
                {soIcone ? (
                  CabecalhoIcone ? (
                    <div
                      className="flex justify-center pb-1 text-rotulo"
                      title={grupo.nome ?? undefined}
                    >
                      <CabecalhoIcone size={14} aria-hidden />
                      <span className="sr-only">{grupo.nome}</span>
                    </div>
                  ) : null
                ) : grupo.nome ? (
                  <p className="px-3 pb-1 text-[11px] uppercase tracking-wide text-rotulo">
                    {grupo.nome}
                  </p>
                ) : null}

                <ul className="space-y-0.5">
                  {itens.map((s) => (
                    <li key={s.fim}>
                      <Link
                        para={`/usinas/${atual}${s.fim}`}
                        rotulo={s.rotulo}
                        Icone={s.icone}
                        fim={casamentoExato(s.fim)}
                        soIcone={soIcone}
                        aoNavegar={aoNavegar}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </>
      ) : soIcone ? null : (
        <p className="px-3 text-sm text-fraco">Escolha uma usina para ver as seções dela.</p>
      )}
    </>
  )

  return (
    <div className="flex min-h-screen flex-col bg-fundo">
      {/* halo radial azul no topo — a assinatura visual herdada do rebrand da marca */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-x-0 top-0 h-72"
        style={{
          background:
            'radial-gradient(60% 100% at 50% 0%, rgba(64,110,255,0.20) 0%, rgba(64,110,255,0) 100%)',
        }}
      />

      <header className="relative z-20 border-b border-borda bg-fundo/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-[1400px] items-center gap-3 px-4 py-3 sm:px-6">
          <button
            type="button"
            onClick={() => setGaveta(true)}
            aria-label="Abrir menu"
            className="rounded-campo p-1.5 text-fraco hover:text-corpo md:hidden"
          >
            <IconeMenu size={20} aria-hidden />
          </button>

          <NavLink
            to={usinaUnica ? `/usinas/${usinaUnica}${SECAO_PADRAO}` : '/'}
            className="shrink-0"
          >
            <span className="text-base font-semibold tracking-tight text-forte">Gestão Solar</span>
          </NavLink>

          <div className="ml-1 min-w-0 flex-1">
            <SeletorUsina atual={atual} />
          </div>

          <NavLink
            to="/conta"
            title="Minha conta"
            className={({ isActive }) =>
              `flex items-center gap-2 text-sm ${
                isActive ? 'text-ambar-texto' : 'text-fraco hover:text-corpo'
              }`
            }
          >
            <UserRound size={18} aria-hidden />
            <span className="hidden max-w-[12rem] truncate sm:inline">
              {usuario?.nome ?? 'Minha conta'}
            </span>
          </NavLink>
        </div>
      </header>

      <div className="relative z-10 mx-auto flex w-full max-w-[1400px] flex-1">
        {/* trilho de ícones: entre 768 px e 1024 px o rótulo não cabe */}
        <nav className="hidden w-16 shrink-0 border-r border-borda px-2 py-6 md:block lg:hidden">
          {navegacao(true)}
        </nav>

        <nav className="hidden w-56 shrink-0 border-r border-borda py-6 pl-6 pr-3 lg:block">
          {navegacao(false)}
        </nav>

        <main className="min-w-0 flex-1">
          <LimiteDeErro chave={local.pathname}>
            <Outlet />
          </LimiteDeErro>
        </main>
      </div>

      <footer className="relative z-10 flex flex-wrap items-center justify-between gap-2 border-t border-borda px-6 py-3 text-xs text-fraco">
        <span className="truncate">
          {usuario?.nome ?? ''}
          {usuario?.empresa ? ` · ${usuario.empresa}` : ''}
        </span>
        <span className="flex items-center gap-3">
          <AtualizadoAs em={atualizadoEm} offlineDesde={offlineDesde} />
          <button type="button" onClick={sair} className="transition hover:text-corpo">
            Sair
          </button>
        </span>
      </footer>

      {/* Gaveta do celular — a MESMA lista de `menu.ts`, sem duplicar item nenhum. */}
      {gaveta ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <button
            type="button"
            aria-label="Fechar menu"
            onClick={() => setGaveta(false)}
            className="absolute inset-0 cursor-default bg-black/55"
          />
          <aside className="relative flex h-full w-64 flex-col border-r border-borda-forte bg-painel p-4">
            <div className="mb-4 flex items-center justify-between">
              <span className="text-sm font-semibold text-forte">Menu</span>
              <button
                type="button"
                onClick={() => setGaveta(false)}
                aria-label="Fechar menu"
                className="text-fraco hover:text-corpo"
              >
                <X size={18} aria-hidden />
              </button>
            </div>
            {navegacao(false, () => setGaveta(false))}
            <div className="mt-auto pt-4">
              <Cartao className="p-3 text-xs text-fraco">
                {usuario?.nome ?? ''}
                {usuario?.empresa ? ` · ${usuario.empresa}` : ''}
              </Cartao>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  )
}
