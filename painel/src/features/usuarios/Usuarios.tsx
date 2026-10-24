/**
 * Usuários — TODO MUNDO que entra no Gestão Solar, com a(s) empresa(s) de cada um.
 *
 * É o inverso de Empresas (pedido do dono, 23/10/2026): lá se entra na empresa e se vê
 * quem é dela; aqui se vê a pessoa e as empresas dela, sem travar ninguém numa empresa só —
 * um usuário pode estar em mais de uma. A equipe da plataforma (administrador e atendimento)
 * vem junto, marcada, com as telas que cada um abre.
 *
 * O adm não tem token: de cada pessoa, só se vê se ela tem o dela no meuWatt e no meuPlano.
 * Quem cola o token, libera o bot e concede usina é o gerente da empresa, no oem-gs.
 *
 * Três travas da equipe que o backend também aplica: ninguém remove o próprio acesso de
 * administrador, precisa sobrar ao menos um administrador ativo, e administrador abre todas
 * as telas por perfil — por isso as caixinhas dele aparecem marcadas e desligadas.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Check, ChevronDown, ChevronRight, KeyRound, ShieldCheck, UserPlus, Users } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Seletor, Vazio } from '@/components/base'
import {
  desagruparConta,
  contasParaAgrupar,
  agruparContas,
  catalogoDeAreas,
  criarUsuario,
  editarConta,
  editarUsuario,
  listarEmpresas,
  redefinirSenhaUsuario,
  todasAsContas,
  type Area,
  type Conta,
  type Membro,
} from '@/features/api'
import { PAPEL } from '@/features/rotulos'
import { EmpresasDaConta, ResumoDaConta, SenhaNova } from '@/features/usuarios/Conta'
import { mensagemDeErro } from '@/lib/api'

export function Usuarios() {
  const qc = useQueryClient()
  const [novo, setNovo] = useState(false)
  const [senhaDe, setSenhaDe] = useState<Conta | null>(null)
  const [empresasDe, setEmpresasDe] = useState<Conta | null>(null)
  const [agrupando, setAgrupando] = useState(false)
  const [erro, setErro] = useState('')
  const [busca, setBusca] = useState('')
  const [empresa, setEmpresa] = useState('')
  const [papel, setPapel] = useState('')

  const { data, isLoading, error } = useQuery({ queryKey: ['contas'], queryFn: todasAsContas })
  const { data: areas } = useQuery({ queryKey: ['areas'], queryFn: catalogoDeAreas })
  const { data: empresas } = useQuery({ queryKey: ['empresas'], queryFn: listarEmpresas })

  const editar = useMutation({
    mutationFn: ({ id, dados }: { id: number; dados: Parameters<typeof editarUsuario>[1] }) =>
      editarUsuario(id, dados),
    onSuccess: () => {
      setErro('')
      qc.invalidateQueries({ queryKey: ['contas'] })
      // O acesso de quem está com a tela aberta pode ser o que acabou de mudar: a casca
      // relê o próprio acesso e o menu acompanha, sem exigir sair e entrar.
      qc.invalidateQueries({ queryKey: ['eu'] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const filtradas = useMemo(() => {
    const t = busca.trim().toLowerCase()
    return (data ?? []).filter((c) => {
      if (t && !`${c.nome} ${c.apelido} ${c.email ?? ''}`.toLowerCase().includes(t)) return false
      if (papel && c.perfil !== papel) return false
      if (empresa === 'plataforma') return c.da_plataforma
      if (empresa === 'sem') return !c.da_plataforma && !c.empresas.length
      if (empresa) return c.empresas.some((e) => String(e.id) === empresa)
      return true
    })
  }, [data, busca, papel, empresa])

  const semEmpresa = (data ?? []).filter((c) => !c.da_plataforma && !c.empresas.length).length

  return (
    <Pagina
      titulo="Usuários"
      apoio="Todo mundo que entra no Gestão Solar, e de qual empresa é — uma pessoa pode estar em mais de uma. A equipe da plataforma aparece marcada. Para criar alguém de uma empresa, entre na empresa."
      acao={
        <div className="flex gap-2">
          <button onClick={() => setAgrupando(true)} className="btn-secundario">
            <Users size={15} />
            Mesma pessoa
          </button>
          <button onClick={() => setNovo(true)} className="btn-primario">
            <UserPlus size={16} />
            Novo da plataforma
          </button>
        </div>
      }
    >
      {erro ? <Erro className="mb-4">{erro}</Erro> : null}
      {semEmpresa ? (
        <div className="mb-4">
          <Aviso>
            {semEmpresa === 1 ? 'Uma conta está' : `${semEmpresa} contas estão`} sem empresa: nenhum
            gerente as enxerga e o aplicativo delas vem vazio. Use “Empresas” na linha para pôr
            numa empresa (filtre por “Sem empresa”).
          </Aviso>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3 mb-4">
        <input
          className="campo"
          placeholder="buscar por nome, apelido ou e-mail"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          aria-label="Buscar usuários"
        />
        <select className="campo" value={empresa} onChange={(e) => setEmpresa(e.target.value)} aria-label="Empresa">
          <option value="">Todas as empresas</option>
          <option value="plataforma">Plataforma (equipe)</option>
          <option value="sem">Sem empresa</option>
          {(empresas ?? []).map((e) => (
            <option key={e.id} value={e.id}>
              {e.nome}
            </option>
          ))}
        </select>
        <select className="campo" value={papel} onChange={(e) => setPapel(e.target.value)} aria-label="Papel">
          <option value="">Todos os papéis</option>
          {Object.entries(PAPEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>

      <Cartao>
        {isLoading ? <Carregando /> : null}
        {error ? (
          <div className="p-5">
            <Erro>{mensagemDeErro(error)}</Erro>
          </div>
        ) : null}
        {data && !filtradas.length ? (
          <Vazio titulo="Ninguém com esse filtro" descricao="Mude a empresa, o papel ou a busca." />
        ) : null}
        {filtradas.map((c, i) =>
          c.da_plataforma ? (
            <LinhaDaEquipe
              key={c.id}
              conta={c}
              areas={areas ?? []}
              primeiro={i === 0}
              salvando={editar.isPending}
              aoMudar={(dados) => editar.mutate({ id: c.id, dados })}
              aoRedefinirSenha={() => setSenhaDe(c)}
            />
          ) : (
            <LinhaDaConta key={c.id} conta={c} primeiro={i === 0} aoAbrirEmpresas={() => setEmpresasDe(c)} />
          ),
        )}
      </Cartao>

      {novo ? <ModalNovoUsuario areas={areas ?? []} aoFechar={() => setNovo(false)} /> : null}
      {senhaDe ? <ModalRedefinirSenha membro={senhaDe} aoFechar={() => setSenhaDe(null)} /> : null}
      {empresasDe ? <EmpresasDaConta conta={empresasDe} aoFechar={() => setEmpresasDe(null)} /> : null}
      {agrupando ? <MesmaPessoa aoFechar={() => setAgrupando(false)} /> : null}
    </Pagina>
  )
}

/** As empresas da conta numa linha: "Splendor O&M (origem) · Eninsa". */
function TextoDasEmpresas({ conta }: { conta: Conta }) {
  if (conta.da_plataforma) {
    return (
      <span className="flex items-center gap-1.5 text-ambar-texto">
        <ShieldCheck size={14} />
        Plataforma
      </span>
    )
  }
  if (!conta.empresas.length)
    return (
      <span className="text-alerta">
        sem empresa{conta.empresa_antiga ? ` (no cadastro antigo: ${conta.empresa_antiga})` : ''}
      </span>
    )
  return (
    <span className="flex items-center gap-1.5">
      <Building2 size={14} />
      {conta.empresas.map((e) => (e.origem && conta.empresas.length > 1 ? `${e.nome} (origem)` : e.nome)).join(' · ')}
    </span>
  )
}

/** Uma conta de EMPRESA (gerente, técnico, dono) — ou sem empresa ainda. */
function LinhaDaConta({
  conta,
  primeiro,
  aoAbrirEmpresas,
}: {
  conta: Conta
  primeiro: boolean
  aoAbrirEmpresas: () => void
}) {
  const qc = useQueryClient()
  const [senhaAberta, setSenhaAberta] = useState(false)
  const [pronto, setPronto] = useState<string | null>(null)
  const editar = useMutation({
    mutationFn: (dados: { ativo?: boolean; senha?: string }) => editarConta(conta.id, dados),
    onSuccess: (_r, dados) => {
      if (dados.senha) {
        setSenhaAberta(false)
        setPronto('Senha definida. Entregue-a junto com o apelido.')
      }
      qc.invalidateQueries({ queryKey: ['contas'] })
      qc.invalidateQueries({ queryKey: ['empresa-usuarios'] })
    },
  })

  return (
    <div className={`px-5 py-4 ${primeiro ? '' : 'border-t border-borda'}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="font-semibold text-forte">
            {conta.nome}
            <span className="mono text-xs text-fraco font-normal ml-2">{conta.apelido}</span>
            {conta.email ? <span className="text-xs text-fraco font-normal ml-2">{conta.email}</span> : null}
          </p>
          <div className="text-sm text-rotulo mt-1">
            <TextoDasEmpresas conta={conta} />
          </div>
          <ResumoDaConta conta={conta} />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Selo tom={conta.ativo ? 'ok' : 'sem-dados'}>{conta.ativo ? 'Ativo' : 'Inativo'}</Selo>
          <button className="btn-fantasma" onClick={aoAbrirEmpresas}>
            <Building2 size={13} />
            Empresas
          </button>
          {conta.perfil === 'cliente' ? (
            <Link to={`/clientes/${conta.id}`} className="btn-fantasma">
              Ficha
            </Link>
          ) : null}
          <button className="btn-fantasma" onClick={() => setSenhaAberta((v) => !v)}>
            <KeyRound size={13} />
            Senha
          </button>
          <button
            className="btn-fantasma"
            disabled={editar.isPending}
            onClick={() => editar.mutate({ ativo: !conta.ativo })}
          >
            {conta.ativo ? 'Desativar' : 'Reativar'}
          </button>
        </div>
      </div>
      {senhaAberta ? <SenhaNova ocupado={editar.isPending} aoDefinir={(senha) => editar.mutate({ senha })} /> : null}
      {pronto ? <p className="text-xs text-ok mt-2">{pronto}</p> : null}
      {editar.error ? <Erro className="mt-2">{mensagemDeErro(editar.error)}</Erro> : null}
    </div>
  )
}

/** Uma conta da EQUIPE da plataforma: perfil, telas que abre, senha e acesso. */
function LinhaDaEquipe({
  conta,
  areas,
  primeiro,
  salvando,
  aoMudar,
  aoRedefinirSenha,
}: {
  conta: Conta
  areas: Area[]
  primeiro: boolean
  salvando: boolean
  aoMudar: (dados: { perfil?: Membro['perfil']; ativo?: boolean; areas?: string[] }) => void
  aoRedefinirSenha: () => void
}) {
  const [aberto, setAberto] = useState(false)
  const ehAdmin = conta.perfil === 'administrador'

  return (
    <div className={primeiro ? '' : 'border-t border-borda'}>
      <div className="flex items-start justify-between gap-3 flex-wrap px-5 py-4">
        <div className="min-w-0">
          <p className="font-semibold text-forte">
            {conta.nome}
            <span className="mono text-xs text-fraco font-normal ml-2">{conta.apelido}</span>
            {conta.email ? <span className="text-xs text-fraco font-normal ml-2">{conta.email}</span> : null}
          </p>
          <div className="text-sm text-rotulo mt-1 flex items-center gap-4 flex-wrap">
            <TextoDasEmpresas conta={conta} />
            <span>{PAPEL[conta.perfil]}</span>
            <span>
              {conta.ultimo_login
                ? `entrou ${new Date(conta.ultimo_login).toLocaleDateString('pt-BR')}`
                : 'nunca entrou'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Selo tom={conta.ativo ? 'ok' : 'sem-dados'}>{conta.ativo ? 'Ativo' : 'Inativo'}</Selo>
          <select
            className="campo h-9 w-40 text-sm"
            value={conta.perfil}
            onChange={(e) => aoMudar({ perfil: e.target.value as Membro['perfil'] })}
            aria-label={`Perfil de ${conta.nome}`}
          >
            <option value="atendimento">Atendimento</option>
            <option value="administrador">Administrador</option>
          </select>
          <button onClick={aoRedefinirSenha} className="btn-fantasma" title={`Definir uma senha nova para ${conta.nome}`}>
            <KeyRound size={13} />
            Senha
          </button>
          <button onClick={() => aoMudar({ ativo: !conta.ativo })} className="btn-fantasma">
            {conta.ativo ? 'Desativar' : 'Reativar'}
          </button>
        </div>
      </div>

      <div className="px-5 pb-3 -mt-2">
        <button
          onClick={() => setAberto((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-rotulo hover:text-forte"
        >
          {aberto ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          {ehAdmin ? 'Telas: todas, por ser administrador' : `Telas: ${conta.areas.length} de ${areas.length}`}
        </button>
        {aberto ? (
          <PainelDeAreas membro={conta} areas={areas} salvando={salvando} aoSalvar={(chaves) => aoMudar({ areas: chaves })} />
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
  membro: { perfil: string; areas: string[] }
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
      qc.invalidateQueries({ queryKey: ['contas'] })
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
function ModalRedefinirSenha({
  membro,
  aoFechar,
}: {
  membro: Pick<Membro, 'id' | 'nome' | 'apelido'>
  aoFechar: () => void
}) {
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


/**
 * Quais contas são do mesmo humano.
 *
 * Uma conta é um PAPEL: quem administra a plataforma também pode ser gerente de uma
 * empresa e dono de uma usina, e hoje isso são três contas. Agrupá-las não funde poder
 * nenhum — cada sessão continua valendo para um portão só. O que muda é que a pessoa
 * troca de papel sem sair e entrar de novo.
 *
 * **Por que só administrador:** agrupar é abrir um caminho de troca entre contas. Quem
 * pudesse fazê-lo juntaria a própria conta à de alguém com mais poder — e a subida ainda
 * pede senha, mas a porta não deveria nem existir.
 */
function MesmaPessoa({ aoFechar }: { aoFechar: () => void }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['contas-para-agrupar'],
    queryFn: contasParaAgrupar,
  })
  const [nome, setNome] = useState('')
  const [marcados, setMarcados] = useState<string[]>([])

  const agrupar = useMutation({
    mutationFn: () => agruparContas({ nome, apelidos: marcados }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contas-para-agrupar'] })
      qc.invalidateQueries({ queryKey: ['papeis'] })
      aoFechar()
    },
  })

  const desagrupar = useMutation({
    mutationFn: (apelido: string) => desagruparConta(apelido),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contas-para-agrupar'] })
      qc.invalidateQueries({ queryKey: ['papeis'] })
    },
  })

  const PAPEL: Record<string, string> = {
    administrador: 'Plataforma · administrador',
    atendimento: 'Plataforma · atendimento',
    gestor_empresa: 'Gerente da empresa',
    cliente: 'Dono de usina',
  }

  return (
    <Modal titulo="Contas da mesma pessoa" aoFechar={aoFechar} largura="max-w-2xl">
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : (
        <div className="grid gap-4">
          <Aviso>
            Agrupar não junta poderes: cada sessão continua valendo para um portão só. O que
            muda é poder trocar de papel sem sair e entrar de novo — e entrar como gestor da
            plataforma continua pedindo a senha daquela conta.
          </Aviso>

          <Campo
            rotulo="Nome da pessoa"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="Renan Marquezini"
            nota="Só para identificar o grupo. O nome que aparece em cada tela continua sendo o da conta."
          />

          <div>
            <p className="rotulo-campo">Contas</p>
            <ul className="mt-2 grid gap-1 max-h-72 overflow-y-auto pr-1">
              {(data ?? []).map((c) => (
                <li key={c.apelido}>
                  <label className="flex items-center gap-2.5 px-3 py-2 rounded-campo hover:bg-superficie cursor-pointer">
                    <input
                      type="checkbox"
                      checked={marcados.includes(c.apelido)}
                      onChange={() =>
                        setMarcados((m) =>
                          m.includes(c.apelido)
                            ? m.filter((x) => x !== c.apelido)
                            : [...m, c.apelido],
                        )
                      }
                    />
                    <span className="text-sm text-forte">{c.apelido}</span>
                    <span className="text-xs text-fraco">
                      {PAPEL[c.perfil] ?? c.perfil}
                      {c.empresa ? ` · ${c.empresa}` : ''}
                    </span>
                    {c.pessoa_nome ? (
                      <span className="text-xs text-rotulo ml-auto flex items-center gap-2">
                        {c.pessoa_nome}
                        <button
                          type="button"
                          className="btn-fantasma"
                          onClick={(e) => {
                            e.preventDefault()
                            desagrupar.mutate(c.apelido)
                          }}
                        >
                          tirar
                        </button>
                      </span>
                    ) : null}
                  </label>
                </li>
              ))}
            </ul>
          </div>

          {agrupar.error ? <Erro>{mensagemDeErro(agrupar.error)}</Erro> : null}
          {desagrupar.error ? <Erro>{mensagemDeErro(desagrupar.error)}</Erro> : null}

          <div className="flex justify-end gap-2">
            <button className="btn-secundario" onClick={aoFechar}>
              Fechar
            </button>
            <button
              className="btn-primario"
              onClick={() => agrupar.mutate()}
              disabled={marcados.length < 2 || !nome.trim() || agrupar.isPending}
            >
              {agrupar.isPending ? 'Agrupando…' : 'Agrupar'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
