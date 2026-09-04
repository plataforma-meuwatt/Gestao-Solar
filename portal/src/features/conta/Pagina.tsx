/**
 * Minha conta — quem está logado, quais usinas enxergo e como troco minha senha.
 *
 * Três decisões que sustentam esta tela:
 *
 * **A senha provisória bloqueia o portal, e o bloqueio é explicado aqui.** O guarda de rota
 * (`App.tsx`) manda todo mundo com `trocar_senha` para cá; se esta tela mostrasse os cartões
 * normais, a pessoa clicaria no menu, seria trazida de volta e não entenderia por quê. Com a
 * marca de pé a página mostra SÓ a frase e o formulário — e a navegação se libera sozinha
 * quando o servidor confirma a troca.
 *
 * **O perfil é relido do servidor ao abrir** (`GET /auth/eu`). O que está no disco é a foto
 * do dia do login: entre uma abertura e outra o gestor pode ter concedido uma usina, tirado
 * outra ou marcado a senha como provisória. Numa tela cujo assunto É o cadastro, mostrar a
 * cópia velha seria contradizer o painel do gestor.
 *
 * **Nada de origem do dado.** O perfil traz os vínculos com os sistemas de onde a informação
 * vem, e eles ficam de fora de propósito: o cliente corporativo acessa UM portal e não tem de
 * saber por qual porta cada número entrou. Essa é a razão de este site existir.
 */

import { useEffect, useState, type FormEvent } from 'react'

import {
  AtualizadoAs,
  Aviso,
  Botao,
  CabecalhoCard,
  Cartao,
  CarregandoCartao,
  Esqueleto,
  Pagina,
  Tabela,
  Tela4Estados,
} from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { inteiro } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import { useAuth } from '@/store/auth'

import { lerPerfil, trocarSenha, type UsinaDaLista, type UsinasOut } from './api'

/** O mesmo mínimo que o BFF cobra. Conferir antes evita uma ida à rede para ouvir o óbvio. */
const MINIMO_SENHA = 8

export default function Conta() {
  const usuario = useAuth((s) => s.usuario)
  const sair = useAuth((s) => s.sair)
  const hidratar = useAuth((s) => s.hidratar)

  // Revalida o cadastro ao abrir a tela. `hidratar` engole falha de rede de propósito: quem
  // tem sessão válida continua vendo o perfil guardado, que é o certo até prova em contrário.
  useEffect(() => {
    void hidratar()
  }, [hidratar])

  // O aviso de sucesso mora AQUI, e não dentro do formulário, porque trocar uma senha
  // provisória muda o desenho da página inteira: o formulário sai da coluna do bloqueio e vai
  // para a grade normal, o React o remonta e o aviso morreria junto com o estado dele —
  // justamente no caso em que a confirmação mais importa.
  const [trocada, setTrocada] = useState(false)

  const leitura = useLeitura<UsinasOut>('plants')
  const usinas = leitura.dados?.usinas ?? null

  const acoes = (
    <Botao variante="secundario" onClick={sair}>
      Sair
    </Botao>
  )

  // Sem perfil não há o que desenhar — e isso só acontece no instante entre a sessão existir
  // e o store terminar de montar. O esqueleto evita o pisca de tela vazia.
  if (!usuario) {
    return (
      <Pagina titulo="Minha conta">
        <CarregandoCartao />
      </Pagina>
    )
  }

  if (usuario.trocar_senha) {
    return (
      <Pagina titulo="Minha conta" subtitulo="Troque a senha para liberar o portal" acoes={acoes}>
        <div className="max-w-xl space-y-4">
          <Aviso tom="alerta">
            A sua senha foi criada pelo gestor da conta e é provisória. Enquanto ela não for
            trocada, esta é a única tela disponível.
          </Aviso>
          <TrocaDeSenha aoTrocar={() => setTrocada(true)} />
        </div>
      </Pagina>
    )
  }

  return (
    <Pagina
      titulo="Minha conta"
      subtitulo="Quem está logado, quais usinas enxergo e como troco minha senha"
      acoes={acoes}
    >
      <div className="space-y-4">
        {trocada ? (
          <Aviso tom="ok">Senha trocada. Use a senha nova no próximo acesso.</Aviso>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-2">
          <Cartao>
            <CabecalhoCard rotulo="Seus dados" />
            <dl>
              <Dado rotulo="Nome" valor={usuario.nome} />
              <Dado rotulo="Usuário" valor={usuario.apelido} />
              <Dado rotulo="E-mail" valor={usuario.email} />
              <Dado rotulo="Empresa" valor={usuario.empresa} />
            </dl>
            <p className="mt-3 text-xs text-fraco">
              Para corrigir qualquer um destes dados, fale com o seu gestor de conta.
            </p>
          </Cartao>

          <TrocaDeSenha aoTrocar={() => setTrocada(true)} />
        </div>

        <Cartao>
          <CabecalhoCard
            rotulo="Usinas que você enxerga"
            direita={
              <span className="flex items-center gap-3">
                {/* A contagem é o número de linhas na tela. O perfil também traz um total, e
                    mostrar os dois criaria a chance de o portal se contradizer sobre um
                    número que o cliente confere de relance. */}
                {usinas ? <span>{`${inteiro(usinas.length)} ${usinas.length === 1 ? 'usina' : 'usinas'}`}</span> : null}
                <AtualizadoAs em={leitura.atualizadoEm} offlineDesde={leitura.offlineDesde} />
              </span>
            }
          />
          <Tela4Estados
            leitura={leitura}
            esqueleto={
              <div className="space-y-3">
                <Esqueleto altura={12} largura="60%" />
                <Esqueleto altura={12} largura="45%" />
                <Esqueleto altura={12} largura="52%" />
              </div>
            }
          >
            {(dados) => (
              <Tabela<UsinaDaLista>
                colunas={[
                  { titulo: 'Usina', celula: (u) => <span className="text-corpo">{u.nome}</span> },
                  { titulo: 'Cidade / UF', celula: (u) => <span className="text-fraco">{local(u)}</span> },
                ]}
                linhas={dados.usinas}
                chave={(u) => u.id}
                vazio={
                  <p className="py-2 text-sm text-fraco">
                    O seu gestor de conta ainda não liberou nenhuma usina para você. Assim que
                    ele liberar, elas aparecem aqui e no seletor do topo.
                  </p>
                }
              />
            )}
          </Tela4Estados>
        </Cartao>
      </div>
    </Pagina>
  )
}

/** "Porto Ferreira, SP" — e "—" quando o cadastro não tem nem cidade nem estado. */
function local(u: UsinaDaLista): string {
  const partes = [u.cidade, u.uf].filter((p): p is string => Boolean(p))
  return partes.length ? partes.join(', ') : '—'
}

function Dado({ rotulo, valor }: { rotulo: string; valor: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-borda-fraca py-2.5 last:border-0">
      <dt className="shrink-0 text-sm text-fraco">{rotulo}</dt>
      <dd className="min-w-0 truncate text-sm text-corpo">{valor ?? '—'}</dd>
    </div>
  )
}

/* ------------------------------------------------------------------ troca de senha */

/**
 * As três recusas do servidor são conferidas aqui ANTES do envio (senha atual em branco,
 * nova curta demais, nova igual à atual) e a quarta é só da tela: a repetição.
 *
 * A repetição existe porque o erro que ela evita é o mais caro de todos — quem digita a senha
 * nova errada e não percebe fica trancado para fora e precisa de senha provisória nova, pelo
 * gestor. O campo não substitui a régua do servidor: se a validação daqui divergir dele um
 * dia, quem manda é a frase que ele devolver.
 */
function TrocaDeSenha({ aoTrocar }: { aoTrocar: () => void }) {
  const usuario = useAuth((s) => s.usuario)
  const atualizarUsuario = useAuth((s) => s.atualizarUsuario)

  const [atual, setAtual] = useState('')
  const [nova, setNova] = useState('')
  const [repetida, setRepetida] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const problema = validar(atual, nova, repetida)
  const digitou = Boolean(atual || nova || repetida)

  async function enviar(evento: FormEvent) {
    evento.preventDefault()
    if (problema || salvando) return

    setSalvando(true)
    setErro(null)
    try {
      await trocarSenha(atual, nova)
      // 204 recebido: a senha mudou e a marca de provisória caiu no servidor. O perfil é
      // relido para a tela falar do estado real. Se ESSA leitura falhar (rede caindo entre
      // uma chamada e outra), a marca cai localmente mesmo assim — não é palpite, é a
      // consequência do 204 que acabou de chegar; deixá-la de pé prenderia a pessoa numa
      // tela de troca de senha que já foi trocada.
      try {
        atualizarUsuario(await lerPerfil())
      } catch {
        if (usuario) atualizarUsuario({ ...usuario, trocar_senha: false })
      }
      setAtual('')
      setNova('')
      setRepetida('')
      aoTrocar()
    } catch (falha) {
      setErro(mensagemDeErro(falha))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Cartao>
      <CabecalhoCard rotulo="Trocar senha" />
      <form onSubmit={enviar} className="space-y-3">
        <Campo
          rotulo="Senha atual"
          valor={atual}
          aoMudar={setAtual}
          autoComplete="current-password"
        />
        <Campo
          rotulo="Senha nova"
          valor={nova}
          aoMudar={setNova}
          autoComplete="new-password"
          nota={`Pelo menos ${MINIMO_SENHA} caracteres, diferente da atual.`}
        />
        <Campo
          rotulo="Repita a senha nova"
          valor={repetida}
          aoMudar={setRepetida}
          autoComplete="new-password"
        />

        {digitou && problema ? <p className="text-xs text-tom-alerta">{problema}</p> : null}
        {erro ? <Aviso tom="parado">{erro}</Aviso> : null}

        <div className="pt-1">
          <Botao tipo="submit" desabilitado={Boolean(problema) || salvando}>
            {salvando ? 'Trocando…' : 'Trocar senha'}
          </Botao>
        </div>
      </form>
    </Cartao>
  )
}

function validar(atual: string, nova: string, repetida: string): string | null {
  if (!atual) return 'Digite a sua senha atual.'
  if (nova.length < MINIMO_SENHA) return `A senha nova precisa de pelo menos ${MINIMO_SENHA} caracteres.`
  if (nova === atual) return 'A senha nova precisa ser diferente da atual.'
  if (repetida !== nova) return 'A repetição não confere com a senha nova.'
  return null
}

function Campo({
  rotulo,
  valor,
  aoMudar,
  autoComplete,
  nota,
}: {
  rotulo: string
  valor: string
  aoMudar: (v: string) => void
  autoComplete: string
  nota?: string
}) {
  // A nota fica FORA do `label` de propósito: dentro, ela entraria no nome acessível do
  // campo, e o leitor de tela (e o teste) passariam a chamá-lo de "Senha nova Pelo menos 8
  // caracteres…" — o rótulo de um campo é o nome dele, não a instrução.
  return (
    <div>
      <label className="block">
        <span className="rotulo-campo">{rotulo}</span>
        <input
          type="password"
          className="campo"
          value={valor}
          autoComplete={autoComplete}
          onChange={(e) => aoMudar(e.target.value)}
        />
      </label>
      {nota ? <p className="mt-1 text-xs text-fraco">{nota}</p> : null}
    </div>
  )
}
