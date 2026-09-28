/**
 * Empresas de O&M — a tela da PLATAFORMA que cria e desliga inquilino.
 *
 * É a única tela do sistema que mostra a lista inteira de empresas. Nenhuma empresa sabe
 * que as outras existem, e é por isso que ela vive em `/api/painel/*`, atrás da área
 * `empresas`, e não em lugar nenhum do portão do inquilino.
 *
 * **Desligar, não apagar.** `ativa=false` tira a empresa de operação — o gerente dela para
 * de entrar na requisição seguinte, sem esperar a sessão expirar — e preserva usina,
 * cliente e histórico. Não há botão de apagar: a chave estrangeira é `RESTRICT`, e o que
 * ela protege é o histórico que alguém ainda vai precisar auditar.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Link2, Power, Sun, Users } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio } from '@/components/base'
import {
  carteiraDaEmpresa,
  contasLivres,
  criarEmpresa,
  criarGerente,
  editarUsuarioDaEmpresa,
  editarEmpresa,
  listarEmpresas,
  salvarCarteira,
  tornarGerente,
  usuariosDaEmpresaAdmin,
  type Empresa,
  type GerenteCriado,
  type ItemDaCarteira,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Empresas() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['empresas'], queryFn: listarEmpresas })
  const [novaAberta, setNovaAberta] = useState(false)
  const [carteiraDe, setCarteiraDe] = useState<Empresa | null>(null)
  const [gerenteDe, setGerenteDe] = useState<Empresa | null>(null)
  const [usuariosDe, setUsuariosDe] = useState<Empresa | null>(null)

  const alternar = useMutation({
    mutationFn: ({ id, ativa }: { id: number; ativa: boolean }) => editarEmpresa(id, { ativa }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresas'] }),
  })

  return (
    <Pagina
      titulo="Empresas de O&M"
      apoio="Cada empresa é um inquilino: os usuários, as usinas e as conexões dela não aparecem para nenhuma outra."
      acao={
        <button className="btn-primario" onClick={() => setNovaAberta(true)}>
          Cadastrar empresa
        </button>
      }
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : !data?.length ? (
        <Vazio
          titulo="Nenhuma empresa cadastrada"
          descricao="Enquanto não houver empresa, usinas e clientes ficam sem dono e só a plataforma os enxerga."
        />
      ) : (
        <div className="grid gap-3">
          {alternar.error ? <Erro>{mensagemDeErro(alternar.error)}</Erro> : null}
          {data.map((e) => (
            <Linha
              key={e.id}
              empresa={e}
              ocupado={alternar.isPending}
              aoAlternar={() => alternar.mutate({ id: e.id, ativa: !e.ativa })}
              aoAbrirCarteira={() => setCarteiraDe(e)}
              aoAbrirGerente={() => setGerenteDe(e)}
              aoAbrirUsuarios={() => setUsuariosDe(e)}
            />
          ))}
        </div>
      )}

      {novaAberta ? <Nova aoFechar={() => setNovaAberta(false)} /> : null}
      {carteiraDe ? (
        <CarteiraModal empresa={carteiraDe} aoFechar={() => setCarteiraDe(null)} />
      ) : null}
      {gerenteDe ? (
        <NovoGerente empresa={gerenteDe} aoFechar={() => setGerenteDe(null)} />
      ) : null}
      {usuariosDe ? (
        <UsuariosModal empresa={usuariosDe} aoFechar={() => setUsuariosDe(null)} />
      ) : null}
    </Pagina>
  )
}

function Linha({
  empresa,
  ocupado,
  aoAlternar,
  aoAbrirCarteira,
  aoAbrirGerente,
  aoAbrirUsuarios,
}: {
  empresa: Empresa
  ocupado: boolean
  aoAlternar: () => void
  aoAbrirCarteira: () => void
  aoAbrirGerente: () => void
  aoAbrirUsuarios: () => void
}) {
  return (
    <Cartao>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <Building2 size={18} className="text-rotulo mt-1 shrink-0" />
          <div>
            <p className="text-forte font-semibold">{empresa.nome}</p>
            <p className="text-sm text-rotulo mt-0.5">
              {empresa.documento ?? 'sem CNPJ cadastrado'}
            </p>
            <div className="flex items-center gap-4 mt-2 text-sm text-rotulo flex-wrap">
              <span className="flex items-center gap-1.5">
                <Users size={14} /> {empresa.usuarios}{' '}
                {empresa.usuarios === 1 ? 'usuário' : 'usuários'}
              </span>
              <span className="flex items-center gap-1.5">
                <Sun size={14} /> {empresa.usinas} {empresa.usinas === 1 ? 'usina' : 'usinas'}
              </span>
              {/* Só leitura: quem casa a empresa com a do meuWatt/meuPlano é o gerente
                  dela, que é quem tem o token. A plataforma não tem credencial nos
                  produtos — ver o aviso abaixo quando faltar. */}
              <span className="flex items-center gap-1.5">
                <Link2 size={14} />
                {[
                  empresa.mw_enterprise_id ? 'meuWatt' : null,
                  empresa.mp_tenant_id ? 'meuPlano' : null,
                ]
                  .filter(Boolean)
                  .join(' · ') || 'sem vínculo'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Selo tom={empresa.ativa ? 'ok' : 'sem-dados'}>{empresa.ativa ? 'Ativa' : 'Desligada'}</Selo>
          <button className="btn-secundario" onClick={aoAbrirUsuarios}>
            Usuários
          </button>
          <button className="btn-secundario" onClick={aoAbrirGerente}>
            Novo gerente
          </button>
          <button className="btn-secundario" onClick={aoAbrirCarteira}>
            Usinas e clientes
          </button>
          <button className="btn-secundario" onClick={aoAlternar} disabled={ocupado}>
            <Power size={14} className="inline mr-1.5" />
            {empresa.ativa ? 'Desligar' : 'Religar'}
          </button>
        </div>
      </div>

      {!empresa.ativa ? (
        <p className="text-sm text-rotulo mt-3">
          O gerente desta empresa não entra enquanto ela estiver desligada. Usinas, clientes e
          histórico continuam guardados.
        </p>
      ) : null}

      {/* Sem nenhum dos dois vínculos a empresa é fantasma: ela aparece na lista e todas
          as telas dela vêm vazias, porque não há upstream de onde ler. */}
      {!empresa.mw_enterprise_id && !empresa.mp_tenant_id ? (
        <Erro className="mt-3">
          Esta empresa ainda não aponta para nenhuma empresa do meuWatt nem do meuPlano —
          as telas dela vêm vazias. Quem faz esse vínculo é o gerente dela, em Conexões e
          Vínculos: é ele que tem o token dos produtos.
        </Erro>
      ) : null}
    </Cartao>
  )
}

function Nova({ aoFechar }: { aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [documento, setDocumento] = useState('')

  const criar = useMutation({
    mutationFn: () => criarEmpresa({ nome, documento: documento || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresas'] })
      aoFechar()
    },
  })

  return (
    <Modal titulo="Cadastrar empresa de O&M" aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Aviso>
          O nome é único. “Splendor O&M” e “splendor o&amp;m” são a mesma empresa — era
          exatamente isso que o cadastro por texto livre deixava passar.
        </Aviso>

        <Campo
          rotulo="Nome"
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="Splendor O&M"
        />
        <Campo
          rotulo="CNPJ (opcional)"
          value={documento}
          onChange={(e) => setDocumento(e.target.value)}
          placeholder="00.000.000/0001-00"
        />

        {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}

        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            className="btn-primario"
            onClick={() => criar.mutate()}
            disabled={!nome.trim() || criar.isPending}
          >
            {criar.isPending ? 'Cadastrando…' : 'Cadastrar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}


/**
 * De quem é o quê: as usinas e os clientes desta empresa.
 *
 * A lista é a do sistema inteiro, com o dono atual ao lado de cada linha. Mostrar só o que
 * já é dela esconderia exatamente o que falta atribuir — que é o estado de tudo o que
 * existia antes do multiempresa.
 *
 * O que pertence a OUTRA empresa aparece travado, com o nome do dono. Transferir carteira
 * com um clique distraído não é uma operação que esta tela oferece: tira-se lá, põe-se
 * aqui, duas decisões.
 */
function CarteiraModal({ empresa, aoFechar }: { empresa: Empresa; aoFechar: () => void }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['carteira', empresa.id],
    queryFn: () => carteiraDaEmpresa(empresa.id),
  })
  const [usinas, setUsinas] = useState<number[] | null>(null)
  const [clientes, setClientes] = useState<number[] | null>(null)

  // A escolha nasce do que o servidor devolveu; enquanto ela for nula, a marcação lida é
  // a do dado. Sem isso, a caixa ficaria desmarcada no primeiro quadro e um "Salvar"
  // rápido apagaria a carteira inteira.
  const marcadasUsinas = usinas ?? (data?.usinas ?? []).filter((i) => i.empresa_id === empresa.id).map((i) => i.id)
  const marcadosClientes =
    clientes ?? (data?.clientes ?? []).filter((i) => i.empresa_id === empresa.id).map((i) => i.id)

  const salvar = useMutation({
    mutationFn: () => salvarCarteira(empresa.id, { usinas: marcadasUsinas, clientes: marcadosClientes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresas'] })
      qc.invalidateQueries({ queryKey: ['carteira', empresa.id] })
      aoFechar()
    },
  })

  function alternarItem(lista: number[], id: number, definir: (v: number[]) => void) {
    definir(lista.includes(id) ? lista.filter((x) => x !== id) : [...lista, id])
  }

  return (
    <Modal titulo={`Usinas e clientes · ${empresa.nome}`} aoFechar={aoFechar} largura="max-w-3xl">
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : (
        <div className="grid gap-5">
          <Aviso>
            O que sair das listas fica <strong>sem dono</strong> — não volta para outra
            empresa. Linha travada já pertence a outra: tire lá antes de trazer para cá.
          </Aviso>

          <Coluna
            titulo="Usinas"
            itens={data?.usinas ?? []}
            marcados={marcadasUsinas}
            empresaId={empresa.id}
            aoAlternar={(id) => alternarItem(marcadasUsinas, id, setUsinas)}
          />
          <Coluna
            titulo="Clientes e gerentes"
            itens={data?.clientes ?? []}
            marcados={marcadosClientes}
            empresaId={empresa.id}
            aoAlternar={(id) => alternarItem(marcadosClientes, id, setClientes)}
          />

          {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}

          <div className="flex justify-end gap-2">
            <button className="btn-secundario" onClick={aoFechar}>
              Cancelar
            </button>
            <button className="btn-primario" onClick={() => salvar.mutate()} disabled={salvar.isPending}>
              {salvar.isPending ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Coluna({
  titulo,
  itens,
  marcados,
  empresaId,
  aoAlternar,
}: {
  titulo: string
  itens: ItemDaCarteira[]
  marcados: number[]
  empresaId: number
  aoAlternar: (id: number) => void
}) {
  if (!itens.length) {
    return (
      <div>
        <p className="rotulo-campo">{titulo}</p>
        <p className="text-sm text-rotulo mt-1">Nada cadastrado ainda.</p>
      </div>
    )
  }
  return (
    <div>
      <p className="rotulo-campo">{titulo}</p>
      <ul className="mt-2 grid gap-1 max-h-64 overflow-y-auto pr-1">
        {itens.map((i) => {
          const deOutra = i.empresa_id !== null && i.empresa_id !== empresaId
          return (
            <li key={i.id}>
              <label
                className={`flex items-center gap-2.5 px-3 py-2 rounded-campo ${
                  deOutra ? 'opacity-60' : 'hover:bg-superficie cursor-pointer'
                }`}
              >
                <input
                  type="checkbox"
                  checked={marcados.includes(i.id)}
                  disabled={deOutra}
                  onChange={() => aoAlternar(i.id)}
                />
                <span className="text-sm text-forte">{i.nome}</span>
                {i.detalhe ? <span className="text-xs text-fraco">{i.detalhe}</span> : null}
                {deOutra ? (
                  <span className="text-xs text-rotulo ml-auto">{i.empresa_nome}</span>
                ) : null}
              </label>
            </li>
          )
        })}
      </ul>
    </div>
  )
}


/**
 * O gerente da empresa nasce aqui — e não na tela de Usuários do sistema.
 *
 * Lá ele nasceria sem empresa, e uma conta de inquilino sem vínculo não entra em lugar
 * nenhum: seria uma conta que parece pronta e não abre nada. Aqui a empresa é o caminho
 * da rota, então o vínculo é obrigatório por construção.
 *
 * A senha aparece UMA vez e some. Ela é entregue junto com o **apelido**, que é o que
 * autentica — mandar o e-mail junto convidaria a tentar entrar com ele, que é exatamente
 * o que não funciona.
 */
function NovoGerente({ empresa, aoFechar }: { empresa: Empresa; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [apelido, setApelido] = useState('')
  const [email, setEmail] = useState('')
  const [minha, setMinha] = useState(false)
  const [criado, setCriado] = useState<GerenteCriado | null>(null)

  const criar = useMutation({
    mutationFn: () => criarGerente(empresa.id, { nome, apelido, email: email || null, minha }),
    onSuccess: (r) => {
      setCriado(r)
      qc.invalidateQueries({ queryKey: ['empresas'] })
      // O seletor de papel muda na hora: a conta nova entrou no grupo de quem criou.
      qc.invalidateQueries({ queryKey: ['papeis'] })
    },
  })

  // O apelido sugerido a partir do nome, enquanto ninguém o editou à mão. O servidor
  // normaliza e decide — isto é só conforto de digitação.
  function aoDigitarNome(valor: string) {
    const sugestaoAnterior = sugerir(nome)
    setNome(valor)
    if (!apelido || apelido === sugestaoAnterior) setApelido(sugerir(valor))
  }

  if (criado) {
    return (
      <Modal titulo="Gerente criado" aoFechar={aoFechar}>
        <div className="grid gap-4">
          <Aviso>
            Anote agora: a senha não é guardada em texto e não dá para vê-la de novo. Quem
            perder, redefine — em “Usuários”, na própria empresa.
          </Aviso>
          {criado.agrupada ? (
            <p className="text-sm text-ok">
              Esta conta entrou no seu grupo de papéis: use “Trocar papel”, no alto da tela.
            </p>
          ) : null}
          <Cartao>
            <p className="text-sm text-rotulo">Entra com o apelido</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.apelido}</p>
            <p className="text-sm text-rotulo mt-4">Senha provisória</p>
            <p className="text-forte font-semibold text-lg mt-1 font-mono">{criado.senha}</p>
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
    <Modal titulo={`Novo gerente · ${empresa.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Aviso>
          O gerente abre a área da empresa — usinas, clientes, usuários e as conexões dela.
          Não abre nada da plataforma.
        </Aviso>

        <Campo
          rotulo="Nome"
          value={nome}
          onChange={(e) => aoDigitarNome(e.target.value)}
          placeholder="Maria Silva"
        />
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

        {/* O caso de quem administra a plataforma E gerencia uma empresa. Marcado, a conta
            nasce no mesmo grupo de papéis e o seletor "Trocar papel" já a mostra — sem uma
            segunda tela para alguém esquecer. */}
        <label className="flex items-start gap-2.5 px-3 py-2.5 rounded-campo bg-superficie cursor-pointer">
          <input
            type="checkbox"
            checked={minha}
            onChange={(e) => setMinha(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            <span className="text-sm text-forte">Esta conta é minha</span>
            <span className="block text-xs text-fraco mt-0.5">
              Você passa a trocar entre o painel da plataforma e esta empresa pelo botão
              “Trocar papel”, sem sair e entrar de novo.
            </span>
          </span>
        </label>

        {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}

        {/* Botão travado sem explicação faz a pessoa clicar de novo achando que quebrou —
            foi o que aconteceu com os campos vazios e o exemplo em cinza parecendo texto
            preenchido. A frase diz o que falta. */}
        {!nome.trim() || !apelido.trim() ? (
          <p className="text-xs text-rotulo">
            Preencha nome e apelido para criar. O texto em cinza é só um exemplo.
          </p>
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
            {criar.isPending ? 'Criando…' : 'Criar gerente'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** A mesma régua do apelido do cliente: sem acento, sem espaço, minúsculo. */
function sugerir(nome: string): string {
  const limpo = nome
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
  const partes = limpo.split(/\s+/).filter(Boolean)
  if (partes.length === 0) return ''
  if (partes.length === 1) return partes[0].replace(/[^a-z0-9._-]/g, '')
  return `${partes[0]}.${partes[partes.length - 1]}`.replace(/[^a-z0-9._-]/g, '')
}



/**
 * Quem é da empresa, e as duas ações que a plataforma precisa ter: desativar e redefinir
 * a senha.
 *
 * Fica aqui, e não em Usuários do sistema, porque aquela tela é do staff da PLATAFORMA —
 * misturar as duas já deixava um clique na linha errada promover o gerente de um inquilino
 * a administrador do sistema inteiro. Cada lado se administra na casa dele.
 */
function UsuariosModal({ empresa, aoFechar }: { empresa: Empresa; aoFechar: () => void }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['empresa-usuarios', empresa.id],
    queryFn: () => usuariosDaEmpresaAdmin(empresa.id),
  })
  const [senhaDe, setSenhaDe] = useState<number | null>(null)
  const [senha, setSenha] = useState('')

  const editar = useMutation({
    mutationFn: ({ id, dados }: { id: number; dados: { ativo?: boolean; senha?: string } }) =>
      editarUsuarioDaEmpresa(empresa.id, id, dados),
    onSuccess: () => {
      setSenhaDe(null)
      setSenha('')
      qc.invalidateQueries({ queryKey: ['empresa-usuarios', empresa.id] })
    },
  })

  const PAPEL: Record<string, string> = {
    gestor_empresa: 'Gerente',
    cliente: 'Dono de usina',
    administrador: 'Plataforma',
    atendimento: 'Plataforma',
  }

  return (
    <Modal titulo={`Usuários · ${empresa.nome}`} aoFechar={aoFechar} largura="max-w-2xl">
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : !data?.length ? (
        <Vazio
          titulo="Nenhuma conta nesta empresa"
          descricao="Crie o gerente dela em “Novo gerente”, ou traga clientes em “Usinas e clientes”."
        />
      ) : (
        <div className="grid gap-2">
          {data.map((u) => (
            <Cartao key={u.id}>
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <p className="text-forte font-semibold">
                    {u.nome}
                    {u.minha ? (
                      <span className="text-xs text-ok font-normal ml-2">é você</span>
                    ) : null}
                  </p>
                  <p className="text-sm text-rotulo mt-0.5">
                    {u.apelido} · {PAPEL[u.perfil] ?? u.perfil}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Selo tom={u.ativo ? 'ok' : 'sem-dados'}>{u.ativo ? 'Ativo' : 'Inativo'}</Selo>
                  <button
                    className="btn-fantasma"
                    onClick={() => setSenhaDe(senhaDe === u.id ? null : u.id)}
                  >
                    Redefinir senha
                  </button>
                  <button
                    className="btn-fantasma"
                    onClick={() => editar.mutate({ id: u.id, dados: { ativo: !u.ativo } })}
                    disabled={editar.isPending}
                  >
                    {u.ativo ? 'Desativar' : 'Reativar'}
                  </button>
                </div>
              </div>

              {senhaDe === u.id ? (
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
                    className="btn-secundario shrink-0"
                    disabled={senha.length < 8 || editar.isPending}
                    onClick={() => editar.mutate({ id: u.id, dados: { senha } })}
                  >
                    Definir
                  </button>
                </div>
              ) : null}
            </Cartao>
          ))}
          {editar.error ? <Erro>{mensagemDeErro(editar.error)}</Erro> : null}
          <p className="text-xs text-fraco mt-1">
            A senha definida aqui é a que você entrega à pessoa — junto com o apelido, que é
            o que ela digita para entrar.
          </p>

          <TrazerConta empresa={empresa} />
        </div>
      )}
    </Modal>
  )
}


/**
 * Trazer para a empresa uma conta que JÁ EXISTE.
 *
 * "Novo gerente" não serve para quem já está no sistema: a conta traz usinas concedidas,
 * tokens de produto e histórico, e recriá-la perderia tudo. É o caso de quem já usava o
 * Gestão Solar como cliente e passa a gerenciar a própria empresa.
 *
 * A sua própria conta não aparece: quem administra a plataforma e se rebaixasse a gerente
 * perderia o painel no mesmo instante, e a saída seria outro administrador ou o banco.
 */
function TrazerConta({ empresa }: { empresa: Empresa }) {
  const qc = useQueryClient()
  const [apelido, setApelido] = useState('')
  const { data } = useQuery({ queryKey: ['contas-livres'], queryFn: contasLivres })

  const trazer = useMutation({
    mutationFn: () => tornarGerente(empresa.id, apelido),
    onSuccess: () => {
      setApelido('')
      qc.invalidateQueries({ queryKey: ['empresa-usuarios', empresa.id] })
      qc.invalidateQueries({ queryKey: ['contas-livres'] })
      qc.invalidateQueries({ queryKey: ['empresas'] })
    },
  })

  return (
    <div className="border-t border-borda pt-4 mt-2">
      <p className="rotulo-campo">Tornar gerente uma conta que já existe</p>
      <p className="text-xs text-fraco mt-1 mb-2">
        Para quem já usa o sistema: a conta mantém usinas, tokens e histórico.
      </p>
      <div className="flex gap-2">
        <select
          className="campo h-9 text-sm"
          value={apelido}
          onChange={(e) => setApelido(e.target.value)}
        >
          <option value="">escolha uma conta…</option>
          {(data ?? []).map((c) => (
            <option key={c.apelido} value={c.apelido}>
              {c.apelido} — {c.nome}
              {c.empresa ? ` (hoje em ${c.empresa})` : ''}
            </option>
          ))}
        </select>
        <button
          className="btn-secundario shrink-0"
          disabled={!apelido || trazer.isPending}
          onClick={() => trazer.mutate()}
        >
          {trazer.isPending ? 'Trazendo…' : 'Tornar gerente'}
        </button>
      </div>
      {trazer.error ? <Erro className="mt-2">{mensagemDeErro(trazer.error)}</Erro> : null}
    </div>
  )
}
