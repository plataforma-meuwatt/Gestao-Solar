/**
 * Log do bot — o que o assistente do WhatsApp recebeu e fez com cada mensagem.
 *
 * Pedido do dono para o adm-gs ("vejo log dos bots"): de quem (conta e empresa, ou o número
 * sem cadastro), o resultado, a pergunta, a resposta, as ferramentas usadas e quanto levou.
 * O mesmo registro aparece recortado na página da empresa e, no oem-gs, para o gerente.
 */

import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio, type Tom } from '@/components/base'
import { listarEmpresas, logDoBot, saudeDoCanal, type RegistroBot } from '@/features/api'
import { quando } from '@/features/rotulos'
import { mensagemDeErro } from '@/lib/api'

const RESULTADO: Record<RegistroBot['resultado'], { tom: Tom; rotulo: string }> = {
  respondeu: { tom: 'ok', rotulo: 'Respondeu' },
  sem_conta: { tom: 'alerta', rotulo: 'Número sem cadastro' },
  nao_liberado: { tom: 'alerta', rotulo: 'Bot não liberado' },
  sem_texto: { tom: 'sem-dados', rotulo: 'Não era texto' },
  zerou: { tom: 'sem-dados', rotulo: 'Conversa zerada' },
  atrasada: { tom: 'alerta', rotulo: 'Chegou atrasada — sem resposta' },
  erro: { tom: 'parado', rotulo: 'Erro' },
}

export function LogDoBot() {
  const [parametros, setParametros] = useSearchParams()
  const empresa = parametros.get('empresa') ?? ''
  const [resultado, setResultado] = useState('')
  const [busca, setBusca] = useState('')

  const { data: empresas } = useQuery({ queryKey: ['empresas'], queryFn: listarEmpresas })
  const filtro = { empresa_id: empresa ? Number(empresa) : undefined, resultado: resultado || undefined }
  const { data, isLoading, error } = useQuery({
    queryKey: ['log-do-bot', filtro],
    queryFn: () => logDoBot(filtro),
  })

  const linhas = useMemo(() => {
    const t = busca.trim().toLowerCase()
    if (!t) return data ?? []
    return (data ?? []).filter((r) =>
      [r.usuario, r.apelido, r.telefone, r.pergunta, r.resposta, r.erro]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(t)),
    )
  }, [data, busca])

  return (
    <Pagina
      titulo="Log do bot"
      apoio="Cada mensagem que chegou ao bot do WhatsApp: de quem e de qual empresa, o que perguntou, o que o bot respondeu, as ferramentas que usou e quanto levou. Número sem cadastro também aparece — é quem tentou falar com o bot sem conta no Gestão Solar."
    >
      <SaudeDoCanalCartao />

      <div className="grid gap-3 sm:grid-cols-3 mb-4">
        <select
          className="campo"
          value={empresa}
          onChange={(e) => {
            const p = new URLSearchParams(parametros)
            if (e.target.value) p.set('empresa', e.target.value)
            else p.delete('empresa')
            setParametros(p)
          }}
          aria-label="Empresa"
        >
          <option value="">Todas as empresas</option>
          {(empresas ?? []).map((e) => (
            <option key={e.id} value={e.id}>
              {e.nome}
            </option>
          ))}
        </select>
        <select className="campo" value={resultado} onChange={(e) => setResultado(e.target.value)} aria-label="Resultado">
          <option value="">Todos os resultados</option>
          {Object.entries(RESULTADO).map(([k, v]) => (
            <option key={k} value={k}>
              {v.rotulo}
            </option>
          ))}
        </select>
        <input
          className="campo"
          placeholder="buscar pessoa, número ou texto"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          aria-label="Buscar no log"
        />
      </div>

      <Cartao>
        {isLoading ? (
          <Carregando />
        ) : error ? (
          <div className="p-5">
            <Erro>{mensagemDeErro(error)}</Erro>
          </div>
        ) : !linhas.length ? (
          <Vazio
            titulo={data?.length ? 'Nada com esse filtro' : 'Nenhuma mensagem ainda'}
            descricao="As mensagens aparecem aqui assim que alguém escreve para o número do bot."
          />
        ) : (
          linhas.map((r, i) => <LinhaDoLog key={r.id} registro={r} primeiro={i === 0} />)
        )}
      </Cartao>
    </Pagina>
  )
}

/**
 * Se o bot está OUVINDO. Não é o "webhook pronto" da tela do WhatsApp (isso é configuração):
 * é o que de fato chega e sai. Em 10/2026 o bot ficou mais de um dia surdo — 40 mensagens
 * presas no gateway por um erro de banco — com a tela de configuração toda verde.
 */
function SaudeDoCanalCartao() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['saude-do-canal'],
    queryFn: saudeDoCanal,
    refetchInterval: 60_000,
  })
  if (isLoading) return null
  if (error) return <Erro className="mb-4">{mensagemDeErro(error)}</Erro>
  if (!data) return null
  return (
    <Cartao className="mb-4 px-5 py-4">
      <div className="flex items-center gap-3 flex-wrap">
        <Selo tom={data.ouvindo ? 'ok' : 'parado'}>{data.ouvindo ? 'Bot ouvindo' : 'Bot NÃO está ouvindo'}</Selo>
        <span className={`text-sm ${data.ouvindo ? 'text-rotulo' : 'text-parado'}`}>{data.resumo}</span>
      </div>
      {data.helper_alcancavel !== null ? (
        <div className="flex items-center gap-3 flex-wrap mt-2">
          <Selo tom={data.helper_alcancavel ? 'ok' : 'parado'}>
            {data.helper_alcancavel ? 'Helper alcançável' : 'Helper fora'}
          </Selo>
          <span className={`text-sm ${data.helper_alcancavel ? 'text-rotulo' : 'text-parado'}`}>{data.helper_resumo}</span>
        </div>
      ) : null}
      <p className="text-xs text-fraco mt-2">
        última mensagem recebida: {quando(data.ultima_recebida_em)} · última mensagem respondida (enviada em):{' '}
        {quando(data.ultima_resposta_em)} · última entrega confirmada pela Meta: {quando(data.ultima_entregue_em)}
      </p>
    </Cartao>
  )
}

/** Uma mensagem. Fechada mostra quem, quando e o resultado; aberta, a pergunta e a resposta. */
export function LinhaDoLog({ registro: r, primeiro }: { registro: RegistroBot; primeiro: boolean }) {
  const [aberta, setAberta] = useState(false)
  const res = RESULTADO[r.resultado] ?? { tom: 'sem-dados' as Tom, rotulo: r.resultado }
  return (
    <div className={primeiro ? '' : 'border-t border-borda'}>
      <button
        className="w-full text-left px-5 py-3 flex items-start sm:items-center gap-3 hover:bg-superficie-alta/40"
        onClick={() => setAberta((v) => !v)}
      >
        {aberta ? <ChevronDown size={14} className="shrink-0 text-fraco mt-1 sm:mt-0" /> : <ChevronRight size={14} className="shrink-0 text-fraco mt-1 sm:mt-0" />}
        <span className="mono text-xs text-fraco w-28 shrink-0 hidden sm:block">{quando(r.em)}</span>
        <span className="min-w-0 flex-1">
          <span className="text-sm text-forte break-words">
            {r.usuario ? `${r.usuario} (${r.apelido})` : r.telefone}
          </span>
          <span className="text-xs text-fraco ml-2">{r.empresa ?? (r.usuario ? 'sem empresa' : '')}</span>
          {r.pergunta ? (
            <span className="block text-xs text-rotulo truncate">{r.pergunta}</span>
          ) : null}
          {/* No celular, quando e o resultado descem para baixo do nome: lado a lado, o selo
              cobria o número e a pergunta virava uma letra (avaliação de 24/10/2026). */}
          <span className="flex sm:hidden flex-wrap items-center gap-x-2 gap-y-1 mt-1.5">
            <span className="mono text-xs text-fraco">{quando(r.em)}</span>
            <Selo tom={res.tom}>{res.rotulo}</Selo>
          </span>
        </span>
        {r.duracao_ms !== null ? (
          <span className="mono text-xs text-fraco hidden sm:block">
            {(r.duracao_ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s
          </span>
        ) : null}
        <span className="hidden sm:block shrink-0">
          <Selo tom={res.tom}>{res.rotulo}</Selo>
        </span>
      </button>
      {aberta ? (
        <div className="px-5 pb-4 pl-12 grid gap-2 text-sm">
          <p className="text-xs text-fraco">
            {r.telefone}
            {r.ferramentas.length ? ` · ferramentas: ${r.ferramentas.join(', ')}` : ''}
          </p>
          {r.pergunta ? (
            <div>
              <p className="rotulo-campo">Pergunta</p>
              <p className="text-corpo whitespace-pre-wrap">{r.pergunta}</p>
            </div>
          ) : null}
          {r.resposta ? (
            <div>
              <p className="rotulo-campo">Resposta</p>
              <p className="text-corpo whitespace-pre-wrap">{r.resposta}</p>
            </div>
          ) : null}
          {r.erro ? <Erro>{r.erro}</Erro> : null}
        </div>
      ) : null}
    </div>
  )
}
