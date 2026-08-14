/**
 * Documentos — onde o dono pega qualquer papel sem pedir para ninguém.
 *
 * Um fechamento são duas peças que andam juntas (Relatório de Geração + Anexo de Paradas).
 * O card agrupa as duas sob o período, senão o dono não entende que uma é anexo da outra.
 *
 * O que saiu desta tela, e por quê:
 *
 * - **A folha "Gerar relatório"** (tipo, usina, competência, "etapa 2 de 3", barra em 62%).
 *   Não existe fila, job nem endpoint de progresso em lugar nenhum — era uma animação
 *   encenando trabalho que ninguém estava fazendo.
 * - **Tamanho do arquivo e selo "offline"**. Nenhum schema carrega bytes; o meuWatt guarda
 *   nome e tipo. Um "2,4 MB" inventado é pior do que nenhum número.
 * - **As abas Ordens de serviço e Cronograma.** Esses PDFs são gerados sob demanda pelo
 *   meuPlano; enquanto não houver rota no BFF, uma aba vazia é mais honesta do que uma
 *   lista falsa — e a tela diz o que falta.
 */

import { router } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'

import { Card, Esqueleto, EstadoVazio, Num } from '@/components/base'
import { LinhaPdf } from '@/components/folha'
import { Tela } from '@/components/Tela'
import { useDocumentos, type Documento } from '@/features/documentos'
import { dataPorExtenso } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo } from '@/theme/tokens'

const NOME_DA_PECA: Record<string, string> = {
  geracao: 'Relatório de Geração',
  paradas: 'Anexo de Paradas',
}

function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

export default function Documentos() {
  const { dados, carregando, erro, offlineDesde, recarregar } = useDocumentos()
  const usuario = useAuth((s) => s.usuario)

  const lista = dados?.documentos ?? []

  return (
    <Tela
      titulo="Documentos"
      subtitulo="relatórios publicados pelas suas usinas"
      avatar={{ iniciais: iniciaisDe(usuario?.nome), onPress: () => router.push('/perfil') }}
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {carregando ? (
        <>
          {[0, 1].map((i) => (
            <Card key={i}>
              <Esqueleto largura="50%" altura={15} forte />
              <View style={{ marginTop: 14, gap: 10 }}>
                <Esqueleto altura={16} />
                <Esqueleto altura={16} />
              </View>
            </Card>
          ))}
        </>
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : lista.length === 0 ? (
        <EstadoVazio
          titulo="Nenhum relatório publicado"
          descricao={
            dados?.aviso ??
            'Quando a equipe publicar um relatório das suas usinas, ele aparece aqui.'
          }
        />
      ) : (
        lista.map((d) => <CardDocumento key={d.id} documento={d} />)
      )}
    </Tela>
  )
}

function CardDocumento({ documento: d }: { documento: Documento }) {
  return (
    <Card semPadding>
      <View style={estilos.cabecalho}>
        <View style={estilos.cabecalhoMiolo}>
          <Text style={estilos.titulo}>{d.nome}</Text>
          <Text style={estilos.sub}>
            {d.usina} · {d.periodo.toLowerCase()}
          </Text>
        </View>
        <Text style={tipo.legenda}>
          <Num style={estilos.data}>{dataPorExtenso(d.publicado_em)}</Num>
        </Text>
      </View>

      {d.arquivos.length === 0 ? (
        <Text style={estilos.semArquivo}>Sem arquivo anexado.</Text>
      ) : (
        d.arquivos.map((a) => (
          <LinhaPdf
            key={a.tipo}
            nome={NOME_DA_PECA[a.tipo] ?? a.nome}
            onPress={() => router.push(`/documento/${d.id}?tipo=${a.tipo}`)}
          />
        ))
      )}
    </Card>
  )
}

const estilos = StyleSheet.create({
  cabecalho: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    paddingHorizontal: espaco.md,
    paddingTop: 14,
    paddingBottom: 10,
  },
  cabecalhoMiolo: { flex: 1 },
  titulo: { fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte },
  sub: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 3 },
  data: { fontSize: 11.5, color: cores.textoRotulo },
  semArquivo: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoRotulo,
    paddingHorizontal: espaco.md,
    paddingBottom: 14,
  },
})
