/**
 * "Entrar com o Gestão Solar" nos produtos que só recebem o login (meuGuarda, TermoVision): a entrada ÚNICA, para
 * qualquer conta. Pedidos do dono, 11/11/2026 ("no final é tudo o mesmo login: a tela principal deve aceitar todos").
 *
 * O produto manda o navegador para `gestao.solar/entrar/<produto>?volta=<endereço dele>`.
 * - Com a sessão do portal (dono de usina): o BFF assina quem é a pessoa e o navegador segue para a `volta`.
 * - Sem sessão: o apelido e a senha do GS de QUALQUER conta (equipe da O&M, dono de usina, plataforma). A senha não
 *   abre sessão aqui: vale só para esta entrada (`POST /api/sessao/<produto>/com-senha`).
 * Nos dois, a asserção vai no fragmento, e a `volta` só pode ser do produto: quem confere é o BFF.
 */

import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useParams } from 'react-router-dom'

import { Aviso, Erro } from '@/components/base'
import { LockupGS } from '@/components/marca'
import { api, mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

const NOME: Record<string, string> = { meuguarda: 'meuGuarda', termovision: 'TermoVision' }

export default function EntrarNoProduto() {
  const local = useLocation()
  const { produto = '' } = useParams()
  const token = useAuth((s) => s.token)
  const volta = new URLSearchParams(local.search).get('volta') ?? ''
  const nome = NOME[produto]
  const [erro, setErro] = useState('')
  const [apelido, setApelido] = useState('')
  const [senha, setSenha] = useState('')
  const [entrando, setEntrando] = useState(false)
  const caminho = `/api/sessao/${encodeURIComponent(produto)}`

  useEffect(() => {
    if (!nome || !token) return
    api
      .post<{ url: string }>(caminho, { volta })
      .then((r) => window.location.replace(r.data.url))
      .catch((e) => setErro(mensagemDeErro(e)))
  }, [caminho, nome, token, volta])

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setErro('')
    setEntrando(true)
    try {
      const r = await api.post<{ url: string }>(`${caminho}/com-senha`, { apelido: apelido.trim(), senha, volta })
      window.location.replace(r.data.url)
    } catch (x) {
      setErro(mensagemDeErro(x))
      setEntrando(false)
    }
  }

  if (!nome) {
    return (
      <div className="grid min-h-screen place-items-center px-4">
        <div className="w-full max-w-sm">
          <Erro mensagem="Este endereço de entrada não existe." />
        </div>
      </div>
    )
  }
  if (token) {
    return (
      <div className="grid min-h-screen place-items-center px-4">
        <div className="w-full max-w-sm text-center">
          {erro ? <Erro mensagem={erro} /> : <p className="text-sm text-fraco">Abrindo o {nome}…</p>}
        </div>
      </div>
    )
  }
  return (
    <div className="grid min-h-screen place-items-center bg-fundo px-4">
      <div className="w-full max-w-sm">
        <LockupGS tamanho={40} />
        <h2 className="mt-6 text-[calc(22px_+_var(--passo-tipo))] font-semibold tracking-[-0.02em] text-forte">
          Entrar no {nome}
        </h2>
        <p className="mt-1 text-sm text-fraco">
          Com a sua conta do Gestão Solar: equipe da O&amp;M, dono de usina ou plataforma.
        </p>
        <form onSubmit={enviar} className="mt-6 flex flex-col gap-4">
          {erro ? (
            <div role="alert">
              <Aviso tom="parado">{erro}</Aviso>
            </div>
          ) : null}
          <div>
            <label className="rotulo-campo" htmlFor="apelido">
              Apelido
            </label>
            <input
              id="apelido"
              className="campo"
              value={apelido}
              onChange={(e) => setApelido(e.target.value.toLowerCase())}
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              placeholder="seu.apelido"
              autoFocus
              required
            />
          </div>
          <div>
            <label className="rotulo-campo" htmlFor="senha">
              Senha
            </label>
            <input
              id="senha"
              className="campo"
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <button type="submit" className="btn-primario" disabled={entrando}>
            {entrando ? 'Entrando…' : `Entrar no ${nome}`}
          </button>
        </form>
      </div>
    </div>
  )
}
