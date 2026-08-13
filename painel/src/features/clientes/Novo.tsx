/**
 * Cadastro de cliente em quatro passos.
 *
 * A ordem não é arbitrária: só depois de existir o cliente dá para vincular as contas
 * dele, e só depois dos vínculos o BFF sabe sugerir quais usinas ele vê. Cada passo
 * salva ao avançar — se o gestor fechar no meio, o cliente já existe e a lista mostra o
 * que falta, em vez de perder tudo.
 *
 * Os passos 2 e 3 podem ser pulados: quem contratou só um produto vincula só um.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, Search } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Aviso, Campo, Cartao, Erro, Pagina, Passos } from '@/components/base'
import {
  criarCliente,
  definirUsinas,
  procurarUsuario,
  vincular,
  type Produto,
  type UsuarioRemoto,
} from '@/features/api'
import { SenhaProvisoria } from '@/features/clientes/SenhaProvisoria'
import { ListaDeUsinas, useSelecaoUsinas } from '@/features/clientes/SeletorUsinas'
import { mensagemDeErro } from '@/lib/api'

const NOMES_PASSOS = ['Dados', 'meuWatt', 'meuPlano', 'Usinas']

/**
 * Um apelido plausível a partir do e-mail, só para o campo já nascer preenchido.
 *
 * Espelha `core/apelido.sugerir` do BFF. A cópia é aceitável porque é sugestão, não
 * validação: quem recusa um apelido inválido é o servidor, num lugar só. Se as duas
 * divergirem, o pior que acontece é a tela propor algo que o gestor corrige antes de
 * salvar.
 */
function sugerirApelido(email: string): string {
  return email
    .trim()
    .toLowerCase()
    .split('@')[0]
    .replace(/[\s_]+/g, '.')
    .replace(/[^a-z0-9._-]/g, '')
    .replace(/[._-]{2,}/g, '.')
    .replace(/^[._-]+|[._-]+$/g, '')
    .slice(0, 32)
}

export function NovoCliente() {
  const navegar = useNavigate()
  const qc = useQueryClient()

  const [passo, setPasso] = useState(0)
  const [erro, setErro] = useState('')

  const [nome, setNome] = useState('')
  const [apelido, setApelido] = useState('')
  // Enquanto o gestor não digitar um apelido próprio, ele acompanha o e-mail. Quem edita
  // o campo assume o controle — daí o sinalizador, e não uma comparação de valores: sem
  // ele, apagar o apelido para reescrevê-lo faria a sugestão voltar por cima.
  const [apelidoManual, setApelidoManual] = useState(false)
  const [email, setEmail] = useState('')
  const [empresa, setEmpresa] = useState('')

  const [clienteId, setClienteId] = useState<number | null>(null)
  const [senha, setSenha] = useState<string | null>(null)

  const criar = useMutation({
    mutationFn: () =>
      criarCliente({ nome, apelido, email: email || null, empresa: empresa || null }),
    onSuccess: (r) => {
      setClienteId(r.id)
      setSenha(r.senha_provisoria)
      setPasso(1)
      qc.invalidateQueries({ queryKey: ['clientes'] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  function avancarDados(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    // Já existe? O passo 1 não repete — o cliente foi criado uma vez só.
    if (clienteId) return setPasso(1)
    criar.mutate()
  }

  return (
    <Pagina titulo="Novo cliente" apoio="Cadastre, vincule as plataformas e entregue o acesso.">
      <Passos atual={passo} nomes={NOMES_PASSOS} />

      {erro ? <Erro className="mb-4">{erro}</Erro> : null}

      {passo === 0 ? (
        <Cartao className="p-5">
          <form onSubmit={avancarDados} className="flex flex-col gap-4 max-w-md">
            <Campo
              rotulo="Nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Renan Moraes"
              required
              autoFocus
              disabled={!!clienteId}
            />
            <Campo
              rotulo="E-mail"
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value)
                if (!apelidoManual) setApelido(sugerirApelido(e.target.value))
              }}
              placeholder="renan@solaris.com.br"
              nota="Serve para achar a conta dele no meuWatt e no meuPlano. Não é com ele que entra."
              disabled={!!clienteId}
            />
            <Campo
              rotulo="Apelido"
              value={apelido}
              onChange={(e) => {
                setApelidoManual(true)
                setApelido(e.target.value.toLowerCase())
              }}
              placeholder="renan.marquezini"
              nota="É com este apelido que ele entra no aplicativo."
              autoCapitalize="none"
              spellCheck={false}
              required
              disabled={!!clienteId}
            />
            <Campo
              rotulo="Empresa"
              value={empresa}
              onChange={(e) => setEmpresa(e.target.value)}
              placeholder="Solaris Energia (opcional)"
              disabled={!!clienteId}
            />
            <div className="flex gap-2">
              <button type="submit" className="btn-primario" disabled={criar.isPending}>
                {criar.isPending ? 'Criando…' : clienteId ? 'Continuar' : 'Criar e continuar'}
                <ArrowRight size={15} />
              </button>
              <button
                type="button"
                onClick={() => navegar('/clientes')}
                className="btn-secundario"
              >
                Cancelar
              </button>
            </div>
          </form>
        </Cartao>
      ) : null}

      {passo === 1 && clienteId ? (
        <PassoVinculo
          produto="meuwatt"
          clienteId={clienteId}
          email={email}
          aoConcluir={() => setPasso(2)}
          aoVoltar={() => setPasso(0)}
        />
      ) : null}

      {passo === 2 && clienteId ? (
        <PassoVinculo
          produto="meuplano"
          clienteId={clienteId}
          email={email}
          aoConcluir={() => setPasso(3)}
          aoVoltar={() => setPasso(1)}
        />
      ) : null}

      {passo === 3 && clienteId ? (
        <PassoUsinas
          clienteId={clienteId}
          aoVoltar={() => setPasso(2)}
          aoConcluir={() => navegar(`/clientes/${clienteId}`)}
        />
      ) : null}

      {senha && passo > 0 ? (
        <SenhaProvisoria
          nome={nome}
          apelido={apelido}
          senha={senha}
          aoFechar={() => setSenha(null)}
        />
      ) : null}
    </Pagina>
  )
}

/* ---------------------------------------------------------------- vínculo */

const ROTULO: Record<Produto, { nome: string; oQueTraz: string }> = {
  meuwatt: { nome: 'meuWatt', oQueTraz: 'geração, inversores e relatórios' },
  meuplano: { nome: 'meuPlano', oQueTraz: 'cronograma, ordens de serviço e assistente' },
}

function PassoVinculo({
  produto,
  clienteId,
  email,
  aoConcluir,
  aoVoltar,
}: {
  produto: Produto
  clienteId: number
  email: string
  aoConcluir: () => void
  aoVoltar: () => void
}) {
  const [busca, setBusca] = useState(email)
  const [achado, setAchado] = useState<UsuarioRemoto | null | undefined>(undefined)
  const [erro, setErro] = useState('')

  const procurar = useMutation({
    mutationFn: () => procurarUsuario(produto, busca.trim()),
    onSuccess: (r) => {
      setAchado(r)
      setErro('')
    },
    onError: (e) => {
      setErro(mensagemDeErro(e))
      setAchado(undefined)
    },
  })

  const salvar = useMutation({
    mutationFn: () =>
      vincular(clienteId, produto, {
        usuario_remoto_id: achado!.id,
        email: achado!.email,
        nome: achado!.nome,
      }),
    onSuccess: aoConcluir,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const { nome, oQueTraz } = ROTULO[produto]

  return (
    <Cartao className="p-5 max-w-2xl">
      <h2 className="text-lg font-semibold text-forte">Conta no {nome}</h2>
      <p className="text-sm text-rotulo mt-1">
        Qual conta deste cliente no {nome}? É dela que vêm {oQueTraz}.
      </p>

      {erro ? <Erro className="mt-4">{erro}</Erro> : null}

      <div className="flex gap-2 items-end mt-4">
        <div className="flex-1">
          <Campo
            rotulo={`E-mail no ${nome}`}
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && procurar.mutate()}
          />
        </div>
        <button
          onClick={() => procurar.mutate()}
          className="btn-secundario"
          disabled={procurar.isPending || !busca.trim()}
        >
          <Search size={15} />
          {procurar.isPending ? 'Procurando…' : 'Procurar'}
        </button>
      </div>

      {achado === null ? (
        <div className="mt-4">
          <Aviso>
            Nenhuma conta com este e-mail no {nome}. Você pode seguir sem vincular — a aba
            correspondente ficará vazia no aplicativo até que a conta exista e seja vinculada
            aqui.
          </Aviso>
        </div>
      ) : null}

      {achado ? (
        <div className="mt-4 rounded-campo border border-ok/30 bg-ok/10 p-4 flex items-center gap-3">
          <Check size={18} className="text-ok shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-forte">{achado.nome || 'Conta encontrada'}</p>
            <p className="mono text-xs text-rotulo truncate">
              {achado.email} · id {achado.id}
            </p>
          </div>
        </div>
      ) : null}

      <div className="flex gap-2 mt-5">
        <button onClick={aoVoltar} className="btn-secundario">
          <ArrowLeft size={15} />
          Voltar
        </button>
        {achado ? (
          <button onClick={() => salvar.mutate()} className="btn-primario" disabled={salvar.isPending}>
            {salvar.isPending ? 'Vinculando…' : 'Vincular e continuar'}
            <ArrowRight size={15} />
          </button>
        ) : (
          <button onClick={aoConcluir} className="btn-secundario">
            Pular este produto
            <ArrowRight size={15} />
          </button>
        )}
      </div>
    </Cartao>
  )
}

/* ----------------------------------------------------------------- usinas */

function PassoUsinas({
  clienteId,
  aoVoltar,
  aoConcluir,
}: {
  clienteId: number
  aoVoltar: () => void
  aoConcluir: () => void
}) {
  const [erro, setErro] = useState('')
  const selecao = useSelecaoUsinas(clienteId)

  const salvar = useMutation({
    mutationFn: () => definirUsinas(clienteId, [...selecao.escolhidas]),
    onSuccess: aoConcluir,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Cartao className="p-5 max-w-2xl">
      <h2 className="text-lg font-semibold text-forte">Usinas deste cliente</h2>
      <p className="text-sm text-rotulo mt-1">
        Marque o que ele vê no aplicativo. Já vem marcado o que as plataformas indicam.
      </p>

      {erro ? <Erro className="mt-4">{erro}</Erro> : null}

      <div className="mt-4">
        <ListaDeUsinas {...selecao} />
      </div>

      <div className="flex gap-2 mt-5">
        <button onClick={aoVoltar} className="btn-secundario">
          <ArrowLeft size={15} />
          Voltar
        </button>
        <button onClick={() => salvar.mutate()} className="btn-primario" disabled={salvar.isPending}>
          {salvar.isPending ? 'Salvando…' : 'Concluir cadastro'}
          <Check size={15} />
        </button>
      </div>
    </Cartao>
  )
}
