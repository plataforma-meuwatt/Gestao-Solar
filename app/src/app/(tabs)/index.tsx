/**
 * Início — a tela que responde "está tudo bem?" em cinco segundos.
 *
 * Ordem dos blocos vem do design: potência agora (o dado mais perecível), o que está
 * errado, e o financeiro. Quem abre o app com pressa lê só o primeiro card.
 *
 * **Nenhum número aqui existe sem origem.** Esta tela já anunciou "4.280 kW de 3 usinas"
 * para quem tem sete — tudo escrito à mão. Agora cada valor vem de `GET /api/v1/home`, que
 * agrega exatamente o que a aba Usinas mostra, e o que não existe **não é desenhado**: sem
 * capacidade cadastrada, some a barra de porcentagem; sem problema em nenhuma usina, não
 * há faixa vermelha; sem assinatura, não há card de financeiro.
 *
 * Blocos que sumiram por não terem fonte: "meta do mês" (não existe em upstream nenhum) e
 * o calendário de manutenção (depende do meuPlano, ainda não ligado). Voltam quando
 * houver de onde tirá-los — não antes.
 */

import { router } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  Card,
  Esqueleto,
  EstadoVazio,
  FaixaAtencao,
  Kpi,
  Num,
  StatusChip,
} from '@/components/base'
import { Tela } from '@/components/Tela'
import { useInicio, type InicioOut } from '@/features/inicio'
import { dataPorExtenso, energia, hora, inteiro, moeda, numero, potencia } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo, TOQUE_MIN } from '@/theme/tokens'

function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

export default function Inicio() {
  const { dados, carregando, erro, offlineDesde, recarregar } = useInicio()
  const usuario = useAuth((s) => s.usuario)

  return (
    <Tela
      titulo={dados ? `${dados.saudacao}, ${dados.primeiro_nome}` : 'Início'}
      subtitulo={<Text style={tipo.secundario}>{dataPorExtenso(new Date().toISOString())}</Text>}
      avatar={{
        iniciais: iniciaisDe(usuario?.nome),
        temAviso: Boolean(dados?.atencao),
        onPress: () => router.push('/perfil'),
      }}
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {carregando ? (
        <Fantasma />
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : !dados ? (
        <EstadoVazio titulo="Sem dados" descricao="Não há nada para mostrar ainda." />
      ) : (
        <Conteudo dados={dados} />
      )}
    </Tela>
  )
}

function Conteudo({ dados: d }: { dados: InicioOut }) {
  if (d.usinas === 0) {
    return (
      <EstadoVazio
        titulo="Nenhuma usina ainda"
        descricao={d.aviso ?? 'Assim que uma usina for liberada para a sua conta, ela aparece aqui.'}
      />
    )
  }

  const parcial = d.usinas_com_dado < d.usinas

  return (
    <>
      <Card>
        <View style={estilos.topoCard}>
          <Text style={tipo.rotuloCard}>AGORA</Text>
          <View style={estilos.espacador} />
          <Text style={tipo.legenda}>
            <Num style={estilos.legendaNum}>{inteiro(d.usinas)}</Num>
            {d.usinas === 1 ? ' usina' : ' usinas'} ·{' '}
            <Num style={estilos.legendaNum}>{hora(d.atualizado_em)}</Num>
          </Text>
        </View>

        <View style={estilos.linhaPotencia}>
          <Kpi valor={potencia(d.potencia_agora_kw)} tamanho="grande" />
        </View>

        {/* A barra só aparece quando há capacidade para comparar. Sem ela, uma barra
            vazia diria "não está gerando nada", que é diferente de "não sabemos". */}
        {d.pct_capacidade !== null ? (
          <>
            <View style={estilos.barra}>
              <Barra pct={d.pct_capacidade} />
            </View>
            <View style={estilos.rodapeCard}>
              <Text style={tipo.legenda}>
                <Num style={estilos.legendaForte}>{d.pct_capacidade}%</Num> da capacidade
                instalada
              </Text>
              {d.energia_hoje_kwh !== null ? (
                <Text style={tipo.legenda}>
                  hoje <Num style={estilos.legendaForte}>{energia(d.energia_hoje_kwh)}</Num>
                </Text>
              ) : null}
            </View>
          </>
        ) : (
          <View style={estilos.rodapeCard}>
            {d.energia_hoje_kwh !== null ? (
              <Text style={tipo.legenda}>
                hoje <Num style={estilos.legendaForte}>{energia(d.energia_hoje_kwh)}</Num>
              </Text>
            ) : null}
            {d.capacidade_total_kwp ? (
              <Text style={tipo.legenda}>
                <Num style={estilos.legendaForte}>
                  {numero(d.capacidade_total_kwp / 1000, 2)}
                </Num>{' '}
                MWp instalados
              </Text>
            ) : null}
          </View>
        )}

        {parcial ? (
          <Text style={estilos.parcial}>
            Número parcial: <Num style={estilos.legendaNum}>{d.usinas_com_dado}</Num> de{' '}
            <Num style={estilos.legendaNum}>{d.usinas}</Num> usinas responderam.
          </Text>
        ) : null}
      </Card>

      {d.atencao ? (
        <FaixaAtencao
          tom={d.atencao.tom}
          titulo={d.atencao.titulo}
          detalhe={d.atencao.detalhe ?? undefined}
          onPress={
            d.atencao.plant_id ? () => router.push(`/usina/${d.atencao!.plant_id}`) : undefined
          }
        />
      ) : null}

      {d.financeiro ? (
        <Card>
          <View style={estilos.topoCard}>
            <Text style={tipo.rotuloCard}>FINANCEIRO</Text>
            <View style={estilos.espacador} />
            <StatusChip tom={d.financeiro.tom} texto={d.financeiro.resumo} />
          </View>
          {d.financeiro.proximo_vencimento ? (
            <Text style={estilos.financeiroLinha}>
              Próximo vencimento{' '}
              <Num style={estilos.legendaForte}>
                {d.financeiro.proximo_vencimento.split('-').reverse().slice(0, 2).join('/')}
              </Num>
              {d.financeiro.total !== null ? (
                <>
                  {' · '}
                  <Num style={estilos.legendaForte}>{moeda(d.financeiro.total)}</Num>
                </>
              ) : null}
            </Text>
          ) : null}
        </Card>
      ) : null}

      {d.aviso ? <Text style={estilos.aviso}>{d.aviso}</Text> : null}
    </>
  )
}

function Fantasma() {
  return (
    <>
      <Card>
        <Esqueleto largura="30%" altura={11} />
        <View style={{ marginTop: 16 }}>
          <Esqueleto largura="60%" altura={34} forte />
        </View>
        <View style={{ marginTop: 16 }}>
          <Esqueleto altura={6} />
        </View>
      </Card>
      <Card>
        <Esqueleto largura="40%" altura={14} />
        <View style={{ marginTop: 12 }}>
          <Esqueleto altura={16} />
        </View>
      </Card>
    </>
  )
}

const estilos = StyleSheet.create({
  topoCard: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 18 },
  espacador: { flex: 1 },
  legendaNum: { fontSize: 12, color: cores.textoRotulo },
  legendaForte: { fontSize: 12, color: cores.textoForte },

  linhaPotencia: { marginTop: 10 },
  barra: { marginTop: 14 },
  rodapeCard: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: espaco.sm,
    gap: 12,
    minHeight: 16,
  },
  parcial: {
    fontFamily: fontes.ui,
    fontSize: 11,
    color: cores.textoRotulo,
    marginTop: espaco.sm,
    paddingTop: espaco.sm,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },

  financeiroLinha: {
    fontFamily: fontes.ui,
    fontSize: 13,
    color: cores.textoCorpo,
    marginTop: espaco.sm,
    minHeight: TOQUE_MIN / 2,
  },

  aviso: { ...tipo.fraco, lineHeight: 17, paddingHorizontal: espaco.xs },
})
