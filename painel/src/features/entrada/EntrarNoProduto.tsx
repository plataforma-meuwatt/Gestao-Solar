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

const NOME: Record<string, string> = {
  meuwatt: 'meuWatt',
  meuplano: 'meuPlano',
  meuguarda: 'meuGuarda',
  termovision: 'TermoVision',
}

/** A janelinha (24/11/2026, "Plano Casa GS"): aberta pelo sistema com `&janela=1`, entrega o passe à página que a abriu
 *  (só à origem da `volta`, que o BFF conferiu) e fecha. Sem quem abriu, navega como sempre. Contrato:
 *  `docs/CONTRATO_PASSE.md`. */
function seguir(url: string, produto: string, janela: boolean) {
  if (janela && window.opener) {
    try {
      const destino = new URL(url)
      const assercao = new URLSearchParams(destino.hash.slice(1)).get('assercao')
      if (assercao) {
        window.opener.postMessage({ tipo: 'gs-passe', produto, assercao }, destino.origin)
        window.close()
        return
      }
    } catch {
      /* endereço estranho: segue pela navegação */
    }
  }
  window.location.replace(url)
}

export function EntrarNoProduto() {
  const token = useAuth((s) => s.token)
  const local = useLocation()
  const { produto = '' } = useParams()
  const busca = new URLSearchParams(local.search)
  const volta = busca.get('volta') ?? ''
  const janela = busca.get('janela') === '1'
  const [erro, setErro] = useState('')
  const nome = NOME[produto]

  useEffect(() => {
    if (!token || !nome) return
    entrarNoProduto(produto, volta)
      .then((r) => seguir(r.url, produto, janela))
      .catch((e) => setErro(mensagemDeErro(e)))
  }, [token, produto, nome, volta, janela])

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
