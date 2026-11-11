/**
 * "Entrar com o Gestão Solar" nos produtos que só recebem o login (meuGuarda, TermoVision), para o dono de usina.
 * Pedidos do dono, 11/11/2026.
 *
 * O produto manda o navegador para `/entrar/<produto>?volta=<endereço dele>`. Sem sessão, o `Protegido` leva à entrada
 * e traz de volta para cá (com o `?volta=`). Com sessão, o BFF assina quem é a pessoa e o navegador segue para a
 * `volta` com a asserção no fragmento. A `volta` só pode ser do produto: quem confere é o BFF.
 */

import { useEffect, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'

import { Erro } from '@/components/base'
import { api, mensagemDeErro } from '@/lib/api'

const NOME: Record<string, string> = { meuguarda: 'meuGuarda', termovision: 'TermoVision' }

export default function EntrarNoProduto() {
  const local = useLocation()
  const { produto = '' } = useParams()
  const volta = new URLSearchParams(local.search).get('volta') ?? ''
  const [erro, setErro] = useState('')
  const nome = NOME[produto]

  useEffect(() => {
    if (!nome) return
    api
      .post<{ url: string }>(`/api/sessao/${encodeURIComponent(produto)}`, { volta })
      .then((r) => window.location.replace(r.data.url))
      .catch((e) => setErro(mensagemDeErro(e)))
  }, [produto, nome, volta])

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm text-center">
        {!nome ? (
          <Erro mensagem="Este endereço de entrada não existe." />
        ) : erro ? (
          <Erro mensagem={erro} />
        ) : (
          <p className="text-sm text-fraco">Abrindo o {nome}…</p>
        )}
      </div>
    </div>
  )
}
