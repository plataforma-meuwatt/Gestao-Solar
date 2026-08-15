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
  GraficoBarras,
  FaixaAtencao,
  Kpi,
  LinhaNavegacao,
  Num,
  Segmentado,
  StatusChip,
} from '@/components/base'
import { Tela } from '@/components/Tela'
import { useGeracao, useUsina } from '@/features/usinas'
import { energia, inteiro, numero, porcento, potencia } from '@/lib/format'
import { cores, espaco, tipo } from '@/theme/tokens'

const RECORTES = ['Dia', 'Mês', 'Ano']

export default function UsinaDetalhe() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [recorte, setRecorte] = useState(0)
  const { dados: u, carregando, erro, offlineDesde, recarregar } = useUsina(id)
  // `recorte` 1 = Mês, 2 = Ano. Cada hook só dispara quando seu recorte está visível.
  const mes = useGeracao(id, 'mes', recorte === 1)
  const ano = useGeracao(id, 'ano', recorte === 2)

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

        {recorte === 0 ? (
          <View style={estilos.miolo}>
            <Text style={tipo.rotuloCard}>Energia hoje</Text>
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
          </View>
        ) : (
          <Periodo
            leitura={recorte === 1 ? mes : ano}
            rotulo={recorte === 1 ? 'Energia no mês' : 'Energia no ano'}
            detalhe={recorte === 1 ? 'por dia' : 'por mês'}
          />
        )}
      </Card>

      <Card>
        <CabecalhoCard
          rotulo="De onde vem"
          direita={
            <Text style={tipo.legenda}>
              {[u.tem_meuwatt && 'meuWatt', u.tem_meuplano && 'meuPlano']
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
        <GraficoBarras pontos={dados.pontos} />
      ) : (
        <Text style={tipo.fraco}>Ainda não há leitura diária neste período.</Text>
      )}
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
  espacoKpi: { marginVertical: espaco.xs },
  previsto: { fontSize: 12, color: cores.textoCorpo },

  linhas: { marginTop: espaco.sm, gap: espaco.xs },
  linha: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  linhaValor: { fontSize: 13, color: cores.textoForte },
})
