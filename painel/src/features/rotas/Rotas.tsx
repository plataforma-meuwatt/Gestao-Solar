/**
 * O inventário do que este sistema depende nos produtos de origem — e o botão que
 * pergunta a cada rota se ela ainda responde.
 *
 * A tela de Conexões (do gerente, no oem-gs) responde "o token vale?". Esta responde "o que ainda funciona?", que
 * é outra pergunta: um token perfeitamente válido convive com uma rota que mudou de lugar
 * no último deploy do meuWatt, e o sintoma disso é uma aba vazia no aplicativo de um
 * cliente, semanas depois.
 *
 * Cada linha diz **o que quebra** se aquela rota cair. É o que transforma
 * `/plants/{slug}/slots` numa frase que faz alguém agir.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  MinusCircle,
  Play,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'

import { Cartao, Erro, Pagina, Selo, Seletor } from '@/components/base'
import {
  listarEmpresas,
  listarRotas,
  sondarRotas,
  type Produto,
  type RotaSondada,
  type SituacaoRota,
  type Varredura,
  rotasDoHelper,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const PRODUTOS: { chave: Produto; nome: string; oQueTraz: string }[] = [
  { chave: 'meuwatt', nome: 'meuWatt', oQueTraz: 'geração, inversores e faturas' },
  { chave: 'meuplano', nome: 'meuPlano', oQueTraz: 'cronograma, ordens de serviço e notificações' },
]

export function Rotas() {
  // A plataforma não tem token (regra do dono, 23/10/2026): sonda-se com a conta de UMA
  // empresa, a que o gerente dela colou no oem-gs. Só leitura.
  const { data: empresas } = useQuery({ queryKey: ['empresas'], queryFn: listarEmpresas })
  const [escolhida, setEscolhida] = useState('')
  // Por padrão, a primeira empresa que JÁ conectou a conta dela: sondar com uma sem conexão
  // só responderia "ainda não conectou".
  const padrao = empresas?.find((e) => e.conexao_meuwatt || e.conexao_meuplano) ?? empresas?.[0]
  const empresaId = Number(escolhida || padrao?.id || 0)
  return (
    <Pagina
      titulo="Rotas"
      apoio="Tudo que o Gestão Solar consome nas duas plataformas. Sondar chama cada rota com a conexão da empresa escolhida e mostra o que voltou."
    >
      <div className="mb-5 max-w-sm">
        <Seletor
          rotulo="Sondar com a conexão de"
          value={String(empresaId || '')}
          onChange={(e) => setEscolhida(e.target.value)}
        >
          {(empresas ?? []).map((e) => (
            <option key={e.id} value={e.id}>
              {e.nome}
            </option>
          ))}
        </Seletor>
      </div>
      <div className="flex flex-col gap-5">
        {PRODUTOS.map((p) => (
          <BlocoProduto key={`${p.chave}-${empresaId}`} {...p} empresaId={empresaId} />
        ))}
        <BlocoHelper />
      </div>
    </Pagina>
  )
}

/** A porta do bot do helper: declarada, não sondada (toda chamada exige o token da pessoa —
 *  a plataforma não tem), com o alcance de agora no alto: túnel e VPN até as usinas. */
function BlocoHelper() {
  const { data, isLoading, error } = useQuery({ queryKey: ['rotas', 'helper'], queryFn: rotasDoHelper })
  return (
    <Cartao>
      <div className="px-5 pt-4 pb-3">
        <div className="flex items-center gap-3 flex-wrap">
          <p className="text-forte font-semibold">Helper — porta do bot</p>
          {data ? <Selo tom={data.ok ? 'ok' : 'parado'}>{data.ok ? 'alcançável' : 'fora'}</Selo> : null}
          {data ? <Selo tom="sem-dados">{data.rotas.length} catalogadas</Selo> : null}
        </div>
        <p className="text-sm text-rotulo mt-1">
          {data?.detalhe ??
            'Ler e comandar as usinas pelo bot do WhatsApp, com o token de cada pessoa. Não é sondado daqui: a plataforma não tem token.'}
        </p>
      </div>
      {isLoading ? null : error ? (
        <div className="px-5 pb-5">
          <Erro>{mensagemDeErro(error)}</Erro>
        </div>
      ) : (
        (data?.rotas ?? []).map((r, i) => <Linha key={r.chave} rota={r} primeira={i === 0} />)
      )}
    </Cartao>
  )
}

function BlocoProduto({
  chave,
  nome,
  oQueTraz,
  empresaId,
}: {
  chave: Produto
  nome: string
  oQueTraz: string
  empresaId: number
}) {
  // O catálogo em repouso é a base; a varredura, quando existe, o substitui. Guardar em
  // estado local (e não no cache do react-query) é deliberado: a varredura é um evento,
  // não um dado que se revalida sozinho — refazer uma dúzia de chamadas ao produto de
  // terceiro por causa de um refetch automático seria carga que ninguém pediu.
  const [varrido, setVarrido] = useState<Varredura | null>(null)
  const [erro, setErro] = useState('')

  const { data: catalogo, isLoading } = useQuery({
    queryKey: ['rotas', chave],
    queryFn: () => listarRotas(chave),
  })

  const sondar = useMutation({
    mutationFn: () => sondarRotas(chave, empresaId),
    onSuccess: (r) => {
      setVarrido(r)
      setErro('')
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const atual = varrido ?? catalogo
  const rotas = atual?.rotas ?? []

  const contagem = {
    ok: rotas.filter((r) => r.situacao === 'ok').length,
    falhou: rotas.filter((r) => r.situacao === 'falhou').length,
    pulada: rotas.filter((r) => r.situacao === 'pulada').length,
  }

  return (
    <Cartao>
      <header className="flex items-center gap-3 px-5 pt-4 pb-3 flex-wrap">
        <h2 className="text-sm font-semibold text-forte">
          {nome}
          <span className="text-fraco font-normal"> · {oQueTraz}</span>
        </h2>

        {varrido ? (
          varrido.ok ? (
            <Selo tom="ok">{contagem.ok} respondendo</Selo>
          ) : (
            <Selo tom="parado">{contagem.falhou} sem responder</Selo>
          )
        ) : (
          <Selo tom="sem-dados">{rotas.length} catalogadas</Selo>
        )}

        <button
          onClick={() => sondar.mutate()}
          className="btn-secundario ml-auto"
          disabled={sondar.isPending || !empresaId}
        >
          <Play size={14} />
          {sondar.isPending ? 'Sondando…' : varrido ? 'Sondar de novo' : 'Sondar agora'}
        </button>
      </header>

      <div className="px-5 pb-3">
        {erro ? <Erro>{erro}</Erro> : null}

        {atual ? (
          <p className={`text-xs ${varrido && !varrido.ok ? 'text-parado' : 'text-fraco'}`}>
            {atual.detalhe}
            {varrido?.executada_em ? (
              <>
                {' · '}
                {new Date(varrido.executada_em).toLocaleString('pt-BR', {
                  dateStyle: 'short',
                  timeStyle: 'short',
                  timeZone: 'America/Sao_Paulo',
                })}
              </>
            ) : null}
            {contagem.pulada ? ` · ${contagem.pulada} pulada(s)` : ''}
          </p>
        ) : null}

        {isLoading ? <p className="text-xs text-fraco">Carregando o catálogo…</p> : null}
      </div>

      <div className="border-t border-borda">
        {rotas.map((r, i) => (
          <Linha key={r.chave} rota={r} primeira={i === 0} />
        ))}
      </div>
    </Cartao>
  )
}

/**
 * Um ícone por situação, e cada um significa uma coisa diferente do gestor fazer:
 * falhou → investigar; pulada → a rota anterior não entregou o parâmetro; não sondada →
 * decisão nossa de não chamar, com o motivo ao lado.
 */
const ICONE: Record<SituacaoRota, { Icone: typeof CheckCircle2; cor: string }> = {
  ok: { Icone: CheckCircle2, cor: 'text-ok' },
  falhou: { Icone: XCircle, cor: 'text-parado' },
  pulada: { Icone: AlertTriangle, cor: 'text-alerta' },
  nao_sondada: { Icone: MinusCircle, cor: 'text-fraco' },
  pendente: { Icone: CircleDashed, cor: 'text-fraco' },
}

function Linha({ rota, primeira }: { rota: RotaSondada; primeira: boolean }) {
  const { Icone, cor } = ICONE[rota.situacao]

  return (
    <div className={`px-5 py-3 ${primeira ? '' : 'border-t border-borda'}`}>
      <div className="flex items-baseline gap-2.5 flex-wrap">
        <Icone size={14} className={`${cor} shrink-0 self-center`} />

        <code className="mono text-xs text-forte break-all">
          <span className="text-fraco">{rota.metodo}</span> {rota.caminho}
        </code>

        {!rota.essencial ? (
          <span className="text-[10px] text-fraco border border-borda rounded px-1.5 py-0.5">
            secundária
          </span>
        ) : null}

        <span className="ml-auto flex items-baseline gap-3 mono text-[11px] text-fraco">
          {rota.itens !== null ? <span>{rota.itens} item(ns)</span> : null}
          {rota.status !== null ? <span>{rota.status}</span> : null}
          {rota.ms !== null ? <span>{rota.ms} ms</span> : null}
        </span>
      </div>

      <p className="text-xs text-rotulo mt-1 ml-6">{rota.alimenta}</p>

      {rota.detalhe ? (
        <p className={`text-xs mt-1 ml-6 ${rota.situacao === 'falhou' ? 'text-parado' : 'text-fraco'}`}>
          {rota.detalhe}
        </p>
      ) : null}

      {/* Os campos que voltaram. É por aqui que uma mudança de formato aparece antes de
          virar tela quebrada no celular do cliente. */}
      {rota.campos.length ? (
        <p className="mono text-[11px] text-fraco mt-1 ml-6 break-words">
          {rota.campos.join(' · ')}
        </p>
      ) : null}
    </div>
  )
}
