/**
 * O mapa único (gestao.solar/usinas/<id>/mapa). O que este teste guarda:
 *
 * 1. **O mapa fora não vira mapa vazio que parece certo** — o aviso do servidor aparece.
 * 2. **Só a O&M edita**, cada camada com a sua permissão. O dono vê o porquê.
 * 3. **O nome vem de outro sistema e entra como TEXTO** (na dica do Leaflet, `textContent`).
 * 4. **Sem o estado lido, nada é "normal"**: a faixa diz que não foi lido e o filtro de estado fica desligado com o porquê.
 * 5. **O filtro**: busca por nome/motivo, "nenhum passa" diz e devolve todos; a lista põe o problema primeiro.
 * 6. **`?destaque=`** abre o objeto; **`?print=1`** mostra só o mapa (a foto do bot).
 * 7. **Desenhar**: os toques viram a linha em [lon, lat] e vão ao servidor.
 *
 * O Leaflet é simulado: o jsdom não desenha mapa, e o que se confere aqui é o que a tela faz com o dado.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const camadas: { tooltip: HTMLElement | null; clique: (() => void) | null; eventos: Record<string, () => void> }[] = []
let cliqueNoMapa: ((e: { latlng: { lat: number; lng: number } }) => void) | null = null
let fundoCarregou: (() => void) | null = null

vi.mock('leaflet', () => {
  const camada = () => {
    const c = { tooltip: null as HTMLElement | null, clique: null as (() => void) | null, eventos: {} as Record<string, () => void> }
    camadas.push(c)
    const api = {
      bindTooltip: (el: HTMLElement) => { c.tooltip = el; return api },
      on: (ev: string, fn: () => void) => { c.eventos[ev] = fn; if (ev === 'click') c.clique = fn; return api },
      addTo: () => api,
    }
    return api
  }
  const mapa = {
    attributionControl: { setPrefix: () => undefined },
    on: (_ev: string, fn: typeof cliqueNoMapa) => { cliqueNoMapa = fn },
    remove: () => undefined, fitBounds: () => undefined, setView: () => undefined,
  }
  const L = {
    map: () => mapa, tileLayer: () => ({ on: (_ev: string, fn: () => void) => { fundoCarregou = fn }, addTo: () => undefined }),
    layerGroup: () => ({ addTo: () => ({ clearLayers: () => undefined }) }),
    imageOverlay: camada, polygon: camada, polyline: camada, circleMarker: camada, latLngBounds: () => ({}),
  }
  return { default: L }
})
vi.mock('leaflet/dist/leaflet.css', () => ({}))

import { api } from '@/lib/api'
import { identificarCache, limparCache } from '@/lib/leitura'
import type { MapaOut, ObjetoDoMapa } from '@/features/mapa/api'
import Mapa, { camadaDe, desenhoDe, estadoDe, passa } from '@/features/mapa/Pagina'

const camera: ObjetoDoMapa = { id: 1, tipo: 'camera', nome: '<b>Câmera 01</b>', node_id: 71, node_nome: '<i>Câmera 01</i>',
  node_tipo: 'camera', origem: 'meuplano:node:71', geometria: { type: 'Point', coordinates: [-47.99, -23.2] } }
const string12: ObjetoDoMapa = { id: 2, tipo: 'string', nome: 'Inv 03 · S12', node_id: null, node_nome: null, node_tipo: null,
  geometria: { type: 'LineString', coordinates: [[-47.99, -23.2], [-47.98, -23.2]] } }
const inversor: ObjetoDoMapa = { id: 3, tipo: 'inversor', nome: 'Inv 03', node_id: null, node_nome: null, node_tipo: null,
  geometria: { type: 'Point', coordinates: [-47.97, -23.21] } }

function resposta(parcial: Partial<MapaOut>): MapaOut {
  return {
    usina: { id: 7, nome: 'UFV Pereiras' },
    pode_editar: false,
    por_que_nao_edita: 'O mapa é editado pela equipe de O&M.',
    edicao: { monitoramento: 'O mapa é editado pela equipe de O&M.', manutencao: 'O mapa é editado pela equipe de O&M.' },
    mapa: {
      usina: { id: 4, nome: 'UFV PEREIRAS', latitude: -23.2, longitude: -47.99, area_poligono: null },
      vinculado: true, slug: 'pereiras', editar_url: null, orto: null, aviso: null, objetos: [camera, string12, inversor],
    },
    aviso: null,
    estado: { lido_em: '2026-11-18T19:30:00', objetos: { '2': { estado: 'problema', motivo: 'corrente zero desde as 10:12' },
      '3': { estado: 'ok' } } },
    estado_aviso: null,
    mapa_completo: true,
    ...parcial,
  }
}

function montar(rota = '/usinas/7/mapa') {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[rota]}>
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
    cliqueNoMapa = null
    fundoCarregou = null
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    limparCache()
  })

  it('as regras: camada, estado (sem leitura não é normal), filtro e o desenho em [lon, lat]', () => {
    const d = resposta({})
    expect([camadaDe(camera), camadaDe(string12)]).toEqual(['cameras', 'monitoramento'])
    expect([estadoDe(d, string12), estadoDe(d, inversor), estadoDe(d, camera)]).toEqual(['problema', 'ok', 'fora'])
    // o desenho que se liga e não está ligado: "sem ligação"; ligado mas fora da lista: "sem estado calculado"
    const solta: ObjetoDoMapa = { ...string12, id: 50 }
    expect([estadoDe(d, solta), estadoDe(d, { ...solta, slot_id: 7, string_number: 1 })]).toEqual(['sem_leitura', 'fora'])
    expect(estadoDe(resposta({ estado: null }), string12)).toBeNull()
    const f = { busca: '', tipos: null, camadas: null, estados: null }
    expect(passa(d, string12, { ...f, busca: 'corrente zero' })).toBe(true)   // pelo motivo
    expect(passa(d, inversor, { ...f, busca: 'corrente zero' })).toBe(false)
    expect(passa(d, string12, { ...f, estados: ['ok'] })).toBe(false)
    expect(passa(resposta({ estado: null }), string12, { ...f, estados: ['problema'] })).toBe(false)
    expect(desenhoDe('LineString', [{ lat: -23.2, lng: -47.99 }])).toBeNull()
    expect(desenhoDe('Polygon', [{ lat: 1, lng: 2 }, { lat: 3, lng: 4 }, { lat: 5, lng: 6 }]))
      .toEqual({ type: 'Polygon', coordinates: [[[2, 1], [4, 3], [6, 5], [2, 1]]] })
  })

  it('pede o mapa da usina da URL e o dono vê o porquê de não editar', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({}) })
    montar()
    await screen.findByText('O mapa é editado pela equipe de O&M.')
    expect(String(get.mock.calls[0][0])).toContain('/api/v1/mapa/usinas/7')
    expect(screen.queryByLabelText(/Marcar no mapa/)).toBeNull()
    expect(screen.queryByText(/Desenhar string/)).toBeNull()
  })

  it('o mapa fora mostra o aviso, nunca um mapa vazio calado', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ mapa: null, aviso: 'O mapa não respondeu agora.' }) })
    montar()
    await screen.findByText('O mapa não respondeu agora.')
  })

  it('sem o estado lido: a faixa diz, o filtro de estado fica desligado e nada sai "Normal"', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ estado: null,
      estado_aviso: 'O estado dos equipamentos (alarme, string com problema) ainda não está disponível.' }) })
    montar()
    await screen.findByText(/ainda não está disponível\. As cores mostram só o tipo/)
    expect(screen.queryByText(/Normal/)).toBeNull()
    expect(screen.queryByText(/Com problema/)).toBeNull()
  })

  it('o filtro: busca, "nenhum passa" diz e devolve todos; a lista põe o problema primeiro', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({}) })
    montar()
    const lista = await screen.findByRole('list', { name: 'Objetos do mapa' })
    const linhas = within(lista).getAllByRole('button')
    expect(linhas[0].textContent).toContain('Inv 03 · S12')                       // o problema primeiro
    expect(linhas[0].textContent).toContain('Com problema: corrente zero desde as 10:12')
    fireEvent.change(screen.getByLabelText('Buscar no mapa'), { target: { value: 'S12' } })
    await screen.findByText('1 de 3 objetos')
    fireEvent.change(screen.getByLabelText('Buscar no mapa'), { target: { value: 'nada disso' } })
    await screen.findByText(/Nenhum objeto passa nesse filtro/)
    fireEvent.click(screen.getByText('Mostrar todos'))
    await screen.findByText('3 objetos')
  })

  it('o nome entra como texto, e o toque na câmera abre a ficha e o Mover', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ pode_editar: true, por_que_nao_edita: null,
      edicao: { monitoramento: null, manutencao: null } }) })
    montar()
    await screen.findByLabelText(/Marcar no mapa/)
    await waitFor(() => expect(camadas.some((c) => c.tooltip?.textContent?.includes('Câmera 01'))).toBe(true))
    const cam = camadas.find((c) => c.tooltip?.textContent?.includes('Câmera 01'))!
    expect(cam.tooltip!.textContent).toContain('<i>Câmera 01</i> · Câmera')       // texto cru, não marcação
    expect(cam.tooltip!.querySelector('i')).toBeNull()
    cam.clique!()
    const abrir = await screen.findByText('Abrir a ficha')
    expect(abrir.getAttribute('href')).toBe('https://app.meuplano.solar/ativos/71')
    fireEvent.click(screen.getByText('Mover'))
    await screen.findByText(/Toque no mapa onde fica/)
  })

  it('?destaque= abre o objeto; ?print=1 mostra só o mapa (a foto do bot)', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({}) })
    montar('/usinas/7/mapa?destaque=2')
    await screen.findByText('camada Monitoramento', { exact: false })
    expect(screen.getAllByText(/corrente zero desde as 10:12/).length).toBeGreaterThan(0)
    cleanup()
    const r = montar('/usinas/7/mapa?destaque=2&print=1')
    await screen.findByText(/Com problema: corrente zero/)
    expect(r.container.querySelector('#mapa-unico')).not.toBeNull()
    expect(screen.queryByLabelText('Buscar no mapa')).toBeNull()
    expect(screen.queryByText('Fechar')).toBeNull()
  })

  it('desenhar: os toques viram a linha em [lon, lat] e vão ao servidor como a pessoa', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ pode_editar: true, por_que_nao_edita: null,
      edicao: { monitoramento: null, manutencao: null } }) })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { criados: 1 } })
    montar()
    fireEvent.click(await screen.findByText(/Desenhar string, inversor, trafo/))
    fireEvent.change(screen.getByLabelText('Nome do objeto'), { target: { value: 'Inv 03 · S13' } })
    fireEvent.click(screen.getByText('Desenhar no mapa'))
    await screen.findByText(/toque no mapa para pôr pelo menos 2 pontos/)
    expect(screen.getByText('Concluir').closest('button')?.disabled).toBe(true)
    cliqueNoMapa!({ latlng: { lat: -23.2, lng: -47.99 } })
    cliqueNoMapa!({ latlng: { lat: -23.2, lng: -47.98 } })
    await screen.findByText(/2 ponto\(s\)/)
    fireEvent.click(screen.getByText('Concluir'))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][0]).toBe('/api/v1/mapa/usinas/7/objetos')
    expect(post.mock.calls[0][1]).toEqual({ tipo: 'string', nome: 'Inv 03 · S13',
      geometria: { type: 'LineString', coordinates: [[-47.99, -23.2], [-47.98, -23.2]] } })
  })

  it('ligar a string ao equipamento: o inversor (a vaga) e a string vão no PATCH', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => (url.includes('/ligacoes')
      ? { data: { vagas: [{ slot_id: 7, rotulo: 'Vaga do Inv 03', trafo: 'TR-01', transformer_id: 3, strings: [12, 13] }],
        trafos: [{ transformer_id: 3, nome: 'TR-01' }] } }
      : { data: resposta({ pode_editar: true, por_que_nao_edita: null, edicao: { monitoramento: null, manutencao: null } }) }))
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} })
    montar('/usinas/7/mapa?destaque=2')
    fireEvent.click(await screen.findByText('Ligar ao equipamento'))
    const modal = await screen.findByRole('dialog')
    fireEvent.click(within(modal).getByText('Qual inversor?'))
    fireEvent.click(await within(modal).findByText('Vaga do Inv 03'))
    fireEvent.click(within(modal).getByText('Qual string?'))
    fireEvent.click(await within(modal).findByText('String 13'))
    fireEvent.click(within(modal).getByText('Gravar'))
    await waitFor(() => expect(patch).toHaveBeenCalled())
    expect(patch.mock.calls[0][0]).toBe('/api/v1/mapa/usinas/7/objetos/2')
    expect(patch.mock.calls[0][1]).toEqual({ slot_id: 7, string_number: 13 })
  })

  it('o monitoramento ainda sem a versão nova: sem Mover nem Ligar, e a tela diz por quê', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ pode_editar: true, por_que_nao_edita: null,
      edicao: { monitoramento: null, manutencao: null }, mapa_completo: false }) })
    montar('/usinas/7/mapa?destaque=2')
    await screen.findByText(/chegam quando o monitoramento publicar a versão nova/)
    expect(screen.queryByText('Ligar ao equipamento')).toBeNull()
    expect(screen.queryByText('Redesenhar')).toBeNull()
    expect(screen.getByText('Renomear')).toBeTruthy()
  })

  it('ligar o trafo: escolhe pelo nome e vai o transformer_id', async () => {
    const trafo: ObjetoDoMapa = { id: 9, tipo: 'transformador', nome: 'Trafo da cabine', node_id: null, node_nome: null, node_tipo: null,
      geometria: { type: 'Point', coordinates: [-47.96, -23.2] } }
    const base = resposta({ pode_editar: true, por_que_nao_edita: null, edicao: { monitoramento: null, manutencao: null } })
    base.mapa!.objetos = [...base.mapa!.objetos, trafo]
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => (url.includes('/ligacoes')
      ? { data: { vagas: [], trafos: [{ transformer_id: 3, nome: 'TR-01' }, { transformer_id: 4, nome: 'TR-02' }] } }
      : { data: base }))
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} })
    montar('/usinas/7/mapa?destaque=9')
    fireEvent.click(await screen.findByText('Ligar ao equipamento'))
    const modal = await screen.findByRole('dialog')
    fireEvent.click(await within(modal).findByText('Qual trafo?'))
    fireEvent.click(await within(modal).findByText('TR-02'))
    fireEvent.click(within(modal).getByText('Gravar'))
    await waitFor(() => expect(patch).toHaveBeenCalled())
    expect(patch.mock.calls[0]).toEqual(['/api/v1/mapa/usinas/7/objetos/9', { transformer_id: 4 }, { timeout: 60_000 }])
  })

  it('quem marca e não pode desenhar vê o porquê (não só a falta do botão)', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: resposta({ pode_editar: true, por_que_nao_edita: null,
      edicao: { monitoramento: 'Esta usina está ligada a outra usina do monitoramento.', manutencao: null } }) })
    montar()
    await screen.findByText('Esta usina está ligada a outra usina do monitoramento.')
    expect(screen.queryByText(/Desenhar string/)).toBeNull()
    expect(screen.getByLabelText(/Marcar no mapa/)).toBeTruthy()
  })

  it('a foto: "pronto" só com o satélite E o voo carregados; o voo que falha diz', async () => {
    const comVoo = resposta({})
    comVoo.mapa!.orto = { voo: '2026-08-26', url: 'https://r2/voo.webp', bounds: [[-23.21, -48], [-23.19, -47.96]] }
    vi.spyOn(api, 'get').mockResolvedValue({ data: comVoo })
    const r = montar('/usinas/7/mapa?destaque=2&print=1')
    await screen.findByText(/Com problema: corrente zero/)
    const caixa = r.container.querySelector('#mapa-unico')!
    const voo = camadas.find((c) => c.eventos.load)!
    fundoCarregou!()
    expect(caixa.getAttribute('data-pronto')).toBeNull()              // o satélite sozinho não basta
    voo.eventos.load()
    expect(caixa.getAttribute('data-pronto')).toBe('1')
    voo.eventos.error()
    expect(caixa.getAttribute('data-voo')).toBe('falhou')
  })

  it('o voo cadastrado sem a imagem é dito (nunca "voo de …" com o voo fora da tela)', async () => {
    const semImagem = resposta({})
    semImagem.mapa!.orto = { voo: '2026-08-26', url: null, bounds: [[-23.21, -48], [-23.19, -47.96]] }
    vi.spyOn(api, 'get').mockResolvedValue({ data: semImagem })
    const r = montar()
    await screen.findByText(/está cadastrado, mas a imagem dele não pôde ser/)
    expect(screen.getByText(/voo de 26\/08\/2026 \(sem a imagem agora\)/)).toBeTruthy()
    expect(r.container.querySelector('[data-voo="sem-imagem"]')).not.toBeNull()
  })

  it('o mapa do TermoVision calado: a tela diz e oferece tentar de novo (nunca um quadro em branco)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const tv = 'https://termovision.gestao.solar'
      vi.spyOn(api, 'get').mockImplementation((url: string) =>
        Promise.resolve({
          data: String(url).includes('/api/sessao/produtos')
            ? [{ produto: 'termovision', nome: 'TermoVision', url: `${tv}/entrar.html` }]
            : resposta({ usina: { id: 7, nome: 'UFV Pereiras', tv_codigo: 'abc123' } }),
        }) as never,
      )
      vi.spyOn(api, 'post').mockResolvedValue({ data: { url: `${tv}/embutir/7#assercao=PASSE1` } })
      montar()
      const quadro = (await screen.findByTitle('Mapa de UFV Pereiras no TermoVision')) as HTMLIFrameElement
      fireEvent.load(quadro)
      await act(async () => {
        vi.advanceTimersByTime(21_000)
      })
      expect(await screen.findByText(/não respondeu em 20 segundos/)).toBeTruthy()
      fireEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
      expect(screen.queryByText(/não respondeu em 20 segundos/)).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('com o mapa no TermoVision e o acesso liberado: a tela de lá embutida, com o passe e o estado do GS', async () => {
    const tv = 'https://termovision.gestao.solar'
    vi.spyOn(api, 'get').mockImplementation((url: string) =>
      Promise.resolve({
        data: String(url).includes('/api/sessao/produtos')
          ? [{ produto: 'termovision', nome: 'TermoVision', url: `${tv}/entrar.html` }]
          : resposta({ usina: { id: 7, nome: 'UFV Pereiras', tv_codigo: 'abc123' } }),
      }) as never,
    )
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { url: `${tv}/embutir/7#assercao=PASSE1` } })
    montar()
    const quadro = (await screen.findByTitle('Mapa de UFV Pereiras no TermoVision')) as HTMLIFrameElement
    expect(quadro.getAttribute('src')).toBe(`${tv}/embutir/7?camada=orto,termica,mesas,strings`)
    const mandou = vi.spyOn(quadro.contentWindow as Window, 'postMessage')
    fireEvent.load(quadro)
    await waitFor(() => expect(mandou).toHaveBeenCalledWith({ tipo: 'gs-passe', produto: 'termovision', assercao: 'PASSE1' }, tv))
    expect(post).toHaveBeenCalledWith('/api/sessao/termovision', { volta: `${tv}/embutir/7` })
    // o TermoVision diz que está pronto: vai o estado que o GS calculou (a string 2 com problema)
    window.dispatchEvent(new MessageEvent('message', { origin: tv, source: quadro.contentWindow, data: { tipo: 'tv-pronto' } }))
    await waitFor(() => expect(mandou).toHaveBeenCalledWith(
      expect.objectContaining({ tipo: 'tv-estado',
                                itens: [{ ref: { meuwatt: 2 }, estado: 'problema' }, { ref: { meuwatt: 3 }, estado: 'ok' }] }),
      tv))
    const enviado = mandou.mock.calls.find((c) => (c[0] as { tipo?: string }).tipo === 'tv-estado')![0] as Record<string, unknown>
    expect('lido_em' in enviado).toBe(true)                            // as cores vão com a hora da leitura
    // passada a folga de 10 s: o pedido de passe de outra origem não conta; o do TermoVision, sim
    const agora = Date.now()
    vi.spyOn(Date, 'now').mockReturnValue(agora + 60_000)
    const antes = post.mock.calls.length
    window.dispatchEvent(new MessageEvent('message', { origin: 'https://outro.site', source: quadro.contentWindow,
                                                       data: { tipo: 'tv-precisa-passe' } }))
    expect(post.mock.calls.length).toBe(antes)
    window.dispatchEvent(new MessageEvent('message', { origin: tv, source: quadro.contentWindow,
                                                       data: { tipo: 'tv-precisa-passe' } }))
    await waitFor(() => expect(post.mock.calls.length).toBe(antes + 1))
    // "Equipamentos" volta ao editor do GS
    fireEvent.click(screen.getByRole('button', { name: 'Equipamentos' }))
    expect(screen.queryByTitle('Mapa de UFV Pereiras no TermoVision')).toBeNull()
  })
})
