/**
 * As fotos de uma ficha — a evidência do que o técnico viu.
 *
 * Existe porque faltava (04/09/2026). O dono: *"as tarefas não aparece foto em nenhuma"*. A
 * ficha trazia só a CONTAGEM, e contava do lugar errado: numa inspeção de checklist a foto é
 * anexada à RESPOSTA — "existem sinais de avaria?" e a foto do que se viu —, então o bloco do
 * equipamento vinha com zero enquanto havia dezenas guardadas nas perguntas.
 *
 * Quatro decisões que não são detalhe:
 *
 * **A imagem é BAIXADA, não apontada.** A rota é autenticada e a sessão vai em cabeçalho —
 * token em URL entra em log de servidor. O `<Image>` aceita `headers` no `source`, e no
 * aparelho do dono nenhuma miniatura carregava assim; quem sabidamente manda o cabeçalho é o
 * `fetch`, por onde o aplicativo inteiro conversa com o servidor. Então `lib/imagens` traz o
 * arquivo para o disco e o `<Image>` lê `file://`, onde não há sessão nenhuma para carregar.
 *
 * **Miniatura na grade, original só ao tocar.** Uma ficha coletiva de vinte inversores tem
 * dezenas de fotos; baixar todas em tamanho cheio para desenhar quadrados de 90 px gastaria
 * a franquia de quem está em campo para não mostrar nada a mais.
 *
 * **Poucas de cada vez.** Sessenta e uma miniaturas pedidas ao mesmo tempo formam uma fila
 * que o servidor não vence, e o que aparece na tela é o quadrado escuro de imagem que não
 * carregou — em TODAS, inclusive nas que teriam vindo. Seis por bloco, e o resto sob um toque.
 *
 * **Falha de imagem se explica.** Um quadrado preto não diz se a foto sumiu, se a sessão
 * venceu ou se a rede caiu; o quadro diz "não carregou" e aceita um toque para tentar de novo.
 */

import { useEffect, useState } from 'react'
import { ActivityIndicator, Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native'

import { arquivoDaImagem } from '@/lib/imagens'
import { cores, espaco, fontes, raio, tipo } from '@/theme/tokens'

export type FotoDaFicha = { id: number; legenda: string | null; url: string; thumb_url: string }

/** Quantas miniaturas nascem carregando. O resto espera o toque em "ver todas". */
const DE_CARA = 6

/**
 * O arquivo local da imagem: `null` enquanto baixa, o motivo em texto quando não vem.
 *
 * `tentativa` no fim das dependências é o que faz "tocar para tentar" tentar de novo — sem
 * ela, o efeito não roda outra vez e o botão seria enfeite.
 */
function useImagem(caminho: string, chave: string, tentativa: number) {
  const [uri, setUri] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    let vivo = true
    setErro(null)
    arquivoDaImagem(caminho, chave)
      .then((local) => {
        if (vivo) setUri(local)
      })
      .catch((e: unknown) => {
        if (vivo) setErro(e instanceof Error ? e.message : 'não deu para carregar')
      })
    return () => {
      vivo = false
    }
  }, [caminho, chave, tentativa])

  return { uri, erro }
}

export function Fotos({ fotos, titulo }: { fotos: FotoDaFicha[] | number; titulo?: string }) {
  const [aberta, setAberta] = useState<FotoDaFicha | null>(null)
  const [todas, setTodas] = useState(false)
  /*
   * O tipo aceita `number` de propósito.
   *
   * OTA e deploy do servidor não chegam juntos: por alguns minutos o aplicativo novo conversa
   * com o BFF antigo, onde `fotos` ainda é a CONTAGEM. Sem esta porta, o `.map` de um número
   * derrubaria a ficha inteira — e a tela quebrada duraria mais que a janela do deploy, porque
   * o cache de leitura guarda a resposta antiga em disco.
   */
  const lista = Array.isArray(fotos) ? fotos : []
  if (!lista.length) return null

  const visiveis = todas ? lista : lista.slice(0, DE_CARA)
  const escondidas = lista.length - visiveis.length

  return (
    <View style={estilos.bloco}>
      {titulo ? (
        <Text style={estilos.titulo}>
          {titulo} · {lista.length}
        </Text>
      ) : null}

      <View style={estilos.grade}>
        {visiveis.map((f) => (
          <Miniatura key={f.id} foto={f} onAbrir={() => setAberta(f)} />
        ))}

        {escondidas > 0 ? (
          <Pressable style={[estilos.celula, estilos.mais]} onPress={() => setTodas(true)}>
            <Text style={estilos.maisTexto}>+{escondidas}</Text>
            <Text style={estilos.maisDica}>ver todas</Text>
          </Pressable>
        ) : null}
      </View>

      {aberta ? <Ampliada foto={aberta} onFechar={() => setAberta(null)} /> : null}
    </View>
  )
}

/** Um quadrado da grade, com os três estados que ele pode ter. */
function Miniatura({ foto, onAbrir }: { foto: FotoDaFicha; onAbrir: () => void }) {
  const [tentativa, setTentativa] = useState(0)
  const { uri, erro } = useImagem(foto.thumb_url, `${foto.id}-thumb`, tentativa)

  if (erro) {
    return (
      <Pressable
        style={[estilos.celula, estilos.falhou]}
        onPress={() => setTentativa((n) => n + 1)}
      >
        {/* O MOTIVO, não "falhou". Um quadrado que só diz que deu errado manda todo mundo
            adivinhar entre sessão vencida, foto apagada e rede caída. */}
        <Text style={estilos.falhouTexto} numberOfLines={3}>
          {erro}
        </Text>
        <Text style={estilos.maisDica}>tocar para tentar</Text>
      </Pressable>
    )
  }

  return (
    <Pressable onPress={onAbrir} style={estilos.celula} disabled={!uri}>
      {uri ? (
        <Image source={{ uri }} style={estilos.miniatura} resizeMode="cover" />
      ) : (
        <ActivityIndicator color={cores.ambar} size="small" />
      )}
    </Pressable>
  )
}

/**
 * A foto em tamanho cheio.
 *
 * Sem pinça de propósito: é um `Modal`, e gesto dentro de folha já custou caro neste
 * aplicativo. `resizeMode="contain"` mostra a foto inteira, que é o que se quer de uma
 * evidência — cortar para preencher a tela esconderia justamente a borda onde costuma estar
 * o dano.
 */
function Ampliada({ foto, onFechar }: { foto: FotoDaFicha; onFechar: () => void }) {
  const { uri, erro } = useImagem(foto.url, `${foto.id}-cheia`, 0)
  return (
    <Modal transparent animationType="fade" visible onRequestClose={onFechar}>
      <Pressable style={estilos.fundo} onPress={onFechar}>
        {erro ? (
          <Text style={estilos.erroCheia}>Não deu para carregar esta foto: {erro}.</Text>
        ) : uri ? (
          <Image source={{ uri }} style={estilos.cheia} resizeMode="contain" />
        ) : (
          <ActivityIndicator color={cores.ambar} style={estilos.espera} />
        )}
        {foto.legenda ? <Text style={estilos.legenda}>{foto.legenda}</Text> : null}
        <Text style={estilos.dica}>toque para fechar</Text>
      </Pressable>
    </Modal>
  )
}

const LADO = 92

const estilos = StyleSheet.create({
  bloco: { marginTop: espaco.sm, gap: 6 },
  titulo: { fontFamily: fontes.uiForte, fontSize: 12, color: cores.textoRotulo, letterSpacing: 0.3 },
  grade: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  celula: {
    width: LADO,
    height: LADO,
    borderRadius: raio.chip,
    overflow: 'hidden',
    backgroundColor: cores.superficie,
    borderWidth: 1,
    borderColor: cores.borda,
    alignItems: 'center',
    justifyContent: 'center',
  },
  miniatura: { width: '100%', height: '100%' },
  sobre: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center' },

  mais: { gap: 2 },
  maisTexto: { fontFamily: fontes.uiForte, fontSize: 16, color: cores.ambar },
  maisDica: { fontFamily: fontes.ui, fontSize: 10, color: cores.textoFraco },

  falhou: { gap: 2, paddingHorizontal: 4 },
  falhouTexto: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo, textAlign: 'center' },

  fundo: {
    flex: 1,
    backgroundColor: 'rgba(2,6,26,0.94)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: espaco.md,
  },
  espera: { position: 'absolute' },
  cheia: { width: '100%', height: '80%' },
  erroCheia: { ...tipo.fraco, textAlign: 'center', paddingHorizontal: espaco.lg },
  legenda: { ...tipo.legenda, color: cores.textoCorpo, marginTop: espaco.sm, textAlign: 'center' },
  dica: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco, marginTop: espaco.xs },
})
