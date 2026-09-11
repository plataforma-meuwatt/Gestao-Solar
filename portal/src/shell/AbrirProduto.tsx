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
 * Só aparece o produto ao qual a conta está vinculada (`tem_meuwatt` / `tem_meuplano`).
 * Um botão que leva a uma recusa é pior do que botão nenhum — e quem recusa é o produto,
 * que é quem sabe do vínculo.
 */

import { useState } from 'react'
import { ExternalLink, Loader2 } from 'lucide-react'

import { api, mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

type Produto = 'meuwatt' | 'meuplano'

const ROTULO: Record<Produto, string> = { meuwatt: 'meuWatt', meuplano: 'meuPlano' }

export function AbrirProduto() {
  const usuario = useAuth((s) => s.usuario)
  const [abrindo, setAbrindo] = useState<Produto | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  const disponiveis: Produto[] = [
    ...(usuario?.tem_meuwatt ? (['meuwatt'] as const) : []),
    ...(usuario?.tem_meuplano ? (['meuplano'] as const) : []),
  ]
  if (disponiveis.length === 0) return null

  async function abrir(produto: Produto) {
    setAbrindo(produto)
    setErro(null)
    try {
      const { data } = await api.post<{ url: string; nome: string }>(
        `/api/v1/auth/produtos/${produto}/entrar`,
      )
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
      {disponiveis.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => void abrir(p)}
          disabled={abrindo !== null}
          title={`Abrir o ${ROTULO[p]} já conectado`}
          className="flex items-center gap-1.5 rounded-campo border border-borda px-2.5 py-1.5 text-xs font-semibold text-fraco transition-colors hover:border-ambar/40 hover:text-corpo disabled:opacity-50"
        >
          {abrindo === p ? (
            <Loader2 size={13} className="animate-spin" aria-hidden />
          ) : (
            <ExternalLink size={13} aria-hidden />
          )}
          <span className="hidden sm:inline">{ROTULO[p]}</span>
        </button>
      ))}
      {/* A falha fica ao lado do botão, e não numa página de erro: o portal não quebrou —
          o que não deu foi abrir o outro sistema. */}
      {erro ? <span className="hidden max-w-[16rem] truncate text-xs text-parado lg:inline">{erro}</span> : null}
    </div>
  )
}
