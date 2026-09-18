import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'

import { Conexoes } from '@/features/conexoes/Conexoes'
import { Diagnostico } from '@/features/diagnostico/Diagnostico'
import { Entrada } from '@/features/entrada/Entrada'
import { Usuarios } from '@/features/usuarios/Usuarios'
import { DetalheCliente } from '@/features/clientes/Detalhe'
import { ListaClientes } from '@/features/clientes/Lista'
import { NovoCliente } from '@/features/clientes/Novo'
import { Rotas } from '@/features/rotas/Rotas'
import { Usinas } from '@/features/usinas/Usinas'
import { Whatsapp } from '@/features/whatsapp/Whatsapp'
import { aoPerderSessao } from '@/lib/api'
import { Layout, SoAdministrador, SoArea, primeiraTela } from '@/shell/Layout'
import { useAuth } from '@/store/auth'

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      // Dado de cadastro muda quando alguém edita, não sozinho — refazer a cada foco de
      // janela seria consulta à toa nos dois upstreams.
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
})

// Sessão expirada em qualquer chamada derruba o painel para a entrada, em vez de deixar
// telas vazias sem explicação.
aoPerderSessao(() => useAuth.getState().sair())

/**
 * Onde a pessoa pousa ao abrir o painel.
 *
 * Não é "sempre Clientes": quem não tem essa área leria um 403 como primeira tela, na
 * própria casa. Vai para a primeira tela do menu que ela abre — e, se não abre nenhuma,
 * lê que falta acesso em vez de rodar entre redirecionamentos.
 */
function Pouso() {
  const { pode, ehAdministrador } = useAuth()
  const destino = primeiraTela(pode, ehAdministrador())
  if (destino) return <Navigate to={destino} replace />
  return (
    <div className="cartao p-8 max-w-lg">
      <p className="text-forte font-semibold">Sua conta ainda não tem nenhuma tela</p>
      <p className="text-sm text-rotulo mt-2">
        Peça a quem administra o painel para conceder o acesso em Usuários do sistema.
      </p>
    </div>
  )
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      {/* Sem `basename`: o painel é um serviço próprio e vive na raiz do domínio dele.
          Enquanto o BFF o servia, ele morava sob `/painel` — e um basename sobrando é
          silencioso do pior jeito: nenhuma rota casa, o React monta um nada, e a tela
          fica preta sem um erro sequer no console. */}
      <Router>
        <Routes>
          <Route path="/entrar" element={<Entrada />} />

          <Route element={<Layout />}>
            {/* Cada tela repete, no `SoArea`, a MESMA área que o BFF exige nas rotas dela.
                A da tela é conforto (a pessoa lê o que fazer em vez de ver cartões vazios);
                a do servidor é a que vale. */}
            <Route
              path="/clientes"
              element={
                <SoArea area="clientes">
                  <ListaClientes />
                </SoArea>
              }
            />
            <Route
              path="/clientes/novo"
              element={
                <SoArea area="clientes">
                  <NovoCliente />
                </SoArea>
              }
            />
            <Route
              path="/clientes/:id"
              element={
                <SoArea area="clientes">
                  <DetalheCliente />
                </SoArea>
              }
            />
            <Route
              path="/usinas"
              element={
                <SoArea area="usinas">
                  <Usinas />
                </SoArea>
              }
            />
            <Route
              path="/diagnostico"
              element={
                <SoArea area="diagnostico">
                  <Diagnostico />
                </SoArea>
              }
            />
            <Route
              path="/conexoes"
              element={
                <SoArea area="conexoes">
                  <Conexoes />
                </SoArea>
              }
            />
            <Route
              path="/rotas"
              element={
                <SoArea area="rotas">
                  <Rotas />
                </SoArea>
              }
            />
            <Route
              path="/whatsapp"
              element={
                <SoArea area="whatsapp">
                  <Whatsapp />
                </SoArea>
              }
            />
            <Route
              path="/usuarios"
              element={
                <SoAdministrador>
                  <Usuarios />
                </SoAdministrador>
              }
            />
            {/* A tela se chamava Equipe até 18/09/2026. O atalho fica porque o link está
                em favorito e em conversa antiga — sem ele, a URL antiga cairia no
                redirecionamento geral e ninguém entenderia por que foi parar em Clientes. */}
            <Route path="/equipe" element={<Navigate to="/usuarios" replace />} />
            <Route index element={<Pouso />} />
          </Route>

          <Route path="*" element={<Pouso />} />
        </Routes>
      </Router>
    </QueryClientProvider>
  )
}
