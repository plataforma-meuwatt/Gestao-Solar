/**
 * Assistente.
 *
 * A única tela que ainda não tem o que mostrar, e diz isso. O chat vive no meuPlano
 * (`assistente_chat`), mas depende de duas coisas que não existem hoje: a chamada exige o
 * token **do usuário** naquele produto — o BFF tem um token de serviço —, e o
 * `_TETO_NIVEL_CLIENTE` limita o cliente a L1 lá, o que é a pendência registrada no
 * CLAUDE.md § 8.
 *
 * Enquanto for assim, esta tela não finge conversa. Uma caixa de texto que não responde
 * seria pior do que a ausência dela.
 */

import { EstadoVazio } from '@/components/base'
import { Tela } from '@/components/Tela'
import { useAuth } from '@/store/auth'

function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

export default function Assistente() {
  const usuario = useAuth((s) => s.usuario)

  return (
    <Tela titulo="Assistente" avatar={{ iniciais: iniciaisDe(usuario?.nome) }} paraTabBar>
      <EstadoVazio
        titulo="Ainda não disponível"
        descricao="O assistente responde perguntas sobre manutenção usando os dados do meuPlano. A ligação depende de uma liberação naquele sistema e será avisada aqui quando estiver pronta."
      />
    </Tela>
  )
}
