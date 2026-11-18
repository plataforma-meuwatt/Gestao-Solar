/**
 * O mapa único (gestao.solar/usinas/<id>/mapa). O que este teste guarda:
 *
 * 1. **O meuWatt fora não vira mapa vazio que parece certo** — o aviso do servidor aparece.
 * 2. **Só a O&M marca.** O dono vê o porquê, e não a busca de marcar.
 * 3. **O nome do equipamento vem de outro sistema e entra como TEXTO** (na dica do Leaflet, `textContent`), e o toque no
 *    equipamento ligado mostra à O&M "Abrir a ficha" com o endereço dela.
 *
 * O Leaflet é simulado: o jsdom não desenha mapa, e o que se confere aqui é o que a tela faz com o dado.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const camadas: { tooltip: HTMLElement | null; clique: (() => void) | null }[] = []

vi.mock('leaflet', () => {
  const camada = () => {
    const c = { tooltip: null as HTMLElement | null, clique: null as (() => void) | null }
    camadas.push(c)
    const api = {
      bindTooltip: (el: HTMLElement) => { c.tooltip = el; return api },
      on: (_ev: string, fn: () => void) => { c.clique = fn; return api },
      addTo: () => api,
    }
    return api
  }
  const mapa = { attributionControl: { setPrefix: () => undefined }, on: () => undefined, remove: () => undefined,
    fitBounds: () => undefined, setView: () => undefined }
  const L = {
    map: () => mapa, tileLayer: () => ({ addTo: () => undefined }),
    layerGroup: () => ({ addTo: () => ({ clearLayers: () => undefined }) }),
    imageOverlay: camada, polygon: camada, polyline: camada, circleMarker: camada, latLngBounds: () => ({}),
  }
  return { default: L }
})
vi.mock('leaflet/dist/leaflet.css', () => ({}))

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { MapaOut } from '@/features/mapa/api'
import Mapa from '@/features/mapa/Pagina'

function resposta(parcial: Partial<MapaOut>): MapaOut {
  return {
    usina: { id: 7, nome: 'UFV Pereiras' },
    pode_editar: false,
    por_que_nao_edita: 'O mapa é editado pela equipe de O&M.',
    mapa: {
      usina: { id: 4, nome: 'UFV PEREIRAS', latitude: -23.2, longitude: -47.99, area_poligono: null },
      vinculado: true, slug: 'pereiras', editar_url: null, orto: null, aviso: null,
      objetos: [{ id: 1, tipo: 'camera', nome: '<b>Câmera 01</b>', node_id: 71, node_nome: 'Câmera 01', node_tipo: 'camera',
        geometria: { type: 'Point', coordinates: [-47.99, -23.2] } }],
    },
    aviso: null,
    ...parcial,
  }
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={['/usinas/7/mapa']}>
        <Routes>
          <Route path="/usinas/:id/mapa" element={<Mapa />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('mapa único', () => {
  beforeEach(() => {
    localStorage.clear()
    identificarCache(7)
    camadas.length = 0
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('pede o mapa da usina da URL e o dono vê o porquê de não editar', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({}) })
    montar()
    await screen.findByText('O mapa é editado pela equipe de O&M.')
    expect(String(get.mock.calls[0][0])).toContain('/api/v1/mapa/usinas/7')
    expect(screen.queryByLabelText(/Marcar no mapa/)).toBeNull()
  })

  it('o meuWatt fora mostra o aviso, nunca um mapa vazio calado', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ mapa: null, aviso: 'O meuPlano não respondeu agora.' }) })
    montar()
    await screen.findByText('O meuPlano não respondeu agora.')
  })

  it('o nome entra como texto, e o toque no equipamento abre a ficha no meuPlano', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ pode_editar: true, por_que_nao_edita: null }) })
    montar()
    await screen.findByLabelText(/Marcar no mapa/)
    await waitFor(() => expect(camadas.some((c) => c.tooltip)).toBe(true))
    const cam = camadas.find((c) => c.tooltip)!
    expect(cam.tooltip!.textContent).toBe('<b>Câmera 01</b> · Câmera')       // texto cru, não marcação
    expect(cam.tooltip!.querySelector('b')).toBeNull()
    cam.clique!()
    const abrir = await screen.findByText('Abrir a ficha')
    expect(abrir.getAttribute('href')).toBe('https://app.meuplano.solar/ativos/71')
    fireEvent.click(screen.getByText('Mover'))
    await screen.findByText(/Toque no mapa onde fica/)
  })
})
