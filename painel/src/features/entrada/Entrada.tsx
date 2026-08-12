import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Campo, Erro } from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

export function Entrada() {
  const { token, entrar } = useAuth()
  const navegar = useNavigate()
  const local = useLocation() as { state?: { de?: string } }

  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState('')
  const [entrando, setEntrando] = useState(false)

  if (token) return <Navigate to={local.state?.de || '/clientes'} replace />

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    setEntrando(true)
    try {
      await entrar(email.trim(), senha)
      navegar(local.state?.de || '/clientes', { replace: true })
    } catch (err) {
      // Os campos ficam como estão: refazer o e-mail por causa de senha errada é o
      // atrito que faz alguém desistir na segunda tentativa.
      setErro(mensagemDeErro(err))
    } finally {
      setEntrando(false)
    }
  }

  return (
    <div className="h-full grid place-items-center px-4">
      <form onSubmit={enviar} className="w-full max-w-sm">
        <div className="text-center mb-7">
          <p className="text-3xl font-bold text-forte tracking-tight">
            Gestão <span className="text-ambar">Solar</span>
          </p>
          <p className="text-sm text-rotulo mt-1">Painel de administração</p>
        </div>

        <div className="cartao p-5 flex flex-col gap-4">
          {erro ? <Erro>{erro}</Erro> : null}

          <Campo
            rotulo="E-mail"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
            required
          />
          <Campo
            rotulo="Senha"
            type="password"
            autoComplete="current-password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            required
          />

          <button type="submit" className="btn-primario" disabled={entrando}>
            {entrando ? 'Entrando…' : 'Entrar'}
          </button>
        </div>
      </form>
    </div>
  )
}
