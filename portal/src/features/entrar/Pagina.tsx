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
import { LockupGS } from '@/components/marca'
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
    <div className="relative grid min-h-full grid-cols-1 lg:grid-cols-[minmax(0,1.05fr)_520px]">
      {/*
        O halo é ÂMBAR e nasce no canto superior esquerdo — no lugar do azul central herdado
        do rebrand do meuWatt. É a única mudança de fundo do sistema, e vale só nesta tela:
        é aqui que a marca se apresenta, e um halo azul atrás de um selo âmbar dizia que o
        produto é de outra família. O `bg-fundo` opaco é obrigatório: o `body` tem o halo
        azul global desenhado por baixo, e sem cobri-lo os dois se somariam.
      */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-fundo"
        style={{
          backgroundImage:
            'radial-gradient(120% 90% at 12% 0%, rgba(255,195,21,.08), transparent 62%)',
        }}
      />

      {/* A metade da marca. Some no celular: ali a tela é o formulário, e uma frase de
          produto acima dele empurraria os campos para fora da primeira dobra. */}
      <div className="relative z-10 hidden flex-col justify-between p-12 lg:flex">
        <LockupGS tamanho={56} descritor="carteira · geração · manutenção" />

        <div className="max-w-[560px]">
          <h1 className="text-[40px] font-semibold leading-[1.15] tracking-[-0.03em] text-forte">
            Uma conta, uma lista de usinas, os dois produtos por baixo
          </h1>
          <p className="mt-5 text-[calc(15px_+_var(--passo-tipo))] leading-relaxed text-corpo">
            O monitoramento da geração e a gestão da manutenção continuam onde sempre
            estiveram. O Gestão Solar se conecta aos dois com um token que o seu gestor de
            conta gera, e que pode ser revogado a qualquer momento — do lado de lá, não daqui.
          </p>
        </div>

        <p className="text-xs text-fraco">
          Gestão Solar · o portal do proprietário de usina fotovoltaica
        </p>
      </div>

      {/* A metade do formulário. */}
      <div className="relative z-10 grid place-items-center border-borda px-5 py-10 lg:border-l lg:bg-superficie">
        <div className="w-full max-w-[380px]">
          {/* No celular a marca não tem coluna própria: ela vem aqui, acima do formulário. */}
          <div className="mb-8 lg:hidden">
            <LockupGS tamanho={44} />
          </div>

          <h2 className="text-[calc(22px_+_var(--passo-tipo))] font-semibold tracking-[-0.02em] text-forte">Entrar</h2>
          <p className="mt-1 text-sm text-fraco">Use a conta que o seu gestor criou para você.</p>

          <form onSubmit={enviar} className="mt-7 flex flex-col gap-4">
            {/* `role="alert"` porque a recusa chega depois do envio: sem isso, quem usa
                leitor de tela fica esperando uma resposta que já está escrita na tela. */}
            {erro ? (
              <div role="alert">
                <Aviso tom="parado">{erro}</Aviso>
              </div>
            ) : null}

            {/*
              O PRIMEIRO CAMPO É O APELIDO, e não o e-mail. A identidade de uma conta aqui é
              o apelido (`bff/app/core/apelido.py`); o e-mail é contato, opcional e não
              único — a MESMA pessoa pode ter duas contas, uma de gestor e uma de dono de
              usina, com o mesmo e-mail. Um campo "E-mail" no topo convidaria a tentar
              entrar com ele, que é exatamente o que não funciona.
            */}
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
            <p className="-mt-2 text-xs text-fraco">
              Minúsculas, sem acento, um separador por vez — <span className="mono">ponto</span> ou{' '}
              <span className="mono">hífen</span>.
            </p>

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
            <button type="submit" className="btn-primario mt-1 h-[46px]" disabled={!podeEnviar}>
              {entrando ? 'Entrando…' : 'Entrar'}
            </button>
          </form>

          <div className="mt-8 space-y-2 border-t border-borda pt-5 text-xs leading-relaxed text-fraco">
            <p>
              Esqueceu a senha? Peça uma senha provisória ao seu gestor de conta — ela é gerada
              na hora, e o portal pede a troca no primeiro acesso.
            </p>
            <p>
              A senha provisória é entregue junto com o apelido. Não há autoatendimento de
              senha neste portal.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
