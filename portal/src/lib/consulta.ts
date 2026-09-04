/**
 * O cliente de consultas, e o botão que o esvazia.
 *
 * `refetchOnWindowFocus` ligado de propósito, ao contrário do painel: o painel é cadastro,
 * que só muda quando alguém edita; o portal é geração e manutenção, que mudam sozinhas.
 * Um diretor que deixa a aba aberta e volta depois do almoço tem de ver o número de agora
 * — o selo "atualizado às HH:MM" diz quando foi.
 *
 * `esquecerConsultas()` existe pelo mesmo motivo do app: o cache em memória sobrevivia ao
 * logout e, na troca de conta no mesmo computador, as usinas de quem saiu voltavam para
 * quem entrou — apresentadas como leitura ao vivo. Dado de outra pessoa apresentado como
 * atual é vazamento, não atraso.
 */

import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})

/** Esvazia tudo o que está em memória. Chamado no logout, junto com o cache em disco. */
export function esquecerConsultas(): void {
  queryClient.clear()
}
