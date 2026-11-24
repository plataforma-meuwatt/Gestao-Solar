/**
 * O que a tela da conta pede ao BFF.
 *
 * São duas leituras e uma escrita, e todas passam pela porta do CLIENTE (`/api/v1/auth/*`) —
 * a mesma do aplicativo. A porta do gestor é outra, e o BFF recusa um token dela aqui; ver o
 * cabeçalho de `store/auth.ts`.
 *
 * A lista de usinas concedidas NÃO tem rota própria: ela é `GET /api/v1/plants`, a mesma
 * leitura que a barra do topo e a Visão geral fazem. Reusar a chave `plants` do `useLeitura`
 * é o que faz as três telas caberem em UMA ida à rede — e, de quebra, garante que a conta e
 * o seletor nunca discordem sobre quais usinas existem.
 */

import { api } from '@/lib/api'
import { useAuth } from '@/store/auth'
import type { Usuario } from '@/store/auth'

// O contrato de `/plants` é declarado uma vez só, onde ele já era lido. Repetir o tipo aqui
// criaria duas versões da mesma verdade, que envelhecem em ritmos diferentes.
export type { UsinaDaLista, UsinasOut } from '@/shell/SeletorUsina'

/** O perfil como o servidor o vê AGORA — não a cópia que ficou no disco desde o login. */
export async function lerPerfil(): Promise<Usuario> {
  const { data } = await api.get<Usuario>('/api/v1/auth/eu')
  return data
}

/**
 * Troca a senha. As outras sessões da conta acabam (R12), e volta a sessão nova DESTE navegador, que fica guardada.
 *
 * As recusas (senha atual errada, nova curta demais, nova igual à atual) chegam como 400 com
 * `detail` em texto — a tela mostra a frase que o servidor escreveu, e não uma tradução
 * própria que pode divergir da regra real.
 */
export async function trocarSenha(senhaAtual: string, senhaNova: string): Promise<void> {
  const { data } = await api.post<{ token: string; expira_em: string | null }>('/api/v1/auth/trocar-senha', {
    senha_atual: senhaAtual,
    senha_nova: senhaNova,
  })
  if (data?.token) useAuth.getState().trocarToken(data.token, data.expira_em ?? null)
}
