/**
 * Bot do WhatsApp — onde o gerente da O&M liga o assistente para cada pessoa da empresa.
 *
 * Pedido do dono: o gerente "libera o bot (meuPlano, meuWatt e helper, um, dois ou todos),
 * coloca os tokens dos usuários e o número de celular". Tudo numa linha por pessoa:
 *
 * - o CELULAR é como o bot reconhece quem escreveu;
 * - o TOKEN é o da própria pessoa (regra do dono, 23/10/2026: cada um usa o bot com o SEU
 *   token — nunca o da empresa): sem o do meuWatt não há geração, sem o do meuPlano não há
 *   manutenção;
 * - as CAIXAS dizem sobre o que o bot responde a ela. Ligar só manda a caixa: não regrava
 *   o cadastro (nem no meuPlano), então um meuPlano fora do ar não impede ligar o bot;
 * - a SENHA DE ATUAÇÃO (pedido do dono, 24/10/2026): o bot a pede antes de qualquer ação —
 *   ligar, desligar, gravar, criar OS. Ler não pede. Sem ela, o bot só lê.
 *
 * Embaixo, as últimas mensagens das pessoas da empresa — é aqui que o gerente vê por que
 * alguém ficou sem resposta.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Lock, MessageCircle } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio, type Tom } from '@/components/base'
import {
  botOuvindo,
  editarContaDaEmpresa,
  logDoBotDaEmpresa,
  usuariosDetalhados,
  type ProdutoDoBot,
  type UsuarioDetalhado,
} from '@/features/api'
import { LinhaDoLog } from '@/features/bot/LogDoBot'
import { Tokens } from '@/features/empresa/Usuarios'
import { NOME_DO_PRODUTO, PAPEL, PARTES_DO_BOT, quando } from '@/features/rotulos'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

export function BotDaEmpresa() {
  const empresa = useAuth((s) => s.empresa)
  const { data, isLoading, error } = useQuery({
    queryKey: ['empresa', 'usuarios-detalhados'],
    queryFn: usuariosDetalhados,
  })
  const { data: log, isLoading: carregandoLog, error: erroLog } = useQuery({
    queryKey: ['empresa', 'log-do-bot'],
    queryFn: logDoBotDaEmpresa,
  })
  const { data: canal } = useQuery({ queryKey: ['empresa', 'bot-ouvindo'], queryFn: botOuvindo, refetchInterval: 60_000 })
  const [tokensDe, setTokensDe] = useState<UsuarioDetalhado | null>(null)
  const [celularDe, setCelularDe] = useState<UsuarioDetalhado | null>(null)
  const [senhaDe, setSenhaDe] = useState<UsuarioDetalhado | null>(null)

  const daqui = (data ?? []).filter((u) => u.cuidada_por === null)
  const deOutra = (data ?? []).filter((u) => u.cuidada_por !== null)

  return (
    <Pagina
      titulo="Bot do WhatsApp"
      apoio={`Quem da ${empresa ?? 'sua empresa'} fala com o assistente do WhatsApp, e sobre o quê. O bot reconhece a pessoa pelo celular e responde só com o token dela.`}
    >
      <div className="mb-4">
        <Aviso>
          Regra: cada pessoa usa o bot com o <strong>token dela</strong> — nunca o da empresa.
          Geração precisa do token do meuWatt dela; manutenção, do token do meuPlano dela. Sem o
          celular, o bot não sabe quem está escrevendo. <strong>Ação</strong> (ligar, desligar,
          gravar, criar OS) só roda com a <strong>senha de atuação</strong> da pessoa; ler não pede
          senha.
        </Aviso>
      </div>

      {canal ? (
        <div className="flex items-center gap-3 flex-wrap mb-2">
          <Selo tom={canal.ouvindo ? 'ok' : 'parado'}>{canal.ouvindo ? 'Bot ouvindo' : 'Bot NÃO está ouvindo'}</Selo>
          <span className={`text-sm ${canal.ouvindo ? 'text-rotulo' : 'text-parado'}`}>{canal.resumo}</span>
        </div>
      ) : null}
      {log?.length ? (
        <p className="text-xs text-fraco mb-3">
          Última resposta do bot a alguém da empresa:{' '}
          {quando(log.find((r) => r.resultado === 'respondeu')?.em ?? null)} · última mensagem recebida:{' '}
          {quando(log[0].em)}
        </p>
      ) : null}

      <Cartao titulo="Pessoas da empresa">
        {isLoading ? (
          <Carregando />
        ) : error ? (
          <div className="px-5 pb-5">
            <Erro>{mensagemDeErro(error)}</Erro>
          </div>
        ) : !daqui.length ? (
          <Vazio titulo="Ninguém na empresa ainda" descricao="Cadastre as pessoas em Usuários." />
        ) : (
          daqui.map((u, i) => (
            <LinhaDoBot
              key={u.id}
              usuario={u}
              primeiro={i === 0}
              aoAbrirTokens={() => setTokensDe(u)}
              aoAbrirCelular={() => setCelularDe(u)}
              aoAbrirSenha={() => setSenhaDe(u)}
            />
          ))
        )}
        {deOutra.length ? (
          <p className="px-5 py-3 border-t border-borda text-xs text-fraco">
            Também da empresa, cuidados por outra (o bot deles é configurado lá):{' '}
            {deOutra.map((u) => `${u.nome} (${u.cuidada_por})`).join(', ')}.
          </p>
        ) : null}
      </Cartao>

      <div className="mt-5">
        <Cartao titulo="Últimas mensagens ao bot">
          {carregandoLog ? (
            <Carregando />
          ) : erroLog ? (
            <div className="px-5 pb-5">
              <Erro>{mensagemDeErro(erroLog)}</Erro>
            </div>
          ) : !log?.length ? (
            <Vazio titulo="Nenhuma mensagem ainda" descricao="O que as pessoas da empresa mandarem ao bot aparece aqui." />
          ) : (
            log.slice(0, 30).map((r, i) => <LinhaDoLog key={r.id} registro={r} primeiro={i === 0} />)
          )}
        </Cartao>
      </div>

      {tokensDe ? <Tokens usuario={tokensDe} aoFechar={() => setTokensDe(null)} /> : null}
      {celularDe ? <Celular usuario={celularDe} aoFechar={() => setCelularDe(null)} /> : null}
      {senhaDe ? <SenhaDeAtuacao usuario={senhaDe} aoFechar={() => setSenhaDe(null)} /> : null}
    </Pagina>
  )
}

/** O que o bot faz de fato com esta pessoa, numa palavra e num tom. */
function situacao(u: UsuarioDetalhado): { tom: Tom; rotulo: string } {
  const liberadas = PARTES_DO_BOT.filter((p) => u[p.campo])
  if (!liberadas.length) return { tom: 'sem-dados', rotulo: 'Desligado' }
  if (!u.telefone) return { tom: 'alerta', rotulo: 'Parado: sem celular' }
  const respondendo = liberadas.filter((p) => u.produtos.includes(p.token))
  if (!respondendo.length) return { tom: 'alerta', rotulo: 'Parado: falta o token dela' }
  if (respondendo.length < liberadas.length) return { tom: 'alerta', rotulo: 'Em parte: falta um token' }
  return { tom: 'ok', rotulo: 'Respondendo' }
}

function LinhaDoBot({
  usuario: u,
  primeiro,
  aoAbrirTokens,
  aoAbrirCelular,
  aoAbrirSenha,
}: {
  usuario: UsuarioDetalhado
  primeiro: boolean
  aoAbrirTokens: () => void
  aoAbrirCelular: () => void
  aoAbrirSenha: () => void
}) {
  const qc = useQueryClient()
  const mudar = useMutation({
    mutationFn: (dados: Partial<Record<ProdutoDoBot, boolean>>) => editarContaDaEmpresa(u.id, dados),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresa'] }),
  })
  const sit = situacao(u)

  return (
    <div className={`px-5 py-4 ${primeiro ? '' : 'border-t border-borda'}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="text-forte font-semibold">
            {u.nome}
            <span className="mono text-xs text-fraco font-normal ml-2">{u.apelido}</span>
          </p>
          <p className="text-sm text-rotulo mt-0.5">{PAPEL[u.perfil] ?? u.perfil}</p>
        </div>
        <Selo tom={sit.tom}>{sit.rotulo}</Selo>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr] text-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <MessageCircle size={14} className="text-rotulo" />
          <span className={u.telefone ? 'text-corpo' : 'text-alerta'}>{u.telefone ?? 'sem celular'}</span>
          <button className="btn-fantasma" onClick={aoAbrirCelular}>
            {u.telefone ? 'Trocar celular' : 'Pôr celular'}
          </button>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <KeyRound size={14} className="text-rotulo" />
          {(['meuwatt', 'meuplano'] as const).map((p) => (
            <span key={p} className={u.produtos.includes(p) ? 'text-ok' : 'text-alerta'}>
              {NOME_DO_PRODUTO[p]} {u.produtos.includes(p) ? `✓${u.tokens_de[p] ? ` (${u.tokens_de[p]})` : ''}` : 'falta'}
            </span>
          ))}
          <button className="btn-fantasma" onClick={aoAbrirTokens}>
            Token
          </button>
        </div>
      </div>

      <div className="mt-3 flex gap-x-5 gap-y-2 flex-wrap">
        {PARTES_DO_BOT.map((p) => {
          const ligado = u[p.campo]
          const falta = !u.telefone ? 'o celular' : !u.produtos.includes(p.token) ? `o token do ${NOME_DO_PRODUTO[p.token]} dela` : null
          const travado = !ligado && falta !== null
          return (
            <label
              key={p.campo}
              className={`flex items-center gap-2 text-sm ${travado ? 'text-fraco' : 'text-corpo cursor-pointer'}`}
              title={falta ? `Falta ${falta}.` : undefined}
            >
              <input
                type="checkbox"
                checked={ligado}
                disabled={travado || mudar.isPending}
                onChange={(e) => mudar.mutate({ [p.campo]: e.target.checked })}
              />
              {p.rotulo}
              {!ligado && falta ? <span className="text-[11px] text-fraco">(falta {falta})</span> : null}
            </label>
          )
        })}
      </div>
      <div className="mt-3 flex items-center gap-2 flex-wrap text-sm">
        <Lock size={14} className="text-rotulo" />
        <span className={u.tem_senha_atuacao ? 'text-ok' : 'text-alerta'}>
          {u.tem_senha_atuacao ? 'Senha de atuação definida' : 'Sem senha de atuação — o bot só lê'}
        </span>
        <button className="btn-fantasma" onClick={aoAbrirSenha}>
          {u.tem_senha_atuacao ? 'Trocar senha' : 'Definir senha'}
        </button>
      </div>
      {mudar.error ? <Erro className="mt-2">{mensagemDeErro(mudar.error)}</Erro> : null}
    </div>
  )
}

/** A senha de atuação: o bot a pede antes de qualquer ação. Só números — é digitada no
 *  celular —, e a de login nunca serve: ela não deve ser escrita no WhatsApp. */
function SenhaDeAtuacao({ usuario, aoFechar }: { usuario: UsuarioDetalhado; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [senha, setSenha] = useState('')
  const [repetida, setRepetida] = useState('')
  const diferentes = repetida.length > 0 && senha !== repetida
  const salvar = useMutation({
    mutationFn: () => editarContaDaEmpresa(usuario.id, { senha_atuacao: senha }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresa'] })
      aoFechar()
    },
  })
  return (
    <Modal titulo={`Senha de atuação de ${usuario.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Aviso>
          O bot pede esta senha antes de <strong>ligar, desligar, gravar</strong> ou criar algo
          (helper e meuPlano). Ler não pede. Só números, de 4 a 8 — nada de sequência nem número
          repetido. Entregue à pessoa como a senha provisória: ela não aparece de novo.
        </Aviso>
        <Campo
          rotulo="Senha de atuação"
          type="password"
          inputMode="numeric"
          autoComplete="new-password"
          maxLength={8}
          value={senha}
          onChange={(e) => setSenha(e.target.value.replace(/\D/g, ''))}
          autoFocus
        />
        <Campo
          rotulo="Repita a senha"
          type="password"
          inputMode="numeric"
          autoComplete="new-password"
          maxLength={8}
          value={repetida}
          onChange={(e) => setRepetida(e.target.value.replace(/\D/g, ''))}
          nota={diferentes ? 'As duas não batem.' : undefined}
        />
        {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            className="btn-primario"
            disabled={salvar.isPending || senha.length < 4 || senha !== repetida}
            onClick={() => salvar.mutate()}
          >
            {salvar.isPending ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** O celular — como o bot reconhece a pessoa. Ligado ao meuPlano, vale nos dois. Vazio apaga
 *  o celular e desliga o bot dela. */
function Celular({ usuario, aoFechar }: { usuario: UsuarioDetalhado; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [telefone, setTelefone] = useState(usuario.telefone ?? '')
  const salvar = useMutation({
    mutationFn: () => editarContaDaEmpresa(usuario.id, { telefone: telefone.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresa'] })
      aoFechar()
    },
  })
  return (
    <Modal titulo={`Celular de ${usuario.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Campo
          rotulo="Celular (o bot reconhece a pessoa por ele)"
          type="tel"
          placeholder="(16) 99999-8888"
          value={telefone}
          onChange={(e) => setTelefone(e.target.value)}
          nota={
            usuario.meuplano
              ? `Ligado a ${usuario.meuplano} no meuPlano: grava lá também. Vazio apaga e desliga o bot dela.`
              : 'Vazio apaga o celular e desliga o bot dela.'
          }
          autoFocus
        />
        {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button className="btn-primario" disabled={salvar.isPending} onClick={() => salvar.mutate()}>
            {salvar.isPending ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
