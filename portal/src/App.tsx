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
 * **O endereço nomeia a família** (`/usinas/:id/energia/...` e `/usinas/:id/manutencao/...`):
 * link colado em e-mail tem de dizer de que assunto se trata, e menu separado com endereço
 * misturado é separação de fachada. Os endereços antigos continuam existindo como
 * redirecionamento — favorito salvo pelo cliente não pode virar tela em branco, e a raiz da
 * usina (`/usinas/:id`) cai no Painel.
 *
 * No boot, duas coisas acontecem em silêncio: o perfil é revalidado contra o servidor
 * (`hidratar` → `GET /auth/eu`) e o prazo da sessão é estendido quando está perto do fim
 * (`renovar`). As duas importam — sem a primeira, uma senha provisória marcada pelo gestor só
 * apareceria no próximo login; sem a segunda, o token de 30 dias venceria para quem abre o
 * portal uma vez por mês.
 */

import { Suspense, useEffect } from 'react'
import {
  Navigate,
  Route,
  BrowserRouter as Router,
  Routes,
  useLocation,
  useParams,
} from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'

import { CarregandoCartao } from '@/components/base'
import { lazyRetry } from '@/lib/lazyRetry'
import { queryClient } from '@/lib/consulta'
import { Layout } from '@/shell/Layout'
import { SECAO_PADRAO } from '@/shell/menu'
import { useAuth } from '@/store/auth'

const Entrar = lazyRetry(() => import('@/features/entrar/Pagina'))
const Conta = lazyRetry(() => import('@/features/conta/Pagina'))
const VisaoGeral = lazyRetry(() => import('@/features/visao-geral/Pagina'))
// Geração de energia. A pasta leva o nome do ASSUNTO, que é o que a rota diz — e não o nome do
// lugar onde a tela morava, que envelhece na primeira reorganização de menu.
const Energia = lazyRetry(() => import('@/features/energia/Pagina'))
const Paradas = lazyRetry(() => import('@/features/paradas/Pagina'))
// Manutenção.
const Cronograma = lazyRetry(() => import('@/features/cronograma/Pagina'))
const Ordens = lazyRetry(() => import('@/features/ordens/Pagina'))
const Ordem = lazyRetry(() => import('@/features/ordem/Pagina'))
const Tarefa = lazyRetry(() => import('@/features/tarefa/Pagina'))
const Pendencias = lazyRetry(() => import('@/features/pendencias/Pagina'))
// Guarda as duas famílias, e por isso fica fora das duas.
const Relatorios = lazyRetry(() => import('@/features/relatorios/Pagina'))

/** O véu enquanto o chunk da tela chega — nunca uma tela branca. */
function Esperando() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
      <CarregandoCartao />
    </div>
  )
}

/**
 * Endereço antigo → endereço novo, com o resto do caminho e a query intactos.
 *
 * O favorito do cliente e o link que ele já colou num e-mail continuam funcionando: só o
 * assunto entra no meio (`/usinas/3/ordens/12` vira `/usinas/3/manutencao/ordens/12`). É
 * `replace` para o botão Voltar não cair no endereço velho e redirecionar de novo, prendendo
 * quem tenta voltar.
 *
 * O caminho é montado à mão em vez de `..` relativo: em rotas irmãs sob um layout sem caminho
 * próprio, o `..` do react-router sobe até a raiz — mandaria o cliente para a Visão geral.
 */
function Mudou({ familia }: { familia: 'energia' | 'manutencao' }) {
  const { id } = useParams<{ id: string }>()
  const local = useLocation()
  if (!id) return <Navigate to="/" replace />
  const resto = local.pathname.slice(`/usinas/${id}`.length)
  return <Navigate to={`/usinas/${id}/${familia}${resto}${local.search}`} replace />
}

/** A raiz da usina não é tela: é o Painel, a primeira pergunta ("gerei o esperado?"). */
function RaizDaUsina() {
  const { id } = useParams<{ id: string }>()
  if (!id) return <Navigate to="/" replace />
  return <Navigate to={`/usinas/${id}${SECAO_PADRAO}`} replace />
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

              {/* Geração de energia */}
              <Route path="/usinas/:id/energia" element={<Energia />} />
              <Route path="/usinas/:id/energia/paradas" element={<Paradas />} />

              {/* Manutenção */}
              <Route path="/usinas/:id/manutencao/cronograma" element={<Cronograma />} />
              <Route path="/usinas/:id/manutencao/ordens" element={<Ordens />} />
              <Route path="/usinas/:id/manutencao/ordens/:osId" element={<Ordem />} />
              <Route
                path="/usinas/:id/manutencao/ordens/:osId/tarefas/:taskId"
                element={<Tarefa />}
              />
              <Route path="/usinas/:id/manutencao/pendencias" element={<Pendencias />} />
              <Route path="/usinas/:id/manutencao/pendencias/:cid" element={<Pendencias />} />

              {/* Relatórios guarda as duas famílias, e por isso fica fora das duas. */}
              <Route path="/usinas/:id/relatorios" element={<Relatorios />} />

              {/* Endereços antigos: favorito do cliente não pode virar tela em branco. */}
              <Route path="/usinas/:id" element={<RaizDaUsina />} />
              <Route path="/usinas/:id/paradas" element={<Mudou familia="energia" />} />
              <Route path="/usinas/:id/cronograma" element={<Mudou familia="manutencao" />} />
              <Route path="/usinas/:id/ordens/*" element={<Mudou familia="manutencao" />} />
              <Route path="/usinas/:id/pendencias/*" element={<Mudou familia="manutencao" />} />
            </Route>

            {/* Endereço desconhecido leva à carteira, não a uma tela em branco. */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </Router>
    </QueryClientProvider>
  )
}
