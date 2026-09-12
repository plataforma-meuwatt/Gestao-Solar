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
import { LockupGS } from '@/components/marca'
import { useLeitura } from '@/lib/leitura'
import {
  GRUPOS,
  SECAO_PADRAO,
  VISAO_GERAL,
  casamentoExato,
  paraDaSecao,
  secoesDaCarteira,
  secoesDaFamilia,
} from '@/shell/menu'
import { SeletorUsina, type UsinasOut } from '@/shell/SeletorUsina'
import { AbrirProduto } from '@/shell/AbrirProduto'
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

/**
 * Uma entrada da navegação, nas três formas (barra, trilho e gaveta).
 *
 * **O item inativo é CLARO, não cinza.** Ele era `text-fraco` (#94A3B8), o mesmo tom que o
 * produto reserva para legenda e para texto de apoio — e com ele os ícones, que herdam a cor,
 * ficavam lavados a ponto de não se distinguirem uns dos outros a um metro da tela. No
 * meuWatt, de onde este portal herda a família, o menu é a única coisa sempre visível e por
 * isso é desenhado com o tom do CORPO: o que está apagado ali é o que não existe, não o que
 * simplesmente não está aberto.
 *
 * O ícone tem cor própria, um degrau abaixo do rótulo (`text-rotulo`), pelo motivo oposto:
 * cheio, ele competia com a palavra. No item aberto os dois viram âmbar juntos.
 */
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
        `group flex items-center gap-3 rounded-campo px-3 py-2.5 text-[calc(14.5px_+_var(--passo-tipo))] transition ${
          soIcone ? 'justify-center' : ''
        } ${
          isActive
            // O item aberto em ÂMBAR, como no meuWatt: o cinza-claro de antes era quase a
            // mesma coisa que o hover, e numa lista de dez itens o cliente não achava onde
            // estava sem ler todos.
            ? 'bg-ambar/14 font-semibold text-ambar-texto'
            : 'font-medium text-corpo hover:bg-superficie hover:text-forte'
        }`
      }
    >
      {({ isActive }: { isActive: boolean }) => (
        <>
          <Icone
            size={19}
            strokeWidth={isActive ? 2.2 : 1.9}
            aria-hidden
            className={`shrink-0 ${isActive ? '' : 'text-rotulo group-hover:text-corpo'}`}
          />
          {soIcone ? null : <span className="truncate">{rotulo}</span>}
        </>
      )}
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

      {/*
        A CARTEIRA vem antes, e em bloco próprio. Sob o cabeçalho "Esta usina" — onde estes
        dois itens estavam — a comparação parecia ser daquela usina, quando ela é justamente
        das outras seis. E o bloco não depende de haver usina escolhida: nenhum dos dois
        endereços carrega `:id`.
      */}
      <div className={soIcone ? 'mb-3' : 'mb-4'}>
        {soIcone ? null : (
          <p className="rotulo-secao px-3 pb-2 pt-1">Comparar usinas</p>
        )}
        <ul className="space-y-0.5">
          {secoesDaCarteira().map((s) => {
            const para = paraDaSecao(s, atual)
            if (para === null) return null
            return (
              <li key={s.fim}>
                <Link
                  para={para}
                  rotulo={s.rotulo}
                  Icone={s.icone}
                  fim={casamentoExato(s.fim)}
                  soIcone={soIcone}
                  aoNavegar={aoNavegar}
                />
              </li>
            )
          })}
        </ul>
      </div>

      {atual ? (
        <>
          {soIcone ? null : (
            <p className="rotulo-secao px-3 pb-2 pt-1">Esta usina</p>
          )}
          {GRUPOS.map((grupo, i) => {
            // Só as seções DA USINA: as de carteira já saíram no bloco acima.
            const itens = secoesDaFamilia(grupo.familia).filter((x) => !x.carteira)
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
                  <p className="rotulo-secao px-3 pb-1.5">{grupo.nome}</p>
                ) : null}

                <ul className="space-y-0.5">
                  {itens.map((s) => (
                    <li key={s.fim}>
                      <Link
                        // `paraDaSecao` é quem monta endereço de menu — a concatenação
                        // crua mandava item de carteira para `/usinas/4/comparar/energia`.
                        para={paraDaSecao(s, atual) ?? `/usinas/${atual}${s.fim}`}
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
        <p className="px-3 text-[calc(13px_+_var(--passo-tipo))] leading-relaxed text-fraco">
          Escolha uma usina no topo para ver as seções dela.
        </p>
      )}
    </>
  )

  return (
    /*
      O CASCO, na mesma construção do meuWatt (`mw-fe/src/App.tsx`): altura da JANELA, nada
      rola por fora, e quem rola é o `<main>`. Antes era `min-h-screen` com a página inteira
      rolando: a barra do topo e o trilho subiam junto com o conteúdo, e numa tabela de
      dezessete usinas o cliente perdia de vista o seletor de usina e o menu justamente
      enquanto procurava a linha. Aqui os dois ficam parados, como no produto vizinho.

      E o halo não é desenhado aqui. Ele é do `body` (`index.css`), com a receita do meuWatt.
      Havia um segundo, nesta div, somando-se ao primeiro num azul mais claro que nenhum dos
      dois pretendia.
    */
    <div className="flex h-dvh flex-col overflow-hidden bg-fundo">
      {/*
        A barra do topo atravessa a tela inteira, sem contêiner central — é o que o meuWatt
        faz, e é o que faz o trilho da esquerda encostar na borda. Altura fixa de 60px e
        `backdrop-blur`: o halo passa por baixo dela em vez de ser cortado por uma faixa opaca.
      */}
      <header className="relative z-20 h-[60px] shrink-0 border-b border-borda bg-topbar backdrop-blur-[18px]">
        <div className="flex h-full w-full items-center gap-3 px-4 lg:px-5">
          <button
            type="button"
            onClick={() => setGaveta(true)}
            aria-label="Abrir menu"
            className="rounded-campo p-1.5 text-fraco hover:text-corpo md:hidden"
          >
            <IconeMenu size={20} aria-hidden />
          </button>

          {/*
            A marca, e não só o nome escrito.

            O portal abre o meuWatt e o meuPlano em aba nova (`AbrirProduto`), e o cliente vai e
            volta entre os três durante a mesma reunião. Sem selo, as três abas eram três textos
            parecidos num fundo escuro igual — e o diretor lia "Gestão Solar" para descobrir onde
            estava. O selo é o que se reconhece antes de ler.

            O nome sai abaixo de 768 px: ali o topo tem de caber o botão do menu, o seletor de
            usina e os atalhos dos produtos. Quem nomeia o destino para um leitor de tela é o
            `aria-label` deste link, que não depende de largura.
          */}
          <NavLink
            to={usinaUnica ? `/usinas/${usinaUnica}${SECAO_PADRAO}` : '/'}
            aria-label={usinaUnica ? 'Gestão Solar — abrir a usina' : 'Gestão Solar — Visão geral'}
            className="shrink-0"
          >
            <LockupGS classeNome="hidden md:block" />
          </NavLink>

          {/* O separador que desgruda a marca do contexto: o que vem depois é a USINA, não mais o
              produto. Sem ele o nome do produto e o nome da usina lêem como uma frase só. */}
          <span aria-hidden className="hidden h-6 w-px shrink-0 bg-borda md:block" />

          <div className="min-w-0 flex-1">
            <SeletorUsina atual={atual} />
          </div>

          <AbrirProduto />

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

      <div className="relative z-10 flex min-h-0 flex-1">
        {/*
          O TRILHO COLADO NA BORDA. Ele estava dentro do `max-w-[1400px]` centrado: num
          monitor de 1920 px sobravam 260 px de fundo vazio à esquerda dele, e o menu
          flutuava no meio da tela em vez de ancorar a página. Agora encosta, como no
          meuWatt — e ganha fundo próprio (`bg-trilho`), que é o que separa a navegação do
          conteúdo sem precisar de uma linha grossa.

          A largura era a do meuWatt (238 px) e subiu para 252 quando a letra do portal
          cresceu. O rótulo mais longo da carteira encolheu junto (ver `menu.ts`): rótulo
          cortado no menu é o pior lugar para economizar pixel — é exatamente onde se lê
          para decidir para onde ir.
        */}
        <nav className="hidden w-16 shrink-0 overflow-y-auto border-r border-borda bg-trilho px-2 py-5 md:block lg:hidden">
          {navegacao(true)}
        </nav>

        <nav className="hidden w-[252px] shrink-0 overflow-y-auto border-r border-borda bg-trilho px-3 py-5 lg:block">
          {navegacao(false)}
        </nav>

        {/* Quem rola é aqui dentro — ver o comentário do casco. */}
        <main className="min-w-0 flex-1 overflow-y-auto">
          <LimiteDeErro chave={local.pathname}>
            <Outlet />
          </LimiteDeErro>
        </main>
      </div>

      <footer className="relative z-10 flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-borda bg-topbar px-5 py-2.5 text-xs text-fraco">
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
