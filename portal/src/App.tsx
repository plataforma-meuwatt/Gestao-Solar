/**
 * As rotas do portal do cliente.
 *
 * Cada tela é um chunk próprio (`lazyRetry`): o cliente que abre a Visão geral não baixa o
 * cronograma, e quem deixou a aba aberta durante um deploy recarrega uma vez em vez de cair
 * numa tela quebrada.
 *
 * Três guardas, nesta ordem:
 *
 * 1. **Sem sessão → `/entrar`.** Qualquer endereço, inclusive um link favoritado, volta para
 *    cá guardando o destino — depois de entrar, o cliente vai para onde queria ir.
 * 2. **Senha provisória bloqueia tudo.** Enquanto `usuario.trocar_senha` for verdadeiro, a
 *    única tela acessível é `/conta`. Deixar navegar com senha que o gestor conhece é o
 *    caminho para ela nunca ser trocada.
 * 3. **A raiz leva à Visão geral**, e um endereço desconhecido também — errar a URL não pode
 *    virar tela em branco.
 *
 * No boot, duas coisas acontecem em silêncio: o perfil é revalidado contra o servidor
 * (`hidratar` → `GET /auth/eu`) e o prazo da sessão é estendido quando está perto do fim
 * (`renovar`). As duas importam — sem a primeira, uma senha provisória marcada pelo gestor só
 * apareceria no próximo login; sem a segunda, o token de 30 dias venceria para quem abre o
 * portal uma vez por mês.
 */

import { Suspense, useEffect } from 'react'
import { Navigate, Route, BrowserRouter as Router, Routes, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'

import { CarregandoCartao } from '@/components/base'
import { lazyRetry } from '@/lib/lazyRetry'
import { queryClient } from '@/lib/consulta'
import { Layout } from '@/shell/Layout'
import { useAuth } from '@/store/auth'

const Entrar = lazyRetry(() => import('@/features/entrar/Pagina'))
const Conta = lazyRetry(() => import('@/features/conta/Pagina'))
const VisaoGeral = lazyRetry(() => import('@/features/visao-geral/Pagina'))
// A tela da usina responde "quanto gerei" — o rótulo no menu é "Energia", mas a pasta leva o
// nome do assunto (`usina`), que é o que a rota `/usinas/:id` diz.
const Usina = lazyRetry(() => import('@/features/usina/Pagina'))
const Paradas = lazyRetry(() => import('@/features/paradas/Pagina'))
const Cronograma = lazyRetry(() => import('@/features/cronograma/Pagina'))
const Ordens = lazyRetry(() => import('@/features/ordens/Pagina'))
const Ordem = lazyRetry(() => import('@/features/ordem/Pagina'))
const Pendencias = lazyRetry(() => import('@/features/pendencias/Pagina'))
const Relatorios = lazyRetry(() => import('@/features/relatorios/Pagina'))

/** O véu enquanto o chunk da tela chega — nunca uma tela branca. */
function Esperando() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
      <CarregandoCartao />
    </div>
  )
}

/** Exige sessão; guarda o destino para depois do login. */
function Protegido({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token)
  const precisaTrocar = useAuth((s) => s.usuario?.trocar_senha ?? false)
  const local = useLocation()

  if (!token) return <Navigate to="/entrar" replace state={{ de: local.pathname + local.search }} />
  if (precisaTrocar && local.pathname !== '/conta') return <Navigate to="/conta" replace />
  return <>{children}</>
}

export function App() {
  const renovar = useAuth((s) => s.renovar)
  const hidratar = useAuth((s) => s.hidratar)

  useEffect(() => {
    void hidratar()
    void renovar()
  }, [hidratar, renovar])

  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <Suspense fallback={<Esperando />}>
          <Routes>
            <Route path="/entrar" element={<Entrar />} />

            <Route
              element={
                <Protegido>
                  <Layout />
                </Protegido>
              }
            >
              <Route path="/" element={<VisaoGeral />} />
              <Route path="/conta" element={<Conta />} />
              <Route path="/usinas/:id" element={<Usina />} />
              <Route path="/usinas/:id/paradas" element={<Paradas />} />
              <Route path="/usinas/:id/cronograma" element={<Cronograma />} />
              <Route path="/usinas/:id/ordens" element={<Ordens />} />
              <Route path="/usinas/:id/ordens/:osId" element={<Ordem />} />
              <Route path="/usinas/:id/pendencias" element={<Pendencias />} />
              <Route path="/usinas/:id/pendencias/:cid" element={<Pendencias />} />
              <Route path="/usinas/:id/relatorios" element={<Relatorios />} />
            </Route>

            {/* Endereço desconhecido leva à carteira, não a uma tela em branco. */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </Router>
    </QueryClientProvider>
  )
}
