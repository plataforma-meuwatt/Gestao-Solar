/**
 * Equipamentos da usina.
 *
 * A contagem do topo existe para o dono não precisar percorrer a lista para saber se há
 * problema. Tudo vem de `GET /api/v1/plants/{id}/equipamentos` — antes esta tela mostrava
 * os mesmos oito inversores fictícios (INV-01 a INV-08, "2 parados há 3 h 10") para
 * qualquer usina de qualquer cliente.
 *
 * Inversor **ignorado** no meuWatt aparece na lista, apagado, e fica fora das contagens:
 * silenciá-lo foi decisão de quem opera, e contá-lo como problema seria discutir com essa
 * decisão a cada abertura.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import {
  Barra,
  Card,
  Chevron,
  Esqueleto,
  EstadoVazio,
  Num,
  Segmentado,
  StatusChip,
} from '@/components/base'
import { Tela } from '@/components/Tela'
import {
  useCurvaProtecao,
  useCurvaTemperatura,
  useEquipamentos,
  useHistoricoDeFlags,
  useMaximas,
  type Equipamento,
  type ReleProtecao,
  type ReleTemperatura,
} from '@/features/equipamentos'
import { GraficoBarras, GraficoSeries } from '@/components/base'
import { GraficoExpansivel } from '@/components/grafico-cheio'
import { hojeIso, SeletorPeriodo } from '@/components/periodo'
import { dataHora, duracao, energia, hora, inteiro, numero, potencia } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons } from '@/theme/tokens'

/**
 * A ordem é a que o dono pediu, e ela tem lógica de operação: o inversor é quem gera, e
 * é onde a perda aparece primeiro; a temperatura do trafo é o que estraga equipamento de
 * forma silenciosa; o relé de proteção é o que desliga tudo quando algo dá errado.
 */
const TIPOS = ['Tudo', 'Inversores', 'Temperatura', 'Proteção']

export default function Equipamentos() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [tipo_, setTipo] = useState(0)
  const { dados, carregando, erro, offlineDesde, recarregar } = useEquipamentos(id)

  return (
    <Tela
      titulo="Equipamentos"
      subtitulo={
        dados ? (
          <Text style={tipo.secundario}>
            {dados.usina}
            {dados.total !== null ? (
              <>
                {' · '}
                <Num style={estilos.subNum}>{inteiro(dados.total)}</Num> inversores
              </>
            ) : null}
          </Text>
        ) : undefined
      }
      voltar
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
      ) : !dados || dados.equipamentos.length === 0 ? (
        <EstadoVazio
          titulo="Nenhum inversor"
          descricao={dados?.aviso ?? 'Esta usina não devolveu inversores no monitoramento.'}
        />
      ) : (
        <>
          <View style={estilos.resumo}>
            {dados.parados ? (
              <>
                <Num style={[estilos.resumoNum, { color: tons.parado }]}>{dados.parados}</Num>
                <Text style={tipo.legenda}>{dados.parados === 1 ? 'parado' : 'parados'}</Text>
              </>
            ) : null}
            {dados.alerta ? (
              <>
                <Num style={[estilos.resumoNum, { color: tons.alerta }]}>{dados.alerta}</Num>
                <Text style={tipo.legenda}>em alerta</Text>
              </>
            ) : null}
            {dados.sem_dados ? (
              <>
                <Num style={[estilos.resumoNum, { color: tons.semDados }]}>{dados.sem_dados}</Num>
                <Text style={tipo.legenda}>sem dados</Text>
              </>
            ) : null}
            {/* "Todos gerando" só quando estão MESMO gerando. De madrugada os três
                contadores de problema ficam em zero — todo inversor é `dormindo` — e a
                versão anterior afirmava "Todos gerando" no topo de uma lista em que cada
                card dizia "Fora da janela solar". */}
            {dados.dormindo ? (
              <>
                <View style={[estilos.ponto, { backgroundColor: tons.semDados }]} />
                <Text style={tipo.legenda}>
                  {dados.dormindo === dados.total
                    ? 'Fora da janela solar'
                    : `${dados.dormindo} fora da janela solar`}
                </Text>
              </>
            ) : !dados.parados && !dados.alerta && !dados.sem_dados ? (
              <>
                <View style={[estilos.ponto, { backgroundColor: tons.ok }]} />
                <Text style={tipo.legenda}>Todos gerando</Text>
              </>
            ) : null}
            <View style={estilos.espacador} />
            {dados.atualizado_em ? (
              <Text style={tipo.legenda}>
                <Num style={estilos.subNum}>{hora(dados.atualizado_em)}</Num>
              </Text>
            ) : null}
          </View>

          {dados.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}

          <ComProblema
            inversores={dados.equipamentos}
            protecao={dados.reles_protecao ?? []}
            temperatura={dados.reles_temperatura ?? []}
            usinaId={id}
          />

          <Segmentado opcoes={TIPOS} ativo={tipo_} onEscolher={setTipo} />

          {/*
           * O que a usina TEM, dito em números, logo abaixo do seletor.
           *
           * Sem isto, "não vejo relé" é ambíguo entre três causas muito diferentes: a
           * usina não tem o aparelho cadastrado, o monitoramento não o devolveu, ou a
           * seção está lá embaixo depois de doze cards de inversor. A contagem separa
           * as três na hora — e um zero aqui é uma afirmação, não um silêncio.
           */}
          <Text style={estilos.inventario}>
            <Num style={estilos.inventarioNum}>{dados.equipamentos.length}</Num> inversores ·{' '}
            <Num style={estilos.inventarioNum}>{(dados.reles_temperatura ?? []).length}</Num>{' '}
            de temperatura ·{' '}
            <Num style={estilos.inventarioNum}>{(dados.reles_protecao ?? []).length}</Num>{' '}
            de proteção
          </Text>

          {tipo_ === 0 || tipo_ === 1 ? (
            <SecaoInversores lista={dados.equipamentos} usinaId={id} comTitulo={tipo_ === 0} />
          ) : null}

          {tipo_ === 0 || tipo_ === 2 ? (
            <SecaoTemperatura
              lista={dados.reles_temperatura ?? []}
              comTitulo={tipo_ === 0}
              usinaId={id}
            />
          ) : null}

          {tipo_ === 0 || tipo_ === 3 ? (
            <SecaoProtecao
              lista={dados.reles_protecao ?? []}
              comTitulo={tipo_ === 0}
              usinaId={id}
            />
          ) : null}
        </>
      )}
    </Tela>
  )
}

/**
 * O que está com problema, antes da lista.
 *
 * Sem isto, achar o inversor parado numa usina de trinta exige rolar até encontrar o card
 * vermelho. A lista continua completa embaixo — este bloco é atalho, não substituto.
 *
 * Só aparece quando há problema: um card permanente dizendo "nada com problema" ocuparia
 * o topo da tela todos os dias para não informar nada.
 */
function ComProblema({
  inversores,
  protecao,
  temperatura,
  usinaId,
}: {
  inversores: Equipamento[]
  protecao: ReleProtecao[]
  temperatura: ReleTemperatura[]
  usinaId?: string
}) {
  const invRuins = inversores.filter((e) => !e.ignorado && (e.tom === 'parado' || e.tom === 'alerta'))
  // Relé com flag ativa é problema declarado pelo próprio aparelho. Relé mudo é problema
  // de outra natureza — não sabemos o que ele está protegendo — e conta igual.
  const relesComFlag = protecao.filter((r) => r.flags.length > 0)
  const relesMudos = protecao.filter((r) => !r.comunicando)
  const tempMudos = temperatura.filter((t) => !t.comunicando)

  const total = invRuins.length + relesComFlag.length + relesMudos.length + tempMudos.length
  if (total === 0) return null

  return (
    <Card>
      <Text style={estilos.tituloSecao}>Precisam de atenção</Text>
      <View style={estilos.problemas}>
        {invRuins.map((e) => (
          <Pressable
            key={e.id}
            style={estilos.problema}
            onPress={usinaId ? () => router.push(`/equipamento/${e.id}?usina=${usinaId}`) : undefined}
          >
            <View style={[estilos.ponto, { backgroundColor: tons[e.tom] }]} />
            <Text style={estilos.problemaNome} numberOfLines={1}>
              {e.nome}
            </Text>
            <Text style={estilos.problemaDetalhe} numberOfLines={1}>
              {e.situacao}
            </Text>
            <Chevron />
          </Pressable>
        ))}
        {relesComFlag.map((r) => (
          <View key={`flag-${r.id}`} style={estilos.problema}>
            <View style={[estilos.ponto, { backgroundColor: tons.parado }]} />
            <Text style={estilos.problemaNome} numberOfLines={1}>
              {r.nome}
            </Text>
            <Text style={estilos.problemaDetalhe} numberOfLines={1}>
              {r.flags.join(' · ')}
            </Text>
          </View>
        ))}
        {[...relesMudos, ...tempMudos].map((r) => (
          <View key={`mudo-${r.id}`} style={estilos.problema}>
            <View style={[estilos.ponto, { backgroundColor: tons.semDados }]} />
            <Text style={estilos.problemaNome} numberOfLines={1}>
              {r.nome}
            </Text>
            <Text style={estilos.problemaDetalhe}>sem comunicação</Text>
          </View>
        ))}
      </View>
    </Card>
  )
}

/**
 * Inversores agrupados por skid.
 *
 * O agrupamento só acontece quando há mais de um skid: numa usina de skid único, o título
 * repetido acima de cada bloco seria ruído puro. Usina sem a estrutura cadastrada cai no
 * mesmo caminho, porque `skid` vem `null` para todos.
 */
function SecaoInversores({
  lista,
  usinaId,
  comTitulo,
}: {
  lista: Equipamento[]
  usinaId?: string
  comTitulo: boolean
}) {
  const grupos = new Map<string, Equipamento[]>()
  for (const e of lista) {
    const chave = e.skid ?? ''
    const atual = grupos.get(chave)
    if (atual) atual.push(e)
    else grupos.set(chave, [e])
  }
  const porSkid = grupos.size > 1 || (grupos.size === 1 && !grupos.has(''))

  return (
    <>
      {comTitulo ? (
        <Text style={estilos.tituloSecao}>Inversores · {lista.length}</Text>
      ) : null}
      {[...grupos.entries()].map(([skid, itens]) => (
        <View key={skid || 'sem-skid'}>
          {porSkid ? (
            <View style={estilos.subtituloLinha}>
              <Text style={estilos.subtitulo}>{skid || 'Sem skid definido'}</Text>
              <Text style={tipo.legenda}>
                <Num style={estilos.subNum}>{itens.length}</Num>
              </Text>
            </View>
          ) : null}
          {itens.map((e) => (
            <CardEquipamento key={e.id} equipamento={e} usinaId={usinaId} />
          ))}
        </View>
      ))}
    </>
  )
}

function SecaoTemperatura({
  lista,
  comTitulo,
  usinaId,
}: {
  lista: ReleTemperatura[]
  comTitulo: boolean
  usinaId?: string
}) {
  if (lista.length === 0) {
    return (
      <>
        {comTitulo ? (
        <Text style={estilos.tituloSecao}>Relé de temperatura · {lista.length}</Text>
      ) : null}
        <Card>
          <Text style={tipo.fraco}>
            Esta usina não tem relé de temperatura no monitoramento.
          </Text>
        </Card>
      </>
    )
  }

  return (
    <>
      {comTitulo ? (
        <Text style={estilos.tituloSecao}>Relé de temperatura · {lista.length}</Text>
      ) : null}
      {lista.map((t) => (
        <Card key={t.id}>
          <View style={estilos.cabecaEquip}>
            <Text style={estilos.nomeEquip} numberOfLines={1}>
              {t.nome}
            </Text>
            <View style={estilos.espacador} />
            {t.comunicando ? (
              t.skid ? <Text style={tipo.legenda}>{t.skid}</Text> : null
            ) : (
              <StatusChip tom="semDados" texto="Sem comunicação" />
            )}
          </View>

          {/*
           * Uma coluna por bobina, com a leitura de agora em cima e a máxima do dia
           * embaixo. A máxima vem do próprio aparelho — não é o maior valor que o app
           * viu, que dependeria de o app estar aberto.
           */}
          <View style={estilos.bobinas}>
            <Bobina rotulo="Bobina 1" agora={t.s1} maxima={t.maxima_s1} />
            <Bobina rotulo="Bobina 2" agora={t.s2} maxima={t.maxima_s2} />
            <Bobina rotulo="Bobina 3" agora={t.s3} maxima={t.maxima_s3} />
            <Bobina rotulo="Ambiente" agora={t.ambiente} maxima={t.maxima_ambiente} />
          </View>

          {t.medido_em ? (
            <Text style={estilos.medido}>medido às {hora(t.medido_em)}</Text>
          ) : null}

          <DetalheTemperatura sensorId={t.id} usinaId={usinaId} />
        </Card>
      ))}
    </>
  )
}

function Bobina({
  rotulo,
  agora,
  maxima,
}: {
  rotulo: string
  agora: number | null
  maxima: number | null
}) {
  return (
    <View style={estilos.bobina}>
      <Text style={tipo.fraco}>{rotulo}</Text>
      <Num style={estilos.bobinaAgora}>{agora !== null ? `${numero(agora, 1)}°` : '—'}</Num>
      <Text style={tipo.fraco}>
        {maxima !== null ? (
          <>
            máx <Num style={estilos.bobinaMax}>{numero(maxima, 1)}°</Num>
          </>
        ) : (
          'máx —'
        )}
      </Text>
    </View>
  )
}

function SecaoProtecao({
  lista,
  comTitulo,
  usinaId,
}: {
  lista: ReleProtecao[]
  comTitulo: boolean
  usinaId?: string
}) {
  if (lista.length === 0) {
    return (
      <>
        {comTitulo ? (
        <Text style={estilos.tituloSecao}>Relé de proteção · {lista.length}</Text>
      ) : null}
        <Card>
          <Text style={tipo.fraco}>Esta usina não tem relé de proteção no monitoramento.</Text>
        </Card>
      </>
    )
  }

  return (
    <>
      {comTitulo ? (
        <Text style={estilos.tituloSecao}>Relé de proteção · {lista.length}</Text>
      ) : null}
      {lista.map((r) => (
        <Card key={r.id}>
          <View style={estilos.cabecaEquip}>
            <Text style={estilos.nomeEquip} numberOfLines={1}>
              {r.nome}
            </Text>
            <View style={estilos.espacador} />
            {!r.comunicando ? (
              <StatusChip tom="semDados" texto="Sem comunicação" />
            ) : r.flags.length > 0 ? (
              <StatusChip tom="parado" texto={`${r.flags.length} flag${r.flags.length > 1 ? 's' : ''}`} />
            ) : (
              <StatusChip tom="ok" texto="Sem flag" />
            )}
          </View>

          {r.skid || r.modelo ? (
            <Text style={tipo.fraco}>{[r.skid, r.modelo].filter(Boolean).join(' · ')}</Text>
          ) : null}

          {/* Flags ativas primeiro: é a única informação aqui que pede ação hoje. */}
          {r.flags.length > 0 ? (
            <View style={estilos.flags}>
              {r.flags.map((f) => (
                <View key={f} style={estilos.flag}>
                  <Text style={estilos.flagTexto}>{f}</Text>
                </View>
              ))}
            </View>
          ) : null}

          <View style={estilos.fases}>
            <Fase rotulo="A" tensao={r.tensao_a} corrente={r.corrente_a} potencia={r.potencia_a} />
            <Fase rotulo="B" tensao={r.tensao_b} corrente={r.corrente_b} potencia={r.potencia_b} />
            <Fase rotulo="C" tensao={r.tensao_c} corrente={r.corrente_c} potencia={r.potencia_c} />
          </View>

          <View style={estilos.totais}>
            <Total rotulo="Potência total" valor={r.potencia_total} unidade="kW" />
            <Total rotulo="Reativo" valor={r.reativo_kvar} unidade="kvar" />
            <Total rotulo="Frequência" valor={r.frequencia_hz} unidade="Hz" casas={2} />
          </View>

          {r.funcoes.length > 0 ? (
            <Text style={estilos.medido}>proteções: {r.funcoes.join(', ')}</Text>
          ) : null}
          {r.medido_em ? <Text style={estilos.medido}>medido às {hora(r.medido_em)}</Text> : null}

          <DetalheProtecao releId={r.id} usinaId={usinaId} />
        </Card>
      ))}
    </>
  )
}

function Fase({
  rotulo,
  tensao,
  corrente,
  potencia: pot,
}: {
  rotulo: string
  tensao: number | null
  corrente: number | null
  potencia: number | null
}) {
  return (
    <View style={estilos.fase}>
      <Text style={estilos.faseRotulo}>{rotulo}</Text>
      <Num style={estilos.faseValor}>{tensao !== null ? numero(tensao, 1) : '—'}</Num>
      <Text style={tipo.fraco}>V</Text>
      <Num style={estilos.faseValor}>{corrente !== null ? numero(corrente, 2) : '—'}</Num>
      <Text style={tipo.fraco}>A</Text>
      <Num style={estilos.faseValor}>{pot !== null ? numero(pot, 1) : '—'}</Num>
      <Text style={tipo.fraco}>kW</Text>
    </View>
  )
}

function Total({
  rotulo,
  valor,
  unidade,
  casas = 1,
}: {
  rotulo: string
  valor: number | null
  unidade: string
  casas?: number
}) {
  return (
    <View>
      <Text style={tipo.fraco}>{rotulo}</Text>
      <Text style={estilos.totalLinha}>
        <Num style={estilos.totalValor}>{valor !== null ? numero(valor, casas) : '—'}</Num>{' '}
        <Text style={tipo.fraco}>{unidade}</Text>
      </Text>
    </View>
  )
}

function CardEquipamento({ equipamento: e, usinaId }: { equipamento: Equipamento; usinaId?: string }) {
  const semDados = e.potencia_kw === null
  const [valor, unidade] = potencia(e.potencia_kw).split(' ')

  return (
    <Pressable onPress={() => router.push(`/equipamento/${e.id}?usina=${usinaId ?? ''}`)}>
      <Card>
        <View style={[estilos.topo, e.ignorado && estilos.apagado]}>
          <Text style={estilos.nome}>{e.nome}</Text>
          <StatusChip tom={e.tom} texto={e.situacao} />
          <View style={estilos.espacador} />
          <Chevron />
        </View>

        <View style={[estilos.linhaPotencia, e.ignorado && estilos.apagado]}>
          {semDados ? (
            <Num style={[estilos.potencia, { color: tons.semDados }]}>—</Num>
          ) : (
            <>
              <Num style={estilos.potencia}>{valor}</Num>
              <Text style={estilos.unidade}>{unidade}</Text>
            </>
          )}
          {e.capacidade_kwp ? (
            <Text style={estilos.capacidade}>
              de <Num style={estilos.capacidadeNum}>{inteiro(e.capacidade_kwp)}</Num> kWp
            </Text>
          ) : null}
        </View>

        {/* Idem: desconhecido não vira barra vazia. */}
        {e.pct_capacidade !== null ? (
          <View style={estilos.barra}>
            <Barra pct={e.pct_capacidade} tom={e.tom === 'ok' ? undefined : e.tom} />
          </View>
        ) : null}

        <View style={estilos.rodape}>
          <Text style={tipo.legenda} numberOfLines={1}>
            {e.modelo ?? e.serial ?? '—'}
          </Text>
          <Text style={tipo.legenda}>
            {e.energia_hoje_kwh !== null ? (
              <>
                hoje <Num style={estilos.energia}>{energia(e.energia_hoje_kwh)}</Num>
              </>
            ) : e.parado_ha_min !== null ? (
              <>
                parado há <Num style={estilos.energia}>{duracao(e.parado_ha_min)}</Num>
              </>
            ) : (
              '—'
            )}
          </Text>
        </View>
      </Card>
    </Pressable>
  )
}

function Fantasma() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <View style={estilos.topo}>
            <Esqueleto largura="30%" altura={16} forte />
            <View style={estilos.espacador} />
            <Esqueleto largura={70} altura={18} />
          </View>
          <View style={estilos.linhaPotencia}>
            <Esqueleto largura="35%" altura={26} forte />
          </View>
          <View style={estilos.barra}>
            <Esqueleto altura={6} />
          </View>
        </Card>
      ))}
    </>
  )
}


/**
 * O detalhe do relé de temperatura: a curva do dia e a máxima de cada dia do intervalo.
 *
 * Fica fechado por padrão. Numa usina com seis trafos, seis gráficos abertos de uma vez
 * transformariam a tela numa rolagem infinita — e o caso comum é olhar a lista, não
 * mergulhar em cada aparelho.
 *
 * As duas perguntas são diferentes e por isso são dois modos: "como foi hoje" é a curva
 * de 5 em 5 minutos; "está esquentando com o tempo" é a máxima diária ao longo de dias,
 * que a curva de um dia não responde.
 */
function DetalheTemperatura({ sensorId, usinaId }: { sensorId: string; usinaId?: string }) {
  const [aberto, setAberto] = useState(false)
  const [modo, setModo] = useState(0)
  const [dia, setDia] = useState(hojeIso())
  const [janela, setJanela] = useState(7)

  const curva = useCurvaTemperatura(usinaId, sensorId, dia, aberto && modo === 0)
  const maximas = useMaximas(usinaId, sensorId, janela, aberto && modo === 1)

  if (!aberto) {
    return (
      <Text style={estilos.abrir} onPress={() => setAberto(true)}>
        ver gráfico e máximas
      </Text>
    )
  }

  return (
    <View style={estilos.detalhe}>
      <Segmentado opcoes={['Hoje', 'Máximas']} ativo={modo} onEscolher={setModo} />

      {modo === 0 ? (
        <>
          <View style={estilos.detalheSeletor}>
            <SeletorPeriodo valor={dia} recorte="dia" onEscolher={setDia} />
          </View>
          {curva.carregando && !curva.dados ? (
            <Esqueleto altura={150} />
          ) : curva.erro || !curva.dados || curva.dados.series.length === 0 ? (
            <Text style={tipo.fraco}>
              {curva.erro ?? curva.dados?.aviso ?? 'Sem leitura deste sensor neste dia.'}
            </Text>
          ) : (
            <GraficoExpansivel titulo="Temperatura ao longo do dia">
              {(altura) => (
                <GraficoSeries
                  horas={curva.dados!.horas}
                  series={curva.dados!.series}
                  altura={altura ?? 150}
                  unidade="°C"
                  casas={1}
                />
              )}
            </GraficoExpansivel>
          )}
        </>
      ) : (
        <>
          <View style={estilos.detalheSeletor}>
            <Segmentado
              opcoes={['7 dias', '15 dias', '30 dias']}
              ativo={janela === 7 ? 0 : janela === 15 ? 1 : 2}
              onEscolher={(i) => setJanela([7, 15, 30][i])}
            />
          </View>
          {maximas.carregando && !maximas.dados ? (
            <Esqueleto altura={150} />
          ) : maximas.erro || !maximas.dados || maximas.dados.dias.length === 0 ? (
            <Text style={tipo.fraco}>
              {maximas.erro ?? maximas.dados?.aviso ?? 'Sem leitura deste sensor no intervalo.'}
            </Text>
          ) : (
            <>
              {maximas.dados.pico !== null ? (
                <Text style={tipo.fraco}>
                  pico de <Num style={estilos.picoNum}>{numero(maximas.dados.pico, 1)}°</Num> em{' '}
                  {(maximas.dados.pico_em ?? '').slice(8, 10)}/
                  {(maximas.dados.pico_em ?? '').slice(5, 7)}
                </Text>
              ) : null}
              {/*
               * Dia sem leitura vem com `maxima` nula e é DESCARTADO do gráfico, não
               * desenhado como barra rasteira — uma barra no chão diria que a bobina
               * esfriou, quando o que houve foi o monitoramento não medir.
               */}
              <GraficoExpansivel titulo="Máxima de cada dia">
                {(altura) => (
                  <GraficoBarras
                    pontos={maximas.dados!.dias
                      .filter((d) => d.maxima !== null)
                      .map((d) => ({
                        chave: d.dia,
                        rotulo: d.dia.slice(8, 10),
                        kwh: d.maxima as number,
                      }))}
                    altura={altura ?? 120}
                    unidade="°C"
                    casas={1}
                  />
                )}
              </GraficoExpansivel>
              {maximas.dados.dias.some((d) => d.maxima === null) ? (
                <Text style={tipo.fraco}>
                  {maximas.dados.dias.filter((d) => d.maxima === null).length} dia(s) sem leitura
                  não aparecem no gráfico.
                </Text>
              ) : null}
            </>
          )}
        </>
      )}

      <Text style={estilos.abrir} onPress={() => setAberto(false)}>
        fechar
      </Text>
    </View>
  )
}

/**
 * O detalhe do relé de proteção: as três fases ao longo do dia e o histórico de flags.
 *
 * A grandeza é escolhida porque as três respondem perguntas diferentes: tensão mostra
 * afundamento da rede, corrente mostra desequilíbrio de carga, potência mostra o que o
 * trafo entregou. Sobrepor todas num eixo só não compararia nada — as ordens de grandeza
 * são incompatíveis.
 */
function DetalheProtecao({ releId, usinaId }: { releId: string; usinaId?: string }) {
  const [aberto, setAberto] = useState(false)
  const [modo, setModo] = useState(0)
  const [dia, setDia] = useState(hojeIso())
  const [grandeza, setGrandeza] = useState(0)

  const grandezas = ['tensao', 'corrente', 'potencia'] as const
  const unidades = ['V', 'A', 'kW']

  const curva = useCurvaProtecao(usinaId, releId, dia, grandezas[grandeza], aberto && modo === 0)
  const flags = useHistoricoDeFlags(usinaId, releId, aberto && modo === 1)

  if (!aberto) {
    return (
      <Text style={estilos.abrir} onPress={() => setAberto(true)}>
        ver gráfico e histórico
      </Text>
    )
  }

  return (
    <View style={estilos.detalhe}>
      <Segmentado opcoes={['Curvas', 'Histórico']} ativo={modo} onEscolher={setModo} />

      {modo === 0 ? (
        <>
          <View style={estilos.detalheSeletor}>
            <Segmentado
              opcoes={['Tensão', 'Corrente', 'Potência']}
              ativo={grandeza}
              onEscolher={setGrandeza}
            />
          </View>
          <View style={estilos.detalheSeletor}>
            <SeletorPeriodo valor={dia} recorte="dia" onEscolher={setDia} />
          </View>
          {curva.carregando && !curva.dados ? (
            <Esqueleto altura={150} />
          ) : curva.erro || !curva.dados || curva.dados.series.length === 0 ? (
            <Text style={tipo.fraco}>
              {curva.erro ?? curva.dados?.aviso ?? 'Sem leitura deste relé neste dia.'}
            </Text>
          ) : (
            <GraficoExpansivel titulo={`${['Tensão', 'Corrente', 'Potência'][grandeza]} por fase`}>
              {(altura) => (
                <GraficoSeries
                  horas={curva.dados!.horas}
                  series={curva.dados!.series}
                  altura={altura ?? 150}
                  unidade={unidades[grandeza]}
                  casas={grandeza === 1 ? 2 : 1}
                />
              )}
            </GraficoExpansivel>
          )}
        </>
      ) : flags.carregando && !flags.dados ? (
        <Esqueleto altura={120} />
      ) : flags.erro || !flags.dados || flags.dados.eventos.length === 0 ? (
        <Text style={tipo.fraco}>
          {flags.erro ?? flags.dados?.aviso ?? 'Este relé não tem histórico de flags.'}
        </Text>
      ) : (
        <View style={estilos.eventos}>
          {flags.dados.eventos.map((e, i) => (
            <View key={`${e.quando ?? ''}-${e.codigo ?? ''}-${i}`} style={estilos.evento}>
              <Text style={estilos.eventoQuando}>
                {e.quando ? `${dataHora(e.quando)}` : '—'}
              </Text>
              <Text style={estilos.eventoTexto} numberOfLines={2}>
                {[e.codigo, e.evento].filter(Boolean).join(' · ') || '—'}
                {e.de || e.para ? ` (${e.de ?? '—'} → ${e.para ?? '—'})` : ''}
              </Text>
            </View>
          ))}
        </View>
      )}

      <Text style={estilos.abrir} onPress={() => setAberto(false)}>
        fechar
      </Text>
    </View>
  )
}

const estilos = StyleSheet.create({
  inventario: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco, marginTop: espaco.xs },
  inventarioNum: { fontSize: 11, color: cores.textoCorpo },
  abrir: { fontFamily: fontes.ui, fontSize: 12, color: cores.ambar, marginTop: espaco.xs },
  detalhe: { marginTop: espaco.sm, gap: espaco.xs },
  detalheSeletor: { marginTop: espaco.xs },
  picoNum: { fontSize: 12, color: cores.textoForte },

  eventos: { gap: espaco.xs, marginTop: espaco.xs },
  evento: { flexDirection: 'row', gap: espaco.xs, alignItems: 'flex-start' },
  eventoQuando: { fontFamily: fontes.mono, fontSize: 11, color: cores.textoRotulo, width: 78 },
  eventoTexto: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoCorpo, flex: 1 },

  tituloSecao: {
    fontFamily: fontes.ui,
    fontSize: 13,
    color: cores.textoForte,
    marginTop: espaco.sm,
  },
  subtituloLinha: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: espaco.xs,
    marginBottom: 2,
  },
  subtitulo: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo },

  problemas: { marginTop: espaco.xs, gap: espaco.xs },
  problema: { flexDirection: 'row', alignItems: 'center', gap: espaco.xs },
  problemaNome: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoForte, flexShrink: 1 },
  problemaDetalhe: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco, flex: 1 },

  cabecaEquip: { flexDirection: 'row', alignItems: 'center', gap: espaco.xs },
  nomeEquip: { fontFamily: fontes.ui, fontSize: 14, color: cores.textoForte, flexShrink: 1 },

  bobinas: { flexDirection: 'row', marginTop: espaco.sm, gap: espaco.xs },
  bobina: { flex: 1, gap: 1 },
  bobinaAgora: { fontSize: 16, color: cores.textoForte },
  bobinaMax: { fontSize: 10, color: cores.textoCorpo },

  flags: { flexDirection: 'row', flexWrap: 'wrap', gap: espaco.xs, marginTop: espaco.xs },
  flag: {
    borderWidth: 1,
    borderColor: tons.parado,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  flagTexto: { fontFamily: fontes.ui, fontSize: 11, color: tons.parado },

  fases: { marginTop: espaco.sm, gap: 2 },
  fase: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  faseRotulo: {
    fontFamily: fontes.ui,
    fontSize: 11,
    color: cores.textoRotulo,
    width: 12,
  },
  faseValor: { fontSize: 12, color: cores.textoForte, minWidth: 52, textAlign: 'right' },

  totais: { flexDirection: 'row', justifyContent: 'space-between', marginTop: espaco.sm },
  totalLinha: { marginTop: 1 },
  totalValor: { fontSize: 13, color: cores.textoForte },

  medido: { fontFamily: fontes.ui, fontSize: 10, color: cores.textoFraco, marginTop: espaco.xs },

  subNum: { fontSize: 13, color: cores.textoRotulo },

  resumo: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: espaco.xs },
  resumoNum: { fontSize: 15 },
  ponto: { width: 8, height: 8, borderRadius: 4 },
  espacador: { flex: 1 },

  aviso: { ...tipo.fraco, paddingHorizontal: espaco.xs },

  topo: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  nome: { fontFamily: fontes.uiSemi, fontSize: 16, color: cores.textoForte },
  /** Ignorado no meuWatt: presente, mas visivelmente fora da conta. */
  apagado: { opacity: 0.45 },

  linhaPotencia: { flexDirection: 'row', alignItems: 'baseline', gap: 7, marginTop: 12 },
  potencia: { fontFamily: fontes.monoSemi, fontSize: 26, lineHeight: 26, color: cores.textoForte },
  unidade: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoCorpo },
  capacidade: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo, marginLeft: 'auto' },
  capacidadeNum: { fontSize: 12, color: cores.textoCorpo },

  barra: { marginTop: 12 },
  rodape: { flexDirection: 'row', justifyContent: 'space-between', marginTop: espaco.sm, gap: 12 },
  energia: { fontSize: 12, color: cores.textoForte },
})
