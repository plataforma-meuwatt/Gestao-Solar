/**
 * O cronograma de manutenção do contrato, como o dono o lê.
 *
 * É a resposta para "a manutenção que eu contratei está sendo feita?" — não OS por OS,
 * mas o ano inteiro de uma vez: cada linha é uma atividade do contrato, cada coluna um
 * mês, e a marca diz o que aconteceu.
 *
 * **Doze meses a partir da âncora do CONTRATO, não de janeiro.** O de Porto Ferreira vai
 * de 2026-08 a 2027-07. Desenhar Jan→Dez encaixaria as marcas nas colunas erradas.
 *
 * **A marca vem do servidor, e o servidor a repassa do meuPlano.** Aquela cor é
 * conformidade calculada contra o histórico do ATIVO, não contra contagem de tarefas
 * (regra máxima do meuPlano). Nada é recalculado aqui: o dono precisa ver o mesmo número
 * nos dois produtos.
 *
 * **✓ e ~ são coisas diferentes.** `feito` é executado; `dispensado` é uma dispensa
 * registrada com motivo, que sai da conta daquele mês por decisão de alguém. Apagar essa
 * diferença — desenhar as duas como ✓ — era exatamente o risco que o meuPlano recusou
 * correr, e não vamos reintroduzi-lo na última tela da cadeia.
 *
 * A grade rola na horizontal porque doze colunas legíveis não cabem em 390 px, e
 * encolher a fonte até caber é como se perde a leitura de relance que a tela existe para
 * dar. A coluna do nome fica fixa à esquerda.
 */

import { useLocalSearchParams } from 'expo-router'
import { ScrollView, StyleSheet, Text, View } from 'react-native'

import { AbrirPdf } from '@/components/AbrirPdf'
import { CabecalhoCard, Card, Esqueleto, EstadoVazio, Num } from '@/components/base'
import { Tela } from '@/components/Tela'
import {
  urlDoPdfDoCronograma,
  useCronograma,
  type Celula,
  type LinhaCronograma,
} from '@/features/manutencao'
import { inteiro } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

const LARGURA_NOME = 150
const LARGURA_MES = 34

/** "2026-08" → "ago". A grade não tem espaço para o mês inteiro. */
const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

function mesCurto(yyyyMm: string): string {
  const m = Number(yyyyMm.slice(5, 7))
  return MESES_CURTOS[m - 1] ?? yyyyMm.slice(5, 7)
}

/** O ano só aparece quando vira — é o que mostra que o contrato atravessa dezembro. */
function anoDe(yyyyMm: string): string {
  return yyyyMm.slice(2, 4)
}

export default function Cronograma() {
  const { usinaId } = useLocalSearchParams<{ usinaId: string }>()
  const { dados: c, carregando, erro, offlineDesde, recarregar } = useCronograma(usinaId)

  return (
    <Tela
      titulo="Cronograma"
      subtitulo={
        c ? (
          <Text style={tipo.secundario}>
            {c.usina}
            {c.previsto_ano > 0 ? (
              <>
                {' · '}
                <Num style={estilos.subNum}>{inteiro(c.feitos_ano)}</Num>
                {` de ${inteiro(c.previsto_ano)} cumpridas`}
              </>
            ) : null}
          </Text>
        ) : undefined
      }
      voltar
      offlineDesde={offlineDesde}
    >
      {carregando && !c ? (
        <Card>
          <Esqueleto largura="50%" altura={14} forte />
          <View style={estilos.espaco}>
            <Esqueleto altura={200} />
          </View>
        </Card>
      ) : erro || !c ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro ?? 'Cronograma indisponível.'}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : c.linhas.length === 0 ? (
        <EstadoVazio
          titulo="Sem cronograma"
          descricao={c.aviso ?? 'O contrato desta usina ainda não tem cronograma montado.'}
        />
      ) : (
        <>
          {c.aviso ? <Text style={estilos.aviso}>{c.aviso}</Text> : null}

          <Card>
            <CabecalhoCard
              rotulo="Plano do contrato"
              direita={
                c.versao !== null ? (
                  <Text style={estilos.versao}>
                    {c.status === 'CONSOLIDATED' ? 'consolidado' : 'rascunho'} · v{c.versao}
                  </Text>
                ) : undefined
              }
            />

            <View style={estilos.grade}>
              {/* Coluna fixa: o nome da atividade. Sem ela, rolar para dezembro deixa
                  as marcas órfãs — quem lê não sabe mais de qual linha são. */}
              <View style={estilos.colunaNome}>
                <View style={estilos.cabecalhoNome}>
                  <Text style={estilos.cabecalhoTexto}>Atividade</Text>
                </View>
                {c.linhas.map((l, i) => (
                  <View key={`n${i}`} style={estilos.celulaNome}>
                    <Text style={estilos.nomeAtividade} numberOfLines={2}>
                      {l.nome}
                    </Text>
                    {l.periodicidade ? (
                      <Text style={estilos.periodicidade}>{l.periodicidade}</Text>
                    ) : null}
                  </View>
                ))}
              </View>

              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <View>
                  <View style={estilos.cabecalhoMeses}>
                    {c.meses.map((m, i) => (
                      <View key={m} style={estilos.cabecalhoMes}>
                        <Text style={estilos.mesTexto}>{mesCurto(m)}</Text>
                        {/* O ano na primeira coluna e sempre que vira. */}
                        {i === 0 || m.slice(0, 4) !== c.meses[i - 1].slice(0, 4) ? (
                          <Text style={estilos.anoTexto}>{anoDe(m)}</Text>
                        ) : null}
                      </View>
                    ))}
                    <View style={estilos.cabecalhoTotal}>
                      <Text style={estilos.mesTexto}>ano</Text>
                    </View>
                  </View>

                  {c.linhas.map((l, i) => (
                    <LinhaGrade key={`l${i}`} linha={l} />
                  ))}
                </View>
              </ScrollView>
            </View>

            <Legenda />
          </Card>

          <Card>
            <CabecalhoCard rotulo="Cronograma em PDF" />
            <Text style={estilos.explicacao}>
              O plano anual completo, com a letra do estado em cada mês. O arquivo é
              baixado e aberto no leitor do seu aparelho.
            </Text>
            <View style={estilos.espaco}>
              <AbrirPdf
                url={urlDoPdfDoCronograma(c.usina_id)}
                arquivo={`cronograma-${c.usina_id}.pdf`}
                titulo={`Cronograma — ${c.usina}`}
                rotulo="Abrir o cronograma em PDF"
              />
            </View>
          </Card>
        </>
      )}
    </Tela>
  )
}

function LinhaGrade({ linha: l }: { linha: LinhaCronograma }) {
  return (
    <View style={estilos.linha}>
      {l.meses.map((cel) => (
        <View key={cel.mes} style={estilos.celula}>
          <Marca celula={cel} />
        </View>
      ))}
      <View style={estilos.celulaTotal}>
        <Num style={estilos.total}>
          {l.feitos}/{l.previsto_ano}
        </Num>
      </View>
    </View>
  )
}

/**
 * A marca de uma célula. Cinco estados, e a ordem dos testes importa: dispensado é
 * `verde_ressalva` e nunca deve cair no ramo de `feito`.
 */
function Marca({ celula: c }: { celula: Celula }) {
  if (c.feito) {
    return (
      <View style={[estilos.marca, { backgroundColor: tons.ok }]}>
        <Text style={estilos.marcaTexto}>✓</Text>
      </View>
    )
  }
  if (c.dispensado) {
    // Contorno, não preenchimento: cumprido por decisão não é cumprido por execução.
    return (
      <View style={[estilos.marca, estilos.marcaVazada, { borderColor: tons.ok }]}>
        <Text style={[estilos.marcaTextoVazado, { color: tons.ok }]}>~</Text>
      </View>
    )
  }
  if (c.atrasado) {
    return (
      <View style={[estilos.marca, { backgroundColor: tons.parado }]}>
        <Text style={estilos.marcaTexto}>!</Text>
      </View>
    )
  }
  if (c.previsto > 0) {
    // Previsto e ainda no prazo: um ponto, que não compete com ✓ nem com !.
    return <View style={estilos.ponto} />
  }
  // Mês em que o contrato não pede nada. Vazio de verdade, sem marca de "faltou".
  return <View style={estilos.vazio} />
}

function Legenda() {
  return (
    <View style={estilos.legenda}>
      <ItemLegenda cor={tons.ok} texto="Feito" />
      <ItemLegenda cor={tons.ok} texto="Dispensado" vazado />
      <ItemLegenda cor={tons.parado} texto="Atrasado" />
      <ItemLegenda cor={cores.textoFraco} texto="Previsto" ponto />
    </View>
  )
}

function ItemLegenda({
  cor,
  texto,
  vazado,
  ponto,
}: {
  cor: string
  texto: string
  vazado?: boolean
  ponto?: boolean
}) {
  return (
    <View style={estilos.itemLegenda}>
      {ponto ? (
        <View style={estilos.ponto} />
      ) : (
        <View
          style={[
            estilos.amostra,
            vazado
              ? { borderColor: cor, borderWidth: 1.5, backgroundColor: 'transparent' }
              : { backgroundColor: cor },
          ]}
        />
      )}
      <Text style={estilos.legendaTexto}>{texto}</Text>
    </View>
  )
}

const estilos = StyleSheet.create({
  espaco: { marginTop: espaco.sm },
  subNum: { fontSize: 13, color: cores.textoRotulo },
  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },
  versao: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco },

  grade: { flexDirection: 'row', marginTop: espaco.xs },
  colunaNome: { width: LARGURA_NOME },

  cabecalhoNome: { height: 30, justifyContent: 'flex-end', paddingBottom: 5 },
  cabecalhoTexto: {
    fontFamily: fontes.ui,
    fontSize: 10,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: cores.textoRotulo,
  },
  cabecalhoMeses: { flexDirection: 'row', height: 30, alignItems: 'flex-end' },
  cabecalhoMes: { width: LARGURA_MES, alignItems: 'center', paddingBottom: 3 },
  cabecalhoTotal: { width: 46, alignItems: 'center', paddingBottom: 3 },
  mesTexto: { fontFamily: fontes.ui, fontSize: 10, color: cores.textoRotulo },
  anoTexto: { fontFamily: fontes.ui, fontSize: 8, color: cores.textoFraco },

  celulaNome: {
    height: 40,
    justifyContent: 'center',
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
    paddingRight: espaco.xs,
  },
  nomeAtividade: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoCorpo, lineHeight: 15 },
  periodicidade: { fontFamily: fontes.ui, fontSize: 9.5, color: cores.textoFraco },

  linha: {
    flexDirection: 'row',
    height: 40,
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  celula: { width: LARGURA_MES, alignItems: 'center', justifyContent: 'center' },
  celulaTotal: { width: 46, alignItems: 'center' },
  total: { fontSize: 11, color: cores.textoFraco },

  marca: { width: 20, height: 20, borderRadius: 5, alignItems: 'center', justifyContent: 'center' },
  marcaVazada: { backgroundColor: 'transparent', borderWidth: 1.5 },
  marcaTexto: { fontFamily: fontes.uiSemi, fontSize: 12, color: cores.fundo, lineHeight: 16 },
  marcaTextoVazado: { fontFamily: fontes.uiSemi, fontSize: 13, lineHeight: 16 },
  ponto: { width: 5, height: 5, borderRadius: 3, backgroundColor: cores.textoFraco },
  vazio: { width: 20, height: 20 },

  legenda: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: espaco.sm,
    marginTop: espaco.sm,
    paddingTop: espaco.sm,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  itemLegenda: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  amostra: { width: 11, height: 11, borderRadius: 3 },
  legendaTexto: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo },

  explicacao: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoCorpo,
    lineHeight: 17,
    marginTop: 4,
  },
})
