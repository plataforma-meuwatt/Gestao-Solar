import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, KeyRound, Pencil, Power, Stethoscope } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
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
  definirPermissoes,
  editarCliente,
  obterCliente,
  permissoesDoCliente,
  regenerarSenha,
  type ClienteDetalhe as TipoCliente,
  type Produto,
  type SituacaoAcesso,
  type Vinculo,
} from '@/features/api'
import { CartaoNotificacoes } from '@/features/clientes/Notificacoes'
import { SenhaProvisoria } from '@/features/clientes/SenhaProvisoria'
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

  if (isLoading) return <Carregando />
  if (!cliente) return <Erro>Dono de usina não encontrado.</Erro>

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
      <Link to="/usuarios" className="inline-flex items-center gap-1.5 text-sm text-rotulo hover:text-forte mb-5">
        <ArrowLeft size={14} />
        Usuários
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
                      timeZone: 'America/Sao_Paulo',
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

        <Cartao titulo="Token próprio nas plataformas">
          {/* Um bloco por PRODUTO, não por vínculo existente. É o que faltava: a lista
              antiga só desenhava o que já estava conectado, e conectar um produto depois
              do cadastro não tinha porta nenhuma — o cliente ficava preso com o que
              tivesse sido vinculado no dia em que nasceu. */}
          {PRODUTOS.map((produto, i) => (
            <ContaNoProduto
              key={produto}
              produto={produto}
              vinculo={cliente.vinculos.find((v) => v.produto === produto) ?? null}
              primeiro={i === 0}
            />
          ))}
        </Cartao>

        {/* Só leitura no adm: quem concede usina é o gerente da empresa do dono, no oem-gs
            (o adm cuida das empresas e das contas; o dia a dia da carteira é da O&M). */}
        <Cartao titulo={`Usinas · ${cliente.usinas.length}`} className="lg:col-span-2">
          {cliente.usinas.length === 0 ? (
            <Vazio
              titulo="Nenhuma usina concedida"
              descricao={
                cliente.empresa
                  ? 'Ele entra no aplicativo, mas não vê usina nenhuma até o gerente da empresa dele conceder, no oem-gs.'
                  : 'Esta conta não é de empresa nenhuma: nenhum gerente a enxerga, e ninguém pode conceder usina a ela. Ponha numa empresa em Usuários → Empresas.'
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
 * A conta do dono num produto — só o ESTADO. O adm não tem token (regra do dono,
 * 23/10/2026): quem cola o token de cada pessoa é o gerente da empresa dela, no oem-gs.
 * Daqui se vê se ele tem o dele, de quem o produto disse que é, e se o login de lá aceita
 * a senha daqui.
 */
function ContaNoProduto({
  produto,
  vinculo,
  primeiro,
}: {
  produto: Produto
  vinculo: Vinculo | null
  primeiro: boolean
}) {
  const { nome } = ROTULO_PRODUTO[produto]
  const temToken = Boolean(vinculo?.tem_token)

  return (
    <div className={`px-5 py-4 ${primeiro ? '' : 'border-t border-borda'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-sm font-semibold text-forte">{nome}</p>
        {temToken ? (
          <Selo tom={vinculo!.estado === 'falhou' ? 'parado' : 'ok'}>
            {vinculo!.estado === 'falhou' ? 'token dele com problema' : 'tem o token dele'}
          </Selo>
        ) : (
          <Selo tom="sem-dados">sem token próprio</Selo>
        )}
        {temToken && vinculo!.login_externo ? <Selo tom="ok">login via Gestão Solar</Selo> : null}
      </div>
      {vinculo ? (
        <p className="mono text-xs text-fraco truncate mt-0.5">
          {vinculo.nome ? `${vinculo.nome} · ` : ''}
          {vinculo.email ?? `id ${vinculo.usuario_remoto_id}`}
        </p>
      ) : null}
      <p className="text-xs text-fraco mt-1">
        {temToken
          ? 'O aplicativo e o bot do WhatsApp leem com a conta dele.'
          : 'O aplicativo lê com a conta da empresa; esta parte do bot fica parada.'}{' '}
        Quem cola o token é o gerente da empresa, no oem-gs.
      </p>
    </div>
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
  const [erro, setErro] = useState('')

  const salvar = useMutation({
    mutationFn: () => editarCliente(cliente.id, { nome }),
    onSuccess: () => {
      aoSalvar()
      aoFechar()
    },
    onError: (e) => setErro(mensagemDeErro(e)),
  })

  return (
    <Modal titulo="Dados do dono de usina" aoFechar={aoFechar}>
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
        <p className="text-xs text-fraco">
          A empresa dele se muda em Usuários → Empresas (uma pessoa pode estar em mais de uma).
          E-mail e celular, o gerente da empresa edita no oem-gs — ligados ao meuPlano, valem
          nos dois.
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
