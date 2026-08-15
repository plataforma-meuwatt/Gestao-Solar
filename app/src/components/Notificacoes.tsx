/**
 * Avisos no celular — o estado das DUAS permissões que precisam existir.
 *
 * O gestor concede o direito de receber; o Android concede o direito de mostrar. Faltando
 * qualquer uma, nada chega — e o sintoma é idêntico ("não recebo notificação"), o que faz
 * o dono cobrar a pessoa errada. Por isso as duas aparecem separadas, cada uma com a ação
 * que a destrava: a do sistema tem botão, a do gestor tem instrução de a quem pedir.
 *
 * O card não promete o que não pode cumprir: enquanto o aviso não estiver realmente ativo
 * ele diz o que falta, e não "quase lá".
 */

import { useCallback, useEffect, useState } from 'react'
import { Linking, StyleSheet, Text, View } from 'react-native'

import { Botao, Card, CabecalhoCard, Esqueleto, StatusChip } from '@/components/base'
import {
  estadoNoSistema,
  pedirERegistrar,
  registrarAparelho,
  temPermissao,
  usePermissoes,
  PERMISSAO_USINA_PARADA,
  type EstadoDoSistema,
} from '@/features/permissoes'
import { cores, espaco, fontes, tipo } from '@/theme/tokens'

export function Notificacoes() {
  const { dados, carregando } = usePermissoes()
  const [sistema, setSistema] = useState<EstadoDoSistema | null>(null)
  const [pedindo, setPedindo] = useState(false)

  const concedidaPeloGestor = temPermissao(dados, PERMISSAO_USINA_PARADA)

  useEffect(() => {
    let vivo = true
    void estadoNoSistema().then((e) => {
      if (vivo) setSistema(e)
    })
    return () => {
      vivo = false
    }
  }, [])

  /*
   * Reencosta o token sempre que as duas permissões estiverem de pé.
   *
   * O token do Expo muda sozinho — reinstalação, restauração de backup, atualização do
   * sistema. Sem reencostar, o aparelho continuaria na tabela com um token morto e o
   * dono pararia de receber sem nada na tela indicar por quê.
   */
  useEffect(() => {
    if (sistema === 'concedida' && concedidaPeloGestor) void registrarAparelho()
  }, [sistema, concedidaPeloGestor])

  const pedir = useCallback(async () => {
    setPedindo(true)
    try {
      setSistema(await pedirERegistrar())
    } finally {
      setPedindo(false)
    }
  }, [])

  const ativo = sistema === 'concedida' && concedidaPeloGestor

  return (
    <Card>
      <CabecalhoCard
        rotulo="Avisos no celular"
        direita={
          carregando && !dados ? undefined : (
            <StatusChip
              tom={ativo ? 'ok' : 'semDados'}
              texto={ativo ? 'Ativo' : 'Inativo'}
            />
          )
        }
      />

      {carregando && !dados ? (
        <Esqueleto altura={54} />
      ) : (
        <View style={estilos.miolo}>
          <Item
            titulo="Usina parada"
            descricao="Aviso quando um inversor da sua usina para de gerar, mesmo com o app fechado."
            liberado={concedidaPeloGestor}
            pendente="Ainda não liberado para você. Peça ao gestor da plataforma."
          />

          <Item
            titulo="Permissão do aparelho"
            descricao="O Android precisa autorizar o aplicativo a mostrar avisos."
            liberado={sistema === 'concedida'}
            pendente={
              sistema === 'indisponivel'
                ? 'Este ambiente não recebe avisos — só o aplicativo instalado no celular.'
                : sistema === 'negada'
                  ? 'Negado no sistema. É preciso reativar nos ajustes do aparelho.'
                  : 'Ainda não autorizado.'
            }
          />

          {sistema === 'nao_perguntado' ? (
            <View style={estilos.acao}>
              <Botao
                titulo={pedindo ? 'Pedindo…' : 'Autorizar avisos'}
                onPress={() => void pedir()}
                desabilitado={pedindo}
              />
            </View>
          ) : sistema === 'negada' ? (
            <View style={estilos.acao}>
              {/* `openSettings` abre a página DESTE app, não a lista geral de ajustes —
                  achar o aplicativo na lista é onde a maioria desiste. */}
              <Botao
                titulo="Abrir ajustes do aparelho"
                variante="secundario"
                onPress={() => void Linking.openSettings()}
              />
            </View>
          ) : null}

          {ativo ? (
            <Text style={estilos.rodape}>
              Tudo pronto. O aviso chega mesmo com o aplicativo fechado.
            </Text>
          ) : null}
        </View>
      )}
    </Card>
  )
}

function Item({
  titulo,
  descricao,
  liberado,
  pendente,
}: {
  titulo: string
  descricao: string
  liberado: boolean
  pendente: string
}) {
  return (
    <View style={estilos.item}>
      <View style={[estilos.marca, liberado ? estilos.marcaOk : estilos.marcaFalta]} />
      <View style={estilos.itemTexto}>
        <Text style={estilos.itemTitulo}>{titulo}</Text>
        <Text style={tipo.fraco}>{liberado ? descricao : pendente}</Text>
      </View>
    </View>
  )
}

const estilos = StyleSheet.create({
  miolo: { marginTop: espaco.sm, gap: espaco.sm },

  item: { flexDirection: 'row', gap: espaco.xs, alignItems: 'flex-start' },
  marca: { width: 8, height: 8, borderRadius: 4, marginTop: 5 },
  marcaOk: { backgroundColor: cores.ambar },
  marcaFalta: { backgroundColor: cores.bordaFraca },
  itemTexto: { flex: 1, gap: 1 },
  itemTitulo: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoForte },

  acao: { marginTop: espaco.xs },
  rodape: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco },
})
