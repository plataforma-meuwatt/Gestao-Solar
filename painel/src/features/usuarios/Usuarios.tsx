/**
 * Usuários do sistema — o staff, e o que cada um abre.
 *
 * Não confundir com Clientes: aqui estão as contas que entram NO PAINEL. Cliente entra no
 * aplicativo e no portal, e mora na outra tela.
 *
 * Três travas que o backend também aplica, repetidas aqui para a pessoa entender antes de
 * tentar: ninguém remove o próprio acesso de administrador, precisa sobrar ao menos um
 * administrador ativo, e administrador abre todas as telas por perfil — por isso as
 * caixinhas dele aparecem marcadas e desligadas, em vez de fingir que dá para desmarcar.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, KeyRound, UserPlus } from 'lucide-react'
import { useState } from 'react'

import { Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Seletor } from '@/components/base'
import { Conexoes } from '@/features/conexoes/Conexoes'
import {
  catalogoDeAreas,
  criarUsuario,
  editarUsuario,
  listarUsuarios,
  redefinirSenhaUsuario,
  type Area,
  type Membro,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Usuarios() {
  const qc = useQueryClient()
  const [novo, setNovo] = useState(false)
  const [senhaDe, setSenhaDe] = useState<Membro | null>(null)
  const [erro, setErro] = useState('')

  const { data, isLoading } = useQuery({ queryKey: ['usuarios'], queryFn: listarUsuarios })
  const { data: areas } = useQuery({ queryKey: ['areas'], queryFn: catalogoDeAreas })

  const editar = useMutation({
    mutationFn: ({ id, dados }: { id: number; dados: Parameters<typeof editarUsuario>[1] }) =>
      editarUsuario(id, dados),
    onSuccess: () => {
      setErro('')
      qc.invalidateQueries({ queryKey: ['usuarios'] })
      // O acesso de quem está com a tela aberta pode ser o que acabou de mudar: a casca
      // relê o próprio acesso e o menu acompanha, sem exigir sair e entrar.
      qc.invalidateQueries({ queryKey: ['eu'] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Pagina
      titulo="Usuários do sistema"
      apoio="Quem entra no painel, e o que cada um abre. Administrador abre todas as telas e é o único que mexe nesta lista; as demais contas abrem só o que estiver marcado."
      acao={
        <button onClick={() => setNovo(true)} className="btn-primario">
          <UserPlus size={16} />
          Novo usuário
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
            areas={areas ?? []}
            primeiro={i === 0}
            salvando={editar.isPending}
            aoMudar={(dados) => editar.mutate({ id: m.id, dados })}
            aoRedefinirSenha={() => setSenhaDe(m)}
          />
        ))}
      </Cartao>

      <Conexoes embutido />

      {novo ? <ModalNovoUsuario areas={areas ?? []} aoFechar={() => setNovo(false)} /> : null}
      {senhaDe ? <ModalRedefinirSenha membro={senhaDe} aoFechar={() => setSenhaDe(null)} /> : null}
    </Pagina>
  )
}

function LinhaMembro({
  membro,
  areas,
  primeiro,
  salvando,
  aoMudar,
  aoRedefinirSenha,
}: {
  membro: Membro
  areas: Area[]
  primeiro: boolean
  salvando: boolean
  aoMudar: (dados: { perfil?: Membro['perfil']; ativo?: boolean; areas?: string[] }) => void
  aoRedefinirSenha: () => void
}) {
  const [aberto, setAberto] = useState(false)
  const ehAdmin = membro.perfil === 'administrador'

  return (
    <div className={primeiro ? '' : 'border-t border-borda'}>
      <div className="flex items-center gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-forte truncate">{membro.nome}</p>
          <p className="mono text-xs text-fraco truncate">
            {/* O apelido primeiro: é ele que a pessoa digita para entrar, e é por ele que
                se confere de quem é a conta quando dois membros têm nomes parecidos. */}
            {membro.apelido}
            {membro.email ? ` · ${membro.email}` : ''}
          </p>
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
          onClick={aoRedefinirSenha}
          className="btn-fantasma"
          title={`Definir uma senha nova para ${membro.nome}`}
        >
          <KeyRound size={13} />
          Redefinir senha
        </button>

        <button
          onClick={() => aoMudar({ ativo: !membro.ativo })}
          className="btn-fantasma w-24"
          title={membro.ativo ? 'Desativar o acesso' : 'Reativar o acesso'}
        >
          {membro.ativo ? 'Desativar' : 'Reativar'}
        </button>

        {membro.ativo ? <Selo tom="ok">Ativo</Selo> : <Selo tom="sem-dados">Inativo</Selo>}
      </div>

      <div className="px-5 pb-3 -mt-1">
        <button
          onClick={() => setAberto((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-rotulo hover:text-forte"
        >
          {aberto ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          {ehAdmin
            ? 'Telas: todas, por ser administrador'
            : `Telas: ${membro.areas.length} de ${areas.length}`}
        </button>

        {aberto ? (
          <PainelDeAreas
            membro={membro}
            areas={areas}
            salvando={salvando}
            aoSalvar={(chaves) => aoMudar({ areas: chaves })}
          />
        ) : null}
      </div>
    </div>
  )
}

/**
 * As caixinhas de um membro, agrupadas como o menu.
 *
 * Salva por botão, e não a cada clique: marcar quatro telas dispararia quatro gravações,
 * e a terceira chegando depois da quarta deixaria o acesso diferente do que está na tela.
 */
function PainelDeAreas({
  membro,
  areas,
  salvando,
  aoSalvar,
}: {
  membro: Membro
  areas: Area[]
  salvando: boolean
  aoSalvar: (chaves: string[]) => void
}) {
  const ehAdmin = membro.perfil === 'administrador'
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set(membro.areas))

  const grupos = [...new Set(areas.map((a) => a.grupo))]
  const mudou =
    marcadas.size !== membro.areas.length || membro.areas.some((a) => !marcadas.has(a))

  function alternar(chave: string) {
    setMarcadas((atual) => {
      const proxima = new Set(atual)
      if (proxima.has(chave)) proxima.delete(chave)
      else proxima.add(chave)
      return proxima
    })
  }

  return (
    <div className="mt-2.5 rounded-campo bg-superficie p-4">
      {ehAdmin ? (
        <p className="text-xs text-rotulo mb-3">
          Administrador abre todas as telas pelo perfil — inclusive esta. Para limitar o que
          esta pessoa vê, mude o perfil para Atendimento e marque as telas abaixo.
        </p>
      ) : null}

      {grupos.map((grupo) => (
        <div key={grupo} className="mb-3 last:mb-0">
          <p className="text-[10px] font-bold uppercase tracking-wider text-fraco/60 mb-1.5">
            {grupo}
          </p>
          <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {areas
              .filter((a) => a.grupo === grupo)
              .map((a) => (
                <label key={a.chave} className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={ehAdmin || marcadas.has(a.chave)}
                    disabled={ehAdmin}
                    onChange={() => alternar(a.chave)}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm text-corpo">{a.rotulo}</span>
                    <span className="block text-xs text-fraco">{a.descricao}</span>
                  </span>
                </label>
              ))}
          </div>
        </div>
      ))}

      {!ehAdmin ? (
        <div className="flex items-center gap-2 mt-3">
          <button
            onClick={() => aoSalvar([...marcadas])}
            className="btn-primario"
            disabled={!mudou || salvando}
          >
            {salvando ? 'Salvando…' : 'Salvar telas'}
          </button>
          {mudou ? (
            <button onClick={() => setMarcadas(new Set(membro.areas))} className="btn-secundario">
              Desfazer
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function ModalNovoUsuario({ areas, aoFechar }: { areas: Area[]; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [apelido, setApelido] = useState('')
  const [email, setEmail] = useState('')
  const [perfil, setPerfil] = useState<Membro['perfil']>('atendimento')
  const [senha, setSenha] = useState('')
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set())
  const [erro, setErro] = useState('')

  const criar = useMutation({
    mutationFn: () =>
      criarUsuario({
        nome,
        apelido,
        email: email || null,
        perfil,
        senha,
        areas: perfil === 'administrador' ? [] : [...marcadas],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['usuarios'] })
      aoFechar()
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Modal titulo="Novo usuário do sistema" aoFechar={aoFechar}>
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
          rotulo="Apelido"
          value={apelido}
          onChange={(e) => setApelido(e.target.value.toLowerCase())}
          placeholder="joao.silva"
          nota="É com ele que a pessoa entra no painel."
          autoCapitalize="none"
          spellCheck={false}
          minLength={3}
          required
        />
        <Campo
          rotulo="E-mail"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          nota="Opcional — serve para alcançar a pessoa, não para entrar."
        />
        <Seletor
          rotulo="Perfil"
          value={perfil}
          onChange={(e) => setPerfil(e.target.value as Membro['perfil'])}
        >
          <option value="atendimento">Atendimento — abre só as telas marcadas</option>
          <option value="administrador">Administrador — abre tudo, inclusive esta tela</option>
        </Seletor>

        {perfil === 'atendimento' ? (
          <div>
            <p className="text-sm text-rotulo mb-2">
              Telas que esta pessoa abre. Sem nenhuma marcada, ela entra no painel e lê que
              falta acesso — o que é honesto, e você concede depois aqui mesmo.
            </p>
            <div className="rounded-campo bg-superficie p-3 grid gap-2">
              {areas.map((a) => (
                <label key={a.chave} className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={marcadas.has(a.chave)}
                    onChange={() =>
                      setMarcadas((atual) => {
                        const proxima = new Set(atual)
                        if (proxima.has(a.chave)) proxima.delete(a.chave)
                        else proxima.add(a.chave)
                        return proxima
                      })
                    }
                  />
                  <span className="min-w-0">
                    <span className="block text-sm text-corpo">
                      {a.rotulo} <span className="text-xs text-fraco">· {a.grupo}</span>
                    </span>
                    <span className="block text-xs text-fraco">{a.descricao}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        ) : null}

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
            {criar.isPending ? 'Criando…' : 'Criar usuário'}
          </button>
          <button type="button" onClick={aoFechar} className="btn-secundario">
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  )
}

/**
 * O administrador define a senha nova, como definiu a primeira no cadastro.
 *
 * Não reaproveita a senha provisória dos clientes: o painel não tem tela de troca para o
 * staff, e uma senha sorteada ficaria sendo a senha da pessoa para sempre.
 */
function ModalRedefinirSenha({ membro, aoFechar }: { membro: Membro; aoFechar: () => void }) {
  const [senha, setSenha] = useState('')
  const [confirmacao, setConfirmacao] = useState('')
  const [erro, setErro] = useState('')

  const redefinir = useMutation({
    mutationFn: () => redefinirSenhaUsuario(membro.id, senha),
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  if (redefinir.isSuccess) {
    return (
      <Modal titulo="Senha redefinida" aoFechar={aoFechar}>
        <p className="flex items-start gap-2 text-sm text-ok">
          <Check size={15} className="shrink-0 mt-0.5" />
          <span>
            A senha de <strong>{membro.nome}</strong> foi trocada. A anterior já não entra.
          </span>
        </p>
        <p className="text-sm text-rotulo mt-3">
          Passe a senha nova para a pessoa junto com o apelido{' '}
          <span className="mono text-forte">{membro.apelido}</span>. Sessões já abertas
          continuam valendo até expirar; para tirar alguém de dentro agora, desative a conta.
        </p>
        <button onClick={aoFechar} className="btn-secundario w-full mt-4">
          Fechar
        </button>
      </Modal>
    )
  }

  return (
    <Modal titulo={`Redefinir senha de ${membro.nome}`} aoFechar={aoFechar}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (senha !== confirmacao) {
            setErro('As senhas não conferem.')
            return
          }
          setErro('')
          redefinir.mutate()
        }}
        className="flex flex-col gap-4"
      >
        {erro ? <Erro>{erro}</Erro> : null}

        <p className="text-sm text-rotulo">
          A senha atual de <span className="mono text-forte">{membro.apelido}</span> deixa de
          funcionar assim que você salvar.
        </p>

        <Campo
          rotulo="Senha nova"
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          nota="Mínimo de 8 caracteres. Combine com a pessoa."
          autoComplete="new-password"
          minLength={8}
          required
          autoFocus
        />
        <Campo
          rotulo="Confirme a senha"
          type="password"
          value={confirmacao}
          onChange={(e) => setConfirmacao(e.target.value)}
          autoComplete="new-password"
          minLength={8}
          required
        />

        <div className="flex gap-2">
          <button type="submit" className="btn-primario" disabled={redefinir.isPending}>
            {redefinir.isPending ? 'Salvando…' : 'Redefinir senha'}
          </button>
          <button type="button" onClick={aoFechar} className="btn-secundario">
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  )
}
