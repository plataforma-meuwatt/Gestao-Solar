/**
 * Pendências — o que ficou pendente nas usinas do dono.
 *
 * A aba Manutenção responde "a manutenção contratada está sendo feita?". Esta tela responde
 * a outra metade: **"e o que ficou pendente?"** — as pendências que a equipe compartilhou com
 * o cliente, com filtro por usina e o recorte do que ele mesmo cobrou.
 *
 * **É lista, não quadro.** O portal tem kanban porque lá há espaço e mouse; aqui três colunas
 * lado a lado numa tela de 390 px seriam três colunas ilegíveis, e arrastar — o gesto que um
 * quadro promete — o cliente não pode fazer em lugar nenhum: ele é leitor, e a etapa quem
 * move é a equipe no meuPlano.
 *
 * **Nenhum chip para escolher opção.** Regra do produto: lista suspensa pesquisável ou
 * segmentado. A situação e a usina saem de `EscolhaEmLista`, com a contagem ao lado de cada
 * opção; o recorte "cobradas por mim × todas" é um segmentado de duas opções.
 *
 * **A tela nunca fica muda por causa de um filtro.** Quando o recorte escolhido não tem
 * linha nenhuma, ela diz quantas existem fora dele — em vez de deixar o dono achando que a
 * usina não tem pendência quando o que ele fez foi deixar um filtro ligado. E abre em
 * "Cobradas por mim" só quando existe alguma: abrir num recorte vazio é o mesmo defeito.
 *
 * **Situação, cor e prazo são decisões do SERVIDOR.** `situacao` já vem "Prazo vencido"
 * quando é o caso, com `tom` vermelho, e o prazo já vem resolvido (previsão de conclusão
 * antes de `end_date`). Remontar essa régua aqui é o que fez, do outro lado, o cartão marcar
 * zero com linhas vermelhas logo abaixo. O filtro usa `coluna`, que é o campo de vocabulário
 * fixo — filtrar pela FRASE faria a pendência atrasada sumir de todos os recortes.
 */

import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import {
  CabecalhoCard,
  Card,
  Esqueleto,
  EstadoVazio,
  Num,
  Segmentado,
  StatusChip,
} from '@/components/base'
import { EscolhaEmLista, type Opcao } from '@/components/EscolhaEmLista'
import { Tela } from '@/components/Tela'
import {
  contarPorSituacao,
  filtrarPendencias,
  recorteInicial,
  RECORTES,
  SITUACAO_INICIAL,
  SITUACOES,
  tomValido,
  vazioPorFiltro,
  type ChaveSituacao,
} from '@/features/manutencao-regras'
import { usePendencias, type Pendencia } from '@/features/pendencias'
import { dataPorExtenso, inteiro } from '@/lib/format'
import { cores, espaco, fontes, tipo } from '@/theme/tokens'

export default function Pendencias() {
  const { dados, carregando, erro, offlineDesde, recarregar } = usePendencias()

  const [usina, setUsina] = useState<string | null>(null)
  const [situacao, setSituacao] = useState<ChaveSituacao>(SITUACAO_INICIAL)
  // `undefined` = ninguém escolheu ainda; aí vale o que o servidor recomenda pelo contador.
  const [recorte, setRecorte] = useState<number | undefined>(undefined)

  const itens = dados?.pendencias ?? []
  const seg = recorte ?? recorteInicial(dados?.cobradas_abertas)
  const soCobradas = seg === 0

  // Filtro que aponta para usina que sumiu da lista é ignorado em vez de esvaziar a tela.
  const usinas = [...new Set(itens.map((p) => p.usina))].sort((a, b) => a.localeCompare(b, 'pt-BR'))
  const alvoUsina = usina && usinas.includes(usina) ? usina : null

  const filtro = { usina: alvoUsina, situacao, soCobradas }
  const visiveis = filtrarPendencias(itens, filtro)
  const porSituacao = contarPorSituacao(itens, { usina: alvoUsina, soCobradas })
  const avisoDeFiltro = vazioPorFiltro(itens, filtro)

  const opcoesDeUsina: Opcao[] = [
    {
      valor: null,
      rotulo: 'Todas as usinas',
      contagem: filtrarPendencias(itens, { ...filtro, usina: null }).length,
    },
    ...usinas.map((u) => ({
      valor: u,
      rotulo: u,
      contagem: filtrarPendencias(itens, { ...filtro, usina: u }).length,
    })),
  ]

  const opcoesDeSituacao: Opcao[] = SITUACOES.map((s) => ({
    valor: s.chave,
    rotulo: s.rotulo,
    contagem: porSituacao[s.chave],
  }))

  return (
    <Tela
      titulo="Pendências"
      subtitulo={
        dados ? (
          <Text style={tipo.secundario}>
            <Num style={estilos.subNum}>{inteiro(visiveis.length)}</Num>{' '}
            {visiveis.length === 1 ? 'pendência' : 'pendências'}
            {' · '}
            {alvoUsina ?? (
              <>
                <Num style={estilos.subNum}>{inteiro(dados.usinas_com_manutencao)}</Num>{' '}
                {dados.usinas_com_manutencao === 1 ? 'usina' : 'usinas'}
              </>
            )}
          </Text>
        ) : undefined
      }
      voltar
      offlineDesde={offlineDesde}
    >
      {carregando && !dados ? (
        <>
          <Card>
            <Esqueleto largura="60%" altura={16} forte />
            <View style={estilos.espaco}>
              <Esqueleto altura={48} />
            </View>
          </Card>
          <Card>
            <Esqueleto altura={120} />
          </Card>
        </>
      ) : erro ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : !dados || itens.length === 0 ? (
        <EstadoVazio
          titulo="Nenhuma pendência"
          descricao={
            dados?.aviso
            ?? 'Quando a equipe compartilhar uma pendência das suas usinas, ela aparece aqui.'
          }
        />
      ) : (
        <>
          {dados.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}

          <Resumo dados={dados} />

          <Card>
            {/* Duas opções fixas: segmentado. Nunca uma fileira de pílulas. */}
            <Segmentado opcoes={[...RECORTES]} ativo={seg} onEscolher={setRecorte} />
            <View style={estilos.filtros}>
              <EscolhaEmLista
                rotulo="Situação"
                titulo="Ver quais pendências"
                valor={situacao}
                aoEscolher={(v) => setSituacao((v ?? SITUACAO_INICIAL) as ChaveSituacao)}
                opcoes={opcoesDeSituacao}
              />
              {/* Um filtro de uma opção é enfeite. */}
              {usinas.length > 1 ? (
                <EscolhaEmLista
                  rotulo="Usina"
                  titulo="De qual usina"
                  valor={alvoUsina}
                  aoEscolher={setUsina}
                  opcoes={opcoesDeUsina}
                />
              ) : null}
            </View>
          </Card>

          {avisoDeFiltro ? (
            <Card>
              <Text style={tipo.fraco}>{avisoDeFiltro}</Text>
            </Card>
          ) : null}

          {visiveis.map((p) => (
            <CardPendencia key={p.id} pendencia={p} mostrarUsina={alvoUsina === null} />
          ))}
        </>
      )}
    </Tela>
  )
}

/**
 * Os contadores do servidor.
 *
 * Nulos quando alguma usina não respondeu — e aí sai travessão, não zero: um total parcial
 * que parece completo é pior do que nenhum total. `prazo_vencido` é a régua do BFF, a mesma
 * que pinta as linhas de vermelho, então o cartão e a lista falam do mesmo conjunto.
 */
function Resumo({
  dados,
}: {
  dados: { abertas: number | null; cobradas_abertas: number | null; prazo_vencido: number | null }
}) {
  return (
    <Card>
      <CabecalhoCard rotulo="Onde estão" />
      <View style={estilos.numeros}>
        <Numero rotulo="Em aberto" valor={dados.abertas} />
        <Numero rotulo="Cobradas por mim" valor={dados.cobradas_abertas} />
        <Numero rotulo="Prazo vencido" valor={dados.prazo_vencido} alerta />
      </View>
    </Card>
  )
}

function Numero({
  rotulo,
  valor,
  alerta,
}: {
  rotulo: string
  valor: number | null
  alerta?: boolean
}) {
  return (
    <View style={estilos.numero}>
      <Num style={[estilos.numeroValor, alerta && valor ? estilos.numeroAlerta : null]}>
        {valor === null ? '—' : inteiro(valor)}
      </Num>
      <Text style={estilos.numeroRotulo}>{rotulo}</Text>
    </View>
  )
}

/**
 * Uma pendência.
 *
 * Sem seta e sem toque: no aplicativo não há tela de detalhe da pendência, e uma seta é
 * promessa de navegação — o dono toca, nada acontece, e conclui que travou. O que o detalhe
 * traria (parecer e documentos publicados) está no portal.
 */
function CardPendencia({ pendencia: p, mostrarUsina }: { pendencia: Pendencia; mostrarUsina: boolean }) {
  return (
    <Card>
      <View style={estilos.topo}>
        <Text style={estilos.titulo} numberOfLines={3}>
          {p.titulo}
        </Text>
        {p.numero !== null ? <Num style={estilos.numeroPendencia}>#{p.numero}</Num> : null}
      </View>

      {mostrarUsina || p.equipamento ? (
        <Text style={estilos.usina} numberOfLines={1}>
          {[
            mostrarUsina ? p.usina : null,
            p.equipamento
              ? p.equip_count && p.equip_count > 1
                ? `${p.equipamento} +${p.equip_count - 1}`
                : p.equipamento
              : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </Text>
      ) : null}

      <View style={estilos.selos}>
        {/* Frase e cor do servidor — "Prazo vencido" já vem decidido lá. */}
        <StatusChip tom={tomValido(p.tom)} texto={p.situacao} />
        {p.criticidade ? (
          <StatusChip tom={tomValido(p.criticidade_tom)} texto={p.criticidade} />
        ) : null}
        {p.cobrada_pelo_cliente ? <StatusChip tom="tempoRuim" texto="cobrada por mim" /> : null}
      </View>

      <View style={estilos.linhas}>
        {p.etapa ? <Linha rotulo="Etapa" valor={p.etapa} /> : null}
        {p.prazo ? <Linha rotulo="Prazo" valor={dataPorExtenso(p.prazo)} /> : null}
        {p.responsavel ? <Linha rotulo="Responsável" valor={p.responsavel} /> : null}
        {p.ultima_atividade_em ? (
          <Linha rotulo="Última atividade" valor={dataPorExtenso(p.ultima_atividade_em)} />
        ) : null}
        {p.concluida_em ? (
          <Linha rotulo="Concluída" valor={dataPorExtenso(p.concluida_em)} />
        ) : null}
      </View>
    </Card>
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
  espaco: { marginTop: espaco.sm },
  subNum: { fontSize: 13, color: cores.textoRotulo },
  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },

  filtros: { flexDirection: 'row', gap: espaco.sm, marginTop: espaco.md },

  numeros: { flexDirection: 'row', gap: espaco.sm, marginTop: 6 },
  numero: { flex: 1, minWidth: 0 },
  numeroValor: { ...tipo.kpiPequeno },
  numeroAlerta: { color: cores.textoAmbar },
  numeroRotulo: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo, marginTop: 2 },

  topo: { flexDirection: 'row', alignItems: 'flex-start', gap: espaco.xs },
  titulo: {
    flex: 1,
    fontFamily: fontes.uiSemi,
    fontSize: 14.5,
    color: cores.textoForte,
    lineHeight: 20,
  },
  numeroPendencia: { fontSize: 11, color: cores.textoFraco },
  usina: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginTop: 3 },
  selos: { flexDirection: 'row', flexWrap: 'wrap', gap: espaco.xs, marginTop: espaco.sm },

  linhas: { marginTop: espaco.sm, gap: espaco.xs },
  linha: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: espaco.sm },
  linhaValor: { fontSize: 12, color: cores.textoForte, flexShrink: 1, textAlign: 'right' },
})
