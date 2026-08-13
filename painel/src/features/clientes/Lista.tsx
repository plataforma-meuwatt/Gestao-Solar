import { useQuery } from '@tanstack/react-query'
import { Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio, type Tom } from '@/components/base'
import { listarClientes, type ClienteResumo, type SituacaoAcesso } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

/** O que a coluna Acesso diz, e por quê. */
const ACESSO: Record<SituacaoAcesso, { tom: Tom; rotulo: string; ajuda: string }> = {
  nunca: { tom: 'sem-dados', rotulo: 'Sem acesso', ajuda: 'Nenhuma senha foi gerada ainda' },
  entregue: { tom: 'alerta', rotulo: 'Entregue', ajuda: 'Senha gerada, o cliente ainda não entrou' },
  usado: { tom: 'ok', rotulo: 'Em uso', ajuda: 'O cliente já entrou com a senha' },
}

export function ListaClientes() {
  const [busca, setBusca] = useState('')
  const { data, isLoading, error } = useQuery({
    queryKey: ['clientes'],
    queryFn: listarClientes,
  })

  const filtrados = useMemo(() => {
    const termo = busca.trim().toLowerCase()
    if (!termo || !data) return data ?? []
    return data.filter(
      (c) =>
        c.nome.toLowerCase().includes(termo) ||
        c.apelido.includes(termo) ||
        (c.email ?? '').toLowerCase().includes(termo) ||
        (c.empresa ?? '').toLowerCase().includes(termo),
    )
  }, [data, busca])

  return (
    <Pagina
      titulo="Clientes"
      apoio="Quem acessa o aplicativo Gestão Solar. Cada cliente vê apenas as usinas vinculadas a ele."
      acao={
        <Link to="/clientes/novo" className="btn-primario">
          <Plus size={16} />
          Novo cliente
        </Link>
      }
    >
      {error ? <Erro className="mb-4">{mensagemDeErro(error)}</Erro> : null}

      {data && data.length > 0 ? (
        <div className="relative mb-4">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-fraco" />
          <input
            className="campo pl-10"
            placeholder="Buscar por nome, e-mail ou empresa"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            aria-label="Buscar clientes"
          />
        </div>
      ) : null}

      <Cartao>
        {isLoading ? <Carregando /> : null}

        {data && data.length === 0 ? (
          <Vazio
            titulo="Nenhum cliente ainda"
            descricao="Cadastre o primeiro cliente para ele acessar o aplicativo e ver as usinas dele."
            acao={
              <Link to="/clientes/novo" className="btn-primario">
                <Plus size={16} />
                Novo cliente
              </Link>
            }
          />
        ) : null}

        {data && data.length > 0 && filtrados.length === 0 ? (
          <Vazio
            titulo="Nenhum cliente encontrado"
            descricao={`Nada corresponde a “${busca}”. Tente outro termo.`}
          />
        ) : null}

        {filtrados.map((c, i) => (
          <LinhaCliente key={c.id} cliente={c} primeiro={i === 0} />
        ))}
      </Cartao>
    </Pagina>
  )
}

function LinhaCliente({ cliente, primeiro }: { cliente: ClienteResumo; primeiro: boolean }) {
  const acesso = ACESSO[cliente.acesso]
  return (
    <Link
      to={`/clientes/${cliente.id}`}
      className={`flex items-center gap-4 px-5 py-4 hover:bg-superficie transition-colors
                  ${primeiro ? '' : 'border-t border-borda'}`}
    >
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-forte truncate">
          {cliente.nome}
          {!cliente.ativo ? <span className="text-fraco font-normal"> · desativado</span> : null}
        </p>
        <p className="text-xs text-fraco truncate">
          <span className="mono">{cliente.apelido}</span>
          {cliente.empresa ? ` · ${cliente.empresa}` : ''}
        </p>
      </div>

      <div className="hidden sm:flex items-center gap-1.5 text-[11px]">
        {cliente.produtos.length === 0 ? (
          <span className="text-fraco">sem plataforma</span>
        ) : (
          cliente.produtos.map((p) => (
            <span key={p} className="rounded-campo border border-borda px-2 py-0.5 text-rotulo">
              {p === 'meuwatt' ? 'meuWatt' : 'meuPlano'}
            </span>
          ))
        )}
      </div>

      <p className="mono text-sm text-rotulo w-20 text-right hidden sm:block">
        {cliente.usinas} {cliente.usinas === 1 ? 'usina' : 'usinas'}
      </p>

      <span title={acesso.ajuda}>
        <Selo tom={acesso.tom}>{acesso.rotulo}</Selo>
      </span>
    </Link>
  )
}
