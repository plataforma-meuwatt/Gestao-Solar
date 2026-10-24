/**
 * As peças de uma CONTA que o adm-gs mostra nos dois lados — dentro da empresa e na lista de
 * todos os usuários: o resumo (papel, celular, bot, token próprio, usinas, último acesso), a
 * senha nova e as empresas da conta (pôr e tirar — um usuário pode estar em mais de uma).
 *
 * Do token, só o FATO: a pessoa tem ou não o dela. O adm não tem token, nem vê prefixo.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, MessageCircle, Sun, UserCog } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Carregando, Erro, Modal } from '@/components/base'
import {
  listarEmpresas,
  porUsuarioNaEmpresa,
  tirarUsuarioDaEmpresa,
  type Conta,
  type Produto,
  type UsuarioDaEmpresaAdmin,
} from '@/features/api'
import { NOME_DO_PRODUTO, PAPEL, quando, textoDoBot } from '@/features/rotulos'
import { mensagemDeErro } from '@/lib/api'

/** As linhas de informação de uma conta. */
export function ResumoDaConta({ conta }: { conta: UsuarioDaEmpresaAdmin }) {
  const tokens = (['meuwatt', 'meuplano'] as Produto[]).map(
    (p) => `${NOME_DO_PRODUTO[p]} ${conta.tokens.includes(p) ? '✓' : '✗'}`,
  )
  return (
    <div className="text-sm text-rotulo mt-1.5 flex items-center gap-x-4 gap-y-1 flex-wrap">
      <span className="flex items-center gap-1.5">
        <UserCog size={14} />
        {PAPEL[conta.perfil] ?? conta.perfil}
      </span>
      {conta.perfil === 'cliente' ? (
        <span className="flex items-center gap-1.5">
          <Sun size={14} />
          {conta.usinas} {conta.usinas === 1 ? 'usina' : 'usinas'} no app
        </span>
      ) : null}
      <span className="flex items-center gap-1.5">
        <MessageCircle size={14} />
        {conta.telefone ?? 'sem celular'} · bot:{' '}
        {textoDoBot(conta.bot, conta.tokens, Boolean(conta.telefone))}
      </span>
      <span className="flex items-center gap-1.5">
        <KeyRound size={14} />
        token próprio: {tokens.join(' · ')}
      </span>
      <span>último acesso: {quando(conta.ultimo_login)}</span>
    </div>
  )
}

/** Senha nova, definida aqui e entregue à pessoa junto com o apelido. */
export function SenhaNova({
  aoDefinir,
  ocupado,
}: {
  aoDefinir: (senha: string) => void
  ocupado: boolean
}) {
  const [senha, setSenha] = useState('')
  return (
    <div className="flex gap-2 mt-3">
      <input
        className="campo h-9 text-sm"
        type="text"
        placeholder="senha nova (mínimo 8 caracteres)"
        value={senha}
        onChange={(e) => setSenha(e.target.value)}
        autoFocus
      />
      <button
        className="btn-secundario h-9 shrink-0"
        disabled={senha.length < 8 || ocupado}
        onClick={() => aoDefinir(senha)}
      >
        Definir
      </button>
    </div>
  )
}

/**
 * As empresas desta conta: a de origem (que cuida da senha, do celular, dos tokens e do bot)
 * e as outras. Pôr numa empresa não tira das outras; tirar de uma leva junto as usinas que
 * a pessoa recebia de lá.
 */
export function EmpresasDaConta({ conta, aoFechar }: { conta: Conta; aoFechar: () => void }) {
  const qc = useQueryClient()
  const { data: empresas, isLoading } = useQuery({ queryKey: ['empresas'], queryFn: listarEmpresas })
  const [escolhida, setEscolhida] = useState('')
  const atualizar = () => {
    qc.invalidateQueries({ queryKey: ['contas'] })
    qc.invalidateQueries({ queryKey: ['empresas'] })
    qc.invalidateQueries({ queryKey: ['empresa-usuarios'] })
  }

  const por = useMutation({
    mutationFn: (empresaId: number) => porUsuarioNaEmpresa(empresaId, conta.id),
    onSuccess: () => {
      setEscolhida('')
      atualizar()
      aoFechar()
    },
  })
  const tirar = useMutation({
    mutationFn: (empresaId: number) => tirarUsuarioDaEmpresa(empresaId, conta.id),
    onSuccess: () => {
      atualizar()
      aoFechar()
    },
  })

  const dela = new Set(conta.empresas.map((e) => e.id))
  const livres = (empresas ?? []).filter((e) => !dela.has(e.id))

  return (
    <Modal titulo={`Empresas de ${conta.nome}`} aoFechar={aoFechar}>
      {isLoading ? (
        <Carregando />
      ) : (
        <div className="grid gap-4">
          <Aviso>
            Uma pessoa pode estar em mais de uma empresa, com o mesmo papel. A empresa de{' '}
            <strong>origem</strong> cuida da conta (senha, celular, tokens e bot); nas outras ela
            é {conta.perfil === 'cliente' ? 'dona de usina' : PAPEL[conta.perfil]?.toLowerCase()} e
            recebe só o que aquela empresa der.
          </Aviso>

          {conta.empresas.length ? (
            <ul className="grid gap-2">
              {conta.empresas.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3">
                  <span className="text-sm text-forte">
                    {e.nome}
                    {e.origem ? <span className="text-xs text-ok ml-2">origem</span> : null}
                  </span>
                  <button
                    className="btn-fantasma"
                    disabled={tirar.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Tirar ${conta.nome} de ${e.nome}? As usinas que ela recebe de lá saem junto.`,
                        )
                      )
                        tirar.mutate(e.id)
                    }}
                  >
                    Tirar desta empresa
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-alerta">
              Sem empresa: nenhum gerente enxerga esta conta, e o aplicativo dela vem vazio.
            </p>
          )}

          <div>
            <p className="rotulo-campo">Pôr em outra empresa</p>
            <div className="flex gap-2">
              <select
                className="campo h-9 text-sm"
                value={escolhida}
                onChange={(e) => setEscolhida(e.target.value)}
                aria-label="Empresa"
              >
                <option value="">escolha a empresa…</option>
                {livres.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.nome}
                  </option>
                ))}
              </select>
              <button
                className="btn-secundario h-9 shrink-0"
                disabled={!escolhida || por.isPending}
                onClick={() => por.mutate(Number(escolhida))}
              >
                Pôr
              </button>
            </div>
          </div>

          {por.error ? <Erro>{mensagemDeErro(por.error)}</Erro> : null}
          {tirar.error ? <Erro>{mensagemDeErro(tirar.error)}</Erro> : null}
        </div>
      )}
    </Modal>
  )
}
