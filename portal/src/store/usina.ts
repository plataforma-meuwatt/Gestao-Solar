/**
 * A usina escolhida — o contexto que atravessa o portal inteiro.
 *
 * No aplicativo o dono toca numa usina e entra nela; no navegador ele tem uma barra sempre à
 * vista, e a usina é o assunto de quase toda tela (energia, paradas, cronograma, ordens,
 * pendências, relatórios). Guardar a escolha aqui, e não na URL apenas, resolve duas coisas:
 * ao trocar de usina o portal mantém a MESMA seção (quem estava vendo o cronograma de uma
 * continua no cronograma da outra), e ao voltar dias depois o site abre onde ele parou.
 *
 * A URL continua mandando: `/usinas/:id` é o endereço de verdade, favoritável e
 * compartilhável. Este store é a memória de qual foi a última — o roteador escreve nele, e
 * ele decide para onde ir quando alguém entra pela raiz.
 *
 * A escolha é guardada POR CONTA (`gs-portal-usina:u{id}`): a mesma pessoa pode ter conta de
 * gestor e de dono no mesmo computador, e a usina de uma não é assunto da outra.
 */

import { create } from 'zustand'

const chave = (usuarioId: number | null) =>
  `gs-portal-usina:${usuarioId === null ? 'anonimo' : `u${usuarioId}`}`

function ler(usuarioId: number | null): number | null {
  try {
    const cru = localStorage.getItem(chave(usuarioId))
    const n = cru ? Number(cru) : NaN
    return Number.isFinite(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

type Estado = {
  /** Id do vínculo (`gs_plant_links.id`) — o mesmo que a URL carrega. */
  id: number | null
  escolher: (id: number | null, usuarioId: number | null) => void
  /** Chamado no boot e na troca de conta: a lembrança é por conta. */
  carregar: (usuarioId: number | null) => void
}

export const useUsina = create<Estado>((set) => ({
  id: null,

  escolher(id, usuarioId) {
    try {
      if (id === null) localStorage.removeItem(chave(usuarioId))
      else localStorage.setItem(chave(usuarioId), String(id))
    } catch {
      // Sem armazenamento a escolha vale só nesta sessão — não é motivo para travar nada.
    }
    set({ id })
  },

  carregar(usuarioId) {
    set({ id: ler(usuarioId) })
  },
}))
