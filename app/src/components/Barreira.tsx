/**
 * O que aparece quando uma tela quebra.
 *
 * Sem isto, um erro de renderização no React Native derruba a árvore inteira e o que
 * sobra é **tela preta** — indistinguível de app travado, de splash que não saiu e de
 * rede lenta. Quem está com o celular na mão não tem como dizer qual dos três é, e quem
 * recebe o relato ("ficou preto") também não.
 *
 * A barreira troca isso por uma tela que diz o que aconteceu e oferece tentar de novo.
 * Em desenvolvimento mostra a pilha; no aparelho do cliente, só a mensagem — rastro de
 * pilha não ajuda quem não vai depurar, e assusta.
 */

import { Component, type ReactNode } from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'

import { Botao } from '@/components/base'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

type Props = { children: ReactNode; nome?: string }
type Estado = { erro: Error | null }

export class Barreira extends Component<Props, Estado> {
  state: Estado = { erro: null }

  static getDerivedStateFromError(erro: Error): Estado {
    return { erro }
  }

  componentDidCatch(erro: Error) {
    // Vai para o console do Metro em desenvolvimento e para o log do dispositivo no
    // aparelho — é o que permite descobrir o que quebrou sem ter o celular em mãos.
    console.error(`[barreira${this.props.nome ? ` · ${this.props.nome}` : ''}]`, erro)
  }

  render() {
    const { erro } = this.state
    if (!erro) return this.props.children

    return (
      <View style={estilos.raiz}>
        <ScrollView contentContainerStyle={estilos.conteudo}>
          <View style={estilos.marca} />
          <Text style={tipo.secao}>Esta tela não abriu</Text>
          <Text style={estilos.descricao}>
            Aconteceu um erro ao desenhar {this.props.nome ?? 'a tela'}. O resto do
            aplicativo continua funcionando.
          </Text>

          <View style={estilos.caixa}>
            <Text style={estilos.mensagem}>{erro.message || String(erro)}</Text>
          </View>

          {__DEV__ && erro.stack ? (
            <View style={estilos.caixa}>
              <Text style={estilos.pilha}>{erro.stack.split('\n').slice(0, 12).join('\n')}</Text>
            </View>
          ) : null}

          <View style={estilos.acao}>
            <Botao titulo="Tentar de novo" onPress={() => this.setState({ erro: null })} />
          </View>
        </ScrollView>
      </View>
    )
  }
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo },
  conteudo: { padding: espaco.lg, gap: espaco.md, justifyContent: 'center', flexGrow: 1 },
  marca: {
    width: 34,
    height: 34,
    borderRadius: 17,
    borderWidth: 2,
    borderColor: tons.parado,
    marginBottom: espaco.xs,
  },
  descricao: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoCorpo, lineHeight: 19 },
  caixa: {
    backgroundColor: cores.superficie,
    borderColor: cores.borda,
    borderWidth: 1,
    borderRadius: 10,
    padding: espaco.sm,
  },
  mensagem: { fontFamily: fontes.mono, fontSize: 12, color: cores.textoForte },
  pilha: { fontFamily: fontes.mono, fontSize: 10, color: cores.textoRotulo, lineHeight: 15 },
  acao: { marginTop: espaco.xs },
})
