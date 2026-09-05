/**
 * Relatórios — onde o dono pega qualquer papel sem pedir para ninguém.
 *
 * A aba se chamava **Documentos**, e o rótulo era o menor dos problemas: "documento" é o
 * que o portal chama de anexo de pendência, e a aba nunca teve anexo nenhum. O que vive
 * aqui são os fechamentos que a equipe publica — relatório é o nome certo, e desfaz a
 * ambiguidade com `manutencao/pendencias/{cid}/documentos/{did}`.
 *
 * **Duas vistas, uma aba.** Esta é o ACERVO: cronológico, com filtro de usina e de mês. A
 * outra é a grade do ano (usina × mês), e ela é uma tela EMPURRADA — não um segmento aqui
 * dentro, e muito menos uma sexta aba. Motivo medido: a grade custa alguns segundos e uma
 * resposta de fan-out por usina; quem abriu a aba para pegar o PDF de agosto não pode
 * pagar por isso. A barra tem cinco abas e responde "que assunto?", não "que tela?".
 *
 * **O mês sai da competência, nunca da publicação.** Os fechamentos 35 e 36 cobrem agosto
 * e foram publicados em 5 de setembro: agrupar pelo campo com que a lista vem ordenada
 * poria agosto na gaveta de setembro. A régua mora no servidor (`competencia`) e o espelho
 * do cliente fatia a string — `new Date('2026-08-01')` é meia-noite UTC e volta para
 * julho no Brasil. Ver `features/relatorios.ts`.
 *
 * O que **não** está aqui, e por quê:
 *
 * - **A folha "Gerar relatório"** (tipo, usina, competência, "etapa 2 de 3", barra em 62%).
 *   Não existe fila, job nem endpoint de progresso em lugar nenhum — era uma animação
 *   encenando trabalho que ninguém estava fazendo.
 * - **O degrau intersticial** entre o card e o PDF. Ele nunca existiu por necessidade:
 *   existia porque a WebView não renderizava PDF. Com o leitor embutido, o card abre o
 *   documento em um toque.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { Card, CabecalhoCard, Esqueleto, EstadoVazio, LinhaNavegacao, Num } from '@/components/base'
import { EscolhaEmLista } from '@/components/EscolhaEmLista'
import { LinhaPdf } from '@/components/folha'
import { Tela } from '@/components/Tela'
import {
  agruparPorGaveta,
  detalheDaPeca,
  frasePecaAusente,
  recorte,
  rotuloDaPeca,
  subtituloDaAba,
  useRelatorios,
  vazioDaLista,
  type Relatorio,
} from '@/features/relatorios'
import { dataPorExtenso } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo } from '@/theme/tokens'

function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

export default function Relatorios() {
  const { dados, carregando, erro, offlineDesde, recarregar } = useRelatorios()
  const usuario = useAuth((s) => s.usuario)
  const [usinaEscolhida, setUsina] = useState<string | null>(null)
  const [gavetaEscolhida, setGaveta] = useState<string | null>(null)

  const lista = dados?.documentos ?? []
  const rec = recorte(lista, usinaEscolhida, gavetaEscolhida)
  const vazio = vazioDaLista(dados?.aviso)

  return (
    <Tela
      titulo="Relatórios"
      subtitulo={lista.length > 0 ? subtituloDaAba(rec) : undefined}
      avatar={{ iniciais: iniciaisDe(usuario?.nome), onPress: () => router.push('/perfil') }}
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {carregando ? (
        <>
          {[0, 1].map((i) => (
            <Card key={i}>
              <Esqueleto largura="50%" altura={15} forte />
              <View style={estilos.espacoEsqueleto}>
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
      ) : (
        <>
          {/* Fixo, e antes de tudo: a grade do ano responde "o que já tenho deste ano?",
              que é a pergunta que traz o dono aqui em dezembro — e continua valendo quando
              o acervo publicado está vazio, porque a manutenção é montada sob demanda. */}
          <Card>
            <CabecalhoCard rotulo="O ano inteiro" />
            <LinhaNavegacao
              titulo="Ver o ano, mês a mês"
              onPress={() => router.push('/relatorios/ano')}
              primeiro
            />
          </Card>

          {lista.length === 0 ? (
            <EstadoVazio
              tom={vazio.ponte ? 'parado' : 'semDados'}
              titulo={vazio.titulo}
              descricao={vazio.descricao}
            />
          ) : (
            <>
              {/* O aviso com lista cheia é escopo parcial: uma usina respondeu, outra não. */}
              {dados?.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}

              {/* Lista suspensa pesquisável com contagem, nunca uma fileira de chips (regra
                  do produto). Um filtro de uma opção só é enfeite: só aparece a partir de
                  duas — as opções saem dos próprios relatórios, então nenhuma tem zero. */}
              {rec.opcoesDeUsina.length > 2 || rec.opcoesDeGaveta.length > 2 ? (
                <View style={estilos.filtros}>
                  {rec.opcoesDeUsina.length > 2 ? (
                    <EscolhaEmLista
                      rotulo="Usina"
                      titulo="Ver os relatórios de qual usina"
                      valor={rec.usina}
                      aoEscolher={setUsina}
                      opcoes={rec.opcoesDeUsina}
                    />
                  ) : null}
                  {rec.opcoesDeGaveta.length > 2 ? (
                    <EscolhaEmLista
                      rotulo="Mês"
                      titulo="De que período"
                      valor={rec.gaveta}
                      aoEscolher={setGaveta}
                      opcoes={rec.opcoesDeGaveta}
                    />
                  ) : null}
                </View>
              ) : null}

              {/* A escolha caiu porque não havia nada atrás dela. A tela diz — em vez de
                  desenhar uma lista que não corresponde ao filtro que está no campo. */}
              {rec.ajuste ? <Text style={estilos.ajuste}>{rec.ajuste}</Text> : null}

              {agruparPorGaveta(rec.visiveis).map((g) => (
                <View key={g.chave}>
                  <Text style={estilos.gaveta}>{g.rotulo}</Text>
                  {g.itens.map((r) => (
                    <CardRelatorio key={r.id} relatorio={r} />
                  ))}
                </View>
              ))}
            </>
          )}
        </>
      )}
    </Tela>
  )
}

function CardRelatorio({ relatorio: r }: { relatorio: Relatorio }) {
  return (
    <Card semPadding>
      <View style={estilos.cabecalho}>
        <View style={estilos.cabecalhoMiolo}>
          <Text style={estilos.titulo}>{r.nome}</Text>
          <Text style={estilos.sub}>
            {r.usina} · {r.periodo.toLowerCase()}
          </Text>
        </View>
        {/* A data da PUBLICAÇÃO, dita como tal: o período coberto é o cabeçalho do grupo,
            e sem o rótulo os dois números pareceriam responder à mesma pergunta. */}
        <View style={estilos.publicado}>
          <Text style={tipo.legenda}>publicado</Text>
          <Num style={estilos.data}>{dataPorExtenso(r.publicado_em)}</Num>
        </View>
      </View>

      {r.arquivos.length === 0 ? (
        <Text style={estilos.semArquivo}>{frasePecaAusente()}</Text>
      ) : (
        r.arquivos.map((a) => (
          <LinhaPdf
            key={a.tipo}
            nome={rotuloDaPeca(a)}
            tamanho={detalheDaPeca(a)}
            onPress={() => router.push(`/relatorio/${r.id}?tipo=${a.tipo}`)}
          />
        ))
      )}
    </Card>
  )
}

const estilos = StyleSheet.create({
  espacoEsqueleto: { marginTop: 14, gap: 10 },
  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },

  filtros: {
    flexDirection: 'row',
    gap: espaco.sm,
    paddingHorizontal: espaco.xs,
    paddingBottom: espaco.xs,
  },
  ajuste: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    color: cores.textoAmbar,
    lineHeight: 17,
    paddingHorizontal: espaco.xs,
    paddingBottom: espaco.xs,
  },

  gaveta: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoRotulo,
    marginTop: espaco.sm,
    marginBottom: 2,
    paddingHorizontal: espaco.xs,
  },

  cabecalho: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    paddingHorizontal: espaco.md,
    paddingTop: 14,
    paddingBottom: 10,
  },
  cabecalhoMiolo: { flex: 1 },
  publicado: { alignItems: 'flex-end' },
  titulo: { fontFamily: fontes.uiSemi, fontSize: 15, color: cores.textoForte },
  sub: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 3 },
  data: { fontSize: 11.5, color: cores.textoRotulo },
  semArquivo: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoFraco,
    lineHeight: 18,
    paddingHorizontal: espaco.md,
    paddingBottom: 14,
  },
})
