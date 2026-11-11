/**
 * "Entrar com o Gestão Solar" nos produtos que só recebem o login: o meuGuarda (CFTV) e o TermoVision (inspeção
 * térmica). Pedidos do dono, 11/11/2026 ("eu clico, o Gestão Solar autentica e boa"; o TermoVision "igual meuguarda").
 *
 * O produto manda o navegador para `/entrar/<produto>?volta=<endereço dele>`. Sem sessão, a pessoa entra aqui e
 * volta a esta página (com o `?volta=`: o `Layout` guardaria só o caminho). Com sessão, o BFF assina quem ela é, e de
 * qual portão, e o navegador segue para a `volta` com a asserção no fragmento. A `volta` só pode ser do produto: quem
 * confere é o BFF (`api/v1/sessao.py`).
 */

import { useEffect, useState } from 'react'
import { Navigate, useLocation, useParams } from 'react-router-dom'

import { Erro } from '@/components/base'
import { entrarNoProduto } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

const NOME: Record<string, string> = { meuguarda: 'meuGuarda', termovision: 'TermoVision' }

export function EntrarNoProduto() {
  const token = useAuth((s) => s.token)
  const local = useLocation()
  const { produto = '' } = useParams()
  const volta = new URLSearchParams(local.search).get('volta') ?? ''
  const [erro, setErro] = useState('')
  const nome = NOME[produto]

  useEffect(() => {
    if (!token || !nome) return
    entrarNoProduto(produto, volta)
      .then((r) => window.location.replace(r.url))
      .catch((e) => setErro(mensagemDeErro(e)))
  }, [token, produto, nome, volta])

  if (!token) return <Navigate to="/entrar" replace state={{ de: local.pathname + local.search }} />
  return (
    <div className="h-full grid place-items-center px-4">
      <div className="cartao p-6 w-full max-w-sm text-center">
        {!nome ? (
          <Erro>Este endereço de entrada não existe.</Erro>
        ) : erro ? (
          <Erro>{erro}</Erro>
        ) : (
          <p className="text-sm text-rotulo">Abrindo o {nome}…</p>
        )}
      </div>
    </div>
  )
}
