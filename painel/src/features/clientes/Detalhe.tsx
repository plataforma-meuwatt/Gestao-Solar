import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Check,
  KeyRound,
  Link2,
  Link2Off,
  Pencil,
  Power,
  RefreshCw,
  Stethoscope,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  Aviso,
  Campo,
  Cartao,
  Carregando,
  Erro,
  Modal,
  Pagina,
  Selo,
  Vazio,
  type Tom,
} from '@/components/base'
import {
  conectarProduto,
  definirPermissoes,
  definirUsinas,
  desvincular,
  editarCliente,
  obterCliente,
  permissoesDoCliente,
  regenerarSenha,
  testarConexao,
  type ClienteDetalhe as TipoCliente,
  type Produto,
  type ResultadoConexao,
  type SituacaoAcesso,
  type Vinculo,
} from '@/features/api'
import { CartaoNotificacoes } from '@/features/clientes/Notificacoes'
import { SenhaProvisoria } from '@/features/clientes/SenhaProvisoria'
import { ListaDeUsinas, useSelecaoUsinas } from '@/features/clientes/SeletorUsinas'
import { mensagemDeErro } from '@/lib/api'

const ACESSO: Record<SituacaoAcesso, { tom: Tom; rotulo: string }> = {
  nunca: { tom: 'sem-dados', rotulo: 'Sem acesso' },
  entregue: { tom: 'alerta', rotulo: 'Entregue, não usado' },
  usado: { tom: 'ok', rotulo: 'Em uso' },
}

/** A ordem em que os dois produtos aparecem na ficha. Fixa: a posição de cada um é
 *  memória muscular de quem abre dez fichas por dia. */
const PRODUTOS: Produto[] = ['meuwatt', 'meuplano']

const ROTULO_PRODUTO: Record<Produto, { nome: string; oQueTraz: string }> = {
  meuwatt: { nome: 'meuWatt', oQueTraz: 'geração, inversores e relatórios' },
  meuplano: { nome: 'meuPlano', oQueTraz: 'cronograma, ordens de serviço e assistente' },
}

export function DetalheCliente() {
  const { id } = useParams<{ id: string }>()
  const clienteId = Number(id)
  const qc = useQueryClient()

  const [erro, setErro] = useState('')
  const [senha, setSenha] = useState<string | null>(null)
  const [editandoUsinas, setEditandoUsinas] = useState(false)
  const [editandoDados, setEditandoDados] = useState(false)

  const { data: cliente, isLoading } = useQuery({
    queryKey: ['cliente', clienteId],
    queryFn: () => obterCliente(clienteId),
  })

  const recarregar = () => {
    qc.invalidateQueries({ queryKey: ['cliente', clienteId] })
    qc.invalidateQueries({ queryKey: ['clientes'] })
  }

  const novaSenha = useMutation({
    mutationFn: () => regenerarSenha(clienteId),
    onSuccess: (r) => {
      setSenha(r.senha_provisoria)
      recarregar()
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const alternarAtivo = useMutation({
    mutationFn: () => editarCliente(clienteId, { ativo: !cliente!.ativo }),
    onSuccess: recarregar,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  const removerVinculo = useMutation({
    mutationFn: (produto: Produto) => desvincular(clienteId, produto),
    onSuccess: recarregar,
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  if (isLoading) return <Carregando />
  if (!cliente) return <Erro>Cliente não encontrado.</Erro>

  const acesso = ACESSO[cliente.acesso]

  return (
    <Pagina
      titulo={cliente.nome}
      apoio={cliente.empresa ?? undefined}
      acao={
        <Link to={`/diagnostico?cliente=${cliente.id}`} className="btn-secundario">
          <Stethoscope size={15} />
          Diagnóstico
        </Link>
      }
    >
      <Link to="/clientes" className="inline-flex items-center gap-1.5 text-sm text-rotulo hover:text-forte mb-5">
        <ArrowLeft size={14} />
        Todos os clientes
      </Link>

      {erro ? <Erro className="mb-4">{erro}</Erro> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Cartao
          titulo="Conta"
          acao={
            <button onClick={() => setEditandoDados(true)} className="btn-fantasma">
              <Pencil size={13} />
              Editar
            </button>
          }
        >
          <dl className="px-5 pb-5 flex flex-col gap-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">Apelido</dt>
              <dd className="mono text-corpo truncate">{cliente.apelido}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">E-mail</dt>
              <dd className="mono text-corpo truncate">{cliente.email ?? '—'}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">Situação</dt>
              <dd>{cliente.ativo ? <Selo tom="ok">Ativo</Selo> : <Selo tom="sem-dados">Desativado</Selo>}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">Acesso</dt>
              <dd><Selo tom={acesso.tom}>{acesso.rotulo}</Selo></dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-rotulo">Último acesso</dt>
              <dd className="mono text-corpo">
                {cliente.ultimo_login
                  ? new Date(cliente.ultimo_login).toLocaleString('pt-BR', {
                      dateStyle: 'short',
                      timeStyle: 'short',
                    })
                  : 'nunca'}
              </dd>
            </div>
          </dl>

          <div className="px-5 pb-5 flex gap-2 flex-wrap">
            <button onClick={() => novaSenha.mutate()} className="btn-secundario" disabled={novaSenha.isPending}>
              <KeyRound size={15} />
              {novaSenha.isPending ? 'Gerando…' : 'Gerar nova senha'}
            </button>
            <button onClick={() => alternarAtivo.mutate()} className="btn-fantasma h-11 px-4 text-sm">
              <Power size={14} />
              {cliente.ativo ? 'Desativar' : 'Reativar'}
            </button>
          </div>
        </Cartao>

        <Cartao titulo="Contas nas plataformas">
          {/* Um bloco por PRODUTO, não por vínculo existente. É o que faltava: a lista
              antiga só desenhava o que já estava conectado, e conectar um produto depois
              do cadastro não tinha porta nenhuma — o cliente ficava preso com o que
              tivesse sido vinculado no dia em que nasceu. */}
          {PRODUTOS.map((produto, i) => (
            <BlocoProduto
              key={produto}
              produto={produto}
              clienteId={cliente.id}
              vinculo={cliente.vinculos.find((v) => v.produto === produto) ?? null}
              primeiro={i === 0}
              aoMudar={recarregar}
              aoDesconectar={() => removerVinculo.mutate(produto)}
            />
          ))}
        </Cartao>

        <Cartao
          titulo={`Usinas · ${cliente.usinas.length}`}
          className="lg:col-span-2"
          acao={
            <button onClick={() => setEditandoUsinas(true)} className="btn-fantasma">
              <Pencil size={13} />
              Alterar usinas
            </button>
          }
        >
          {cliente.usinas.length === 0 ? (
            <Vazio
              titulo="Nenhuma usina concedida"
              descricao="O cliente entra no aplicativo, mas não vê usina nenhuma até você conceder."
              acao={
                <button onClick={() => setEditandoUsinas(true)} className="btn-primario">
                  Conceder usinas
                </button>
              }
            />
          ) : (
            cliente.usinas.map((u, i) => (
              <div
                key={u.plant_link_id}
                className={`flex items-center gap-4 px-5 py-3.5 ${i ? 'border-t border-borda' : ''}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-forte">{u.nome}</p>
                  {u.cidade ? (
                    <p className="text-xs text-fraco">
                      {u.cidade}
                      {u.uf ? `, ${u.uf}` : ''}
                    </p>
                  ) : null}
                </div>
                {/* Estes selos falam da USINA, não do cliente: dizem em quais produtos
                    ela está casada na conciliação. Escritos antes só como "meuWatt" e
                    "meuPlano", ficavam a três centímetros do cartão de contas do cliente
                    e eram lidos como se fossem dele — a ficha parecia se contradizer,
                    anunciando "nenhuma plataforma vinculada" em cima de sete linhas
                    cheias de selos verdes. O verbo resolve: a usina É monitorada, ELA
                    tem manutenção. */}
                <div className="flex gap-1.5">
                  {u.tem_meuwatt ? <Selo tom="ok">monitorada</Selo> : null}
                  {u.tem_meuplano ? <Selo tom="ok">com manutenção</Selo> : null}
                  {!u.tem_meuwatt || !u.tem_meuplano ? (
                    <Selo tom="alerta">
                      {u.tem_meuwatt ? 'sem manutenção' : 'sem monitoramento'}
                    </Selo>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </Cartao>

        <CartaoPermissoes clienteId={cliente.id} nome={cliente.nome} />

        {/* A central de notificações fica ao lado das permissões de propósito: as duas
            respondem "o que ele recebe". As permissões valem para o aviso no aplicativo;
            esta vale para o WhatsApp, e é a única que pergunta DE QUAL USINA. */}
        <CartaoNotificacoes clienteId={cliente.id} nome={cliente.nome} />
      </div>

      {senha ? (
        <SenhaProvisoria
          nome={cliente.nome}
          apelido={cliente.apelido}
          senha={senha}
          aoFechar={() => setSenha(null)}
        />
      ) : null}

      {editandoUsinas ? (
        <ModalUsinas
          cliente={cliente}
          aoFechar={() => setEditandoUsinas(false)}
          aoSalvar={recarregar}
        />
      ) : null}

      {editandoDados ? (
        <ModalDados
          cliente={cliente}
          aoFechar={() => setEditandoDados(false)}
          aoSalvar={recarregar}
        />
      ) : null}
    </Pagina>
  )
}

/**
 * A conta do cliente num produto: o que está conectado, e como conectar.
 *
 * A tela inteira gira em torno de UM campo — o token que o cliente gerou no produto.
 * Não há campo de e-mail nem de id, e isso é deliberado: quem diz de quem é a conta é o
 * produto, ao receber o token. Deixar o gestor digitar essa parte reabriria o engano que
 * o desenho fechou — uma anotação podendo discordar da credencial gravada.
 *
 * Os dois estados que a tela separa, porque pedem correções diferentes:
 *
 * - **conectado** — o Gestão Solar lê o produto como ele, e o app mostra os dados dele;
 * - **login via Gestão Solar** — o produto aceita que ele entre lá com a senha daqui.
 *
 * O segundo depende do primeiro e pode falhar sozinho (chave de assinatura ausente,
 * produto sem a rota ainda). Quando falha, a conexão continua valendo e o aviso diz o quê.
 */
function BlocoProduto({
  produto,
  clienteId,
  vinculo,
  primeiro,
  aoMudar,
  aoDesconectar,
}: {
  produto: Produto
  clienteId: number
  vinculo: Vinculo | null
  primeiro: boolean
  aoMudar: () => void
  aoDesconectar: () => void
}) {
  const [colando, setColando] = useState(false)
  const [token, setToken] = useState('')
  const [resultado, setResultado] = useState<ResultadoConexao | null>(null)

  const conectar = useMutation({
    mutationFn: () => conectarProduto(clienteId, produto, token.trim()),
    onSuccess: (r) => {
      setResultado(r)
      if (r.ok) {
        // O token some da tela assim que serve. Ele não volta por GET nenhum, e deixá-lo
        // no campo só cria a chance de alguém achar que precisa guardá-lo em algum lugar.
        setToken('')
        setColando(false)
        aoMudar()
      }
    },
    onError: (e) => setResultado({ ok: false, detalhe: mensagemDeErro(e), vinculo: null, login_externo: false, aviso_login: null }),
  })

  const testar = useMutation({
    mutationFn: () => testarConexao(clienteId, produto),
    onSuccess: (r) => {
      setResultado(r)
      aoMudar()
    },
    onError: (e) => setResultado({ ok: false, detalhe: mensagemDeErro(e), vinculo: null, login_externo: false, aviso_login: null }),
  })

  const { nome, oQueTraz } = ROTULO_PRODUTO[produto]
  const conectado = Boolean(vinculo?.token_prefixo)

  return (
    <div className={`px-5 py-4 ${primeiro ? '' : 'border-t border-borda'}`}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-semibold text-forte">{nome}</p>
            {conectado ? (
              <Selo tom={vinculo!.estado === 'falhou' ? 'parado' : 'ok'}>
                {vinculo!.estado === 'falhou' ? 'com problema' : 'conectado'}
              </Selo>
            ) : (
              <Selo tom="sem-dados">não conectado</Selo>
            )}
            {conectado && vinculo!.login_externo ? (
              <Selo tom="ok">login via Gestão Solar</Selo>
            ) : null}
          </div>

          {conectado ? (
            <>
              <p className="mono text-xs text-fraco truncate mt-0.5">
                {vinculo!.nome ? `${vinculo!.nome} · ` : ''}
                {vinculo!.email ?? `id ${vinculo!.usuario_remoto_id}`}
              </p>
              <p className="mono text-xs text-fraco/70 mt-0.5">
                {vinculo!.token_prefixo}…
                {vinculo!.usinas_visiveis != null
                  ? ` · ${vinculo!.usinas_visiveis} usina(s) visíveis`
                  : ''}
              </p>
              {/* O login é a metade que pode faltar com a conexão inteira de pé. Dizer
                  isso aqui evita a pergunta "conectei, por que ele não entra?". */}
              {!vinculo!.login_externo ? (
                <p className="text-xs text-alerta mt-1">
                  Ele ainda não entra no {nome} com a senha do Gestão Solar.
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-xs text-fraco mt-0.5">
              Cole o token que ele gerou no {nome}. É de lá que vêm {oQueTraz}.
            </p>
          )}
        </div>

        <div className="flex gap-1.5 shrink-0">
          {conectado ? (
            <>
              <button
                onClick={() => testar.mutate()}
                className="btn-fantasma"
                disabled={testar.isPending}
                title="Conferir se o token ainda é aceito"
              >
                <RefreshCw size={13} />
                {testar.isPending ? 'Testando…' : 'Testar'}
              </button>
              <button onClick={() => setColando((v) => !v)} className="btn-fantasma">
                <KeyRound size={13} />
                Trocar
              </button>
              <button onClick={aoDesconectar} className="btn-fantasma" title="Apagar o vínculo e o token">
                <Link2Off size={13} />
                Desconectar
              </button>
            </>
          ) : (
            <button onClick={() => setColando((v) => !v)} className="btn-secundario">
              <Link2 size={14} />
              Conectar
            </button>
          )}
        </div>
      </div>

      {colando ? (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setResultado(null)
            conectar.mutate()
          }}
          className="mt-3 flex gap-2 items-end"
        >
          <div className="flex-1">
            <Campo
              rotulo={`Token do ${nome}`}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={produto === 'meuwatt' ? 'mw_pat_…' : 'mp_pat_…'}
              autoCapitalize="none"
              spellCheck={false}
              autoFocus
              nota={`Ele gera esse valor na própria conta do ${nome} e te envia. Aparece uma vez lá.`}
            />
          </div>
          <button
            type="submit"
            className="btn-primario"
            disabled={conectar.isPending || !token.trim()}
          >
            {conectar.isPending ? 'Conectando…' : 'Conectar'}
          </button>
        </form>
      ) : null}

      {resultado ? (
        <div className="mt-3 space-y-2">
          {resultado.ok ? (
            <div className="rounded-campo border border-ok/30 bg-ok/10 p-3 flex items-start gap-2">
              <Check size={15} className="text-ok shrink-0 mt-0.5" />
              <p className="text-xs text-corpo">{resultado.detalhe}</p>
            </div>
          ) : (
            <Erro>{resultado.detalhe}</Erro>
          )}
          {/* A conexão deu certo e o login não: dois desfechos, duas frases. Juntá-los
              faria o gestor achar que nada funcionou. */}
          {resultado.aviso_login ? <Aviso>{resultado.aviso_login}</Aviso> : null}
        </div>
      ) : null}
    </div>
  )
}

/** Mesma escolha do cadastro, reaproveitada — ver SeletorUsinas. */
function ModalUsinas({
  cliente,
  aoFechar,
  aoSalvar,
}: {
  cliente: TipoCliente
  aoFechar: () => void
  aoSalvar: () => void
}) {
  const [erro, setErro] = useState('')
  const selecao = useSelecaoUsinas(
    cliente.id,
    cliente.usinas.map((u) => u.plant_link_id),
  )

  const salvar = useMutation({
    mutationFn: () => definirUsinas(cliente.id, [...selecao.escolhidas]),
    onSuccess: () => {
      aoSalvar()
      aoFechar()
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Modal titulo="Usinas do cliente" aoFechar={aoFechar} largura="max-w-2xl">
      <p className="text-sm text-rotulo mb-4">
        Marque o que {cliente.nome} vê no aplicativo. Desmarcar tira do aplicativo dele na
        hora e libera a usina para outro cliente.
      </p>

      {erro ? (
        <div className="mb-4">
          <Erro>{erro}</Erro>
        </div>
      ) : null}

      <ListaDeUsinas {...selecao} />

      <div className="flex gap-2 mt-5">
        <button onClick={() => salvar.mutate()} className="btn-primario" disabled={salvar.isPending}>
          {salvar.isPending ? 'Salvando…' : 'Salvar usinas'}
        </button>
        <button onClick={aoFechar} className="btn-secundario">
          Cancelar
        </button>
      </div>
    </Modal>
  )
}


/**
 * Permissões do aplicativo.
 *
 * Fica no detalhe do cliente, ao lado das usinas, porque é a mesma decisão em duas
 * dimensões: as usinas dizem O QUE ele vê, as permissões dizem O QUE ele recebe. Separar
 * em outra página faria o gestor conceder uma e esquecer a outra.
 *
 * O estado é local enquanto ele mexe e só vai ao servidor no Salvar — assim marcar três
 * chaves é uma requisição, e não três, e ele pode desistir sem ter alterado nada.
 */
function CartaoPermissoes({ clienteId, nome }: { clienteId: number; nome: string }) {
  const qc = useQueryClient()
  const [erro, setErro] = useState('')
  const [rascunho, setRascunho] = useState<Set<string> | null>(null)

  const { data: itens, isLoading } = useQuery({
    queryKey: ['permissoes', clienteId],
    queryFn: () => permissoesDoCliente(clienteId),
  })

  // O rascunho nasce do servidor na primeira renderização com dados. Depois disso ele é
  // a verdade da tela — recalcular a cada render desfaria o clique do gestor.
  const concedidas =
    rascunho ??
    new Set((itens ?? []).filter((i) => i.concedida).map((i) => `${i.categoria}.${i.subcategoria}`))

  const sujo =
    rascunho !== null &&
    (itens ?? []).some(
      (i) => Boolean(i.concedida) !== concedidas.has(`${i.categoria}.${i.subcategoria}`),
    )

  const salvar = useMutation({
    mutationFn: () => definirPermissoes(clienteId, [...concedidas]),
    onSuccess: () => {
      setRascunho(null)
      setErro('')
      qc.invalidateQueries({ queryKey: ['permissoes', clienteId] })
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  function alternar(chave: string) {
    const proximo = new Set(concedidas)
    if (proximo.has(chave)) proximo.delete(chave)
    else proximo.add(chave)
    setRascunho(proximo)
  }

  return (
    <Cartao titulo={`Permissões · ${concedidas.size}`} className="lg:col-span-2">
      {isLoading ? (
        <p className="px-5 py-4 text-sm text-fraco">Carregando…</p>
      ) : (itens ?? []).length === 0 ? (
        <Vazio
          titulo="Nenhuma permissão disponível"
          descricao="O catálogo de permissões está vazio."
        />
      ) : (
        <>
          <p className="px-5 pt-4 text-sm text-rotulo">
            O que {nome} recebe no aplicativo. Sem marcar, ele não recebe nada — e o
            aparelho dele ainda precisa autorizar os avisos no Android.
          </p>

          {(itens ?? []).map((i, idx) => {
            const chave = `${i.categoria}.${i.subcategoria}`
            const ligada = concedidas.has(chave)
            return (
              <label
                key={chave}
                className={`flex items-start gap-4 px-5 py-3.5 cursor-pointer ${idx ? 'border-t border-borda' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={ligada}
                  onChange={() => alternar(chave)}
                  className="mt-1"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-forte">
                    {i.categoria_rotulo} · {i.rotulo}
                  </p>
                  <p className="text-xs text-fraco">{i.descricao}</p>
                </div>
              </label>
            )
          })}

          {erro ? (
            <div className="px-5 pb-3">
              <Erro>{erro}</Erro>
            </div>
          ) : null}

          <div className="flex gap-2 px-5 py-4 border-t border-borda">
            <button
              onClick={() => salvar.mutate()}
              className="btn-primario"
              disabled={!sujo || salvar.isPending}
            >
              {salvar.isPending ? 'Salvando…' : 'Salvar permissões'}
            </button>
            {sujo ? (
              <button onClick={() => setRascunho(null)} className="btn-secundario">
                Descartar
              </button>
            ) : null}
          </div>
        </>
      )}
    </Cartao>
  )
}

function ModalDados({
  cliente,
  aoFechar,
  aoSalvar,
}: {
  cliente: TipoCliente
  aoFechar: () => void
  aoSalvar: () => void
}) {
  const [nome, setNome] = useState(cliente.nome)
  const [empresa, setEmpresa] = useState(cliente.empresa ?? '')
  const [erro, setErro] = useState('')

  const salvar = useMutation({
    mutationFn: () => editarCliente(cliente.id, { nome, empresa: empresa || null }),
    onSuccess: () => {
      aoSalvar()
      aoFechar()
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Modal titulo="Dados do cliente" aoFechar={aoFechar}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setErro('')
          salvar.mutate()
        }}
        className="flex flex-col gap-4"
      >
        {erro ? <Erro>{erro}</Erro> : null}
        <Campo rotulo="Nome" value={nome} onChange={(e) => setNome(e.target.value)} required autoFocus />
        <Campo rotulo="Empresa" value={empresa} onChange={(e) => setEmpresa(e.target.value)} />
        <p className="text-xs text-fraco">
          O e-mail não muda: é com ele que o cliente entra, e trocar exigiria entregar acesso
          de novo.
        </p>
        <div className="flex gap-2">
          <button type="submit" className="btn-primario" disabled={salvar.isPending}>
            {salvar.isPending ? 'Salvando…' : 'Salvar'}
          </button>
          <button type="button" onClick={aoFechar} className="btn-secundario">
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  )
}
