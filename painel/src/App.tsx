import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'

import { LogDoBot } from '@/features/bot/LogDoBot'
import { Diagnostico } from '@/features/diagnostico/Diagnostico'
import { EmpresaPagina } from '@/features/empresas/Empresa'
import { Empresas } from '@/features/empresas/Empresas'
import { Entrada } from '@/features/entrada/Entrada'
import { BotDaEmpresa } from '@/features/empresa/Bot'
import { ConexoesDaEmpresa } from '@/features/empresa/Conexoes'
import { VinculosDaEmpresa } from '@/features/empresa/Vinculos'
import { UsinasDaEmpresa } from '@/features/empresa/Usinas'
import { UsuariosDaEmpresa } from '@/features/empresa/Usuarios'
import { Usuarios } from '@/features/usuarios/Usuarios'
import { DetalheCliente } from '@/features/clientes/Detalhe'
import { Rotas } from '@/features/rotas/Rotas'
import { Usinas } from '@/features/usinas/Usinas'
import { MeuWhatsapp } from '@/features/tecnico/MeuWhatsapp'
import { Whatsapp } from '@/features/whatsapp/Whatsapp'
import { aoPerderSessao } from '@/lib/api'
import { Layout, SoAdministrador, SoArea, SoEmpresa, SoTecnico, primeiraTela } from '@/shell/Layout'
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
 * Não é "sempre Empresas": quem não tem essa área leria um 403 como primeira tela, na
 * própria casa. Vai para a primeira tela do menu que ela abre — e, se não abre nenhuma,
 * lê que falta acesso em vez de rodar entre redirecionamentos.
 */
function Pouso() {
  const { pode, ehAdministrador, escopo } = useAuth()
  const destino = primeiraTela(pode, ehAdministrador(), escopo)
  if (destino) return <Navigate to={destino} replace />
  return (
    <div className="cartao p-8 max-w-lg">
      <p className="text-forte font-semibold">Sua conta ainda não tem nenhuma tela</p>
      <p className="text-sm text-rotulo mt-2">
        Peça a quem administra o painel para conceder o acesso em Usuários.
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
            {/* adm-gs: Empresas é a entrada (os clientes da plataforma são as empresas de
                O&M, e cada uma tem os usuários dela); Usuários é o inverso. A lista de
                "Clientes" solta e o "Novo cliente" sem empresa saíram em 23/10/2026 — o
                cliente nasce dentro da empresa. A ficha dele continua, aberta da lista. */}
            <Route
              path="/empresas"
              element={
                <SoArea area="empresas">
                  <Empresas />
                </SoArea>
              }
            />
            <Route
              path="/empresas/:id"
              element={
                <SoArea area="empresas">
                  <EmpresaPagina />
                </SoArea>
              }
            />
            <Route path="/clientes" element={<Navigate to="/usuarios" replace />} />
            <Route path="/clientes/novo" element={<Navigate to="/empresas" replace />} />
            <Route
              path="/clientes/:id"
              element={
                <SoArea area="clientes">
                  <DetalheCliente />
                </SoArea>
              }
            />
            <Route
              path="/bot"
              element={
                <SoArea area="bot">
                  <LogDoBot />
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
            {/* "Acesso do painel aos produtos" saiu: a plataforma não tem token (regra do
                dono, 23/10/2026). Favorito antigo cai em Empresas. */}
            <Route path="/conexoes" element={<Navigate to="/empresas" replace />} />
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

            {/* O outro portão. `SoEmpresa` não é conforto como as áreas: uma sessão de
                painel aqui chamaria `/api/empresa/*` e tomaria 403 — a tela diz isso em
                vez de desenhar cartões vazios. */}
            <Route
              path="/minha-empresa/usinas"
              element={
                <SoEmpresa>
                  <UsinasDaEmpresa />
                </SoEmpresa>
              }
            />
            {/* "Clientes" repetia "Usuários" com um segundo formulário: os donos de usina
                são usuários da empresa, e moram lá. */}
            <Route path="/minha-empresa/clientes" element={<Navigate to="/minha-empresa/usuarios" replace />} />
            <Route
              path="/minha-empresa/bot"
              element={
                <SoEmpresa>
                  <BotDaEmpresa />
                </SoEmpresa>
              }
            />
            <Route
              path="/minha-empresa/usuarios"
              element={
                <SoEmpresa>
                  <UsuariosDaEmpresa />
                </SoEmpresa>
              }
            />
            <Route
              path="/minha-empresa/conexoes"
              element={
                <SoEmpresa>
                  <ConexoesDaEmpresa />
                </SoEmpresa>
              }
            />
            <Route
              path="/minha-empresa/vinculos"
              element={
                <SoEmpresa>
                  <VinculosDaEmpresa />
                </SoEmpresa>
              }
            />
            {/* O terceiro portão: o técnico, e só o WhatsApp dele. */}
            <Route
              path="/meu-whatsapp"
              element={
                <SoTecnico>
                  <MeuWhatsapp />
                </SoTecnico>
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
