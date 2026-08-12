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
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Search } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Aviso, Campo, Cartao, Erro, Pagina, Passos, Selo } from '@/components/base'
import {
  criarCliente,
  definirUsinas,
  procurarUsuario,
  usinasSugeridas,
  vincular,
  type Produto,
  type UsinaSugerida,
  type UsuarioRemoto,
} from '@/features/api'
import { SenhaProvisoria } from '@/features/clientes/SenhaProvisoria'
import { mensagemDeErro } from '@/lib/api'

const NOMES_PASSOS = ['Dados', 'meuWatt', 'meuPlano', 'Usinas']

export function NovoCliente() {
  const navegar = useNavigate()
  const qc = useQueryClient()

  const [passo, setPasso] = useState(0)
  const [erro, setErro] = useState('')

  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [empresa, setEmpresa] = useState('')

  const [clienteId, setClienteId] = useState<number | null>(null)
  const [senha, setSenha] = useState<string | null>(null)

  const criar = useMutation({
    mutationFn: () => criarCliente({ nome, email, empresa: empresa || null }),
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
              onChange={(e) => setEmail(e.target.value)}
              placeholder="renan@solaris.com.br"
              nota="É com este e-mail que ele entra no aplicativo."
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
          email={email}
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
  const [escolhidas, setEscolhidas] = useState<Set<number> | null>(null)
  const [sugestoes, setSugestoes] = useState<UsinaSugerida[] | null>(null)

  const carregar = useMutation({
    mutationFn: () => usinasSugeridas(clienteId),
    onSuccess: (r) => {
      setSugestoes(r)
      // Já vem marcado o que os produtos indicam — o gestor tira, em vez de procurar.
      setEscolhidas(new Set(r.filter((u) => u.origem.length > 0 && !u.dono_atual).map((u) => u.plant_link_id)))
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const salvar = useMutation({
    mutationFn: () => definirUsinas(clienteId, [...(escolhidas ?? [])]),
    onSuccess: aoConcluir,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  if (sugestoes === null && !carregar.isPending && !carregar.isError) carregar.mutate()

  function alternar(id: number) {
    setEscolhidas((atual) => {
      const novo = new Set(atual ?? [])
      novo.has(id) ? novo.delete(id) : novo.add(id)
      return novo
    })
  }

  return (
    <Cartao className="p-5 max-w-2xl">
      <h2 className="text-lg font-semibold text-forte">Usinas deste cliente</h2>
      <p className="text-sm text-rotulo mt-1">
        Marque o que ele vê no aplicativo. Já vem marcado o que as plataformas indicam.
      </p>

      {erro ? <Erro className="mt-4">{erro}</Erro> : null}

      {carregar.isPending ? <p className="text-sm text-fraco py-6">Consultando as plataformas…</p> : null}

      {sugestoes && sugestoes.length === 0 ? (
        <div className="mt-4">
          <Aviso>
            Nenhuma usina para sugerir. Isso acontece quando o cliente não foi vinculado a
            nenhum produto, ou quando as usinas ainda não foram casadas entre as duas
            plataformas — veja a tela Usinas.
          </Aviso>
        </div>
      ) : null}

      <div className="mt-4 flex flex-col gap-2">
        {(sugestoes ?? []).map((u) => {
          const bloqueada = !!u.dono_atual
          const marcada = escolhidas?.has(u.plant_link_id) ?? false
          return (
            <label
              key={u.plant_link_id}
              className={`flex items-center gap-3 rounded-campo border px-4 py-3 cursor-pointer
                ${bloqueada ? 'border-borda opacity-60 cursor-not-allowed' : marcada ? 'border-ambar/40 bg-ambar/5' : 'border-borda hover:border-borda-forte'}`}
            >
              <input
                type="checkbox"
                className="accent-[#FFC315] w-4 h-4"
                checked={marcada}
                disabled={bloqueada}
                onChange={() => alternar(u.plant_link_id)}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-forte">{u.nome}</p>
                <p className="text-xs text-fraco">
                  {u.origem.length ? `indicada por ${u.origem.join(' e ')}` : 'sem indicação'}
                </p>
              </div>
              {bloqueada ? (
                <span className="flex items-center gap-1.5 text-[11px] text-alerta">
                  <AlertTriangle size={13} />
                  já é de {u.dono_atual}
                </span>
              ) : u.origem.length === 2 ? (
                <Selo tom="ok">nos dois</Selo>
              ) : null}
            </label>
          )
        })}
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
