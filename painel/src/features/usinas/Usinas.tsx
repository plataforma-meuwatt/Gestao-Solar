/**
 * O inventário de usinas: o que existe em cada plataforma, e o que entra no aplicativo.
 *
 * Duas decisões moram nesta tela, e são independentes:
 *
 * 1. **Qual usina é qual.** Casar a usina do meuWatt com a do meuPlano. A sugestão ordena;
 *    quem decide é o gestor — um par errado mistura a geração de uma com a manutenção de
 *    outra, e ninguém percebe até alguém questionar um relatório.
 * 2. **Quais entram no app.** Uma usina pode existir nas plataformas e não interessar aqui.
 *    Só o que está ligado pode ser concedido a um cliente.
 *
 * As três origens aparecem em grupos separados, incluindo **só no meuPlano** — manutenção
 * sem monitoramento é um caso normal de negócio, e a versão anterior desta tela omitia
 * essas usinas por percorrer apenas o meuWatt.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, Sun, Wrench } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Aviso, Cartao, Carregando, Erro, Pagina, Selo, Vazio } from '@/components/base'
import {
  carregarConciliacao,
  salvarUsina,
  type Conciliacao,
  type LinhaUsina,
  type OrigemUsina,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const GRUPOS: {
  origem: OrigemUsina
  titulo: string
  icone: typeof Sun
  apoio: string
}[] = [
  {
    origem: 'ambos',
    titulo: 'Nas duas plataformas',
    icone: Link2,
    apoio: 'Geração e manutenção da mesma usina. É o caso completo.',
  },
  {
    origem: 'meuwatt',
    titulo: 'Só no meuWatt',
    icone: Sun,
    apoio: 'Monitoramento sem manutenção contratada. No app, a aba de manutenção fica oculta.',
  },
  {
    origem: 'meuplano',
    titulo: 'Só no meuPlano',
    icone: Wrench,
    apoio: 'Manutenção sem monitoramento. No app, a aba de geração fica oculta.',
  },
]

export function Usinas() {
  const qc = useQueryClient()
  const [erro, setErro] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['conciliacao'],
    queryFn: carregarConciliacao,
  })

  const salvar = useMutation({
    mutationFn: (dados: Parameters<typeof salvarUsina>[0]) => salvarUsina(dados),
    onSuccess: () => {
      setErro('')
      qc.invalidateQueries({ queryKey: ['conciliacao'] })
      // A lista de usinas do cliente vem da mesma origem: sem isto, uma usina recém-ligada
      // não apareceria para conceder até alguém recarregar a página.
      qc.invalidateQueries({ queryKey: ['usinas'] })
    },
    onError: (e) => {
      setErro(mensagemDeErro(e))
      // Recarrega para os controles voltarem ao valor real do servidor, e não ficarem
      // mostrando uma escolha que não foi gravada.
      qc.invalidateQueries({ queryKey: ['conciliacao'] })
    },
  })

  const porGrupo = useMemo(() => {
    const mapa = new Map<OrigemUsina, LinhaUsina[]>()
    for (const g of GRUPOS) mapa.set(g.origem, [])
    for (const l of data?.linhas ?? []) mapa.get(l.origem)?.push(l)
    return mapa
  }, [data])

  const noApp = (data?.linhas ?? []).filter((l) => l.no_app).length

  return (
    <Pagina
      titulo="Usinas"
      apoio="Tudo que existe nas duas plataformas. Case as que são a mesma usina e escolha quais entram no aplicativo."
    >
      {error ? <Erro className="mb-4">{mensagemDeErro(error)}</Erro> : null}
      {erro ? <Erro className="mb-4">{erro}</Erro> : null}
      {data?.aviso ? (
        <div className="mb-4">
          <Aviso>{data.aviso}</Aviso>
        </div>
      ) : null}

      {isLoading ? (
        <Cartao>
          <Carregando texto="Consultando as duas plataformas…" />
        </Cartao>
      ) : null}

      {data ? (
        <p className="text-sm text-rotulo mb-4">
          <strong className="text-forte">{noApp}</strong> de {data.linhas.length} usinas no
          aplicativo. Só as ligadas podem ser concedidas a um cliente.
        </p>
      ) : null}

      <div className="flex flex-col gap-5">
        {GRUPOS.map(({ origem, titulo, icone: Icone, apoio }) => {
          const linhas = porGrupo.get(origem) ?? []
          if (!data || (linhas.length === 0 && origem === 'ambos' && data.linhas.length === 0)) {
            return null
          }

          return (
            <Cartao key={origem}>
              <header className="px-5 pt-4 pb-3">
                <div className="flex items-center gap-2.5">
                  <Icone size={15} className="text-fraco" />
                  <h2 className="text-sm font-semibold text-forte">{titulo}</h2>
                  <span className="text-xs text-fraco">· {linhas.length}</span>
                </div>
                <p className="text-xs text-fraco mt-1">{apoio}</p>
              </header>

              {linhas.length === 0 ? (
                <div className="px-5 pb-4">
                  <p className="text-xs text-fraco">Nenhuma.</p>
                </div>
              ) : (
                <div className="border-t border-borda">
                  {linhas.map((linha, i) => (
                    <LinhaDeUsina
                      key={linha.chave}
                      linha={linha}
                      dados={data}
                      primeira={i === 0}
                      salvando={salvar.isPending}
                      aoSalvar={(mudanca) =>
                        salvar.mutate({
                          plant_link_id: linha.plant_link_id,
                          mw_slug: linha.mw_slug,
                          mp_usina_id: linha.mp_usina_id,
                          nome: linha.nome,
                          cidade: linha.cidade,
                          uf: linha.uf,
                          kwp: linha.kwp,
                          no_app: linha.no_app,
                          ...mudanca,
                        })
                      }
                    />
                  ))}
                </div>
              )}
            </Cartao>
          )
        })}
      </div>

      {data && data.linhas.length === 0 && !isLoading ? (
        <Cartao>
          <Vazio
            titulo="Nenhuma usina nas plataformas"
            descricao="Conecte o meuWatt e o meuPlano em Conexões para as usinas aparecerem aqui."
          />
        </Cartao>
      ) : null}
    </Pagina>
  )
}

function LinhaDeUsina({
  linha,
  dados,
  primeira,
  salvando,
  aoSalvar,
}: {
  linha: LinhaUsina
  dados: Conciliacao
  primeira: boolean
  salvando: boolean
  aoSalvar: (mudanca: Partial<Parameters<typeof salvarUsina>[0]>) => void
}) {
  const sugestao = linha.candidatos[0]

  // As usinas do meuPlano que ainda não pertencem a ninguém, mais a desta linha — sem
  // isso, o seletor abriria sem a opção que já está escolhida.
  const disponiveis = useMemo(() => {
    const tomadas = new Set(
      dados.linhas
        .filter((l) => l.mp_usina_id !== null && l.chave !== linha.chave)
        .map((l) => l.mp_usina_id),
    )
    return dados.meuplano.filter((u) => !tomadas.has(Number(u.id)))
  }, [dados, linha.chave])

  return (
    <div className={`px-5 py-4 ${primeira ? '' : 'border-t border-borda'}`}>
      <div className="flex items-start gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-forte truncate">{linha.nome}</p>
          <p className="mono text-xs text-fraco truncate">
            {linha.mw_slug ? `mw:${linha.mw_slug}` : ''}
            {linha.mw_slug && linha.mp_usina_id ? ' · ' : ''}
            {linha.mp_usina_id ? `mp:${linha.mp_usina_id}` : ''}
            {linha.cidade ? ` · ${linha.cidade}${linha.uf ? `, ${linha.uf}` : ''}` : ''}
            {linha.kwp ? ` · ${linha.kwp.toLocaleString('pt-BR')} kWp` : ''}
          </p>
        </div>

        {linha.no_app ? (
          <Selo tom="ok">No aplicativo</Selo>
        ) : (
          <Selo tom="sem-dados">Fora do aplicativo</Selo>
        )}

        <button
          onClick={() => aoSalvar({ no_app: !linha.no_app })}
          className="btn-fantasma w-28"
          disabled={salvando}
          title={
            linha.no_app
              ? 'Tira do aplicativo. Os vínculos e as concessões são preservados.'
              : 'Traz para o aplicativo. Só assim ela pode ser concedida a um cliente.'
          }
        >
          {linha.no_app ? 'Desligar' : 'Ligar'}
        </button>
      </div>

      {/* O par só se escolhe do lado do meuWatt: é ele que tem o slug, a chave de todo o
          resto. Uma usina só do meuPlano vira par ao ser escolhida na linha de uma do
          meuWatt, não o contrário. */}
      {linha.mw_slug ? (
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <label className="text-xs text-rotulo" htmlFor={`par-${linha.chave}`}>
            Usina correspondente no meuPlano
          </label>
          <select
            id={`par-${linha.chave}`}
            className="campo h-9 text-sm max-w-xs"
            value={linha.mp_usina_id ?? ''}
            disabled={salvando}
            onChange={(e) =>
              aoSalvar({ mp_usina_id: e.target.value ? Number(e.target.value) : null })
            }
          >
            <option value="">— sem par no meuPlano —</option>
            {disponiveis.map((u) => (
              <option key={u.id} value={u.id}>
                {u.nome}
              </option>
            ))}
          </select>

          {!linha.mp_usina_id && sugestao ? (
            <button
              onClick={() => aoSalvar({ mp_usina_id: sugestao.mp_usina_id })}
              className="btn-fantasma text-xs"
              disabled={salvando}
            >
              usar “{sugestao.nome}” ({sugestao.motivos.join(', ')})
            </button>
          ) : null}
        </div>
      ) : null}

      {/* A linha do meuPlano ainda solta diz de quem parece ser par, e casa num clique.
          Sem isto, a mesma usina aparece em dois grupos e caberia ao gestor perceber. */}
      {!linha.mw_slug && linha.par_provavel_mw ? (
        <p className="text-xs text-fraco mt-2">
          Parece ser a mesma que{' '}
          <span className="text-rotulo">{linha.par_provavel_nome}</span> no meuWatt
          {linha.par_provavel_motivos.length
            ? ` (${linha.par_provavel_motivos.join(', ')})`
            : ''}
          {' · '}
          <button
            onClick={() => aoSalvar({ mw_slug: linha.par_provavel_mw })}
            className="text-ambar hover:underline"
            disabled={salvando}
          >
            casar as duas
          </button>
        </p>
      ) : null}
    </div>
  )
}
