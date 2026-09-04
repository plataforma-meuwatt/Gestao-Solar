/**
 * O casco do portal: barra superior com a usina, navegação lateral, rodapé com a hora.
 *
 * A decisão que organiza tudo: **a usina é o contexto, não uma tela.** O cliente escolhe a
 * usina uma vez, no alto, e as seções (Energia, Paradas, Cronograma, Ordens, Pendências,
 * Relatórios) são recortes daquela usina. Trocar de usina mantém a MESMA seção — quem estava
 * comparando o cronograma de uma continua no cronograma da outra, que é exatamente o que um
 * diretor com cinco usinas faz.
 *
 * A Visão geral é a exceção: é a carteira inteira, e por isso vive fora do contexto de usina.
 *
 * Navegação lateral e não abas: são seis seções e um monitor largo — abas no topo espremeriam
 * os rótulos e obrigariam a abreviar. À esquerda elas cabem por extenso, que é o que um
 * portal corporativo pede.
 */

import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useEffect, useMemo } from 'react'

import { Combobox, Num } from '@/components/base'
import { useLeitura } from '@/lib/leitura'
import { useAuth } from '@/store/auth'
import { useUsina } from '@/store/usina'

type UsinaDaLista = { id: number; nome: string; cidade: string | null; uf: string | null }
type UsinasOut = { usinas: UsinaDaLista[] }

/** As seções de uma usina, na ordem das perguntas que o cliente faz. */
const SECOES = [
  { fim: '', rotulo: 'Energia' },
  { fim: '/paradas', rotulo: 'Paradas' },
  { fim: '/cronograma', rotulo: 'Cronograma' },
  { fim: '/ordens', rotulo: 'Ordens de serviço' },
  { fim: '/pendencias', rotulo: 'Pendências' },
  { fim: '/relatorios', rotulo: 'Relatórios' },
]

export function Layout() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const usuario = useAuth((s) => s.usuario)
  const sair = useAuth((s) => s.sair)
  const usinaEscolhida = useUsina((s) => s.id)
  const escolher = useUsina((s) => s.escolher)
  const carregar = useUsina((s) => s.carregar)

  const { dados, atualizadoEm } = useLeitura<UsinasOut>('plants')
  const usinas = dados?.usinas ?? []

  // A lembrança é por conta: trocar de usuário no mesmo computador não herda a usina do outro.
  useEffect(() => {
    carregar(usuario?.id ?? null)
  }, [carregar, usuario?.id])

  // A URL manda: quando ela traz uma usina, é ela que passa a ser a lembrada.
  const daUrl = id ? Number(id) : null
  useEffect(() => {
    if (daUrl && daUrl !== usinaEscolhida) escolher(daUrl, usuario?.id ?? null)
  }, [daUrl, usinaEscolhida, escolher, usuario?.id])

  const opcoes = useMemo(
    () =>
      usinas.map((u) => ({
        valor: String(u.id),
        rotulo: u.nome,
        detalhe: [u.cidade, u.uf].filter(Boolean).join(', ') || undefined,
      })),
    [usinas],
  )

  const atual = daUrl ?? usinaEscolhida
  const secaoAtual = useMemo(() => {
    const caminho = window.location.pathname
    const achada = [...SECOES]
      .sort((a, b) => b.fim.length - a.fim.length)
      .find((s) => s.fim && caminho.endsWith(s.fim))
    return achada?.fim ?? ''
  }, [])

  function trocarUsina(valor: string) {
    const novo = Number(valor)
    escolher(novo, usuario?.id ?? null)
    // Mantém a seção: é o que faz o seletor ser um contexto, e não um atalho para a home.
    navigate(`/usinas/${novo}${secaoAtual}`)
  }

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
        <div className="mx-auto flex w-full max-w-[1400px] items-center gap-4 px-6 py-3">
          <NavLink to="/" className="flex items-center gap-2">
            <span className="text-base font-semibold tracking-tight text-forte">Gestão Solar</span>
          </NavLink>

          {opcoes.length > 0 ? (
            <div className="ml-2 min-w-0 flex-1">
              <Combobox
                opcoes={opcoes}
                valor={atual ? String(atual) : null}
                onEscolher={trocarUsina}
                placeholder="Escolher usina…"
                className="max-w-xs"
              />
            </div>
          ) : (
            <div className="flex-1" />
          )}

          <NavLink
            to="/conta"
            className={({ isActive }) =>
              `text-sm ${isActive ? 'text-ambar-texto' : 'text-fraco hover:text-corpo'}`
            }
          >
            {usuario?.nome ?? 'Minha conta'}
          </NavLink>
          <button
            type="button"
            onClick={sair}
            className="text-sm text-fraco transition hover:text-corpo"
          >
            Sair
          </button>
        </div>
      </header>

      <div className="relative z-10 mx-auto flex w-full max-w-[1400px] flex-1 gap-0 px-0">
        <nav className="hidden w-56 shrink-0 border-r border-borda py-6 pl-6 pr-3 lg:block">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `mb-4 block rounded-campo px-3 py-2 text-sm ${
                isActive ? 'bg-superficie-alta font-medium text-forte' : 'text-fraco hover:text-corpo'
              }`
            }
          >
            Visão geral
          </NavLink>

          {atual ? (
            <>
              <p className="px-3 pb-2 text-[11px] uppercase tracking-wide text-rotulo">Esta usina</p>
              <ul className="space-y-0.5">
                {SECOES.map((s) => (
                  <li key={s.fim || 'energia'}>
                    <NavLink
                      to={`/usinas/${atual}${s.fim}`}
                      end={s.fim === ''}
                      className={({ isActive }) =>
                        `block rounded-campo px-3 py-2 text-sm ${
                          isActive
                            ? 'bg-superficie-alta font-medium text-forte'
                            : 'text-fraco hover:text-corpo'
                        }`
                      }
                    >
                      {s.rotulo}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="px-3 text-sm text-fraco">Escolha uma usina para ver as seções dela.</p>
          )}
        </nav>

        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>

      <footer className="relative z-10 border-t border-borda px-6 py-3 text-center text-xs text-fraco">
        {atualizadoEm ? (
          <>
            atualizado às <Num>{atualizadoEm}</Num>
          </>
        ) : (
          'Gestão Solar'
        )}
      </footer>
    </div>
  )
}
