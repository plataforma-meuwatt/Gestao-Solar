/**
 * Uma empresa de O&M por dentro — o que a plataforma vê ao ENTRAR na empresa.
 *
 * Os usuários dela (gerentes, técnicos e donos de usina, inclusive quem é dela e de outra),
 * as usinas dela e as últimas mensagens do bot das pessoas dela. A plataforma cadastra e
 * cuida das contas (criar, papel, senha, ativar, pôr e tirar da empresa); o dia a dia da
 * empresa — conceder usina, colar o token de cada pessoa, liberar o bot — é do gerente, no
 * oem-gs. O adm não tem token: daqui só se vê se a pessoa tem o dela.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Pencil, Power, UserPlus, Users } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio } from '@/components/base'
import {
  criarUsuarioDaEmpresa,
  editarEmpresa,
  editarUsuarioDaEmpresa,
  logDoBot,
  obterEmpresa,
  porUsuarioNaEmpresa,
  tirarUsuarioDaEmpresa,
  todasAsContas,
  usinasDaPlataforma,
  usuariosDaEmpresaAdmin,
  type Empresa,
  type PapelNaEmpresa,
  type UsuarioDaEmpresaAdmin,
} from '@/features/api'
import { estadoDaConexao } from '@/features/empresas/Empresas'
import { LinhaDoLog } from '@/features/bot/LogDoBot'
import { PAPEL, confirmaAtivacao } from '@/features/rotulos'
import { ResumoDaConta, SenhaNova } from '@/features/usuarios/Conta'
import { mensagemDeErro } from '@/lib/api'

export function EmpresaPagina() {
  const { id } = useParams<{ id: string }>()
  const empresaId = Number(id)
  const qc = useQueryClient()
  const { data: empresa, isLoading, error } = useQuery({
    queryKey: ['empresa', empresaId],
    queryFn: () => obterEmpresa(empresaId),
  })
  const [editando, setEditando] = useState(false)

  const alternar = useMutation({
    mutationFn: () => editarEmpresa(empresaId, { ativa: !empresa?.ativa }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresa', empresaId] })
      qc.invalidateQueries({ queryKey: ['empresas'] })
    },
  })

  if (isLoading) return <Carregando />
  if (error || !empresa) return <Erro>{error ? mensagemDeErro(error) : 'Empresa não encontrada.'}</Erro>

  return (
    <Pagina
      titulo={empresa.nome}
      apoio={`${empresa.documento ?? 'sem CNPJ cadastrado'} · meuWatt: ${estadoDaConexao(empresa.conexao_meuwatt)} · meuPlano: ${estadoDaConexao(empresa.conexao_meuplano)}`}
      acao={
        <div className="flex gap-2">
          <button className="btn-secundario" onClick={() => setEditando(true)}>
            <Pencil size={14} />
            Editar
          </button>
          <button
            className="btn-secundario"
            onClick={() => {
              if (
                !empresa.ativa ||
                window.confirm(
                  `Desligar ${empresa.nome}? O gerente e os usuários dela param de entrar na hora; usinas, contas e histórico ficam guardados.`,
                )
              )
                alternar.mutate()
            }}
            disabled={alternar.isPending}
          >
            <Power size={14} />
            {empresa.ativa ? 'Desligar' : 'Religar'}
          </button>
        </div>
      }
    >
      <Link
        to="/empresas"
        className="inline-flex items-center gap-1.5 text-sm text-rotulo hover:text-forte mb-5"
      >
        <ArrowLeft size={14} />
        Todas as empresas
      </Link>

      {!empresa.ativa ? (
        <div className="mb-4">
          <Aviso>
            Empresa desligada: ninguém dela entra (gerente, técnico nem dono de usina). Usinas,
            contas e histórico continuam guardados.
          </Aviso>
        </div>
      ) : null}
      {alternar.error ? <Erro className="mb-4">{mensagemDeErro(alternar.error)}</Erro> : null}

      <div className="grid gap-5">
        <UsuariosDaEmpresa empresa={empresa} />
        <UsinasDaEmpresa empresa={empresa} />
        <BotDaEmpresa empresa={empresa} />
      </div>

      {editando ? <EditarEmpresa empresa={empresa} aoFechar={() => setEditando(false)} /> : null}
    </Pagina>
  )
}

/* ---------------------------------------------------------------- usuários */

function UsuariosDaEmpresa({ empresa }: { empresa: Empresa }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['empresa-usuarios', empresa.id],
    queryFn: () => usuariosDaEmpresaAdmin(empresa.id),
  })
  const [novo, setNovo] = useState(false)
  const [existente, setExistente] = useState(false)

  return (
    <Cartao
      titulo={`Usuários · ${data?.length ?? '…'}`}
      acao={
        <div className="flex flex-wrap gap-2">
          <button className="btn-fantasma" onClick={() => setExistente(true)}>
            <Users size={13} />
            Pôr quem já existe
          </button>
          <button className="btn-fantasma" onClick={() => setNovo(true)}>
            <UserPlus size={13} />
            Novo usuário
          </button>
        </div>
      }
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <div className="px-5 pb-5">
          <Erro>{mensagemDeErro(error)}</Erro>
        </div>
      ) : !data?.length ? (
        <Vazio
          titulo="Ninguém nesta empresa ainda"
          descricao="Crie o gerente dela em “Novo usuário”: é quem cadastra os técnicos e os donos de usina, cola o token de cada um e libera o bot."
        />
      ) : (
        data.map((u, i) => <LinhaDoUsuario key={u.id} empresa={empresa} usuario={u} primeiro={i === 0} />)
      )}

      {novo ? <NovoUsuario empresa={empresa} aoFechar={() => setNovo(false)} /> : null}
      {existente ? <PorQuemJaExiste empresa={empresa} jaDela={data ?? []} aoFechar={() => setExistente(false)} /> : null}
    </Cartao>
  )
}

function LinhaDoUsuario({
  empresa,
  usuario,
  primeiro,
}: {
  empresa: Empresa
  usuario: UsuarioDaEmpresaAdmin
  primeiro: boolean
}) {
  const qc = useQueryClient()
  const [senhaAberta, setSenhaAberta] = useState(false)
  const [pronto, setPronto] = useState<string | null>(null)
  const atualizar = () => {
    qc.invalidateQueries({ queryKey: ['empresa-usuarios', empresa.id] })
    qc.invalidateQueries({ queryKey: ['empresa', empresa.id] })
    qc.invalidateQueries({ queryKey: ['empresas'] })
    qc.invalidateQueries({ queryKey: ['contas'] })
  }

  const editar = useMutation({
    mutationFn: (dados: { ativo?: boolean; senha?: string; perfil?: PapelNaEmpresa }) =>
      editarUsuarioDaEmpresa(empresa.id, usuario.id, dados),
    onSuccess: (_r, dados) => {
      if (dados.senha) {
        setSenhaAberta(false)
        setPronto('Senha definida. Entregue-a junto com o apelido.')
      }
      atualizar()
    },
  })
  const tirar = useMutation({
    mutationFn: () => tirarUsuarioDaEmpresa(empresa.id, usuario.id),
    onSuccess: atualizar,
  })

  // Quem é de OUTRA empresa e também desta: a conta é cuidada por lá.
  const daqui = usuario.cuidada_por === null

  return (
    <div className={`px-5 py-4 ${primeiro ? '' : 'border-t border-borda'}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="text-forte font-semibold">
            {usuario.nome}
            <span className="mono text-xs text-fraco font-normal ml-2">{usuario.apelido}</span>
            {usuario.minha ? <span className="text-xs text-ok font-normal ml-2">é você</span> : null}
          </p>
          <ResumoDaConta conta={usuario} />
          {!daqui ? (
            <p className="text-xs text-alerta mt-1.5">
              Também é de {usuario.cuidada_por}, que cuida da conta (senha, celular, tokens e bot).
              Aqui ela recebe só o que esta empresa der
              {usuario.perfil === 'cliente'
                ? '. No aplicativo, as usinas daqui só trazem dado com o token próprio da pessoa.'
                : '.'}
            </p>
          ) : usuario.outras_empresas.length ? (
            <p className="text-xs text-rotulo mt-1.5">
              Também em: {usuario.outras_empresas.join(', ')}
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Selo tom={usuario.ativo ? 'ok' : 'sem-dados'}>{usuario.ativo ? 'Ativo' : 'Inativo'}</Selo>
          {daqui ? (
            <select
              className="campo h-9 w-44 text-xs"
              value={usuario.perfil}
              onChange={(e) => {
                const novo = e.target.value as PapelNaEmpresa
                if (window.confirm(`Mudar ${usuario.nome} para “${PAPEL[novo]}”? Muda o que a pessoa abre na hora.`))
                  editar.mutate({ perfil: novo })
              }}
              aria-label={`Papel de ${usuario.nome}`}
            >
              <option value="gestor_empresa">{PAPEL.gestor_empresa}</option>
              <option value="tecnico">{PAPEL.tecnico}</option>
              <option value="cliente">{PAPEL.cliente}</option>
            </select>
          ) : null}
          {usuario.perfil === 'cliente' ? (
            <Link to={`/clientes/${usuario.id}`} className="btn-fantasma">
              Ficha
            </Link>
          ) : null}
          <button className="btn-fantasma" onClick={() => setSenhaAberta((v) => !v)}>
            Senha
          </button>
          <button
            className="btn-fantasma"
            disabled={editar.isPending}
            onClick={() => confirmaAtivacao(usuario.nome, usuario.ativo) && editar.mutate({ ativo: !usuario.ativo })}
          >
            {usuario.ativo ? 'Desativar' : 'Reativar'}
          </button>
          <button
            className="btn-fantasma"
            disabled={tirar.isPending}
            onClick={() => {
              if (
                window.confirm(
                  `Tirar ${usuario.nome} de ${empresa.nome}? A conta continua existindo; as usinas que essa conta recebe desta empresa saem junto.` +
                    (usuario.outras_empresas.length || usuario.cuidada_por
                      ? ''
                      : ' Esta é a ÚNICA empresa da pessoa: ela fica sem empresa: nenhum gerente a enxerga e o aplicativo dela fica vazio até alguém a pôr em outra.'),
                )
              )
                tirar.mutate()
            }}
          >
            Tirar da empresa
          </button>
        </div>
      </div>

      {senhaAberta ? (
        <SenhaNova ocupado={editar.isPending} aoDefinir={(senha) => editar.mutate({ senha })} />
      ) : null}
      {pronto ? <p className="text-xs text-ok mt-2">{pronto}</p> : null}
      {editar.error ? <Erro className="mt-2">{mensagemDeErro(editar.error)}</Erro> : null}
      {tirar.error ? <Erro className="mt-2">{mensagemDeErro(tirar.error)}</Erro> : null}
    </div>
  )
}

/** Usuário novo DENTRO da empresa: gerente, técnico ou dono de usina. A senha provisória
 *  aparece uma vez e é entregue com o APELIDO, que é o que autentica. */
function NovoUsuario({ empresa, aoFechar }: { empresa: Empresa; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [perfil, setPerfil] = useState<PapelNaEmpresa>(empresa.gerentes ? 'cliente' : 'gestor_empresa')
  const [nome, setNome] = useState('')
  const [apelido, setApelido] = useState('')
  const [email, setEmail] = useState('')
  const [criado, setCriado] = useState<{ apelido: string; senha: string } | null>(null)

  const criar = useMutation({
    mutationFn: () => criarUsuarioDaEmpresa(empresa.id, { nome, apelido, email: email || null, perfil }),
    onSuccess: (r) => {
      setCriado({ apelido: r.apelido, senha: r.senha })
      qc.invalidateQueries({ queryKey: ['empresa-usuarios', empresa.id] })
      qc.invalidateQueries({ queryKey: ['empresa', empresa.id] })
      qc.invalidateQueries({ queryKey: ['empresas'] })
      qc.invalidateQueries({ queryKey: ['contas'] })
    },
  })

  function aoDigitarNome(valor: string) {
    const anterior = sugerir(nome)
    setNome(valor)
    if (!apelido || apelido === anterior) setApelido(sugerir(valor))
  }

  if (criado) {
    return (
      <Modal titulo="Usuário criado" aoFechar={aoFechar}>
        <div className="grid gap-4">
          <Aviso>Anote agora: a senha não é guardada em texto e não dá para vê-la de novo.</Aviso>
          <Cartao className="p-4">
            <p className="text-sm text-rotulo">Entra com o apelido</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.apelido}</p>
            <p className="text-sm text-rotulo mt-4">Senha provisória</p>
            <p className="text-forte font-semibold text-lg mt-1 mono">{criado.senha}</p>
          </Cartao>
          <div className="flex justify-end">
            <button className="btn-primario" onClick={aoFechar}>
              Fechar
            </button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal titulo={`Novo usuário · ${empresa.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-4">
        <div>
          <p className="rotulo-campo">Papel na empresa</p>
          <select
            className="campo"
            value={perfil}
            onChange={(e) => setPerfil(e.target.value as PapelNaEmpresa)}
            aria-label="Papel na empresa"
          >
            <option value="gestor_empresa">Gerente: opera a empresa no oem-gs</option>
            <option value="tecnico">Técnico: usa o bot (geração, manutenção e helper) nas usinas da empresa e conecta o próprio WhatsApp</option>
            <option value="cliente">Dono de usina: entra no aplicativo</option>
          </select>
        </div>
        <Campo rotulo="Nome" value={nome} onChange={(e) => aoDigitarNome(e.target.value)} placeholder="Maria Silva" />
        <Campo
          rotulo="Apelido (é com ele que entra)"
          value={apelido}
          onChange={(e) => setApelido(e.target.value)}
          placeholder="maria.silva"
        />
        <Campo
          rotulo="E-mail (opcional)"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          nota="Contato apenas. Quem autentica é o apelido."
        />
        {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}
        {!nome.trim() || !apelido.trim() ? (
          <p className="text-xs text-rotulo">Preencha nome e apelido. O texto em cinza é só exemplo.</p>
        ) : null}
        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            className="btn-primario"
            onClick={() => criar.mutate()}
            disabled={!nome.trim() || !apelido.trim() || criar.isPending}
          >
            {criar.isPending ? 'Criando…' : 'Criar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** Pôr nesta empresa uma conta que JÁ EXISTE — sem tirar das outras dela. */
function PorQuemJaExiste({
  empresa,
  jaDela,
  aoFechar,
}: {
  empresa: Empresa
  jaDela: UsuarioDaEmpresaAdmin[]
  aoFechar: () => void
}) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['contas'], queryFn: todasAsContas })
  const [filtro, setFiltro] = useState('')
  const [escolhida, setEscolhida] = useState<number | null>(null)

  const por = useMutation({
    mutationFn: () => porUsuarioNaEmpresa(empresa.id, escolhida as number),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresa-usuarios', empresa.id] })
      qc.invalidateQueries({ queryKey: ['empresa', empresa.id] })
      qc.invalidateQueries({ queryKey: ['empresas'] })
      qc.invalidateQueries({ queryKey: ['contas'] })
      aoFechar()
    },
  })

  const ids = new Set(jaDela.map((u) => u.id))
  const f = filtro.trim().toLowerCase()
  const candidatas = (data ?? []).filter(
    (c) =>
      !c.da_plataforma &&
      !ids.has(c.id) &&
      (!f || `${c.nome} ${c.apelido} ${c.email ?? ''}`.toLowerCase().includes(f)),
  )

  return (
    <Modal titulo={`Pôr em ${empresa.nome} quem já existe`} aoFechar={aoFechar} largura="max-w-2xl">
      {isLoading ? (
        <Carregando />
      ) : (
        <div className="grid gap-3">
          <p className="text-sm text-rotulo">
            A pessoa continua nas empresas dela e passa a ser desta também, com o mesmo papel.
            Sem empresa nenhuma, esta vira a de origem.
          </p>
          <input
            className="campo h-9 text-sm"
            placeholder="buscar por nome, apelido ou e-mail"
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
          />
          <select
            className="campo text-sm h-auto py-2"
            size={Math.min(8, Math.max(3, candidatas.length))}
            value={escolhida ?? ''}
            onChange={(e) => setEscolhida(Number(e.target.value))}
            aria-label="Conta"
          >
            {candidatas.map((c) => (
              <option key={c.id} value={c.id}>
                {c.nome} · {c.apelido} · {PAPEL[c.perfil] ?? c.perfil} ·{' '}
                {c.empresas.length ? c.empresas.map((e) => e.nome).join(', ') : 'sem empresa'}
              </option>
            ))}
          </select>
          {!candidatas.length ? <p className="text-xs text-fraco">Ninguém com esse filtro.</p> : null}
          {por.error ? <Erro>{mensagemDeErro(por.error)}</Erro> : null}
          <div className="flex justify-end gap-2">
            <button className="btn-secundario" onClick={aoFechar}>
              Cancelar
            </button>
            <button className="btn-primario" disabled={!escolhida || por.isPending} onClick={() => por.mutate()}>
              {por.isPending ? 'Pondo…' : 'Pôr nesta empresa'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

/* ------------------------------------------------------------------ usinas */

function UsinasDaEmpresa({ empresa }: { empresa: Empresa }) {
  const { data, isLoading, error } = useQuery({ queryKey: ['usinas-plataforma'], queryFn: usinasDaPlataforma })
  const dela = (data ?? []).filter((u) => u.empresa_id === empresa.id)

  return (
    <Cartao titulo={`Usinas · ${isLoading ? '…' : dela.length}`}>
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <div className="px-5 pb-5">
          <Erro>{mensagemDeErro(error)}</Erro>
        </div>
      ) : !dela.length ? (
        <Vazio
          titulo="Nenhuma usina nesta empresa"
          descricao="Quem traz as usinas é o gerente, no oem-gs (Usinas), com a conta da empresa no meuWatt e no meuPlano."
        />
      ) : (
        <>
          {dela.map((u, i) => (
            // No celular, o que é a usina desce para baixo do nome: lado a lado, o nome virava uma
            // coluna de uma palavra por linha (avaliação 10, 390 px).
            <div
              key={u.id}
              className={`px-5 py-3 flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-4 ${i ? 'border-t border-borda' : ''}`}
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-forte">{u.nome}</p>
                <p className="text-xs text-fraco">
                  {[u.cidade, u.uf].filter(Boolean).join(' · ') || 'sem cidade'}
                  {u.kwp !== null ? ` · ${u.kwp.toLocaleString('pt-BR')} kWp` : ''}
                  {` · dono: ${u.dono_nome ?? 'ninguém ainda'}`}
                </p>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-xs text-rotulo">
                  {[u.tem_meuwatt ? 'monitorada' : u.tem_micro ? 'portal do fabricante' : null, u.tem_meuplano ? 'com manutenção' : null]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
                <Selo tom={u.no_app ? 'ok' : 'sem-dados'}>{u.no_app ? 'No app' : 'Desligada'}</Selo>
              </div>
            </div>
          ))}
          <p className="px-5 py-3 border-t border-borda text-xs text-fraco">
            Trazer, casar, ligar e conceder usina é do gerente da empresa, no oem-gs.
          </p>
        </>
      )}
    </Cartao>
  )
}

/* --------------------------------------------------------------------- bot */

function BotDaEmpresa({ empresa }: { empresa: Empresa }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['log-do-bot', { empresa_id: empresa.id }],
    queryFn: () => logDoBot({ empresa_id: empresa.id }),
  })
  const ultimas = (data ?? []).slice(0, 8)
  return (
    <Cartao
      titulo="Últimas mensagens do bot"
      acao={
        <Link to={`/bot?empresa=${empresa.id}`} className="btn-fantasma">
          Ver o log inteiro
        </Link>
      }
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <div className="px-5 pb-5">
          <Erro>{mensagemDeErro(error)}</Erro>
        </div>
      ) : !ultimas.length ? (
        <Vazio titulo="Nenhuma mensagem ainda" descricao="O que as pessoas desta empresa mandarem ao bot do WhatsApp aparece aqui." />
      ) : (
        ultimas.map((r, i) => <LinhaDoLog key={r.id} registro={r} primeiro={i === 0} />)
      )}
    </Cartao>
  )
}

/* ------------------------------------------------------------------ editar */

function EditarEmpresa({ empresa, aoFechar }: { empresa: Empresa; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState(empresa.nome)
  const [documento, setDocumento] = useState(empresa.documento ?? '')
  const salvar = useMutation({
    mutationFn: () => editarEmpresa(empresa.id, { nome, documento }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresa', empresa.id] })
      qc.invalidateQueries({ queryKey: ['empresas'] })
      aoFechar()
    },
  })
  return (
    <Modal titulo={`Editar ${empresa.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Campo rotulo="Nome" value={nome} onChange={(e) => setNome(e.target.value)} />
        <Campo rotulo="CNPJ" value={documento} onChange={(e) => setDocumento(e.target.value)} />
        {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button className="btn-primario" disabled={!nome.trim() || salvar.isPending} onClick={() => salvar.mutate()}>
            Salvar
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** A mesma régua do apelido: sem acento, sem espaço, minúsculo. O servidor decide. */
function sugerir(nome: string): string {
  const partes = nome
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  if (!partes.length) return ''
  const base = partes.length === 1 ? partes[0] : `${partes[0]}.${partes[partes.length - 1]}`
  return base.replace(/[^a-z0-9._-]/g, '')
}
