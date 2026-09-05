/**
 * Usina — o estado de agora e o que ela produziu hoje.
 *
 * Tudo vem de `GET /api/v1/plants/{id}`, e o `id` é o da rota: antes esta tela procurava
 * a usina numa lista de exemplo e, quando não achava, desenhava um objeto fixo — de modo
 * que **qualquer** usina abria como Porto Ferreira. O sintoma parecia navegação; a causa
 * era não ter fonte de dado.
 *
 * Os três recortes vêm da API: `Dia` de `monitoring/current` (já no detalhe) e
 * `Mês`/`Ano` de `GET /plants/{id}/geracao`, que soma a série diária do meuWatt.
 * Período sem leitura NÃO vira zero — o total mostra "—" e a barra não existe,
 * porque zero é medição (usina parada) e ausência é outra coisa.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import {
  CabecalhoCard,
  Card,
  Esqueleto,
  EstadoVazio,
  FaixaAtencao,
  GraficoBarras,
  GraficoLinha,
  Kpi,
  LinhaNavegacao,
  Num,
  Segmentado,
  StatusChip,
} from '@/components/base'
import { hojeIso, SeletorPeriodo, type Recorte } from '@/components/periodo'
import { GraficoExpansivel } from '@/components/grafico-cheio'
import { Tela } from '@/components/Tela'
import { useComparativo, useCurva, useGeracao, useUsina } from '@/features/usinas'
import { energia, inteiro, numero, porcento, potencia } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

const RECORTES = ['Dia', 'Mês', 'Ano']
const CHAVE_RECORTE: Recorte[] = ['dia', 'mes', 'ano']

export default function UsinaDetalhe() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [recorte, setRecorte] = useState(0)
  /*
   * Uma data de referência para os três recortes, e não uma por recorte.
   *
   * Quem está olhando 12 de março no Dia e passa para Mês quer março — não o mês
   * corrente. Guardar separado quebraria exatamente essa continuidade, que é o motivo
   * de existir o seletor.
   */
  const [referencia, setReferencia] = useState(hojeIso())
  const ehHoje = referencia === hojeIso()

  const { dados: u, carregando, erro, offlineDesde, recarregar } = useUsina(id)
  // Cada hook só dispara quando seu recorte está visível: abrir a usina não deve
  // disparar três chamadas para o usuário ver uma.
  const mes = useGeracao(id, 'mes', recorte === 1, referencia)
  const ano = useGeracao(id, 'ano', recorte === 2, referencia)
  const curva = useCurva(id, referencia, recorte === 0)
  // A comparação vale nos três recortes — é a mesma pergunta ("quem está fora da
  // média?") sobre janelas diferentes.
  const comparativo = useComparativo(id, CHAVE_RECORTE[recorte], referencia, true)

  if (carregando || !u) {
    return (
      <Tela titulo="Usina" voltar paraTabBar>
        {erro ? (
          <EstadoVazio
            tom="parado"
            titulo="Não deu para carregar"
            descricao={erro}
            acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
          />
        ) : (
          <>
            <Card>
              <Esqueleto largura="55%" altura={18} forte />
              <View style={estilos.espacoKpi}>
                <Esqueleto largura="40%" altura={30} forte />
              </View>
            </Card>
            <Card>
              <Esqueleto altura={90} />
            </Card>
          </>
        )}
      </Tela>
    )
  }

  const parados = u.inversores_parados ?? 0

  return (
    <Tela
      titulo={u.nome}
      subtitulo={
        <Text style={tipo.secundario}>
          {u.capacidade_kwp ? (
            <>
              <Num style={estilos.subNum}>{numero(u.capacidade_kwp / 1000, 2)}</Num> MWp
            </>
          ) : (
            'capacidade não informada'
          )}
          {u.inversores !== null ? (
            <>
              {' · '}
              <Num style={estilos.subNum}>{inteiro(u.inversores)}</Num> inversores
            </>
          ) : null}
        </Text>
      }
      voltar
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {parados > 0 ? (
        <FaixaAtencao
          tom="parado"
          titulo={`${parados} ${parados === 1 ? 'inversor parado' : 'inversores parados'}`}
          onPress={() => router.push(`/usina/${id}/equipamentos`)}
        />
      ) : null}

      {/* Mudez PARCIAL: alguns inversores calados, não todos. Sem esta faixa, a usina
          parecia inteira — a potência exibida é a soma de quem está falando, e nada na
          tela dizia que faltava gente na conta. */}
      {u.inversores_mudos && !u.sem_comunicacao ? (
        <FaixaAtencao
          tom="semDados"
          titulo={`${u.inversores_mudos} ${u.inversores_mudos === 1 ? 'inversor sem comunicação' : 'inversores sem comunicação'}`}
          detalhe="Os números abaixo não incluem esses aparelhos."
          onPress={() => router.push(`/usina/${id}/equipamentos`)}
        />
      ) : null}

      {u.aviso ? <FaixaAtencao tom="alerta" titulo={u.aviso} /> : null}

      <Card>
        <View style={estilos.topo}>
          <StatusChip tom={u.tom} texto={u.situacao} />
          <View style={estilos.espacador} />
          <Text style={tipo.legenda}>
            agora <Num style={estilos.agora}>{potencia(u.potencia_kw)}</Num>
          </Text>
        </View>

        <Segmentado opcoes={RECORTES} ativo={recorte} onEscolher={setRecorte} />

        <View style={estilos.seletor}>
          <SeletorPeriodo
            valor={referencia}
            recorte={CHAVE_RECORTE[recorte]}
            onEscolher={setReferencia}
          />
        </View>

        {recorte === 0 ? (
          <View style={estilos.miolo}>
            {/*
             * `monitoring/current` responde pelo AGORA — só serve para hoje. Escolhido
             * outro dia, a energia sai da curva daquele dia, e o rótulo muda junto para
             * ninguém ler o número de 12 de março como se fosse de hoje.
             */}
            <Text style={tipo.rotuloCard}>{ehHoje ? 'Energia hoje' : 'Energia no dia'}</Text>
            {ehHoje ? (
              <>
                <View style={estilos.espacoKpi}>
                  <Kpi
                    valor={u.energia_hoje_kwh !== null ? energia(u.energia_hoje_kwh) : '—'}
                    tamanho="grande"
                    direita={
                      u.disponibilidade_pct !== null ? (
                        <Text style={tipo.legenda}>
                          disponibilidade{' '}
                          <Num style={estilos.previsto}>{porcento(u.disponibilidade_pct)}</Num>
                        </Text>
                      ) : undefined
                    }
                  />
                </View>
                {u.pct_capacidade !== null ? (
                  <Text style={tipo.legenda}>
                    <Num style={estilos.previsto}>{u.pct_capacidade}%</Num> da capacidade
                    instalada neste momento
                  </Text>
                ) : null}
              </>
            ) : null}

            <CurvaDoDia leitura={curva} />
          </View>
        ) : (
          <Periodo
            leitura={recorte === 1 ? mes : ano}
            rotulo={recorte === 1 ? 'Energia no mês' : 'Energia no ano'}
            detalhe={recorte === 1 ? 'por dia' : 'por mês'}
          />
        )}
      </Card>

      <Comparacao leitura={comparativo} />

      <Card>
        {/* O SERVIÇO, nunca o produto que está por trás. O cliente não tem conta no
            monitoramento nem no sistema de manutenção, não sabe o nome deles e não tem a
            quem cobrar por eles — descobrir que existem dois outros sistemas por um chip
            de canto de tela só levanta uma pergunta que este portal existe para não
            precisar responder. É o mesmo vocabulário que o BFF já usa nas rotas do
            cliente (`MONITORAMENTO` e `MANUTENCAO`, em `bff/app/api/v1/manutencao.py`),
            e a régua está escrita em `bff/tests/test_vocabulario_do_cliente.py`. */}
        <CabecalhoCard
          rotulo="De onde vem"
          direita={
            <Text style={tipo.legenda}>
              {[u.tem_meuwatt && 'Monitoramento', u.tem_meuplano && 'Manutenção']
                .filter(Boolean)
                .join(' · ') || '—'}
            </Text>
          }
        />
        <View style={estilos.linhas}>
          <Linha rotulo="Local" valor={[u.cidade, u.uf].filter(Boolean).join(', ') || '—'} />
          {u.alertas_ativos !== null ? (
            <Linha rotulo="Alertas ativos" valor={inteiro(u.alertas_ativos)} />
          ) : null}
        </View>
      </Card>

      <Card semPadding>
        <LinhaNavegacao
          titulo="Equipamentos"
          valor={u.inversores !== null ? inteiro(u.inversores) : '—'}
          primeiro
          onPress={() => router.push(`/usina/${id}/equipamentos`)}
        />
        {/* Nulo é "não conseguimos consultar o meuPlano", não "está tudo em dia". O verde
            era o único tom decidido nesta tela em vez de no servidor — e decidia errado:
            um travessão VERDE se lê como tranquilidade quando o que houve foi a ponte
            cair. */}
        <LinhaNavegacao
          titulo="Manutenção"
          valor={
            u.ordens_abertas !== null ? `${inteiro(u.ordens_abertas)} em aberto` : 'não consultado'
          }
          tomValor={
            u.ordens_abertas === null ? 'semDados' : u.ordens_abertas > 0 ? 'alerta' : 'ok'
          }
        />
      </Card>
    </Tela>
  )
}

/**
 * O miolo dos recortes Mês e Ano. Três estados, e nenhum deles inventa número:
 * carregando (esqueleto), sem resposta do monitoramento (o aviso que a própria API
 * mandou) e com dado (total + barras).
 */
function Periodo({
  leitura,
  rotulo,
  detalhe,
}: {
  leitura: ReturnType<typeof useGeracao>
  rotulo: string
  detalhe: string
}) {
  const { dados, carregando, erro } = leitura

  if (carregando && !dados) {
    return (
      <View style={estilos.miolo}>
        <Text style={tipo.rotuloCard}>{rotulo}</Text>
        <View style={estilos.espacoKpi}>
          <Esqueleto largura="45%" altura={30} forte />
        </View>
        <Esqueleto altura={120} />
      </View>
    )
  }

  // `total_kwh` nulo = o monitoramento não respondeu. Some o KPI e mostra o motivo.
  if (erro || !dados || dados.total_kwh === null) {
    return (
      <View style={estilos.miolo}>
        <Text style={tipo.rotuloCard}>{rotulo}</Text>
        <View style={estilos.espacoKpi}>
          <Kpi valor="—" tamanho="grande" />
        </View>
        <Text style={tipo.fraco}>
          {erro ?? dados?.aviso ?? 'O monitoramento não devolveu geração para este período.'}
        </Text>
      </View>
    )
  }

  return (
    <View style={estilos.miolo}>
      <Text style={tipo.rotuloCard}>{rotulo}</Text>
      <View style={estilos.espacoKpi}>
        <Kpi
          valor={energia(dados.total_kwh)}
          tamanho="grande"
          direita={<Text style={tipo.legenda}>{detalhe}</Text>}
        />
      </View>
      {dados.pontos.length > 0 ? (
        <GraficoExpansivel titulo={rotulo}>
          {(altura) => <GraficoBarras pontos={dados.pontos} altura={altura ?? 120} />}
        </GraficoExpansivel>
      ) : (
        <Text style={tipo.fraco}>Ainda não há leitura diária neste período.</Text>
      )}
    </View>
  )
}

/**
 * Potência ao longo do dia, com a irradiação junto quando a usina tem estação.
 *
 * Sem estação a tela **diz** que não tem, em vez de simplesmente não desenhar a segunda
 * curva. A diferença importa: uma curva ausente sem explicação se lê como falha do app,
 * e o dono fica procurando um botão que não existe.
 */
function CurvaDoDia({ leitura }: { leitura: ReturnType<typeof useCurva> }) {
  const { dados, carregando, erro } = leitura

  if (carregando && !dados) return <Esqueleto altura={150} />

  if (erro || !dados || dados.pontos.length === 0) {
    return (
      <Text style={tipo.fraco}>
        {erro ?? dados?.aviso ?? 'O monitoramento não devolveu leitura para este dia.'}
      </Text>
    )
  }

  return (
    <View style={estilos.curva}>
      <CabecalhoCard
        rotulo="Potência ao longo do dia"
        direita={
          <Text style={tipo.legenda}>
            pico <Num style={estilos.previsto}>{potencia(dados.pico_kw)}</Num>
            {dados.tem_estacao && dados.pico_poa !== null ? (
              <>
                {' · '}
                <Num style={estilos.previsto}>{numero(dados.pico_poa, 0)}</Num> W/m²
              </>
            ) : null}
          </Text>
        }
      />
      <GraficoExpansivel titulo="Potência ao longo do dia">
        {(altura) => <GraficoLinha pontos={dados.pontos} altura={altura ?? 150} />}
      </GraficoExpansivel>
      {!dados.tem_estacao ? (
        <Text style={tipo.fraco}>
          Esta usina não tem estação solarimétrica — sem irradiação para comparar.
        </Text>
      ) : null}
    </View>
  )
}

/**
 * Quem está fora da média — por skid e por inversor.
 *
 * A comparação é em kWh/kWp (energia específica) porque skid grande gera mais sem que isso
 * seja mérito, e o desvio é contra a MEDIANA: um inversor parado puxaria a média para
 * baixo e faria os saudáveis parecerem acima do normal.
 *
 * Os inversores vêm do servidor já ordenados do pior desvio para o melhor, e a tela mostra
 * só os primeiros — numa usina de trinta, a lista inteira aqui seria a mesma rolagem que
 * a tela de equipamentos já oferece. Quem está no topo é quem interessa.
 */
function Comparacao({ leitura }: { leitura: ReturnType<typeof useComparativo> }) {
  const { dados, carregando, erro } = leitura
  const [tudo, setTudo] = useState(false)

  if (carregando && !dados) {
    return (
      <Card>
        <Esqueleto altura={110} />
      </Card>
    )
  }
  if (erro || !dados || (dados.skids.length === 0 && dados.inversores.length === 0)) {
    return (
      <Card>
        <CabecalhoCard rotulo="Comparação" />
        <Text style={tipo.fraco}>
          {erro ?? dados?.aviso ?? 'Sem energia por inversor neste período para comparar.'}
        </Text>
      </Card>
    )
  }

  const inversores = tudo ? dados.inversores : dados.inversores.slice(0, 5)
  const escondidos = dados.inversores.length - inversores.length

  return (
    <Card>
      <CabecalhoCard
        rotulo="Comparação"
        direita={<Text style={tipo.legenda}>kWh por kWp</Text>}
      />

      {/* Um skid só não se compara com ninguém — a seção seria uma linha solitária. */}
      {dados.skids.length > 1 ? (
        <View style={estilos.bloco}>
          <Text style={tipo.rotuloCard}>Entre skids</Text>
          {dados.skids.map((s) => (
            <LinhaDesvio
              key={s.nome}
              nome={s.nome}
              detalhe={`${s.inversores} ${s.inversores === 1 ? 'inversor' : 'inversores'}`}
              especifica={s.especifica}
              desvio={s.desvio_pct}
            />
          ))}
        </View>
      ) : null}

      <View style={estilos.bloco}>
        <Text style={tipo.rotuloCard}>Entre inversores</Text>
        {inversores.map((i) => (
          <LinhaDesvio
            key={i.serial ?? i.nome}
            nome={i.nome}
            detalhe={i.skid ?? ''}
            especifica={i.especifica}
            desvio={i.desvio_pct}
          />
        ))}
        {escondidos > 0 ? (
          <Text style={estilos.maisTexto} onPress={() => setTudo(true)}>
            ver os outros {escondidos}
          </Text>
        ) : null}
      </View>
    </Card>
  )
}

/**
 * Uma linha da comparação. O tom sai da distância da mediana: até 5% é ruído de medição
 * numa usina saudável, e pintar isso de amarelo faria a tela acender todo dia.
 */
function LinhaDesvio({
  nome,
  detalhe,
  especifica,
  desvio,
}: {
  nome: string
  detalhe: string
  especifica: number | null
  desvio: number | null
}) {
  const tom = desvio === null ? undefined : desvio <= -15 ? 'parado' : desvio <= -5 ? 'alerta' : 'ok'

  return (
    <View style={estilos.desvioLinha}>
      {tom ? <View style={[estilos.pontoDesvio, { backgroundColor: tons[tom] }]} /> : null}
      <View style={estilos.desvioNomes}>
        <Text style={estilos.desvioNome} numberOfLines={1}>
          {nome}
        </Text>
        {detalhe ? <Text style={tipo.fraco}>{detalhe}</Text> : null}
      </View>
      <Num style={estilos.desvioValor}>{especifica !== null ? numero(especifica, 2) : '—'}</Num>
      <Num
        style={[estilos.desvioPct, tom ? { color: tons[tom] } : null]}
      >
        {desvio !== null ? `${desvio > 0 ? '+' : ''}${numero(desvio, 1)}%` : '—'}
      </Num>
    </View>
  )
}

function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <View style={estilos.linha}>
      <Text style={tipo.legenda}>{rotulo}</Text>
      <Num style={estilos.linhaValor}>{valor}</Num>
    </View>
  )
}

const estilos = StyleSheet.create({
  subNum: { fontSize: 13, color: cores.textoRotulo },

  topo: { flexDirection: 'row', alignItems: 'center', marginBottom: espaco.sm },
  espacador: { flex: 1 },
  agora: { fontSize: 12, color: cores.textoForte },

  miolo: { marginTop: espaco.md, gap: espaco.xs },
  seletor: { marginTop: espaco.sm },

  bloco: { marginTop: espaco.sm, gap: 2 },
  desvioLinha: { flexDirection: 'row', alignItems: 'center', gap: espaco.xs },
  pontoDesvio: { width: 6, height: 6, borderRadius: 3 },
  desvioNomes: { flex: 1 },
  desvioNome: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoForte },
  desvioValor: { fontSize: 12, color: cores.textoCorpo, minWidth: 44, textAlign: 'right' },
  desvioPct: { fontSize: 12, minWidth: 52, textAlign: 'right', color: cores.textoCorpo },
  maisTexto: { fontFamily: fontes.ui, fontSize: 12, color: cores.ambar, marginTop: espaco.xs },
  curva: { marginTop: espaco.sm },
  espacoKpi: { marginVertical: espaco.xs },
  previsto: { fontSize: 12, color: cores.textoCorpo },

  linhas: { marginTop: espaco.sm, gap: espaco.xs },
  linha: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  linhaValor: { fontSize: 13, color: cores.textoForte },
})
