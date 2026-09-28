/**
 * As contas da EMPRESA no meuWatt e no meuPlano.
 *
 * Cada empresa de O&M tem a conta dela nos dois produtos. O que se cola aqui é um token
 * gerado **naquela conta**, e ele vale exatamente o que ela vale lá: usina que a conta não
 * enxerga no meuWatt não aparece aqui. Por isso a resposta do teste diz quantas usinas o
 * token alcançou — uma credencial aceita que não vê nada abriria a plataforma vazia, sem
 * erro nenhum na tela.
 *
 * **Enquanto a empresa não tiver a conta dela, quem responde é a credencial da
 * plataforma** — e a tela diz isso, em vez de mostrar tudo verde. Esse atalho existe para
 * a migração e para de valer sozinho: no dia em que houver mais de uma empresa ativa, o
 * servidor recusa usá-lo, porque a credencial da plataforma é de uma das empresas e
 * serviria a carteira dela para a outra.
 *
 * **Desconectar não revoga.** O token continua válido no produto de origem; o que muda é
 * que a plataforma para de usá-lo. Fechar a porta de verdade é lá.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Aviso, Campo, Cartao, Carregando, Erro, Pagina, Selo } from '@/components/base'
import {
  conectarEmpresa,
  conexoesDaEmpresa,
  desconectarEmpresa,
  type ConexaoDaEmpresa,
  type Produto,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

const NOME: Record<Produto, string> = { meuwatt: 'meuWatt', meuplano: 'meuPlano' }
const ENDERECO_SUGERIDO: Record<Produto, string> = {
  meuwatt: 'https://api.meuwatt.com.br',
  meuplano: 'https://meuplano.up.railway.app',
}

export function ConexoesDaEmpresa() {
  const empresa = useAuth((s) => s.empresa)
  const { data, isLoading, error } = useQuery({
    queryKey: ['empresa', 'conexoes'],
    queryFn: conexoesDaEmpresa,
  })

  return (
    <Pagina
      titulo="Conexões"
      apoio={
        empresa
          ? `As contas de ${empresa} no meuWatt e no meuPlano`
          : 'As contas da sua empresa no meuWatt e no meuPlano'
      }
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : (
        <div className="grid gap-3">
          {(data ?? []).map((c) => (
            <Conexao key={c.produto} conexao={c} />
          ))}
        </div>
      )}
    </Pagina>
  )
}

function Conexao({ conexao }: { conexao: ConexaoDaEmpresa }) {
  const qc = useQueryClient()
  const [token, setToken] = useState('')
  const [endereco, setEndereco] = useState(
    conexao.base_url ?? ENDERECO_SUGERIDO[conexao.produto],
  )
  const [abrindo, setAbrindo] = useState(false)

  const conectar = useMutation({
    mutationFn: () => conectarEmpresa(conexao.produto, { base_url: endereco, token }),
    onSuccess: (r) => {
      if (r.ok) {
        setToken('')
        setAbrindo(false)
        qc.invalidateQueries({ queryKey: ['empresa'] })
      }
    },
  })

  const desconectar = useMutation({
    mutationFn: () => desconectarEmpresa(conexao.produto),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresa'] }),
  })

  const ligada = conexao.configurada && conexao.propria

  return (
    <Cartao>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-forte font-semibold">{NOME[conexao.produto]}</p>
          {ligada ? (
            <p className="text-sm text-rotulo mt-1">
              Conectado como {conexao.token_dono_nome ?? conexao.token_dono_email ?? 'conta sem nome'}
              {conexao.usinas_visiveis !== null ? ` · ${conexao.usinas_visiveis} usina(s)` : ''}
            </p>
          ) : (
            <p className="text-sm text-rotulo mt-1">
              {conexao.configurada
                ? 'Respondendo pela credencial da plataforma'
                : 'Sem conexão'}
            </p>
          )}
        </div>
        <Selo tom={ligada ? 'ok' : 'alerta'}>{ligada ? 'Própria' : 'Pendente'}</Selo>
      </div>

      {!ligada ? (
        <Aviso>
          Enquanto a conta desta empresa não estiver conectada, o que você vê depende de uma
          credencial que não é sua — e ela para de valer assim que houver outra empresa na
          plataforma. Gere um token dentro da sua conta do {NOME[conexao.produto]} e cole aqui.
        </Aviso>
      ) : null}

      {abrindo ? (
        <div className="grid gap-3 mt-4">
          <Campo
            rotulo="Endereço da API"
            value={endereco}
            onChange={(e) => setEndereco(e.target.value)}
          />
          <Campo
            rotulo="Token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="cole aqui o token gerado na sua conta"
            nota="O token é conferido antes de ser gravado. Não servindo, a conexão de antes continua de pé."
          />

          {conectar.data && !conectar.data.ok ? <Erro>{conectar.data.detalhe}</Erro> : null}
          {conectar.error ? <Erro>{mensagemDeErro(conectar.error)}</Erro> : null}

          <div className="flex justify-end gap-2">
            <button className="botao-secundario" onClick={() => setAbrindo(false)}>
              Cancelar
            </button>
            <button
              className="botao"
              onClick={() => conectar.mutate()}
              disabled={!token.trim() || conectar.isPending}
            >
              {conectar.isPending ? 'Conferindo…' : 'Conectar'}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2 mt-4">
          <button className="botao-secundario" onClick={() => setAbrindo(true)}>
            {ligada ? 'Trocar o token' : 'Conectar'}
          </button>
          {ligada ? (
            <button
              className="botao-secundario"
              onClick={() => desconectar.mutate()}
              disabled={desconectar.isPending}
            >
              Desconectar
            </button>
          ) : null}
        </div>
      )}

      {ligada ? (
        <p className="text-xs text-fraco mt-3">
          Desconectar aqui não revoga o token no {NOME[conexao.produto]} — ele continua válido
          lá, e é lá que a porta se fecha de verdade.
        </p>
      ) : null}
      {desconectar.error ? <Erro>{mensagemDeErro(desconectar.error)}</Erro> : null}
    </Cartao>
  )
}
