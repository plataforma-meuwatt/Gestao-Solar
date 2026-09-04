/**
 * Baixar um PDF do BFF e entregá-lo ao sistema — a fonte única.
 *
 * Existiam duas cópias disto (o componente `AbrirPdf` e a tela `documento/[id]`), com o
 * mesmo defeito nas duas: o download por `File.downloadFileAsync` e a mensagem de erro
 * adivinhada por expressão regular sobre o texto da exceção. Consertar em um lugar deixava
 * o outro quebrado, então virou função.
 *
 * ## Por que `fetch` e não `downloadFileAsync`
 *
 * No Android o `downloadFileAsync` usa um `OkHttpClient()` sem configuração: *read timeout*
 * de **10 segundos**. Como o BFF só começa a responder depois que o PDF inteiro chegou do
 * meuPlano, esse relógio corre contra a GERAÇÃO do documento — e uma ficha com fotos leva
 * mais que isso na primeira vez. O `fetch` do React Native usa o cliente do próprio RN, sem
 * esse teto, e ainda entrega o corpo da resposta de erro, que é onde o servidor escreve o
 * motivo de verdade.
 *
 * ## Por que a mensagem vem do servidor
 *
 * O código antigo procurava "403" ou "502" no texto da exceção e escrevia uma frase própria.
 * A ponte achata falhas do meuPlano em 502, então uma questão de permissão chegava ao dono
 * como "não conseguiu gerar o PDF" — uma acusação falsa, e sem pista do que fazer. Agora o
 * que aparece na tela é o `detail` que o servidor escreveu.
 */

import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'

import { detalheEmTexto, tokenDaSessao } from '@/lib/api'

/** Um PDF grande é normal; um "PDF" de 200 bytes é uma página de erro disfarçada. */
const MINIMO_PLAUSIVEL = 1000

/**
 * Baixa, grava em cache e abre o compartilhamento do sistema.
 *
 * @returns `null` quando deu certo, ou a frase a mostrar ao usuário.
 */
export async function abrirPdf({
  url,
  arquivo,
  titulo,
}: {
  url: string
  /** Nome do arquivo em cache. Sem extensão o Android não sabe o que abrir. */
  arquivo: string
  /** O que aparece no diálogo do sistema. */
  titulo: string
}): Promise<string | null> {
  let bytes: Uint8Array
  try {
    const resposta = await fetch(url, {
      headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
    })
    if (!resposta.ok) return await motivoDaResposta(resposta)
    bytes = new Uint8Array(await resposta.arrayBuffer())
  } catch (e) {
    return e instanceof Error && /abort/i.test(e.message)
      ? 'O download foi interrompido. Tente de novo.'
      : 'Não foi possível baixar. Verifique a conexão e tente de novo.'
  }

  if (bytes.byteLength < MINIMO_PLAUSIVEL) {
    return 'O servidor respondeu, mas o arquivo veio vazio. Tente de novo.'
  }

  try {
    const destino = new FileSystem.File(FileSystem.Paths.cache, arquivo)
    // Apaga antes: o upstream versiona o PDF por fingerprint, então um arquivo antigo com
    // o mesmo nome entregaria a versão de ontem sem avisar.
    if (destino.exists) destino.delete()
    destino.create()
    destino.write(bytes)

    if (!(await Sharing.isAvailableAsync())) return 'Este aparelho não tem com o que abrir PDF.'
    await Sharing.shareAsync(destino.uri, {
      mimeType: 'application/pdf',
      dialogTitle: titulo,
      UTI: 'com.adobe.pdf',
    })
    return null
  } catch {
    return 'O arquivo baixou, mas não deu para abri-lo neste aparelho.'
  }
}

/** O motivo que o SERVIDOR escreveu — nunca uma adivinhação a partir do número do status. */
async function motivoDaResposta(r: Response): Promise<string> {
  let detalhe: string | null = null
  try {
    const texto = await r.text()
    try {
      detalhe = detalheEmTexto((JSON.parse(texto) as { detail?: unknown }).detail)
    } catch {
      detalhe = null
    }
    if (!detalhe) detalhe = texto.trim().slice(0, 300) || null
  } catch {
    detalhe = null
  }

  if (r.status === 401) return 'A sua sessão expirou. Entre de novo.'
  if (r.status === 403) return detalhe ?? 'Este documento não está disponível para a sua conta.'
  if (r.status === 404) return detalhe ?? 'Este documento não existe mais.'
  return detalhe
    ? `Não deu para abrir o PDF: ${detalhe}`
    : `Não deu para abrir o PDF (erro ${r.status}). Tente mais tarde.`
}
