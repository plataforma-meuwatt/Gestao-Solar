/**
 * Buscar atualização — as duas que existem, que são diferentes.
 *
 * **Atualização de conteúdo (OTA).** Baixa uma versão nova do JavaScript pelo EAS Update
 * e reinicia o aplicativo nela. Cobre tela, texto, regra de cálculo — a maior parte do
 * que muda no dia a dia. Não precisa de loja nem de instalar nada.
 *
 * **Versão nova do aplicativo (APK).** Quando muda alguma peça nativa — uma biblioteca
 * nova, permissão nova, versão do Expo — o OTA não alcança: o pacote instalado precisa
 * ser trocado. Aqui isso vira um aviso com o link para baixar.
 *
 * A distinção não é detalhe técnico exposto à toa: sem ela, "atualizar" não funciona
 * metade das vezes e ninguém entende por quê. Por isso a tela nomeia as duas coisas e diz
 * qual acabou de acontecer.
 *
 * Em desenvolvimento o `expo-updates` fica desligado (`isEnabled` falso) — o Metro já
 * recarrega a cada salvamento —, e a tela diz isso em vez de fingir que procurou.
 */

import * as Updates from 'expo-updates'
import { useState } from 'react'
import { Linking, StyleSheet, Text, View } from 'react-native'

import { Botao, Card, CabecalhoCard, Num } from '@/components/base'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

/** Onde baixar o pacote novo quando o OTA não bastar. */
const PAGINA_DE_BUILDS =
  'https://expo.dev/accounts/prnmarchesini/projects/gestao-solar/builds'

type Situacao =
  | { tipo: 'parado' }
  | { tipo: 'procurando' }
  | { tipo: 'baixando' }
  | { tipo: 'emDia' }
  | { tipo: 'aplicando' }
  | { tipo: 'erro'; mensagem: string }

export function Atualizacao() {
  const [situacao, setSituacao] = useState<Situacao>({ tipo: 'parado' })

  // `useUpdates` reflete o que o expo-updates sabe agora: qual pacote está rodando e se
  // já viu um mais novo.
  const { currentlyRunning, isUpdateAvailable, isUpdatePending } = Updates.useUpdates()

  async function procurar() {
    if (!Updates.isEnabled) {
      setSituacao({
        tipo: 'erro',
        mensagem:
          'As atualizações automáticas só valem no aplicativo instalado. Em desenvolvimento, quem recarrega é o Metro.',
      })
      return
    }

    try {
      setSituacao({ tipo: 'procurando' })
      const achou = await Updates.checkForUpdateAsync()

      if (!achou.isAvailable) {
        setSituacao({ tipo: 'emDia' })
        return
      }

      setSituacao({ tipo: 'baixando' })
      await Updates.fetchUpdateAsync()

      // `reloadAsync` reinicia na versão nova. É o único ponto que interrompe o uso, e
      // por isso só acontece depois de o pacote estar inteiro no aparelho.
      setSituacao({ tipo: 'aplicando' })
      await Updates.reloadAsync()
    } catch (e) {
      setSituacao({
        tipo: 'erro',
        mensagem: e instanceof Error ? e.message : 'Não foi possível buscar a atualização.',
      })
    }
  }

  const ocupado =
    situacao.tipo === 'procurando' ||
    situacao.tipo === 'baixando' ||
    situacao.tipo === 'aplicando'

  const canal = currentlyRunning.channel ?? (Updates.isEnabled ? '—' : 'desenvolvimento')
  const runtime = Updates.runtimeVersion ?? '—'

  return (
    <Card>
      <CabecalhoCard
        rotulo="Atualização"
        direita={
          <Text style={tipo.legenda}>
            versão <Num style={estilos.versao}>{Updates.runtimeVersion ?? '—'}</Num>
          </Text>
        }
      />

      <View style={estilos.miolo}>
        <Linha
          rotulo="Conteúdo rodando"
          valor={currentlyRunning.isEmbeddedLaunch ? 'o que veio no aplicativo' : 'atualização OTA'}
        />
        <Linha rotulo="Publicado em" valor={dataDoConteudo(currentlyRunning)} />
        <Linha rotulo="Identificador" valor={idCurto(currentlyRunning.updateId)} />
        <Linha rotulo="Canal" valor={canal} />

        {isUpdateAvailable || isUpdatePending ? (
          <View style={[estilos.aviso, { borderColor: tons.alerta }]}>
            <Text style={estilos.avisoTexto}>
              Há conteúdo novo esperando. Toque em Buscar atualização para aplicar.
            </Text>
          </View>
        ) : null}

        {situacao.tipo === 'emDia' ? (
          <View style={[estilos.aviso, { borderColor: tons.ok }]}>
            {/*
             * A frase precisa dizer ONDE procurou. "Tudo em dia" sozinho é ambíguo entre
             * "nada novo mesmo" e "publicaram no canal errado" — e em 15/08/2026 um OTA
             * publicado em `production` não alcançou este aparelho, que ouve `preview`,
             * enquanto a tela garantia que estava tudo certo.
             */}
            <Text style={estilos.avisoTexto}>
              Tudo em dia — nada novo no canal {canal}, versão {runtime}.
            </Text>
          </View>
        ) : null}

        {situacao.tipo === 'erro' ? (
          <View style={[estilos.aviso, { borderColor: tons.parado }]}>
            <Text style={estilos.avisoTexto}>{situacao.mensagem}</Text>
          </View>
        ) : null}

        <View style={estilos.acao}>
          <Botao
            titulo={
              situacao.tipo === 'procurando'
                ? 'Procurando…'
                : situacao.tipo === 'baixando'
                  ? 'Baixando…'
                  : situacao.tipo === 'aplicando'
                    ? 'Reiniciando…'
                    : 'Buscar atualização'
            }
            onPress={() => void procurar()}
            desabilitado={ocupado}
          />
        </View>

        <Text style={estilos.rodape}>
          Isso traz melhorias de tela e de cálculo. Quando mudar alguma peça interna do
          aplicativo, é preciso instalar um pacote novo — e aí o botão abaixo leva à
          página de downloads.
        </Text>

        <View style={estilos.acaoSecundaria}>
          <Botao
            titulo="Baixar versão nova do aplicativo"
            variante="secundario"
            onPress={() => void Linking.openURL(PAGINA_DE_BUILDS)}
          />
        </View>
      </View>
    </Card>
  )
}

/**
 * Data de publicação do pacote em execução.
 *
 * Quando o app roda o conteúdo embutido, `createdAt` é o instante em que o APK foi
 * montado — informação verdadeira e útil, então é exibida. Ausência vira "—": não
 * inventamos "atualizado agora" para um campo que o expo-updates não devolveu.
 */
function dataDoConteudo(atual: { createdAt?: Date }): string {
  const quando = atual.createdAt
  if (!quando) return '—'
  return quando.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * O `updateId` é um UUID — inteiro não cabe na linha e ninguém lê. Os 8 primeiros
 * caracteres bastam para casar com o Group ID que o `eas update` imprime ao publicar,
 * que é exatamente a conferência que se quer fazer daqui.
 */
function idCurto(id?: string): string {
  if (!id) return 'embutido no aplicativo'
  return id.slice(0, 8)
}

function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <View style={estilos.linha}>
      <Text style={tipo.legenda}>{rotulo}</Text>
      <Text style={estilos.linhaValor} numberOfLines={1}>
        {valor}
      </Text>
    </View>
  )
}

const estilos = StyleSheet.create({
  versao: { fontSize: 12, color: cores.textoCorpo },
  miolo: { marginTop: espaco.sm, gap: espaco.xs },

  linha: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  linhaValor: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoForte, flexShrink: 1 },

  aviso: {
    borderWidth: 1,
    borderRadius: 8,
    padding: espaco.sm,
    marginTop: espaco.xs,
    backgroundColor: cores.superficieElevada,
  },
  avisoTexto: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoCorpo, lineHeight: 17 },

  acao: { marginTop: espaco.sm },
  acaoSecundaria: { marginTop: espaco.xs },
  rodape: {
    fontFamily: fontes.ui,
    fontSize: 11,
    color: cores.textoRotulo,
    lineHeight: 16,
    marginTop: espaco.xs,
  },
})
