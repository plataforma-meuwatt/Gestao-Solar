/**
 * MAPA ÚNICO da usina — gestao.solar/usinas/<id>/mapa (e o atalho gestao.solar/mapa/<id>).
 *
 * O dono (18/11/2026): "o mapa pode ser tipo gestao.solar/mapa/usina … todos usam o mesmo … o meuGuarda só consome o
 * mapa". Escolheu: a O&M edita, o dono da usina só vê. O satélite é o mesmo dos outros mapas (Esri), o voo do
 * TermoVision por cima, o contorno e o pino da usina, e cada equipamento marcado — o toque abre a ficha dele no meuPlano.
 *
 * Marcar e mover (só a O&M, com o token pessoal do meuPlano): escolhe o equipamento pela busca (o "câmera 1" acha a
 * "Câmera 01"), toca no mapa onde ele está e confirma. A posição vai ao mapa do meuWatt pela rota do meuPlano — a mesma
 * que o bot do WhatsApp usa com a localização do celular. Nunca há uma segunda cópia aqui.
 */

import 'leaflet/dist/leaflet.css'

import L from 'leaflet'
import { MapPinned } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import { Aviso, Botao, Cartao, Modal, Pagina, Tela4Estados } from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { numero } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'

import {
  buscarEquipamentos,
  caminhoDoMapa,
  marcarNoMapa,
  type EquipamentoAchado,
  type MapaOut,
  type ObjetoDoMapa,
} from './api'

/** A cor e o nome de cada tipo — os MESMOS do mapa do meuPlano (site e app). */
const COR: Record<string, string> = {
  inversor: '#f59e0b', string: '#a78bfa', tracker_fileira: '#38bdf8', transformador: '#fb923c',
  subestacao: '#f87171', estacao: '#34d399', caixa_juncao: '#e879f9', mesa: '#94a3b8', camera: '#22d3ee', outro: '#cbd5e1',
}
const ROTULO: Record<string, string> = {
  inversor: 'Inversor', string: 'String', tracker_fileira: 'Fileira de tracker', transformador: 'Transformador',
  subestacao: 'Subestação', estacao: 'Estação', caixa_juncao: 'Caixa de junção', mesa: 'Mesa', camera: 'Câmera', outro: 'Outro',
}
/** A ficha do equipamento (só a O&M abre: ela tem conta no sistema de manutenção). */
const FICHA = 'https://app.meuplano.solar/ativos'
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

type Modo = { tipo: 'nada' } | { tipo: 'marcar'; equipamento: { node_id: number; nome: string } }
type Ponto = { lat: number; lng: number }

/** GeoJSON é [lon, lat]; o Leaflet quer [lat, lon]. */
function ll(p: unknown): L.LatLngTuple | null {
  return Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'number' ? [p[1], p[0]] : null
}

function camadaDo(o: ObjetoDoMapa): L.Layer | null {
  const g = o.geometria
  if (!g) return null
  const cor = COR[o.tipo] ?? COR.outro
  if (g.type === 'Point') {
    const p = ll(g.coordinates)
    return p ? L.circleMarker(p, { radius: o.node_id ? 8 : 5, color: cor, fillColor: cor, fillOpacity: o.node_id ? 0.9 : 0.4, weight: 2 }) : null
  }
  if (g.type === 'LineString') {
    const pts = ((g.coordinates as unknown[]) || []).map(ll).filter((p): p is L.LatLngTuple => p !== null)
    return pts.length ? L.polyline(pts, { color: cor, weight: o.node_id ? 4 : 2 }) : null
  }
  const anel = (((g.coordinates as unknown[][]) || [])[0] || []).map(ll).filter((p): p is L.LatLngTuple => p !== null)
  return anel.length ? L.polygon(anel, { color: cor, weight: 2, fillOpacity: o.node_id ? 0.35 : 0.15 }) : null
}

export default function Mapa() {
  const { id } = useParams()
  const usinaId = Number(id)
  const leitura = useLeitura<MapaOut>(caminhoDoMapa(usinaId))
  return (
    <Pagina
      rotulo="O MAPA ÚNICO DA USINA"
      titulo={leitura.dados ? `Mapa · ${leitura.dados.usina.nome}` : 'Mapa da usina'}
      subtitulo="O voo e cada equipamento marcado; toque num equipamento para ver qual é."
    >
      <Tela4Estados leitura={leitura}>{(d) => <Conteudo d={d} usinaId={usinaId} recarregar={leitura.recarregar} />}</Tela4Estados>
    </Pagina>
  )
}

function Conteudo({ d, usinaId, recarregar }: { d: MapaOut; usinaId: number; recarregar: () => void }) {
  const caixa = useRef<HTMLDivElement>(null)
  const mapa = useRef<L.Map | null>(null)
  const camadas = useRef<L.LayerGroup | null>(null)
  const [escolhido, setEscolhido] = useState<ObjetoDoMapa | null>(null)
  const [modo, setModo] = useState<Modo>({ tipo: 'nada' })
  const [ponto, setPonto] = useState<Ponto | null>(null)
  const modoRef = useRef<Modo>(modo)
  modoRef.current = modo

  const objetos = d.mapa?.objetos ?? []
  const porTipo = useMemo(() => {
    const m = new Map<string, number>()
    for (const o of objetos) {
      const n = m.get(o.tipo)
      m.set(o.tipo, n === undefined ? 1 : n + 1)
    }
    return [...m.entries()]
  }, [objetos])
  const ligados = objetos.filter((o) => o.node_id).length

  // o mapa nasce uma vez; as camadas se refazem quando o dado muda
  useEffect(() => {
    if (!caixa.current || mapa.current) return
    const m = L.map(caixa.current, { zoomControl: true, maxZoom: 21 })
    m.attributionControl.setPrefix('Leaflet')
    L.tileLayer(ESRI, { maxZoom: 21, maxNativeZoom: 19, attribution: 'Imagens © Esri' }).addTo(m)
    camadas.current = L.layerGroup().addTo(m)
    m.on('click', (e: L.LeafletMouseEvent) => {
      if (modoRef.current.tipo === 'marcar') setPonto({ lat: e.latlng.lat, lng: e.latlng.lng })
    })
    mapa.current = m
    return () => {
      m.remove()
      mapa.current = null
    }
  }, [])

  useEffect(() => {
    const m = mapa.current
    const grupo = camadas.current
    if (!m || !grupo) return
    grupo.clearLayers()
    const enquadrar: L.LatLngTuple[] = []
    const u = d.mapa?.usina
    if (d.mapa?.orto?.url) {
      L.imageOverlay(d.mapa.orto.url, d.mapa.orto.bounds).addTo(grupo)
      enquadrar.push(...(d.mapa.orto.bounds as L.LatLngTuple[]))
    }
    const contorno = (u?.area_poligono ?? []).filter((p) => Array.isArray(p) && p.length >= 2) as L.LatLngTuple[]
    if (contorno.length >= 3) L.polygon(contorno, { color: '#fbbf24', weight: 2, fillOpacity: 0.04, dashArray: '6 4' }).addTo(grupo)
    if (u?.latitude != null && u?.longitude != null) {
      L.circleMarker([u.latitude, u.longitude], { radius: 6, color: '#fbbf24', fillColor: '#ffffff', fillOpacity: 1, weight: 3 }).addTo(grupo)
    }
    for (const o of objetos) {
      const c = camadaDo(o)
      if (!c) continue
      const dica = document.createElement('div')
      dica.textContent = `${o.nome || ROTULO[o.tipo] || o.tipo} · ${ROTULO[o.tipo] || o.tipo}`   // texto, nunca HTML
      ;(c as L.Path).bindTooltip(dica, { sticky: true })
      c.on('click', () => setEscolhido(o))
      c.addTo(grupo)
      if (!d.mapa?.orto) {
        const g = o.geometria
        if (g?.type === 'Point') {
          const p = ll(g.coordinates)
          if (p) enquadrar.push(p)
        }
      }
    }
    if (!enquadrar.length && contorno.length) enquadrar.push(...contorno)
    if (!enquadrar.length && u?.latitude != null && u?.longitude != null) enquadrar.push([u.latitude, u.longitude])
    if (enquadrar.length) m.fitBounds(L.latLngBounds(enquadrar), { maxZoom: 18, padding: [24, 24] })
    else m.setView([-15.8, -47.9], 4)
  }, [d, objetos])

  return (
    <div className="space-y-3">
      {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}
      {d.mapa && !d.mapa.vinculado ? (
        <Aviso>O voo e as marcações ainda não estão ligados a esta usina: o mapa mostra só o pino e o contorno.</Aviso>
      ) : null}
      {d.mapa && d.mapa.vinculado && !d.mapa.orto && objetos.length === 0 && !d.aviso ? (
        <Aviso tom="semDados">O mapa desta usina ainda está vazio: o voo entra pelo TermoVision, e a O&M marca os equipamentos aqui
          ou pelo WhatsApp, mandando a localização.</Aviso>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-fraco">
        {porTipo.map(([t, n]) => (
          <span key={t} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: COR[t] ?? COR.outro }} />
            {ROTULO[t] || t}: {n}
          </span>
        ))}
        {objetos.length ? <span>· {ligados} de {objetos.length} ligados à ficha do equipamento</span> : null}
        {d.mapa?.orto ? <span>· voo de {d.mapa.orto.voo.split('-').reverse().join('/')}</span> : null}
      </div>

      {d.pode_editar ? (
        <Marcar usinaId={usinaId} modo={modo} setModo={(m) => { setModo(m); setPonto(null) }} />
      ) : d.por_que_nao_edita ? (
        <p className="text-[13px] text-fraco">{d.por_que_nao_edita}</p>
      ) : null}

      <div ref={caixa} className={`h-[calc(100dvh-320px)] min-h-[420px] w-full overflow-hidden rounded-campo border border-borda ${
        modo.tipo === 'marcar' ? 'cursor-crosshair' : ''}`} />

      {escolhido ? (
        <Cartao>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-semibold text-forte">{escolhido.node_nome || escolhido.nome || ROTULO[escolhido.tipo]}</div>
              <div className="text-[13px] text-fraco">
                {ROTULO[escolhido.tipo] || escolhido.tipo}
                {escolhido.node_id ? '' : escolhido.ambiguo ? ' · nome repetido no cadastro: não liguei'
                  : ' · sem ficha de equipamento com esse nome'}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {d.pode_editar && escolhido.node_id ? (
                <a className="inline-flex min-h-[38px] items-center rounded-campo border border-borda px-3 text-sm text-corpo hover:bg-superficie-alta"
                  href={`${FICHA}/${escolhido.node_id}`} target="_blank" rel="noreferrer">Abrir a ficha</a>
              ) : null}
              {d.pode_editar && escolhido.node_id && escolhido.geometria?.type === 'Point' ? (
                <Botao variante="secundario" onClick={() => { setModo({ tipo: 'marcar', equipamento: { node_id: escolhido.node_id as number,
                  nome: escolhido.node_nome || escolhido.nome || 'equipamento' } }); setPonto(null) }}>Mover</Botao>
              ) : null}
            </div>
          </div>
        </Cartao>
      ) : null}

      {modo.tipo === 'marcar' && ponto ? (
        <Confirmar usinaId={usinaId} equipamento={modo.equipamento} ponto={ponto}
          aoFechar={() => setPonto(null)} aoGravar={() => { setModo({ tipo: 'nada' }); setPonto(null); setEscolhido(null); recarregar() }} />
      ) : null}
    </div>
  )
}

/** A busca do equipamento a marcar (lista que filtra enquanto se digita) e o "toque no mapa". */
function Marcar({ usinaId, modo, setModo }: { usinaId: number; modo: Modo; setModo: (m: Modo) => void }) {
  const [busca, setBusca] = useState('')
  const [achados, setAchados] = useState<EquipamentoAchado[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    const termo = busca.trim()
    if (termo.length < 2) {
      setAchados(null)
      return
    }
    let vivo = true
    const t = window.setTimeout(() => {
      buscarEquipamentos(usinaId, termo)
        .then((r) => { if (vivo) { setAchados(r); setErro(null) } })
        .catch((e) => { if (vivo) setErro(mensagemDeErro(e)) })
    }, 300)
    return () => { vivo = false; window.clearTimeout(t) }
  }, [busca, usinaId])

  if (modo.tipo === 'marcar') {
    return (
      <Aviso tom="semDados">
        <span className="inline-flex flex-wrap items-center gap-3">
          <span><MapPinned size={15} className="mr-1 inline" aria-hidden />Toque no mapa onde fica <b>{modo.equipamento.nome}</b>.</span>
          <Botao variante="secundario" onClick={() => setModo({ tipo: 'nada' })}>Cancelar</Botao>
        </span>
      </Aviso>
    )
  }
  return (
    <div className="space-y-2">
      <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Marcar no mapa: qual equipamento?" aria-label="Marcar no mapa: o equipamento (ex.: câmera 1, inversor 3)"
        className="min-h-[38px] w-full max-w-xl rounded-campo border border-borda bg-superficie px-3 text-sm text-corpo" />
      {erro ? <p className="text-[13px] text-tom-parado">{erro}</p> : null}
      {achados !== null && achados.length === 0 ? <p className="text-[13px] text-fraco">Nenhum equipamento com esse nome.</p> : null}
      {achados?.length ? (
        <ul className="max-w-xl divide-y divide-borda rounded-campo border border-borda">
          {achados.slice(0, 30).map((a) => (
            <li key={a.node_id}>
              <button type="button" className="w-full px-3 py-2 text-left text-sm text-corpo hover:bg-superficie-alta"
                onClick={() => { setModo({ tipo: 'marcar', equipamento: { node_id: a.node_id, nome: a.nome } }); setBusca(''); setAchados(null) }}>
                <span className="font-medium text-forte">{a.nome}</span>
                {a.local ? <span className="text-fraco"> · {a.local}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function Confirmar({ usinaId, equipamento, ponto, aoFechar, aoGravar }: {
  usinaId: number; equipamento: { node_id: number; nome: string }; ponto: Ponto; aoFechar: () => void; aoGravar: () => void
}) {
  const [gravando, setGravando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  return (
    <Modal titulo="Marcar no mapa" aberto aoFechar={aoFechar} largura="max-w-lg">
      <p className="text-sm text-corpo">
        <b>{equipamento.nome}</b> fica aqui: {numero(ponto.lat, 6)}, {numero(ponto.lng, 6)}. A posição vale para todos os
        mapas da usina.
      </p>
      {erro ? <p className="mt-2 text-sm text-tom-parado">{erro}</p> : null}
      <div className="mt-4 flex justify-end gap-2">
        <Botao variante="secundario" onClick={aoFechar}>Cancelar</Botao>
        <Botao
          variante="primario"
          desabilitado={gravando}
          onClick={() => {
            setGravando(true)
            marcarNoMapa(usinaId, equipamento.node_id, ponto.lat, ponto.lng)
              .then(aoGravar)
              .catch((e) => { setErro(mensagemDeErro(e)); setGravando(false) })
          }}
        >
          {gravando ? 'Gravando…' : 'Marcar aqui'}
        </Botao>
      </div>
    </Modal>
  )
}
