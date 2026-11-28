/**
 * Os atalhos para o meuWatt e o meuPlano, no topo do portal.
 *
 * O cliente já provou quem é nesta sessão. Clicar aqui carrega essa prova para o outro
 * lado: o BFF assina uma asserção de dois minutos, devolve o endereço do produto com ela
 * no fragmento da URL, e o produto a troca pela sessão dele. Ninguém digita senha de novo.
 *
 * **Fragmento, não query.** `#assercao=` não é enviado ao servidor: não entra em log de
 * acesso, não vaza pelo `Referer`, não fica no histórico de um proxy. A asserção vale dois
 * minutos e uma vez só — mas dois minutos num log são dois minutos a mais do que o preciso.
 *
 * **Aba nova.** O portal fica onde está. Quem abre a manutenção para conferir uma ordem de
 * serviço quer voltar para a geração no clique seguinte, e substituir a página forçaria
 * refazer o caminho.
 *
 * Só aparece o produto liberado para a conta. Um botão que leva a uma recusa é pior do que botão nenhum.
 *
 * Desde 24/11/2026 ("Plano Casa GS") a lista é UMA, a do GS (`GET /api/sessao/produtos`), para os quatro sistemas
 * (meuWatt, meuPlano, meuGuarda, TermoVision): o mesmo caminho e o mesmo registro de acesso para todos.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2 } from 'lucide-react'

import { api, mensagemDeErro } from '@/lib/api'

/** Os sistemas que esta conta abre pelo GS (`GET /api/sessao/produtos`): entram pelo passe, no endereço de entrada deles. */
type DaSessao = { produto: string; nome: string; url: string; direto?: boolean }

export function AbrirProduto() {
  const [abrindo, setAbrindo] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const { data: daSessao } = useQuery({
    queryKey: ['sessao', 'produtos'],
    queryFn: () => api.get<DaSessao[]>('/api/sessao/produtos').then((r) => r.data),
    staleTime: 300_000,
  })

  const lista = daSessao ?? []
  if (lista.length === 0) return null

  async function abrir(produto: string, entrada: string, direto?: boolean) {
    // o helper: só abre (http, pela VPN); a pessoa entra lá com o login do GS
    if (direto) { window.open(entrada, '_blank', 'noopener,noreferrer'); return }
    setAbrindo(produto)
    setErro(null)
    try {
      const { data } = await api.post<{ url: string }>(`/api/sessao/${encodeURIComponent(produto)}`, { volta: entrada })
      // `noopener` corta o acesso da página nova à que a abriu (`window.opener`), que é a
      // higiene padrão de qualquer link para fora.
      window.open(data.url, '_blank', 'noopener,noreferrer')
    } catch (e) {
      setErro(mensagemDeErro(e))
    } finally {
      setAbrindo(null)
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      {lista.map((o) => ({ chave: o.produto, nome: o.nome, entrada: o.url, direto: o.direto })).map((p) => (
        <button
          key={p.chave}
          type="button"
          onClick={() => void abrir(p.chave, p.entrada, p.direto)}
          disabled={abrindo !== null}
          title={`Abrir o ${p.nome} já conectado`}
          className="flex items-center gap-1.5 rounded-campo border border-borda px-2.5 py-1.5 text-xs font-semibold text-fraco transition-colors hover:border-ambar/40 hover:text-corpo disabled:opacity-50"
        >
          {abrindo === p.chave ? (
            <Loader2 size={13} className="animate-spin" aria-hidden />
          ) : (
            <ExternalLink size={13} aria-hidden />
          )}
          <span className="hidden sm:inline">{p.nome}</span>
        </button>
      ))}
      {/* A falha fica ao lado do botão, e não numa página de erro: o portal não quebrou —
          o que não deu foi abrir o outro sistema. */}
      {erro ? <span className="hidden max-w-[16rem] truncate text-xs text-parado lg:inline">{erro}</span> : null}
    </div>
  )
}
