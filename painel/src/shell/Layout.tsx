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

import { meuAcesso } from '@/features/api'
import { useAuth } from '@/store/auth'

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
]

/** Onde pousa quem entra: a primeira tela que a conta abre, na ordem do menu. */
export function primeiraTela(pode: (a: string) => boolean, ehAdmin: boolean): string | null {
  const item = MENU.find((i) =>
    i.soAdministrador ? ehAdmin : i.area !== undefined && pode(i.area),
  )
  return item?.para ?? null
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
  const { token, nome, perfil, sair, ehAdministrador, pode, atualizar } = useAuth()
  const local = useLocation()

  // A verdade do acesso é do servidor, e ela muda no meio da sessão. Falha de rede aqui
  // não derruba nada: o menu segue com a foto do login até a próxima resposta.
  const { data: eu } = useQuery({
    queryKey: ['eu'],
    queryFn: meuAcesso,
    enabled: Boolean(token),
    retry: false,
  })
  React.useEffect(() => {
    if (eu) atualizar({ nome: eu.nome, perfil: eu.perfil, areas: eu.areas })
  }, [eu, atualizar])

  if (!token) return <Navigate to="/entrar" replace state={{ de: local.pathname }} />

  const itens = MENU.filter((i) =>
    i.soAdministrador ? ehAdministrador() : i.area !== undefined && pode(i.area),
  )

  return (
    <div className="flex h-full">
      <nav className="w-56 shrink-0 border-r border-borda flex flex-col">
        <div className="px-5 py-5">
          <p className="text-lg font-bold text-forte leading-none">
            Gestão <span className="text-ambar">Solar</span>
          </p>
          <p className="text-[11px] text-fraco mt-1">painel</p>
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
          <p className="text-[11px] text-fraco px-1 mb-2 capitalize">{perfil}</p>
          <button onClick={sair} className="btn-fantasma w-full">
            <LogOut size={13} />
            Sair
          </button>
        </div>
      </nav>

      <main className="flex-1 overflow-y-auto px-8 py-7">
        <LimiteDeErro chaveDeReset={local.pathname}>
          <Outlet />
        </LimiteDeErro>
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
