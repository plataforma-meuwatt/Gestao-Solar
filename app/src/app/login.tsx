/**
 * Login.
 *
 * A credencial é a que o usuário JÁ TEM no meuWatt ou no meuPlano — o BFF tenta nos dois
 * e basta um aceitar. Daí a linha de apoio sob o botão: sem ela, o dono não sabe qual
 * senha digitar.
 *
 * No erro os campos NÃO são limpos. Refazer o e-mail inteiro por causa de uma senha
 * errada é o tipo de atrito que faz o usuário desistir na segunda tentativa.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native'

import { Botao, Halo } from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'
import { ambarAlpha, cores, espaco, fontes, raio, tomAlpha, tons } from '@/theme/tokens'

export default function Login() {
  const entrar = useAuth((s) => s.entrar)
  const entrarEmDemonstracao = useAuth((s) => s.entrarEmDemonstracao)
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [mostrarSenha, setMostrarSenha] = useState(false)
  const [focado, setFocado] = useState<'email' | 'senha' | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  const preenchido = email.trim().length > 0 && senha.length > 0
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
      await entrar(email.trim(), senha)
      router.replace('/(tabs)')
    } catch (e) {
      setErro(mensagemDeErro(e))
      // Sem servidor no ar, insistir na credencial não leva a lugar nenhum — a saída de
      // desenvolvimento fica logo abaixo do erro.
    } finally {
      setCarregando(false)
    }
  }

  /** Borda do campo: vermelha no erro, âmbar no foco, discreta em repouso. */
  const bordaCampo = (campo: 'email' | 'senha') => {
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
        <View style={estilos.marcaArea}>
          <Text style={estilos.marca}>
            Gestão <Text style={estilos.marcaAcento}>Solar</Text>
          </Text>
        </View>

        {erro ? (
          <View style={estilos.faixaErro}>
            <View style={estilos.pontoErro} />
            <Text style={estilos.textoErro}>{erro}</Text>
          </View>
        ) : null}

        <View style={[estilos.campos, carregando && estilos.camposTravados]}>
          <View>
            <Text style={estilos.rotuloCampo}>E-mail</Text>
            <TextInput
              style={[estilos.campo, { borderColor: bordaCampo('email') }]}
              value={email}
              onChangeText={setEmail}
              onFocus={() => setFocado('email')}
              onBlur={() => setFocado(null)}
              autoCapitalize="none"
              autoComplete="email"
              keyboardType="email-address"
              editable={!carregando}
              placeholder="voce@empresa.com.br"
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

        {carregando ? (
          <View style={estilos.progresso}>
            <View style={estilos.progressoPreenchido} />
          </View>
        ) : (
          <Botao
            titulo={__DEV__ && !preenchido ? 'Entrar sem senha' : 'Entrar'}
            onPress={() => void aoEntrar()}
            desabilitado={!podeEntrar}
          />
        )}

        <Text style={estilos.apoio}>
          {carregando
            ? 'Entrando…'
            : __DEV__ && !preenchido
              ? 'Modo desenvolvimento: entra com dados de exemplo, sem servidor.'
              : 'Use o mesmo login do meuWatt ou do meuPlano.'}
        </Text>

        {!carregando ? (
          <Botao titulo="Entrar com Google" variante="secundario" />
        ) : null}

        <View style={estilos.espacador} />
        <Text style={estilos.esqueci}>Esqueci minha senha</Text>
      </View>
    </KeyboardAvoidingView>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo },
  miolo: { flex: 1, paddingHorizontal: espaco.lg, paddingBottom: 34 },

  marcaArea: { height: 190, alignItems: 'center', justifyContent: 'center' },
  marca: {
    fontFamily: fontes.uiForte,
    fontSize: 28,
    letterSpacing: -0.56,
    color: cores.textoForte,
  },
  marcaAcento: { color: cores.ambar },

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

  progresso: {
    height: 52,
    borderRadius: raio.campo,
    marginTop: espaco.md,
    backgroundColor: ambarAlpha(0.18),
    borderWidth: 1,
    borderColor: ambarAlpha(0.33),
    overflow: 'hidden',
    justifyContent: 'center',
  },
  progressoPreenchido: { position: 'absolute', top: 0, bottom: 0, left: 0, width: '40%', backgroundColor: cores.ambar },

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
