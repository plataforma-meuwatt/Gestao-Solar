/**
 * Login.
 *
 * A credencial é a que o usuário JÁ TEM no meuWatt ou no meuPlano — o BFF tenta nos dois e
 * basta um aceitar. Por isso a linha de apoio abaixo do botão: sem ela, o dono não sabe
 * qual senha digitar.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native'

import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, raio, tipo, tons } from '@/theme/tokens'

export default function Login() {
  const entrar = useAuth((s) => s.entrar)
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  const podeEntrar = email.trim().length > 0 && senha.length > 0 && !carregando

  async function aoEntrar() {
    setErro(null)
    setCarregando(true)
    try {
      await entrar(email.trim(), senha)
      router.replace('/(tabs)')
    } catch (e) {
      // Os campos NÃO são limpos: refazer o e-mail inteiro por causa de um erro de senha
      // é exatamente o tipo de atrito que faz o usuário desistir.
      setErro(mensagemDeErro(e))
    } finally {
      setCarregando(false)
    }
  }

  return (
    <KeyboardAvoidingView
      style={estilos.raiz}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={estilos.miolo}>
        <Text style={estilos.marca}>Gestão Solar</Text>

        {erro ? (
          <View style={estilos.faixaErro}>
            <Text style={estilos.textoErro}>{erro}</Text>
          </View>
        ) : null}

        <TextInput
          style={estilos.campo}
          placeholder="E-mail"
          placeholderTextColor={cores.textoRotulo}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          editable={!carregando}
        />
        <TextInput
          style={estilos.campo}
          placeholder="Senha"
          placeholderTextColor={cores.textoRotulo}
          value={senha}
          onChangeText={setSenha}
          secureTextEntry
          editable={!carregando}
          onSubmitEditing={() => podeEntrar && void aoEntrar()}
        />

        <Pressable
          style={[estilos.botao, !podeEntrar && estilos.botaoInativo]}
          onPress={() => void aoEntrar()}
          disabled={!podeEntrar}
        >
          {carregando ? (
            <ActivityIndicator color={cores.sobreAmbar} />
          ) : (
            <Text style={estilos.textoBotao}>Entrar</Text>
          )}
        </Pressable>

        <Text style={estilos.apoio}>Use o mesmo login do meuWatt ou do meuPlano.</Text>
      </View>
    </KeyboardAvoidingView>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo, justifyContent: 'center' },
  miolo: { padding: espaco.lg, gap: espaco.md },
  marca: {
    ...tipo.titulo,
    fontFamily: fontes.uiForte,
    fontSize: 32,
    textAlign: 'center',
    marginBottom: espaco.lg,
  },
  campo: {
    backgroundColor: cores.afundado,
    borderColor: cores.borda,
    borderWidth: 1,
    borderRadius: raio.campo,
    paddingHorizontal: espaco.md,
    height: 52,
    color: cores.textoForte,
    fontFamily: fontes.ui,
    fontSize: 16,
  },
  botao: {
    backgroundColor: cores.ambar,
    borderRadius: raio.campo,
    height: 52,
    alignItems: 'center',
    justifyContent: 'center',
  },
  botaoInativo: { opacity: 0.4 },
  textoBotao: { fontFamily: fontes.uiSemi, fontSize: 16, color: cores.sobreAmbar },
  faixaErro: {
    backgroundColor: `${tons.parado}1A`,
    borderColor: `${tons.parado}55`,
    borderWidth: 1,
    borderRadius: raio.campo,
    padding: espaco.sm,
  },
  textoErro: { fontFamily: fontes.ui, fontSize: 14, color: tons.parado },
  apoio: { ...tipo.rotulo, textAlign: 'center' },
})
