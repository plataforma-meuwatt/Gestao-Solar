/**
 * "Entrar com o Gestão Solar" no meuGuarda, para o dono de usina (pedido do dono, 11/11/2026).
 *
 * O meuGuarda manda o navegador para `/entrar/meuguarda?volta=<endereço dele>`. Sem sessão, o `Protegido` leva à
 * entrada e traz de volta para cá (com o `?volta=`). Com sessão, o BFF assina quem é a pessoa e o navegador segue
 * para a `volta` com a asserção no fragmento. A `volta` só pode ser do meuGuarda: quem confere é o BFF.
 */

import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { Erro } from '@/components/base'
import { api, mensagemDeErro } from '@/lib/api'

export default function EntrarNoMeuGuarda() {
  const local = useLocation()
  const volta = new URLSearchParams(local.search).get('volta') ?? ''
  const [erro, setErro] = useState('')

  useEffect(() => {
    api
      .post<{ url: string }>('/api/sessao/meuguarda', { volta })
      .then((r) => window.location.replace(r.data.url))
      .catch((e) => setErro(mensagemDeErro(e)))
  }, [volta])

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm text-center">
        {erro ? <Erro mensagem={erro} /> : <p className="text-sm text-fraco">Abrindo o meuGuarda…</p>}
      </div>
    </div>
  )
}
