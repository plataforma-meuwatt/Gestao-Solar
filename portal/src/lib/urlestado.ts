/**
 * Estado que mora na URL — para que um link colado num e-mail abra o que a pessoa viu.
 *
 * O portal já tinha decidido que a URL nomeia a família (`/manutencao/ordens`, e não
 * `/ordens`) porque "link colado em e-mail tem de dizer de que assunto se trata". A mesma
 * razão vale um degrau abaixo: um diretor que abre a aba **Ano** de Porto Ferreira e manda o
 * endereço para o time quer que o time caia no ano, não em setembro. Enquanto a aba e o
 * período viviam só em `useState`, o endereço era sempre o mesmo — e o destinatário via outra
 * tela. Recarregar a página tinha o mesmo efeito: voltava tudo ao padrão.
 *
 * Três decisões que este arquivo carrega:
 *
 * **O padrão não é escrito.** `?aba=mes` some da barra quando `mes` já é o padrão, e a URL
 * fica limpa para quem só está navegando. Escrever o padrão faria toda tela nascer com uma
 * cauda de parâmetros que não informa nada.
 *
 * **Valor inválido cai no padrão, calado.** `?aba=trimestre` não existe: em vez de tela vazia
 * ou erro, vale `mes`. É a mesma regra do resto do portal — filtro nunca deixa a tela em
 * branco —, e aqui ela protege de um endereço truncado no meio pelo cliente de e-mail.
 *
 * **Trocar de assunto empilha; ajustar o mesmo assunto não.** Mudar de aba é navegação e o
 * botão Voltar deve desfazê-la (`push`). Andar de agosto para setembro é ajuste fino do mesmo
 * assunto: com `push`, doze cliques na seta deixariam o Voltar inútil, então vai de `replace`.
 * Quem escreve o estado escolhe, com `historico`.
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

type Opcoes<T extends string> = {
  /** Nome do parâmetro na barra de endereço. Em português, como o resto do portal. */
  chave: string
  /** O que vale quando o parâmetro está ausente — ou traz lixo. */
  padrao: T
  /** Os únicos valores aceitos. Fora desta lista, vale o padrão. */
  aceitos: readonly T[]
}

/** Um valor de conjunto fechado (aba, recorte, filtro) guardado na URL. */
export function useEstadoNaUrl<T extends string>({ chave, padrao, aceitos }: Opcoes<T>) {
  const [params, setParams] = useSearchParams()

  const bruto = params.get(chave)
  const valor = useMemo<T>(
    () => (bruto && (aceitos as readonly string[]).includes(bruto) ? (bruto as T) : padrao),
    [bruto, aceitos, padrao],
  )

  const definir = useCallback(
    (novo: T, historico: 'push' | 'replace' = 'push') => {
      setParams(
        (atuais) => {
          const proximos = new URLSearchParams(atuais)
          if (novo === padrao) proximos.delete(chave)
          else proximos.set(chave, novo)
          return proximos
        },
        { replace: historico === 'replace' },
      )
    },
    [chave, padrao, setParams],
  )

  return [valor, definir] as const
}

/**
 * Um valor livre (uma data, uma busca) guardado na URL, com uma prova de validade própria.
 *
 * Diferente do de cima: não há lista de aceitos — quem chama diz se o texto serve. Uma data
 * inventada (`?em=amanhã`) cai no padrão pelo mesmo motivo que uma aba inexistente cai.
 */
export function useTextoNaUrl({
  chave,
  padrao,
  valido,
}: {
  chave: string
  padrao: string
  valido: (v: string) => boolean
}) {
  const [params, setParams] = useSearchParams()

  const bruto = params.get(chave)
  const valor = bruto && valido(bruto) ? bruto : padrao

  const definir = useCallback(
    (novo: string, historico: 'push' | 'replace' = 'replace') => {
      setParams(
        (atuais) => {
          const proximos = new URLSearchParams(atuais)
          if (!novo || novo === padrao) proximos.delete(chave)
          else proximos.set(chave, novo)
          return proximos
        },
        { replace: historico === 'replace' },
      )
    },
    [chave, padrao, setParams],
  )

  return [valor, definir] as const
}
