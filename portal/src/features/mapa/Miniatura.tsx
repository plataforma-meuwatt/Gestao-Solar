/**
 * A miniatura do mapa no Painel da usina (Plano Casa GS, 24/11/2026, o dono: "o mapa deveria ficar logo no início em
 * home, um botão para abrir o mapa, um thumbnail, e aí abre e vê o mapa, para eu poder editar"). A foto de satélite
 * em volta da usina, com os mesmos ladrilhos da tela do mapa, o contorno dela por cima e o atalho para o mapa. Lê só o
 * pino e o contorno (`mapa/usinas/<id>/posicao`, uma leitura leve); sem eles, diz por quê.
 */

import { MapPinned } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useLeitura } from '@/lib/leitura'

const LARGURA = 176
const ALTURA = 100
/** zoom 16 desenhado pela metade: nítido em tela de alta densidade, uns 800 m de largura */
const ZOOM = 16
const LADO = 128

const ESRI = (z: number, x: number, y: number) =>
  `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`

/** O pino e o contorno da usina ([[lat, lng], ...]); `aviso` diz por que faltam. */
export type PosicaoDaUsina = {
  latitude: number | null
  longitude: number | null
  area_poligono: number[][] | null
  aviso: string | null
}

const caminhoDaPosicao = (usinaId: number) => `mapa/usinas/${usinaId}/posicao`

function contorno(p: PosicaoDaUsina | null | undefined): number[][] {
  return (p?.area_poligono ?? []).filter(
    (x) => Array.isArray(x) && x.length >= 2 && Number.isFinite(x[0]) && Number.isFinite(x[1]),
  )
}

/** O centro da miniatura: o meio do contorno, senão o pino do cadastro; sem os dois, nulo (a miniatura diz). */
export function centroDoMapa(p: PosicaoDaUsina | null | undefined): [number, number] | null {
  const c = contorno(p)
  if (c.length) {
    const soma = c.reduce((a, x) => [a[0] + x[0], a[1] + x[1]], [0, 0])
    return [soma[0] / c.length, soma[1] / c.length]
  }
  if (p?.latitude != null && p?.longitude != null) return [p.latitude, p.longitude]
  return null
}

/** O pixel do mundo no zoom da miniatura (ladrilhos de 256 px). */
function pixel(lat: number, lng: number): [number, number] {
  const n = 2 ** ZOOM * 256
  const s = Math.sin((lat * Math.PI) / 180)
  return [((lng + 180) / 360) * n, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n]
}

/** A caixa centrada em (lat, lng): os ladrilhos que a cobrem e onde cai um ponto qualquer nela (em px da caixa). */
export function caixa(lat: number, lng: number) {
  const [px, py] = pixel(lat, lng)
  const x0 = px - LARGURA                                   // a caixa, em pixels do ladrilho (desenhado pela metade)
  const y0 = py - ALTURA
  const ladrilhos: { url: string; esquerda: number; topo: number }[] = []
  for (let tx = Math.floor(x0 / 256); tx <= Math.floor((px + LARGURA) / 256); tx++)
    for (let ty = Math.floor(y0 / 256); ty <= Math.floor((py + ALTURA) / 256); ty++)
      ladrilhos.push({ url: ESRI(ZOOM, tx, ty), esquerda: (tx * 256 - x0) / 2, topo: (ty * 256 - y0) / 2 })
  const ponto = (la: number, ln: number): [number, number] => {
    const [gx, gy] = pixel(la, ln)
    return [(gx - x0) / 2, (gy - y0) / 2]
  }
  return { ladrilhos, ponto }
}

/** Por que a miniatura está sem a foto, na ordem em que se sabe. */
export function semFoto(carregando: boolean, dados: PosicaoDaUsina | null | undefined, imagemFalhou: boolean): string {
  if (carregando) return 'Carregando o mapa…'
  if (!dados) return 'O mapa não pôde ser lido agora.'
  if (dados.aviso) return dados.aviso
  if (imagemFalhou) return 'A imagem de satélite não carregou agora.'
  return 'Sem a posição da usina no cadastro: marque no mapa.'
}

export function MiniaturaDoMapa({ usinaId }: { usinaId: number }) {
  const leitura = useLeitura<PosicaoDaUsina>(caminhoDaPosicao(usinaId))
  // o ladrilho que não carrega sai sozinho; a mensagem só quando nenhum carregou
  const [falharam, setFalharam] = useState<Set<string>>(() => new Set())
  const centro = centroDoMapa(leitura.dados)
  const montada = centro ? caixa(centro[0], centro[1]) : null
  const imagemFalhou = montada !== null && montada.ladrilhos.every((t) => falharam.has(t.url))
  const foto = imagemFalhou ? null : montada
  const linha = foto ? contorno(leitura.dados).map(([la, ln]) => foto.ponto(la, ln).join(',')).join(' ') : ''
  return (
    <Link
      to={`/usinas/${usinaId}/mapa`}
      className="relative block shrink-0 overflow-hidden rounded-lg border border-borda bg-superficie-alta"
      style={{ width: LARGURA, height: foto ? ALTURA : undefined, minHeight: ALTURA }}
      aria-label="Abrir o mapa da usina"
      title="Abrir o mapa da usina"
    >
      {foto ? (
        <>
          {foto.ladrilhos.filter((t) => !falharam.has(t.url)).map((t) => (
            <img
              key={t.url}
              src={t.url}
              alt=""
              onError={() => setFalharam((f) => new Set(f).add(t.url))}
              className="absolute max-w-none"
              style={{ left: t.esquerda, top: t.topo, width: LADO, height: LADO }}
            />
          ))}
          {linha ? (
            <svg className="absolute inset-0" width={LARGURA} height={ALTURA} aria-hidden="true">
              <polygon points={linha} fill="rgba(251, 191, 36, 0.14)" stroke="#fbbf24" strokeWidth={1.5} />
            </svg>
          ) : (
            <span
              className="absolute h-2.5 w-2.5 rounded-full border-2 border-amber-400 bg-white"
              style={{ left: LARGURA / 2 - 5, top: ALTURA / 2 - 5 }}
            />
          )}
          <span className="absolute right-1 top-1 rounded bg-black/60 px-1 text-[10px] leading-tight text-white">
            Imagens © Esri
          </span>
        </>
      ) : (
        <span className="block px-2 pb-8 pt-2 text-xs text-fraco">
          {semFoto(leitura.carregando, leitura.dados, imagemFalhou)}
        </span>
      )}
      <span className="absolute inset-x-0 bottom-0 flex items-center gap-1.5 bg-black/65 px-2 py-1 text-xs text-white">
        <MapPinned size={13} />
        Abrir o mapa
      </span>
    </Link>
  )
}
