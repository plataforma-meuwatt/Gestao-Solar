/**
 * MAPA ÚNICO da usina — gestao.solar/usinas/<id>/mapa (e o atalho gestao.solar/mapa/<id>).
 *
 * O dono (18/11/2026): "o mapa pode ser tipo gestao.solar/mapa/usina … todos usam o mesmo"; depois: "quero que todos
 * possam editar, todos é mw, mp e mg … se uma string der problema quero que pinte lá … cadastrar as strings,
 * inversores, trafos, etc tudo no mapa … um sistema de filtro realmente top". O dono da usina vê; a O&M edita.
 *
 * As CAMADAS, cada uma editada com a permissão do produto dela (o servidor confere):
 * - Monitoramento: string, inversor, trafo, mesa… desenhados aqui (ponto, linha ou área) e gravados no mapa do
 *   monitoramento com o token da pessoa;
 * - Manutenção: o equipamento da árvore (o "Marcar" e o "Mover" de antes);
 * - Câmeras: a câmera ligada ao meuGuarda (a posição também pelo "Marcar").
 * A COR vem do estado que o monitoramento calcula (alarme, problema, sem dado); sem essa leitura, nada é pintado de
 * "normal" — a faixa diz que o estado não foi lido. `?destaque=<id>` centraliza e realça um objeto (o link do bot);
 * `?print=1` mostra só o mapa, para a foto que o bot manda.
 */

import 'leaflet/dist/leaflet.css'

import L from 'leaflet'
import { Crosshair, MapPinned, PenLine } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'

import { Aviso, Botao, Cartao, Combobox, ComboboxMulti, Modal, Pagina, Segmentado, Tela4Estados, type Opcao } from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { numero } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'

import {
  alterarObjeto,
  apagarObjeto,
  buscarEquipamentos,
  caminhoDoMapa,
  desenharObjeto,
  marcarNoMapa,
  ligacoesDoMapa,
  type Desenho,
  type EquipamentoAchado,
  type MapaOut,
  type ObjetoDoMapa,
  type LigacoesDoMapa,
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
/** O que se desenha na camada do monitoramento (o servidor confere a mesma lista). */
const TIPOS_DESENHO = ['string', 'inversor', 'caixa_juncao', 'transformador', 'subestacao', 'estacao', 'mesa', 'tracker_fileira', 'outro']

/** O estado pinta por cima da cor do tipo — "normal" fica com a cor do tipo. */
const COR_ESTADO: Record<string, string> = { alarme: '#ef4444', problema: '#f97316', sem_dado: '#64748b' }
const ROTULO_ESTADO: Record<string, string> = {
  alarme: 'Em alarme', problema: 'Com problema', sem_dado: 'Sem dado', ok: 'Normal', sem_leitura: 'Sem ligação ao equipamento',
  fora: 'Sem estado calculado',
}
/** A que equipamento cada tipo se liga (a régua do monitoramento). */
const LIGA_VAGA = ['string', 'mesa', 'inversor']
const LIGA_STRING = ['string', 'mesa']
const LIGA_TRAFO = ['transformador', 'subestacao']
export type Camada = 'monitoramento' | 'manutencao' | 'cameras'
const ROTULO_CAMADA: Record<Camada, string> = { monitoramento: 'Monitoramento', manutencao: 'Manutenção', cameras: 'Câmeras' }

/** A ficha do equipamento (só a O&M abre: ela tem conta no sistema de manutenção). */
const FICHA = 'https://app.meuplano.solar/ativos'
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

type Ponto = { lat: number; lng: number }
type Forma = Desenho['type']
type Modo =
  | { tipo: 'nada' }
  | { tipo: 'marcar'; equipamento: { node_id: number; nome: string } }
  | { tipo: 'desenhar'; forma: Forma; objeto: { tipo: string; nome: string }; alvo: number | null; pontos: Ponto[] }

export type Filtro = { busca: string; tipos: string[] | null; camadas: string[] | null; estados: string[] | null }
const SEM_FILTRO: Filtro = { busca: '', tipos: null, camadas: null, estados: null }

/** A camada de um objeto: o equipamento da árvore é da manutenção; a câmera, das câmeras; o resto, do monitoramento. */
export function camadaDe(o: ObjetoDoMapa): Camada {
  if (o.mg_camera_id || o.tipo === 'camera' || o.node_tipo === 'camera') return 'cameras'
  if ((o.origem ?? '').startsWith('meuplano:')) return 'manutencao'
  return 'monitoramento'
}

/** O estado do objeto: `null` quando o estado não foi lido (nenhum "normal" inventado). Fora da lista do
 *  monitoramento: o desenho que se liga e não está ligado é "sem ligação" (o que falta fazer); o resto (câmera,
 *  equipamento da árvore, fileira de tracker) é "sem estado calculado" — nunca "normal". */
export function estadoDe(d: MapaOut, o: ObjetoDoMapa): string | null {
  if (!d.estado) return null
  const e = d.estado.objetos[String(o.id)]?.estado
  if (e) return e
  const ligavel = LIGA_VAGA.includes(o.tipo) || LIGA_TRAFO.includes(o.tipo)
  const ligado = o.slot_id != null || o.transformer_id != null
  return camadaDe(o) === 'monitoramento' && ligavel && !ligado ? 'sem_leitura' : 'fora'
}

const semAcento = (t: unknown) => String(t ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

export function passa(d: MapaOut, o: ObjetoDoMapa, f: Filtro): boolean {
  if (f.tipos !== null && !f.tipos.includes(o.tipo)) return false
  if (f.camadas !== null && !f.camadas.includes(camadaDe(o))) return false
  if (f.estados !== null) {
    const e = estadoDe(d, o)
    if (e === null || !f.estados.includes(e)) return false
  }
  const q = semAcento(f.busca).trim()
  if (q) {
    const texto = semAcento([o.nome, o.node_nome, ROTULO[o.tipo], d.estado?.objetos[String(o.id)]?.motivo].join(' '))
    if (!q.split(/\s+/).every((p) => texto.includes(p))) return false
  }
  return true
}

/** GeoJSON é [lon, lat]; o Leaflet quer [lat, lon]. */
function ll(p: unknown): L.LatLngTuple | null {
  return Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'number' ? [p[1], p[0]] : null
}

function pontosDo(o: ObjetoDoMapa): L.LatLngTuple[] {
  const g = o.geometria
  if (!g) return []
  if (g.type === 'Point') return [ll(g.coordinates)].filter((p): p is L.LatLngTuple => p !== null)
  const lista = g.type === 'LineString' ? (g.coordinates as unknown[]) : ((g.coordinates as unknown[][]) || [])[0] || []
  return (lista || []).map(ll).filter((p): p is L.LatLngTuple => p !== null)
}

function camadaDo(o: ObjetoDoMapa, estado: string | null, realce: boolean): L.Layer | null {
  const g = o.geometria
  if (!g) return null
  const cor = (estado && COR_ESTADO[estado]) || COR[o.tipo] || COR.outro
  // sem dado: tracejado; sem ligação (o estado não se calcula para ele): pontilhado — nenhum dos dois parece "normal"
  const tracejado = estado === 'sem_dado' ? '4 4' : estado === 'sem_leitura' ? '1 5' : undefined
  const pts = pontosDo(o)
  if (!pts.length) return null
  if (g.type === 'Point') {
    return L.circleMarker(pts[0], { radius: realce ? 12 : o.node_id ? 8 : 6, color: realce ? '#ffffff' : cor, fillColor: cor,
      fillOpacity: 0.9, weight: realce ? 4 : 2, dashArray: tracejado })
  }
  if (g.type === 'LineString') return L.polyline(pts, { color: cor, weight: realce ? 8 : 4, dashArray: tracejado })
  return L.polygon(pts, { color: realce ? '#ffffff' : cor, fillColor: cor, weight: realce ? 4 : 2, fillOpacity: realce ? 0.6 : 0.3,
    dashArray: tracejado })
}

/** O desenho em GeoJSON ([lon, lat]); a área fecha o anel. */
export function desenhoDe(forma: Forma, pontos: Ponto[]): Desenho | null {
  const c = pontos.map((p) => [p.lng, p.lat])
  if (forma === 'Point') return c.length === 1 ? { type: 'Point', coordinates: c[0] } : null
  if (forma === 'LineString') return c.length >= 2 ? { type: 'LineString', coordinates: c } : null
  return c.length >= 3 ? { type: 'Polygon', coordinates: [[...c, c[0]]] } : null
}

const horaBrasilia = (iso: string | null | undefined) => {
  if (!iso) return null
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? null
    : d.toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export default function Mapa() {
  const { id } = useParams()
  const [busca] = useSearchParams()
  const usinaId = Number(id)
  const leitura = useLeitura<MapaOut>(caminhoDoMapa(usinaId))
  const destaque = Number(busca.get('destaque')) || null
  if (busca.get('print') === '1') {
    // só o mapa: a foto que o bot manda (sem menu, filtro nem botões)
    return <Tela4Estados leitura={leitura}>{(d) => <Conteudo d={d} usinaId={usinaId} recarregar={leitura.recarregar} destaque={destaque} soMapa />}</Tela4Estados>
  }
  return (
    <Pagina
      rotulo="O MAPA ÚNICO DA USINA"
      titulo={leitura.dados ? `Mapa · ${leitura.dados.usina.nome}` : 'Mapa da usina'}
      subtitulo="O voo e cada equipamento marcado, com o estado de cada um; toque num objeto para ver qual é."
    >
      <Tela4Estados leitura={leitura}>{(d) => <Conteudo d={d} usinaId={usinaId} recarregar={leitura.recarregar} destaque={destaque} />}</Tela4Estados>
    </Pagina>
  )
}

function Conteudo({ d, usinaId, recarregar, destaque, soMapa = false }: {
  d: MapaOut; usinaId: number; recarregar: () => void; destaque: number | null; soMapa?: boolean
}) {
  const caixa = useRef<HTMLDivElement>(null)
  const mapa = useRef<L.Map | null>(null)
  const camadas = useRef<L.LayerGroup | null>(null)
  const rascunho = useRef<L.LayerGroup | null>(null)
  const enquadrado = useRef(false)
  // a foto do bot só sai com o satélite E o voo (quando há voo) carregados: `#mapa-unico[data-pronto="1"]`
  const carregado = useRef({ fundo: false, voo: true })
  const marcarPronto = () => {
    if (carregado.current.fundo && carregado.current.voo) caixa.current?.setAttribute('data-pronto', '1')
  }
  const objetos = useMemo(() => d.mapa?.objetos ?? [], [d])
  const [escolhido, setEscolhido] = useState<ObjetoDoMapa | null>(() => objetos.find((o) => o.id === destaque) ?? null)
  const [modo, setModo] = useState<Modo>({ tipo: 'nada' })
  const [ponto, setPonto] = useState<Ponto | null>(null)
  const [filtro, setFiltro] = useState<Filtro>(SEM_FILTRO)
  const modoRef = useRef<Modo>(modo)
  modoRef.current = modo

  const edicao = d.edicao ?? { monitoramento: d.por_que_nao_edita, manutencao: d.por_que_nao_edita }
  const visiveis = useMemo(() => objetos.filter((o) => passa(d, o, filtro)), [d, objetos, filtro])
  const filtrando = filtro.busca.trim() !== '' || filtro.tipos !== null || filtro.camadas !== null || filtro.estados !== null

  // o mapa nasce uma vez; as camadas se refazem quando o dado, o filtro ou o escolhido mudam
  useEffect(() => {
    if (!caixa.current || mapa.current) return
    const m = L.map(caixa.current, { zoomControl: !soMapa, maxZoom: 21 })
    m.attributionControl.setPrefix('Leaflet')
    // o Esri só tem imagem até o zoom 18 (medido em 08/11/2026): acima disso, aumenta o 18 em vez do "sem imagem"
    const fundo = L.tileLayer(ESRI, { maxZoom: 21, maxNativeZoom: 18, attribution: 'Imagens © Esri' })
    fundo.on?.('load', () => { carregado.current.fundo = true; marcarPronto() })
    fundo.addTo(m)
    camadas.current = L.layerGroup().addTo(m)
    rascunho.current = L.layerGroup().addTo(m)
    m.on('click', (e: L.LeafletMouseEvent) => {
      const p = { lat: e.latlng.lat, lng: e.latlng.lng }
      if (modoRef.current.tipo === 'marcar') setPonto(p)
      // pelo estado MAIS RECENTE: dois toques rápidos não perdem ponto
      setModo((atual) => (atual.tipo === 'desenhar'
        ? { ...atual, pontos: atual.forma === 'Point' ? [p] : [...atual.pontos, p] } : atual))
    })
    mapa.current = m
    return () => {
      m.remove()
      mapa.current = null
    }
  }, [soMapa])

  useEffect(() => {
    const m = mapa.current
    const grupo = camadas.current
    if (!m || !grupo) return
    grupo.clearLayers()
    const enquadrar: L.LatLngTuple[] = []
    const u = d.mapa?.usina
    if (d.mapa?.orto?.url) {
      const voo = L.imageOverlay(d.mapa.orto.url, d.mapa.orto.bounds)
      if (!caixa.current?.hasAttribute('data-pronto')) carregado.current.voo = false
      voo.on?.('load', () => { carregado.current.voo = true; marcarPronto() })
      // o voo que não carrega não vira foto "sem voo" calada: `data-voo="falhou"` diz ao bot para desistir
      voo.on?.('error', () => caixa.current?.setAttribute('data-voo', 'falhou'))
      voo.addTo(grupo)
      enquadrar.push(...(d.mapa.orto.bounds as L.LatLngTuple[]))
    }
    const contorno = (u?.area_poligono ?? []).filter((p) => Array.isArray(p) && p.length >= 2) as L.LatLngTuple[]
    if (contorno.length >= 3) L.polygon(contorno, { color: '#fbbf24', weight: 2, fillOpacity: 0.04, dashArray: '6 4' }).addTo(grupo)
    if (u?.latitude != null && u?.longitude != null) {
      L.circleMarker([u.latitude, u.longitude], { radius: 6, color: '#fbbf24', fillColor: '#ffffff', fillOpacity: 1, weight: 3 }).addTo(grupo)
    }
    // o realçado por último: fica por cima dos outros
    const ordem = [...visiveis].sort((a, b) => Number(a.id === escolhido?.id) - Number(b.id === escolhido?.id))
    for (const o of ordem) {
      const estado = estadoDe(d, o)
      const c = camadaDo(o, estado, o.id === escolhido?.id)
      if (!c) continue
      const dica = document.createElement('div')
      const motivo = d.estado?.objetos[String(o.id)]?.motivo
      dica.textContent = [o.node_nome || o.nome || ROTULO[o.tipo] || o.tipo, ROTULO[o.tipo] || o.tipo,
        estado && estado !== 'ok' ? ROTULO_ESTADO[estado] : null, motivo].filter(Boolean).join(' · ')   // texto, nunca HTML
      ;(c as L.Path).bindTooltip(dica, { sticky: true })
      c.on('click', () => setEscolhido(o))
      c.addTo(grupo)
      if (!d.mapa?.orto) enquadrar.push(...pontosDo(o))
    }
    if (enquadrado.current) return
    enquadrado.current = true
    const alvo = objetos.find((o) => o.id === destaque)
    if (alvo && pontosDo(alvo).length) {
      m.fitBounds(L.latLngBounds(pontosDo(alvo)), { maxZoom: 20, padding: [80, 80] })
      return
    }
    if (!enquadrar.length && contorno.length) enquadrar.push(...contorno)
    if (!enquadrar.length && u?.latitude != null && u?.longitude != null) enquadrar.push([u.latitude, u.longitude])
    if (enquadrar.length) m.fitBounds(L.latLngBounds(enquadrar), { maxZoom: 18, padding: [24, 24] })
    else m.setView([-15.8, -47.9], 4)
  }, [d, objetos, visiveis, escolhido, destaque])

  // o rascunho do desenho em andamento
  useEffect(() => {
    const g = rascunho.current
    if (!g) return
    g.clearLayers()
    if (modo.tipo !== 'desenhar' || !modo.pontos.length) return
    const pts = modo.pontos.map((p) => [p.lat, p.lng] as L.LatLngTuple)
    const cor = COR[modo.objeto.tipo] ?? COR.outro
    if (modo.forma === 'Polygon' && pts.length >= 3) L.polygon(pts, { color: cor, dashArray: '6 4', fillOpacity: 0.2 }).addTo(g)
    else if (pts.length >= 2) L.polyline(pts, { color: cor, dashArray: '6 4' }).addTo(g)
    for (const p of pts) L.circleMarker(p, { radius: 5, color: '#ffffff', fillColor: cor, fillOpacity: 1, weight: 2 }).addTo(g)
  }, [modo])

  function enquadrarFiltrados() {
    const pts = visiveis.flatMap(pontosDo)
    if (pts.length && mapa.current) mapa.current.fitBounds(L.latLngBounds(pts), { maxZoom: 20, padding: [40, 40] })
  }
  function focar(o: ObjetoDoMapa) {
    setEscolhido(o)
    const pts = pontosDo(o)
    if (pts.length && mapa.current) mapa.current.fitBounds(L.latLngBounds(pts), { maxZoom: 20, padding: [80, 80] })
  }

  const legendaEstado = d.estado ? (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      {(['alarme', 'problema', 'sem_dado'] as const).map((e) => (
        <span key={e} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: COR_ESTADO[e] }} />{ROTULO_ESTADO[e]}
        </span>
      ))}
      {objetos.some((o) => estadoDe(d, o) === 'sem_leitura') ? (
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full border border-dotted border-fraco" />{ROTULO_ESTADO.sem_leitura}
        </span>
      ) : null}
      {horaBrasilia(d.estado.dados_de) ? <span>· dados de {horaBrasilia(d.estado.dados_de)}</span>
        : horaBrasilia(d.estado.lido_em) ? <span>· calculado às {horaBrasilia(d.estado.lido_em)}</span> : null}
    </span>
  ) : null

  if (soMapa) {
    const alvo = objetos.find((o) => o.id === destaque)
    const e = alvo ? estadoDe(d, alvo) : null
    return (
      // `#mapa-unico-foto` é o bloco que o bot fotografa (a legenda, o mapa e as cores; sem o menu do portal)
      <div id="mapa-unico-foto" className="space-y-2 p-2">
        <div className="text-sm text-forte">
          <b>{d.usina.nome}</b>
          {alvo ? <> · {alvo.node_nome || alvo.nome || ROTULO[alvo.tipo]} ({ROTULO[alvo.tipo] || alvo.tipo})
            {e && e !== 'ok' ? <> · {ROTULO_ESTADO[e]}{d.estado?.objetos[String(alvo.id)]?.motivo ? `: ${d.estado.objetos[String(alvo.id)].motivo}` : ''}</> : null}</> : null}
        </div>
        {d.aviso || d.estado_aviso ? <div className="text-[13px] text-corpo">{d.aviso || d.estado_aviso}</div> : null}
        {/* abaixo do cabeçalho e acima do rodapé fixos do portal: a foto pega o mapa inteiro e a legenda */}
        <div id="mapa-unico" ref={caixa} className="h-[calc(100dvh-200px)] min-h-[360px] w-full overflow-hidden rounded-campo border border-borda" />
        <div className="text-[12px] text-fraco">{legendaEstado}</div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}
      {d.estado_aviso && objetos.length ? <Aviso tom="semDados">{d.estado_aviso} As cores mostram só o tipo de cada objeto.</Aviso> : null}
      {d.mapa && !d.mapa.vinculado ? (
        <Aviso>O voo e as marcações ainda não estão ligados a esta usina: o mapa mostra só o pino e o contorno.</Aviso>
      ) : null}
      {d.mapa && d.mapa.vinculado && !d.mapa.orto && objetos.length === 0 && !d.aviso ? (
        <Aviso tom="semDados">O mapa desta usina ainda está vazio: o voo entra pelo TermoVision, e a O&M desenha os equipamentos aqui
          ou marca pelo WhatsApp, mandando a localização.</Aviso>
      ) : null}

      {objetos.length ? <Filtros d={d} objetos={objetos} filtro={filtro} setFiltro={setFiltro} /> : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-fraco">
        <span className="text-corpo">{filtrando ? `${visiveis.length} de ${objetos.length} objetos` : `${objetos.length} objetos`}</span>
        {filtrando ? <Botao variante="secundario" onClick={() => setFiltro(SEM_FILTRO)}>Limpar filtros</Botao> : null}
        {visiveis.length ? (
          <button type="button" onClick={enquadrarFiltrados} className="inline-flex items-center gap-1 text-corpo underline">
            <Crosshair size={14} aria-hidden />Enquadrar {filtrando ? 'o filtrado' : 'tudo'}
          </button>
        ) : null}
        {legendaEstado}
        {d.mapa?.orto ? <span>· voo de {d.mapa.orto.voo.split('-').reverse().join('/')}</span> : null}
      </div>
      {filtrando && visiveis.length === 0 ? (
        <Aviso tom="semDados">Nenhum objeto passa nesse filtro. <button type="button" className="underline" onClick={() => setFiltro(SEM_FILTRO)}>Mostrar todos</button></Aviso>
      ) : null}

      <Ferramentas usinaId={usinaId} edicao={edicao} modo={modo} recarregar={recarregar}
        setModo={(m) => { setModo(m); setPonto(null) }} />

      <div ref={caixa} className={`h-[calc(100dvh-360px)] min-h-[420px] w-full overflow-hidden rounded-campo border border-borda ${
        modo.tipo !== 'nada' ? 'cursor-crosshair' : ''}`} />

      {escolhido ? (
        <Escolhido d={d} usinaId={usinaId} o={escolhido} edicao={edicao} fechar={() => setEscolhido(null)}
          recarregar={() => { setEscolhido(null); recarregar() }}
          setModo={(m) => { setModo(m); setPonto(null) }} />
      ) : null}

      {visiveis.length ? <Lista d={d} objetos={visiveis} escolhido={escolhido} focar={focar} /> : null}

      {modo.tipo === 'marcar' && ponto ? (
        <Confirmar usinaId={usinaId} equipamento={modo.equipamento} ponto={ponto}
          aoFechar={() => setPonto(null)} aoGravar={() => { setModo({ tipo: 'nada' }); setPonto(null); setEscolhido(null); recarregar() }} />
      ) : null}
    </div>
  )
}

/** O filtro: busca (nome, tipo, motivo), tipo, camada e estado — listas pesquisáveis, nunca chips. */
function Filtros({ d, objetos, filtro, setFiltro }: {
  d: MapaOut; objetos: ObjetoDoMapa[]; filtro: Filtro; setFiltro: (f: Filtro) => void
}) {
  const contar = (chave: (o: ObjetoDoMapa) => string | null) => {
    const n = new Map<string, number>()
    for (const o of objetos) {
      const k = chave(o)
      if (k === null) continue
      const atual = n.get(k)
      n.set(k, atual === undefined ? 1 : atual + 1)
    }
    return n
  }
  const tipos = contar((o) => o.tipo)
  const camadas = contar(camadaDe)
  const estados = contar((o) => estadoDe(d, o))
  const op = (n: Map<string, number>, rotulo: (k: string) => string): Opcao[] =>
    [...n.entries()].map(([k, q]) => ({ valor: k, rotulo: `${rotulo(k)} · ${q}` }))
  const opEstados: Opcao[] = d.estado
    ? op(estados, (k) => ROTULO_ESTADO[k] || k)
    : [{ valor: 'x', rotulo: 'Estado', detalhe: d.estado_aviso || 'O estado não foi lido.', desabilitada: true }]
  return (
    <div className="flex flex-wrap items-start gap-2">
      <input value={filtro.busca} onChange={(e) => setFiltro({ ...filtro, busca: e.target.value })}
        placeholder="Buscar: nome, tipo ou motivo" aria-label="Buscar no mapa"
        className="min-h-[38px] w-full max-w-sm rounded-campo border border-borda bg-superficie px-3 text-sm text-corpo" />
      <ComboboxMulti opcoes={op(tipos, (k) => ROTULO[k] || k)} valor={filtro.tipos} substantivo="tipos"
        onEscolher={(v) => setFiltro({ ...filtro, tipos: v })} className="w-56" />
      <ComboboxMulti opcoes={op(camadas, (k) => ROTULO_CAMADA[k as Camada] || k)} valor={filtro.camadas} substantivo="camadas"
        rotuloTodos="todas" onEscolher={(v) => setFiltro({ ...filtro, camadas: v })} className="w-56" />
      <ComboboxMulti opcoes={opEstados} valor={d.estado ? filtro.estados : null} substantivo="estados"
        onEscolher={(v) => setFiltro({ ...filtro, estados: v })} className="w-56" />
    </div>
  )
}

/** A lista do que está no mapa (o que passa no filtro): o problema primeiro, e o toque leva até ele. */
function Lista({ d, objetos, escolhido, focar }: {
  d: MapaOut; objetos: ObjetoDoMapa[]; escolhido: ObjetoDoMapa | null; focar: (o: ObjetoDoMapa) => void
}) {
  const peso: Record<string, number> = { alarme: 0, problema: 1, sem_dado: 2 }
  const ordem = [...objetos].sort((a, b) => (peso[estadoDe(d, a) ?? ''] ?? 9) - (peso[estadoDe(d, b) ?? ''] ?? 9)
    || semAcento(a.node_nome || a.nome).localeCompare(semAcento(b.node_nome || b.nome), 'pt-BR', { numeric: true }))
  return (
    <ul aria-label="Objetos do mapa" className="max-h-80 divide-y divide-borda overflow-auto rounded-campo border border-borda">
      {ordem.map((o) => {
        const e = estadoDe(d, o)
        const motivo = d.estado?.objetos[String(o.id)]?.motivo
        return (
          <li key={o.id}>
            <button type="button" onClick={() => focar(o)}
              className={`flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-left text-sm hover:bg-superficie-alta ${
                escolhido?.id === o.id ? 'bg-superficie-alta' : ''}`}>
              <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: (e && COR_ESTADO[e]) || COR[o.tipo] || COR.outro }} />
              <span className="font-medium text-forte [overflow-wrap:anywhere]">{o.node_nome || o.nome || ROTULO[o.tipo]}</span>
              <span className="text-fraco">{ROTULO[o.tipo] || o.tipo} · {ROTULO_CAMADA[camadaDe(o)]}</span>
              {e && e !== 'ok' ? <span className="text-corpo [overflow-wrap:anywhere]">{ROTULO_ESTADO[e]}{motivo ? `: ${motivo}` : ''}</span> : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

/** Desenhar (monitoramento) e marcar o equipamento (manutenção), cada um com a permissão do produto. */
function Ferramentas({ usinaId, edicao, modo, setModo, recarregar }: {
  usinaId: number; edicao: { monitoramento: string | null; manutencao: string | null }; modo: Modo
  setModo: (m: Modo) => void; recarregar: () => void
}) {
  const [novo, setNovo] = useState<{ tipo: string; nome: string; forma: Forma } | null>(null)
  if (modo.tipo === 'desenhar') return <Desenhando usinaId={usinaId} modo={modo} setModo={setModo} recarregar={recarregar} />
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
      {edicao.monitoramento === null ? (
        novo ? (
          <div className="flex flex-wrap items-center gap-2 rounded-campo border border-borda p-2">
            <Combobox opcoes={TIPOS_DESENHO.map((t) => ({ valor: t, rotulo: ROTULO[t] }))} valor={novo.tipo}
              onEscolher={(t) => setNovo({ ...novo, tipo: t })} className="w-52" />
            <input value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })} maxLength={80}
              placeholder="Nome (ex.: Inv 03 · S12)" aria-label="Nome do objeto"
              className="min-h-[38px] w-56 rounded-campo border border-borda bg-superficie px-3 text-sm text-corpo" />
            <Segmentado opcoes={[{ valor: 'Point', rotulo: 'Ponto' }, { valor: 'LineString', rotulo: 'Linha' }, { valor: 'Polygon', rotulo: 'Área' }]}
              valor={novo.forma} onEscolher={(f) => setNovo({ ...novo, forma: f as Forma })} />
            <Botao variante="primario" onClick={() => {
              setModo({ tipo: 'desenhar', forma: novo.forma, objeto: { tipo: novo.tipo, nome: novo.nome }, alvo: null, pontos: [] })
              setNovo(null)
            }}>Desenhar no mapa</Botao>
            <Botao variante="secundario" onClick={() => setNovo(null)}>Cancelar</Botao>
          </div>
        ) : (
          <Botao variante="secundario" onClick={() => setNovo({ tipo: 'string', nome: '', forma: 'LineString' })}>
            <PenLine size={15} className="mr-1 inline" aria-hidden />Desenhar string, inversor, trafo…
          </Botao>
        )
      ) : null}
      {/* o porquê de não poder desenhar (outra usina do monitoramento, mapa não lido…), quando a pessoa edita o resto */}
      {edicao.monitoramento !== null && edicao.monitoramento !== edicao.manutencao ? (
        <p className="text-[13px] text-fraco">{edicao.monitoramento}</p>
      ) : null}
      {edicao.manutencao === null ? <Marcar usinaId={usinaId} setModo={setModo} /> : null}
      {edicao.monitoramento !== null && edicao.manutencao !== null && edicao.manutencao ? (
        <p className="text-[13px] text-fraco">{edicao.manutencao}</p>
      ) : null}
    </div>
  )
}

/** O desenho em andamento: toque para pôr cada ponto; concluir grava (com a confirmação do que vai). */
function Desenhando({ usinaId, modo, setModo, recarregar }: {
  usinaId: number; modo: Extract<Modo, { tipo: 'desenhar' }>; setModo: (m: Modo) => void; recarregar: () => void
}) {
  const [gravando, setGravando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const desenho = desenhoDe(modo.forma, modo.pontos)
  const falta = modo.forma === 'Point' ? 'o ponto' : modo.forma === 'LineString' ? 'pelo menos 2 pontos' : 'pelo menos 3 pontos'
  return (
    <Aviso tom="semDados">
      <span className="flex flex-wrap items-center gap-3">
        <span>
          <PenLine size={15} className="mr-1 inline" aria-hidden />
          {modo.alvo ? 'Redesenhando' : 'Desenhando'} <b>{modo.objeto.nome || ROTULO[modo.objeto.tipo]}</b> ({ROTULO[modo.objeto.tipo]}):
          toque no mapa para pôr {falta}. {modo.pontos.length ? `${modo.pontos.length} ponto(s).` : ''}
        </span>
        {modo.pontos.length && modo.forma !== 'Point' ? (
          <Botao variante="secundario" onClick={() => setModo({ ...modo, pontos: modo.pontos.slice(0, -1) })}>Desfazer ponto</Botao>
        ) : null}
        <Botao variante="primario" desabilitado={!desenho || gravando} onClick={() => {
          if (!desenho) return
          setGravando(true)
          setErro(null)
          const feito = modo.alvo
            ? alterarObjeto(usinaId, modo.alvo, { geometria: desenho })
            : desenharObjeto(usinaId, modo.objeto.tipo, modo.objeto.nome.trim() || null, desenho)
          feito.then(() => { setModo({ tipo: 'nada' }); recarregar() })
            .catch((e) => { setErro(mensagemDeErro(e)); setGravando(false) })
        }}>{gravando ? 'Gravando…' : 'Concluir'}</Botao>
        <Botao variante="secundario" onClick={() => setModo({ tipo: 'nada' })}>Cancelar</Botao>
      </span>
      {!modo.alvo && LIGA_VAGA.includes(modo.objeto.tipo) ? (
        <span className="mt-1 block">Depois de gravar, toque no desenho e ligue ao equipamento: é a ligação que dá a cor do estado.</span>
      ) : null}
      {erro ? <span className="mt-1 block text-tom-parado">{erro}</span> : null}
    </Aviso>
  )
}

/** O objeto tocado: o que é, o estado e o que dá para fazer com ele (cada camada com a sua permissão). */
function Escolhido({ d, usinaId, o, edicao, fechar, recarregar, setModo }: {
  d: MapaOut; usinaId: number; o: ObjetoDoMapa; edicao: { monitoramento: string | null; manutencao: string | null }
  fechar: () => void; recarregar: () => void; setModo: (m: Modo) => void
}) {
  const [acao, setAcao] = useState<Acao | null>(null)
  const camada = camadaDe(o)
  const e = estadoDe(d, o)
  const info = d.estado?.objetos[String(o.id)]
  const doVoo = (o.origem ?? '').startsWith('termovision:')
  const editaMonitoramento = camada === 'monitoramento' && edicao.monitoramento === null
  const completo = d.mapa_completo === true
  const ligado = o.slot_id != null || o.transformer_id != null
  const moveEquipamento = edicao.manutencao === null && !!o.node_id && o.geometria?.type === 'Point'
  return (
    <Cartao>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold text-forte [overflow-wrap:anywhere]">{o.node_nome || o.nome || ROTULO[o.tipo]}</div>
          <div className="text-[13px] text-fraco">
            {ROTULO[o.tipo] || o.tipo} · camada {ROTULO_CAMADA[camada]}
            {o.node_id ? '' : o.ambiguo ? ' · nome repetido no cadastro: não liguei' : ''}
          </div>
          <div className="text-[13px] text-corpo [overflow-wrap:anywhere]">
            {e === null ? 'Estado: não lido agora.' : e === 'sem_leitura' ? 'Estado: sem ligação ao equipamento do monitoramento.'
              : e === 'fora' ? 'Estado: o monitoramento não calcula para este objeto.'
              : `${info?.equipamento ? `${info.equipamento} · ` : ''}${ROTULO_ESTADO[e]}${info?.motivo ? `: ${info.motivo}` : ''}`
                + `${info?.desde ? ` · desde ${horaBrasilia(info.desde)}` : ''}${info?.leitura_em ? ` · leitura de ${horaBrasilia(info.leitura_em)}` : ''}`}
          </div>
          {info?.conhecido ? (
            <div className="text-[13px] text-fraco [overflow-wrap:anywhere]">
              A equipe já sabe{info.conhecido.nota ? `: ${info.conhecido.nota}` : ''}{info.conhecido.por ? ` (${info.conhecido.por}` : ''}
              {info.conhecido.por && info.conhecido.ate ? `, até ${horaBrasilia(info.conhecido.ate)})` : info.conhecido.por ? ')' : ''}
            </div>
          ) : null}
          {editaMonitoramento && !completo ? (
            <div className="text-[13px] text-fraco">Mover e ligar ao equipamento chegam quando o monitoramento publicar a versão nova.</div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {edicao.manutencao === null && o.node_id ? (
            <a className="inline-flex min-h-[38px] items-center rounded-campo border border-borda px-3 text-sm text-corpo hover:bg-superficie-alta"
              href={`${FICHA}/${o.node_id}`} target="_blank" rel="noreferrer">Abrir a ficha</a>
          ) : null}
          {moveEquipamento && camada !== 'monitoramento' ? (
            <Botao variante="secundario" onClick={() => setModo({ tipo: 'marcar', equipamento: { node_id: o.node_id as number,
              nome: o.node_nome || o.nome || 'equipamento' } })}>Mover</Botao>
          ) : null}
          {editaMonitoramento ? (
            <>
              {completo && (LIGA_VAGA.includes(o.tipo) || LIGA_TRAFO.includes(o.tipo)) ? (
                <Botao variante="secundario" onClick={() => setAcao('ligar')}>{ligado ? 'Trocar a ligação' : 'Ligar ao equipamento'}</Botao>
              ) : null}
              {completo && ligado ? <Botao variante="secundario" onClick={() => setAcao('soltar')}>Soltar a ligação</Botao> : null}
              {/* o ligado à árvore PELO NOME não se renomeia aqui: renomear o desligaria dela */}
              {o.node_id ? null : <Botao variante="secundario" onClick={() => setAcao('renomear')}>Renomear</Botao>}
              {/* mudar o tipo do ligado pelo nome também o desligaria da árvore (o nome casa dentro do tipo) */}
              {o.node_id ? null : <Botao variante="secundario" onClick={() => setAcao('tipo')}>Mudar o tipo</Botao>}
              {completo && !doVoo && o.geometria ? (
                <Botao variante="secundario" onClick={() => setModo({ tipo: 'desenhar', forma: o.geometria?.type as Forma,
                  objeto: { tipo: o.tipo, nome: o.nome || '' }, alvo: o.id, pontos: [] })}>{o.geometria.type === 'Point' ? 'Mover' : 'Redesenhar'}</Botao>
              ) : null}
              {/* o que veio do voo voltaria na próxima importação (sem a ligação) */}
              {doVoo ? null : <Botao variante="secundario" onClick={() => setAcao('apagar')}>Apagar</Botao>}
            </>
          ) : null}
          <Botao variante="secundario" onClick={fechar}>Fechar</Botao>
        </div>
      </div>
      {acao ? <AcaoNoObjeto usinaId={usinaId} o={o} acao={acao} fechar={() => setAcao(null)} feito={recarregar} /> : null}
    </Cartao>
  )
}

type Acao = 'renomear' | 'tipo' | 'apagar' | 'ligar' | 'soltar'

function AcaoNoObjeto({ usinaId, o, acao, fechar, feito }: {
  usinaId: number; o: ObjetoDoMapa; acao: Acao; fechar: () => void; feito: () => void
}) {
  const [nome, setNome] = useState(o.nome || '')
  const [tipo, setTipo] = useState(o.tipo)
  const [lig, setLig] = useState<LigacoesDoMapa | null>(null)
  const [vaga, setVaga] = useState<number | null>(o.slot_id ?? null)
  const [trafo, setTrafo] = useState<number | null>(o.transformer_id ?? null)
  const deTrafo = LIGA_TRAFO.includes(o.tipo)
  const vagas = lig?.vagas ?? null
  const [entrada, setEntrada] = useState<number | null>(o.string_number ?? null)
  const [gravando, setGravando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const pedeString = LIGA_STRING.includes(o.tipo)
  useEffect(() => {
    if (acao !== 'ligar') return
    let vivo = true
    ligacoesDoMapa(usinaId).then((v) => { if (vivo) setLig(v) }).catch((e) => { if (vivo) setErro(mensagemDeErro(e)) })
    return () => { vivo = false }
  }, [acao, usinaId])
  const titulo = { renomear: 'Renomear', tipo: 'Mudar o tipo', apagar: 'Apagar do mapa', ligar: 'Ligar ao equipamento',
    soltar: 'Soltar a ligação' }[acao]
  const escolhida = vagas?.find((v) => v.slot_id === vaga) ?? null
  const pronto = acao === 'renomear' ? !!nome.trim()
    : acao === 'ligar' ? (deTrafo ? trafo !== null : vaga !== null && (!pedeString || entrada !== null)) : true
  const fazer = () => {
    setGravando(true)
    setErro(null)
    const p = acao === 'apagar' ? apagarObjeto(usinaId, o.id)
      : alterarObjeto(usinaId, o.id, acao === 'renomear' ? { nome: nome.trim() } : acao === 'tipo' ? { tipo }
        : acao === 'soltar' ? { slot_id: null, string_number: null, transformer_id: null }
          : deTrafo ? { transformer_id: trafo } : { slot_id: vaga, ...(pedeString ? { string_number: entrada } : {}) })
    p.then(feito).catch((e) => { setErro(mensagemDeErro(e)); setGravando(false) })
  }
  return (
    <Modal titulo={titulo} aberto aoFechar={fechar} largura="max-w-lg">
      {acao === 'renomear' ? (
        <input value={nome} onChange={(e) => setNome(e.target.value)} maxLength={80} aria-label="Nome novo"
          className="min-h-[38px] w-full rounded-campo border border-borda bg-superficie px-3 text-sm text-corpo" />
      ) : acao === 'tipo' ? (
        <Combobox opcoes={TIPOS_DESENHO.map((t) => ({ valor: t, rotulo: ROTULO[t] }))} valor={tipo} onEscolher={setTipo} />
      ) : acao === 'ligar' && deTrafo ? (
        lig === null && !erro ? <p className="text-sm text-fraco">Lendo os trafos da usina…</p> : lig && lig.trafos.length === 0 ? (
          <p className="text-sm text-corpo">{lig.trafos_aviso || 'O monitoramento não tem trafo ligado às vagas desta usina: não há a quem ligar.'}</p>
        ) : lig ? (
          <Combobox opcoes={lig.trafos.map((t) => ({ valor: String(t.transformer_id), rotulo: t.nome }))}
            valor={trafo === null ? null : String(trafo)} onEscolher={(v) => setTrafo(Number(v))} placeholder="Qual trafo?" />
        ) : null
      ) : acao === 'ligar' ? (
        vagas === null && !erro ? <p className="text-sm text-fraco">Lendo os inversores da usina…</p> : vagas && vagas.length === 0 ? (
          <p className="text-sm text-corpo">O monitoramento não tem inversor com vaga nesta usina: não há a quem ligar.</p>
        ) : vagas ? (
          <div className="space-y-2">
            <Combobox opcoes={vagas.map((v) => ({ valor: String(v.slot_id), rotulo: v.rotulo, detalhe: v.trafo ?? undefined }))}
              valor={vaga === null ? null : String(vaga)} onEscolher={(v) => { setVaga(Number(v)); setEntrada(null) }}
              placeholder="Qual inversor?" />
            {pedeString && escolhida ? (
              <Combobox opcoes={escolhida.strings.map((n) => ({ valor: String(n), rotulo: `String ${n}` }))}
                valor={entrada === null ? null : String(entrada)} onEscolher={(v) => setEntrada(Number(v))} placeholder="Qual string?" />
            ) : null}
          </div>
        ) : null
      ) : acao === 'soltar' ? (
        <p className="text-sm text-corpo">Soltar <b>{o.nome || ROTULO[o.tipo]}</b> do equipamento? Ele deixa de ganhar a cor do estado.</p>
      ) : (
        <p className="text-sm text-corpo">Apagar <b>{o.nome || ROTULO[o.tipo]}</b> do mapa de todos os sistemas? O equipamento não é apagado;
          só o desenho dele.</p>
      )}
      {erro ? <p className="mt-2 text-sm text-tom-parado">{erro}</p> : null}
      <div className="mt-4 flex justify-end gap-2">
        <Botao variante="secundario" onClick={fechar}>Cancelar</Botao>
        <Botao variante="primario" desabilitado={gravando || !pronto} onClick={fazer}>
          {gravando ? 'Gravando…' : acao === 'apagar' ? 'Apagar' : acao === 'soltar' ? 'Soltar' : 'Gravar'}
        </Botao>
      </div>
    </Modal>
  )
}

/** A busca do equipamento da árvore a marcar (lista que filtra enquanto se digita) e o "toque no mapa". */
function Marcar({ usinaId, setModo }: { usinaId: number; setModo: (m: Modo) => void }) {
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
