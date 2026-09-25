/**
 * Relatórios — onde o dono pega qualquer papel sem pedir para ninguém.
 *
 * A aba se chamava **Documentos**, e o rótulo era o menor dos problemas: "documento" é o
 * que o portal chama de anexo de pendência, e a aba nunca teve anexo nenhum. O que vive
 * aqui são os fechamentos que a equipe publica — relatório é o nome certo, e desfaz a
 * ambiguidade com `manutencao/pendencias/{cid}/documentos/{did}`.
 *
 * **Duas vistas, e esta é a de baixo.** A ABA é a grade do ano (usina × mês), por pedido do
 * dono; esta é o ACERVO — cronológico, com filtro de usina e de mês, alcançado pela linha
 * no fim da grade. Não é um segmento lá dentro, e muito menos uma sexta aba: a barra tem
 * cinco e responde "que assunto?", não "que tela?".
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

import { Card, Esqueleto, EstadoVazio, Num } from '@/components/base'
import { EscolhaEmLista } from '@/components/EscolhaEmLista'
import { LinhaPdf } from '@/components/folha'
import { Tela } from '@/components/Tela'
import {
  acervo,
  agruparPorGaveta,
  dataDoCartao,
  detalheDaPeca,
  detalheDoMensal,
  ehCartaoMensal,
  frasePecaAusente,
  recorte,
  rotuloDaPeca,
  rotuloDoMensal,
  subtituloDaAba,
  useRelatorios,
  vazioDaLista,
  type CartaoMensal,
  type Relatorio,
} from '@/features/relatorios'
import { dataPorExtenso } from '@/lib/format'
import { cores, espaco, fontes, tipo } from '@/theme/tokens'

export default function AcervoDeRelatorios() {
  const { dados, carregando, erro, frescor, recarregar } = useRelatorios()
  const [usinaEscolhida, setUsina] = useState<string | null>(null)
  const [gavetaEscolhida, setGaveta] = useState<string | null>(null)

  // As duas famílias numa lista só, com a ordem do servidor preservada. A composição é do
  // BFF (uma leitura, uma chave de cache): pedir o mensal daqui seria sete conexões e a
  // quebra do arquivo em disco de quem está no campo.
  const lista = acervo(dados)
  const rec = recorte(lista, usinaEscolhida, gavetaEscolhida)
  const vazio = vazioDaLista(dados?.aviso, dados?.aviso_mensais)

  return (
    <Tela
      titulo="Relatórios publicados"
      subtitulo={lista.length > 0 ? subtituloDaAba(rec) : undefined}
      voltar
      frescor={frescor}
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
          {lista.length === 0 ? (
            <EstadoVazio
              tom={vazio.ponte ? 'parado' : 'semDados'}
              titulo={vazio.titulo}
              descricao={vazio.descricao}
            />
          ) : (
            <>
              {/* O aviso com lista cheia é escopo parcial: uma usina respondeu, outra não.
                  São DOIS campos, um por família — nunca um só com a família na prosa, que
                  foi o atalho que obrigou o app a arrancar prefixo com expressão regular. */}
              {dados?.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}
              {dados?.aviso_mensais ? (
                <Text style={estilos.aviso}>{dados.aviso_mensais}</Text>
              ) : null}

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
                  {g.itens.map((item) =>
                    ehCartaoMensal(item) ? (
                      // A chave do cartão é TEXTO e a do fechamento é número: o id 14 do
                      // meuPlano e o 14 do monitoramento convivem na mesma gaveta.
                      <CardMensal key={item.id} cartao={item} />
                    ) : (
                      <CardRelatorio key={item.id} relatorio={item} />
                    ),
                  )}
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

/**
 * O relatório mensal de MANUTENÇÃO — um cartão por (usina × mês), com uma linha por peça.
 *
 * O título diz "Manutenção" porque o cartão vizinho, na mesma gaveta, é o fechamento de
 * GERAÇÃO da mesma usina e do mesmo mês: sem a palavra, dois cartões parecidos respondem à
 * mesma pergunta e o dono abre o errado. São dois sistemas, dois ciclos de publicação e
 * dois acervos — o que eles têm em comum é a competência, e é por ela que estão juntos.
 *
 * **Duas linhas, nunca um segmentado nem um chip.** Técnico e executivo não são modos de um
 * documento: são dois PDFs, de dois motores. A forma é a mesma das peças do fechamento
 * logo acima, e a ordem — executivo primeiro — é a que o servidor manda, igual no portal.
 *
 * **Cada linha diz o próprio nome** ("Relatório executivo" / "Relatório técnico") e, abaixo,
 * para quem foi escrita — as mesmas palavras do portal. Antes as duas se chamavam
 * "Relatório de manutenção" e só um rótulo miúdo as separava: dois títulos idênticos na
 * mesma rolagem fazem abrir o errado.
 *
 * A data é uma só e vem rotulada: `liberado_em`, dita "publicado". `aprovado_por`,
 * `aprovado_em` e `apurado_em` não chegam até aqui de propósito — o primeiro é nome de
 * funcionário da executora, e os outros dois respondem "quando os números foram
 * calculados", que não é "de quando é este documento".
 */
function CardMensal({ cartao }: { cartao: CartaoMensal }) {
  const publicado = dataDoCartao(cartao)

  return (
    <Card semPadding>
      <View style={estilos.cabecalho}>
        <View style={estilos.cabecalhoMiolo}>
          <Text style={estilos.titulo}>Manutenção — {cartao.usina}</Text>
          <Text style={estilos.sub}>relatório mensal</Text>
        </View>
        <View style={estilos.publicado}>
          <Text style={tipo.legenda}>publicado</Text>
          {/* Sem data declarada é travessão — nunca a competência fazendo as vezes dela. */}
          <Num style={estilos.data}>{publicado ? dataPorExtenso(publicado) : '—'}</Num>
        </View>
      </View>

      {cartao.pecas.map((peca) => (
        <LinhaPdf
          key={peca.id}
          nome={rotuloDoMensal(peca.tipo)}
          tamanho={detalheDoMensal(peca)}
          onPress={() =>
            router.push(
              `/relatorio/${peca.id}?tipo=${encodeURIComponent(peca.tipo)}` +
                `&nome=${encodeURIComponent(rotuloDoMensal(peca.tipo))}` +
                `&usina=${encodeURIComponent(cartao.usina)}` +
                `&competencia=${encodeURIComponent(cartao.competencia)}`,
            )
          }
        />
      ))}
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
