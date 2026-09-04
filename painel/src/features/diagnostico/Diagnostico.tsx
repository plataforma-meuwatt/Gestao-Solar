/**
 * Responde "o dado está chegando certo dos dois lados?" sem abrir o aplicativo.
 *
 * Mostra o que o cliente veria e de onde cada número vem — o endpoint exato, para poder
 * conferir contra a tela do produto de origem. Cada lado falha sozinho: uma ponte fora não
 * esconde a outra.
 */

import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, XCircle } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio } from '@/components/base'
import { carregarDiagnostico, listarClientes, type BlocoDiagnostico } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Diagnostico() {
  const [params, setParams] = useSearchParams()
  const clienteId = Number(params.get('cliente')) || null

  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: listarClientes })

  const {
    data: diag,
    isFetching,
    error,
  } = useQuery({
    queryKey: ['diagnostico', clienteId],
    queryFn: () => carregarDiagnostico(clienteId!),
    enabled: !!clienteId,
  })

  return (
    <Pagina
      titulo="Diagnóstico"
      apoio="Confira o que o cliente recebe, e de onde cada número vem, antes de ele abrir o aplicativo."
    >
      <div className="mb-5 max-w-md">
        <label className="rotulo-campo" htmlFor="cliente">
          Cliente
        </label>
        <select
          id="cliente"
          className="campo"
          value={clienteId ?? ''}
          onChange={(e) => setParams(e.target.value ? { cliente: e.target.value } : {})}
        >
          <option value="">— escolha um cliente —</option>
          {(clientes ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.nome}
              {c.empresa ? ` · ${c.empresa}` : ''}
            </option>
          ))}
        </select>
      </div>

      {!clienteId ? (
        <Cartao>
          <Vazio
            titulo="Escolha um cliente"
            descricao="O diagnóstico consulta as duas plataformas com as usinas daquele cliente e mostra o que voltou."
          />
        </Cartao>
      ) : null}

      {error ? <Erro>{mensagemDeErro(error)}</Erro> : null}
      {clienteId && isFetching ? <Carregando texto="Consultando as duas plataformas…" /> : null}

      {diag ? (
        <div className="flex flex-col gap-4">
          <Cartao titulo={`Usinas que ${diag.cliente} vê · ${diag.usinas.length}`}>
            {diag.usinas.length === 0 ? (
              <Vazio
                titulo="Nenhuma usina concedida"
                descricao="Este cliente entra no aplicativo e não vê usina nenhuma. Conceda usinas na tela dele."
              />
            ) : (
              diag.usinas.map((u, i) => (
                <div
                  key={u.plant_link_id}
                  className={`flex items-center gap-3 px-5 py-3 ${i ? 'border-t border-borda' : ''}`}
                >
                  <p className="text-sm text-forte flex-1 truncate">{u.nome}</p>
                  {u.tem_meuwatt ? <Selo tom="ok">meuWatt</Selo> : null}
                  {u.tem_meuplano ? <Selo tom="ok">meuPlano</Selo> : null}
                </div>
              ))
            )}
          </Cartao>

          <Bloco titulo="meuWatt — geração" bloco={diag.meuwatt} />
          <Bloco titulo="meuPlano — manutenção" bloco={diag.meuplano} />
          {diag.manutencao ? (
            <Bloco titulo="Portal do cliente — cronograma do contrato" bloco={diag.manutencao} />
          ) : null}
        </div>
      ) : null}
    </Pagina>
  )
}

function Bloco({ titulo, bloco }: { titulo: string; bloco: BlocoDiagnostico }) {
  return (
    <Cartao>
      <header className="flex items-center gap-2.5 px-5 pt-4 pb-3">
        {bloco.ok ? (
          <CheckCircle2 size={16} className="text-ok" />
        ) : (
          <XCircle size={16} className="text-parado" />
        )}
        <h2 className="text-sm font-semibold text-forte">{titulo}</h2>
        <span className={`ml-auto text-xs ${bloco.ok ? 'text-ok' : 'text-parado'}`}>
          {bloco.detalhe}
        </span>
      </header>

      {bloco.itens.length === 0 ? null : (
        <div className="border-t border-borda">
          {bloco.itens.map((item, i) => (
            <ItemDiagnostico key={i} item={item} primeiro={i === 0} />
          ))}
        </div>
      )}
    </Cartao>
  )
}

function ItemDiagnostico({
  item,
  primeiro,
}: {
  item: Record<string, unknown>
  primeiro: boolean
}) {
  const { usina, origem, erro, ...resto } = item as Record<string, any>

  return (
    <div className={`px-5 py-3.5 ${primeiro ? '' : 'border-t border-borda'}`}>
      <div className="flex items-baseline gap-3">
        <p className="text-sm font-semibold text-forte">{String(usina)}</p>
        {origem ? <code className="mono text-[11px] text-fraco truncate">{String(origem)}</code> : null}
      </div>

      {erro ? (
        <p className="text-sm text-parado mt-1.5">{String(erro)}</p>
      ) : (
        <dl className="flex flex-wrap gap-x-6 gap-y-1 mt-2">
          {Object.entries(resto).map(([chave, valor]) => (
            <div key={chave} className="flex items-baseline gap-1.5">
              <dt className="text-xs text-rotulo">{chave.replace(/_/g, ' ')}</dt>
              <dd className="mono text-sm text-forte">
                {Array.isArray(valor)
                  ? valor.length
                    ? valor.join(', ')
                    : '—'
                  : valor === null || valor === undefined
                    ? '—'
                    : String(valor)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
