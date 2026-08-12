/**
 * A casca do painel: barra lateral, cabeçalho e a área da tela.
 *
 * Duas travas de acesso, e as duas importam:
 * - sem sessão, qualquer rota manda para a entrada;
 * - itens de administrador nem aparecem para atendimento. Isso é conforto, não segurança
 *   — quem digitar a URL na mão toma 403 do servidor de qualquer jeito.
 *
 * Um erro de renderização numa tela não pode derrubar o painel inteiro: o limite de erro
 * abaixo mostra um aviso recuperável e se limpa sozinho ao navegar.
 */

import {
  Cable,
  LogOut,
  Stethoscope,
  Sun,
  Users,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'
import React from 'react'
import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/store/auth'

type ItemMenu = {
  para: string
  rotulo: string
  icone: LucideIcon
  soAdministrador?: boolean
}

const MENU: ItemMenu[] = [
  { para: '/clientes', rotulo: 'Clientes', icone: Users },
  { para: '/usinas', rotulo: 'Usinas', icone: Sun },
  { para: '/diagnostico', rotulo: 'Diagnóstico', icone: Stethoscope },
  { para: '/conexoes', rotulo: 'Conexões', icone: Cable, soAdministrador: true },
  { para: '/equipe', rotulo: 'Equipe', icone: UsersRound, soAdministrador: true },
]

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
  const { token, nome, perfil, sair, ehAdministrador } = useAuth()
  const local = useLocation()

  if (!token) return <Navigate to="/entrar" replace state={{ de: local.pathname }} />

  const itens = MENU.filter((i) => !i.soAdministrador || ehAdministrador())

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
          {itens.map(({ para, rotulo, icone: Icone }) => (
            <li key={para}>
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

/** Guarda das telas que só administrador abre. */
export function SoAdministrador({ children }: { children: React.ReactNode }) {
  const ehAdmin = useAuth((s) => s.perfil === 'administrador')
  if (!ehAdmin) {
    return (
      <div className="cartao p-8 max-w-lg">
        <p className="text-forte font-semibold">Área restrita</p>
        <p className="text-sm text-rotulo mt-2">
          Esta tela é de administradores. Peça a quem administra o painel, ou use as telas de
          Clientes e Diagnóstico.
        </p>
      </div>
    )
  }
  return <>{children}</>
}
