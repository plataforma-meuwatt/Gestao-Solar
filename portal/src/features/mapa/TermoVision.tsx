/**
 * O mapa do TermoVision embutido no GS (Plano Casa GS, R6: "todo mapa mora no TermoVision; os outros sistemas embutem
 * a tela dele"). O contrato é o do TermoVision (`docs/contrato-embutir.md` do termosolar):
 *
 * - o iframe abre `<TermoVision>/embutir/<gs>`; o GS manda o PASSE da pessoa (`gs-passe`) quando ele carrega e de novo
 *   a cada `tv-precisa-passe` (com 10 s de folga, para não gastar dois passes seguidos);
 * - o GS manda o ESTADO que já calcula (`tv-estado`, por objeto do meuWatt, com a hora da leitura) quando o mapa fica
 *   pronto e de novo a cada leitura nova: a string com problema pinta lá;
 * - do iframe vêm a altura (`tv-altura`), o pronto (`tv-pronto`), o objeto tocado (`tv-objeto`) e o erro (`tv-erro`),
 *   conferidos pela origem e pela janela (só o iframe daqui fala com esta tela).
 * - silêncio é falha ("nunca enganar"): sem o `tv-pronto` em 20 s, a tela diz que o mapa não respondeu e oferece tentar
 *   de novo, em vez de ficar num quadro em branco.
 *
 * Nesta etapa a tela embutida é só para ver: quem edita usa "Abrir no TermoVision" (dentro dela) ou a aba
 * "Equipamentos" do GS.
 */

import { useEffect, useRef, useState } from 'react'

import { Aviso } from '@/components/base'
import { api, mensagemDeErro } from '@/lib/api'

import type { MapaOut } from './api'

type DoIframe =
  | { tipo: 'tv-precisa-passe' }
  | { tipo: 'tv-altura'; altura: number }
  | { tipo: 'tv-pronto'; usina?: { nome?: string; voo?: string | null } }
  | { tipo: 'tv-objeto'; objeto: { tipo: string; rotulo?: string; refs?: { meuwatt?: number | string | null } } }
  | { tipo: 'tv-erro'; codigo: string; texto?: string }

const ESTADO: Record<string, string> = { ok: 'Normal', problema: 'Com problema', alarme: 'Em alarme', sem_dado: 'Sem dado' }
const FOLGA_DO_PASSE_MS = 10_000
/** quanto o mapa pode ficar calado depois de carregar (o TermoVision manda o `tv-pronto` quando desenhou) */
export const PRAZO_DO_PRONTO_MS = 20_000

const hora = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : null

export function MapaDoTermoVision({ d, origem }: { d: MapaOut; origem: string }) {
  const quadro = useRef<HTMLIFrameElement>(null)
  const ultimoPasse = useRef(0)
  const pronto = useRef(false)
  const [altura, setAltura] = useState(560)
  const [erro, setErro] = useState<string | null>(null)
  const [calado, setCalado] = useState(false)
  const [tentativa, setTentativa] = useState(0)
  const [escolhido, setEscolhido] = useState<string | null>(null)
  const gs = d.usina.id
  const endereco = `${origem}/embutir/${gs}?camada=orto,termica,mesas,strings`

  /** O estado que o GS calcula, por objeto do meuWatt, com a hora da leitura: o TermoVision pinta a string. */
  const estado = () => ({
    tipo: 'tv-estado',
    lido_em: d.estado?.lido_em ?? null,
    dados_de: d.estado?.dados_de ?? null,
    itens: Object.entries(d.estado?.objetos ?? {}).map(([id, e]) => ({ ref: { meuwatt: Number(id) }, estado: e.estado })),
  })

  async function mandarPasse() {
    const janela = quadro.current?.contentWindow
    if (!janela) return
    ultimoPasse.current = Date.now()
    try {
      // a volta é o próprio iframe: o GS confere que ela é do TermoVision e devolve a asserção no fragmento
      const { data } = await api.post<{ url: string }>('/api/sessao/termovision', { volta: `${origem}/embutir/${gs}` })
      const assercao = new URLSearchParams(data.url.split('#')[1] ?? '').get('assercao')
      if (!assercao) throw new Error('O GS não devolveu o passe do TermoVision.')
      janela.postMessage({ tipo: 'gs-passe', produto: 'termovision', assercao }, origem)
      setErro(null)
    } catch (e) {
      setErro(mensagemDeErro(e))
    }
  }

  const prazo = useRef<number | undefined>(undefined)
  /** o prazo de silêncio: sem o `tv-pronto` em 20 s = o mapa não respondeu (dito, nunca um quadro em branco). Conta
   *  da abertura e recomeça a cada carregamento do quadro. */
  function contarPrazo() {
    window.clearTimeout(prazo.current)
    prazo.current = window.setTimeout(() => {
      if (!pronto.current) setCalado(true)
    }, PRAZO_DO_PRONTO_MS)
  }

  function carregou() {
    pronto.current = false
    setCalado(false)
    contarPrazo()
    void mandarPasse()
  }

  useEffect(() => {
    contarPrazo()
    return () => window.clearTimeout(prazo.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tentativa, gs])

  // leitura nova do monitoramento: as cores vão de novo, com a hora delas
  useEffect(() => {
    if (pronto.current) quadro.current?.contentWindow?.postMessage(estado(), origem)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.estado?.lido_em, d.estado?.objetos])

  useEffect(() => {
    function ouvir(ev: MessageEvent) {
      if (ev.origin !== origem || ev.source !== quadro.current?.contentWindow) return
      const m = ev.data as DoIframe
      if (!m || typeof m !== 'object') return
      if (m.tipo === 'tv-precisa-passe') {
        if (Date.now() - ultimoPasse.current > FOLGA_DO_PASSE_MS) void mandarPasse()
      } else if (m.tipo === 'tv-altura' && Number.isFinite(m.altura)) {
        setAltura(Math.max(360, Math.min(4000, m.altura)))
      } else if (m.tipo === 'tv-pronto') {
        pronto.current = true
        setCalado(false)
        quadro.current?.contentWindow?.postMessage(estado(), origem)
      } else if (m.tipo === 'tv-objeto') {
        const id = m.objeto?.refs?.meuwatt
        const e = id != null ? d.estado?.objetos[String(id)] : undefined
        setEscolhido(
          `${m.objeto?.rotulo || m.objeto?.tipo || 'Objeto'}${e ? ` · ${ESTADO[e.estado] ?? e.estado}${e.motivo ? `: ${e.motivo}` : ''}` : ''}`,
        )
      } else if (m.tipo === 'tv-erro') {
        setErro(m.texto || 'O mapa do TermoVision não abriu agora.')
      }
    }
    window.addEventListener('message', ouvir)
    return () => window.removeEventListener('message', ouvir)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [origem, d])

  const lido = hora(d.estado?.lido_em)
  return (
    <div className="space-y-2">
      {erro ? <Aviso tom="semDados">{erro}</Aviso> : null}
      {calado && !erro ? (
        <Aviso tom="semDados">
          <span className="inline-flex flex-wrap items-center gap-2">
            O mapa do TermoVision não respondeu em {PRAZO_DO_PRONTO_MS / 1000} segundos.
            <button
              className="underline"
              onClick={() => {
                setCalado(false)
                setTentativa((n) => n + 1)
              }}
            >
              Tentar de novo
            </button>
          </span>
        </Aviso>
      ) : null}
      <iframe
        key={tentativa}
        ref={quadro}
        title={`Mapa de ${d.usina.nome} no TermoVision`}
        src={endereco}
        onLoad={carregou}
        className="w-full rounded-campo border border-borda bg-afundado"
        style={{ height: altura }}
        allow="fullscreen"
      />
      <p className="text-[13px] text-fraco">
        {escolhido ?? 'O mapa e o voo moram no TermoVision. Toque numa mesa ou string para ver qual é.'}
        {' '}
        {lido
          ? `As cores são do monitoramento lido em ${lido}.`
          : d.estado_aviso
            ? `Sem as cores do monitoramento: ${d.estado_aviso}`
            : 'Sem as cores do monitoramento agora.'}
      </p>
    </div>
  )
}
