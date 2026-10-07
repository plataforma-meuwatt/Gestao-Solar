import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Campo, Erro } from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

export function Entrada() {
  const { token, entrar } = useAuth()
  const navegar = useNavigate()
  const local = useLocation() as { state?: { de?: string } }

  const [apelido, setApelido] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState('')
  const [entrando, setEntrando] = useState(false)

  // Sem destino pedido, vai para a RAIZ, onde o `Pouso` escolhe a primeira tela do portão
  // desta sessão. Era `/clientes` fixo: o gerente e o técnico entravam direto numa tela da
  // plataforma e liam "Área restrita" como a primeira coisa depois da senha certa.
  if (token) return <Navigate to={local.state?.de || '/'} replace />

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    setEntrando(true)
    try {
      await entrar(apelido.trim().toLowerCase(), senha)
      navegar(local.state?.de || '/', { replace: true })
    } catch (err) {
      // Os campos ficam como estão: refazer o apelido por causa de senha errada é o
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
            rotulo="Apelido"
            autoComplete="username"
            // O apelido é sempre minúsculo. Corrigir a caixa aqui, e não só no envio,
            // evita a cena de digitar "Renan", ver "Renan" na tela e receber erro sem
            // entender o motivo.
            value={apelido}
            onChange={(e) => setApelido(e.target.value.toLowerCase())}
            autoCapitalize="none"
            spellCheck={false}
            placeholder="seu.apelido"
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
