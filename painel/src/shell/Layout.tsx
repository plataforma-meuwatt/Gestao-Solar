/**
 * A casca do painel: barra lateral, cabeçalho e a área da tela.
 *
 * Três travas de acesso, e as três importam:
 * - sem sessão, qualquer rota manda para a entrada;
 * - o menu mostra só as áreas que a conta abre, e a pessoa pousa na primeira delas —
 *   mandar todo mundo para Clientes deixaria quem não a tem olhando um 403 na cara;
 * - a casca revalida o acesso em `GET /eu` ao abrir, porque a sessão dura oito horas e
 *   o que a pessoa abre pode mudar no meio delas.
 *
 * **Nada disso é segurança, é conforto**: quem digitar a URL na mão toma 403 do servidor
 * de qualquer jeito, que confere a área a cada requisição.
 *
 * Um erro de renderização numa tela não pode derrubar o painel inteiro: o limite de erro
 * abaixo mostra um aviso recuperável e se limpa sozinho ao navegar.
 */

import {
  Building2,
  KeyRound,
  Link2,
  Repeat,
  ShieldCheck,
  LogOut,
  MessageCircle,
  Route,
  Stethoscope,
  Sun,
  Users,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import React from 'react'
import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'

import { meuAcesso, meusPapeis, trocarDePapel, trocarMinhaSenha } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { useAuth, type Escopo, type Perfil } from '@/store/auth'

type ItemMenu = {
  para: string
  rotulo: string
  icone: LucideIcon
  /** A área do catálogo do BFF (`services/areas_painel`) que abre esta tela. */
  area?: string
  /** Telas que não são área nenhuma: só administrador, e ponto. */
  soAdministrador?: boolean
  /** O bloco do menu a que este item pertence. O título aparece uma vez, no primeiro
   *  item visível do bloco — e não preso a um item fixo: com a régua por área, o item que
   *  abria o bloco pode não estar no menu desta pessoa, e o título sumiria junto,
   *  deixando "WhatsApp" colado em "Diagnóstico". */
  grupo?: string
}

/**
 * O menu, e a ausência que importa: **não há mais item de Conexões**.
 *
 * Ele existia no mesmo nível de "Clientes" e era lido como se fosse a conexão de alguém —
 * mas quem abria via sempre os mesmos dois cartões, independentemente do cliente
 * escolhido. A conexão é do usuário: a de cada cliente mora dentro da ficha dele, e a
 * credencial com que o painel monta o catálogo de usinas mora dentro de Usuários do
 * sistema, ao lado de quem administra.
 *
 * Sobra em "Sistema" só a sonda de rotas, que é diagnóstico do sistema e de mais nada.
 *
 * **`area` é a chave do catálogo do BFF, e os dois lados têm de casar.** Item com área que
 * o servidor não conhece é uma tela que ninguém abre; área do servidor sem item aqui é uma
 * tela concedida que não aparece no menu. Ao criar tela nova, acrescente nos dois.
 */
const MENU: ItemMenu[] = [
  { para: '/clientes', rotulo: 'Clientes', icone: Users, area: 'clientes' },
  { para: '/usinas', rotulo: 'Usinas', icone: Sun, area: 'usinas' },
  { para: '/diagnostico', rotulo: 'Diagnóstico', icone: Stethoscope, area: 'diagnostico' },
  // Quem opera o painel. Não é área concedível: conceder "mexer em quem administra" a
  // quem não administra é conceder tudo — ver `services/areas_painel`.
  {
    para: '/usuarios',
    rotulo: 'Usuários do sistema',
    icone: UsersRound,
    soAdministrador: true,
  },
  // Sonda das rotas dos produtos: diagnóstico do SISTEMA, não de cliente nenhum. O acesso
  // aos produtos saiu daqui e foi para dentro de Usuários do sistema — ver
  // `features/conexoes`.
  { para: '/rotas', rotulo: 'Rotas', icone: Route, area: 'rotas', grupo: 'Sistema' },
  // O número da empresa, não o de um cliente: quem abre esta tela configura por onde TODAS
  // as notificações saem. Por isso Sistema, e por isso área própria.
  {
    para: '/whatsapp',
    rotulo: 'WhatsApp',
    icone: MessageCircle,
    area: 'whatsapp',
    grupo: 'Sistema',
  },
  // Quem abre isto vê a lista INTEIRA de empresas — nenhuma delas sabe que as outras
  // existem. Por isso Sistema, e por isso área própria.
  {
    para: '/empresas',
    rotulo: 'Empresas de O&M',
    icone: Building2,
    area: 'empresas',
    grupo: 'Sistema',
  },
]

/**
 * O menu do OUTRO portão: o gerente da empresa de O&M.
 *
 * Lista separada, e não os mesmos itens escondidos por perfil. Com uma lista só, cada
 * tela nova da plataforma nasceria visível para o inquilino até alguém lembrar de
 * escondê-la — e o esquecimento seria descoberto pelo cliente, não por nós. Aqui o
 * padrão é o contrário: o que não está nesta lista não existe para ele.
 *
 * Não há áreas: elas são o catálogo do painel da plataforma. O que o gerente abre é o
 * que o portão `/api/empresa/*` serve, e quem confere é o servidor a cada requisição.
 */
const MENU_EMPRESA: ItemMenu[] = [
  { para: '/minha-empresa/usinas', rotulo: 'Usinas', icone: Sun },
  { para: '/minha-empresa/clientes', rotulo: 'Clientes', icone: Users },
  { para: '/minha-empresa/usuarios', rotulo: 'Usuários', icone: UsersRound },
  // As contas da empresa nos produtos. Fica por último porque é configuração, não o dia
  // a dia — mas é o primeiro lugar aonde ir quando as listas acima vierem vazias.
  { para: '/minha-empresa/conexoes', rotulo: 'Conexões', icone: Link2 },
  // Depois de Conexões de propósito: sem o token, não há o que casar aqui.
  { para: '/minha-empresa/vinculos', rotulo: 'Vínculos', icone: Building2 },
]

/** Onde pousa quem entra: a primeira tela que a conta abre, na ordem do menu. */
export function primeiraTela(
  pode: (a: string) => boolean,
  ehAdmin: boolean,
  ehEmpresa = false,
): string | null {
  if (ehEmpresa) return MENU_EMPRESA[0].para
  const item = MENU.find((i) =>
    i.soAdministrador ? ehAdmin : i.area !== undefined && pode(i.area),
  )
  return item?.para ?? null
}

/**
 * O seletor de papel, na ponta da faixa.
 *
 * Só aparece quando a pessoa tem mais de um papel — um botão que não faz nada é pior do
 * que botão nenhum, porque promete uma função que não existe para aquela conta.
 *
 * **Trocar para a plataforma pede a senha, e isso não é esquecimento do desenho.** Descer
 * é livre; subir não. Sem essa regra, uma sessão de aplicativo roubada viraria sessão de
 * administrador sem ninguém precisar saber nenhuma senha.
 *
 * O papel de CLIENTE aparece na lista mas não é clicável aqui: a sessão dele vale para o
 * aplicativo e para o portal, que são outras telas. Escondê-lo faria a pessoa procurar o
 * que existe; mostrá-lo sem dizer onde usar faria clicar e nada acontecer.
 */
function TrocarPapel() {
  const assumir = useAuth((s) => s.assumir)
  const [aberto, setAberto] = React.useState(false)
  const [pedindoSenha, setPedindoSenha] = React.useState<string | null>(null)
  const [senha, setSenha] = React.useState('')
  const [erro, setErro] = React.useState<string | null>(null)

  const { data } = useQuery({ queryKey: ['papeis'], queryFn: meusPapeis, retry: false })
  const papeis = data ?? []

  if (papeis.length < 2) return null

  async function trocar(apelido: string, comSenha?: string) {
    setErro(null)
    try {
      const nova = await trocarDePapel(apelido, comSenha)
      assumir({
        token: nova.token,
        nome: nova.nome,
        apelido: nova.apelido,
        perfil: nova.perfil as Perfil,
        escopo: nova.escopo === 'cliente' ? 'painel' : nova.escopo,
        empresa: nova.empresa,
      })
      // Recarrega a casca inteira: menu, áreas e consultas são de outro papel, e
      // reaproveitar o que está em memória mostraria a tela de um com o dado do outro.
      window.location.assign('/')
    } catch (e) {
      setErro(mensagemDeErro(e))
    }
  }

  return (
    <div className="ml-auto relative">
      <button
        onClick={() => setAberto((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-campo
                   border border-current/30 hover:bg-white/5"
      >
        <Repeat size={13} />
        Trocar papel
      </button>

      {aberto ? (
        <div
          className="absolute right-0 mt-2 w-80 rounded-card border border-borda bg-fundo
                     shadow-xl p-2 z-20 text-corpo"
        >
          {papeis.map((p) => {
            const ehCliente = p.escopo === 'cliente'
            return (
              <div key={p.apelido} className="px-2.5 py-2 rounded-campo">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm text-forte truncate">
                      {p.escopo === 'painel'
                        ? 'Plataforma'
                        : p.escopo === 'empresa'
                          ? `Empresa · ${p.empresa ?? 'sem nome'}`
                          : 'Dono de usina'}
                    </p>
                    <p className="text-[11px] text-fraco truncate">{p.apelido}</p>
                  </div>
                  {p.atual ? (
                    <span className="text-[11px] text-ok shrink-0">atual</span>
                  ) : ehCliente ? (
                    <span className="text-[11px] text-fraco shrink-0">no app</span>
                  ) : (
                    <button
                      className="btn-fantasma shrink-0"
                      onClick={() =>
                        p.exige_senha ? setPedindoSenha(p.apelido) : void trocar(p.apelido)
                      }
                    >
                      Entrar
                    </button>
                  )}
                </div>

                {pedindoSenha === p.apelido ? (
                  <div className="mt-2 flex gap-2">
                    <input
                      type="password"
                      className="campo h-9 text-sm"
                      placeholder="senha desta conta"
                      value={senha}
                      onChange={(e) => setSenha(e.target.value)}
                      autoFocus
                    />
                    <button
                      className="btn-secundario shrink-0"
                      onClick={() => void trocar(p.apelido, senha)}
                    >
                      Entrar
                    </button>
                  </div>
                ) : null}
              </div>
            )
          })}

          {erro ? <p className="text-xs text-parado px-2.5 py-1">{erro}</p> : null}
          <p className="text-[11px] text-fraco px-2.5 pt-2 border-t border-borda mt-1">
            Entrar como gestor da plataforma pede a senha daquela conta.
          </p>
        </div>
      ) : null}
    </div>
  )
}

/**
 * Trocar a própria senha — de qualquer papel.
 *
 * Não existia no painel: só o aplicativo do cliente tinha essa tela. Quem administra a
 * plataforma e quem gerencia uma empresa ficavam com a senha que alguém digitou e viu ao
 * criar a conta, e a única saída era pedir a outro administrador.
 *
 * A senha atual é pedida mesmo com a sessão aberta, pela mesma razão do aplicativo: um
 * computador destravado e esquecido não pode bastar para trancar o dono para fora.
 */
function TrocarSenha({ aoFechar }: { aoFechar: () => void }) {
  const [atual, setAtual] = React.useState('')
  const [nova, setNova] = React.useState('')
  const [erro, setErro] = React.useState<string | null>(null)
  const [pronto, setPronto] = React.useState(false)
  const [salvando, setSalvando] = React.useState(false)

  async function salvar() {
    setErro(null)
    setSalvando(true)
    try {
      await trocarMinhaSenha({ senha_atual: atual, senha_nova: nova })
      setPronto(true)
    } catch (e) {
      setErro(mensagemDeErro(e))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="fixed inset-0 z-30 bg-black/60 flex items-center justify-center p-4">
      <div className="cartao w-full max-w-md p-5">
        <p className="text-lg font-bold text-forte mb-4">Trocar minha senha</p>

        {pronto ? (
          <>
            <p className="text-sm text-ok">
              Senha trocada. Ela vale a partir da próxima vez que você entrar — esta sessão
              continua aberta.
            </p>
            <div className="flex justify-end mt-4">
              <button className="btn-primario" onClick={aoFechar}>
                Fechar
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="grid gap-3">
              <div>
                <label className="rotulo-campo" htmlFor="senha-atual">
                  Senha atual
                </label>
                <input
                  id="senha-atual"
                  type="password"
                  className="campo"
                  value={atual}
                  onChange={(e) => setAtual(e.target.value)}
                  autoFocus
                />
              </div>
              <div>
                <label className="rotulo-campo" htmlFor="senha-nova">
                  Senha nova
                </label>
                <input
                  id="senha-nova"
                  type="password"
                  className="campo"
                  value={nova}
                  onChange={(e) => setNova(e.target.value)}
                />
                <p className="text-xs text-fraco mt-1.5">Pelo menos 8 caracteres.</p>
              </div>
            </div>

            {erro ? <p className="text-sm text-parado mt-3">{erro}</p> : null}

            <div className="flex justify-end gap-2 mt-4">
              <button className="btn-secundario" onClick={aoFechar}>
                Cancelar
              </button>
              <button
                className="btn-primario"
                onClick={() => void salvar()}
                disabled={!atual || nova.length < 8 || salvando}
              >
                {salvando ? 'Trocando…' : 'Trocar senha'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/** Como cada perfil se chama na tela. */
const PAPEL: Record<Perfil, string> = {
  administrador: 'Administrador do sistema',
  atendimento: 'Atendimento',
  gestor_empresa: 'Gerente da empresa',
}

/**
 * A faixa que diz, o tempo todo, EM QUE PAPEL a sessão está.
 *
 * Não é enfeite e não é redundância com o menu: as duas sessões abrem o mesmo painel, no
 * mesmo navegador, com telas de nomes parecidos ("Usinas" existe dos dois lados). Sem uma
 * marca fixa, quem opera as duas contas cadastra o cliente na empresa errada e ninguém
 * descobre no mesmo dia — e é justamente quem administra a plataforma que troca de conta
 * várias vezes ao dia.
 *
 * Por isso ela é **larga, colorida e presa ao topo do conteúdo**, e não uma linha miúda na
 * lateral: o que precisa ser lido sem procurar tem de estar onde o olho já está.
 *
 * As duas cores não são decoração — elas são o sinal. Âmbar (a cor da marca) é a
 * plataforma, que enxerga tudo; verde é uma empresa, que enxerga só a carteira dela.
 */
function FaixaDePapel({
  escopo,
  empresa,
  perfil,
}: {
  escopo: Escopo
  empresa: string | null
  perfil: Perfil | null
}) {
  const daEmpresa = escopo === 'empresa'
  return (
    <div
      className={`sticky top-0 z-10 flex items-center gap-2.5 px-8 py-2.5 border-b backdrop-blur ${
        daEmpresa
          ? 'bg-ok/10 border-ok/30 text-ok'
          : 'bg-ambar/10 border-ambar/30 text-ambar-texto'
      }`}
    >
      {daEmpresa ? <Building2 size={15} /> : <ShieldCheck size={15} />}
      <p className="text-sm font-semibold truncate">
        {daEmpresa ? `Empresa · ${empresa ?? 'sem nome'}` : 'Plataforma · Gestão Solar'}
      </p>
      <span className="text-xs opacity-80 truncate">
        {daEmpresa
          ? 'você vê apenas a carteira desta empresa'
          : perfil === 'administrador'
            ? 'administrador do sistema — você vê todas as empresas'
            : 'atendimento — você vê todas as empresas'}
      </span>
      <TrocarPapel />
    </div>
  )
}

class LimiteDeErro extends React.Component<
  { chaveDeReset: string; children: React.ReactNode },
  { quebrou: boolean; mensagem: string }
> {
  state = { quebrou: false, mensagem: '' }

  static getDerivedStateFromError(erro: unknown) {
    return { quebrou: true, mensagem: String((erro as Error)?.message ?? erro) }
  }

  componentDidUpdate(anterior: { chaveDeReset: string }) {
    if (anterior.chaveDeReset !== this.props.chaveDeReset && this.state.quebrou) {
      this.setState({ quebrou: false, mensagem: '' })
    }
  }

  render() {
    if (this.state.quebrou) {
      return (
        <div className="cartao p-8 text-center max-w-lg">
          <p className="text-forte font-semibold">Algo deu errado ao abrir esta tela.</p>
          <p className="text-sm text-rotulo mt-2">
            Use o menu lateral para ir a outra tela. Nada foi perdido.
          </p>
          <details className="mt-4 text-left">
            <summary className="cursor-pointer text-xs text-fraco">Detalhes técnicos</summary>
            <pre className="mt-2 text-[11px] text-parado whitespace-pre-wrap break-words">
              {this.state.mensagem}
            </pre>
          </details>
        </div>
      )
    }
    return this.props.children
  }
}

export function Layout() {
  const { token, nome, perfil, empresa, escopo, sair, ehAdministrador, ehEmpresa, pode, atualizar } =
    useAuth()
  const [trocandoSenha, setTrocandoSenha] = React.useState(false)
  const local = useLocation()

  // A verdade do acesso é do servidor, e ela muda no meio da sessão. Falha de rede aqui
  // não derruba nada: o menu segue com a foto do login até a próxima resposta.
  const { data: eu } = useQuery({
    queryKey: ['eu'],
    queryFn: meuAcesso,
    enabled: Boolean(token) && !ehEmpresa(),
    retry: false,
  })
  React.useEffect(() => {
    if (eu) atualizar({ nome: eu.nome, perfil: eu.perfil, areas: eu.areas })
  }, [eu, atualizar])

  if (!token) return <Navigate to="/entrar" replace state={{ de: local.pathname }} />

  const itens = ehEmpresa()
    ? MENU_EMPRESA
    : MENU.filter((i) =>
        i.soAdministrador ? ehAdministrador() : i.area !== undefined && pode(i.area),
      )

  return (
    <div className="flex h-full">
      <nav className="w-56 shrink-0 border-r border-borda flex flex-col">
        <div className="px-5 py-5">
          <p className="text-lg font-bold text-forte leading-none">
            Gestão <span className="text-ambar">Solar</span>
          </p>
          {/* De qual empresa é esta sessão, sempre visível. Não é enfeite: quem opera
              duas contas cadastra o cliente na empresa errada e ninguém descobre no
              mesmo dia. */}
          <p className="text-[11px] text-fraco mt-1 truncate" title={empresa ?? undefined}>
            {ehEmpresa() ? (empresa ?? 'empresa') : 'painel'}
          </p>
        </div>

        <ul className="px-2.5 flex flex-col gap-0.5">
          {itens.map(({ para, rotulo, icone: Icone, grupo }, i) => (
            <li key={para}>
              {grupo && grupo !== itens[i - 1]?.grupo ? (
                <p className="px-3 pt-4 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-fraco/60">
                  {grupo}
                </p>
              ) : null}
              <NavLink
                to={para}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-3 py-2.5 rounded-campo text-sm transition-colors ${
                    isActive
                      ? 'bg-superficie-alta text-forte font-semibold'
                      : 'text-rotulo hover:text-forte hover:bg-superficie'
                  }`
                }
              >
                <Icone size={16} />
                {rotulo}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="mt-auto p-3 border-t border-borda">
          <p className="text-sm text-forte truncate px-1">{nome}</p>
          {/* O papel por extenso, e não o código com `capitalize`: `gestor_empresa` viraria
              "Gestor_empresa" na tela — código de banco lido por gente é o mesmo defeito
              que o CLAUDE.md nomeia. */}
          <p className="text-[11px] text-fraco px-1 mb-2">{perfil ? PAPEL[perfil] : ''}</p>
          <button onClick={() => setTrocandoSenha(true)} className="btn-fantasma w-full mb-1.5">
            <KeyRound size={13} />
            Trocar minha senha
          </button>
          <button onClick={sair} className="btn-fantasma w-full">
            <LogOut size={13} />
            Sair
          </button>
        </div>
      </nav>

      {trocandoSenha ? <TrocarSenha aoFechar={() => setTrocandoSenha(false)} /> : null}

      <main className="flex-1 overflow-y-auto">
        <FaixaDePapel escopo={escopo} empresa={empresa} perfil={perfil} />
        <div className="px-8 py-7">
          <LimiteDeErro chaveDeReset={local.pathname}>
            <Outlet />
          </LimiteDeErro>
        </div>
      </main>
    </div>
  )
}

/** Guarda das telas que só administrador abre — hoje, só Usuários do sistema. */
export function SoAdministrador({ children }: { children: React.ReactNode }) {
  const ehAdmin = useAuth((s) => s.perfil === 'administrador')
  if (!ehAdmin) return <SemAcesso />
  return <>{children}</>
}

/**
 * Guarda das telas do outro portão.
 *
 * Diferente de `SoArea`, que é conforto: aqui a sessão errada não é falta de permissão,
 * é o cliente HTTP errado. Uma sessão de painel nestas telas chamaria `/api/empresa/*`
 * com o token do painel e levaria 403 do servidor — a tela diz isso em vez de desenhar
 * cartões vazios e deixar a pessoa achando que a empresa não tem nada.
 */
export function SoEmpresa({ children }: { children: React.ReactNode }) {
  const ehEmpresa = useAuth((s) => s.escopo === 'empresa')
  if (!ehEmpresa) return <SemAcesso />
  return <>{children}</>
}

/** Guarda de uma tela concedível. A mesma área que o BFF exige na rota. */
export function SoArea({ area, children }: { area: string; children: React.ReactNode }) {
  const pode = useAuth((s) => s.perfil === 'administrador' || s.areas.includes(area))
  if (!pode) return <SemAcesso />
  return <>{children}</>
}

/**
 * O que a pessoa lê quando abre uma tela que não tem.
 *
 * Diz o que fazer em vez de só barrar: sem a frase final, quem digitou a URL e viu um
 * cartão vazio conclui que o painel quebrou, e abre chamado em vez de pedir o acesso.
 */
function SemAcesso() {
  return (
    <div className="cartao p-8 max-w-lg">
      <p className="text-forte font-semibold">Área restrita</p>
      <p className="text-sm text-rotulo mt-2">
        Seu acesso não inclui esta tela. Quem administra o painel concede em Usuários do
        sistema.
      </p>
    </div>
  )
}
