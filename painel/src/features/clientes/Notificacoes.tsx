/**
 * A central de notificações do cliente.
 *
 * Três decisões que andam juntas, e por isso moram no mesmo cartão:
 *
 * 1. **Para onde** — telefone e o aceite registrado no contrato. Sem os dois, nada sai por
 *    mais que esteja marcado, e a tela diz qual dos dois falta em vez de ficar calada.
 * 2. **O quê, de qual usina** — a matriz. O funil começa na pessoa e afunila na usina:
 *    quem tem dez usinas quase nunca quer o mesmo aviso das dez.
 * 3. **O que já saiu** — o histórico, que abre vazio enquanto o envio não existir.
 *
 * Separar em telas faria o gestor marcar o aviso e esquecer o telefone — e o cliente
 * ficaria com tudo configurado e nada chegando.
 *
 * O estado da matriz é local enquanto ele mexe e só vai ao servidor no Salvar: marcar seis
 * caixas é uma requisição, não seis, e dá para desistir sem ter mudado nada.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellRing, History, Pencil } from 'lucide-react'
import { useState } from 'react'

import { Campo, Cartao, Erro, Selo, Vazio } from '@/components/base'
import {
  centralDeNotificacoes,
  definirNotificacoes,
  historicoDeNotificacoes,
  salvarContatoWhatsapp,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

/** `parada|4` — o par que a matriz marca. */
const par = (tipo: string, plantLinkId: number) => `${tipo}|${plantLinkId}`

function quando(iso: string | null) {
  if (!iso) return null
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export function CartaoNotificacoes({ clienteId, nome }: { clienteId: number; nome: string }) {
  const qc = useQueryClient()
  const [erro, setErro] = useState('')
  const [rascunho, setRascunho] = useState<Set<string> | null>(null)
  const [editandoContato, setEditandoContato] = useState(false)
  const [vendoHistorico, setVendoHistorico] = useState(false)

  const { data: central, isLoading } = useQuery({
    queryKey: ['notificacoes', clienteId],
    queryFn: () => centralDeNotificacoes(clienteId),
  })

  // O rascunho nasce do servidor na primeira renderização com dados. Depois disso ele é a
  // verdade da tela — recalcular a cada render desfaria o clique do gestor.
  const marcados =
    rascunho ??
    new Set(
      (central?.tipos ?? []).flatMap((t) =>
        t.usinas.filter((u) => u.marcada).map((u) => par(t.tipo, u.plant_link_id)),
      ),
    )

  const sujo =
    rascunho !== null &&
    (central?.tipos ?? []).some((t) =>
      t.usinas.some((u) => u.marcada !== marcados.has(par(t.tipo, u.plant_link_id))),
    )

  const salvar = useMutation({
    mutationFn: () =>
      definirNotificacoes(
        clienteId,
        [...marcados].map((chave) => {
          const [tipo, id] = chave.split('|')
          return { tipo, plant_link_id: Number(id) }
        }),
      ),
    onSuccess: () => {
      setRascunho(null)
      setErro('')
      qc.invalidateQueries({ queryKey: ['notificacoes', clienteId] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  function alternar(chave: string) {
    const proximo = new Set(marcados)
    if (proximo.has(chave)) proximo.delete(chave)
    else proximo.add(chave)
    setRascunho(proximo)
  }

  function alternarTipo(tipo: string, ids: number[], ligarTudo: boolean) {
    const proximo = new Set(marcados)
    for (const id of ids) {
      if (ligarTudo) proximo.add(par(tipo, id))
      else proximo.delete(par(tipo, id))
    }
    setRascunho(proximo)
  }

  const contato = central?.contato

  return (
    <Cartao
      titulo={`Notificações · ${marcados.size}`}
      className="lg:col-span-2"
      acao={
        <button onClick={() => setVendoHistorico((v) => !v)} className="btn-fantasma">
          <History size={13} />
          {vendoHistorico ? 'Ocultar envios' : 'Últimos envios'}
        </button>
      }
    >
      {isLoading || !central ? (
        <p className="px-5 py-4 text-sm text-fraco">Carregando…</p>
      ) : (
        <>
          {/* ── para onde vai ─────────────────────────────────────────────── */}
          <div className="px-5 py-4 border-b border-borda">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <BellRing size={14} className="text-rotulo" />
                  <p className="text-sm font-semibold text-forte">WhatsApp do cliente</p>
                  {contato?.apto ? (
                    <Selo tom="ok">pronto para receber</Selo>
                  ) : (
                    <Selo tom="alerta">não recebe ainda</Selo>
                  )}
                </div>
                <p className="mono text-xs text-fraco mt-1">
                  {contato?.telefone_exibicao ?? 'sem telefone'}
                  {contato?.telefone && !contato.e_celular ? ' · fixo, não recebe WhatsApp' : ''}
                </p>
                <p className="text-xs text-fraco mt-0.5">
                  {contato?.aceite_em
                    ? `Aceite registrado em ${quando(contato.aceite_em)}${
                        contato.aceite_por ? ` por ${contato.aceite_por}` : ''
                      }`
                    : 'Aceite do contrato ainda não registrado'}
                </p>
                {contato?.impedimento ? (
                  <p className="text-xs text-alerta mt-1">{contato.impedimento}</p>
                ) : null}
              </div>

              <button onClick={() => setEditandoContato((v) => !v)} className="btn-fantasma">
                <Pencil size={13} />
                {editandoContato ? 'Fechar' : 'Editar contato'}
              </button>
            </div>

            {editandoContato ? (
              <FormularioContato
                clienteId={clienteId}
                telefone={contato?.telefone_exibicao ?? ''}
                aceite={Boolean(contato?.aceite_em)}
                aoSalvar={() => {
                  setEditandoContato(false)
                  qc.invalidateQueries({ queryKey: ['notificacoes', clienteId] })
                  qc.invalidateQueries({ queryKey: ['cliente', clienteId] })
                }}
              />
            ) : null}
          </div>

          {/* ── o quê, de qual usina ──────────────────────────────────────── */}
          {central.sem_usinas ? (
            <Vazio
              titulo="Nenhuma usina concedida"
              descricao={`${nome} precisa ter usina para escolher o que recebe de cada uma.`}
            />
          ) : (
            <>
              <p className="px-5 pt-4 text-sm text-rotulo">
                Marque, por aviso, de quais usinas {nome} quer receber. Nada vem ligado: sem
                marcar, ele não recebe nada.
              </p>

              {central.tipos.map((t) => {
                const ids = t.usinas.map((u) => u.plant_link_id)
                const todas = ids.every((id) => marcados.has(par(t.tipo, id)))
                return (
                  <div key={t.tipo} className="px-5 py-4 border-t border-borda">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-forte">
                          {t.rotulo}{' '}
                          <span className="text-xs font-normal text-fraco">· {t.origem}</span>
                        </p>
                        <p className="text-xs text-fraco">{t.descricao}</p>
                      </div>
                      <button
                        onClick={() => alternarTipo(t.tipo, ids, !todas)}
                        className="btn-fantasma shrink-0"
                      >
                        {todas ? 'Nenhuma' : 'Todas'}
                      </button>
                    </div>

                    <div className="mt-2.5 grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
                      {t.usinas.map((u) => {
                        const chave = par(t.tipo, u.plant_link_id)
                        return (
                          <label
                            key={chave}
                            className="flex items-center gap-2.5 py-1 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={marcados.has(chave)}
                              onChange={() => alternar(chave)}
                            />
                            <span className="text-sm text-corpo truncate">{u.nome}</span>
                          </label>
                        )
                      })}
                    </div>
                  </div>
                )
              })}

              {erro ? (
                <div className="px-5 pt-3">
                  <Erro>{erro}</Erro>
                </div>
              ) : null}

              <div className="flex gap-2 px-5 py-4 border-t border-borda">
                <button
                  onClick={() => salvar.mutate()}
                  className="btn-primario"
                  disabled={!sujo || salvar.isPending}
                >
                  {salvar.isPending ? 'Salvando…' : 'Salvar notificações'}
                </button>
                {sujo ? (
                  <button onClick={() => setRascunho(null)} className="btn-secundario">
                    Descartar
                  </button>
                ) : null}
              </div>
            </>
          )}

          {vendoHistorico ? <Historico clienteId={clienteId} /> : null}
        </>
      )}
    </Cartao>
  )
}

function FormularioContato({
  clienteId,
  telefone,
  aceite,
  aoSalvar,
}: {
  clienteId: number
  telefone: string
  aceite: boolean
  aoSalvar: () => void
}) {
  const [valor, setValor] = useState(telefone)
  const [marcado, setMarcado] = useState(aceite)
  const [erro, setErro] = useState('')

  const salvar = useMutation({
    mutationFn: () =>
      salvarContatoWhatsapp(clienteId, { telefone: valor.trim() || null, aceite: marcado }),
    onSuccess: aoSalvar,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        setErro('')
        salvar.mutate()
      }}
      className="mt-4 flex flex-col gap-3"
    >
      {erro ? <Erro>{erro}</Erro> : null}
      <Campo
        rotulo="Telefone"
        value={valor}
        onChange={(e) => setValor(e.target.value)}
        placeholder="(16) 99999-8888"
        nota="Pode digitar como quiser — com DDD. O sistema guarda num formato só."
      />
      <label className="flex items-start gap-2.5 cursor-pointer">
        <input
          type="checkbox"
          checked={marcado}
          onChange={(e) => setMarcado(e.target.checked)}
          className="mt-1"
        />
        <span className="text-sm text-corpo">
          Aceite registrado no contrato
          <span className="block text-xs text-fraco">
            A cláusula que ele assinou é a autorização. Sem esta marca, nada é enviado.
          </span>
        </span>
      </label>
      <div className="flex gap-2">
        <button type="submit" className="btn-primario" disabled={salvar.isPending}>
          {salvar.isPending ? 'Salvando…' : 'Salvar contato'}
        </button>
      </div>
    </form>
  )
}

function Historico({ clienteId }: { clienteId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['notificacoes-historico', clienteId],
    queryFn: () => historicoDeNotificacoes(clienteId),
  })

  if (isLoading) return <p className="px-5 py-4 text-sm text-fraco">Carregando envios…</p>

  if (!data?.length) {
    return (
      <div className="px-5 py-4 border-t border-borda">
        <p className="text-sm text-rotulo">Nenhuma mensagem enviada ainda.</p>
        <p className="text-xs text-fraco mt-0.5">
          O envio entra quando o WhatsApp estiver ligado. Até lá, esta central guarda a
          escolha.
        </p>
      </div>
    )
  }

  return (
    <div className="border-t border-borda">
      {data.map((e, i) => (
        <div
          key={`${e.criada_em}-${i}`}
          className={`flex items-center gap-4 px-5 py-3 ${i ? 'border-t border-borda' : ''}`}
        >
          <div className="min-w-0 flex-1">
            <p className="text-sm text-forte truncate">
              {e.tipo_rotulo}
              {e.usina ? ` · ${e.usina}` : ''}
            </p>
            <p className="mono text-xs text-fraco">
              {quando(e.criada_em)}
              {e.destino ? ` · ${e.destino}` : ''}
            </p>
            {e.erro ? <p className="text-xs text-parado mt-0.5">{e.erro}</p> : null}
          </div>
          <Selo tom={e.status === 'falhou' ? 'parado' : e.status === 'pendente' ? 'alerta' : 'ok'}>
            {e.status}
          </Selo>
        </div>
      ))}
    </div>
  )
}
