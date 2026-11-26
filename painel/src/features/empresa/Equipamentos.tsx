/**
 * Os equipamentos da usina no índice do GS (a POSIÇÃO: o transformador e os inversores dele) e o nó
 * do meuPlano de cada um. O meuPlano não tem esses pares, então o GS propõe ("sugestão", com o
 * porquê) e quem confirma é o gerente: nada é gravado antes do Salvar, e o Salvar pergunta antes.
 *
 * Um nó é uma posição só: o servidor recusa o nó que já está em outro equipamento, a não ser que
 * os dois troquem no mesmo salvar. A recusa aparece aqui, inteira.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { Aviso, Carregando, Erro, Selo } from '@/components/base'
import {
  equipamentosDaUsina,
  salvarNosDosEquipamentos,
  type DispositivoDaUsina,
  type EquipamentosDaUsina,
  type NoCandidato,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

/** A árvore em lista, com o nível de cada um (o inversor fica recuado debaixo do transformador). */
const emLista = (itens: DispositivoDaUsina[], nivel = 0): { d: DispositivoDaUsina; nivel: number }[] =>
  itens.flatMap((d) => [{ d, nivel }, ...emLista(d.filhos, nivel + 1)])

/** O que a tela mostra ao abrir: o nó gravado; sem ele, a sugestão do GS. */
const aoAbrir = (dados: EquipamentosDaUsina): Record<number, number | null> =>
  Object.fromEntries(emLista(dados.dispositivos).map(({ d }) => [d.gd, d.no?.id ?? d.sugestao?.node_id ?? null]))

export function Equipamentos({ usinaId }: { usinaId: number }) {
  const qc = useQueryClient()
  const chave = ['empresa', 'usina-equipamentos', usinaId]
  const { data, isLoading, error } = useQuery({ queryKey: chave, queryFn: () => equipamentosDaUsina(usinaId) })
  const [escolhas, setEscolhas] = useState<Record<number, number | null>>({})
  const [confirmando, setConfirmando] = useState(false)
  const [aviso, setAviso] = useState<string | null>(null)
  useEffect(() => {
    if (data) setEscolhas(aoAbrir(data))
  }, [data])

  const salvar = useMutation({
    mutationFn: (nos: { gd: number; node_id: number | null }[]) => salvarNosDosEquipamentos(usinaId, nos),
    onSuccess: (d) => {
      qc.setQueryData(chave, d)
      qc.invalidateQueries({ queryKey: ['empresa', 'usina-dados', usinaId] })
      setAviso('Salvo. O meuPlano recebe na próxima leitura dele.')
    },
    onSettled: () => setConfirmando(false),
  })

  if (isLoading) return <Carregando />
  if (error) return <Erro className="mt-3">{mensagemDeErro(error)}</Erro>
  if (!data) return null

  const linhas = emLista(data.dispositivos)
  const mudancas = linhas
    .filter(({ d }) => d.gd in escolhas && escolhas[d.gd] !== (d.no?.id ?? null))
    .map(({ d }) => ({ gd: d.gd, node_id: escolhas[d.gd] }))
  const aLigar = mudancas.filter((m) => m.node_id !== null).length
  const aDesligar = mudancas.length - aLigar
  // o mesmo nó escolhido duas vezes: a tela diz antes de o servidor recusar
  const escolhidos = Object.values(escolhas).filter((n): n is number => n !== null)
  const repetidos = new Set(escolhidos.filter((n, i) => escolhidos.indexOf(n) !== i))

  const escolher = (gd: number, valor: string) => {
    setAviso(null)
    setConfirmando(false)
    salvar.reset()
    setEscolhas({ ...escolhas, [gd]: valor === '' ? null : Number(valor) })
  }

  return (
    <div className="mt-3 border-t border-borda pt-3 grid gap-3">
      <div>
        <p className="text-sm text-forte font-semibold">
          {data.ligados} de {data.total} {data.total === 1 ? 'equipamento ligado' : 'equipamentos ligados'} ao meuPlano
        </p>
        <p className="text-sm text-rotulo">
          Diga qual nó da árvore do meuPlano é cada transformador e cada inversor daqui. A sugestão é um palpite do
          Gestão Solar: confira antes de salvar.
        </p>
      </div>
      {data.aviso ? <Aviso>{data.aviso}</Aviso> : null}

      {linhas.length ? (
        <ul className="grid gap-2">
          {linhas.map(({ d, nivel }) => (
            <Linha
              key={d.gd}
              d={d}
              nivel={nivel}
              candidatos={data.candidatos[d.tipo] ?? []}
              valor={escolhas[d.gd] ?? null}
              repetido={escolhas[d.gd] != null && repetidos.has(escolhas[d.gd] as number)}
              aoEscolher={(v) => escolher(d.gd, v)}
            />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-fraco">
          Esta usina ainda não tem equipamentos no índice: eles chegam do meuWatt (transformadores e inversores).
        </p>
      )}

      {linhas.length ? (
        <div className="flex items-center gap-3 flex-wrap">
          {confirmando ? (
            <>
              <span className="text-sm text-rotulo">
                {[
                  aLigar ? `Ligar ${aLigar} ${aLigar === 1 ? 'equipamento' : 'equipamentos'} ao nó escolhido` : null,
                  aDesligar ? `tirar o nó de ${aDesligar}` : null,
                ]
                  .filter(Boolean)
                  .join(' e ')}
                ? As sugestões entram como estão na tela.
              </span>
              <button className="btn-secundario" disabled={salvar.isPending} onClick={() => salvar.mutate(mudancas)}>
                {salvar.isPending ? 'Salvando…' : 'Salvar'}
              </button>
              <button className="btn-fantasma" disabled={salvar.isPending} onClick={() => setConfirmando(false)}>
                Não
              </button>
            </>
          ) : (
            <button
              className="btn-secundario"
              disabled={repetidos.size > 0}
              onClick={() => {
                salvar.reset()
                if (!mudancas.length) return setAviso('Nada mudou.')
                setAviso(null)
                setConfirmando(true)
              }}
            >
              Salvar os equipamentos
            </button>
          )}
          {repetidos.size ? (
            <span className="text-sm text-alerta">O mesmo nó está em mais de um equipamento: um nó é uma posição só.</span>
          ) : null}
          {aviso ? <span className="text-sm text-rotulo">{aviso}</span> : null}
        </div>
      ) : null}
      {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
    </div>
  )
}

function Linha({
  d,
  nivel,
  candidatos,
  valor,
  repetido,
  aoEscolher,
}: {
  d: DispositivoDaUsina
  nivel: number
  candidatos: NoCandidato[]
  valor: number | null
  repetido: boolean
  aoEscolher: (valor: string) => void
}) {
  const gravado = d.no?.id ?? null
  // o nó gravado que não veio entre os candidatos (o meuPlano fora, ou um nó de outro tipo): continua na lista
  const foraDaLista = gravado !== null && !candidatos.some((c) => c.id === gravado)
  const estado =
    valor === gravado
      ? gravado !== null
        ? { texto: 'confirmado', classe: 'text-ok' }
        : null
      : valor !== null && valor === d.sugestao?.node_id
        ? { texto: `sugestão ${d.sugestao.motivo}: ainda não salva`, classe: 'text-ambar-texto' }
        : { texto: valor === null ? 'vai ficar sem nó: ainda não salvo' : 'escolhido por você: ainda não salvo', classe: 'text-ambar-texto' }
  const id = `no-do-equipamento-${d.gd}`
  return (
    <li className={`grid gap-2 sm:grid-cols-2 sm:items-start ${nivel ? 'pl-4 border-l border-borda' : ''}`}>
      <div className="min-w-0">
        <label className="text-sm text-forte" htmlFor={id}>
          {d.nome} <span className="text-fraco">· {d.tipo_rotulo}</span>
        </label>
        <p className="text-xs text-fraco mono">{d.codigo}</p>
        {d.ativo ? null : (
          <p className="mt-1">
            <Selo tom="sem-dados">fora da última lista do meuWatt</Selo>
          </p>
        )}
      </div>
      <div className="min-w-0">
        <select
          id={id}
          className={`campo h-auto min-h-11 py-2 text-sm ${repetido ? 'border-alerta' : ''}`}
          value={valor ?? ''}
          onChange={(e) => aoEscolher(e.target.value)}
        >
          <option value="">sem nó no meuPlano</option>
          {foraDaLista && d.no ? <option value={d.no.id}>{d.no.rotulo ?? `nó ${d.no.id} (gravado)`}</option> : null}
          {candidatos.map((c) => (
            <option key={c.id} value={c.id}>
              {c.rotulo}
            </option>
          ))}
        </select>
        {estado ? <p className={`text-xs mt-1 ${estado.classe}`}>{estado.texto}</p> : null}
      </div>
    </li>
  )
}
