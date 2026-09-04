/**
 * Entrar — Quem sou eu? (e como recupero o acesso se perdi a senha)
 *
 * A única tela do portal que vive FORA do casco (`App.tsx` a monta sem o `Layout`): sem
 * sessão não há usina em contexto, não há menu e não há para onde navegar. Por isso ela
 * desenha o próprio quadro, centrado, em vez de usar a `Pagina`.
 *
 * Três decisões que não devem ser desfeitas:
 *
 * **Quem loga é o store, não esta tela.** `useAuth.entrar` faz o `POST /api/v1/auth/login`,
 * grava a sessão, aponta o cache de leitura para a conta certa e limpa o que sobrou da conta
 * anterior. Uma segunda chamada de login escrita aqui seria uma porta paralela que esquece
 * metade disso — e o caso real é conhecido: gestor e dono no mesmo computador, as usinas de
 * quem saiu aparecendo para quem entrou.
 *
 * **A senha esquecida NÃO se resolve sozinha.** O BFF não envia e-mail (não há remetente do
 * lado do cliente): a senha provisória é gerada pelo gestor de conta, no painel de
 * administração. Escrever "Esqueci minha senha" com um link que não leva a lugar nenhum
 * seria pior que não escrever nada — então a tela DIZ o caminho verdadeiro. E não há link
 * para o painel: são dois sites, dois públicos, duas sessões.
 *
 * **O erro é o que o servidor disse.** `mensagemDeErro` (dentro do store) já achata o
 * `detail`, inclusive a lista do 422, numa frase; a tela não reescreve motivo de recusa —
 * um "usuário ou senha inválidos" inventado aqui esconderia "conta desativada", que é outra
 * conversa e outro telefonema.
 */

import { useEffect, useState, type InputHTMLAttributes } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Aviso } from '@/components/base'
import { useAuth } from '@/store/auth'

/** Campo de formulário — rótulo, `id` amarrado e as classes de `index.css`. */
function Campo({
  rotulo,
  id,
  ...resto
}: { rotulo: string; id: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label className="rotulo-campo" htmlFor={id}>
        {rotulo}
      </label>
      <input id={id} className="campo" {...resto} />
    </div>
  )
}

export default function Entrar() {
  const token = useAuth((s) => s.token)
  const entrando = useAuth((s) => s.entrando)
  const erro = useAuth((s) => s.erro)
  const entrar = useAuth((s) => s.entrar)

  const navegar = useNavigate()
  const local = useLocation() as { state?: { de?: string } }
  const destino = local.state?.de || '/'

  const [apelido, setApelido] = useState('')
  const [senha, setSenha] = useState('')

  // O título da aba diz onde a pessoa está antes de entrar — vale para quem deixa o portal
  // aberto ao lado das outras abas do trabalho.
  useEffect(() => {
    document.title = 'Entrar · Gestão Solar'
  }, [])

  // Já entrou (ou voltou para cá com a sessão viva): vai direto para onde queria ir. Um
  // token de OUTRO produto guardado no navegador não trava nada — o portal segue, o BFF
  // recusa a primeira leitura com 401 e o store derruba a sessão, devolvendo esta tela.
  if (token) return <Navigate to={destino} replace />

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    // O `entrar` do store devolve `false` e guarda o motivo em `erro`; os campos ficam como
    // estão, porque refazer o apelido por causa de senha errada é o atrito que faz alguém
    // desistir na segunda tentativa.
    const ok = await entrar(apelido, senha)
    if (ok) navegar(destino, { replace: true })
  }

  const podeEnviar = apelido.trim().length > 0 && senha.length > 0 && !entrando

  return (
    <div className="grid min-h-full place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-7 text-center">
          <p className="text-3xl font-bold tracking-tight text-forte">
            Gestão <span className="text-ambar">Solar</span>
          </p>
          <p className="mt-1 text-sm text-rotulo">A sua usina, em um lugar só</p>
        </div>

        <form onSubmit={enviar} className="cartao flex flex-col gap-4 p-5">
          {/* `role="alert"` porque a recusa chega depois do envio: sem isso, quem usa leitor
              de tela fica esperando uma resposta que já está escrita na tela. */}
          {erro ? (
            <div role="alert">
              <Aviso tom="parado">{erro}</Aviso>
            </div>
          ) : null}

          <Campo
            id="apelido"
            rotulo="Apelido"
            value={apelido}
            // A caixa é corrigida enquanto se digita, e não só no envio: ver "Renan" na
            // tela e receber erro sem entender o motivo é o pior dos dois mundos.
            onChange={(e) => setApelido(e.target.value.toLowerCase())}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder="seu.apelido"
            autoFocus
            required
          />

          <Campo
            id="senha"
            rotulo="Senha"
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            autoComplete="current-password"
            required
          />

          {/* `type="submit"`: o Enter em qualquer campo envia, que é como se entra num
              formulário de duas linhas sem tirar a mão do teclado. */}
          <button type="submit" className="btn-primario" disabled={!podeEnviar}>
            {entrando ? 'Entrando…' : 'Entrar'}
          </button>

          <p className="text-xs leading-relaxed text-fraco">
            Esqueceu a senha? Peça uma senha provisória ao seu gestor de conta — ela é gerada
            na hora, e o portal pede a troca no primeiro acesso.
          </p>
        </form>
      </div>
    </div>
  )
}
