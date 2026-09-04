/**
 * PDF e documento com a sessão no CABEÇALHO.
 *
 * As rotas de arquivo do BFF (`/manutencao/ordens/{id}/pdf`, `/documents/{id}/file`,
 * `/manutencao/pendencias/{cid}/documentos/{did}`) exigem `Authorization`. Um `<a href>`
 * ou `<img src>` direto não manda cabeçalho — e a saída fácil, o token na query string,
 * é a proibida: endereço entra em log de servidor, em histórico e em relatório de erro,
 * e um token vazado ali vale tanto quanto a senha. Então é `fetch` + Blob, sempre.
 *
 * O bloqueador de popup é o outro problema: `window.open` depois de um `await` é tratado
 * como abertura sem gesto do usuário e cai. Por isso `abrirPdf` abre a aba VAZIA no ato
 * do clique e só depois a aponta para o Blob.
 */

import { baseURL, detalheEmTexto, tokenDaSessao } from '@/lib/api'

export async function baixarComSessao(
  caminho: string,
  opcoes: { prazoMs?: number } = {},
): Promise<Blob> {
  const controlador = new AbortController()
  const prazo = setTimeout(() => controlador.abort(), opcoes.prazoMs ?? 120_000)
  const token = tokenDaSessao()
  try {
    const resposta = await fetch(`${baseURL}${caminho}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controlador.signal,
    })
    if (!resposta.ok) {
      let detalhe: string | null = null
      try {
        detalhe = detalheEmTexto(((await resposta.json()) as { detail?: unknown }).detail)
      } catch {
        // Corpo que não é JSON (página de erro do proxy, por exemplo): fica a frase padrão.
      }
      if (resposta.status === 401) throw new Error(detalhe ?? 'Sua sessão expirou. Entre de novo.')
      throw new Error(detalhe ?? `Não foi possível abrir o arquivo (erro ${resposta.status}).`)
    }
    const blob = await resposta.blob()
    // Um PDF de verdade tem quilobytes; um corpo de poucos bytes é uma mensagem de erro
    // que veio com status 200 por descuido de algum proxy.
    if (blob.size < 100) throw new Error('O servidor devolveu um arquivo vazio.')
    return blob
  } catch (erro) {
    if (erro instanceof DOMException && erro.name === 'AbortError') {
      throw new Error('O arquivo demorou demais para ficar pronto. Tente de novo.')
    }
    if (erro instanceof TypeError) throw new Error('Sem conexão com o servidor.')
    throw erro
  } finally {
    clearTimeout(prazo)
  }
}

/** Dispara o download de um Blob com o nome dado. */
export function baixarBlob(blob: Blob, nome: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nome
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Sem pressa: o navegador só lê a URL depois do clique; revogar no mesmo tick cancela
  // o download em alguns motores.
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export async function baixarArquivo(
  caminho: string,
  nome: string,
  opcoes: { prazoMs?: number } = {},
): Promise<void> {
  baixarBlob(await baixarComSessao(caminho, opcoes), nome)
}

/**
 * Abre um PDF em nova aba. Chame de dentro do `onClick` — é o gesto do usuário que
 * autoriza a aba. Se o navegador mesmo assim bloquear, cai no download.
 */
export async function abrirPdf(
  caminho: string,
  nome: string,
  opcoes: { prazoMs?: number } = {},
): Promise<void> {
  const aba = window.open('', '_blank')
  try {
    const blob = await baixarComSessao(caminho, opcoes)
    const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
    if (aba) {
      aba.location.href = url
    } else {
      baixarBlob(blob, nome)
    }
  } catch (erro) {
    aba?.close()
    throw erro
  }
}
