/**
 * Automações — as regras e lembretes que as pessoas da empresa criaram pelo WhatsApp do Gestão Solar (Plano Assistente
 * GS, 26/11/2026). Criar é pelo bot; aqui o gerente da O&M vê todas as da empresa, liga, pausa, põe em ensaio e apaga,
 * e lê o que cada uma mandou (ou só guardou, no ensaio).
 *
 * O recorte sai da sessão (`/api/empresa/automacoes`) e toda frase vem pronta do BFF (situação, ajuda, agenda, cega,
 * entrega, evento, status, as linhas da leitura): a tela não monta texto a partir de código.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Cartao, Erro, Modal, Pagina, Selo, Vazio, type Tom } from '@/components/base'
import {
  apagarAutomacao,
  automacoesDaEmpresa,
  disparosDaAutomacao,
  mudarAutomacao,
  type DisparoDeAutomacao,
  type ListaDeAutomacoes,
  type RegraDeAutomacao,
  type SituacaoDaRegra,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const CHAVE = ['empresa', 'automacoes']
const FUSO = 'America/Sao_Paulo'

/** A volta do motor é de um minuto, com uma folga na subida: passado isto sem a primeira volta, ou sem volta nenhuma,
 *  ele parou ou se arrasta. A conta é pela hora do servidor (`motor.agora`). */
const MOTOR_SEM_PRIMEIRA_VOLTA_MS = 5 * 60_000
const MOTOR_CALADO_MS = 10 * 60_000

const ano = (d: Date) => d.toLocaleDateString('pt-BR', { year: 'numeric', timeZone: FUSO })
const hora = (t: string | number) =>
  new Date(t).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: FUSO })

/** "26/11 19:00" em Brasília; com o ano quando não é o deste ano (o relógio do navegador só decide se o ano aparece). */
function diaHora(iso: string): string {
  const d = new Date(iso)
  const dia = d.toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: ano(d) === ano(new Date()) ? undefined : 'numeric',
    timeZone: FUSO,
  })
  return `${dia} ${hora(iso)}`
}

const TOM_DA_SITUACAO: Record<SituacaoDaRegra, Tom> = {
  ligada: 'ok',
  ensaio: 'alerta',
  pausada: 'sem-dados',
  concluida: 'sem-dados',
}
const TOM_DO_STATUS: Record<string, Tom> = {
  enviada: 'ok',
  entregue: 'ok',
  falhou: 'parado',
  recusada: 'parado',
  venceu: 'parado',
}

/** O motor pela hora do SERVIDOR: "ligado" só com volta recente; configurado e calado é âmbar. */
function estadoDoMotor(m: ListaDeAutomacoes['motor']): { texto: string; alerta: boolean } {
  const agora = Date.parse(m.agora)
  if (!m.ligado) return { texto: 'Motor desligado neste servidor', alerta: true }
  if (m.ultima_volta === null) {
    if (m.iniciado_em === null) return { texto: 'Motor configurado, mas não subiu neste servidor', alerta: true }
    if (agora - Date.parse(m.iniciado_em) > MOTOR_SEM_PRIMEIRA_VOLTA_MS)
      return { texto: `Motor configurado, mas sem nenhuma volta desde que subiu às ${hora(m.iniciado_em)}`, alerta: true }
    return { texto: 'Motor ligado · ainda não deu a primeira volta desde a última publicação', alerta: false }
  }
  if (agora - Date.parse(m.ultima_volta) > MOTOR_CALADO_MS)
    return {
      texto: `Motor ligado, mas sem volta desde ${diaHora(m.ultima_volta)}: os avisos podem estar parados`,
      alerta: true,
    }
  return { texto: `Motor ligado · última volta às ${hora(m.ultima_volta)}`, alerta: false }
}

export function AutomacoesDaEmpresa() {
  const { data, error, dataUpdatedAt, errorUpdatedAt } = useQuery({
    queryKey: CHAVE,
    queryFn: automacoesDaEmpresa,
    // a última volta do motor e o último registro de cada regra andam sozinhos
    refetchInterval: 60_000,
  })
  const [pessoa, setPessoa] = useState('')
  const [abertaId, setAbertaId] = useState<number | null>(null)

  const regras = data?.regras ?? []
  // a gaveta lê a regra da lista viva: a volta de um minuto a atualiza, e a que sumiu fecha a gaveta
  const aberta = regras.find((r) => r.id === abertaId)
  // quem tem regra, pelo login (único); quem saiu da lista (apagou a última) volta a "todas"
  const donos = [...new Map(regras.map((r) => [r.dono_apelido, r.dono])).entries()].sort((a, b) =>
    a[1].localeCompare(b[1], 'pt-BR'),
  )
  const filtro = donos.some(([apelido]) => apelido === pessoa) ? pessoa : ''
  const linhas = filtro ? regras.filter((r) => r.dono_apelido === filtro) : regras
  const motor = data ? estadoDoMotor(data.motor) : null

  // a releitura de fundo que falhou não apaga a lista: ela fica, com a faixa dizendo de quando é. A hora da falha é a
  // do servidor: o relógio do navegador corrigido pela diferença medida na última leitura boa.
  let naoAtualizou: string | null = null
  if (data && error) {
    const frase = mensagemDeErro(error)
    const desvio = Date.parse(data.motor.agora) - dataUpdatedAt
    naoAtualizou = `Não consegui atualizar às ${hora(errorUpdatedAt + desvio)}: ${frase}${/[.!?]$/.test(frase) ? '' : '.'} A lista abaixo é de ${hora(data.motor.agora)}.`
  }

  return (
    <Pagina
      titulo="Automações"
      apoio="As regras e lembretes que as pessoas da empresa criaram pelo WhatsApp do Gestão Solar."
    >
      {/* `anywhere`: a palavra sem espaço (uma URL) quebra em qualquer ponto em vez de sair da caixa; é herdado por
          toda a tela, o detalhe inclusive (o título dele também) */}
      <div className="[overflow-wrap:anywhere]">
        {!data ? (
          error ? (
            <Erro>{mensagemDeErro(error)}</Erro>
          ) : (
            <Cartao>
              <div className="px-5">
                <Esqueleto linhas={3} />
              </div>
            </Cartao>
          )
        ) : (
          <>
            {naoAtualizou ? (
              <div className="mb-4">
                <Aviso>{naoAtualizou}</Aviso>
              </div>
            ) : null}
            <p className={`text-sm mb-4 ${motor?.alerta ? 'text-alerta' : 'text-rotulo'}`}>{motor?.texto}</p>

            {regras.length ? (
              <div className="grid gap-3 sm:grid-cols-3 mb-4">
                <select className="campo" value={filtro} onChange={(e) => setPessoa(e.target.value)} aria-label="Pessoa">
                  <option value="">Todas as pessoas</option>
                  {donos.map(([apelido, nome]) => (
                    <option key={apelido} value={apelido}>
                      {nome} ({apelido})
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <Cartao>
              {!regras.length ? (
                <Vazio
                  titulo="Ninguém da empresa criou regra ainda"
                  descricao="Peça pelo WhatsApp do Gestão Solar: «me lembra de ver a geração amanhã ao meio-dia» ou «me avisa se a tensão do relé de Pirapozinho acabar por mais de 10 min»."
                />
              ) : (
                linhas.map((r, i) => (
                  <LinhaDaRegra key={r.id} regra={r} primeiro={i === 0} aoAbrir={() => setAbertaId(r.id)} />
                ))
              )}
            </Cartao>
          </>
        )}

        {aberta ? <Detalhe regra={aberta} aoFechar={() => setAbertaId(null)} /> : null}
      </div>
    </Pagina>
  )
}

/** As linhas da regra, as mesmas na lista e no alto do detalhe. Só elementos de frase: moram dentro de um botão. */
function Resumo({ regra: r }: { regra: RegraDeAutomacao }) {
  const d = r.ultimo_disparo
  return (
    <>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Selo tom={r.cega ? 'alerta' : (TOM_DA_SITUACAO[r.situacao] ?? 'sem-dados')}>{r.situacao_rotulo}</Selo>
        <span className="min-w-0 text-xs text-rotulo">{r.situacao_ajuda}</span>
      </span>
      <span className="text-sm text-rotulo">
        {r.dono}
        <span className="mono text-xs text-fraco ml-2">{r.dono_apelido}</span>
      </span>
      <span className="text-sm text-corpo">
        {r.quando}
        {r.onde ? ` · ${r.onde}` : ''}
      </span>
      <span className="text-xs text-fraco">
        {r.agenda_rotulo ? `${r.agenda_rotulo} · ` : ''}Avisa por: {r.entrega_rotulo}
      </span>
      <span className="text-xs text-fraco">
        Último registro: {d ? `${diaHora(d.em)} · ${d.evento_rotulo} · ${d.status_rotulo}` : 'nenhum ainda'}
      </span>
      {r.cega ? <span className="text-sm text-alerta">{r.cega}</span> : null}
      {r.ensaio_segurados > 0 ? (
        <span className="text-sm text-alerta">
          {r.ensaio_segurados.toLocaleString('pt-BR')}{' '}
          {r.ensaio_segurados === 1 ? 'aviso guardado' : 'avisos guardados'} no ensaio
        </span>
      ) : null}
      {r.ultimo_erro ? <span className="text-sm text-parado">Último erro: {r.ultimo_erro}</span> : null}
    </>
  )
}

function LinhaDaRegra({
  regra: r,
  primeiro,
  aoAbrir,
}: {
  regra: RegraDeAutomacao
  primeiro: boolean
  aoAbrir: () => void
}) {
  return (
    <div className={primeiro ? '' : 'border-t border-borda'}>
      <button
        className="w-full text-left px-5 pt-4 pb-2 flex items-start gap-3 hover:bg-superficie-alta"
        onClick={aoAbrir}
        data-regra={r.id}
      >
        <span className="min-w-0 flex-1 grid gap-1 *:min-w-0">
          <span className="text-forte font-semibold">{r.nome}</span>
          <Resumo regra={r} />
        </span>
        <ChevronRight size={16} className="shrink-0 text-fraco mt-1" />
      </button>
      <div className="px-5 pb-4 pt-1">
        <Acoes regra={r} />
      </div>
    </div>
  )
}

/** Ligar, pausar, pôr em ensaio e apagar, na linha e no detalhe (para agir sem fechar). A recusa vem com a frase da
 *  API (o 409 do lembrete vencido, por exemplo). */
function Acoes({ regra: r }: { regra: RegraDeAutomacao }) {
  const qc = useQueryClient()
  const recarregar = () => qc.invalidateQueries({ queryKey: CHAVE })
  const mudar = useMutation({
    mutationFn: (situacao: Exclude<SituacaoDaRegra, 'concluida'>) => mudarAutomacao(r.id, situacao),
    onSuccess: recarregar,
  })
  const apagar = useMutation({ mutationFn: () => apagarAutomacao(r.id), onSuccess: recarregar })
  const ocupada = mudar.isPending || apagar.isPending
  const s = r.situacao

  return (
    <div className="grid gap-2 *:min-w-0">
      <div className="flex flex-wrap gap-2">
        {s === 'ensaio' || s === 'pausada' ? (
          <button
            className="btn-primario h-9 px-3 text-xs"
            disabled={ocupada}
            onClick={() =>
              window.confirm(
                `Ligar a regra «${r.nome}»? Os avisos desta regra passam a sair de verdade para ${r.dono}.`,
              ) && mudar.mutate('ligada')
            }
          >
            Ligar
          </button>
        ) : null}
        {s === 'ligada' || s === 'ensaio' ? (
          <button className="btn-fantasma" disabled={ocupada} onClick={() => mudar.mutate('pausada')}>
            Pausar
          </button>
        ) : null}
        {s === 'ligada' || s === 'pausada' ? (
          <button className="btn-fantasma" disabled={ocupada} onClick={() => mudar.mutate('ensaio')}>
            Pôr em ensaio
          </button>
        ) : null}
        <button
          className="btn-fantasma text-parado"
          disabled={ocupada}
          onClick={() =>
            window.confirm(`Apagar a regra «${r.nome}» de ${r.dono}? Os avisos que ela já mandou ficam no registro.`) &&
            apagar.mutate()
          }
        >
          Apagar
        </button>
      </div>
      {mudar.error || apagar.error ? <Erro>{mensagemDeErro(mudar.error ?? apagar.error)}</Erro> : null}
    </div>
  )
}

/** O detalhe: a regra inteira com os botões, as palavras de quem pediu e os 50 últimos avisos, com o texto inteiro. */
function Detalhe({ regra: r, aoFechar }: { regra: RegraDeAutomacao; aoFechar: () => void }) {
  const { data, error } = useQuery({
    queryKey: [...CHAVE, r.id, 'disparos'],
    queryFn: () => disparosDaAutomacao(r.id),
    refetchInterval: 60_000,
  })
  return (
    <Modal titulo={r.nome} aoFechar={aoFechar} largura="max-w-2xl">
      <div className="grid gap-5 *:min-w-0">
        <div className="grid gap-1 *:min-w-0">
          <Resumo regra={r} />
          <span className="text-xs text-fraco">Criada em {diaHora(r.criada_em)}</span>
        </div>
        <Acoes regra={r} />

        <div>
          <p className="rotulo-campo">As palavras de quem pediu</p>
          <p className="text-sm text-corpo whitespace-pre-wrap">{r.texto_original || '—'}</p>
        </div>

        <div className="grid gap-2 *:min-w-0">
          <p className="rotulo-campo">Últimos 50 avisos</p>
          {!data ? (
            error ? (
              <Erro>{mensagemDeErro(error)}</Erro>
            ) : (
              <Esqueleto linhas={2} />
            )
          ) : (
            <>
              {error ? <Aviso>Não consegui atualizar os avisos: {mensagemDeErro(error)}</Aviso> : null}
              {!data.length ? (
                <p className="text-sm text-fraco">Esta regra ainda não mandou nenhum aviso.</p>
              ) : (
                <ul className="grid gap-3 *:min-w-0">
                  {data.map((d) => (
                    <LinhaDoAviso key={d.id} disparo={d} />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </Modal>
  )
}

function LinhaDoAviso({ disparo: d }: { disparo: DisparoDeAutomacao }) {
  return (
    <li className="rounded-campo border border-borda px-3.5 py-3 grid gap-1.5 *:min-w-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="mono text-xs text-fraco">{diaHora(d.em)}</span>
        <span className="text-sm text-forte">{d.evento_rotulo}</span>
        {d.ensaio ? <Selo tom="alerta">ensaio</Selo> : null}
        <Selo tom={TOM_DO_STATUS[d.status] ?? 'sem-dados'}>{d.status_rotulo}</Selo>
      </div>
      <p className="text-xs text-fraco">
        Canal: {d.canal_rotulo} · Usina: {d.usina ?? '—'}
      </p>
      <p className="text-sm text-corpo whitespace-pre-wrap">{d.texto || '—'}</p>
      {d.leitura_linhas.length ? (
        <ul className="text-xs text-rotulo list-disc pl-4 space-y-0.5">
          {d.leitura_linhas.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      ) : null}
      {d.erro ? <Erro>{d.erro}</Erro> : null}
    </li>
  )
}

/** O carregando: o desenho das linhas, sem número nenhum (esqueleto, não um spinner solto). */
function Esqueleto({ linhas }: { linhas: number }) {
  return (
    <div role="status" className="grid animate-pulse">
      <span className="sr-only">Carregando…</span>
      {Array.from({ length: linhas }, (_, i) => (
        <div key={i} className={`grid gap-2 py-4 ${i ? 'border-t border-borda' : ''}`}>
          <div className="h-4 w-2/5 rounded bg-superficie-alta" />
          <div className="h-3 w-3/5 rounded bg-superficie-alta" />
          <div className="h-3 w-1/2 rounded bg-superficie-alta" />
        </div>
      ))}
    </div>
  )
}
