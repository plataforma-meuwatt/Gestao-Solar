/**
 * Usinas — o inventário da plataforma, por empresa. Só leitura.
 *
 * Trazer a usina do meuWatt e do meuPlano, casar uma com a outra, ligar no aplicativo e
 * conceder ao dono é trabalho do GERENTE da empresa, no oem-gs — com a conta da empresa
 * nos produtos. A plataforma não tem token (regra do dono, 23/10/2026) e não lê produto
 * nenhum: aqui ela vê o que existe no Gestão Solar, de qual empresa é e de quem.
 */

import { useQuery } from '@tanstack/react-query'
import { Building2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio } from '@/components/base'
import { usinasDaPlataforma, type UsinaDaPlataforma } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Usinas() {
  const { data, isLoading, error } = useQuery({ queryKey: ['usinas-plataforma'], queryFn: usinasDaPlataforma })
  const [busca, setBusca] = useState('')

  const grupos = useMemo(() => {
    const t = busca.trim().toLowerCase()
    const mapa = new Map<string, UsinaDaPlataforma[]>()
    for (const u of data ?? []) {
      if (t && !`${u.nome} ${u.cidade ?? ''} ${u.dono_nome ?? ''} ${u.empresa ?? ''}`.toLowerCase().includes(t)) continue
      const chave = u.empresa ?? 'Sem empresa'
      mapa.set(chave, [...(mapa.get(chave) ?? []), u])
    }
    return [...mapa.entries()].sort(([a], [b]) => (a === 'Sem empresa' ? 1 : b === 'Sem empresa' ? -1 : a.localeCompare(b)))
  }, [data, busca])

  return (
    <Pagina
      titulo="Usinas"
      apoio="Todas as usinas do Gestão Solar, por empresa, e de quem é cada uma. Trazer, casar, ligar e conceder usina é do gerente da empresa, no oem-gs."
    >
      <input
        className="campo mb-4"
        placeholder="buscar usina, cidade, dono ou empresa"
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
        aria-label="Buscar usinas"
      />
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : !grupos.length ? (
        <Cartao>
          <Vazio titulo={data?.length ? 'Nada com essa busca' : 'Nenhuma usina ainda'} />
        </Cartao>
      ) : (
        <div className="grid gap-5">
          {grupos.map(([empresa, usinas]) => (
            <Cartao key={empresa} titulo={`${empresa} · ${usinas.length}`}>
              {empresa === 'Sem empresa' ? (
                <p className="px-5 pb-3 text-xs text-alerta flex items-center gap-1.5">
                  <Building2 size={13} />
                  De antes do multiempresa: nenhuma empresa a opera ainda.
                </p>
              ) : null}
              {usinas.map((u, i) => (
                <div key={u.id} className={`px-5 py-3 flex items-center gap-4 ${i ? 'border-t border-borda' : ''}`}>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-forte">{u.nome}</p>
                    <p className="text-xs text-fraco">
                      {[u.cidade, u.uf].filter(Boolean).join(' · ') || 'sem cidade'}
                      {u.kwp !== null ? ` · ${u.kwp.toLocaleString('pt-BR')} kWp` : ''}
                      {` · dono: ${u.dono_nome ?? 'ninguém ainda'}`}
                    </p>
                  </div>
                  <span className="text-xs text-rotulo hidden sm:block">
                    {[u.tem_meuwatt ? 'monitorada' : null, u.tem_meuplano ? 'com manutenção' : null]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  <Selo tom={u.no_app ? 'ok' : 'sem-dados'}>{u.no_app ? 'No app' : 'Desligada'}</Selo>
                </div>
              ))}
            </Cartao>
          ))}
        </div>
      )}
    </Pagina>
  )
}
