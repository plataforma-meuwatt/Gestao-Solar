/**
 * Ponte permanente: `/documento/{id}` → `/relatorio/{id}`.
 *
 * A tela mudou de nome junto com a aba, e o nome do arquivo **é** a rota no expo-router.
 * Este arquivo não desenha nada: ele existe porque link salvo não pode virar rota morta e
 * o expo-router não redireciona sozinho. Nada no repositório gera `gestaosolar://documento/12`
 * hoje — não há listener de push, conferido —, mas o esquema `gestaosolar` é público e o
 * endereço é válido por construção desde que a tela existe. Quem guardou um, guardou.
 *
 * O que importa aqui é **preservar os parâmetros**: sem eles, um link antigo de
 * `/documento/36?tipo=resumo` chegaria à tela nova pedindo a peça errada — abriria o
 * Relatório de Geração de um fechamento que só tem o Resumo Executivo, e o servidor
 * responderia 404 numa peça que o dono nunca pediu. Por isso o redirecionamento repassa
 * **tudo** o que veio, e não só `tipo`: a lista pode acrescentar um parâmetro amanhã e a
 * ponte não precisa saber o nome dele.
 *
 * `<Redirect>` e não `router.replace` num efeito: o redirecionamento acontece na primeira
 * renderização, sem um quadro de tela vazia entre as duas rotas.
 */

import { Redirect, useLocalSearchParams } from 'expo-router'

/**
 * Para onde vai um endereço antigo — função pura, para o teste conferir o desvio de
 * verdade em vez de procurar palavras no arquivo.
 */
export function destinoDaPonte(parametros: Record<string, string | string[] | undefined>): string {
  const { id, ...resto } = parametros

  const consulta = new URLSearchParams()
  for (const [chave, valor] of Object.entries(resto)) {
    // `useLocalSearchParams` devolve um array quando o mesmo nome aparece duas vezes na
    // URL. Repassar cada ocorrência mantém a URL idêntica à que a pessoa guardou.
    for (const item of Array.isArray(valor) ? valor : [valor]) {
      if (item !== undefined) consulta.append(chave, item)
    }
  }

  const cauda = consulta.toString()
  return `/relatorio/${encodeURIComponent(String(id ?? ''))}${cauda ? `?${cauda}` : ''}`
}

export default function PonteDocumento() {
  return <Redirect href={destinoDaPonte(useLocalSearchParams())} />
}
