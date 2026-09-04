/**
 * Leitura em 4 estados: a tela abre com o que já se sabia e se corrige quando a rede
 * responde. Porte de `app/src/lib/cache.ts` (`fetchWithCache`) para o navegador.
 *
 * Os quatro estados que toda tela desenha saem daqui:
 * - **carregando** — só enquanto não há absolutamente nada (nem cache): o skeleton;
 * - **erro** — só sem cache e sem resposta;
 * - **offline** — há cache e a rede falhou: a tela mostra o cache com o selo
 *   "Sem conexão — mostrando dados de HH:MM" (`offlineDesde`);
 * - **atualizado às** — a hora da última leitura boa (`atualizadoEm`), para o rodapé.
 *
 * **`401` e `403` nunca são mascarados.** Nos dois casos o cache é apagado e o erro sobe
 * inteiro. Servir cache numa sessão expirada mostraria a usina de quem já não tem direito
 * a ela, e o pior é que pareceria funcionando — é a diferença entre uma tela velha e um
 * vazamento.
 *
 * **A conta está no nome da chave** (`leitura:u{id}:{chave}`). O logout apaga tudo, mas
 * isso não basta: se `sair()` falhar no meio, o cache de uma conta ficaria legível pela
 * seguinte. Com a conta na chave, ler o cache alheio deixa de ser possível por
 * construção — o caso real é a mesma pessoa com conta de gestor e conta de dono no mesmo
 * computador.
 */

import { useQuery, type QueryKey } from '@tanstack/react-query'
import axios from 'axios'
import { useCallback, useState } from 'react'

import { api, mensagemDeErro } from '@/lib/api'
import { hora } from '@/lib/format'

type Envelope<T> = { dados: T; gravadoEm: string }

let donoDoCache = 'anonimo'

export function identificarCache(usuarioId: number | null): void {
  donoDoCache = usuarioId === null ? 'anonimo' : `u${usuarioId}`
}

const chaveDe = (chave: string) => `leitura:${donoDoCache}:${chave}`

export function lerCache<T>(chave: string): Envelope<T> | null {
  try {
    const cru = localStorage.getItem(chaveDe(chave))
    return cru ? (JSON.parse(cru) as Envelope<T>) : null
  } catch {
    // Sem cache, JSON corrompido ou `localStorage` bloqueado dão no mesmo: não há o que
    // mostrar, e a tela cai no caminho de carregamento normal.
    return null
  }
}

export function gravarCache<T>(chave: string, dados: T): void {
  const envelope: Envelope<T> = { dados, gravadoEm: new Date().toISOString() }
  try {
    localStorage.setItem(chaveDe(chave), JSON.stringify(envelope))
  } catch {
    // Cota estourada não pode derrubar uma tela que já tem o dado na mão.
  }
}

export function apagarCache(chave: string): void {
  try {
    localStorage.removeItem(chaveDe(chave))
  } catch {
    /* idem */
  }
}

/** Apaga tudo o que foi lido, de qualquer conta. Chamado no logout. */
export function limparCache(): void {
  try {
    const chaves = Object.keys(localStorage)
    for (const k of chaves) {
      if (k.startsWith('leitura:')) localStorage.removeItem(k)
    }
  } catch {
    // Falhar aqui não pode impedir o logout: sair tem de funcionar sempre.
  }
}

const ehSessao = (erro: unknown) =>
  axios.isAxiosError(erro) && (erro.response?.status === 401 || erro.response?.status === 403)

/** O status HTTP da recusa. Rede que não chegou ao servidor não tem status — é `null`. */
const statusDe = (erro: unknown): number | null =>
  axios.isAxiosError(erro) ? (erro.response?.status ?? null) : null

export type Leitura<T> = {
  dados: T | null
  /** Só enquanto não há absolutamente nada para desenhar — o skeleton. */
  carregando: boolean
  /** Preenchido quando não há nem cache nem resposta. Com cache na tela, vira a faixa. */
  erro: string | null
  /**
   * O status HTTP da recusa; `null` quando deu certo ou quando a rede nem chegou ao servidor.
   *
   * Existe por causa de uma distinção que várias telas precisam fazer e nenhuma conseguia:
   * **"não é sua / não existe" (404) não é "a rede caiu"**. A primeira é um estado vazio com
   * o caminho de volta — insistir nunca vai abrir aquela porta; a segunda é um erro com
   * "Tentar de novo". Sem o status, três telas (Usina, OS e Pendências) reconheciam o 404
   * pela FRASE que o BFF escreve, e ficavam penduradas na prosa dele: acrescentar um ponto
   * final a "Ordem de serviço não encontrada." faria a tela cair no erro genérico, sem nada
   * quebrar e sem ninguém notar.
   */
  status: number | null
  /** `HH:MM` da gravação, quando o que está na tela é cache e a rede falhou. */
  offlineDesde: string | undefined
  /** `HH:MM` da última leitura boa (rede ou cache) — o "atualizado às" do rodapé. */
  atualizadoEm: string | undefined
  atualizando: boolean
  recarregar: () => void
}

/**
 * A leitura de uma tela, cache primeiro.
 *
 * ```ts
 * const { dados, carregando, erro, offlineDesde } = useLeitura<UsinasOut>('plants')
 * ```
 *
 * `chave` é o caminho no BFF sem `/api/v1/`, e serve de nome no cache e de `queryKey`.
 */
export function useLeitura<T>(
  chave: string,
  opcoes: {
    caminho?: string
    ativo?: boolean
    queryKey?: QueryKey
    /**
     * Prazo em milissegundos, quando o padrão de 30 s não serve. A ficha coletiva e o
     * relatório de manutenção passam disso no BFF; prazo é por chamada porque subir o
     * padrão faria toda tela ficar pendurada quando a rede cair de verdade.
     */
    prazoMs?: number
  } = {},
): Leitura<T> {
  const caminho = opcoes.caminho ?? `/api/v1/${chave}`
  const ativo = opcoes.ativo ?? true

  // O cache é lido de forma síncrona no primeiro render — sem o "piscar de vazio" que o
  // app tem de tratar por ler do disco. Quando a chave muda (outra usina, outro mês), o
  // envelope é trocado no próprio render, antes de qualquer efeito.
  const [disco, setDisco] = useState<{ chave: string; envelope: Envelope<T> | null }>(() => ({
    chave,
    envelope: lerCache<T>(chave),
  }))
  if (disco.chave !== chave) setDisco({ chave, envelope: lerCache<T>(chave) })
  const doDisco = disco.chave === chave ? disco.envelope : null

  const consulta = useQuery({
    // A conta entra na chave: sem ela, o cache em memória do TanStack devolveria a
    // leitura de outro usuário se a limpeza do logout falhasse.
    queryKey: opcoes.queryKey ?? [donoDoCache, chave],
    enabled: ativo,
    // Sessão morta não se resolve tentando de novo: o retry só atrasa a ida ao login.
    retry: (tentativas, erro) => !ehSessao(erro) && tentativas < 1,
    queryFn: async () => {
      try {
        const { data } = await api.get<T>(
          caminho,
          opcoes.prazoMs ? { timeout: opcoes.prazoMs } : undefined,
        )
        gravarCache(chave, data)
        return data
      } catch (erro) {
        if (ehSessao(erro)) {
          apagarCache(chave)
          setDisco({ chave, envelope: null })
        }
        throw erro
      }
    },
  })

  const recarregar = useCallback(() => {
    void consulta.refetch()
  }, [consulta])

  const daRede = consulta.data !== undefined
  const dados = daRede ? (consulta.data as T) : (doDisco?.dados ?? null)
  const mostrandoCache = !daRede && doDisco != null

  return {
    dados,
    carregando: ativo && dados === null && consulta.isPending,
    erro: dados === null && consulta.error ? mensagemDeErro(consulta.error) : null,
    // O status acompanha o `erro`: só vale falar em 404 quando não há nada na tela. Com
    // cache mostrando, a tela está desenhada e o que importa é a faixa de offline.
    status: dados === null && consulta.error ? statusDe(consulta.error) : null,
    offlineDesde: mostrandoCache && consulta.error ? hora(doDisco.gravadoEm) : undefined,
    atualizadoEm: daRede
      ? hora(new Date(consulta.dataUpdatedAt).toISOString())
      : doDisco
        ? hora(doDisco.gravadoEm)
        : undefined,
    atualizando: consulta.isFetching,
    recarregar,
  }
}
