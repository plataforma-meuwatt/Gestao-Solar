/**
 * O "esqueci a senha" do Gestão Solar (Plano Casa GS, R12), para QUALQUER conta (dono de usina, equipe da O&M,
 * plataforma): `/esqueci-a-senha` diz como pedir o link (pelo WhatsApp do GS, do celular cadastrado; pelo e-mail
 * quando houver remetente) e `/nova-senha#t=<link>` cria a senha nova. Tudo vem da API (`/api/v1/auth/senha/*`):
 * o número do WhatsApp e se o e-mail está disponível. O link vale 30 minutos e uma vez só, e a senha nova encerra as
 * sessões abertas da pessoa (inclusive as dos sistemas).
 */
import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { Aviso } from '@/components/base'
import { LockupGS } from '@/components/marca'
import { api, mensagemDeErro } from '@/lib/api'

type Canais = { whatsapp: string | null; email: boolean }

function Quadro({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center bg-fundo px-4 py-10">
      <div className="w-full max-w-sm">
        <LockupGS tamanho={40} />
        <h2 className="mt-6 text-[calc(22px_+_var(--passo-tipo))] font-semibold tracking-[-0.02em] text-forte">
          {titulo}
        </h2>
        {children}
        <p className="mt-8 text-sm">
          <Link className="underline text-corpo" to="/entrar">
            Voltar para entrar
          </Link>
        </p>
      </div>
    </div>
  )
}

export function EsqueciASenha() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['senha', 'canais'],
    queryFn: () => api.get<Canais>('/api/v1/auth/senha/canais').then((r) => r.data),
  })
  const [email, setEmail] = useState('')
  const [mandou, setMandou] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function pedir(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setEnviando(true)
    try {
      await api.post('/api/v1/auth/senha/esqueci', { email: email.trim() })
      setMandou(true)
    } catch (x) {
      setErro(mensagemDeErro(x))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Quadro titulo="Esqueci a senha">
      <div className="mt-4 grid gap-4 text-sm text-corpo">
        <div className="grid gap-1">
          <p className="font-semibold text-forte">Pelo WhatsApp</p>
          {isLoading ? (
            <p className="text-fraco">Lendo o número…</p>
          ) : data?.whatsapp ? (
            <p>
              Do celular cadastrado na sua conta, mande <b>esqueci a senha</b> para o WhatsApp do Gestão Solar,{' '}
              <span className="mono whitespace-nowrap text-forte">{data.whatsapp}</span>. O link para criar a senha
              nova chega na hora e vale 30 minutos.
            </p>
          ) : (
            <p>
              Do celular cadastrado na sua conta, mande <b>esqueci a senha</b> para o WhatsApp do Gestão Solar. (O número
              não pôde ser lido agora{error ? `: ${mensagemDeErro(error)}` : ''}.)
            </p>
          )}
        </div>
        {data?.email ? (
          <form onSubmit={pedir} className="grid gap-2">
            <p className="font-semibold text-forte">Pelo e-mail</p>
            {mandou ? (
              <Aviso tom="ok">
                Se o e-mail é de uma conta, o link chega em instantes (vale 30 minutos). Confira também o spam.
              </Aviso>
            ) : (
              <>
                <label className="rotulo-campo" htmlFor="email">
                  E-mail da conta
                </label>
                <input id="email" className="campo" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                       autoComplete="email" required />
                {erro ? <Aviso tom="parado">{erro}</Aviso> : null}
                <button type="submit" className="btn-primario" disabled={enviando || !email.trim()}>
                  {enviando ? 'Enviando…' : 'Mandar o link'}
                </button>
              </>
            )}
          </form>
        ) : null}
        <p className="text-xs text-fraco">
          Sem celular cadastrado? Peça ao gerente da sua empresa (ou ao seu gestor de conta) uma senha provisória.
        </p>
      </div>
    </Quadro>
  )
}

export function NovaSenha() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('t') ?? ''
  const [senha, setSenha] = useState('')
  const [outra, setOutra] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [pronto, setPronto] = useState(false)
  const [enviando, setEnviando] = useState(false)

  async function trocar(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    if (senha.length < 8) return setErro('A senha nova tem de ter 8 caracteres ou mais.')
    if (senha !== outra) return setErro('As duas senhas não são iguais.')
    setEnviando(true)
    try {
      await api.post('/api/v1/auth/senha/nova', { token, senha })
      setPronto(true)
      window.history.replaceState(null, '', window.location.pathname)   // o link sai do endereço (e do histórico)
    } catch (x) {
      setErro(mensagemDeErro(x))
    } finally {
      setEnviando(false)
    }
  }

  if (!token && !pronto) {
    return (
      <Quadro titulo="Nova senha">
        <div className="mt-4">
          <Aviso tom="parado">
            Este endereço está sem o link. Peça um novo: mande <b>esqueci a senha</b> ao WhatsApp do Gestão Solar.
          </Aviso>
        </div>
      </Quadro>
    )
  }
  return (
    <Quadro titulo="Nova senha">
      {pronto ? (
        <div className="mt-4">
          <Aviso tom="ok">
            Senha nova gravada. As sessões que estavam abertas foram encerradas: entre de novo com ela.
          </Aviso>
        </div>
      ) : (
        <form onSubmit={trocar} className="mt-4 grid gap-3">
          <label className="rotulo-campo" htmlFor="senha">
            Senha nova (8 caracteres ou mais)
          </label>
          <input id="senha" className="campo" type="password" value={senha} onChange={(e) => setSenha(e.target.value)}
                 autoComplete="new-password" autoFocus required />
          <label className="rotulo-campo" htmlFor="outra">
            A mesma senha, de novo
          </label>
          <input id="outra" className="campo" type="password" value={outra} onChange={(e) => setOutra(e.target.value)}
                 autoComplete="new-password" required />
          {erro ? <Aviso tom="parado">{erro}</Aviso> : null}
          <button type="submit" className="btn-primario" disabled={enviando}>
            {enviando ? 'Gravando…' : 'Gravar a senha nova'}
          </button>
        </form>
      )}
    </Quadro>
  )
}
