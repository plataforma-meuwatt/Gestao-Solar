/**
 * "Entrar com o Gestão Solar" nos produtos que só recebem o login (meuGuarda, TermoVision): a entrada ÚNICA, para
 * qualquer conta. Pedidos do dono, 11/11/2026 ("no final é tudo o mesmo login: a tela principal deve aceitar todos").
 *
 * O produto manda o navegador para `gestao.solar/entrar/<produto>?volta=<endereço dele>`.
 * - Com a sessão do portal (dono de usina): o BFF assina quem é a pessoa e o navegador segue para a `volta`.
 * - Sem sessão: o apelido e a senha do GS de QUALQUER conta (equipe da O&M, dono de usina, plataforma), UMA vez
 *   (`POST /api/sessao/<produto>/com-senha`). A resposta traz a sessão de ENTRADA, guardada aqui (`gs_entrada`): ela só
 *   gera as asserções dos produtos (nenhuma tela do GS a aceita), dura 30 dias e se renova a cada uso. Assim a pessoa
 *   não digita a senha de novo ("não quero fazer login, já estou autenticado via Gestão", o dono, 12/11/2026).
 * Nos dois, a asserção vai no fragmento, e a `volta` só pode ser do produto: quem confere é o BFF.
 *
 * Desde 24/11/2026 ("Plano Casa GS": GS é o pai) a entrada é dos QUATRO sistemas (meuWatt, meuPlano, meuGuarda e
 * TermoVision), entra-se pelo login OU pelo e-mail, e há a JANELINHA: o sistema abre esta página com `&janela=1`
 * (`window.open`) e, em vez de navegar, ela entrega o passe à página que a abriu (`postMessage` só para a origem da
 * `volta`, que o BFF já conferiu) e fecha. Sem a página que abriu (janela bloqueada, link aberto direto), segue como
 * sempre: navega para a `volta`. O contrato está em `docs/CONTRATO_PASSE.md`.
 */

import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useParams } from 'react-router-dom'

import { Aviso, Erro } from '@/components/base'
import { LockupGS } from '@/components/marca'
import { api, mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

const NOME: Record<string, string> = {
  meuwatt: 'meuWatt',
  meuplano: 'meuPlano',
  meuguarda: 'meuGuarda',
  termovision: 'TermoVision',
}
const CHAVE = 'gs_entrada'

type Resposta = { url: string; entrada?: string | null }

/** Na janelinha, o passe vai à página que a abriu (só à origem da `volta`) e a janela fecha; fora dela, navega. */
export function seguir(
  url: string,
  produto: string,
  janela: boolean,
  ir: (u: string) => void = (u) => window.location.replace(u),
) {
  if (janela && window.opener) {
    try {
      const destino = new URL(url)
      const assercao = new URLSearchParams(destino.hash.slice(1)).get('assercao')
      if (assercao) {
        window.opener.postMessage({ tipo: 'gs-passe', produto, assercao }, destino.origin)
        window.close()
        return
      }
    } catch {
      /* endereço estranho: segue pela navegação, que o BFF já conferiu */
    }
  }
  ir(url)
}

function lerEntrada(): string | null {
  try {
    return localStorage.getItem(CHAVE)
  } catch {
    return null
  }
}

function gravarEntrada(token: string | null | undefined) {
  try {
    if (token) localStorage.setItem(CHAVE, token)
    else localStorage.removeItem(CHAVE)
  } catch {
    /* sem armazenamento: a senha é pedida de novo da próxima vez */
  }
}

export default function EntrarNoProduto() {
  const local = useLocation()
  const { produto = '' } = useParams()
  const token = useAuth((s) => s.token)
  // a sessão do portal (dono de usina) ou, sem ela, a de ENTRADA guardada aqui
  const [entrada, setEntrada] = useState(lerEntrada)
  const busca = new URLSearchParams(local.search)
  const volta = busca.get('volta') ?? ''
  const janela = busca.get('janela') === '1'
  const nome = NOME[produto]
  const [erro, setErro] = useState('')
  const [apelido, setApelido] = useState('')
  const [senha, setSenha] = useState('')
  const [entrando, setEntrando] = useState(false)
  const caminho = `/api/sessao/${encodeURIComponent(produto)}`

  useEffect(() => {
    if (!nome || (!token && !entrada)) return
    api
      .post<Resposta>(caminho, { volta }, token ? undefined : { headers: { Authorization: `Bearer ${entrada}` } })
      .then((r) => {
        if (r.data.entrada) gravarEntrada(r.data.entrada)
        seguir(r.data.url, produto, janela)
      })
      .catch((e) => {
        if (!token && (e as { response?: { status?: number } })?.response?.status === 401) {
          gravarEntrada(null)                              // venceu ou foi recusada: a senha de novo, uma vez
          setEntrada(null)
          return
        }
        setErro(mensagemDeErro(e))
      })
  }, [caminho, nome, token, entrada, volta, produto, janela])

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setErro('')
    setEntrando(true)
    try {
      const r = await api.post<Resposta>(`${caminho}/com-senha`, { apelido: apelido.trim(), senha, volta })
      gravarEntrada(r.data.entrada)
      seguir(r.data.url, produto, janela)
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
  if (token || entrada) {
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
              Login ou e-mail
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
              placeholder="seu.login ou voce@empresa.com"
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
