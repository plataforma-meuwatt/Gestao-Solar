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

import { router } from 'expo-router'
import { Component, type ReactNode } from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'

import { Botao } from '@/components/base'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

type Props = { children: ReactNode; nome?: string }
type Estado = { erro: Error | null; pilha: boolean }

/** O último erro que a barreira pegou — para a tela de Perfil poder mostrá-lo depois. */
export let ultimoErro: { quando: Date; mensagem: string; pilha?: string } | null = null

export class Barreira extends Component<Props, Estado> {
  state: Estado = { erro: null, pilha: false }

  static getDerivedStateFromError(erro: Error): Estado {
    return { erro, pilha: false }
  }

  componentDidCatch(erro: Error) {
    // Vai para o console do Metro em desenvolvimento e para o log do dispositivo no
    // aparelho — é o que permite descobrir o que quebrou sem ter o celular em mãos.
    console.error(`[barreira${this.props.nome ? ` · ${this.props.nome}` : ''}]`, erro)
    // E fica guardado: quem está com o aparelho na mão costuma tocar em voltar antes de ler a
    // mensagem, e aí não sobra rastro nenhum de que houve um erro.
    ultimoErro = { quando: new Date(), mensagem: erro.message || String(erro), pilha: erro.stack }
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

          {/*
            * A pilha aparece no aparelho do cliente também — atrás de um toque.
            *
            * A regra antiga ("rastro de pilha assusta") vale para quem não pediu; mas quando
            * o dono diz que uma tela não abre, essa é a ÚNICA informação que diz ONDE.
            * Escondida atrás de "detalhes técnicos", não assusta ninguém e sobrevive ao
            * relato por telefone.
            */}
          {erro.stack ? (
            <Pressable onPress={() => this.setState({ pilha: !this.state.pilha })} hitSlop={8}>
              <Text style={estilos.link}>
                {this.state.pilha ? 'ocultar detalhes técnicos' : 'ver detalhes técnicos'}
              </Text>
            </Pressable>
          ) : null}

          {this.state.pilha && erro.stack ? (
            <View style={estilos.caixa}>
              <Text style={estilos.pilha} selectable>
                {erro.stack.split('\n').slice(0, 14).join('\n')}
              </Text>
            </View>
          ) : null}

          <View style={estilos.acao}>
            <Botao titulo="Tentar de novo" onPress={() => this.setState({ erro: null })} />
          </View>

          {/*
            * SAIR DAQUI. Sem este botão a barreira é uma armadilha: ela substitui a árvore
            * inteira — abas inclusive — e "tentar de novo" redesenha a mesma tela quebrada.
            * Quem estava só olhando uma usina fica sem caminho de volta e conclui que o
            * aplicativo travou. Foi assim que um erro numa tela virou "o app fecha".
            */}
          <View style={estilos.acaoSecundaria}>
            <Botao
              titulo="Voltar ao início"
              variante="secundario"
              onPress={() => {
                this.setState({ erro: null })
                router.replace('/')
              }}
            />
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
  acaoSecundaria: { marginTop: -espaco.xs },
  link: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoRotulo, textDecorationLine: 'underline' },
})
