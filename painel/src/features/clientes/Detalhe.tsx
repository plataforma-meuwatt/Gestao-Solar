import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, KeyRound, Link2Off, Power, Stethoscope } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio, type Tom } from '@/components/base'
import {
  desvincular,
  editarCliente,
  obterCliente,
  regenerarSenha,
  type Produto,
  type SituacaoAcesso,
} from '@/features/api'
import { SenhaProvisoria } from '@/features/clientes/SenhaProvisoria'
import { mensagemDeErro } from '@/lib/api'

const ACESSO: Record<SituacaoAcesso, { tom: Tom; rotulo: string }> = {
  nunca: { tom: 'sem-dados', rotulo: 'Sem acesso' },
  entregue: { tom: 'alerta', rotulo: 'Entregue, não usado' },
  usado: { tom: 'ok', rotulo: 'Em uso' },
}

const NOME_PRODUTO: Record<Produto, string> = { meuwatt: 'meuWatt', meuplano: 'meuPlano' }

export function DetalheCliente() {
  const { id } = useParams<{ id: string }>()
  const clienteId = Number(id)
  const qc = useQueryClient()

  const [erro, setErro] = useState('')
  const [senha, setSenha] = useState<string | null>(null)

  const { data: cliente, isLoading } = useQuery({
    queryKey: ['cliente', clienteId],
    queryFn: () => obterCliente(clienteId),
  })

  const recarregar = () => {
    qc.invalidateQueries({ queryKey: ['cliente', clienteId] })
    qc.invalidateQueries({ queryKey: ['clientes'] })
  }

  const novaSenha = useMutation({
    mutationFn: () => regenerarSenha(clienteId),
    onSuccess: (r) => {
      setSenha(r.senha_provisoria)
      recarregar()
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const alternarAtivo = useMutation({
    mutationFn: () => editarCliente(clienteId, { ativo: !cliente!.ativo }),
    onSuccess: recarregar,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const removerVinculo = useMutation({
    mutationFn: (produto: Produto) => desvincular(clienteId, produto),
    onSuccess: recarregar,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  if (isLoading) return <Carregando />
  if (!cliente) return <Erro>Cliente não encontrado.</Erro>

  const acesso = ACESSO[cliente.acesso]

  return (
    <Pagina
      titulo={cliente.nome}
      apoio={cliente.empresa ?? undefined}
      acao={
        <Link to={`/diagnostico?cliente=${cliente.id}`} className="btn-secundario">
          <Stethoscope size={15} />
          Diagnóstico
        </Link>
      }
    >
      <Link to="/clientes" className="inline-flex items-center gap-1.5 text-sm text-rotulo hover:text-forte mb-5">
        <ArrowLeft size={14} />
        Todos os clientes
      </Link>

      {erro ? <Erro className="mb-4">{erro}</Erro> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Cartao titulo="Conta">
          <dl className="px-5 pb-5 flex flex-col gap-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">E-mail</dt>
              <dd className="mono text-corpo truncate">{cliente.email}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">Situação</dt>
              <dd>{cliente.ativo ? <Selo tom="ok">Ativo</Selo> : <Selo tom="sem-dados">Desativado</Selo>}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">Acesso</dt>
              <dd><Selo tom={acesso.tom}>{acesso.rotulo}</Selo></dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">Último acesso</dt>
              <dd className="mono text-corpo">
                {cliente.ultimo_login
                  ? new Date(cliente.ultimo_login).toLocaleString('pt-BR', {
                      dateStyle: 'short',
                      timeStyle: 'short',
                    })
                  : 'nunca'}
              </dd>
            </div>
          </dl>

          <div className="px-5 pb-5 flex gap-2 flex-wrap">
            <button onClick={() => novaSenha.mutate()} className="btn-secundario" disabled={novaSenha.isPending}>
              <KeyRound size={15} />
              {novaSenha.isPending ? 'Gerando…' : 'Gerar nova senha'}
            </button>
            <button onClick={() => alternarAtivo.mutate()} className="btn-fantasma h-11 px-4 text-sm">
              <Power size={14} />
              {cliente.ativo ? 'Desativar' : 'Reativar'}
            </button>
          </div>
        </Cartao>

        <Cartao titulo="Plataformas vinculadas">
          {cliente.vinculos.length === 0 ? (
            <Vazio
              titulo="Nenhuma plataforma vinculada"
              descricao="Sem vínculo, o aplicativo abre vazio para este cliente."
            />
          ) : (
            cliente.vinculos.map((v, i) => (
              <div
                key={v.produto}
                className={`flex items-center gap-3 px-5 py-4 ${i ? 'border-t border-borda' : ''}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-forte">{NOME_PRODUTO[v.produto]}</p>
                  <p className="mono text-xs text-fraco truncate">
                    {v.nome ? `${v.nome} · ` : ''}
                    {v.email ?? `id ${v.usuario_remoto_id}`}
                  </p>
                </div>
                <button
                  onClick={() => removerVinculo.mutate(v.produto)}
                  className="btn-fantasma"
                  title="Desvincular esta conta"
                >
                  <Link2Off size={13} />
                  Desvincular
                </button>
              </div>
            ))
          )}
        </Cartao>

        <Cartao titulo={`Usinas · ${cliente.usinas.length}`} className="lg:col-span-2">
          {cliente.usinas.length === 0 ? (
            <Vazio
              titulo="Nenhuma usina concedida"
              descricao="O cliente entra no aplicativo, mas não vê usina nenhuma até você conceder."
            />
          ) : (
            cliente.usinas.map((u, i) => (
              <div
                key={u.plant_link_id}
                className={`flex items-center gap-4 px-5 py-3.5 ${i ? 'border-t border-borda' : ''}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-forte">{u.nome}</p>
                  {u.cidade ? (
                    <p className="text-xs text-fraco">
                      {u.cidade}
                      {u.uf ? `, ${u.uf}` : ''}
                    </p>
                  ) : null}
                </div>
                <div className="flex gap-1.5">
                  {u.tem_meuwatt ? <Selo tom="ok">meuWatt</Selo> : null}
                  {u.tem_meuplano ? <Selo tom="ok">meuPlano</Selo> : null}
                  {!u.tem_meuwatt || !u.tem_meuplano ? (
                    <Selo tom="alerta">só um lado</Selo>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </Cartao>
      </div>

      {senha ? (
        <SenhaProvisoria
          nome={cliente.nome}
          email={cliente.email}
          senha={senha}
          aoFechar={() => setSenha(null)}
        />
      ) : null}
    </Pagina>
  )
}
