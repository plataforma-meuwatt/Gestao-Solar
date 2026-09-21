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

import { Campo, Cartao, Carregando, Erro, Pagina, Selo, Seletor, type Tom } from '@/components/base'
import {
  credenciaisWhatsapp,
  enviarTesteWhatsapp,
  eventosWhatsapp,
  numerosWhatsapp,
  removerCredenciaisWhatsapp,
  salvarCredenciaisWhatsapp,
  templatesWhatsapp,
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

      {data?.configurada ? <NumerosDaConta idEmUso={data.phone_number_id} /> : null}
      {data?.configurada ? <Modelos /> : null}

      <Cartao titulo="Como ligar o webhook" className="mt-4">
        <ol className="px-5 pb-5 pt-1 text-sm text-rotulo list-decimal ml-4 flex flex-col gap-1.5">
          <li>
            Gere um token <strong>permanente</strong> (usuário do sistema) no Gerenciador de
            Negócios — o do painel do app expira em 24 horas.
          </li>
          <li>Cole aqui o token, o Phone Number ID e o segredo do app.</li>
          <li>
            Escolha um token de verificação qualquer, cole aqui e depois no painel da Meta, em
            Webhooks, junto deste endereço:
            {data?.webhook_url ? (
              <code className="mono block mt-1.5 rounded-campo border border-borda bg-fundo px-3 py-2 text-forte break-all">
                {data.webhook_url}
              </code>
            ) : (
              <span className="text-fraco"> (o endereço aparece aqui quando o gateway estiver configurado)</span>
            )}
          </li>
          <li>Assine o campo <span className="mono">messages</span> para receber as mensagens.</li>
        </ol>
      </Cartao>
    </Pagina>
  )
}

/**
 * Os números que a conta da Meta tem.
 *
 * Existe por um erro real (21/09/2026): o primeiro cadastro gravou o número de TESTE no
 * lugar do comercial, e o teste de conexão respondeu "ok" — porque enviar usa o id do
 * número, e aquele id existia. A tela pedia três identificadores de dezesseis dígitos e
 * não mostrava nenhum; agora ela mostra o que a conta tem, com o que está em uso marcado.
 */
function NumerosDaConta({ idEmUso }: { idEmUso: string | null | undefined }) {
  const { data, isLoading, error } = useQuery({ queryKey: ['whatsapp-numeros'], queryFn: numerosWhatsapp, retry: false })

  return (
    <Cartao titulo="Números desta conta" className="mt-4">
      <div className="px-5 pb-5 pt-1">
        {isLoading ? <Carregando /> : null}
        {error ? <p className="text-sm text-rotulo">{mensagemDeErro(error)}</p> : null}
        {(data ?? []).map((n) => (
          <div key={n.id} className="flex items-center gap-3 py-2 border-b border-borda last:border-0 flex-wrap">
            <span className="font-semibold text-forte">{n.numero ?? '—'}</span>
            <span className="text-sm text-rotulo">{n.nome ?? ''}</span>
            {n.id === idEmUso ? <Selo tom="ok">em uso</Selo> : null}
            <span className="mono text-xs text-fraco ml-auto">{n.id}</span>
          </div>
        ))}
        {data && data.length === 0 ? (
          <p className="text-sm text-rotulo">A conta não tem número nenhum.</p>
        ) : null}
      </div>
    </Cartao>
  )
}

/**
 * Os modelos de mensagem, e o envio de prova.
 *
 * Fora da janela de 24 horas a Meta só aceita modelo aprovado — então esta lista é o teto
 * do que o robô consegue dizer. Os reprovados e os pendentes aparecem junto: esconder um
 * modelo recusado faria procurar no lugar errado por que o aviso não sai.
 */
function Modelos() {
  const { data, isLoading, error } = useQuery({ queryKey: ['whatsapp-templates'], queryFn: templatesWhatsapp, retry: false })
  const [escolhido, setEscolhido] = useState('')
  const [telefone, setTelefone] = useState('')
  const [parametros, setParametros] = useState('')
  const [saida, setSaida] = useState<string | null>(null)

  const modelo = (data ?? []).find((t) => t.nome === escolhido)

  const enviar = useMutation({
    mutationFn: () =>
      enviarTesteWhatsapp({
        telefone,
        template: escolhido,
        parametros: parametros ? parametros.split('|').map((p) => p.trim()) : [],
      }),
    onSuccess: (r) =>
      setSaida(r.ok ? `Enviado. Identificação da mensagem: ${r.wamid}` : `Recusado: ${r.erro}`),
    onError: (e) => setSaida(mensagemDeErro(e)),
  })

  const aprovados = (data ?? []).filter((t) => t.situacao === 'APPROVED')

  return (
    <Cartao titulo="Modelos de mensagem" className="mt-4">
      <div className="px-5 pb-5 pt-1">
        {isLoading ? <Carregando /> : null}
        {error ? <p className="text-sm text-rotulo">{mensagemDeErro(error)}</p> : null}

        {(data ?? []).map((t) => (
          <div key={`${t.nome}-${t.idioma}`} className="py-2.5 border-b border-borda last:border-0">
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="mono text-sm text-forte">{t.nome}</span>
              <Selo tom={t.situacao === 'APPROVED' ? 'ok' : t.situacao === 'REJECTED' ? 'parado' : 'alerta'}>
                {t.situacao === 'APPROVED' ? 'aprovado' : t.situacao === 'REJECTED' ? 'reprovado' : 'em análise'}
              </Selo>
              <span className="text-xs text-fraco">
                {t.categoria} · {t.idioma}
                {t.parametros > 0 ? ` · ${t.parametros} parâmetro(s)` : ''}
              </span>
            </div>
            {t.corpo ? <p className="text-xs text-rotulo mt-1 whitespace-pre-wrap">{t.corpo}</p> : null}
          </div>
        ))}

        {data && data.length === 0 ? (
          <p className="text-sm text-rotulo">
            Nenhum modelo nesta conta. Sem modelo aprovado, nenhum aviso sai — crie em
            Gerenciador do WhatsApp → Modelos de mensagem.
          </p>
        ) : null}

        {aprovados.length > 0 ? (
          <div className="mt-4 rounded-campo bg-superficie p-4">
            <p className="text-sm font-semibold text-forte mb-3">Enviar um teste</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Seletor rotulo="Modelo" value={escolhido} onChange={(e) => setEscolhido(e.target.value)}>
                <option value="">escolha…</option>
                {aprovados.map((t) => (
                  <option key={t.nome} value={t.nome}>
                    {t.nome}
                  </option>
                ))}
              </Seletor>
              <Campo
                rotulo="Telefone"
                value={telefone}
                onChange={(e) => setTelefone(e.target.value)}
                placeholder="+55 17 99999-0000"
                nota="Com DDI e DDD."
              />
            </div>
            {modelo && modelo.parametros > 0 ? (
              <Campo
                rotulo={`Parâmetros (${modelo.parametros}, separados por |)`}
                value={parametros}
                onChange={(e) => setParametros(e.target.value)}
                placeholder="Usina Tietê | 14:12"
              />
            ) : null}
            <button
              onClick={() => {
                setSaida(null)
                enviar.mutate()
              }}
              className="btn-primario mt-3"
              disabled={!escolhido || !telefone || enviar.isPending}
            >
              {enviar.isPending ? 'Enviando…' : 'Enviar teste'}
            </button>
            {saida ? <p className="text-sm text-corpo mt-3">{saida}</p> : null}
          </div>
        ) : null}
      </div>
    </Cartao>
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
