/**
 * Perfil — o que o avatar do topo abre. Entra deslizando da esquerda, como no design.
 */

import { router } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'

import { Card, LinhaNavegacao } from '@/components/base'
import { Tela } from '@/components/Tela'
import { usuario } from '@/features/exemplo'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tons } from '@/theme/tokens'

export default function Perfil() {
  const dados = useAuth((s) => s.usuario)
  const sair = useAuth((s) => s.sair)

  async function aoSair() {
    await sair()
    router.replace('/login')
  }

  return (
    <Tela titulo="Perfil" voltar>
      <View style={estilos.cabecalho}>
        <View style={estilos.avatar}>
          <Text style={estilos.avatarTexto}>{usuario.iniciais}</Text>
        </View>
        <Text style={estilos.nome}>{dados?.nome ?? 'Renan Moraes'}</Text>
        <Text style={estilos.email}>{dados?.email ?? 'renan.moraes@solaris.com.br'}</Text>
        {dados?.empresa ? <Text style={estilos.empresa}>{dados.empresa}</Text> : null}
      </View>

      <Card semPadding>
        <LinhaNavegacao titulo="Notificações" primeiro onPress={() => router.push('/notificacoes')} />
        <LinhaNavegacao titulo="Novidades" />
        <LinhaNavegacao titulo="Configurações" />
        <LinhaNavegacao titulo="Ajuda" />
      </Card>

      <Text style={estilos.sair} onPress={() => void aoSair()}>
        Sair
      </Text>
    </Tela>
  )
}

const estilos = StyleSheet.create({
  cabecalho: { alignItems: 'center', gap: espaco.xs, paddingVertical: espaco.md },
  avatar: {
    width: 88,
    height: 88,
    borderRadius: 44,
    borderWidth: 1,
    borderColor: cores.ambar,
    backgroundColor: cores.superficieElevada,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: espaco.sm,
  },
  avatarTexto: { fontFamily: fontes.uiSemi, fontSize: 28, color: cores.textoAmbar },
  nome: { fontFamily: fontes.uiSemi, fontSize: 20, color: cores.textoForte },
  email: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoRotulo },
  empresa: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoFraco },

  sair: {
    fontFamily: fontes.uiSemi,
    fontSize: 15,
    color: tons.parado,
    textAlign: 'center',
    paddingVertical: espaco.md,
  },
})
