/**
 * As pontes do Gestão Solar com cada produto.
 *
 * A conexão se faz por TOKEN: alguém gera um token pessoal na própria conta do meuWatt e
 * do meuPlano e cola aqui. Melhor que usuário e senha em três pontos — o Gestão Solar
 * nunca vê a senha de ninguém, trocar a senha lá não derruba a integração, e o acesso é
 * revogável na origem por quem o emitiu.
 *
 * Conectar já testa, e o teste diz DE QUEM é o token. Isso não é enfeite: colar o token
 * da pessoa errada é o engano que passa despercebido — o cartão fica verde, o escopo de
 * usinas vem menor, e a falta só aparece semanas depois como usina sumida na tela de um
 * cliente. Ver o nome do dono na hora é o que fecha essa porta.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, History, Plug, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Cartao, Carregando, Erro, Pagina, Selo, type Tom } from '@/components/base'
import {
  conectarPorToken,
  desconectarToken,
  historicoIntegracao,
  listarIntegracoes,
  testarIntegracao,
  type EventoIntegracao,
  type Integracao,
  type Produto,
  type ResultadoTeste,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { prefixoDe, problemaNoToken, tokenPreenchido } from '@/lib/tokenProduto'

const DESCRICAO: Record<Produto, { nome: string; oQue: string; onde: string }> = {
  meuwatt: {
    nome: 'meuWatt',
    oQue: 'geração, inversores, relatórios',
    onde: 'no meuWatt, em Perfil → Tokens de acesso',
  },
  meuplano: {
    nome: 'meuPlano',
    oQue: 'cronograma, ordens de serviço, assistente',
    onde: 'no meuPlano, em Minha conta → Tokens de acesso',
  },
}

const ESTADO: Record<Integracao['estado'], { tom: Tom; rotulo: string }> = {
  ok: { tom: 'ok', rotulo: 'Conectado' },
  falhou: { tom: 'parado', rotulo: 'Com problema' },
  nunca: { tom: 'sem-dados', rotulo: 'Não testada' },
}

const ROTULO_EVENTO: Record<EventoIntegracao['evento'], string> = {
  token_gravado: 'Token conectado',
  token_removido: 'Token removido',
  teste_ok: 'Teste passou',
  teste_falhou: 'Teste falhou',
  senha_gravada: 'Conta de serviço gravada',
}

function quando(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export function Conexoes() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['integracoes'],
    queryFn: listarIntegracoes,
  })

  return (
    <Pagina
      titulo="Conexões"
      apoio="O token que o Gestão Solar usa para ler cada produto. Ele vale o que a conta de quem o gerou vale — precisa enxergar as usinas dos clientes, e o teste confere isso e diz quantas encontrou."
    >
      {error ? <Erro className="mb-4">{mensagemDeErro(error)}</Erro> : null}
      {isLoading ? <Carregando /> : null}

      <div className="flex flex-col gap-4">
        {(data ?? []).map((i) => (
          <CartaoConexao key={i.produto} integracao={i} />
        ))}
      </div>
    </Pagina>
  )
}

function CartaoConexao({ integracao }: { integracao: Integracao }) {
  const qc = useQueryClient()
  const { nome, oQue, onde } = DESCRICAO[integracao.produto]
  const estado = ESTADO[integracao.estado]

  const [url, setUrl] = useState(integracao.base_url ?? '')
  const [token, setToken] = useState('')
  const [trocando, setTrocando] = useState(false)
  const [verHistorico, setVerHistorico] = useState(false)
  const [resultado, setResultado] = useState<ResultadoTeste | null>(null)
  const [erro, setErro] = useState('')

  const problema = problemaNoToken(integracao.produto, token)
  const podeConectar = url.trim().length > 3 && tokenPreenchido(integracao.produto, token)
  const mostrandoFormulario = trocando || !integracao.por_token

  function aoResponder(r: ResultadoTeste) {
    setResultado(r)
    setErro('')
    if (r.ok) {
      setToken('')
      setTrocando(false)
      qc.invalidateQueries({ queryKey: ['conciliacao'] })
    }
    qc.invalidateQueries({ queryKey: ['integracoes'] })
    qc.invalidateQueries({ queryKey: ['eventos', integracao.produto] })
  }

  const conectar = useMutation({
    mutationFn: () => conectarPorToken(integracao.produto, { base_url: url.trim(), token: token.trim() }),
    onSuccess: aoResponder,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const testar = useMutation({
    mutationFn: () => testarIntegracao(integracao.produto),
    onSuccess: aoResponder,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const desconectar = useMutation({
    mutationFn: () => desconectarToken(integracao.produto),
    onSuccess: () => {
      setResultado(null)
      setErro('')
      qc.invalidateQueries({ queryKey: ['integracoes'] })
      qc.invalidateQueries({ queryKey: ['eventos', integracao.produto] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const ocupado = conectar.isPending || testar.isPending || desconectar.isPending

  return (
    <Cartao className="p-5">
      <header className="flex items-center gap-3 mb-1 flex-wrap">
        <h2 className="text-lg font-semibold text-forte">{nome}</h2>
        <Selo tom={estado.tom}>{estado.rotulo}</Selo>
        {integracao.usinas_visiveis !== null && integracao.estado === 'ok' ? (
          <span className="mono text-xs text-rotulo">
            {integracao.usinas_visiveis} usina(s) visíveis
          </span>
        ) : null}
      </header>
      <p className="text-sm text-rotulo mb-4">{oQue}</p>

      {integracao.configurada && !integracao.por_token ? (
        <div className="mb-4">
          <Aviso>
            Esta conexão ainda usa a conta de serviço <strong>{integracao.usuario_servico}</strong> com
            senha guardada. Gere um token {onde} e cole abaixo — a senha deixa de ser
            necessária e sai do banco.
          </Aviso>
        </div>
      ) : null}

      {integracao.por_token && !trocando ? (
        <TokenGravado integracao={integracao} />
      ) : (
        <Formulario
          produto={integracao.produto}
          onde={onde}
          url={url}
          setUrl={setUrl}
          token={token}
          setToken={setToken}
          problema={problema}
        />
      )}

      <div className="flex gap-2 items-center mt-4 flex-wrap">
        {mostrandoFormulario ? (
          <>
            <button
              onClick={() => conectar.mutate()}
              className="btn-primario"
              disabled={ocupado || !podeConectar}
            >
              <Plug size={15} />
              {conectar.isPending ? 'Conectando…' : 'Conectar e testar'}
            </button>
            {trocando ? (
              <button
                onClick={() => {
                  setTrocando(false)
                  setToken('')
                }}
                className="btn-fantasma"
                disabled={ocupado}
              >
                Cancelar
              </button>
            ) : null}
          </>
        ) : (
          <>
            <button onClick={() => testar.mutate()} className="btn-primario" disabled={ocupado}>
              <RefreshCw size={15} className={testar.isPending ? 'animate-spin' : ''} />
              {testar.isPending ? 'Testando…' : 'Testar conexão'}
            </button>
            <button onClick={() => setTrocando(true)} className="btn-secundario" disabled={ocupado}>
              Trocar token
            </button>
            <button
              onClick={() => desconectar.mutate()}
              className="btn-fantasma text-parado"
              disabled={ocupado}
              title="Para de usar o token aqui. Não o revoga no produto de origem."
            >
              <Trash2 size={15} />
              Desconectar
            </button>
          </>
        )}

        <button
          onClick={() => setVerHistorico((v) => !v)}
          className="btn-fantasma ml-auto"
          aria-expanded={verHistorico}
        >
          <History size={15} />
          Histórico
        </button>
      </div>

      {erro ? <Erro className="mt-3">{erro}</Erro> : null}

      {resultado ? (
        <p className={`text-sm mt-3 ${resultado.ok ? 'text-ok' : 'text-parado'}`}>
          {resultado.detalhe}
        </p>
      ) : integracao.detalhe ? (
        <p className={`text-sm mt-3 ${integracao.estado === 'ok' ? 'text-ok' : 'text-parado'}`}>
          {integracao.detalhe}
        </p>
      ) : null}

      {integracao.testada_em ? (
        <p className="mono text-xs text-fraco mt-2">último teste {quando(integracao.testada_em)}</p>
      ) : null}

      {verHistorico ? <Historico produto={integracao.produto} /> : null}
    </Cartao>
  )
}

function TokenGravado({ integracao }: { integracao: Integracao }) {
  const dono = integracao.token_dono_nome || integracao.token_dono_email

  return (
    <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[auto,1fr] text-sm">
      <dt className="text-rotulo">Endereço</dt>
      <dd className="mono text-forte truncate">{integracao.base_url}</dd>

      <dt className="text-rotulo">Token</dt>
      <dd className="mono text-forte">
        {integracao.token_prefixo}
        <span className="text-fraco">………</span>
      </dd>

      <dt className="text-rotulo">Conta</dt>
      <dd className="text-forte">
        {dono ?? <span className="text-fraco">desconhecida</span>}
        {integracao.token_dono_email && integracao.token_dono_nome ? (
          <span className="text-fraco mono text-xs"> · {integracao.token_dono_email}</span>
        ) : null}
      </dd>

      {integracao.token_gravado_em ? (
        <>
          <dt className="text-rotulo">Conectado em</dt>
          <dd className="mono text-xs text-fraco self-center">
            {quando(integracao.token_gravado_em)}
          </dd>
        </>
      ) : null}
    </dl>
  )
}

function Formulario({
  produto,
  onde,
  url,
  setUrl,
  token,
  setToken,
  problema,
}: {
  produto: Produto
  onde: string
  url: string
  setUrl: (v: string) => void
  token: string
  setToken: (v: string) => void
  problema: string | null
}) {
  return (
    <div className="grid gap-3">
      <div>
        <label className="rotulo-campo" htmlFor={`url-${produto}`}>
          Endereço da API
        </label>
        <input
          id={`url-${produto}`}
          className="campo mono"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://api.exemplo.com.br"
        />
      </div>

      <div>
        <label className="rotulo-campo" htmlFor={`token-${produto}`}>
          Token de acesso
        </label>
        <input
          id={`token-${produto}`}
          className={`campo mono ${problema ? 'border-parado' : ''}`}
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={`${prefixoDe(produto)}…`}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={problema ? true : undefined}
          aria-describedby={`ajuda-${produto}`}
        />
        <p id={`ajuda-${produto}`} className={`text-xs mt-1.5 ${problema ? 'text-parado' : 'text-fraco'}`}>
          {problema ?? (
            <>
              Gere {onde} e cole aqui. O valor só aparece uma vez, na hora em que é criado.{' '}
              <ExternalLink size={11} className="inline align-[-1px]" />
            </>
          )}
        </p>
      </div>
    </div>
  )
}

function Historico({ produto }: { produto: Produto }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['eventos', produto],
    queryFn: () => historicoIntegracao(produto),
  })

  if (isLoading) return <Carregando texto="Carregando histórico…" />
  if (error) return <Erro className="mt-3">{mensagemDeErro(error)}</Erro>
  if (!data?.length) {
    return <p className="text-sm text-fraco mt-4">Nada aconteceu com esta conexão ainda.</p>
  }

  return (
    <ol className="mt-4 border-t border-borda divide-y divide-borda">
      {data.map((e, i) => (
        <li key={i} className="py-2.5 flex gap-3 items-baseline flex-wrap">
          <span className="mono text-xs text-fraco w-28 shrink-0">{quando(e.ocorrido_em)}</span>
          <span
            className={`text-sm font-medium ${
              e.evento === 'teste_falhou' ? 'text-parado' : 'text-forte'
            }`}
          >
            {ROTULO_EVENTO[e.evento] ?? e.evento}
          </span>
          {e.token_prefixo ? (
            <span className="mono text-xs text-fraco">{e.token_prefixo}…</span>
          ) : null}
          {e.detalhe ? <span className="text-sm text-rotulo min-w-0">{e.detalhe}</span> : null}
          {e.ator_email ? (
            <span className="mono text-xs text-fraco ml-auto">{e.ator_email}</span>
          ) : null}
        </li>
      ))}
    </ol>
  )
}
