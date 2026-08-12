/**
 * As pontes do Gestão Solar com cada produto.
 *
 * Salvar não prova nada — testar prova. Por isso salvar já dispara o teste: o gestor
 * digitou uma credencial e precisa saber na hora se ela serve, não descobrir pelo cliente
 * dias depois.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plug, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Cartao, Carregando, Erro, Pagina, Selo, type Tom } from '@/components/base'
import {
  listarIntegracoes,
  salvarIntegracao,
  testarIntegracao,
  type Integracao,
  type Produto,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const DESCRICAO: Record<Produto, { nome: string; oQue: string }> = {
  meuwatt: { nome: 'meuWatt', oQue: 'geração, inversores, relatórios' },
  meuplano: { nome: 'meuPlano', oQue: 'cronograma, ordens de serviço, assistente' },
}

const ESTADO: Record<Integracao['estado'], { tom: Tom; rotulo: string }> = {
  ok: { tom: 'ok', rotulo: 'Conectado' },
  falhou: { tom: 'parado', rotulo: 'Com problema' },
  nunca: { tom: 'sem-dados', rotulo: 'Não testada' },
}

export function Conexoes() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['integracoes'],
    queryFn: listarIntegracoes,
  })

  return (
    <Pagina
      titulo="Conexões"
      apoio="A conta de serviço que o Gestão Solar usa para ler cada produto. Ela precisa enxergar as usinas dos clientes — o teste confere isso e diz quantas encontrou."
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
  const { nome, oQue } = DESCRICAO[integracao.produto]
  const estado = ESTADO[integracao.estado]

  const [url, setUrl] = useState(integracao.base_url ?? '')
  const [usuario, setUsuario] = useState(integracao.usuario_servico ?? '')
  const [senha, setSenha] = useState('')
  const [mensagem, setMensagem] = useState<{ ok: boolean; texto: string } | null>(null)

  // Quando outra ação recarrega a lista, os campos acompanham o servidor.
  useEffect(() => {
    setUrl(integracao.base_url ?? '')
    setUsuario(integracao.usuario_servico ?? '')
  }, [integracao.base_url, integracao.usuario_servico])

  const testar = useMutation({
    mutationFn: () => testarIntegracao(integracao.produto),
    onSuccess: (r) => {
      setMensagem({ ok: r.ok, texto: r.detalhe })
      qc.invalidateQueries({ queryKey: ['integracoes'] })
      if (r.ok) qc.invalidateQueries({ queryKey: ['conciliacao'] })
    },
    onError: (e) => setMensagem({ ok: false, texto: mensagemDeErro(e) }),
  })

  const salvar = useMutation({
    mutationFn: () =>
      salvarIntegracao(integracao.produto, {
        base_url: url.trim(),
        usuario_servico: usuario.trim(),
        senha: senha || null,
      }),
    onSuccess: () => {
      setSenha('')
      testar.mutate()
    },
    onError: (e) => setMensagem({ ok: false, texto: mensagemDeErro(e) }),
  })

  const ocupado = salvar.isPending || testar.isPending

  return (
    <Cartao className="p-5">
      <header className="flex items-center gap-3 mb-1">
        <h2 className="text-lg font-semibold text-forte">{nome}</h2>
        <Selo tom={estado.tom}>{estado.rotulo}</Selo>
        {integracao.usinas_visiveis !== null && integracao.estado === 'ok' ? (
          <span className="mono text-xs text-rotulo">
            {integracao.usinas_visiveis} usina(s) visíveis
          </span>
        ) : null}
      </header>
      <p className="text-sm text-rotulo mb-4">{oQue}</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="rotulo-campo" htmlFor={`url-${integracao.produto}`}>
            Endereço da API
          </label>
          <input
            id={`url-${integracao.produto}`}
            className="campo mono"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://api.exemplo.com.br"
          />
        </div>
        <div>
          <label className="rotulo-campo" htmlFor={`user-${integracao.produto}`}>
            Usuário de serviço
          </label>
          <input
            id={`user-${integracao.produto}`}
            className="campo"
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            placeholder="servico@empresa.com.br"
            autoComplete="off"
          />
        </div>
        <div>
          <label className="rotulo-campo" htmlFor={`senha-${integracao.produto}`}>
            Senha
          </label>
          <input
            id={`senha-${integracao.produto}`}
            type="password"
            className="campo"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            placeholder={integracao.configurada ? 'deixe vazio para manter a atual' : ''}
            autoComplete="new-password"
          />
        </div>
      </div>

      <div className="flex gap-2 items-center mt-4 flex-wrap">
        <button onClick={() => salvar.mutate()} className="btn-primario" disabled={ocupado}>
          <Plug size={15} />
          {salvar.isPending ? 'Salvando…' : 'Salvar e testar'}
        </button>
        <button
          onClick={() => testar.mutate()}
          className="btn-secundario"
          disabled={ocupado || !integracao.configurada}
        >
          <RefreshCw size={15} className={testar.isPending ? 'animate-spin' : ''} />
          {testar.isPending ? 'Testando…' : 'Testar conexão'}
        </button>
        {integracao.testada_em ? (
          <span className="mono text-xs text-fraco">
            último teste{' '}
            {new Date(integracao.testada_em).toLocaleString('pt-BR', {
              dateStyle: 'short',
              timeStyle: 'short',
            })}
          </span>
        ) : null}
      </div>

      {(mensagem ?? integracao.detalhe) ? (
        <p
          className={`text-sm mt-3 ${
            (mensagem ? mensagem.ok : integracao.estado === 'ok') ? 'text-ok' : 'text-parado'
          }`}
        >
          {mensagem ? mensagem.texto : integracao.detalhe}
        </p>
      ) : null}
    </Cartao>
  )
}
