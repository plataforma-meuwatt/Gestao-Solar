import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { caixa, centroDoMapa, MiniaturaDoMapa, semFoto, type PosicaoDaUsina } from './Miniatura'

const leitura = vi.hoisted(() => ({ atual: { dados: null as unknown, carregando: false } }))
vi.mock('@/lib/leitura', () => ({ useLeitura: () => leitura.atual }))

const pos = (p: Partial<PosicaoDaUsina>): PosicaoDaUsina => ({
  latitude: null,
  longitude: null,
  area_poligono: null,
  aviso: null,
  ...p,
})

describe('miniatura do mapa', () => {
  it('centra no contorno da usina, senão no pino do cadastro, senão em nada', () => {
    const c = centroDoMapa(pos({ area_poligono: [[-21, -48], [-21.002, -48.004]], latitude: -10, longitude: -10 }))
    expect(c?.[0]).toBeCloseTo(-21.001, 9)
    expect(c?.[1]).toBeCloseTo(-48.002, 9)
    expect(centroDoMapa(pos({ latitude: -21.7, longitude: -48.8 }))).toEqual([-21.7, -48.8])
    expect(centroDoMapa(pos({}))).toBeNull()
    expect(centroDoMapa(null)).toBeNull()
  })

  it('os ladrilhos cobrem a caixa inteira e o centro cai no meio dela', () => {
    const { ladrilhos, ponto } = caixa(-21.7639, -48.8295)
    expect(ladrilhos.length).toBeGreaterThanOrEqual(4)
    expect(Math.min(...ladrilhos.map((t) => t.esquerda))).toBeLessThanOrEqual(0)
    expect(Math.max(...ladrilhos.map((t) => t.esquerda + 128))).toBeGreaterThanOrEqual(176)
    expect(Math.min(...ladrilhos.map((t) => t.topo))).toBeLessThanOrEqual(0)
    expect(Math.max(...ladrilhos.map((t) => t.topo + 128))).toBeGreaterThanOrEqual(100)
    const [x, y] = ponto(-21.7639, -48.8295)
    expect(x).toBeCloseTo(88, 6)
    expect(y).toBeCloseTo(50, 6)
    const [lx] = ponto(-21.7639, -48.8285)                  // a leste fica à direita, ~0,1 km = ~23 px no zoom 16
    expect(lx).toBeGreaterThan(88)
    expect(
      ladrilhos.every((t) =>
        t.url.startsWith('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/16/'),
      ),
    ).toBe(true)
  })

  it('sem a foto, diz o porquê certo, na ordem em que se sabe', () => {
    expect(semFoto(true, null, false)).toBe('Carregando o mapa…')
    expect(semFoto(false, null, false)).toBe('O mapa não pôde ser lido agora.')
    // o motivo do servidor vem como veio: "ainda não ligada" não é "não pôde ser lido"
    const aviso = 'Esta usina ainda não está ligada à manutenção: o mapa dela ainda não existe.'
    expect(semFoto(false, pos({ aviso }), false)).toBe(aviso)
    expect(semFoto(false, pos({ latitude: -21, longitude: -48 }), true)).toBe('A imagem de satélite não carregou agora.')
    expect(semFoto(false, pos({}), false)).toBe('Sem a posição da usina no cadastro: marque no mapa.')
  })

  it('desenha o contorno da usina, o crédito da Esri e diz quando a imagem não carrega', () => {
    leitura.atual = {
      dados: pos({ area_poligono: [[-21.7639, -48.8295], [-21.7649, -48.8295], [-21.7649, -48.8285]] }),
      carregando: false,
    }
    const { container } = render(
      <MemoryRouter>
        <MiniaturaDoMapa usinaId={6} />
      </MemoryRouter>,
    )
    expect(container.querySelector('polygon')?.getAttribute('points')?.split(' ')).toHaveLength(3)
    expect(screen.getByText('Imagens © Esri')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Abrir o mapa da usina' }).getAttribute('href')).toBe('/usinas/6/mapa')
    const total = container.querySelectorAll('img').length
    fireEvent.error(container.querySelector('img') as HTMLImageElement)   // um ladrilho só: os outros ficam
    expect(container.querySelectorAll('img')).toHaveLength(total - 1)
    expect(screen.queryByText('A imagem de satélite não carregou agora.')).toBeNull()
    for (const img of Array.from(container.querySelectorAll('img'))) fireEvent.error(img)   // nenhum: a mensagem
    expect(screen.getByText('A imagem de satélite não carregou agora.')).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })
})
