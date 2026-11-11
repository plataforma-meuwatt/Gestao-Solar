/**
 * "Entrar com o Gestão Solar" no meuGuarda (pedido do dono, 11/11/2026: "eu clico, o Gestão Solar autentica e boa").
 *
 * O meuGuarda manda o navegador para `/entrar/meuguarda?volta=<endereço dele>`. Sem sessão, a pessoa entra aqui e
 * volta a esta página (com o `?volta=`: o `Layout` guardaria só o caminho). Com sessão, o BFF assina quem ela é, e de
 * qual portão, e o navegador segue para a `volta` com a asserção no fragmento. A `volta` só pode ser do meuGuarda: quem
 * confere é o BFF (`api/v1/sessao.py`).
 */

import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { Erro } from '@/components/base'
import { entrarNoMeuGuarda } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

export function EntrarNoMeuGuarda() {
  const token = useAuth((s) => s.token)
  const local = useLocation()
  const volta = new URLSearchParams(local.search).get('volta') ?? ''
  const [erro, setErro] = useState('')

  useEffect(() => {
    if (!token) return
    entrarNoMeuGuarda(volta)
      .then((r) => window.location.replace(r.url))
      .catch((e) => setErro(mensagemDeErro(e)))
  }, [token, volta])

  if (!token) return <Navigate to="/entrar" replace state={{ de: local.pathname + local.search }} />
  return (
    <div className="h-full grid place-items-center px-4">
      <div className="cartao p-6 w-full max-w-sm text-center">
        {erro ? <Erro>{erro}</Erro> : <p className="text-sm text-rotulo">Abrindo o meuGuarda…</p>}
      </div>
    </div>
  )
}
