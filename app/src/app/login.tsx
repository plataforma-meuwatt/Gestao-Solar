/**
 * Login.
 *
 * Entra-se com o **apelido**, não com o e-mail: a conta é do Gestão Solar, criada pelo
 * gestor no painel, e não a mesma dos sistemas por trás. Daí a linha de apoio sob o
 * botão — sem ela, o dono da usina tentaria o e-mail e a senha que já conhece.
 *
 * A linha nomeia os SERVIÇOS ("monitoramento", "manutenção"), nunca os produtos. Quem
 * entra aqui não tem conta neles, não sabe o nome deles e não tem a quem cobrar por eles;
 * ler um nome próprio na primeira tela do aplicativo só levanta uma pergunta que este
 * portal existe para não precisar responder. É a mesma régua do BFF, escrita em
 * `bff/tests/test_vocabulario_do_cliente.py`.
 *
 * No erro os campos NÃO são limpos. Refazer o apelido inteiro por causa de uma senha
 * errada é o tipo de atrito que faz o usuário desistir na segunda tentativa.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import {
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native'

import { Botao, Halo } from '@/components/base'
import { SeloGS } from '@/components/marca'
import { api, mensagemDeErro } from '@/lib/api'
import { useAuth, type DuasEtapas } from '@/store/auth'
import { cores, espaco, fontes, raio, tomAlpha, tons } from '@/theme/tokens'

export default function Login() {
  const entrar = useAuth((s) => s.entrar)
  const entrarComCodigo = useAuth((s) => s.entrarComCodigo)
  const entrarEmDemonstracao = useAuth((s) => s.entrarEmDemonstracao)
  // a conta usa a verificação em duas etapas: a senha está certa e falta o código do autenticador
  const [pedido, setPedido] = useState<DuasEtapas | null>(null)
  const [codigo, setCodigo] = useState('')
  const [apelido, setApelido] = useState('')
  const [senha, setSenha] = useState('')
  const [mostrarSenha, setMostrarSenha] = useState(false)
  const [focado, setFocado] = useState<'apelido' | 'senha' | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  const preenchido = apelido.trim().length > 0 && senha.length > 0
  // Em desenvolvimento o botão nunca fica travado: com os campos vazios ele entra em
  // demonstração, que é o único caminho enquanto o BFF não existe.
  const podeEntrar = (preenchido || __DEV__) && !carregando

  async function aoEntrar() {
    if (__DEV__ && !preenchido) {
      await entrarEmDemonstracao()
      router.replace('/(tabs)')
      return
    }

    setErro(null)
    setCarregando(true)
    try {
      if (pedido) {
        await entrarComCodigo(pedido.desafio, codigo)
      } else {
        const falta = await entrar(apelido.trim(), senha)
        if (falta) {
          setPedido(falta)
          setCodigo('')
          return
        }
      }
      router.replace('/(tabs)')
    } catch (e) {
      setErro(mensagemDeErro(e))
      // Sem servidor no ar, insistir na credencial não leva a lugar nenhum — a saída de
      // desenvolvimento fica logo abaixo do erro.
    } finally {
      setCarregando(false)
    }
  }

  /** O "esqueci a senha" (R12): o WhatsApp do GS com "esqueci a senha" escrito; o número vem da API (rota pública). */
  async function esqueciASenha() {
    try {
      const { data } = await api.get<{ whatsapp: string | null }>('/api/v1/auth/senha/canais')
      const numero = (data.whatsapp ?? '').replace(/\D/g, '')
      if (!numero) throw new Error('sem número')
      await Linking.openURL(`https://wa.me/${numero}?text=${encodeURIComponent('esqueci a senha')}`)
    } catch {
      setErro('Não deu para abrir o WhatsApp agora. Mande "esqueci a senha" ao WhatsApp do Gestão Solar pelo celular cadastrado.')
    }
  }

  /** Borda do campo: vermelha no erro, âmbar no foco, discreta em repouso. */
  const bordaCampo = (campo: 'apelido' | 'senha') => {
    if (erro && campo === 'senha') return tons.parado
    if (focado === campo) return cores.ambar
    return cores.borda
  }

  return (
    <KeyboardAvoidingView
      style={estilos.raiz}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Halo />
      <View style={estilos.miolo}>
        {/*
          A marca, e não só o nome escrito em duas cores.

          O selo é o mesmo do portal (`components/marca.tsx`), e é ele que o cliente
          reconhece antes de ler — na loja, na lista de apps do celular e aqui. O descritor
          abaixo diz o que o produto faz, que é o que uma tela de entrada precisa responder
          para quem abriu pela primeira vez.
        */}
        <View style={estilos.marcaArea}>
          <SeloGS tamanho={64} />
          <Text style={estilos.marca}>Gestão Solar</Text>
          <Text style={estilos.descritor}>CARTEIRA · GERAÇÃO · MANUTENÇÃO</Text>
        </View>

        {erro ? (
          <View style={estilos.faixaErro}>
            <View style={estilos.pontoErro} />
            <Text style={estilos.textoErro}>{erro}</Text>
          </View>
        ) : null}

        {pedido ? (
          <View style={[estilos.campos, carregando && estilos.camposTravados]}>
            {pedido.cadastrar ? (
              <View style={{ gap: 8 }}>
                <Text style={estilos.rotuloCampo}>Verificação em duas etapas</Text>
                <Text style={estilos.apoio}>
                  Esta conta passa a pedir, além da senha, um código do autenticador (Google Authenticator ou Microsoft
                  Authenticator). Toque abaixo para cadastrar o Gestão Solar nele, ou digite a chave no aplicativo.
                </Text>
                {pedido.otpauth ? (
                  <Botao titulo="Abrir no autenticador" onPress={() => void Linking.openURL(pedido.otpauth as string)} />
                ) : null}
                {pedido.segredo ? (
                  <Text selectable style={estilos.apoio}>
                    Chave: {pedido.segredo}
                  </Text>
                ) : null}
              </View>
            ) : (
              <Text style={estilos.apoio}>Digite o código de 6 números do autenticador deste celular.</Text>
            )}
            <View>
              <Text style={estilos.rotuloCampo}>Código do autenticador</Text>
              <TextInput
                style={[estilos.campo, { borderColor: focado ? cores.ambar : cores.borda }]}
                value={codigo}
                onChangeText={(t) => setCodigo(t.replace(/\D/g, '').slice(0, 6))}
                onFocus={() => setFocado('senha')}
                onBlur={() => setFocado(null)}
                keyboardType="number-pad"
                textContentType="oneTimeCode"
                autoComplete="sms-otp"
                editable={!carregando}
                placeholder="000000"
                placeholderTextColor={cores.textoFraco}
                onSubmitEditing={() => codigo.length === 6 && void aoEntrar()}
              />
            </View>
          </View>
        ) : (
        <View style={[estilos.campos, carregando && estilos.camposTravados]}>
          <View>
            <Text style={estilos.rotuloCampo}>Apelido</Text>
            <TextInput
              style={[estilos.campo, { borderColor: bordaCampo('apelido') }]}
              value={apelido}
              // Minúscula na hora de digitar, não só no envio: quem digita "Renan" e vê
              // "Renan" na tela não entende por que o servidor recusou.
              onChangeText={(t) => setApelido(t.toLowerCase())}
              onFocus={() => setFocado('apelido')}
              onBlur={() => setFocado(null)}
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="username"
              editable={!carregando}
              placeholder="seu.apelido"
              placeholderTextColor={cores.textoFraco}
            />
          </View>

          <View>
            <Text style={estilos.rotuloCampo}>Senha</Text>
            <View style={[estilos.campoSenha, { borderColor: bordaCampo('senha') }]}>
              <TextInput
                style={estilos.entradaSenha}
                value={senha}
                onChangeText={setSenha}
                onFocus={() => setFocado('senha')}
                onBlur={() => setFocado(null)}
                secureTextEntry={!mostrarSenha}
                editable={!carregando}
                onSubmitEditing={() => podeEntrar && void aoEntrar()}
              />
              <Pressable onPress={() => setMostrarSenha((v) => !v)} hitSlop={10}>
                <Text style={estilos.mostrar}>{mostrarSenha ? 'Ocultar' : 'Mostrar'}</Text>
              </Pressable>
            </View>
          </View>
        </View>
        )}

        {carregando ? (
          /* Botão desabilitado com "Entrando…", e não barra de progresso: a barra estava
             congelada em 40% — um número que nada media, encenando avanço. É a mesma
             espécie do "etapa 2 de 3" que saiu de Documentos. */
          <Botao titulo="Entrando…" desabilitado />
        ) : (
          <Botao
            titulo={pedido ? 'Entrar' : __DEV__ && !preenchido ? 'Entrar sem senha' : 'Entrar'}
            onPress={() => void aoEntrar()}
            desabilitado={pedido ? codigo.length !== 6 : !podeEntrar}
          />
        )}
        {pedido ? (
          <Pressable
            onPress={() => {
              setPedido(null)
              setErro(null)
            }}
            hitSlop={10}
          >
            <Text style={estilos.mostrar}>Voltar</Text>
          </Pressable>
        ) : null}

        <Text style={estilos.apoio}>
          {carregando
            ? 'Entrando…'
            : __DEV__ && !preenchido
              ? 'Modo desenvolvimento: entra sem servidor. As telas ficam vazias — não há mais dados de exemplo.'
              : 'Use o apelido e a senha que a Gestão Solar enviou. Não é o mesmo login dos sistemas de monitoramento e de manutenção.'}
        </Text>

        {/* "Entrar com Google" e "Esqueci minha senha" saíram daqui: os dois eram botões
            sem ação — o primeiro não tinha `onPress`, o segundo não tem fluxo no BFF. Um
            controle que não faz nada é pior do que a sua ausência: a pessoa toca, não
            acontece nada, e ela conclui que o aplicativo está quebrado. Voltam quando os
            fluxos existirem. A senha, hoje, é reposta pelo gestor no painel — e é isso
            que a linha abaixo diz. */}
        <View style={estilos.espacador} />
        <Pressable onPress={() => void esqueciASenha()} hitSlop={10}>
          <Text style={estilos.esqueci}>
            Esqueceu a senha? Toque aqui: o WhatsApp do Gestão Solar abre com a mensagem pronta, e o link para a senha
            nova chega no celular cadastrado.
          </Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo },
  miolo: { flex: 1, paddingHorizontal: espaco.lg, paddingBottom: 34 },

  marcaArea: { height: 200, alignItems: 'center', justifyContent: 'center', gap: 14 },
  marca: {
    fontFamily: fontes.uiForte,
    fontSize: 28,
    letterSpacing: -0.56,
    color: cores.textoForte,
  },
  // O descritor em Mono caixa alta com tracking largo — a mesma receita do rótulo de seção
  // do portal, e o que mais distingue a tipografia do Gestão Solar da do meuWatt.
  descritor: {
    fontFamily: fontes.mono,
    fontSize: 10.5,
    letterSpacing: 1.5,
    color: cores.textoRotulo,
  },

  faixaErro: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    backgroundColor: tomAlpha('parado', 0.1),
    borderWidth: 1,
    borderColor: tomAlpha('parado', 0.33),
    borderRadius: raio.campo,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginBottom: espaco.md,
  },
  pontoErro: { width: 10, height: 10, borderRadius: 5, backgroundColor: tons.parado, marginTop: 4 },
  textoErro: { flex: 1, fontFamily: fontes.uiMedio, fontSize: 13, lineHeight: 19, color: tons.parado },

  campos: { gap: 12 },
  camposTravados: { opacity: 0.5 },
  rotuloCampo: {
    fontFamily: fontes.uiMedio,
    fontSize: 12,
    color: cores.textoRotulo,
    marginBottom: 6,
  },
  campo: {
    height: 50,
    borderRadius: raio.campo,
    backgroundColor: cores.afundado,
    borderWidth: 1,
    paddingHorizontal: 14,
    fontFamily: fontes.ui,
    fontSize: 15,
    color: cores.textoCorpo,
  },
  campoSenha: {
    height: 50,
    borderRadius: raio.campo,
    backgroundColor: cores.afundado,
    borderWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
  },
  entradaSenha: {
    flex: 1,
    fontFamily: fontes.mono,
    fontSize: 15,
    color: cores.textoCorpo,
    letterSpacing: 2,
  },
  mostrar: { fontFamily: fontes.uiSemi, fontSize: 12.5, color: cores.textoAmbar },


  apoio: {
    fontFamily: fontes.ui,
    fontSize: 12,
    lineHeight: 18,
    color: cores.textoRotulo,
    textAlign: 'center',
    marginVertical: 12,
  },

  espacador: { flex: 1 },
  esqueci: {
    fontFamily: fontes.uiSemi,
    fontSize: 13.5,
    color: cores.textoAmbar,
    textAlign: 'center',
    paddingVertical: 12,
  },
})
