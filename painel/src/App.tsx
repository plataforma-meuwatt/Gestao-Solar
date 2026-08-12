import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'

import { Conexoes } from '@/features/conexoes/Conexoes'
import { Diagnostico } from '@/features/diagnostico/Diagnostico'
import { Entrada } from '@/features/entrada/Entrada'
import { Equipe } from '@/features/equipe/Equipe'
import { DetalheCliente } from '@/features/clientes/Detalhe'
import { ListaClientes } from '@/features/clientes/Lista'
import { NovoCliente } from '@/features/clientes/Novo'
import { Usinas } from '@/features/usinas/Usinas'
import { aoPerderSessao } from '@/lib/api'
import { Layout, SoAdministrador } from '@/shell/Layout'
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

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <Router basename="/painel">
        <Routes>
          <Route path="/entrar" element={<Entrada />} />

          <Route element={<Layout />}>
            <Route path="/clientes" element={<ListaClientes />} />
            <Route path="/clientes/novo" element={<NovoCliente />} />
            <Route path="/clientes/:id" element={<DetalheCliente />} />
            <Route path="/usinas" element={<Usinas />} />
            <Route path="/diagnostico" element={<Diagnostico />} />
            <Route
              path="/conexoes"
              element={
                <SoAdministrador>
                  <Conexoes />
                </SoAdministrador>
              }
            />
            <Route
              path="/equipe"
              element={
                <SoAdministrador>
                  <Equipe />
                </SoAdministrador>
              }
            />
            <Route index element={<Navigate to="/clientes" replace />} />
          </Route>

          <Route path="*" element={<Navigate to="/clientes" replace />} />
        </Routes>
      </Router>
    </QueryClientProvider>
  )
}
