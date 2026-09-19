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

/**
 * De quem é o cache que está sendo lido ou escrito.
 *
 * O logout apaga tudo, mas isso não basta: se o aplicativo for encerrado no meio da troca
 * de conta — ou se o `sair()` falhar por qualquer razão —, o arquivo de uma conta ficaria
 * legível pela seguinte. Com a conta no nome do arquivo, ler o cache alheio deixa de ser
 * possível por construção, e não por disciplina de limpeza.
 */
let donoDoCache = 'anonimo'

export function identificarCache(usuarioId: number | null): void {
  donoDoCache = usuarioId === null ? 'anonimo' : `u${usuarioId}`
}

/** Nome de arquivo a partir da chave: `plants` · `plants/3`. Prefixado pela conta. */
const arquivoDe = (chave: string) =>
  new File(pasta(), `${donoDoCache}__${chave.replace(/[^a-z0-9]+/gi, '_')}.json`)

export async function lerCache<T>(chave: string): Promise<Envelope<T> | null> {
  try {
    if (naWeb) {
      const cru = globalThis.localStorage?.getItem(`leitura:${donoDoCache}:${chave}`)
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
      globalThis.localStorage?.setItem(`leitura:${donoDoCache}:${chave}`, JSON.stringify(envelope))
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
      globalThis.localStorage?.removeItem(`leitura:${donoDoCache}:${chave}`)
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

/**
 * Quão velho é o que está desenhado — e se a tela ainda espera algo melhor.
 *
 * Existe porque o carimbo de horário só aparecia **quando a rede falhava**. No caminho
 * comum, que é rede lenta e não rede morta, a tela desenhava o número de dez minutos
 * atrás sem marca nenhuma e o trocava quando a resposta chegava: quem abria o app lia
 * potência antiga como se fosse a de agora, e via o valor saltar do nada três segundos
 * depois. Carimbar só no erro é carimbar no caso menos frequente.
 */
export type Frescor = {
  /** `rede` = acabou de responder · `cache` = veio do disco · `vazio` = não há o que dizer. */
  origem: 'rede' | 'cache' | 'vazio'
  /** `HH:MM` de quando o que está na tela foi lido. Ausente quando veio da rede. */
  hora: string | undefined
  /** Idade do que está na tela. Zero quando é resposta de rede. */
  idadeMs: number
  /**
   * O que está na tela passou da validade dos números instantâneos.
   *
   * Potência "agora" de ontem à noite é mentira mesmo carimbada: a tela esconde o número
   * perecível e mostra o esqueleto, em vez de pedir que a pessoa leia o carimbo antes de
   * acreditar no valor. O que não estraga — nome da usina, fatura, cronograma — continua
   * aparecendo, e por isso a validade é por leitura (`validadeMs`), não global.
   */
  vencido: boolean
  /** A rede está buscando agora. */
  atualizando: boolean
  /** A rede falhou e o que sobrou é o disco. */
  offline: boolean
}

export type Leitura<T> = {
  dados: T | null
  /** Só enquanto não há absolutamente nada para desenhar — o skeleton. */
  carregando: boolean
  /** Preenchido quando não há nem cache nem resposta. Com cache na tela, vira a faixa. */
  erro: string | null
  /** De quando é o que está na tela, e o que ainda está a caminho. Alimenta `Tela.frescor`. */
  frescor: Frescor
  atualizando: boolean
  recarregar: () => void
}

/**
 * Quanto tempo um número instantâneo continua valendo.
 *
 * Quinze minutos é o intervalo em que a potência de uma usina ainda descreve o que está
 * acontecendo: dentro dele o valor antigo erra por pouco e vale mais que um vazio; fora
 * dele já é outro céu. Leitura que não estraga passa `validadeMs: Infinity`.
 */
export const VALIDADE_PADRAO_MS = 15 * 60_000

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
  opcoes: {
    caminho?: string
    ativo?: boolean
    queryKey?: QueryKey
    /**
     * Por quanto tempo o cache desta leitura ainda descreve a realidade. Ver
     * `VALIDADE_PADRAO_MS`; `Infinity` para o que não estraga (cadastro, fatura, ficha).
     */
    validadeMs?: number
    /**
     * Prazo em milissegundos, quando o padrão de 12 s não serve.
     *
     * Existe por um caso concreto (04/09/2026): a ficha de uma tarefa coletiva com vinte
     * inversores atravessa quatro chamadas em série no BFF, a última delas montando a ficha
     * inteira — passa dos 12 s e o aplicativo desistia com "a conexão demorou demais", numa
     * tarefa que estava sendo montada normalmente do outro lado. Prazo é por chamada porque
     * subir o padrão faria toda tela ficar 40 s pendurada quando a rede cair de verdade.
     */
    prazoMs?: number
  } = {},
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
    // A conta entra na chave: sem ela, o cache em memória do TanStack devolveria a
    // leitura de outro usuário se a limpeza do logout falhasse.
    queryKey: opcoes.queryKey ?? [donoDoCache, chave],
    enabled: ativo,
    // Sessão morta não se resolve tentando de novo: o retry só atrasa a ida ao login.
    retry: (tentativas, erro) => !ehSessao(erro) && tentativas < 1,
    queryFn: async () => {
      try {
        const { data } = await api.get<T>(caminho,
          opcoes.prazoMs ? { timeout: opcoes.prazoMs } : undefined)
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

  // A idade é calculada a cada render, e não guardada: o que importa é a idade no
  // instante em que a tela desenha. Um relógio próprio custaria um render por segundo
  // para adiantar em nada — a rede responde ou falha antes de qualquer minuto virar.
  const validadeMs = opcoes.validadeMs ?? VALIDADE_PADRAO_MS
  const idadeMs = mostrandoCache ? Date.now() - new Date(doDisco.gravadoEm).getTime() : 0

  const frescor: Frescor = {
    origem: daRede ? 'rede' : mostrandoCache ? 'cache' : 'vazio',
    hora: mostrandoCache ? hora(doDisco.gravadoEm) : undefined,
    idadeMs,
    vencido: mostrandoCache && idadeMs > validadeMs,
    atualizando: consulta.isFetching,
    offline: mostrandoCache && consulta.error != null,
  }

  return {
    dados,
    // Enquanto o disco não respondeu não é vazio nem erro: ainda não se sabe.
    carregando: ativo && dados === null && (doDisco === undefined || consulta.isPending),
    erro: dados === null && consulta.error ? mensagemDeErro(consulta.error) : null,
    frescor,
    atualizando: consulta.isFetching,
    recarregar: () => void consulta.refetch(),
  }
}
