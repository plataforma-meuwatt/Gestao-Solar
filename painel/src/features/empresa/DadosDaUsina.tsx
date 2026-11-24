/**
 * Os dados básicos da usina moram no GS (Plano Casa GS, R10): o endereço, a cidade, a UF, a
 * coordenada e a potência. O gerente edita aqui; o meuPlano, o TermoVision e o meuGuarda
 * leem e editam pela porta deles, e cada mudança fica no histórico com quem, de onde, o
 * antes e o depois. O nome continua na linha da usina (um lugar só para cada campo).
 *
 * E as usinas criadas em outro sistema que parecem uma daqui ficam "a confirmar": quem
 * decide se é a mesma é o gerente, nunca a semelhança de nome ou de lugar.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPin } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Campo, Carregando, Cartao, Erro } from '@/components/base'
import {
  dadosDaUsina,
  decidirUsinaAConfirmar,
  salvarDadosDaUsina,
  usinasAConfirmar,
  type DadosDaUsina as Dados,
  type MudancaDeDados,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const quando = (iso: string) =>
  new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' })

const coordenada = (v: number | null) =>
  v === null ? '' : v.toLocaleString('pt-BR', { maximumFractionDigits: 7, useGrouping: false })

/** O número digitado em pt-BR ("-21,7512"), ou null quando vazio; NaN quando não é número. */
const numero = (texto: string) => (texto.trim() === '' ? null : Number(texto.trim().replace(',', '.')))

type Form = { endereco: string; cidade: string; uf: string; latitude: string; longitude: string; kwp: string }

const doServidor = (d: Dados): Form => ({
  endereco: d.endereco ?? '',
  cidade: d.cidade ?? '',
  uf: d.uf ?? '',
  latitude: coordenada(d.latitude),
  longitude: coordenada(d.longitude),
  kwp: d.kwp === null ? '' : d.kwp.toLocaleString('pt-BR', { useGrouping: false }),
})

export function DadosDaUsina({ usinaId }: { usinaId: number }) {
  const qc = useQueryClient()
  const chave = ['empresa', 'usina-dados', usinaId]
  const { data, isLoading, error } = useQuery({ queryKey: chave, queryFn: () => dadosDaUsina(usinaId) })
  const [form, setForm] = useState<Form | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  useEffect(() => {
    if (data) setForm(doServidor(data))
  }, [data])

  const salvar = useMutation({
    mutationFn: (m: MudancaDeDados) => salvarDadosDaUsina(usinaId, m),
    onSuccess: (d) => {
      qc.setQueryData(chave, d)
      setAviso('Salvo. Os outros sistemas leem daqui.')
    },
  })

  if (isLoading || !form) return error ? <Erro>{mensagemDeErro(error)}</Erro> : <Carregando />
  if (!data) return null
  const original = doServidor(data)
  const muda = (campo: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setAviso(null)
    setForm({ ...form, [campo]: e.target.value })
  }

  function enviar() {
    if (!form) return
    const m: MudancaDeDados = {}
    if (form.endereco !== original.endereco) m.endereco = form.endereco
    if (form.cidade !== original.cidade) m.cidade = form.cidade
    if (form.uf !== original.uf) m.uf = form.uf
    if (form.kwp !== original.kwp) {
      const kwp = numero(form.kwp)
      if (kwp !== null && Number.isNaN(kwp)) return setAviso('A potência tem de ser um número.')
      m.kwp = kwp
    }
    if (form.latitude !== original.latitude || form.longitude !== original.longitude) {
      const la = numero(form.latitude)
      const lo = numero(form.longitude)
      if ((la !== null && Number.isNaN(la)) || (lo !== null && Number.isNaN(lo)))
        return setAviso('A coordenada tem de ser em números, como -21,7512.')
      m.latitude = la
      m.longitude = lo
    }
    if (!Object.keys(m).length) return setAviso('Nada mudou.')
    salvar.mutate(m)
  }

  const temCoordenada = data.latitude !== null && data.longitude !== null
  return (
    <div className="mt-3 border-t border-borda pt-3 grid gap-3">
      <p className="text-sm text-rotulo">
        Código no GS <span className="text-forte font-semibold">{data.codigo}</span>, o mesmo em todos
        os sistemas.
        {data.tv_codigo ? ` Mapa no TermoVision: ${data.tv_codigo}.` : ' Sem mapa do TermoVision ligado.'}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Campo rotulo="Endereço" value={form.endereco} onChange={muda('endereco')} maxLength={300} />
        <div className="grid grid-cols-[1fr_5rem] gap-3">
          <Campo rotulo="Cidade" value={form.cidade} onChange={muda('cidade')} maxLength={120} />
          <Campo rotulo="UF" value={form.uf} onChange={muda('uf')} maxLength={2} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Campo rotulo="Latitude" value={form.latitude} onChange={muda('latitude')} inputMode="decimal" />
          <Campo rotulo="Longitude" value={form.longitude} onChange={muda('longitude')} inputMode="decimal" />
        </div>
        <Campo rotulo="Potência (kWp)" value={form.kwp} onChange={muda('kwp')} inputMode="decimal" />
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <button className="btn-secundario" disabled={salvar.isPending} onClick={enviar}>
          {salvar.isPending ? 'Salvando…' : 'Salvar os dados'}
        </button>
        {temCoordenada ? (
          <a
            className="text-sm text-rotulo hover:text-forte inline-flex items-center gap-1"
            href={`https://www.google.com/maps?q=${data.latitude},${data.longitude}`}
            target="_blank"
            rel="noreferrer"
          >
            <MapPin size={14} /> Ver no Google Maps
          </a>
        ) : (
          <span className="text-sm text-fraco">Sem coordenada no GS.</span>
        )}
        {aviso ? <span className="text-sm text-rotulo">{aviso}</span> : null}
      </div>
      {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}

      <div>
        <p className="rotulo-campo">Histórico</p>
        {data.historico.length ? (
          <ul className="grid gap-1.5">
            {data.historico.map((h, i) => (
              <li key={i} className="text-sm text-rotulo">
                <span className="text-fraco">{quando(h.em)}</span> · <span className="text-forte">{h.rotulo}</span>
                {h.campo === 'criada' ? ` (${h.depois})` : `: ${h.antes ?? 'vazio'} → ${h.depois ?? 'vazio'}`}
                {' · '}
                {h.por ?? 'o próprio sistema'}, pelo {h.sistema}
                {h.motivo ? ` (${h.motivo})` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fraco">Nenhuma mudança registrada desde 24/11/2026.</p>
        )}
      </div>
    </div>
  )
}

export function UsinasAConfirmar() {
  const qc = useQueryClient()
  const { data, error } = useQuery({ queryKey: ['empresa', 'usinas-a-confirmar'], queryFn: usinasAConfirmar })
  const decidir = useMutation({
    mutationFn: ({ id, decisao, gs }: { id: number; decisao: 'mesma' | 'outra' | 'descartar'; gs?: number }) =>
      decidirUsinaAConfirmar(id, decisao, gs),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresa'] }),
  })
  if (error) return <Erro>{mensagemDeErro(error)}</Erro>
  if (!data?.length) return null
  return (
    <Cartao className="px-5 py-4 grid gap-3">
      <div>
        <p className="text-forte font-semibold">A confirmar</p>
        <p className="text-sm text-rotulo">
          Usinas criadas em outro sistema que parecem uma que já está aqui. Diga se é a mesma: a
          semelhança de nome ou de lugar não decide sozinha.
        </p>
      </div>
      {decidir.error ? <Erro>{mensagemDeErro(decidir.error)}</Erro> : null}
      {data.map((p) => (
        <div key={p.id} className="border-t border-borda pt-3">
          <p className="text-sm text-forte">
            {p.dados.nome} <span className="text-fraco">(do {p.sistema}, código {p.referencia})</span>
          </p>
          <p className="text-xs text-fraco">
            {[p.dados.cidade, p.dados.uf].filter(Boolean).join(' · ') || 'sem cidade'}
            {p.dados.latitude !== null ? ` · ${coordenada(p.dados.latitude)}, ${coordenada(p.dados.longitude)}` : ''}
            {` · pedido em ${quando(p.em)}`}
          </p>
          <div className="flex gap-2 flex-wrap mt-2">
            {p.parecidas.map((x) => (
              <button
                key={x.gs}
                className="btn-secundario"
                disabled={decidir.isPending}
                onClick={() => decidir.mutate({ id: p.id, decisao: 'mesma', gs: x.gs })}
              >
                É a {x.codigo} {x.nome}
                <span className="text-xs text-fraco ml-1">
                  ({[x.pelo_nome ? 'nome parecido' : null, x.distancia_km !== null
                    ? `a ${x.distancia_km.toLocaleString('pt-BR')} km` : null].filter(Boolean).join(', ')})
                </span>
              </button>
            ))}
            <button
              className="btn-fantasma"
              disabled={decidir.isPending}
              onClick={() => decidir.mutate({ id: p.id, decisao: 'outra' })}
            >
              É outra usina: criar no GS
            </button>
            <button
              className="btn-fantasma"
              disabled={decidir.isPending}
              onClick={() => decidir.mutate({ id: p.id, decisao: 'descartar' })}
            >
              Descartar
            </button>
          </div>
        </div>
      ))}
    </Cartao>
  )
}
