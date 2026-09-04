/**
 * As fotos de uma ficha — a evidência do que o técnico viu.
 *
 * Existe porque faltava (04/09/2026). O dono: *"as tarefas não aparece foto em nenhuma"*. A
 * ficha trazia só a CONTAGEM, e contava do lugar errado: numa inspeção de checklist a foto é
 * anexada à RESPOSTA — "existem sinais de avaria?" e a foto do que se viu —, então o bloco do
 * equipamento vinha com zero enquanto havia dezenas guardadas nas perguntas.
 *
 * Duas decisões que não são detalhe:
 *
 * **A sessão vai em cabeçalho.** A imagem é servida por rota autenticada do BFF; token em
 * URL entra em log de servidor.
 *
 * **Miniatura na grade, original só ao tocar.** Uma ficha coletiva de vinte inversores tem
 * dezenas de fotos; baixar todas em tamanho cheio para desenhar quadrados de 90 px gastaria
 * a franquia de quem está em campo para não mostrar nada a mais.
 */

import { useState } from 'react'
import { ActivityIndicator, Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native'

import { baseURL, tokenDaSessao } from '@/lib/api'
import { cores, espaco, fontes, raio, tipo } from '@/theme/tokens'

export type FotoDaFicha = { id: number; legenda: string | null; url: string; thumb_url: string }

/** O endereço completo com a sessão — o BFF devolve o caminho, não a URL inteira. */
function fonte(caminho: string) {
  return {
    uri: caminho.startsWith('http') ? caminho : `${baseURL}${caminho}`,
    headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
  }
}

export function Fotos({ fotos, titulo }: { fotos: FotoDaFicha[]; titulo?: string }) {
  const [aberta, setAberta] = useState<FotoDaFicha | null>(null)
  if (!fotos.length) return null

  return (
    <View style={estilos.bloco}>
      {titulo ? <Text style={estilos.titulo}>{titulo}</Text> : null}
      <View style={estilos.grade}>
        {fotos.map((f) => (
          <Pressable key={f.id} onPress={() => setAberta(f)} style={estilos.celula}>
            <Image source={fonte(f.thumb_url)} style={estilos.miniatura} resizeMode="cover" />
          </Pressable>
        ))}
      </View>

      {aberta ? <Ampliada foto={aberta} onFechar={() => setAberta(null)} /> : null}
    </View>
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
  const [carregando, setCarregando] = useState(true)
  return (
    <Modal transparent animationType="fade" visible onRequestClose={onFechar}>
      <Pressable style={estilos.fundo} onPress={onFechar}>
        {carregando ? <ActivityIndicator color={cores.ambar} style={estilos.espera} /> : null}
        <Image
          source={fonte(foto.url)}
          style={estilos.cheia}
          resizeMode="contain"
          onLoadEnd={() => setCarregando(false)}
        />
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
  },
  miniatura: { width: '100%', height: '100%' },

  fundo: { flex: 1, backgroundColor: 'rgba(2,6,26,0.94)', alignItems: 'center', justifyContent: 'center', padding: espaco.md },
  espera: { position: 'absolute' },
  cheia: { width: '100%', height: '80%' },
  legenda: { ...tipo.legenda, color: cores.textoCorpo, marginTop: espaco.sm, textAlign: 'center' },
  dica: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco, marginTop: espaco.xs },
})
