/**
 * Quem é da empresa, e tudo o que o gerente faz com cada conta.
 *
 * A primeira versão era uma lista de leitura, e o dono resumiu o problema: *"só consigo
 * puxar as usinas da conta do gerente, mas não consigo atribuir aos usuários"*. As três
 * ações que faltavam estão aqui, na linha de cada pessoa:
 *
 * - **Usinas** — o que ela vê no aplicativo. É a concessão, e é ela que manda: o token
 *   diz com que credencial se lê, a concessão diz o que aparece.
 * - **Token** — opcional, e a tela explica por quê: sem ele o Gestão Solar lê com a
 *   credencial da EMPRESA. Com ele, a leitura passa a acontecer como a pessoa, e o produto
 *   aceita que ela entre com a senha daqui.
 * - **Senha e acesso** — redefinir e desativar.
 *
 * O gerente aparece na lista junto dos clientes, e é de propósito: ele também recebe
 * usinas (é assim que ele vê a carteira no aplicativo). O que não se oferece a ele é
 * desativar a si mesmo — ficaria sem acesso no mesmo instante, e a saída seria a
 * plataforma.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Link2, Sun, UserCog, UserPlus } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio } from '@/components/base'
import {
  catalogoDeUsinas,
  conectarContaDoCliente,
  definirUsinasDoCliente,
  desconectarContaDoCliente,
  editarContaDaEmpresa,
  criarClienteDaEmpresa,
  usinasConcedidas,
  usuariosDetalhados,
  type Produto,
  type UsuarioDetalhado,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

const PAPEL: Record<string, string> = {
  gestor_empresa: 'Gerente da empresa',
  cliente: 'Dono de usina',
}

const NOME_DO_PRODUTO: Record<Produto, string> = { meuwatt: 'meuWatt', meuplano: 'meuPlano' }

export function UsuariosDaEmpresa() {
  const empresa = useAuth((s) => s.empresa)
  const eu = useAuth((s) => s.apelido)
  const { data, isLoading, error } = useQuery({
    queryKey: ['empresa', 'usuarios-detalhados'],
    queryFn: usuariosDetalhados,
  })
  const [usinasDe, setUsinasDe] = useState<UsuarioDetalhado | null>(null)
  const [tokensDe, setTokensDe] = useState<UsuarioDetalhado | null>(null)
  const [novo, setNovo] = useState(false)

  return (
    <Pagina
      titulo="Usuários"
      apoio={empresa ? `Quem é da sua empresa · ${empresa}` : 'Quem é da sua empresa'}
      acao={
        <button className="btn-primario" onClick={() => setNovo(true)}>
          <UserPlus size={16} />
          Novo usuário
        </button>
      }
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : !data?.length ? (
        <Vazio
          titulo="Nenhuma conta nesta empresa"
          descricao="Cadastre um dono de usina em Clientes → Novo cliente."
        />
      ) : (
        <div className="grid gap-3">
          {data.map((u) => (
            <Linha
              key={u.id}
              usuario={u}
              souEu={u.apelido === eu}
              aoAbrirUsinas={() => setUsinasDe(u)}
              aoAbrirTokens={() => setTokensDe(u)}
            />
          ))}
        </div>
      )}

      {usinasDe ? (
        <UsinasDoUsuario usuario={usinasDe} aoFechar={() => setUsinasDe(null)} />
      ) : null}
      {tokensDe ? <Tokens usuario={tokensDe} aoFechar={() => setTokensDe(null)} /> : null}
      {novo ? <NovoUsuario aoFechar={() => setNovo(false)} /> : null}
    </Pagina>
  )
}

function Linha({
  usuario,
  souEu,
  aoAbrirUsinas,
  aoAbrirTokens,
}: {
  usuario: UsuarioDetalhado
  souEu: boolean
  aoAbrirUsinas: () => void
  aoAbrirTokens: () => void
}) {
  const qc = useQueryClient()
  const [senhaAberta, setSenhaAberta] = useState(false)
  const [senha, setSenha] = useState('')

  const editar = useMutation({
    mutationFn: (dados: { ativo?: boolean; senha?: string }) =>
      editarContaDaEmpresa(usuario.id, dados),
    onSuccess: () => {
      setSenhaAberta(false)
      setSenha('')
      qc.invalidateQueries({ queryKey: ['empresa'] })
    },
  })

  return (
    <Cartao>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-3 min-w-0">
          <UserCog size={18} className="text-rotulo mt-1 shrink-0" />
          <div className="min-w-0">
            <p className="text-forte font-semibold">
              {usuario.nome}
              {souEu ? <span className="text-xs text-ok font-normal ml-2">é você</span> : null}
            </p>
            <p className="text-sm text-rotulo mt-0.5">
              {usuario.apelido} · {PAPEL[usuario.perfil] ?? usuario.perfil}
              {usuario.email ? ` · ${usuario.email}` : ''}
            </p>
            <p className="text-sm text-rotulo mt-2 flex items-center gap-3 flex-wrap">
              <span className="flex items-center gap-1.5">
                <Sun size={14} />
                {usuario.usinas} {usuario.usinas === 1 ? 'usina' : 'usinas'} no app
              </span>
              <span className="flex items-center gap-1.5">
                <Link2 size={14} />
                {usuario.produtos.length
                  ? `conta própria: ${usuario.produtos.map((p) => NOME_DO_PRODUTO[p]).join(' · ')}`
                  : 'lê com a conta da empresa'}
              </span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Selo tom={usuario.ativo ? 'ok' : 'sem-dados'}>
            {usuario.ativo ? 'Ativo' : 'Inativo'}
          </Selo>
          <button className="btn-secundario" onClick={aoAbrirUsinas}>
            Usinas
          </button>
          <button className="btn-fantasma" onClick={aoAbrirTokens}>
            Token
          </button>
          <button className="btn-fantasma" onClick={() => setSenhaAberta((v) => !v)}>
            <KeyRound size={13} />
            Senha
          </button>
          {!souEu ? (
            <button
              className="btn-fantasma"
              disabled={editar.isPending}
              onClick={() => editar.mutate({ ativo: !usuario.ativo })}
            >
              {usuario.ativo ? 'Desativar' : 'Reativar'}
            </button>
          ) : null}
        </div>
      </div>

      {senhaAberta ? (
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
            onClick={() => editar.mutate({ senha })}
          >
            Definir
          </button>
        </div>
      ) : null}

      {editar.error ? <Erro className="mt-2">{mensagemDeErro(editar.error)}</Erro> : null}
    </Cartao>
  )
}

/**
 * O que esta pessoa vê no aplicativo.
 *
 * Só usinas ligadas no app aparecem: uma desligada não pode ser concedida, e oferecê-la
 * produziria uma concessão que não mostra nada. A lista é completa — o que ficar
 * desmarcado é retirado dela.
 */
function UsinasDoUsuario({
  usuario,
  aoFechar,
}: {
  usuario: UsuarioDetalhado
  aoFechar: () => void
}) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['empresa', 'usinas-catalogo'],
    queryFn: catalogoDeUsinas,
  })
  // O que ela JÁ recebe. Sem isto a tela abriria com tudo desmarcado, e o primeiro
  // clique em Salvar apagaria a concessão inteira — a gravação é a lista completa.
  const { data: atuais, isLoading: carregandoAtuais } = useQuery({
    queryKey: ['empresa', 'usinas-concedidas', usuario.id],
    queryFn: () => usinasConcedidas(usuario.id),
  })
  const [marcadas, setMarcadas] = useState<number[] | null>(null)
  const escolhidas = marcadas ?? (atuais ?? []).map((c) => c.plant_link_id)
  // Concessão HERDADA: usina dada antes do multiempresa, que nunca foi trazida para
  // empresa nenhuma. Ela precisa aparecer — senão vai junto no salvar e volta como erro.
  const herdadas = (atuais ?? []).filter((c) => !c.da_empresa)

  const salvar = useMutation({
    mutationFn: () => definirUsinasDoCliente(usuario.id, escolhidas),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresa'] })
      aoFechar()
    },
  })

  const noApp = (data?.linhas ?? []).filter((l) => l.plant_link_id !== null && l.no_app)

  return (
    <Modal titulo={`Usinas de ${usuario.nome}`} aoFechar={aoFechar} largura="max-w-2xl">
      {isLoading || carregandoAtuais ? (
        <Carregando />
      ) : (
        <div className="grid gap-4">
          <Aviso>
            A lista é completa: o que ficar desmarcado é retirado dele. Hoje ele recebe{' '}
            {usuario.usinas} {usuario.usinas === 1 ? 'usina' : 'usinas'} — marque tudo o que
            ele deve ver.
          </Aviso>

          {herdadas.length ? (
            <div className="border border-alerta/30 bg-alerta/5 rounded-card p-3">
              <p className="text-sm text-alerta font-semibold">
                {herdadas.length === 1 ? 'Uma usina concedida' : `${herdadas.length} usinas concedidas`}{' '}
                antes desta empresa existir
              </p>
              <p className="text-xs text-rotulo mt-1">
                {herdadas.map((h) => h.nome).join(', ')} — ainda não {herdadas.length === 1 ? 'pertence' : 'pertencem'} a
                nenhuma empresa. Traga em “Usinas” para manter, ou salve assim para tirar
                {herdadas.length === 1 ? '-la' : '-las'} desta pessoa.
              </p>
            </div>
          ) : null}

          {!noApp.length ? (
            <p className="text-sm text-rotulo">
              Nenhuma usina ligada no aplicativo ainda. Traga e ligue em “Usinas”.
            </p>
          ) : (
            <ul className="grid gap-1 max-h-80 overflow-y-auto pr-1">
              {noApp.map((l) => {
                const id = l.plant_link_id as number
                return (
                  <li key={l.chave}>
                    <label className="flex items-center gap-2.5 px-3 py-2 rounded-campo hover:bg-superficie cursor-pointer">
                      <input
                        type="checkbox"
                        checked={escolhidas.includes(id)}
                        onChange={() =>
                          setMarcadas(
                            escolhidas.includes(id)
                              ? escolhidas.filter((x) => x !== id)
                              : [...escolhidas, id],
                          )
                        }
                      />
                      <span className="text-sm text-forte">{l.nome}</span>
                      <span className="text-xs text-fraco">
                        {[l.cidade, l.uf].filter(Boolean).join(' · ')}
                      </span>
                    </label>
                  </li>
                )
              })}
            </ul>
          )}

          {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}

          <div className="flex justify-end gap-2">
            <button className="btn-secundario" onClick={aoFechar}>
              Cancelar
            </button>
            <button
              className="btn-primario"
              onClick={() => salvar.mutate()}
              disabled={salvar.isPending}
            >
              {salvar.isPending ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

/**
 * O token pessoal desta pessoa em cada produto — **opcional**.
 *
 * Sem ele, o Gestão Solar lê os dados dela com a credencial da EMPRESA, e a concessão
 * decide o que aparece. É o caso comum: o dono de usina costuma não ter conta no meuWatt
 * nem no meuPlano.
 *
 * Com ele, a leitura passa a acontecer **como ela**: as usinas que ela enxergaria lá, pela
 * regra de lá — e o produto passa a aceitar que ela entre com a senha daqui.
 */
function Tokens({ usuario, aoFechar }: { usuario: UsuarioDetalhado; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [produto, setProduto] = useState<Produto>('meuwatt')
  const [token, setToken] = useState('')
  const [resultado, setResultado] = useState<{ ok: boolean; detalhe: string } | null>(null)

  const conectar = useMutation({
    mutationFn: () => conectarContaDoCliente(usuario.id, produto, token),
    onSuccess: (r) => {
      setResultado(r)
      if (r.ok) setToken('')
      qc.invalidateQueries({ queryKey: ['empresa'] })
    },
  })

  const desconectar = useMutation({
    mutationFn: (p: Produto) => desconectarContaDoCliente(usuario.id, p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresa'] }),
  })

  return (
    <Modal titulo={`Token de ${usuario.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Aviso>
          O token é <strong>opcional</strong>. Sem ele, os dados desta pessoa são lidos com a
          conta da <strong>empresa</strong>, e o que ela vê continua sendo o que você
          concedeu. Com ele, a leitura acontece como ela — e ela passa a poder entrar no
          meuWatt/meuPlano com a senha daqui.
        </Aviso>

        {usuario.produtos.length ? (
          <div className="grid gap-2">
            {usuario.produtos.map((p) => (
              <div key={p} className="flex items-center justify-between gap-2">
                <span className="text-sm text-forte">
                  Conta própria no {NOME_DO_PRODUTO[p]}
                </span>
                <button
                  className="btn-fantasma"
                  disabled={desconectar.isPending}
                  onClick={() => desconectar.mutate(p)}
                >
                  Desconectar
                </button>
              </div>
            ))}
          </div>
        ) : null}

        <div>
          <p className="rotulo-campo">Produto</p>
          <select
            className="campo h-9 text-sm mt-1"
            value={produto}
            onChange={(e) => setProduto(e.target.value as Produto)}
          >
            <option value="meuwatt">meuWatt</option>
            <option value="meuplano">meuPlano</option>
          </select>
        </div>

        <div>
          <p className="rotulo-campo">Token gerado na conta dela</p>
          <input
            className="campo mt-1"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="cole aqui"
          />
        </div>

        {resultado ? (
          resultado.ok ? (
            <p className="text-sm text-ok">{resultado.detalhe}</p>
          ) : (
            <Erro>{resultado.detalhe}</Erro>
          )
        ) : null}
        {conectar.error ? <Erro>{mensagemDeErro(conectar.error)}</Erro> : null}

        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Fechar
          </button>
          <button
            className="btn-primario"
            onClick={() => conectar.mutate()}
            disabled={!token.trim() || conectar.isPending}
          >
            {conectar.isPending ? 'Conferindo…' : 'Conectar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}


/** Cadastro de quem é da empresa: dono de usina ou outro gerente. */
function NovoUsuario({ aoFechar }: { aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [apelido, setApelido] = useState('')
  const [email, setEmail] = useState('')
  const [perfil, setPerfil] = useState<'cliente' | 'gestor_empresa'>('cliente')
  const [criado, setCriado] = useState<{ apelido: string; senha: string } | null>(null)

  const criar = useMutation({
    mutationFn: () => criarClienteDaEmpresa({ nome, apelido, email: email || null, perfil }),
    onSuccess: (r) => {
      setCriado({ apelido: r.apelido, senha: r.senha })
      qc.invalidateQueries({ queryKey: ['empresa'] })
    },
  })

  if (criado) {
    return (
      <Modal titulo="Usuário criado" aoFechar={aoFechar}>
        <div className="grid gap-4">
          <Aviso>Anote agora: a senha não é guardada em texto e não dá para vê-la de novo.</Aviso>
          <Cartao>
            <p className="text-sm text-rotulo">Entra com o apelido</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.apelido}</p>
            <p className="text-sm text-rotulo mt-4">Senha provisória</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.senha}</p>
          </Cartao>
          <p className="text-xs text-fraco">
            Entregue as duas juntas. O e-mail é só contato — quem autentica é o apelido.
          </p>
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
    <Modal titulo="Novo usuário" aoFechar={aoFechar}>
      <div className="grid gap-4">
        <div>
          <p className="rotulo-campo">O que ele é</p>
          <select
            className="campo h-9 text-sm mt-1"
            value={perfil}
            onChange={(e) => setPerfil(e.target.value as 'cliente' | 'gestor_empresa')}
          >
            <option value="cliente">Dono de usina — entra no aplicativo</option>
            <option value="gestor_empresa">Gerente — opera a empresa com você</option>
          </select>
          <p className="text-xs text-fraco mt-1.5">
            {perfil === 'cliente'
              ? 'Vê apenas as usinas que você conceder a ele.'
              : 'Vê e opera tudo desta empresa, como você.'}
          </p>
        </div>

        <div>
          <p className="rotulo-campo">Nome</p>
          <input className="campo mt-1" value={nome} onChange={(e) => setNome(e.target.value)} />
        </div>
        <div>
          <p className="rotulo-campo">Apelido (é com ele que entra)</p>
          <input
            className="campo mt-1"
            value={apelido}
            onChange={(e) => setApelido(e.target.value)}
          />
        </div>
        <div>
          <p className="rotulo-campo">E-mail (opcional)</p>
          <input className="campo mt-1" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>

        {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}
        {!nome.trim() || !apelido.trim() ? (
          <p className="text-xs text-rotulo">Preencha nome e apelido para cadastrar.</p>
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
