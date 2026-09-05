/**
 * Trazer para a memória uma imagem que só sai com sessão.
 *
 * ## Por que não basta apontar o `<img src>` para o endereço
 *
 * As fotos de uma ficha são servidas por rota autenticada do BFF
 * (`/manutencao/ordens/{os}/tarefas/{id}/fotos/{foto}`), e a sessão vai em CABEÇALHO. O
 * `<img>` do navegador não manda cabeçalho nenhum — e a saída fácil, o token na query, é a
 * proibida: endereço entra em log de servidor, em histórico e em relatório de erro, e um
 * token vazado ali vale tanto quanto a senha. (Este é o motivo NO NAVEGADOR; o aplicativo
 * baixa por outra razão, um defeito do carregador nativo do React Native. Não é a mesma
 * história, e trocá-las levaria alguém a concluir que aqui dá para apontar direto.)
 *
 * Então a imagem é BAIXADA por `fetch` e exibida a partir de um `blob:` — endereço local,
 * onde não há sessão nenhuma para carregar. Quem faz o download é `baixarComSessao`
 * (`lib/arquivo.ts`), que já é a régua do produto para arquivo autenticado: manda o Bearer,
 * traduz o 401 em "sua sessão expirou", devolve a frase que o servidor escreveu e recusa
 * corpo curto demais — a página de erro que algum proxy manda com status 200.
 *
 * ## Uma vez só
 *
 * Uma ficha coletiva tem dezenas de fotos, e a mesma foto pode aparecer duas vezes na tela
 * (a evidência de uma resposta e o rodapé do equipamento). `emVoo` faz as duas dividirem o
 * MESMO download em vez de disputarem a fila do servidor.
 *
 * Não há cache de blob em memória de propósito: guardar 61 imagens vivas enquanto a página
 * existe é caro, e a repetição já está resolvida um nível acima — o BFF responde
 * `Cache-Control: private, max-age=3600`, então reabrir a ficha lê do cache do navegador.
 * O que NÃO pode faltar é revogar o `blob:` ao desmontar: cada endereço criado segura os
 * bytes até ser revogado, e uma tela de fotos que não revoga vaza a ficha inteira.
 */

import { baixarComSessao } from '@/lib/arquivo'

/**
 * Quanto se espera por uma imagem antes de dizer que demorou.
 *
 * Menos que os 120 s do padrão de PDF: um PDF de ficha é RENDERIZADO no pedido, uma foto já
 * está gravada. Passou disso, o quadro diz que demorou e aceita um clique para tentar.
 */
const PRAZO_MS = 45_000

/** Downloads em andamento, por chave — duas miniaturas iguais não viram dois downloads. */
const emVoo = new Map<string, Promise<Blob>>()

/**
 * Os bytes da imagem, compartilhando o download que já estiver em andamento.
 *
 * @param caminho endereço no BFF (relativo, como ele o devolve na ficha)
 * @param chave nome estável do pedido — o id da foto mais a variante
 */
export function bytesDaImagem(caminho: string, chave: string): Promise<Blob> {
  const voando = emVoo.get(chave)
  if (voando) return voando

  const promessa = baixarComSessao(caminho, { prazoMs: PRAZO_MS }).finally(() => {
    emVoo.delete(chave)
  })
  emVoo.set(chave, promessa)
  return promessa
}

/** Só para o teste: nenhuma tela precisa disto, e um estado global sujo mente entre casos. */
export function esquecerImagensEmVoo(): void {
  emVoo.clear()
}
