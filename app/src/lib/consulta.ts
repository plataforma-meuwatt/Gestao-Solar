/**
 * O cliente de consultas, e o botão que o esvazia.
 *
 * Ele vivia no escopo do módulo em `_layout.tsx`, e **nada o limpava no logout**. O
 * `limparCache()` apagava a pasta em disco e parava aí; o cache em memória do TanStack
 * sobrevivia, com `queryKey` sem identificação de usuário.
 *
 * O efeito é o pior que este aplicativo pode ter: na troca de conta no mesmo aparelho —
 * cenário que o CLAUDE.md descreve como corriqueiro, `renanmarquezini` gestor e
 * `renan.marquezini` dono —, dentro do `gcTime` (cinco minutos, por padrão), as usinas, a
 * potência e as mensalidades da conta anterior voltavam para a nova. E voltavam **sem o
 * selo de horário**: como o dado vinha do cache em memória, `fetchWithCache` o tratava
 * como resposta de rede e a tela o apresentava como leitura ao vivo.
 *
 * Dado de outra pessoa apresentado como atual é vazamento, não atraso.
 */

import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Dado de geração muda a cada poucos minutos; refazer a cada foco seria ruído.
      staleTime: 60_000,
      retry: 1,
    },
  },
})

/** Esvazia tudo o que está em memória. Chamado no logout, junto com o cache em disco. */
export function esquecerConsultas(): void {
  queryClient.clear()
}
