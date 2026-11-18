/**
 * O atalho do mapa único: gestao.solar/mapa/<id>, e o endereço que os OUTROS produtos montam sem saber o id daqui —
 * `/mapa?meuplano=<usina do meuPlano>` (o botão do mapa do meuPlano) e `/mapa?meuwatt=<slug>` (o do meuWatt). Leva à
 * tela da usina (`/usinas/<id>/mapa`). A usina que a pessoa não vê não é achada — a lista é a do recorte dela.
 */

import { useEffect, useState } from 'react'
import { Navigate, useParams, useSearchParams } from 'react-router-dom'

import { Erro, Pagina } from '@/components/base'
import { mensagemDeErro } from '@/lib/api'

import { usinasDoMapa } from './api'

export default function AtalhoDoMapa() {
  const { id } = useParams()
  const [q] = useSearchParams()
  const [destino, setDestino] = useState<string | null>(id ? `/usinas/${id}/mapa` : null)
  const [erro, setErro] = useState<string | null>(null)
  const mp = q.get('meuplano')
  const mw = q.get('meuwatt')

  useEffect(() => {
    if (id) return
    usinasDoMapa()
      .then((lista) => {
        const u = lista.find((x) => (mp && String(x.mp_usina_id) === mp) || (mw && x.mw_slug === mw))
        if (u) setDestino(`/usinas/${u.id}/mapa`)
        else setErro(mp || mw ? 'Esta usina não está entre as suas no Gestão Solar.' : 'Diga a usina do mapa.')
      })
      .catch((e) => setErro(mensagemDeErro(e)))
  }, [id, mp, mw])

  if (destino) return <Navigate to={destino} replace />
  return (
    <Pagina titulo="Mapa da usina">
      {erro ? <Erro mensagem={erro} /> : <p className="text-sm text-fraco">Procurando a usina…</p>}
    </Pagina>
  )
}
