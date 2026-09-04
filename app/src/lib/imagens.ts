/**
 * Trazer para o disco uma imagem que só sai com sessão.
 *
 * ## Por que não basta apontar o `<Image>` para a URL
 *
 * As fotos de uma ficha são servidas por rota autenticada — a sessão vai em CABEÇALHO, porque
 * token em URL entra em log de servidor e em histórico. O `<Image>` do React Native aceita
 * `headers` no `source`, e é o caminho que a documentação indica; na prática, no aparelho do
 * dono (04/09/2026), toda miniatura falhava. Não dá para depurar o carregador nativo daqui, e
 * insistir nele seria apostar de novo no mesmo número.
 *
 * O `fetch` do React Native, esse, sabidamente manda o cabeçalho — é por ele que o aplicativo
 * inteiro conversa com o servidor. Então a imagem é BAIXADA por `fetch`, gravada no cache e
 * exibida a partir do arquivo local. O `<Image>` passa a ler `file://`, onde não há sessão
 * nenhuma para carregar.
 *
 * Três ganhos que vieram junto:
 *
 * - **O erro fica legível.** Uma imagem que falha no `<Image>` só sabe dizer "falhou"; aqui
 *   se lê o status e a frase que o servidor escreveu, e é isso que aparece no quadro.
 * - **Cache de verdade.** Reabrir a ficha não rebaixa nada: o arquivo já está no aparelho.
 * - **Uma vez só.** Duas miniaturas iguais na mesma tela dividem o mesmo download, em vez de
 *   disputar a fila do servidor.
 */

import * as FileSystem from 'expo-file-system'

import { baseURL, detalheEmTexto, tokenDaSessao } from '@/lib/api'

/** Onde as fotos ficam. Cache e não documentos: o sistema pode limpar quando faltar espaço. */
const PASTA = 'fotos-ficha'

/** Baixas em andamento, por chave — duas miniaturas iguais não viram dois downloads. */
const emVoo = new Map<string, Promise<string>>()

/** Um "PDF de 200 bytes" para imagem: resposta curta demais é página de erro disfarçada. */
const MINIMO_PLAUSIVEL = 200

/** Quanto se espera por uma imagem antes de dizer que demorou. */
const PRAZO_MS = 45_000

export class ImagemIndisponivel extends Error {}

/**
 * O caminho local da imagem, baixando-a se ainda não estiver no aparelho.
 *
 * @param caminho endereço no BFF (relativo, como ele devolve)
 * @param chave nome estável do arquivo — o id da foto mais a variante
 */
export async function arquivoDaImagem(caminho: string, chave: string): Promise<string> {
  const jaVoando = emVoo.get(chave)
  if (jaVoando) return jaVoando

  const promessa = baixar(caminho, chave).finally(() => emVoo.delete(chave))
  emVoo.set(chave, promessa)
  return promessa
}

async function baixar(caminho: string, chave: string): Promise<string> {
  const pasta = new FileSystem.Directory(FileSystem.Paths.cache, PASTA)
  // `idempotent`: seis miniaturas começam juntas, e sem isto a segunda a chegar aqui
  // encontraria a pasta recém-criada pela primeira e lançaria.
  if (!pasta.exists) pasta.create({ intermediates: true, idempotent: true })

  const destino = new FileSystem.File(pasta, `${chave}.jpg`)
  // Já no aparelho: a foto de uma ficha executada não muda, então o arquivo vale para sempre.
  if (destino.exists && destino.size > MINIMO_PLAUSIVEL) return destino.uri

  const url = caminho.startsWith('http') ? caminho : `${baseURL}${caminho}`
  /*
   * PRAZO. O `fetch` do React Native não desiste sozinho: se o servidor segurar a conexão, a
   * miniatura fica "carregando" para sempre — e foi o que o dono viu quando o meuPlano ficou
   * 30 s na fila do pool de conexões. Quarenta e cinco segundos é folga para uma imagem que
   * normalmente vem em dois; passou disso, o quadro diz que demorou e aceita tentar de novo.
   */
  const prazo = new AbortController()
  const alarme = setTimeout(() => prazo.abort(), PRAZO_MS)
  let resposta: Response
  try {
    resposta = await fetch(url, {
      headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
      signal: prazo.signal,
    })
  } catch (e) {
    throw new ImagemIndisponivel(
      e instanceof Error && /abort/i.test(e.message)
        ? 'demorou demais para vir'
        : 'sem conexão com o servidor',
    )
  } finally {
    clearTimeout(alarme)
  }

  if (!resposta.ok) throw new ImagemIndisponivel(await motivo(resposta))

  const bytes = new Uint8Array(await resposta.arrayBuffer())
  if (bytes.byteLength < MINIMO_PLAUSIVEL) {
    throw new ImagemIndisponivel('o servidor respondeu, mas a imagem veio vazia')
  }

  if (destino.exists) destino.delete()
  destino.create()
  destino.write(bytes)
  return destino.uri
}

/** O que dizer quando o servidor recusa — a frase dele, não uma adivinhação nossa. */
async function motivo(r: Response): Promise<string> {
  if (r.status === 401) return 'a sua sessão expirou'
  let detalhe: string | null = null
  try {
    const texto = await r.text()
    try {
      detalhe = detalheEmTexto((JSON.parse(texto) as { detail?: unknown }).detail)
    } catch {
      detalhe = texto.trim().slice(0, 120) || null
    }
  } catch {
    detalhe = null
  }
  return detalhe ?? `o servidor respondeu ${r.status}`
}
