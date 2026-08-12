/**
 * Quem opera o painel.
 *
 * Duas travas que o backend também aplica, repetidas aqui para o gestor entender antes de
 * tentar: ninguém remove o próprio acesso de administrador, e precisa sobrar ao menos um
 * administrador ativo — senão o painel tranca para todo mundo e só o script de linha de
 * comando destrava.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserPlus } from 'lucide-react'
import { useState } from 'react'

import { Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Seletor } from '@/components/base'
import { criarMembro, editarMembro, listarEquipe, type Membro } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Equipe() {
  const qc = useQueryClient()
  const [novo, setNovo] = useState(false)
  const [erro, setErro] = useState('')

  const { data, isLoading } = useQuery({ queryKey: ['equipe'], queryFn: listarEquipe })

  const editar = useMutation({
    mutationFn: ({ id, dados }: { id: number; dados: Parameters<typeof editarMembro>[1] }) =>
      editarMembro(id, dados),
    onSuccess: () => {
      setErro('')
      qc.invalidateQueries({ queryKey: ['equipe'] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Pagina
      titulo="Equipe"
      apoio="Quem abre o painel. Atendimento cuida de clientes e diagnóstico; administrador também mexe nas conexões e na equipe."
      acao={
        <button onClick={() => setNovo(true)} className="btn-primario">
          <UserPlus size={16} />
          Novo membro
        </button>
      }
    >
      {erro ? <Erro className="mb-4">{erro}</Erro> : null}

      <Cartao>
        {isLoading ? <Carregando /> : null}
        {(data ?? []).map((m, i) => (
          <LinhaMembro
            key={m.id}
            membro={m}
            primeiro={i === 0}
            aoMudar={(dados) => editar.mutate({ id: m.id, dados })}
          />
        ))}
      </Cartao>

      {novo ? <ModalNovoMembro aoFechar={() => setNovo(false)} /> : null}
    </Pagina>
  )
}

function LinhaMembro({
  membro,
  primeiro,
  aoMudar,
}: {
  membro: Membro
  primeiro: boolean
  aoMudar: (dados: { perfil?: Membro['perfil']; ativo?: boolean }) => void
}) {
  return (
    <div className={`flex items-center gap-4 px-5 py-4 ${primeiro ? '' : 'border-t border-borda'}`}>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-forte truncate">{membro.nome}</p>
        <p className="mono text-xs text-fraco truncate">{membro.email}</p>
      </div>

      {membro.ultimo_login ? (
        <span className="mono text-xs text-fraco hidden sm:block">
          entrou {new Date(membro.ultimo_login).toLocaleDateString('pt-BR')}
        </span>
      ) : (
        <span className="text-xs text-fraco hidden sm:block">nunca entrou</span>
      )}

      <select
        className="campo h-9 w-40 text-sm"
        value={membro.perfil}
        onChange={(e) => aoMudar({ perfil: e.target.value as Membro['perfil'] })}
        aria-label={`Perfil de ${membro.nome}`}
      >
        <option value="atendimento">Atendimento</option>
        <option value="administrador">Administrador</option>
      </select>

      <button
        onClick={() => aoMudar({ ativo: !membro.ativo })}
        className="btn-fantasma w-24"
        title={membro.ativo ? 'Desativar o acesso' : 'Reativar o acesso'}
      >
        {membro.ativo ? 'Desativar' : 'Reativar'}
      </button>

      {membro.ativo ? <Selo tom="ok">Ativo</Selo> : <Selo tom="sem-dados">Inativo</Selo>}
    </div>
  )
}

function ModalNovoMembro({ aoFechar }: { aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [perfil, setPerfil] = useState<Membro['perfil']>('atendimento')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState('')

  const criar = useMutation({
    mutationFn: () => criarMembro({ nome, email, perfil, senha }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['equipe'] })
      aoFechar()
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Modal titulo="Novo membro" aoFechar={aoFechar}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setErro('')
          criar.mutate()
        }}
        className="flex flex-col gap-4"
      >
        {erro ? <Erro>{erro}</Erro> : null}

        <Campo rotulo="Nome" value={nome} onChange={(e) => setNome(e.target.value)} required autoFocus />
        <Campo
          rotulo="E-mail"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <Seletor
          rotulo="Perfil"
          value={perfil}
          onChange={(e) => setPerfil(e.target.value as Membro['perfil'])}
        >
          <option value="atendimento">Atendimento — clientes e diagnóstico</option>
          <option value="administrador">Administrador — tudo, inclusive conexões</option>
        </Seletor>
        <Campo
          rotulo="Senha"
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          nota="Mínimo de 8 caracteres. Combine com a pessoa e peça para trocar depois."
          minLength={8}
          required
        />

        <div className="flex gap-2">
          <button type="submit" className="btn-primario" disabled={criar.isPending}>
            {criar.isPending ? 'Criando…' : 'Criar membro'}
          </button>
          <button type="button" onClick={aoFechar} className="btn-secundario">
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  )
}
