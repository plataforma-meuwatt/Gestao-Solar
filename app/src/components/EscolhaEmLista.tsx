/**
 * Escolha de uma opção por LISTA SUSPENSA PESQUISÁVEL.
 *
 * Regra do produto, herdada do meuPlano e válida em toda a interface: escolher opção é lista
 * suspensa ou segmentado — **nunca uma fileira de chips**. Vale de duas a duzentas opções.
 * A fileira de pílulas de usina que existia na aba Manutenção é o caso que motivou este
 * componente: com sete usinas ela já rolava horizontalmente e escondia metade das opções
 * fora da tela, que é o defeito que um chip sempre tem quando a lista cresce.
 *
 * O campo de busca só aparece a partir de `MINIMO_PARA_BUSCAR` opções: uma caixa de texto
 * sobre três linhas é mobília, e no celular ela ainda levanta o teclado por nada.
 *
 * A contagem ao lado de cada opção é deliberada — ela diz para onde a escolha leva ANTES do
 * toque. Opção com zero **continua na lista**: sumir seria pior, porque quem procura por ela
 * conclui que o aplicativo perdeu o dado.
 */

import { useState } from 'react'
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native'

import { Chevron, Num } from '@/components/base'
import { Folha } from '@/components/folha'
import { cores, espaco, fontes, raio, TOQUE_MIN } from '@/theme/tokens'

/** A partir de quantas opções vale a pena oferecer busca. */
const MINIMO_PARA_BUSCAR = 8

export type Opcao = {
  /** Identidade estável. `null` é uma escolha legítima ("Todas"), não ausência. */
  valor: string | null
  rotulo: string
  /** Quantas linhas esta opção mostraria. Omitido = a lista não conta nada. */
  contagem?: number
}

/** Tira acento e caixa: quem digita "porto" acha "Porto Ferreira" e "PÔRTO". */
function normalizar(t: string): string {
  return t
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
}

export function EscolhaEmLista({
  rotulo,
  opcoes,
  valor,
  aoEscolher,
  titulo,
}: {
  /** O que se está escolhendo ("Usina", "Situação") — fica acima do campo fechado. */
  rotulo: string
  opcoes: Opcao[]
  valor: string | null
  aoEscolher: (valor: string | null) => void
  /** Título da folha. Sem ele, usa o rótulo. */
  titulo?: string
}) {
  const [aberta, setAberta] = useState(false)
  const [busca, setBusca] = useState('')

  const escolhida = opcoes.find((o) => o.valor === valor)
  const alvo = normalizar(busca)
  const visiveis = alvo ? opcoes.filter((o) => normalizar(o.rotulo).includes(alvo)) : opcoes

  return (
    <View style={estilos.campo}>
      <Text style={estilos.rotulo}>{rotulo}</Text>
      <Pressable
        style={estilos.fechado}
        onPress={() => {
          setBusca('')
          setAberta(true)
        }}
        accessibilityRole="button"
        accessibilityLabel={`${rotulo}: ${escolhida?.rotulo ?? 'escolher'}`}
      >
        <Text style={estilos.valor} numberOfLines={1}>
          {escolhida?.rotulo ?? '—'}
        </Text>
        <View style={estilos.seta} />
      </Pressable>

      <Folha visivel={aberta} aoFechar={() => setAberta(false)} titulo={titulo ?? rotulo}>
        {opcoes.length >= MINIMO_PARA_BUSCAR ? (
          <TextInput
            style={estilos.busca}
            value={busca}
            onChangeText={setBusca}
            placeholder="Buscar"
            placeholderTextColor={cores.textoFraco}
            autoCorrect={false}
            autoCapitalize="none"
          />
        ) : null}

        {visiveis.length === 0 ? (
          // A lei de nunca deixar a tela muda vale aqui dentro também.
          <Text style={estilos.semResultado}>
            Nada com “{busca}”. Apague a busca para ver as {opcoes.length} opções.
          </Text>
        ) : (
          visiveis.map((o, i) => {
            const marcada = o.valor === valor
            return (
              <Pressable
                key={o.valor ?? `__todas__${i}`}
                style={[estilos.opcao, i > 0 && estilos.opcaoComDivisoria]}
                onPress={() => {
                  aoEscolher(o.valor)
                  setAberta(false)
                }}
                accessibilityRole="button"
                accessibilityState={{ selected: marcada }}
              >
                <Text
                  style={[estilos.opcaoTexto, marcada && estilos.opcaoTextoMarcada]}
                  numberOfLines={2}
                >
                  {o.rotulo}
                </Text>
                {o.contagem !== undefined ? (
                  <Num style={estilos.contagem}>{o.contagem}</Num>
                ) : null}
                {marcada ? <Text style={estilos.marca}>✓</Text> : <Chevron />}
              </Pressable>
            )
          })
        )}
      </Folha>
    </View>
  )
}

const estilos = StyleSheet.create({
  campo: { flex: 1, minWidth: 0 },
  rotulo: {
    fontFamily: fontes.ui,
    fontSize: 10,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: cores.textoRotulo,
    marginBottom: 4,
  },
  fechado: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: espaco.xs,
    minHeight: TOQUE_MIN - 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: raio.campo,
    borderWidth: 1,
    borderColor: cores.borda,
    backgroundColor: cores.superficie,
  },
  valor: { flex: 1, fontFamily: fontes.uiMedio, fontSize: 13, color: cores.textoForte },
  // A mesma seta para baixo do seletor de lista do sistema de design.
  seta: {
    width: 7,
    height: 7,
    borderRightWidth: 1.5,
    borderBottomWidth: 1.5,
    borderColor: cores.textoRotulo,
    transform: [{ rotate: '45deg' }],
    marginTop: -3,
  },

  busca: {
    marginTop: espaco.sm,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: raio.campo,
    borderWidth: 1,
    borderColor: cores.borda,
    backgroundColor: cores.afundado,
    color: cores.textoForte,
    fontFamily: fontes.ui,
    fontSize: 14,
  },
  semResultado: {
    fontFamily: fontes.ui,
    fontSize: 12.5,
    color: cores.textoFraco,
    lineHeight: 18,
    paddingVertical: espaco.md,
  },

  opcao: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: espaco.sm,
    paddingVertical: 12,
    minHeight: TOQUE_MIN,
  },
  opcaoComDivisoria: { borderTopWidth: 1, borderTopColor: cores.bordaFraca },
  opcaoTexto: { flex: 1, fontFamily: fontes.ui, fontSize: 14, color: cores.textoCorpo },
  opcaoTextoMarcada: { fontFamily: fontes.uiSemi, color: cores.textoForte },
  contagem: { fontSize: 12, color: cores.textoFraco },
  marca: { fontFamily: fontes.uiForte, fontSize: 14, color: cores.ambar },
})
