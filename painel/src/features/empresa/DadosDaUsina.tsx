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
  usinasDaEmpresa,
  type DadosDaUsina as Dados,
  type MudancaDeDados,
  type UsinaAConfirmar as UsinaAConfirmarT,
  type UsinaDaEmpresa,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const quando = (iso: string) =>
  new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' })

const coordenada = (v: number | null | undefined) =>
  v === null || v === undefined ? '' : v.toLocaleString('pt-BR', { maximumFractionDigits: 7, useGrouping: false })

/** A coordenada digitada: vírgula ou ponto como decimal ("-21,7512" ou "-21.7512", como o Google Maps copia), sem
 *  separador de milhar; null quando vazia; NaN quando não é número ou é ambígua (dois separadores). */
const coordenadaDigitada = (texto: string) => {
  const t = texto.trim()
  if (t === '') return null
  if ((t.match(/[.,]/g) ?? []).length > 1) return Number.NaN
  return Number(t.replace(',', '.'))
}

/** A potência em pt-BR: ponto de milhar e vírgula decimal ("1.250,5"). "1.500" é mil e quinhentos; "1250.5" (o ponto
 *  como decimal) é ambíguo e é recusado, em vez de virar 1,25 kWp em silêncio. */
const potenciaDigitada = (texto: string) => {
  const t = texto.trim()
  if (t === '') return null
  if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(t) || /^\d+(,\d+)?$/.test(t)) return Number(t.replace(/\./g, '').replace(',', '.'))
  return Number.NaN
}

type Form = { endereco: string; cidade: string; uf: string; latitude: string; longitude: string; kwp: string }

const doServidor = (d: Dados): Form => ({
  endereco: d.endereco ?? '',
  cidade: d.cidade ?? '',
  uf: d.uf ?? '',
  latitude: coordenada(d.latitude),
  longitude: coordenada(d.longitude),
  kwp: d.kwp === null ? '' : d.kwp.toLocaleString('pt-BR', { maximumFractionDigits: 2 }),
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
      setAviso('Salvo no GS. Cada sistema recebe na próxima leitura dele.')
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
      const kwp = potenciaDigitada(form.kwp)
      if (kwp !== null && Number.isNaN(kwp)) return setAviso('A potência vai em pt-BR: 1.250 ou 1.250,5.')
      m.kwp = kwp
    }
    if (form.latitude !== original.latitude || form.longitude !== original.longitude) {
      const la = coordenadaDigitada(form.latitude)
      const lo = coordenadaDigitada(form.longitude)
      if ((la !== null && Number.isNaN(la)) || (lo !== null && Number.isNaN(lo)))
        return setAviso('A coordenada vai em números, como -21,7512 (sem separador de milhar).')
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
  const [verDescartadas, setVerDescartadas] = useState(false)
  const { data, error } = useQuery({ queryKey: ['empresa', 'usinas-a-confirmar'], queryFn: () => usinasAConfirmar() })
  const descartadas = useQuery({
    queryKey: ['empresa', 'usinas-a-confirmar', 'descartadas'],
    queryFn: () => usinasAConfirmar(true),
    enabled: verDescartadas,
  })
  const usinas = useQuery({ queryKey: ['empresa', 'usinas'], queryFn: usinasDaEmpresa, enabled: !!data?.length })
  const decidir = useMutation({
    mutationFn: ({ id, decisao, gs }: { id: number; decisao: 'mesma' | 'outra' | 'descartar' | 'reabrir'; gs?: number }) =>
      decidirUsinaAConfirmar(id, decisao, gs),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresa'] }),
  })
  if (error) return <Erro>{mensagemDeErro(error)}</Erro>
  if (!data?.length && !verDescartadas)
    return (
      <button className="btn-fantasma justify-self-start" onClick={() => setVerDescartadas(true)}>
        Ver os pedidos descartados
      </button>
    )
  return (
    <Cartao className="px-5 py-4 grid gap-3">
      {data?.length ? (
        <div>
          <p className="text-forte font-semibold">A confirmar ({data.length})</p>
          <p className="text-sm text-rotulo">
            Usinas criadas em outro sistema que parecem uma que já está aqui. Diga se é a mesma: a
            semelhança de nome ou de lugar não decide sozinha.
          </p>
        </div>
      ) : null}
      {decidir.error ? <Erro>{mensagemDeErro(decidir.error)}</Erro> : null}
      {usinas.error ? (
        <Erro>
          A lista das usinas daqui não carregou ({mensagemDeErro(usinas.error)}): o “é outra usina daqui” fica sem
          opções até ela carregar.
        </Erro>
      ) : null}
      {(data ?? []).map((p) => (
        <Pedido key={p.id} p={p} usinas={usinas.data ?? []} ocupado={decidir.isPending}
                aoDecidir={(decisao, gs) => decidir.mutate({ id: p.id, decisao, gs })} />
      ))}
      <div className="border-t border-borda pt-3">
        <button className="btn-fantasma" onClick={() => setVerDescartadas((v) => !v)}>
          {verDescartadas ? 'Esconder os descartados' : 'Ver os pedidos descartados'}
        </button>
        {verDescartadas ? (
          descartadas.isLoading ? (
            <Carregando />
          ) : descartadas.error ? (
            <Erro>Os pedidos descartados não carregaram: {mensagemDeErro(descartadas.error)}</Erro>
          ) : !descartadas.data?.length ? (
            <p className="text-sm text-fraco mt-2">Nenhum pedido descartado.</p>
          ) : (
            <ul className="grid gap-2 mt-2">
              {descartadas.data.map((p) => (
                <li key={p.id} className="flex items-center gap-3 flex-wrap text-sm text-rotulo">
                  <span>
                    {p.dados.nome} (do {p.sistema}, código {p.referencia})
                    {p.decidido_em ? `, descartado em ${quando(p.decidido_em)}` : ''}
                  </span>
                  <button className="btn-fantasma" disabled={decidir.isPending}
                          onClick={() => decidir.mutate({ id: p.id, decisao: 'reabrir' })}>
                    Voltar a confirmar
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </div>
    </Cartao>
  )
}

function Pedido({
  p,
  usinas,
  ocupado,
  aoDecidir,
}: {
  p: UsinaAConfirmarT
  usinas: UsinaDaEmpresa[]
  ocupado: boolean
  aoDecidir: (decisao: 'mesma' | 'outra' | 'descartar', gs?: number) => void
}) {
  const [busca, setBusca] = useState('')
  // a lista PESQUISÁVEL (regra da casa) pelo próprio navegador: digita, filtra e escolhe; o número separa nomes iguais
  const opcoes = usinas.map((u) => ({ id: u.id, rotulo: `${u.nome} (nº ${u.id}${u.cidade ? `, ${u.cidade}` : ''})` }))
  const escolhida = opcoes.find((o) => o.rotulo === busca)
  const [descartando, setDescartando] = useState(false)
  const detalhes = [
    [p.dados.cidade, p.dados.uf].filter(Boolean).join(' · ') || 'sem cidade',
    p.dados.latitude !== null ? `lat ${coordenada(p.dados.latitude)} · long ${coordenada(p.dados.longitude)}` : null,
    p.dados.kwp !== null ? `${p.dados.kwp.toLocaleString('pt-BR')} kWp` : null,
    p.pedido_por ? `pedido por ${p.pedido_por}` : 'importado',
    `em ${quando(p.em)}`,
  ].filter(Boolean)
  return (
    <div className="border-t border-borda pt-3">
      <p className="text-sm text-forte">
        {p.dados.nome} <span className="text-fraco">(do {p.sistema}, código {p.referencia})</span>
      </p>
      <p className="text-xs text-fraco">{detalhes.join(' · ')}</p>
      <div className="flex gap-2 flex-wrap mt-2">
        {p.parecidas.map((x) => (
          <button
            key={x.gs}
            className="btn-secundario h-auto min-h-11 py-2 text-left"
            disabled={ocupado}
            onClick={() => aoDecidir('mesma', x.gs)}
          >
            É a {x.codigo} {x.nome}
            <span className="text-xs text-fraco ml-1">
              ({[x.pelo_nome ? 'nome parecido' : null,
                x.distancia_km !== null ? `a ${x.distancia_km.toLocaleString('pt-BR')} km` : null,
                x.ativo ? null : 'desligada no app'].filter(Boolean).join(', ')})
            </span>
          </button>
        ))}
      </div>
      <div className="flex gap-2 flex-wrap mt-2 items-center">
        <input
          className="campo h-11 text-sm min-w-0 flex-1"
          list={`usinas-do-pedido-${p.id}`}
          placeholder="É outra usina daqui? Digite o nome para procurar"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          aria-label="Outra usina daqui"
        />
        <datalist id={`usinas-do-pedido-${p.id}`}>
          {opcoes.map((o) => (
            <option key={o.id} value={o.rotulo} />
          ))}
        </datalist>
        <button className="btn-secundario" disabled={!escolhida || ocupado}
                onClick={() => escolhida && aoDecidir('mesma', escolhida.id)}>
          É esta
        </button>
        <button className="btn-fantasma h-auto min-h-11 py-2 text-left" disabled={ocupado} onClick={() => aoDecidir('outra')}>
          É uma usina nova: criar no GS
        </button>
        {descartando ? (
          <>
            <span className="text-sm text-rotulo">Descartar este pedido? Volta pela lista dos descartados.</span>
            <button className="btn-fantasma" disabled={ocupado} onClick={() => aoDecidir('descartar')}>
              Descartar
            </button>
            <button className="btn-fantasma" onClick={() => setDescartando(false)}>
              Não
            </button>
          </>
        ) : (
          <button className="btn-fantasma" disabled={ocupado} onClick={() => setDescartando(true)}>
            Descartar
          </button>
        )}
      </div>
    </div>
  )
}
