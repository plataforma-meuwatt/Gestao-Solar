/**
 * O leitor de PDF **dentro** do aplicativo.
 *
 * ## Por que WebView + pdf.js, e não uma biblioteca nativa
 *
 * A pergunta que decide isto não é "qual desenha melhor" — é **quando o dono vê**. O
 * `react-native-webview` entrou no primeiro commit deste repositório e o *autolinking* do
 * Expo compila módulo nativo a partir das DEPENDÊNCIAS, não dos imports: todo APK já
 * instalado carrega esse módulo dentro, mesmo sem nenhuma tela usando WebView até hoje. Com
 * `runtimeVersion: appVersion` na 0.1.0, um `eas update` alcança esses aparelhos **hoje**.
 * `react-native-pdf` seria o contrário, e pior que "só precisa de APK novo": o
 * `requireNativeModule` estoura na AVALIAÇÃO do módulo, então quem estivesse com o APK
 * velho não veria um leitor degradado — veria a tela cair.
 *
 * ## Por que o `onLoadEnd` não decide nada aqui
 *
 * Foi exatamente ele que fez a tentativa anterior de WebView falhar em silêncio: apontava-se
 * a `WebView` para o PDF, o `onLoadEnd` disparava, a tela saía do carregando e o dono ficava
 * olhando uma folha branca de um documento que existe e está autorizado. Aqui o `onLoadEnd`
 * não é escutado. Quem tira a tela do carregando é o **veredito** que o visualizador posta
 * de dentro (`pagina-pronta`, depois que o `render` daquela página de fato terminou), e
 * quem a tira em erro é o `erro`, com a mensagem que o pdf.js escreveu. Há ainda um relógio
 * de segurança: se nenhum recado chegar, a tela desiste dizendo isso — porque um WebView
 * morto não posta nem erro.
 *
 * ## O externo não foi rebaixado
 *
 * "Abrir em outro app" continua existindo, agora como segundo botão dentro do leitor: é a
 * saída para imprimir, mandar no WhatsApp e para o caso de o desenho falhar. E ele reusa o
 * arquivo que já está em disco — não baixa de novo.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ActivityIndicator, AppState, Pressable, StyleSheet, Text, View } from 'react-native'
import { WebView, type WebViewMessageEvent } from 'react-native-webview'

import { Botao } from '@/components/base'
import {
  baixarPdf,
  compartilharPdf,
  escreverPaginaDoLeitor,
  TETO_LEITOR_BYTES,
  type RecadoDoLeitor,
} from '@/lib/pdf'
import { cores, espaco, fontes, raio, tipo, tons } from '@/theme/tokens'

/**
 * Quanto tempo esperar por um recado do visualizador antes de declarar que ele não veio.
 *
 * Generoso de propósito: um pacote de fichas de 24 MB leva vários segundos só para o pdf.js
 * abrir. O relógio existe para o caso em que NADA chega — WebView derrubada por falta de
 * memória, motor sem suporte —, não para apressar documento grande.
 */
const ESPERA_MAXIMA_MS = 45_000

type Estado =
  | { fase: 'baixando' }
  | { fase: 'montando' }
  | { fase: 'desenhando'; uri: string; pagina: number; paginas: number }
  | { fase: 'pronto'; uri: string; paginas: number; truncado: boolean }
  | { fase: 'erro'; mensagem: string }

export function LeitorPdf({
  url,
  arquivo,
  titulo,
}: {
  /** Endereço no BFF. O WebView nunca o vê: os bytes viajam para dentro do HTML local. */
  url: string
  /** Nome do arquivo em cache. Sem extensão o Android não sabe o que abrir. */
  arquivo: string
  /** O que aparece no diálogo do sistema ao abrir em outro aplicativo. */
  titulo: string
}) {
  const [estado, setEstado] = useState<Estado>({ fase: 'baixando' })
  const [erroExterno, setErroExterno] = useState<string | null>(null)
  const [tentativa, setTentativa] = useState(0)
  // O arquivo em disco, guardado para o botão externo não baixar de novo.
  const pdfUri = useRef<string | null>(null)
  const vivo = useRef(true)

  useEffect(() => {
    vivo.current = true
    return () => {
      vivo.current = false
    }
  }, [])

  useEffect(() => {
    let cancelado = false
    setEstado({ fase: 'baixando' })
    setErroExterno(null)
    pdfUri.current = null
    ;(async () => {
      const baixado = await baixarPdf({ url, arquivo })
      if (cancelado) return
      if ('erro' in baixado) {
        setEstado({ fase: 'erro', mensagem: baixado.erro })
        return
      }
      pdfUri.current = baixado.arquivo.uri

      const tamanho = baixado.arquivo.size ?? 0
      if (tamanho > TETO_LEITOR_BYTES) {
        setEstado({
          fase: 'erro',
          mensagem:
            'Este documento é grande demais para ser desenhado aqui dentro. Abra em outro aplicativo.',
        })
        return
      }

      setEstado({ fase: 'montando' })
      // A gravação é SÍNCRONA e pesada (alguns megabytes). O `setEstado` acima só agenda o
      // repinte; sem devolver a vez ao laço de eventos, a tela travaria ainda mostrando
      // "Baixando…" — dizendo uma coisa enquanto faz outra.
      await new Promise((r) => setTimeout(r, 0))
      if (cancelado) return
      try {
        const pagina = escreverPaginaDoLeitor(baixado.arquivo)
        if (cancelado) return
        setEstado({ fase: 'desenhando', uri: pagina.uri, pagina: 0, paginas: 0 })
      } catch {
        if (!cancelado) {
          setEstado({
            fase: 'erro',
            mensagem: 'Não deu para preparar o documento para leitura neste aparelho.',
          })
        }
      }
    })()
    return () => {
      cancelado = true
    }
  }, [url, arquivo, tentativa])

  // O relógio de segurança. Só corre enquanto se espera o primeiro recado: um WebView que
  // morreu não posta nem erro, e sem isto a tela ficaria no carregando para sempre.
  //
  // Ele conta apenas o tempo em que o aplicativo esteve À FRENTE, e isso não é capricho: o
  // pdf.js agenda cada fatia de desenho por `requestAnimationFrame`, que o sistema congela
  // quando a superfície não está sendo pintada. Medido no motor do WebView, com o documento
  // oculto: a mesma página que leva 30 ms ficou 24 s sem sair do lugar, e voltou a andar no
  // primeiro quadro pintado. Um relógio de parede acusaria de morto um desenho que está
  // apenas esperando a vez — e mandaria o dono para fora do app sem motivo.
  useEffect(() => {
    if (estado.fase !== 'desenhando' || estado.pagina > 0) return
    let restante = ESPERA_MAXIMA_MS
    let ultimo = Date.now()
    const tique = setInterval(() => {
      const agora = Date.now()
      if (AppState.currentState === 'active') restante -= agora - ultimo
      ultimo = agora
      if (restante > 0 || !vivo.current) return
      clearInterval(tique)
      setEstado({
        fase: 'erro',
        mensagem: 'O documento não terminou de abrir neste aparelho. Tente em outro aplicativo.',
      })
    }, 1000)
    return () => clearInterval(tique)
  }, [estado])

  const receber = useCallback((evento: WebViewMessageEvent) => {
    let recado: RecadoDoLeitor
    try {
      recado = JSON.parse(evento.nativeEvent.data) as RecadoDoLeitor
    } catch {
      return
    }
    setEstado((atual) => {
      if (atual.fase !== 'desenhando' && atual.fase !== 'pronto') return atual
      const uri = atual.uri
      if (recado.tipo === 'erro') {
        return { fase: 'erro', mensagem: `Não deu para desenhar: ${recado.mensagem}` }
      }
      if (recado.tipo === 'documento-aberto') {
        return atual.fase === 'desenhando' ? { ...atual, paginas: recado.paginas } : atual
      }
      if (recado.tipo === 'pagina-pronta') {
        return { fase: 'desenhando', uri, pagina: recado.pagina, paginas: recado.paginas }
      }
      return {
        fase: 'pronto',
        uri,
        paginas: recado.paginas,
        truncado: recado.truncado,
      }
    })
  }, [])

  async function abrirLaFora() {
    setErroExterno(null)
    const uri = pdfUri.current
    if (!uri) {
      setErroExterno('O arquivo ainda não terminou de baixar.')
      return
    }
    setErroExterno(await compartilharPdf(uri, titulo))
  }

  if (estado.fase === 'erro') {
    return (
      <View style={estilos.raiz}>
        <View style={estilos.aviso}>
          <Text style={estilos.avisoTitulo}>Não deu para ler aqui dentro</Text>
          <Text style={estilos.avisoTexto}>{estado.mensagem}</Text>
          <View style={estilos.avisoAcoes}>
            <Botao titulo="Abrir em outro app" onPress={() => void abrirLaFora()} />
            <Botao
              titulo="Tentar de novo"
              variante="secundario"
              onPress={() => setTentativa((n) => n + 1)}
            />
          </View>
          {erroExterno ? <Text style={estilos.erroExterno}>{erroExterno}</Text> : null}
        </View>
      </View>
    )
  }

  const desenhando = estado.fase === 'desenhando'
  const carregando = estado.fase !== 'pronto' && !(desenhando && estado.pagina > 0)

  return (
    <View style={estilos.raiz}>
      {estado.fase === 'desenhando' || estado.fase === 'pronto' ? (
        <WebView
          source={{ uri: estado.uri }}
          style={estilos.pagina}
          containerStyle={estilos.pagina}
          originWhitelist={['file://', 'about:blank']}
          onMessage={receber}
          // Nada de rede, nada de arquivo vizinho: tudo o que a página precisa está dentro
          // dela. Um leitor de documento não tem por que alcançar o disco nem a internet.
          javaScriptEnabled
          allowFileAccess={false}
          allowFileAccessFromFileURLs={false}
          allowUniversalAccessFromFileURLs={false}
          setSupportMultipleWindows={false}
          // Sem isto o pinch fica preso no que o RN acha da densidade da tela.
          scalesPageToFit={false}
          androidLayerType="hardware"
          // A folha de papel é branca; o fundo por trás é o do app, não o branco padrão do
          // motor — senão pisca branco antes de desenhar.
          backgroundColor={cores.fundoPapel}
        />
      ) : null}

      {carregando ? (
        <View style={estilos.veu}>
          <ActivityIndicator color={cores.ambar} />
          <Text style={estilos.veuTexto}>
            {estado.fase === 'baixando'
              ? 'Baixando o documento…'
              : estado.fase === 'montando'
                ? 'Preparando para leitura…'
                : 'Desenhando a primeira página…'}
          </Text>
        </View>
      ) : null}

      <View style={estilos.rodape}>
        <Text style={estilos.rodapeTexto}>
          {estado.fase === 'pronto'
            ? estado.truncado
              ? `${estado.paginas} páginas · só as primeiras foram desenhadas`
              : `${estado.paginas} ${estado.paginas === 1 ? 'página' : 'páginas'}`
            : desenhando && estado.paginas > 0
              ? `desenhando ${estado.pagina} de ${estado.paginas}`
              : '—'}
        </Text>
        <Pressable onPress={() => void abrirLaFora()} style={estilos.externo}>
          <Text style={estilos.externoTexto}>Abrir em outro app</Text>
        </Pressable>
      </View>
      {erroExterno ? <Text style={estilos.erroExterno}>{erroExterno}</Text> : null}
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundoPapel },
  pagina: { flex: 1, backgroundColor: cores.fundoPapel },

  veu: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: 'center',
    justifyContent: 'center',
    gap: espaco.sm,
    backgroundColor: cores.fundoPapel,
  },
  veuTexto: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoRotulo },

  rodape: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: espaco.md,
    paddingHorizontal: espaco.md,
    paddingVertical: espaco.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: cores.borda,
    backgroundColor: cores.fundo,
  },
  rodapeTexto: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoFraco, flexShrink: 1 },
  externo: {
    paddingHorizontal: espaco.md,
    paddingVertical: espaco.sm,
    borderRadius: raio.chip,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: cores.bordaForte,
    backgroundColor: cores.superficie,
  },
  externoTexto: { fontFamily: fontes.uiSemi, fontSize: 13, color: cores.textoCorpo },

  aviso: { flex: 1, justifyContent: 'center', padding: espaco.lg, gap: espaco.sm },
  avisoTitulo: tipo.secao,
  avisoTexto: { fontFamily: fontes.ui, fontSize: 14, color: cores.textoCorpo, lineHeight: 20 },
  avisoAcoes: { gap: espaco.sm, marginTop: espaco.sm },
  erroExterno: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: tons.parado,
    lineHeight: 17,
    paddingHorizontal: espaco.md,
    paddingBottom: espaco.sm,
  },
})
