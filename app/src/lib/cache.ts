/**
 * Leitura offline primeiro: a tela abre com o que já se sabia e se corrige quando a rede
 * responde.
 *
 * Usina fica onde o sinal é ruim. Sem isto, abrir o app num pátio sem cobertura mostra
 * skeleton, timeout e um erro — quando o dado de dez minutos atrás estava no aparelho e
 * responderia a pergunta. O selo de horário é o que torna isso honesto: o número é antigo
 * e a tela diz desde quando.
 *
 * **`401` e `403` nunca são mascarados.** Nos dois casos o cache é apagado e o erro sobe
 * inteiro. Servir cache numa sessão expirada mostraria a usina de quem já não tem direito
 * a ela, e o pior é que pareceria funcionando — é a diferença entre uma tela velha e um
 * vazamento.
 *
 * O armazenamento é arquivo, não o cofre: isto é dado de leitura, e o `SecureStore` tem
 * limite apertado por chave. A sessão continua no [cofre](./cofre.ts).
 *
 * A API usada é a nova do `expo-file-system` (SDK 54+): `File`/`Directory`/`Paths`, com
 * escrita e leitura **síncronas**. `FileSystem.readAsStringAsync` e companhia são a API
 * legada, que hoje só existe sob `expo-file-system/legacy`.
 */

import { useQuery, type QueryKey } from '@tanstack/react-query'
import axios from 'axios'
import { Directory, File, Paths } from 'expo-file-system'
import { useEffect, useState } from 'react'
import { Platform } from 'react-native'

import { api, mensagemDeErro } from '@/lib/api'
import { hora } from '@/lib/format'

type Envelope<T> = { dados: T; gravadoEm: string }

const naWeb = Platform.OS === 'web'

/**
 * Cache do sistema, e não `document`: é dado reconstruível, que o sistema pode limpar
 * quando o aparelho apertar — e que não deve entrar no backup do usuário.
 */
const pasta = () => new Directory(Paths.cache, 'leituras')

/** Nome de arquivo a partir da chave: `plants` · `usina:3`. Os dois pontos não passam. */
const arquivoDe = (chave: string) => new File(pasta(), `${chave.replace(/[^a-z0-9]+/gi, '_')}.json`)

export async function lerCache<T>(chave: string): Promise<Envelope<T> | null> {
  try {
    if (naWeb) {
      const cru = globalThis.localStorage?.getItem(`leitura:${chave}`)
      return cru ? (JSON.parse(cru) as Envelope<T>) : null
    }
    const arquivo = arquivoDe(chave)
    if (!arquivo.exists) return null
    return JSON.parse(await arquivo.text()) as Envelope<T>
  } catch {
    // Sem cache, arquivo corrompido ou JSON de uma versão anterior do formato dão no
    // mesmo: não há o que mostrar, e a tela cai no caminho de carregamento normal.
    return null
  }
}

export async function gravarCache<T>(chave: string, dados: T): Promise<void> {
  const envelope: Envelope<T> = { dados, gravadoEm: new Date().toISOString() }
  try {
    if (naWeb) {
      globalThis.localStorage?.setItem(`leitura:${chave}`, JSON.stringify(envelope))
      return
    }
    // `create` explícito, e não confiança em `write` criar o que falta: `intermediates`
    // abre a pasta na primeira gravação e `overwrite` evita o erro na segunda. Sem os
    // dois, a falha seria muda — o `catch` a engoliria e o cache nunca existiria.
    const arquivo = arquivoDe(chave)
    arquivo.create({ intermediates: true, overwrite: true })
    arquivo.write(JSON.stringify(envelope))
  } catch {
    // Disco cheio não pode derrubar uma tela que já tem o dado na mão.
  }
}

export async function apagarCache(chave: string): Promise<void> {
  try {
    if (naWeb) {
      globalThis.localStorage?.removeItem(`leitura:${chave}`)
      return
    }
    const arquivo = arquivoDe(chave)
    if (arquivo.exists) arquivo.delete()
  } catch {
    /* idem */
  }
}

/**
 * Apaga tudo o que foi lido.
 *
 * Chamado no logout. Sem isto, a troca de conta no mesmo aparelho — cenário previsto no
 * CLAUDE.md, em que a mesma pessoa tem uma conta de gestor e uma de dono — mostraria a
 * quem entra as usinas de quem saiu, até a rede responder. Em usina, a rede demora.
 */
export async function limparCache(): Promise<void> {
  try {
    if (naWeb) {
      const chaves = Object.keys(globalThis.localStorage ?? {})
      for (const k of chaves) {
        if (k.startsWith('leitura:')) globalThis.localStorage?.removeItem(k)
      }
      return
    }
    const destino = pasta()
    if (destino.exists) destino.delete()
  } catch {
    // Falhar aqui não pode impedir o logout: sair tem de funcionar sempre.
  }
}

const ehSessao = (erro: unknown) =>
  axios.isAxiosError(erro) && (erro.response?.status === 401 || erro.response?.status === 403)

export type Leitura<T> = {
  dados: T | null
  /** Só enquanto não há absolutamente nada para desenhar — o skeleton. */
  carregando: boolean
  /** Preenchido quando não há nem cache nem resposta. Com cache na tela, vira a faixa. */
  erro: string | null
  /** `HH:MM` da gravação, quando o que está na tela é cache. Alimenta `Tela.offlineDesde`. */
  offlineDesde: string | undefined
  atualizando: boolean
  recarregar: () => void
}

/**
 * A leitura de uma tela, cache primeiro.
 *
 * ```ts
 * const { dados, carregando, erro, offlineDesde } = fetchWithCache<UsinasOut>('plants')
 * ```
 *
 * `chave` é o caminho no BFF sem `/api/v1/`, e serve de nome de arquivo e de `queryKey`.
 */
export function fetchWithCache<T>(
  chave: string,
  opcoes: { caminho?: string; ativo?: boolean; queryKey?: QueryKey } = {},
): Leitura<T> {
  const caminho = opcoes.caminho ?? `/api/v1/${chave}`
  const ativo = opcoes.ativo ?? true

  // `undefined` é "ainda lendo o disco"; `null` é "li e não havia nada". A distinção é o
  // que impede o piscar de vazio antes de o cache aparecer.
  const [doDisco, setDoDisco] = useState<Envelope<T> | null | undefined>(undefined)

  useEffect(() => {
    let vivo = true
    void lerCache<T>(chave).then((c) => {
      if (vivo) setDoDisco(c)
    })
    return () => {
      vivo = false
    }
  }, [chave])

  const consulta = useQuery({
    queryKey: opcoes.queryKey ?? [chave],
    enabled: ativo,
    // Sessão morta não se resolve tentando de novo: o retry só atrasa a ida ao login.
    retry: (tentativas, erro) => !ehSessao(erro) && tentativas < 1,
    queryFn: async () => {
      try {
        const { data } = await api.get<T>(caminho)
        void gravarCache(chave, data)
        return data
      } catch (erro) {
        if (ehSessao(erro)) {
          await apagarCache(chave)
          setDoDisco(null)
        }
        throw erro
      }
    },
  })

  const daRede = consulta.data !== undefined
  const dados = daRede ? (consulta.data as T) : (doDisco?.dados ?? null)
  const mostrandoCache = !daRede && doDisco != null

  return {
    dados,
    // Enquanto o disco não respondeu não é vazio nem erro: ainda não se sabe.
    carregando: ativo && dados === null && (doDisco === undefined || consulta.isPending),
    erro: dados === null && consulta.error ? mensagemDeErro(consulta.error) : null,
    offlineDesde: mostrandoCache && consulta.error ? hora(doDisco.gravadoEm) : undefined,
    atualizando: consulta.isFetching,
    recarregar: () => void consulta.refetch(),
  }
}
