/**
 * Documentos — onde o dono pega qualquer papel sem pedir para ninguém.
 *
 * Três origens diferentes atrás do mesmo segmentado:
 * - **Relatórios** já vêm publicados pelo meuWatt (o PDF está guardado), então trazem
 *   tamanho e podem estar disponíveis offline.
 * - **Ordens de serviço** e **cronograma** são gerados na hora pelo meuPlano; por isso
 *   não anunciam tamanho — ele só existe depois de gerar.
 *
 * Um fechamento mensal são duas peças que andam juntas (Relatório de Geração + Anexo de
 * Paradas). O card agrupa as duas sob a competência em vez de soltá-las na lista, senão
 * o dono não entende que uma é anexo da outra.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { Botao, Card, EstadoVazio, Num, Segmentado, SeletorLista } from '@/components/base'
import { BotaoFlutuante, CampoFolha, Folha, LinhaPdf } from '@/components/folha'
import { Tela } from '@/components/Tela'
import { fechamentos, tiposRelatorio, usinas, usuario } from '@/features/exemplo'
import { ambarAlpha, cores, espaco, fontes, tomAlpha, tons } from '@/theme/tokens'

const ABAS = ['Relatórios', 'Ordens de serviço', 'Cronograma']

/** Estado da folha de geração: escolhendo, trabalhando ou falhou. */
type EstadoGeracao = 'fechada' | 'escolhendo' | 'gerando' | 'falhou'

export default function Documentos() {
  const [aba, setAba] = useState(0)
  const [usina, setUsina] = useState('Todas as usinas')
  const [geracao, setGeracao] = useState<EstadoGeracao>('fechada')

  // Só a aba de relatórios tem conteúdo por ora; OS e cronograma vêm do meuPlano e entram
  // na Fase 4. O estado vazio diz isso ao usuário em vez de mostrar uma tela morta.
  const temConteudo = aba === 0

  return (
    <Tela
      titulo="Documentos"
      subtitulo="fechamentos, ordens de serviço e cronograma"
      avatar={{ iniciais: usuario.iniciais, onPress: () => router.push('/perfil') }}
      semRolagem
    >
      <View style={estilos.filtros}>
        <Segmentado opcoes={ABAS} ativo={aba} onEscolher={setAba} />
        <SeletorLista
          valor={usina}
          onPress={() =>
            setUsina((atual) => (atual === 'Todas as usinas' ? usinas[2].nome : 'Todas as usinas'))
          }
        />
      </View>

      {temConteudo ? (
        <View style={estilos.lista}>
          {fechamentos.map((f) => (
            <Card key={f.id} semPadding>
              <View style={estilos.cabecalhoFechamento}>
                <Text style={estilos.tituloFechamento}>Fechamento de {f.competencia}</Text>
                <Text style={estilos.subFechamento}>
                  {f.usina} · emitido em <Num style={estilos.dataEmissao}>{f.emitidoEm}</Num>
                </Text>
              </View>
              {f.pecas.map((p) => (
                <LinhaPdf
                  key={p.nome}
                  nome={p.nome}
                  tamanho={p.tamanho}
                  offline={p.offline}
                  onPress={() => router.push(`/documento/${f.id}`)}
                />
              ))}
            </Card>
          ))}
        </View>
      ) : (
        <EstadoVazio
          titulo={aba === 1 ? 'Nenhuma ordem de serviço' : 'Nenhum cronograma'}
          descricao={`${usina} não tem documento neste filtro. Ordens de serviço e cronograma vêm do meuPlano e entram na Fase 4.`}
        />
      )}

      <BotaoFlutuante onPress={() => setGeracao('escolhendo')} />
      <FolhaGerarRelatorio estado={geracao} setEstado={setGeracao} />
    </Tela>
  )
}

/**
 * A folha de gerar relatório tem três momentos, e todos importam: escolher, esperar e
 * falhar. O PDF sob demanda passa por um Chromium headless no BFF e leva alguns
 * segundos — sem o estado de espera o usuário acha que travou e toca de novo.
 */
function FolhaGerarRelatorio({
  estado,
  setEstado,
}: {
  estado: EstadoGeracao
  setEstado: (e: EstadoGeracao) => void
}) {
  const [tipoIdx, setTipoIdx] = useState(1)

  if (estado === 'falhou') {
    return (
      <Folha visivel aoFechar={() => setEstado('fechada')} cabecalho={<View />}>
        <View style={estilos.falha}>
          <View style={estilos.falhaCirculo}>
            <View style={estilos.falhaMiolo} />
          </View>
          <Text style={estilos.falhaTitulo}>O relatório não ficou pronto</Text>
          <Text style={estilos.falhaTexto}>
            A geração parou no meio. Normalmente é a conexão. Seus dados de julho continuam
            salvos — nada se perdeu.
          </Text>
        </View>
        <View style={estilos.falhaBotoes}>
          <Botao titulo="Tentar de novo" onPress={() => setEstado('gerando')} />
          <Botao
            titulo="Voltar aos documentos"
            variante="secundario"
            onPress={() => setEstado('fechada')}
          />
        </View>
      </Folha>
    )
  }

  if (estado === 'gerando') {
    return (
      <Folha
        visivel
        aoFechar={() => setEstado('fechada')}
        titulo="Gerar relatório"
        apoio={`${tiposRelatorio[tipoIdx]} · Porto Ferreira · julho de 2026`}
      >
        <View style={estilos.travado} pointerEvents="none">
          <CampoFolha rotulo="Tipo">
            <Segmentado opcoes={tiposRelatorio} ativo={tipoIdx} onEscolher={() => {}} />
          </CampoFolha>
          <CampoFolha rotulo="Usina">
            <SeletorLista valor="Porto Ferreira" />
          </CampoFolha>
        </View>

        <View style={estilos.progressoArea}>
          <View style={estilos.progressoTrilho}>
            <View style={estilos.progressoPreenchido} />
          </View>
          <View style={estilos.progressoLinha}>
            <Text style={estilos.progressoTexto}>Montando o relatório…</Text>
            <Num style={estilos.progressoEtapa}>etapa 2 de 3</Num>
          </View>
          <Text style={estilos.progressoNota}>
            Leva alguns segundos. Você pode sair desta tela — avisamos quando ficar pronto.
          </Text>
        </View>
      </Folha>
    )
  }

  return (
    <Folha
      visivel={estado === 'escolhendo'}
      aoFechar={() => setEstado('fechada')}
      titulo="Gerar relatório"
      apoio="o PDF fica salvo em Documentos"
    >
      <CampoFolha rotulo="Tipo">
        <Segmentado opcoes={tiposRelatorio} ativo={tipoIdx} onEscolher={setTipoIdx} />
      </CampoFolha>
      <CampoFolha rotulo="Usina">
        <SeletorLista valor="Porto Ferreira" />
      </CampoFolha>
      <CampoFolha
        rotulo="Competência"
        nota="Agosto ainda está em curso — o fechamento sai em 01/09."
      >
        <SeletorLista valor="Julho de 2026" />
      </CampoFolha>
      <View style={estilos.acaoFolha}>
        <Botao titulo="Gerar PDF" onPress={() => setEstado('gerando')} />
      </View>
    </Folha>
  )
}

const estilos = StyleSheet.create({
  filtros: { paddingHorizontal: espaco.md, paddingTop: 14, paddingBottom: 10, gap: 10 },
  lista: { paddingHorizontal: espaco.md, paddingTop: 6, gap: 12, flex: 1 },

  cabecalhoFechamento: { paddingHorizontal: espaco.md, paddingTop: 13, paddingBottom: 11 },
  tituloFechamento: { fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte },
  subFechamento: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 3 },
  dataEmissao: { fontSize: 12, color: cores.textoRotulo },

  travado: { opacity: 0.45 },

  progressoArea: { marginTop: 22 },
  progressoTrilho: {
    height: 52,
    borderRadius: 12,
    backgroundColor: ambarAlpha(0.18),
    borderWidth: 1,
    borderColor: ambarAlpha(0.33),
    overflow: 'hidden',
  },
  progressoPreenchido: { height: '100%', width: '62%', backgroundColor: cores.ambar },
  progressoLinha: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    marginTop: 12,
  },
  progressoTexto: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoCorpo },
  progressoEtapa: { fontSize: 12.5, color: cores.textoRotulo },
  progressoNota: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco, marginTop: 6 },

  acaoFolha: { marginTop: espaco.lg },

  falha: { alignItems: 'center', gap: 14, paddingHorizontal: espaco.sm, paddingTop: 10 },
  falhaCirculo: {
    width: 72,
    height: 72,
    borderRadius: 36,
    borderWidth: 1,
    borderColor: tomAlpha('parado', 0.33),
    backgroundColor: tomAlpha('parado', 0.1),
    alignItems: 'center',
    justifyContent: 'center',
  },
  falhaMiolo: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 2,
    borderColor: tons.parado,
  },
  falhaTitulo: { fontFamily: fontes.uiForte, fontSize: 19, color: cores.textoForte },
  falhaTexto: {
    fontFamily: fontes.ui,
    fontSize: 13.5,
    lineHeight: 21,
    color: cores.textoRotulo,
    textAlign: 'center',
  },
  falhaBotoes: { gap: 10, marginTop: 22 },
})
