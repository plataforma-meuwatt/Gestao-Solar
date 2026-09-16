/**
 * Administração do WhatsApp.
 *
 * É onde as credenciais da Meta são cadastradas: o token, o número, o segredo do app e o
 * token de verificação do webhook. Elas não moram em variável de ambiente de propósito —
 * quem configura é o gestor, e ele precisa testar: digitar, ver se responde, corrigir.
 *
 * A tela separa as duas metades porque elas falham sozinhas e pedem correções diferentes:
 *
 * - **envio** — token e número. Sem eles, nenhuma notificação sai.
 * - **webhook** — segredo do app e token de verificação. Sem eles, a Meta não consegue
 *   entregar o que o cliente escreve, e a URL nem chega a ser registrada.
 *
 * Gravar já testa, e o teste diz de quem é o número. Isso não é enfeite: colar o token de
 * outro app deixa o cartão verde com o número errado, e a falta só apareceria como mensagem
 * saindo de um número que o cliente não reconhece.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, History, KeyRound, Link2Off, MessageCircle, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { Campo, Cartao, Carregando, Erro, Pagina, Selo, type Tom } from '@/components/base'
import {
  credenciaisWhatsapp,
  eventosWhatsapp,
  removerCredenciaisWhatsapp,
  salvarCredenciaisWhatsapp,
  testarCredenciaisWhatsapp,
  type ResultadoWhatsapp,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const ESTADO: Record<string, { tom: Tom; rotulo: string }> = {
  ok: { tom: 'ok', rotulo: 'Conectado' },
  falhou: { tom: 'parado', rotulo: 'Com problema' },
  nunca: { tom: 'sem-dados', rotulo: 'Não testado' },
}

const ROTULO_EVENTO: Record<string, string> = {
  gravada: 'Credenciais gravadas',
  testada_ok: 'Teste passou',
  testada_falhou: 'Teste falhou',
  removida: 'Credenciais removidas',
  webhook_verificado: 'A Meta confirmou o webhook',
}

const APOIO =
  'O número de WhatsApp da empresa, pelo qual as notificações saem e as mensagens dos ' +
  'clientes chegam. O token vale o que a conta que o gerou vale, e o segredo do app é o ' +
  'que prova que uma entrega veio mesmo da Meta.'

function quando(iso: string | null | undefined) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export function Whatsapp() {
  const qc = useQueryClient()
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState<ResultadoWhatsapp | null>(null)
  const [editando, setEditando] = useState(false)
  const [verHistorico, setVerHistorico] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['whatsapp'],
    queryFn: credenciaisWhatsapp,
  })

  function aoResponder(r: ResultadoWhatsapp) {
    setResultado(r)
    setErro('')
    if (r.ok) setEditando(false)
    qc.invalidateQueries({ queryKey: ['whatsapp'] })
    qc.invalidateQueries({ queryKey: ['whatsapp-eventos'] })
  }

  const testar = useMutation({
    mutationFn: testarCredenciaisWhatsapp,
    onSuccess: aoResponder,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const remover = useMutation({
    mutationFn: removerCredenciaisWhatsapp,
    onSuccess: () => {
      setResultado(null)
      setErro('')
      qc.invalidateQueries({ queryKey: ['whatsapp'] })
      qc.invalidateQueries({ queryKey: ['whatsapp-eventos'] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  if (isLoading) return <Carregando />

  // O gateway fora do ar ou não configurado é estado do sistema, não erro de tela: a
  // mensagem do servidor já diz o que fazer.
  if (error) {
    return (
      <Pagina titulo="WhatsApp" apoio={APOIO}>
        <Erro>{mensagemDeErro(error)}</Erro>
      </Pagina>
    )
  }

  const estado = ESTADO[data?.estado ?? 'nunca'] ?? ESTADO.nunca
  const mostrandoFormulario = editando || !data?.configurada

  return (
    <Pagina titulo="WhatsApp" apoio={APOIO}>
      {erro ? <Erro className="mb-4">{erro}</Erro> : null}

      <Cartao className="p-5">
        <header className="flex items-center gap-3 mb-1 flex-wrap">
          <MessageCircle size={18} className="text-rotulo" />
          <h2 className="text-lg font-semibold text-forte">Número da empresa</h2>
          <Selo tom={estado.tom}>{estado.rotulo}</Selo>
          {data?.envio_pronto ? <Selo tom="ok">envio pronto</Selo> : (
            <Selo tom="alerta">envio não configurado</Selo>
          )}
          {data?.webhook_pronto ? <Selo tom="ok">webhook pronto</Selo> : (
            <Selo tom="alerta">webhook não configurado</Selo>
          )}
        </header>

        {data?.cifragem_disponivel === false ? (
          <Erro className="mt-3">
            O gateway está sem a chave de cifragem (GATEWAY_ENCRYPTION_KEY). Sem ela o token
            iria para o banco em texto, então nada pode ser gravado.
          </Erro>
        ) : null}

        {!mostrandoFormulario ? (
          <Gravado dados={data!} />
        ) : (
          <Formulario
            inicial={data}
            aoResponder={aoResponder}
            aoErro={(m) => setErro(m)}
            aoCancelar={data?.configurada ? () => setEditando(false) : undefined}
          />
        )}

        {!mostrandoFormulario ? (
          <div className="flex gap-2 items-center mt-4 flex-wrap">
            <button onClick={() => testar.mutate()} className="btn-primario" disabled={testar.isPending}>
              <RefreshCw size={15} className={testar.isPending ? 'animate-spin' : ''} />
              {testar.isPending ? 'Testando…' : 'Testar conexão'}
            </button>
            <button onClick={() => setEditando(true)} className="btn-secundario">
              <KeyRound size={15} />
              Trocar credenciais
            </button>
            <button
              onClick={() => remover.mutate()}
              className="btn-fantasma text-parado"
              disabled={remover.isPending}
              title="Apaga os segredos daqui. Não revoga nada na Meta."
            >
              <Link2Off size={15} />
              Remover
            </button>
            <button
              onClick={() => setVerHistorico((v) => !v)}
              className="btn-fantasma ml-auto"
              aria-expanded={verHistorico}
            >
              <History size={15} />
              Histórico
            </button>
          </div>
        ) : null}

        {resultado ? (
          resultado.ok ? (
            <div className="mt-3 rounded-campo border border-ok/30 bg-ok/10 p-3 flex items-start gap-2">
              <Check size={15} className="text-ok shrink-0 mt-0.5" />
              <p className="text-xs text-corpo">{resultado.detalhe}</p>
            </div>
          ) : (
            <Erro className="mt-3">{resultado.detalhe}</Erro>
          )
        ) : data?.detalhe ? (
          <p className={`text-sm mt-3 ${data.estado === 'ok' ? 'text-ok' : 'text-parado'}`}>
            {data.detalhe}
          </p>
        ) : null}

        {data?.testada_em ? (
          <p className="mono text-xs text-fraco mt-2">último teste {quando(data.testada_em)}</p>
        ) : null}

        {verHistorico ? <Historico /> : null}
      </Cartao>

      <Cartao titulo="Como ligar o webhook" className="mt-4">
        <ol className="px-5 pb-5 pt-1 text-sm text-rotulo list-decimal ml-4 flex flex-col gap-1.5">
          <li>
            Gere um token <strong>permanente</strong> (usuário do sistema) no Gerenciador de
            Negócios — o do painel do app expira em 24 horas.
          </li>
          <li>Cole aqui o token, o Phone Number ID e o segredo do app.</li>
          <li>
            Escolha um token de verificação qualquer, cole aqui e depois no painel da Meta, em
            Webhooks, junto do endereço do gateway terminado em <span className="mono">/webhook</span>.
          </li>
          <li>Assine o campo <span className="mono">messages</span> para receber as mensagens.</li>
        </ol>
      </Cartao>
    </Pagina>
  )
}

function Gravado({ dados }: { dados: NonNullable<Awaited<ReturnType<typeof credenciaisWhatsapp>>> }) {
  return (
    <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[auto,1fr] text-sm mt-3">
      <dt className="text-rotulo">Número (ID)</dt>
      <dd className="mono text-forte truncate">{dados.phone_number_id ?? '—'}</dd>

      <dt className="text-rotulo">Token</dt>
      <dd className="mono text-forte">
        {dados.token_prefixo ? (
          <>
            {dados.token_prefixo}
            <span className="text-fraco">………</span>
          </>
        ) : (
          <span className="text-fraco">não gravado</span>
        )}
      </dd>

      <dt className="text-rotulo">Conta (WABA)</dt>
      <dd className="mono text-forte truncate">{dados.waba_id ?? '—'}</dd>

      <dt className="text-rotulo">App</dt>
      <dd className="mono text-forte truncate">{dados.app_id ?? '—'}</dd>

      {dados.atualizada_por ? (
        <>
          <dt className="text-rotulo">Gravado por</dt>
          <dd className="text-forte">
            {dados.atualizada_por}
            <span className="mono text-xs text-fraco"> · {quando(dados.atualizada_em)}</span>
          </dd>
        </>
      ) : null}
    </dl>
  )
}

function Formulario({
  inicial,
  aoResponder,
  aoErro,
  aoCancelar,
}: {
  inicial?: Awaited<ReturnType<typeof credenciaisWhatsapp>>
  aoResponder: (r: ResultadoWhatsapp) => void
  aoErro: (m: string) => void
  aoCancelar?: () => void
}) {
  const [phoneNumberId, setPhoneNumberId] = useState(inicial?.phone_number_id ?? '')
  const [wabaId, setWabaId] = useState(inicial?.waba_id ?? '')
  const [appId, setAppId] = useState(inicial?.app_id ?? '')
  const [token, setToken] = useState('')
  const [appSecret, setAppSecret] = useState('')
  const [verifyToken, setVerifyToken] = useState('')

  const salvar = useMutation({
    mutationFn: () =>
      salvarCredenciaisWhatsapp({
        phone_number_id: phoneNumberId.trim(),
        waba_id: wabaId.trim() || null,
        app_id: appId.trim() || null,
        token: token.trim() || null,
        app_secret: appSecret.trim() || null,
        verify_token: verifyToken.trim() || null,
      }),
    onSuccess: (r) => {
      setToken('')
      setAppSecret('')
      setVerifyToken('')
      aoResponder(r)
    },
    onError: (e) => aoErro(mensagemDeErro(e)),
  })

  const jaTemToken = Boolean(inicial?.token_prefixo)

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        salvar.mutate()
      }}
      className="grid gap-3 mt-3"
    >
      <Campo
        rotulo="Phone Number ID"
        value={phoneNumberId}
        onChange={(e) => setPhoneNumberId(e.target.value)}
        className="mono"
        placeholder="1352387357947608"
        nota="Painel da Meta → WhatsApp → Configuração da API. Não é o telefone."
        required
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <Campo
          rotulo="WABA ID (opcional)"
          value={wabaId}
          onChange={(e) => setWabaId(e.target.value)}
          className="mono"
        />
        <Campo
          rotulo="App ID (opcional)"
          value={appId}
          onChange={(e) => setAppId(e.target.value)}
          className="mono"
        />
      </div>
      <Campo
        rotulo="Token de acesso"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="mono"
        placeholder={jaTemToken ? 'deixe vazio para manter o atual' : 'EAAG…'}
        autoComplete="off"
        spellCheck={false}
        nota="Use o permanente, de usuário do sistema. O do painel do app expira em 24 horas."
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <Campo
          rotulo="Segredo do app"
          value={appSecret}
          onChange={(e) => setAppSecret(e.target.value)}
          className="mono"
          type="password"
          autoComplete="off"
          placeholder={inicial?.webhook_pronto ? 'deixe vazio para manter' : ''}
          nota="Confere a assinatura de cada entrega da Meta."
        />
        <Campo
          rotulo="Token de verificação"
          value={verifyToken}
          onChange={(e) => setVerifyToken(e.target.value)}
          className="mono"
          autoComplete="off"
          placeholder={inicial?.webhook_pronto ? 'deixe vazio para manter' : ''}
          nota="Você escolhe o valor e repete no painel da Meta ao registrar a URL."
        />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          className="btn-primario"
          disabled={salvar.isPending || !phoneNumberId.trim()}
        >
          {salvar.isPending ? 'Testando e gravando…' : 'Gravar e testar'}
        </button>
        {aoCancelar ? (
          <button type="button" onClick={aoCancelar} className="btn-secundario">
            Cancelar
          </button>
        ) : null}
      </div>
    </form>
  )
}

function Historico() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['whatsapp-eventos'],
    queryFn: () => eventosWhatsapp(),
  })

  if (isLoading) return <Carregando texto="Carregando histórico…" />
  if (error) return <Erro className="mt-3">{mensagemDeErro(error)}</Erro>
  if (!data?.length) return <p className="text-sm text-fraco mt-4">Nada aconteceu ainda.</p>

  return (
    <ol className="mt-4 border-t border-borda divide-y divide-borda">
      {data.map((e, i) => (
        <li key={i} className="py-2.5 flex gap-3 items-baseline flex-wrap">
          <span className="mono text-xs text-fraco w-28 shrink-0">{quando(e.ocorrido_em)}</span>
          <span
            className={`text-sm font-medium ${
              e.evento === 'testada_falhou' ? 'text-parado' : 'text-forte'
            }`}
          >
            {ROTULO_EVENTO[e.evento] ?? e.evento}
          </span>
          {e.token_prefixo ? (
            <span className="mono text-xs text-fraco">{e.token_prefixo}…</span>
          ) : null}
          {e.detalhe ? <span className="text-sm text-rotulo min-w-0">{e.detalhe}</span> : null}
          {e.ator ? <span className="mono text-xs text-fraco ml-auto">{e.ator}</span> : null}
        </li>
      ))}
    </ol>
  )
}
