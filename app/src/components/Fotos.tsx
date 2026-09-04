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
 * **A sessão vai em cabeçalho.** A imagem é servida por rota autenticada do BFF; token em
 * URL entra em log de servidor.
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

import { useState } from 'react'
import { ActivityIndicator, Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native'

import { baseURL, tokenDaSessao } from '@/lib/api'
import { cores, espaco, fontes, raio, tipo } from '@/theme/tokens'

export type FotoDaFicha = { id: number; legenda: string | null; url: string; thumb_url: string }

/** Quantas miniaturas nascem carregando. O resto espera o toque em "ver todas". */
const DE_CARA = 6

/** O endereço completo com a sessão — o BFF devolve o caminho, não a URL inteira. */
function fonte(caminho: string) {
  return {
    uri: caminho.startsWith('http') ? caminho : `${baseURL}${caminho}`,
    headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
  }
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
  const [estado, setEstado] = useState<'carregando' | 'pronta' | 'erro'>('carregando')
  // Muda a cada tentativa: sem isto o componente reusa o resultado anterior e "tentar de
  // novo" não tenta nada.
  const [tentativa, setTentativa] = useState(0)

  if (estado === 'erro') {
    return (
      <Pressable
        style={[estilos.celula, estilos.falhou]}
        onPress={() => {
          setEstado('carregando')
          setTentativa((n) => n + 1)
        }}
      >
        <Text style={estilos.falhouTexto}>não carregou</Text>
        <Text style={estilos.maisDica}>tocar para tentar</Text>
      </Pressable>
    )
  }

  return (
    <Pressable onPress={onAbrir} style={estilos.celula}>
      <Image
        key={tentativa}
        source={fonte(foto.thumb_url)}
        style={estilos.miniatura}
        resizeMode="cover"
        onLoad={() => setEstado('pronta')}
        onError={() => setEstado('erro')}
      />
      {estado === 'carregando' ? (
        <View style={estilos.sobre}>
          <ActivityIndicator color={cores.ambar} size="small" />
        </View>
      ) : null}
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
  const [estado, setEstado] = useState<'carregando' | 'pronta' | 'erro'>('carregando')
  return (
    <Modal transparent animationType="fade" visible onRequestClose={onFechar}>
      <Pressable style={estilos.fundo} onPress={onFechar}>
        {estado === 'carregando' ? (
          <ActivityIndicator color={cores.ambar} style={estilos.espera} />
        ) : null}
        {estado === 'erro' ? (
          <Text style={estilos.erroCheia}>
            Não deu para carregar esta foto agora. Toque para fechar e tente de novo.
          </Text>
        ) : (
          <Image
            source={fonte(foto.url)}
            style={estilos.cheia}
            resizeMode="contain"
            onLoad={() => setEstado('pronta')}
            onError={() => setEstado('erro')}
          />
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
