/**
 * `React.lazy` que sobrevive a um deploy.
 *
 * Cada tela do portal é um chunk com hash no nome. Quem deixou a aba aberta durante um
 * deploy tem um `index.html` antigo apontando para chunks que não existem mais; ao
 * navegar, o `import()` falha e a tela cai no limite de erro — parece o portal quebrado,
 * quando só está desatualizado. Aqui a primeira falha recarrega a página UMA vez (o
 * `sessionStorage` impede o loop se o chunk continuar faltando por outro motivo).
 *
 * O meuPlano tem o mesmo mecanismo em todas as suas rotas lazy, pelo mesmo caso real.
 */

import { lazy, type ComponentType } from 'react'

const CHAVE = 'gs_portal_recarregou_por_chunk'

export function lazyRetry<T extends ComponentType<unknown>>(
  importar: () => Promise<{ default: T }>,
) {
  return lazy(async () => {
    try {
      const modulo = await importar()
      sessionStorage.removeItem(CHAVE)
      return modulo
    } catch (erro) {
      if (!sessionStorage.getItem(CHAVE)) {
        sessionStorage.setItem(CHAVE, '1')
        window.location.reload()
        // A página está recarregando; devolve uma promessa que nunca resolve para o
        // Suspense não piscar um erro no meio do caminho.
        return new Promise<{ default: T }>(() => {})
      }
      throw erro
    }
  })
}
