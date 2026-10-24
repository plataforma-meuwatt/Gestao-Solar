/**
 * Quem é da empresa, e tudo o que o gerente faz com cada conta.
 *
 * A primeira versão era uma lista de leitura, e o dono resumiu o problema: *"só consigo
 * puxar as usinas da conta do gerente, mas não consigo atribuir aos usuários"*. As três
 * ações que faltavam estão aqui, na linha de cada pessoa:
 *
 * - **Usinas** — o que ela vê no aplicativo. É a concessão, e é ela que manda: o token
 *   diz com que credencial se lê, a concessão diz o que aparece.
 * - **Token** — opcional no aplicativo (sem ele o Gestão Solar lê com a credencial da
 *   EMPRESA) e OBRIGATÓRIO no assistente do WhatsApp: o bot só responde com o token da
 *   própria pessoa (regra do dono, 23/10/2026).
 * - **Senha e acesso** — redefinir e desativar.
 *
 * O gerente aparece na lista junto dos clientes, e é de propósito: ele também recebe
 * usinas (é assim que ele vê a carteira no aplicativo). O que não se oferece a ele é
 * desativar a si mesmo — ficaria sem acesso no mesmo instante, e a saída seria a
 * plataforma.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Link2, MessageCircle, Sun, UserCog, UserPlus } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio } from '@/components/base'
import {
  catalogoDeUsinas,
  conectarContaDoCliente,
  definirUsinasDoCliente,
  desconectarContaDoCliente,
  editarContaDaEmpresa,
  criarClienteDaEmpresa,
  usinasConcedidas,
  usuariosDetalhados,
  desligarDoMeuPlano,
  ligarAoMeuPlano,
  pessoasDoMeuPlano,
  type PessoaMeuPlano,
  type Produto,
  type ProdutoDoBot,
  type UsuarioDetalhado,
} from '@/features/api'
import { NOME_DO_PRODUTO, PAPEL, PARTES_DO_BOT, confirmaAtivacao, textoDoBot } from '@/features/rotulos'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

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
          descricao="Cadastre o primeiro em “Novo usuário”."
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

/** As caixinhas do assistente. Ligar exige celular e o token dela naquele produto; o que já
 *  está ligado sem token pode ser desligado. */
function CaixasDoBot({
  bot,
  produtos,
  temCelular,
  aoMudar,
}: {
  bot: Record<ProdutoDoBot, boolean>
  produtos: Produto[]
  temCelular: boolean
  aoMudar: (campo: ProdutoDoBot, valor: boolean) => void
}) {
  const faltam = [
    ...new Set(PARTES_DO_BOT.filter((b) => !produtos.includes(b.token)).map((b) => b.token)),
  ]
  return (
    <div>
      <p className="rotulo-campo">O assistente do WhatsApp responde a esta pessoa sobre</p>
      <div className="flex gap-4 flex-wrap mt-1.5">
        {PARTES_DO_BOT.map((b) => (
          <label key={b.campo} className="flex items-center gap-1.5 text-sm text-corpo">
            <input
              type="checkbox"
              checked={bot[b.campo]}
              disabled={!bot[b.campo] && (!temCelular || !produtos.includes(b.token))}
              onChange={(e) => aoMudar(b.campo, e.target.checked)}
            />
            {b.rotulo}
          </label>
        ))}
      </div>
      {!temCelular ? <p className="text-xs text-fraco mt-1">Cadastre o celular para liberar.</p> : null}
      {faltam.length ? (
        <p className="text-xs text-fraco mt-1">
          O assistente só responde com o token da própria pessoa. Falta o do{' '}
          {faltam.map((p) => NOME_DO_PRODUTO[p]).join(' e do ')} (botão Token).
        </p>
      ) : null}
    </div>
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
  const [cadastroAberto, setCadastroAberto] = useState(false)

  const editar = useMutation({
    mutationFn: (dados: Parameters<typeof editarContaDaEmpresa>[1]) =>
      editarContaDaEmpresa(usuario.id, dados),
    onSuccess: () => {
      setSenhaAberta(false)
      setSenha('')
      qc.invalidateQueries({ queryKey: ['empresa'] })
    },
  })

  return (
    <Cartao className="px-5 py-4">
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
                {usuario.perfil === 'cliente'
                  ? `${usuario.usinas} ${usuario.usinas === 1 ? 'usina' : 'usinas'} no app`
                  : usuario.perfil === 'tecnico'
                    ? 'entra só para o próprio WhatsApp'
                    : 'vê todas as usinas da empresa'}
              </span>
              <span className="flex items-center gap-1.5">
                <MessageCircle size={14} />
                {usuario.telefone
                  ? `${usuario.telefone} · assistente: ${textoDoBot(
                      PARTES_DO_BOT.filter((p) => usuario[p.campo]).map((p) => p.campo),
                      usuario.produtos,
                      true,
                    )}`
                  : 'sem celular'}
              </span>
              <span className="flex items-center gap-1.5">
                <UserCog size={14} />
                {usuario.meuplano ? `cadastro ligado a ${usuario.meuplano} no meuPlano` : 'cadastro só do Gestão Solar'}
              </span>
              <span className="flex items-center gap-1.5">
                <Link2 size={14} />
                {usuario.produtos.length
                  ? `token próprio: ${usuario.produtos
                      .map((p) => `${NOME_DO_PRODUTO[p]}${usuario.tokens_de[p] ? ` (de ${usuario.tokens_de[p]})` : ''}`)
                      .join(' · ')}`
                  : 'lê com a conta da empresa'}
              </span>
            </p>
            {usuario.sugestao_meuplano && usuario.sugestao_meuplano_id && !usuario.cuidada_por ? (
              <SugestaoMeuPlano
                usuarioId={usuario.id}
                pessoaId={usuario.sugestao_meuplano_id}
                pessoa={usuario.sugestao_meuplano}
              />
            ) : null}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Selo tom={usuario.ativo ? 'ok' : 'sem-dados'}>
            {usuario.ativo ? 'Ativo' : 'Inativo'}
          </Selo>
          {usuario.cuidada_por ? (
            // Também é de OUTRA empresa, que cuida da conta: daqui só se concedem as usinas
            // desta empresa. Senha, celular, token e bot são de lá.
            usuario.perfil === 'cliente' ? (
              <button className="btn-secundario" onClick={aoAbrirUsinas}>
                Usinas
              </button>
            ) : null
          ) : (
            <>
          {/* Gerente não recebe concessão: ele vê a carteira inteira da empresa por SER
              gerente. Oferecer o botão o punha a competir com os clientes pela mesma
              usina — a regra é "cada usina pertence a um dono só" —, e o salvar voltava
              como erro. Um botão que só sabe recusar é pior que botão nenhum. */}
          {usuario.perfil === 'cliente' ? (
            <button className="btn-secundario" onClick={aoAbrirUsinas}>
              Usinas
            </button>
          ) : null}
          <button className="btn-fantasma" onClick={aoAbrirTokens}>
            Token
          </button>
          <button className="btn-fantasma" onClick={() => setCadastroAberto(true)}>
            <UserCog size={13} />
            Cadastro
          </button>
          <button className="btn-fantasma" onClick={() => setSenhaAberta((v) => !v)}>
            <KeyRound size={13} />
            Senha
          </button>
          {!souEu ? (
            <button
              className="btn-fantasma"
              disabled={editar.isPending}
              onClick={() => confirmaAtivacao(usuario.nome, usuario.ativo) && editar.mutate({ ativo: !usuario.ativo })}
            >
              {usuario.ativo ? 'Desativar' : 'Reativar'}
            </button>
          ) : null}
            </>
          )}
        </div>
      </div>
      {usuario.cuidada_por ? (
        <p className="text-xs text-alerta mt-2">
          Também é da empresa {usuario.cuidada_por}, que cuida da conta (senha, celular, token e
          bot). Aqui você concede só as usinas da sua empresa.
        </p>
      ) : null}

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
      {cadastroAberto ? (
        <CadastroDoUsuario usuario={usuario} aoFechar={() => setCadastroAberto(false)} />
      ) : null}
    </Cartao>
  )
}

/** "Há <pessoa> no meuPlano com este e-mail" — o ligar sugerido, num clique (puxa nome,
 *  e-mail e celular de lá, e passam a valer nos dois). */
function SugestaoMeuPlano({ usuarioId, pessoaId, pessoa }: { usuarioId: number; pessoaId: number; pessoa: string }) {
  const qc = useQueryClient()
  const ligar = useMutation({
    mutationFn: () => ligarAoMeuPlano(usuarioId, pessoaId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresa'] }),
  })
  return (
    <div className="mt-2 flex items-center gap-2 flex-wrap text-xs text-rotulo">
      <span>
        No meuPlano da empresa há <b className="text-corpo">{pessoa}</b> com este e-mail.
      </span>
      <button className="btn-fantasma" disabled={ligar.isPending} onClick={() => ligar.mutate()}>
        {ligar.isPending ? 'Ligando…' : 'Ligar e puxar o cadastro'}
      </button>
      {ligar.error ? <span className="text-parado">{mensagemDeErro(ligar.error)}</span> : null}
    </div>
  )
}

/**
 * A pessoa do meuPlano, numa lista suspensa PESQUISÁVEL (nada de chips). Só oferece quem
 * ainda não está ligado a outra conta daqui.
 */
function EscolherPessoaMeuPlano({ aoEscolher }: { aoEscolher: (p: PessoaMeuPlano) => void }) {
  const [filtro, setFiltro] = useState('')
  const { data, error, isLoading } = useQuery({
    queryKey: ['empresa', 'meuplano-pessoas'],
    queryFn: pessoasDoMeuPlano,
    retry: false,
  })
  if (isLoading) return <Carregando texto="Lendo as pessoas do meuPlano…" />
  if (error) return <Erro>{mensagemDeErro(error)}</Erro>
  const f = filtro.trim().toLowerCase()
  const livres = (data ?? []).filter(
    (p) => !p.ligada_a && (!f || `${p.nome} ${p.email} ${p.telefone}`.toLowerCase().includes(f)),
  )
  return (
    <div className="grid gap-2">
      <input
        className="campo h-9 text-sm"
        placeholder="buscar por nome, e-mail ou telefone"
        value={filtro}
        onChange={(e) => setFiltro(e.target.value)}
      />
      <select
        className="campo text-sm"
        size={Math.min(6, Math.max(2, livres.length))}
        onChange={(e) => {
          const p = livres.find((x) => x.id === Number(e.target.value))
          if (p) aoEscolher(p)
        }}
      >
        {livres.map((p) => (
          <option key={p.id} value={p.id}>
            {[p.nome, p.email, p.telefone].filter(Boolean).join(' · ')}
          </option>
        ))}
      </select>
      {!livres.length ? <p className="text-xs text-fraco">Ninguém livre com esse filtro.</p> : null}
    </div>
  )
}

/**
 * O cadastro da pessoa: nome, e-mail, celular, o que o assistente responde e a ligação com o
 * meuPlano. Ligada, o que se grava aqui grava lá também (uma base só).
 */
function CadastroDoUsuario({ usuario, aoFechar }: { usuario: UsuarioDetalhado; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState(usuario.nome)
  const [email, setEmail] = useState(usuario.email ?? '')
  const [telefone, setTelefone] = useState(usuario.telefone ?? '')
  const [bot, setBot] = useState<Record<ProdutoDoBot, boolean>>({
    bot_meuplano: usuario.bot_meuplano,
    bot_meuwatt: usuario.bot_meuwatt,
    bot_helper: usuario.bot_helper,
  })
  const [ligadoA, setLigadoA] = useState(usuario.meuplano)
  const [ligando, setLigando] = useState(false)
  const [avisos, setAvisos] = useState<string[]>([])
  const atualizar = () => qc.invalidateQueries({ queryKey: ['empresa'] })

  const salvar = useMutation({
    mutationFn: () => {
      const temCelular = Boolean(telefone.trim())
      return editarContaDaEmpresa(usuario.id, {
        nome: nome.trim(),
        email: email.trim() || undefined,
        telefone: telefone.trim(),
        bot_meuplano: temCelular && bot.bot_meuplano,
        bot_meuwatt: temCelular && bot.bot_meuwatt,
        bot_helper: temCelular && bot.bot_helper,
      })
    },
    onSuccess: () => {
      atualizar()
      aoFechar()
    },
  })
  const ligar = useMutation({
    mutationFn: (p: PessoaMeuPlano) => ligarAoMeuPlano(usuario.id, p.id),
    onSuccess: (r) => {
      setNome(r.usuario.nome)
      setEmail(r.usuario.email ?? '')
      setTelefone(r.usuario.telefone ?? '')
      setLigadoA(r.usuario.meuplano)
      setAvisos(r.avisos)
      setLigando(false)
      atualizar()
    },
  })
  const desligar = useMutation({
    mutationFn: () => desligarDoMeuPlano(usuario.id),
    onSuccess: () => {
      setLigadoA(null)
      atualizar()
    },
  })

  return (
    <Modal titulo={`Cadastro de ${usuario.nome}`} aoFechar={aoFechar} largura="max-w-2xl">
      <div className="grid gap-4">
        <Cartao>
          {ligadoA ? (
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm text-corpo">
                Ligado a <b>{ligadoA}</b> no meuPlano — nome, e-mail e celular valem nos dois.
              </p>
              <button className="btn-fantasma" disabled={desligar.isPending} onClick={() => desligar.mutate()}>
                Desligar
              </button>
            </div>
          ) : ligando ? (
            <div className="grid gap-2">
              <p className="text-sm text-corpo">Escolha a pessoa no meuPlano — os dados de lá vêm para cá.</p>
              <EscolherPessoaMeuPlano aoEscolher={(p) => ligar.mutate(p)} />
            </div>
          ) : (
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm text-corpo">Cadastro só do Gestão Solar.</p>
              <button className="btn-secundario" onClick={() => setLigando(true)}>
                Ligar ao meuPlano
              </button>
            </div>
          )}
          {ligar.error ? <Erro className="mt-2">{mensagemDeErro(ligar.error)}</Erro> : null}
          {desligar.error ? <Erro className="mt-2">{mensagemDeErro(desligar.error)}</Erro> : null}
          {avisos.map((a) => (
            <p key={a} className="text-xs text-fraco mt-2">{a}</p>
          ))}
        </Cartao>

        <div className="grid sm:grid-cols-2 gap-3">
          <Campo rotulo="Nome" value={nome} onChange={(e) => setNome(e.target.value)} />
          <Campo rotulo="E-mail" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Campo
            rotulo="Celular (o assistente reconhece a pessoa por ele)"
            type="tel"
            placeholder="(16) 99999-8888"
            value={telefone}
            onChange={(e) => setTelefone(e.target.value)}
          />
        </div>

        <CaixasDoBot
          bot={bot}
          produtos={usuario.produtos}
          temCelular={Boolean(telefone.trim())}
          aoMudar={(campo, valor) => setBot((v) => ({ ...v, [campo]: valor }))}
        />

        {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>Cancelar</button>
          <button className="btn-primario" disabled={nome.trim().length < 2 || salvar.isPending} onClick={() => salvar.mutate()}>
            {salvar.isPending ? 'Salvando…' : ligadoA ? 'Salvar nos dois' : 'Salvar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/**
 * O que esta pessoa vê no aplicativo.
 *
 * Só usinas ligadas no app aparecem: uma desligada não pode ser concedida, e oferecê-la
 * produziria uma concessão que não mostra nada. A lista é completa — o que ficar
 * desmarcado é retirado dela.
 *
 * **Exportado porque a tela de Clientes tinha uma segunda cópia deste modal, e a cópia
 * apagava a concessão inteira no primeiro clique**: ela abria com tudo desmarcado e
 * gravava a lista vazia. Duas telas fazendo a mesma coisa é a divergência da casa; aqui
 * ela custou dado. O tipo é o mínimo que o modal usa, para servir às duas listas.
 */
export function UsinasDoUsuario({
  usuario,
  aoFechar,
}: {
  usuario: { id: number; nome: string; usinas: number }
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

          {/* A herdada entra na LISTA, marcada — não só num aviso.
              O aviso sozinho criou um beco: a tela mandava desmarcar uma usina que ela
              mesma não mostrava, porque a lista só traz as da empresa. Não havia caixa
              para desmarcar, e o salvar recusava para sempre. */}
          {herdadas.length ? (
            <div className="border border-alerta/30 bg-alerta/5 rounded-card p-3">
              <p className="text-sm text-alerta font-semibold">
                {herdadas.length === 1
                  ? 'Uma usina concedida antes desta empresa existir'
                  : `${herdadas.length} usinas concedidas antes desta empresa existir`}
              </p>
              <p className="text-xs text-rotulo mt-1">
                {herdadas.length === 1 ? 'Ela ainda não pertence' : 'Elas ainda não pertencem'} a
                nenhuma empresa. Desmarque abaixo para tirar desta pessoa, ou traga em
                “Usinas” para manter.
              </p>
            </div>
          ) : null}

          {!noApp.length && !herdadas.length ? (
            <p className="text-sm text-rotulo">
              Nenhuma usina ligada no aplicativo ainda. Traga e ligue em “Usinas”.
            </p>
          ) : (
            <ul className="grid gap-1 max-h-80 overflow-y-auto pr-1">
              {herdadas.map((h) => (
                <li key={`herdada-${h.plant_link_id}`}>
                  <label className="flex items-center gap-2.5 px-3 py-2 rounded-campo bg-alerta/5 hover:bg-superficie cursor-pointer">
                    <input
                      type="checkbox"
                      checked={escolhidas.includes(h.plant_link_id)}
                      onChange={() =>
                        setMarcadas(
                          escolhidas.includes(h.plant_link_id)
                            ? escolhidas.filter((x) => x !== h.plant_link_id)
                            : [...escolhidas, h.plant_link_id],
                        )
                      }
                    />
                    <span className="text-sm text-forte">{h.nome}</span>
                    <span className="text-xs text-alerta">não é da empresa</span>
                  </label>
                </li>
              ))}
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
 * O token pessoal desta pessoa em cada produto — opcional no aplicativo, OBRIGATÓRIO no
 * assistente do WhatsApp.
 *
 * Sem ele, o Gestão Solar lê os dados dela com a credencial da EMPRESA, e a concessão
 * decide o que aparece. É o caso comum: o dono de usina costuma não ter conta no meuWatt
 * nem no meuPlano. O bot, não: ele só responde com o token da própria pessoa.
 *
 * Com ele, a leitura passa a acontecer **como ela**: as usinas que ela enxergaria lá, pela
 * regra de lá — e o produto passa a aceitar que ela entre com a senha daqui.
 */
export function Tokens({ usuario: inicial, aoFechar }: { usuario: UsuarioDetalhado; aoFechar: () => void }) {
  const qc = useQueryClient()
  // A linha FRESCA: conectar ou desconectar atualiza a lista, e o modal tem de acompanhar.
  const { data: lista } = useQuery({ queryKey: ['empresa', 'usuarios-detalhados'], queryFn: usuariosDetalhados })
  const usuario = lista?.find((u) => u.id === inicial.id) ?? inicial
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
          No aplicativo o token é <strong>opcional</strong>: sem ele, os dados desta pessoa são
          lidos com a conta da <strong>empresa</strong>, e o que ela vê continua sendo o que você
          concedeu. O <strong>bot do WhatsApp</strong> só responde com o token próprio da pessoa — sem o
          do meuWatt, nada de geração nem helper; sem o do meuPlano, nada de manutenção.
        </Aviso>

        {usuario.produtos.length ? (
          <div className="grid gap-2">
            {usuario.produtos.map((p) => (
              <div key={p} className="flex items-center justify-between gap-2">
                <span className="text-sm text-forte">
                  Token do {NOME_DO_PRODUTO[p]}
                  {usuario.tokens_de[p] ? <span className="text-rotulo"> · de {usuario.tokens_de[p]}</span> : null}
                </span>
                <button
                  className="btn-fantasma"
                  disabled={desconectar.isPending}
                  onClick={() =>
                    window.confirm(
                      `Desconectar o token do ${NOME_DO_PRODUTO[p]} de ${usuario.nome}? O bot desta pessoa para de responder sobre ${p === 'meuwatt' ? 'geração e helper' : 'manutenção'} até colar outro.`,
                    ) && desconectar.mutate(p)
                  }
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
          <p className="rotulo-campo">Token gerado na conta da própria pessoa</p>
          <input
            className="campo mt-1"
            type="password"
            autoComplete="off"
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
  const [perfil, setPerfil] = useState<'cliente' | 'gestor_empresa' | 'tecnico'>('cliente')
  const [telefone, setTelefone] = useState('')
  const [origem, setOrigem] = useState<'zero' | 'meuplano'>('zero')
  const [pessoa, setPessoa] = useState<PessoaMeuPlano | null>(null)
  const [criado, setCriado] = useState<{ apelido: string; senha: string; avisos: string[] } | null>(null)

  const criar = useMutation({
    mutationFn: () =>
      criarClienteDaEmpresa({
        nome,
        apelido,
        email: email || null,
        perfil,
        telefone: telefone.trim() || null,
        mp_user_id: origem === 'meuplano' ? pessoa?.id ?? null : null,
      }),
    onSuccess: (r) => {
      setCriado({ apelido: r.apelido, senha: r.senha, avisos: r.avisos ?? [] })
      qc.invalidateQueries({ queryKey: ['empresa'] })
    },
  })

  if (criado) {
    return (
      <Modal titulo="Usuário criado" aoFechar={aoFechar}>
        <div className="grid gap-4">
          <Aviso>Anote agora: a senha não é guardada em texto e não dá para vê-la de novo.</Aviso>
          <Cartao className="p-4">
            <p className="text-sm text-rotulo">Entra com o apelido</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.apelido}</p>
            <p className="text-sm text-rotulo mt-4">Senha provisória</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.senha}</p>
          </Cartao>
          <p className="text-xs text-fraco">
            Entregue as duas juntas. O e-mail é só contato — quem autentica é o apelido.
          </p>
          {criado.avisos.map((a) => (
            <p key={a} className="text-xs text-fraco">{a}</p>
          ))}
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
            onChange={(e) => setPerfil(e.target.value as 'cliente' | 'gestor_empresa' | 'tecnico')}
          >
            <option value="cliente">Dono de usina — entra no aplicativo</option>
            <option value="gestor_empresa">Gerente — opera a empresa com você</option>
            <option value="tecnico">Técnico — conecta o WhatsApp dele aos tickets</option>
          </select>
          <p className="text-xs text-fraco mt-1.5">
            {perfil === 'cliente'
              ? 'Vê apenas as usinas que você conceder a ele.'
              : perfil === 'tecnico'
                ? 'Entra no painel só para conectar o WhatsApp Business dele. Depois, ligue a conta dele do meuPlano em Token — é ela que diz quais tickets são dele.'
                : 'Vê e opera tudo desta empresa, como você.'}
          </p>
        </div>

        <div>
          <p className="rotulo-campo">Cadastro</p>
          <div className="mt-1 flex gap-1">
            {(
              [
                ['zero', 'Do zero'],
                ['meuplano', 'Puxar do meuPlano'],
              ] as const
            ).map(([v, rotulo]) => (
              <button
                key={v}
                type="button"
                className={origem === v ? 'btn-secundario' : 'btn-fantasma'}
                onClick={() => setOrigem(v)}
              >
                {rotulo}
              </button>
            ))}
          </div>
          {origem === 'meuplano' ? (
            <div className="mt-2">
              <EscolherPessoaMeuPlano
                aoEscolher={(p) => {
                  setPessoa(p)
                  setNome(p.nome ?? '')
                  setEmail(p.email ?? '')
                  setTelefone(p.telefone ?? '')
                }}
              />
              {pessoa ? (
                <p className="text-xs text-fraco mt-1">
                  Nasce ligado a {pessoa.nome} no meuPlano: mudanças passam a valer nos dois.
                </p>
              ) : null}
            </div>
          ) : null}
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
        <div>
          <p className="rotulo-campo">Celular (opcional — o assistente do WhatsApp reconhece por ele)</p>
          <input
            className="campo mt-1"
            type="tel"
            placeholder="(16) 99999-8888"
            value={telefone}
            onChange={(e) => setTelefone(e.target.value)}
          />
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
            disabled={
              !nome.trim() || !apelido.trim() || criar.isPending || (origem === 'meuplano' && !pessoa)
            }
          >
            {criar.isPending ? 'Criando…' : 'Criar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
