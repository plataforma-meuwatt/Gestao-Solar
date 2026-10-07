/**
 * O WhatsApp Business do técnico — a única tela do portão dele.
 *
 * O número conectado aqui é o que o help-desk do meuPlano passa a usar nas conversas dos
 * tickets deste técnico. A conexão é o **Embedded Signup** da Meta: um botão abre a janela
 * dela, a pessoa entra com o Facebook, escolhe a conta e o número, e volta. Nenhum token
 * passa pelas mãos de ninguém. Desenho em `docs/PLANO_WHATSAPP_TECNICOS.md`.
 *
 * **O `code` vive 30 segundos.** A janela devolve duas coisas por caminhos diferentes — o
 * `code` no callback do `FB.login` e os ids (WABA, número, evento) numa mensagem
 * `WA_EMBEDDED_SIGNUP` —, e a ordem entre elas não é garantida. Quem chegar primeiro
 * espera o outro, por pouco tempo, e os dois vão juntos ao servidor na hora.
 *
 * **A coexistência não se escolhe aqui.** Na versão 4 do Embedded Signup o `extras` é
 * vazio de propósito: oferecer "usar o número que já está no WhatsApp Business do celular"
 * é configuração do app na Meta, feita pelo administrador da plataforma. O que esta tela
 * faz é ler o evento que volta (`FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`) e mandar adiante.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Aviso, Cartao, Carregando, Erro, Pagina, Selo, Vazio } from '@/components/base'
import {
  conectarMeuWhatsapp,
  desconectarMeuWhatsapp,
  euTecnico,
  meuWhatsapp,
  type ConexaoWhatsappIn,
  type ContaWhatsapp,
  type MeuWhatsapp as Config,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

// ── o SDK da Meta ───────────────────────────────────────────────────────────

type RespostaDoLogin = { authResponse?: { code?: string } | null; status?: string }

declare global {
  interface Window {
    FB?: {
      init: (o: Record<string, unknown>) => void
      login: (cb: (r: RespostaDoLogin) => void, o: Record<string, unknown>) => void
    }
    fbAsyncInit?: () => void
  }
}

/** Carrega o SDK uma vez por página e o inicia com o app da PLATAFORMA. */
let carregando: Promise<void> | null = null
function carregarSdk(appId: string, versao: string): Promise<void> {
  if (window.FB) return Promise.resolve()
  carregando ??= new Promise((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB!.init({ appId, autoLogAppEvents: true, xfbml: true, version: versao })
      resolve()
    }
    const s = document.createElement('script')
    s.src = 'https://connect.facebook.net/en_US/sdk.js'
    s.async = true
    s.defer = true
    s.crossOrigin = 'anonymous'
    s.onerror = () => {
      carregando = null
      reject(new Error('Não deu para carregar a janela da Meta. Confira a internet e tente de novo.'))
    }
    document.body.appendChild(s)
  })
  return carregando
}

type Sessao = { waba_id?: string; phone_number_id?: string; business_id?: string; evento: string }

/**
 * Abre a janela e devolve o que o servidor precisa. Rejeita com a frase para a tela.
 *
 * Os dois retornos da Meta chegam por caminhos diferentes e em qualquer ordem; o prazo
 * de 10 s para o que faltar é folga sobre os 30 s de vida do `code`, nunca o contrário.
 */
function abrirJanela(cfg: Config): Promise<ConexaoWhatsappIn> {
  return new Promise((resolve, reject) => {
    let sessao: Sessao | null = null
    let code: string | null = null
    let prazo: ReturnType<typeof setTimeout> | null = null

    const encerrar = () => {
      window.removeEventListener('message', ouvir)
      if (prazo) clearTimeout(prazo)
    }
    const tentar = () => {
      if (!sessao || !code) return
      encerrar()
      if (sessao.evento === 'FINISH_ONLY_WABA' || !sessao.phone_number_id || !sessao.waba_id) {
        reject(new Error(
          'A conta foi criada, mas nenhum número foi escolhido. Abra de novo e escolha o número.',
        ))
        return
      }
      resolve({
        code,
        waba_id: sessao.waba_id,
        phone_number_id: sessao.phone_number_id,
        business_id: sessao.business_id ?? null,
        evento: sessao.evento,
      })
    }

    function ouvir(e: MessageEvent) {
      if (!e.origin.endsWith('facebook.com')) return
      let dados: { type?: string; event?: string; data?: Record<string, string> }
      try {
        dados = typeof e.data === 'string' ? JSON.parse(e.data) : e.data
      } catch {
        return
      }
      if (dados?.type !== 'WA_EMBEDDED_SIGNUP') return
      const evento = dados.event ?? ''
      if (evento === 'CANCEL') {
        encerrar()
        reject(new Error('A conexão foi cancelada antes do fim. Nada foi alterado.'))
        return
      }
      if (evento === 'ERROR') {
        encerrar()
        reject(new Error(`A Meta interrompeu a conexão: ${dados.data?.error_message ?? 'sem motivo informado'}.`))
        return
      }
      const d = dados.data ?? {}
      sessao = { waba_id: d.waba_id, phone_number_id: d.phone_number_id, business_id: d.business_id, evento }
      tentar()
    }

    window.addEventListener('message', ouvir)
    window.FB!.login(
      (r) => {
        if (!r.authResponse?.code) {
          encerrar()
          reject(new Error('A janela da Meta foi fechada sem autorizar. Nada foi alterado.'))
          return
        }
        code = r.authResponse.code
        prazo = setTimeout(() => {
          encerrar()
          reject(new Error('A Meta não disse qual número foi escolhido. Tente de novo.'))
        }, 10_000)
        tentar()
      },
      {
        config_id: cfg.config_id,
        response_type: 'code',
        override_default_response_type: true,
        extras: { setup: {} },
      },
    )
  })
}

// ── a tela ──────────────────────────────────────────────────────────────────

function quando(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export function MeuWhatsapp() {
  const qc = useQueryClient()
  const eu = useQuery({ queryKey: ['tecnico', 'eu'], queryFn: euTecnico })
  const wa = useQuery({ queryKey: ['tecnico', 'whatsapp'], queryFn: meuWhatsapp })

  const conectar = useMutation({
    mutationFn: async () => {
      const cfg = wa.data!
      if (!cfg.app_id || !cfg.config_id || !cfg.versao) {
        throw new Error('A conexão com a Meta não está completa na plataforma.')
      }
      await carregarSdk(cfg.app_id, cfg.versao)
      return conectarMeuWhatsapp(await abrirJanela(cfg))
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tecnico', 'whatsapp'] }),
  })

  const conectadas = (wa.data?.contas ?? []).filter((c) => c.estado === 'conectada')

  return (
    <Pagina titulo="Meu WhatsApp" apoio="O número por onde você conversa nos tickets do meuPlano">
      {wa.isLoading || eu.isLoading ? (
        <Carregando />
      ) : wa.error ? (
        <Erro>{mensagemDeErro(wa.error)}</Erro>
      ) : (
        <div className="grid gap-3 max-w-2xl">
          {eu.data && !eu.data.meuplano.vinculado ? (
            <Aviso>
              Sua conta do meuPlano ainda não está ligada a esta. Sem isso, o número conecta
              mas os tickets não sabem que ele é seu. Peça ao gerente da empresa para ligar
              em Usuários.
            </Aviso>
          ) : eu.data ? (
            <p className="text-sm text-rotulo">
              Conta do meuPlano: <span className="text-forte">{eu.data.meuplano.nome ?? eu.data.meuplano.email}</span>
            </p>
          ) : null}

          {!wa.data?.pronto ? (
            <Aviso>
              A conexão com a Meta ainda não está configurada na plataforma. Fale com quem
              administra o Gestão Solar.
            </Aviso>
          ) : null}

          {(wa.data?.contas ?? []).length === 0 ? (
            <Vazio
              titulo="Nenhum número conectado"
              descricao="Conecte o WhatsApp Business que você usa com fabricantes e clientes."
            />
          ) : (
            (wa.data?.contas ?? []).map((c) => <Conta key={c.phone_number_id} conta={c} />)
          )}

          {conectadas.length === 0 ? (
            <Cartao className="p-5">
              <p className="text-forte font-semibold">Conectar meu WhatsApp Business</p>
              <ol className="text-sm text-rotulo mt-2 grid gap-1 list-decimal pl-5">
                <li>Abre uma janela da Meta: entre com o seu Facebook.</li>
                <li>Escolha a conta e o número do seu WhatsApp Business.</li>
                <li>
                  Se o número já está no aplicativo do celular, escolha mantê-lo lá — ele continua
                  funcionando no celular, e as conversas aparecem nos dois lugares.
                </li>
              </ol>
              {conectar.error ? <Erro className="mt-3">{mensagemDeErro(conectar.error)}</Erro> : null}
              {conectar.data && !conectar.data.ok ? (
                <Erro className="mt-3">{conectar.data.detalhe}</Erro>
              ) : null}
              <div className="flex justify-end mt-4">
                <button
                  className="btn-primario"
                  onClick={() => conectar.mutate()}
                  disabled={!wa.data?.pronto || conectar.isPending}
                >
                  {conectar.isPending ? 'Conectando…' : 'Conectar'}
                </button>
              </div>
            </Cartao>
          ) : null}
        </div>
      )}
    </Pagina>
  )
}

function Conta({ conta }: { conta: ContaWhatsapp }) {
  const qc = useQueryClient()
  const [confirmando, setConfirmando] = useState(false)
  const desconectar = useMutation({
    mutationFn: () => desconectarMeuWhatsapp(conta.phone_number_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tecnico', 'whatsapp'] }),
  })
  const ligada = conta.estado === 'conectada'

  return (
    <Cartao className="p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-forte font-semibold">{conta.numero_exibicao ?? conta.phone_number_id}</p>
          <p className="text-sm text-rotulo mt-1">
            {conta.nome_verificado ?? 'sem nome verificado'}
            {' · '}
            {ligada ? `conectado em ${quando(conta.conectada_em)}` : `desconectado em ${quando(conta.desconectada_em)}`}
          </p>
        </div>
        <Selo tom={ligada ? 'ok' : 'alerta'}>{ligada ? 'Conectado' : 'Desconectado'}</Selo>
      </div>

      {conta.detalhe && (!ligada || conta.detalhe !== 'Conectado.') ? (
        ligada ? <Aviso>{conta.detalhe}</Aviso> : <Erro className="mt-3">{conta.detalhe}</Erro>
      ) : null}

      {ligada && conta.coexistencia ? (
        <p className="text-xs text-fraco mt-3">
          Este número continua no aplicativo do celular. Abra o WhatsApp Business no celular
          pelo menos a cada 14 dias: parado por mais tempo, a Meta desconecta o número daqui.
        </p>
      ) : null}

      {ligada ? (
        <div className="flex justify-end gap-2 mt-4">
          {confirmando ? (
            <>
              <span className="text-sm text-rotulo self-center">
                As conversas dos tickets param de passar por este número.
              </span>
              <button className="btn-secundario" onClick={() => setConfirmando(false)}>
                Cancelar
              </button>
              <button
                className="btn-primario"
                onClick={() => desconectar.mutate()}
                disabled={desconectar.isPending}
              >
                {desconectar.isPending ? 'Desconectando…' : 'Desconectar'}
              </button>
            </>
          ) : (
            <button className="btn-secundario" onClick={() => setConfirmando(true)}>
              Desconectar
            </button>
          )}
        </div>
      ) : null}
      {desconectar.error ? <Erro className="mt-3">{mensagemDeErro(desconectar.error)}</Erro> : null}
    </Cartao>
  )
}
