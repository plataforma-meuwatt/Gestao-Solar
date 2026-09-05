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
// A exportação de dados brutos. Fica na Geração — e não em Relatórios, que é `geral` por
// guardar as DUAS famílias — porque o contrato de exportação do meuWatt não tem uma linha de
// manutenção. Ver `shell/menu.ts` e `docs/TELAS.md` (P.10).
const BaixarDados = lazyRetry(() => import('@/features/dados/Pagina'))
// Manutenção.
const Cronograma = lazyRetry(() => import('@/features/cronograma/Pagina'))
const Ordens = lazyRetry(() => import('@/features/ordens/Pagina'))
const Ordem = lazyRetry(() => import('@/features/ordem/Pagina'))
const Tarefa = lazyRetry(() => import('@/features/tarefa/Pagina'))
const Pendencias = lazyRetry(() => import('@/features/pendencias/Pagina'))
// Comparativos de CARTEIRA: sem `:id`, porque a pergunta que eles respondem ("qual gera
// mais", "qual está mais atrasada") não cabe dentro de uma usina. São dois, e não um com
// abas, porque cada um pertence a uma família — quem cobra kWh não abre ordem de serviço.
const CompararEnergia = lazyRetry(() => import('@/features/comparar/Energia'))
const CompararManutencao = lazyRetry(() => import('@/features/comparar/Manutencao'))
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

/**
 * `/usinas/3/comparar/energia` → `/comparar/energia`, com a query intacta.
 *
 * O comparativo é da CARTEIRA e o endereço dele não tem usina — mas a navegação lateral
 * (`shell/Layout.tsx`) ainda monta TODA entrada de menu como `/usinas/${atual}${fim}`, sem
 * consultar `paraDaSecao`. Enquanto ela não o fizer, é este redirecionamento que mantém os
 * dois itens funcionando nas três larguras em vez de levarem a uma tela em branco.
 *
 * Ele fica de pé mesmo depois: um link com usina no meio pode ter sido colado num e-mail, e
 * favorito do cliente não pode virar tela em branco — a mesma regra dos endereços antigos.
 * A usina é DESCARTADA de propósito: a comparação é de todas, e carregar uma no endereço
 * prometeria um recorte que a tela não faz.
 */
function ComparativoDaCarteira({ familia }: { familia: 'energia' | 'manutencao' }) {
  const local = useLocation()
  return <Navigate to={`/comparar/${familia}${local.search}`} replace />
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

              {/* Carteira: comparar usinas. Fora de `/usinas/:id` de propósito. */}
              <Route path="/comparar/energia" element={<CompararEnergia />} />
              <Route path="/comparar/manutencao" element={<CompararManutencao />} />

              {/* Geração de energia */}
              <Route path="/usinas/:id/energia" element={<Energia />} />
              <Route path="/usinas/:id/energia/paradas" element={<Paradas />} />
              <Route path="/usinas/:id/energia/dados" element={<BaixarDados />} />

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

              {/* O comparativo é da carteira: a usina no meio do endereço é descartada. */}
              <Route
                path="/usinas/:id/comparar/energia"
                element={<ComparativoDaCarteira familia="energia" />}
              />
              <Route
                path="/usinas/:id/comparar/manutencao"
                element={<ComparativoDaCarteira familia="manutencao" />}
              />

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
