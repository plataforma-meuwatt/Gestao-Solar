/**
 * Lista de usinas.
 *
 * Cada card responde "esta está bem?" sem precisar abrir: potência agora contra a
 * capacidade instalada, com a barra dando a proporção de relance. A usina sem
 * comunicação mostra travessão e barra vazia — nunca zero, que se leria como
 * "gerou nada" em vez de "não sabemos".
 *
 * A cor e a frase de status vêm prontas do BFF. A tela não decide se uma usina está bem:
 * essa régua é a mesma no monitoramento e mudaria com a loja no meio do caminho.
 *
 * No topo, o **comparativo**: "qual delas rende mais no período?". É outra pergunta — a
 * lista fala do agora, o comparativo fala de um período —, e por isso tem seletor próprio.
 * A ordem é a que o servidor mandou, nunca uma calculada aqui; ver `features/carteira.ts`.
 */

import { router } from 'expo-router'
import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  CabecalhoCard,
  Card,
  Chevron,
  Esqueleto,
  EstadoVazio,
  Num,
  Segmentado,
  StatusChip,
} from '@/components/base'
import { hojeIso, SeletorPeriodo } from '@/components/periodo'
import { Tela } from '@/components/Tela'
import {
  fraseDaJanela,
  ordenarPeloRanking,
  periodoDaCarteira,
  rankingDe,
  useComparativo,
  type UsinaEnergia,
} from '@/features/carteira'
import { useUsinas, type Usina } from '@/features/usinas'
import { energia, inteiro, numero, potencia } from '@/lib/format'
import { useAuth } from '@/store/auth'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

export default function Usinas() {
  const { dados, carregando, erro, offlineDesde, recarregar } = useUsinas()
  const usuario = useAuth((s) => s.usuario)

  const lista = dados?.usinas ?? []

  return (
    <Tela
      titulo="Usinas"
      subtitulo={
        dados ? (
          <Text style={tipo.secundario}>
            <Num style={estilos.subNum}>{lista.length}</Num> usinas
            {/* A capacidade só aparece quando existe. Sem ela `total_kwp` é 0 — a
                capacidade vem dos inversores, e uma ponte fora do ar zera a soma. Exibir
                "0,0 MWp" seria fabricar um número para um desconhecido, e logo no
                subtítulo da tela. */}
            {dados.total_kwp > 0 ? (
              <>
                {' · '}
                <Num style={estilos.subNum}>{numero(dados.total_kwp / 1000, 1)}</Num> MWp
              </>
            ) : null}
          </Text>
        ) : undefined
      }
      avatar={{
        iniciais: iniciaisDe(usuario?.nome),
        temAviso: Boolean(dados?.aviso),
        onPress: () => router.push('/perfil'),
      }}
      offlineDesde={offlineDesde}
      paraTabBar
    >
      {/* Uma usina não se compara com ninguém — o bloco seria uma linha solitária com um
          seletor de período em cima. Mesma regra da comparação entre skids. */}
      {lista.length > 1 ? <Comparativo /> : null}

      {carregando ? (
        <CardsFantasma />
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : lista.length === 0 ? (
        <EstadoVazio
          titulo="Nenhuma usina ainda"
          descricao={
            dados?.aviso ??
            'Assim que uma usina for liberada para a sua conta, ela aparece aqui.'
          }
        />
      ) : (
        lista.map((u) => <CardUsina key={u.id} usina={u} />)
      )}
    </Tela>
  )
}

/** Iniciais para o avatar: as do primeiro e do último nome. */
function iniciaisDe(nome: string | undefined): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '·'
  const primeira = partes[0][0]
  const ultima = partes.length > 1 ? partes[partes.length - 1][0] : ''
  return (primeira + ultima).toUpperCase()
}

/* ------------------------------------------------------------- comparativo */

const RECORTES = ['Mês', 'Ano']

/**
 * "Qual usina rende mais?" — a pergunta de quem está no carro.
 *
 * Duas réguas lado a lado, cada uma rotulada com a pergunta que responde: **kWh/kWp**
 * (rende mais para o tamanho que tem) ordena, e a **energia** (gerou mais) vai ao lado.
 * Ordenar pela energia faria a usina maior ganhar sempre, o que não é mérito nenhum.
 *
 * A **janela comum** é impressa em texto: usinas que entraram em operação em datas
 * diferentes não têm o mesmo período medido, e comparar doze meses com quatro sem dizer
 * isso é o jeito silencioso de mentir. Quem não mediu nada no período sai da ordem com
 * travessão e o motivo ao lado — nunca como zero no último lugar.
 */
function Comparativo() {
  const [recorte, setRecorte] = useState(0)
  const [referencia, setReferencia] = useState(hojeIso())
  const chave = recorte === 0 ? ('mes' as const) : ('ano' as const)
  const { de, ate } = periodoDaCarteira(referencia, chave)

  // Só o bloco de energia: a família de Geração não deve esperar o sistema de manutenção
  // responder para o cliente ver quem rende mais.
  const { dados, carregando, erro } = useComparativo(de, ate, 'energia')

  const bloco = dados?.energia ?? null
  const ranking = rankingDe(bloco, 'produtividade')
  const { ordenadas, fora } = ordenarPeloRanking<UsinaEnergia>(bloco?.usinas ?? [], ranking)
  const frase = fraseDaJanela(dados?.janela)

  // A barra é proporcional ao líder — é o próprio valor desenhado, não uma escala
  // inventada. Sem líder positivo, nenhuma barra: largura zero em todas as linhas se
  // leria como "ninguém gerou".
  const maior = ordenadas.reduce((m, l) => (l.valor > m ? l.valor : m), 0)

  return (
    <Card>
      <CabecalhoCard
        rotulo="Comparar usinas"
        direita={<Text style={tipo.legenda}>{ranking?.unidade ?? 'kWh/kWp'}</Text>}
      />

      {/* A pergunta é a do servidor. Escrevê-la aqui faria "produtividade" virar
          "rendimento" no celular e "eficiência" no computador, para o mesmo número. */}
      {ranking?.pergunta ? <Text style={tipo.fraco}>{ranking.pergunta}</Text> : null}

      <View style={estilos.controles}>
        <Segmentado opcoes={RECORTES} ativo={recorte} onEscolher={setRecorte} />
        <SeletorPeriodo valor={referencia} recorte={chave} onEscolher={setReferencia} />
      </View>

      {frase ? <Text style={estilos.janela}>{frase}</Text> : null}

      {carregando && !dados ? (
        <View style={estilos.fantasmaLinhas}>
          <Esqueleto altura={14} />
          <Esqueleto altura={14} />
          <Esqueleto altura={14} />
        </View>
      ) : erro || !bloco ? (
        <Text style={tipo.fraco}>
          {erro ?? dados?.aviso ?? 'Não deu para comparar as usinas neste período.'}
        </Text>
      ) : ordenadas.length === 0 && fora.length === 0 ? (
        // O aviso do servidor primeiro: "nenhuma usina medida" e "o monitoramento não
        // respondeu" produzem a mesma tela vazia, e só o primeiro é uma medição.
        <Text style={tipo.fraco}>
          {dados?.aviso ?? 'Nenhuma usina com geração medida neste período.'}
        </Text>
      ) : (
        <>
          <View style={estilos.cabecalhoColunas}>
            <View style={estilos.espacador} />
            <Text style={[estilos.colunaRotulo, estilos.colunaValor]}>rende</Text>
            <Text style={[estilos.colunaRotulo, estilos.colunaValorSec]}>gerou</Text>
          </View>

          {ordenadas.map((linha) => (
            <LinhaComparativo
              key={linha.usina.id}
              posicao={linha.posicao}
              empatado={linha.empatado}
              usina={linha.usina}
              produtividade={linha.valor}
              maior={maior}
            />
          ))}

          {/* Fora da ordem, e dizendo por quê. Somá-las no fim da lista com zero seria a
              leitura mais injusta possível de uma ausência de medição. */}
          {fora.map((u) => (
            <LinhaComparativo key={u.id} usina={u} produtividade={null} maior={maior} />
          ))}

          {ranking && ranking.fora.length > 0 ? (
            <Text style={estilos.rodapeFora}>Fora deste ranking: {ranking.fora.join(' · ')}</Text>
          ) : null}

          {dados?.aviso ? <Text style={estilos.rodapeFora}>{dados.aviso}</Text> : null}
        </>
      )}
    </Card>
  )
}

/**
 * Uma linha do comparativo. `produtividade` nula = a usina não entrou na ordem, e a linha
 * mostra travessão com o motivo que o servidor escreveu.
 */
function LinhaComparativo({
  posicao,
  empatado,
  usina,
  produtividade,
  maior,
}: {
  posicao?: number
  empatado?: boolean
  usina: UsinaEnergia
  produtividade: number | null
  maior: number
}) {
  // A energia da JANELA COMUM, que é a mesma de que o ranking fala. Cair em `energia_kwh`
  // quando ela falta trocaria a janela sem avisar — dois números, duas perguntas.
  const kwh = usina.energia_comparavel_kwh

  return (
    <View style={estilos.linha}>
      <View style={estilos.linhaTopo}>
        <Text style={estilos.posicao}>{posicao !== undefined ? `${posicao}º` : '—'}</Text>
        <View style={estilos.linhaNomes}>
          <Text style={estilos.linhaNome} numberOfLines={1}>
            {usina.nome}
          </Text>
          {empatado ? <Text style={tipo.legenda}>empate</Text> : null}
          {produtividade === null && usina.motivo ? (
            <Text style={tipo.legenda} numberOfLines={2}>
              {usina.motivo}
            </Text>
          ) : null}
        </View>
        <Num style={estilos.valor}>
          {produtividade !== null ? numero(produtividade, 1) : '—'}
        </Num>
        <Num style={estilos.valorSecundario}>{kwh !== null ? energia(kwh) : '—'}</Num>
      </View>
      {produtividade !== null && maior > 0 ? (
        <View style={estilos.linhaBarra}>
          <Barra pct={(produtividade / maior) * 100} fina />
        </View>
      ) : null}
    </View>
  )
}

/* ------------------------------------------------------------------- lista */

function CardUsina({ usina }: { usina: Usina }) {
  const semDados = usina.potencia_kw === null
  // `potencia()` escolhe kW ou MW pela ordem de grandeza e formata em pt-BR; o design
  // pede o número grande e a unidade pequena ao lado, daí a separação.
  const [valor, unidade] = potencia(usina.potencia_kw).split(' ')
  const local = [usina.cidade, usina.uf].filter(Boolean).join(', ')

  return (
    <Pressable onPress={() => router.push(`/usina/${usina.id}`)}>
      <Card>
        <View style={estilos.topo}>
          <Text style={estilos.nome}>{usina.nome}</Text>
          <StatusChip tom={usina.tom} texto={usina.situacao} />
          <View style={estilos.espacador} />
          <Chevron />
        </View>

        <View style={estilos.linhaPotencia}>
          {semDados ? (
            <Num style={[estilos.potencia, { color: tons.semDados }]}>—</Num>
          ) : (
            <>
              <Num style={estilos.potencia}>{valor}</Num>
              <Text style={estilos.unidade}>{unidade}</Text>
            </>
          )}
          {usina.capacidade_kwp ? (
            <Text style={estilos.capacidade}>
              de <Num style={estilos.capacidadeNum}>{inteiro(usina.capacidade_kwp)}</Num> kWp
            </Text>
          ) : null}
        </View>

        {/* Sem percentual, NENHUMA barra. Uma barra vazia se lê como "não está gerando
            nada", que é uma afirmação — e aqui não se sabe. Mesma regra da tela inicial. */}
        {usina.pct_capacidade !== null ? (
          <View style={estilos.barra}>
            <Barra pct={usina.pct_capacidade} />
          </View>
        ) : null}

        <View style={estilos.rodape}>
          <Text style={tipo.legenda}>{local || '—'}</Text>
          <Text style={tipo.legenda} numberOfLines={1}>
            {usina.energia_hoje_kwh !== null ? (
              <>
                hoje <Num style={estilos.energia}>{energia(usina.energia_hoje_kwh)}</Num>
              </>
            ) : (
              (usina.aviso ?? 'sem dados do dia')
            )}
          </Text>
        </View>
      </Card>
    </Pressable>
  )
}

/** Skeleton, nunca spinner solto: três cards com o desenho do que vem. */
function CardsFantasma() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <View style={estilos.topo}>
            <Esqueleto largura="45%" altura={16} forte />
            <View style={estilos.espacador} />
            <Esqueleto largura={64} altura={18} />
          </View>
          <View style={estilos.linhaPotencia}>
            <Esqueleto largura="35%" altura={28} forte />
          </View>
          <View style={estilos.barra}>
            <Esqueleto altura={6} />
          </View>
          <View style={estilos.rodape}>
            <Esqueleto largura={110} altura={12} />
            <Esqueleto largura={80} altura={12} />
          </View>
        </Card>
      ))}
    </>
  )
}

const estilos = StyleSheet.create({
  subNum: { fontSize: 13, color: cores.textoRotulo },

  topo: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  nome: { fontFamily: fontes.uiSemi, fontSize: 16, color: cores.textoForte },
  espacador: { flex: 1 },

  linhaPotencia: { flexDirection: 'row', alignItems: 'baseline', gap: 7, marginTop: 12 },
  potencia: { fontFamily: fontes.monoSemi, fontSize: 30, lineHeight: 30, color: cores.textoForte },
  unidade: { fontFamily: fontes.ui, fontSize: 14, color: cores.textoCorpo },
  capacidade: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginLeft: 'auto' },
  capacidadeNum: { fontSize: 12, color: cores.textoCorpo },

  barra: { marginTop: 12 },
  rodape: { flexDirection: 'row', justifyContent: 'space-between', marginTop: espaco.sm, gap: 12 },
  energia: { fontSize: 12, color: cores.textoForte },

  controles: { marginTop: espaco.sm, gap: espaco.xs },
  janela: {
    fontFamily: fontes.ui,
    fontSize: 12,
    lineHeight: 17,
    color: cores.textoRotulo,
    marginTop: espaco.xs,
  },
  fantasmaLinhas: { marginTop: espaco.sm, gap: 10 },

  cabecalhoColunas: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: espaco.xs,
    marginTop: espaco.sm,
    marginBottom: 2,
  },
  colunaRotulo: { fontFamily: fontes.ui, fontSize: 10.5, color: cores.textoFraco, textAlign: 'right' },
  colunaValor: { minWidth: 52 },
  colunaValorSec: { minWidth: 68 },

  linha: { marginTop: espaco.xs },
  linhaTopo: { flexDirection: 'row', alignItems: 'center', gap: espaco.xs },
  posicao: { fontFamily: fontes.monoSemi, fontSize: 11, color: cores.textoRotulo, minWidth: 20 },
  linhaNomes: { flex: 1 },
  linhaNome: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoForte },
  valor: { fontSize: 13, color: cores.textoForte, minWidth: 52, textAlign: 'right' },
  valorSecundario: { fontSize: 12, color: cores.textoCorpo, minWidth: 68, textAlign: 'right' },
  linhaBarra: { marginTop: 4, marginLeft: 28 },
  rodapeFora: {
    fontFamily: fontes.ui,
    fontSize: 11.5,
    lineHeight: 16,
    color: cores.textoFraco,
    marginTop: espaco.sm,
  },
})
