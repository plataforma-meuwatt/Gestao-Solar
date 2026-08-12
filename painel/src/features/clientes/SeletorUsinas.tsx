/**
 * Escolha das usinas de um cliente.
 *
 * Um componente só, usado no cadastro e na edição depois: são a mesma decisão, e duas
 * telas parecidas divergiriam na primeira mudança de regra. As usinas de outro cliente
 * aparecem desabilitadas com o nome do dono — esconder faria o gestor procurar uma usina
 * que existe e não entender por que sumiu.
 */

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Aviso, Carregando, Selo } from '@/components/base'
import { usinasSugeridas } from '@/features/api'

export function useSelecaoUsinas(clienteId: number, jaConcedidas?: number[]) {
  const [escolhidas, setEscolhidas] = useState<Set<number> | null>(null)

  const consulta = useQuery({
    queryKey: ['usinas-sugeridas', clienteId],
    queryFn: () => usinasSugeridas(clienteId),
  })

  useEffect(() => {
    if (!consulta.data || escolhidas !== null) return
    // Na edição parte do que o cliente já tem; no cadastro, do que os produtos indicam.
    setEscolhidas(
      new Set(
        jaConcedidas ??
          consulta.data
            .filter((u) => u.origem.length > 0 && !u.dono_atual)
            .map((u) => u.plant_link_id),
      ),
    )
  }, [consulta.data, escolhidas, jaConcedidas])

  function alternar(id: number) {
    setEscolhidas((atual) => {
      const novo = new Set(atual ?? [])
      if (novo.has(id)) novo.delete(id)
      else novo.add(id)
      return novo
    })
  }

  return { consulta, escolhidas: escolhidas ?? new Set<number>(), alternar }
}

export function ListaDeUsinas({
  consulta,
  escolhidas,
  alternar,
}: ReturnType<typeof useSelecaoUsinas>) {
  if (consulta.isPending) return <Carregando texto="Consultando as plataformas…" />

  if (consulta.data && consulta.data.length === 0) {
    return (
      <Aviso>
        Nenhuma usina cadastrada ainda. As usinas aparecem aqui depois de configurar a
        conexão com o meuWatt — veja as telas Conexões e Usinas.
      </Aviso>
    )
  }

  const semIndicacao = consulta.data?.every((u) => u.origem.length === 0)

  return (
    <div className="flex flex-col gap-2">
      {semIndicacao ? (
        <div className="mb-1">
          <Aviso>
            Nenhuma plataforma indicou usinas para este cliente — ou ele ainda não foi
            vinculado, ou a conta dele lá não tem usinas. Você pode conceder à mão do mesmo
            jeito.
          </Aviso>
        </div>
      ) : null}

      {(consulta.data ?? []).map((u) => {
        const bloqueada = !!u.dono_atual
        const marcada = escolhidas.has(u.plant_link_id)
        return (
          <label
            key={u.plant_link_id}
            className={`flex items-center gap-3 rounded-campo border px-4 py-3
              ${
                bloqueada
                  ? 'border-borda opacity-60 cursor-not-allowed'
                  : marcada
                    ? 'border-ambar/40 bg-ambar/5 cursor-pointer'
                    : 'border-borda hover:border-borda-forte cursor-pointer'
              }`}
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
  )
}
