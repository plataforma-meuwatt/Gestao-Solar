/**
 * As usinas dos dois sistemas, e qual é qual.
 *
 * A sugestão ordena; quem decide é o gestor. Um par errado mistura a geração de uma usina
 * com a manutenção de outra, e ninguém percebe até alguém questionar um relatório — por
 * isso nada aqui é automático.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Cartao, Carregando, Erro, Pagina, Vazio } from '@/components/base'
import { carregarConciliacao, vincularUsina, type Conciliacao } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Usinas() {
  const qc = useQueryClient()
  const [erro, setErro] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['conciliacao'],
    queryFn: carregarConciliacao,
  })

  const vincular = useMutation({
    mutationFn: (dados: Parameters<typeof vincularUsina>[0]) => vincularUsina(dados),
    onSuccess: () => {
      setErro('')
      qc.invalidateQueries({ queryKey: ['conciliacao'] })
    },
    onError: (e) => {
      setErro(mensagemDeErro(e))
      // Recarrega para o seletor voltar ao valor real do servidor, e não ficar mostrando
      // uma escolha que não foi gravada.
      qc.invalidateQueries({ queryKey: ['conciliacao'] })
    },
  })

  return (
    <Pagina
      titulo="Usinas"
      apoio="Qual usina do meuWatt corresponde a qual do meuPlano. Só depois de casadas o aplicativo consegue mostrar geração e manutenção da mesma usina."
    >
      {error ? <Erro className="mb-4">{mensagemDeErro(error)}</Erro> : null}
      {erro ? <Erro className="mb-4">{erro}</Erro> : null}
      {data?.aviso ? (
        <div className="mb-4">
          <Aviso>{data.aviso}</Aviso>
        </div>
      ) : null}

      <Cartao>
        {isLoading ? <Carregando texto="Consultando as duas plataformas…" /> : null}

        {data && data.linhas.length === 0 ? (
          <Vazio
            titulo="Nenhuma usina no meuWatt"
            descricao="Configure e teste a conexão com o meuWatt para as usinas aparecerem aqui."
          />
        ) : null}

        {(data?.linhas ?? []).map((linha, i) => (
          <LinhaPar
            key={linha.mw_slug}
            linha={linha}
            dados={data!}
            primeiro={i === 0}
            aoEscolher={(mp) => {
              const usina = data!.meuwatt.find((u) => u.id === linha.mw_slug)
              vincular.mutate({
                mw_slug: linha.mw_slug,
                mp_usina_id: mp,
                nome: linha.mw_nome,
                cidade: usina?.cidade ?? null,
                uf: usina?.uf ?? null,
                kwp: usina?.kwp ?? null,
              })
            }}
          />
        ))}
      </Cartao>
    </Pagina>
  )
}

function LinhaPar({
  linha,
  dados,
  primeiro,
  aoEscolher,
}: {
  linha: Conciliacao['linhas'][number]
  dados: Conciliacao
  primeiro: boolean
  aoEscolher: (mp: number | null) => void
}) {
  const usina = dados.meuwatt.find((u) => u.id === linha.mw_slug)
  const sugestao = linha.candidatos[0]

  return (
    <div
      className={`grid gap-4 px-5 py-4 items-center sm:grid-cols-[1fr,auto,1fr]
                  ${primeiro ? '' : 'border-t border-borda'}`}
    >
      <div className="min-w-0">
        <p className="font-semibold text-forte truncate">{linha.mw_nome}</p>
        <p className="mono text-xs text-fraco truncate">
          {linha.mw_slug}
          {usina?.cidade ? ` · ${usina.cidade}${usina.uf ? `, ${usina.uf}` : ''}` : ''}
        </p>
      </div>

      <ArrowRight size={16} className="text-fraco hidden sm:block" />

      <div className="min-w-0">
        <label className="sr-only" htmlFor={`par-${linha.mw_slug}`}>
          Usina correspondente no meuPlano para {linha.mw_nome}
        </label>
        <select
          id={`par-${linha.mw_slug}`}
          className="campo"
          value={linha.vinculado_a ?? ''}
          onChange={(e) => aoEscolher(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">— sem par no meuPlano —</option>
          {dados.meuplano.map((u) => (
            <option key={u.id} value={u.id}>
              {u.nome}
            </option>
          ))}
        </select>
        {!linha.vinculado_a && sugestao ? (
          <p className="text-xs text-fraco mt-1.5">
            sugestão: <span className="text-rotulo">{sugestao.nome}</span> — {sugestao.motivos.join(', ')}
          </p>
        ) : null}
      </div>
    </div>
  )
}
