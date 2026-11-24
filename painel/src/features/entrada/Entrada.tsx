import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Campo, Erro } from '@/components/base'
import { baseDaApi, mensagemDeErro } from '@/lib/api'
import { TITULO } from '@/lib/portao'
import { useAuth, type DuasEtapas } from '@/store/auth'

export function Entrada() {
  const { token, entrar, entrarComCodigo } = useAuth()
  const navegar = useNavigate()
  const local = useLocation() as { state?: { de?: string } }

  const [apelido, setApelido] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState('')
  const [entrando, setEntrando] = useState(false)
  // a senha está certa e falta o código do autenticador (a verificação em duas etapas)
  const [etapa, setEtapa] = useState<DuasEtapas | null>(null)
  const [codigo, setCodigo] = useState('')

  // Sem destino pedido, vai para a RAIZ, onde o `Pouso` escolhe a primeira tela do portão
  // desta sessão. Era `/clientes` fixo: o gerente e o técnico entravam direto numa tela da
  // plataforma e liam "Área restrita" como a primeira coisa depois da senha certa.
  if (token) return <Navigate to={local.state?.de || '/'} replace />

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    setEntrando(true)
    try {
      if (etapa) {
        await entrarComCodigo(etapa.desafio, codigo)
        navegar(local.state?.de || '/', { replace: true })
        return
      }
      const pedido = await entrar(apelido.trim().toLowerCase(), senha)
      if (pedido) {
        setEtapa(pedido)
        setCodigo('')
        return
      }
      navegar(local.state?.de || '/', { replace: true })
    } catch (err) {
      // Os campos ficam como estão: refazer o apelido por causa de senha errada é o
      // atrito que faz alguém desistir na segunda tentativa.
      setErro(mensagemDeErro(err))
    } finally {
      setEntrando(false)
    }
  }

  return (
    <div className="min-h-full grid place-items-center px-4 py-8">
      <form onSubmit={enviar} className="w-full max-w-sm">
        <div className="text-center mb-7">
          <p className="text-3xl font-bold text-forte tracking-tight">
            Gestão <span className="text-ambar">Solar</span>
          </p>
          <p className="text-sm text-rotulo mt-1">{TITULO}</p>
        </div>

        <div className="cartao p-5 flex flex-col gap-4">
          {erro ? <Erro>{erro}</Erro> : null}

          {etapa ? (
            <>
              {etapa.cadastrar ? (
                <div className="grid gap-3">
                  <p className="text-sm text-forte font-semibold">Verificação em duas etapas</p>
                  <p className="text-sm text-rotulo">
                    Esta conta passa a pedir, além da senha, um código do celular. Abra o Google Authenticator
                    ou o Microsoft Authenticator, toque em + e leia este QR:
                  </p>
                  {etapa.qr ? (
                    <img
                      src={etapa.qr}
                      alt="QR code para cadastrar o Gestão Solar no autenticador"
                      className="mx-auto w-48 h-48 rounded bg-white p-1"
                    />
                  ) : null}
                  <p className="text-sm text-rotulo">
                    Sem câmera? Digite a chave no autenticador:{' '}
                    <span className="text-forte font-mono break-all">{etapa.segredo}</span>
                  </p>
                  {etapa.otpauth ? (
                    <a className="text-sm underline text-rotulo hover:text-forte" href={etapa.otpauth}>
                      No celular: abrir direto no autenticador
                    </a>
                  ) : null}
                  <p className="text-sm text-rotulo">Depois, digite aqui o código de 6 números que ele mostra.</p>
                </div>
              ) : (
                <p className="text-sm text-rotulo">
                  Digite o código de 6 números do autenticador do seu celular (Gestão Solar: {apelido}).
                </p>
              )}
              <Campo
                rotulo="Código do autenticador"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={codigo}
                onChange={(e) => setCodigo(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="000000"
                autoFocus
                required
              />
              <button type="submit" className="btn-primario" disabled={entrando || codigo.length !== 6}>
                {entrando ? 'Conferindo…' : 'Entrar'}
              </button>
              <button
                type="button"
                className="btn-fantasma"
                onClick={() => {
                  setEtapa(null)
                  setErro('')
                }}
              >
                Voltar
              </button>
              {!etapa.cadastrar ? (
                <p className="text-xs text-fraco">
                  Perdeu o celular? Peça ao gerente da sua empresa (ou a quem administra a plataforma) para refazer a
                  verificação em duas etapas da sua conta.
                </p>
              ) : null}
            </>
          ) : (
            <>
              <Campo
                rotulo="Login ou e-mail"
                autoComplete="username"
                // O apelido é sempre minúsculo. Corrigir a caixa aqui, e não só no envio,
                // evita a cena de digitar "Renan", ver "Renan" na tela e receber erro sem
                // entender o motivo.
                value={apelido}
                onChange={(e) => setApelido(e.target.value.toLowerCase())}
                autoCapitalize="none"
                spellCheck={false}
                placeholder="seu.login ou voce@empresa.com"
                autoFocus
                required
              />
              <Campo
                rotulo="Senha"
                type="password"
                autoComplete="current-password"
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                required
              />

              <button type="submit" className="btn-primario" disabled={entrando}>
                {entrando ? 'Entrando…' : 'Entrar'}
              </button>
              <EsqueciASenha />
            </>
          )}
        </div>
      </form>
    </div>
  )
}


/** O "esqueci a senha" (R12): pelo WhatsApp do GS, do celular cadastrado (o número vem da API, a rota é pública). */
function EsqueciASenha() {
  const { data } = useQuery({
    queryKey: ['senha', 'canais'],
    queryFn: () =>
      fetch(`${baseDaApi()}/api/v1/auth/senha/canais`).then((r) => (r.ok ? r.json() : null)) as Promise<{
        whatsapp: string | null
      } | null>,
    staleTime: 3_600_000,
  })
  return (
    <p className="text-xs text-fraco text-center">
      Esqueceu a senha? Do celular cadastrado, mande <b>esqueci a senha</b> ao WhatsApp do Gestão Solar
      {data?.whatsapp ? <span className="mono whitespace-nowrap"> {data.whatsapp}</span> : null}: o link para a senha
      nova chega na hora.
    </p>
  )
}
