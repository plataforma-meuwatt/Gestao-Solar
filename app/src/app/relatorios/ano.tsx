/**
 * O ano inteiro, usina por usina, mês a mês — e o fecho anual no fim de cada linha.
 *
 * O pedido do dono, literal: *"faça uma versão da tela para o usuário ver facilmente os
 * relatórios do ANO, MÊS A MÊS, e aí, no final do ano, o RELATÓRIO ANUAL — isso POR USINA.
 * Tanto GERAÇÃO quanto MANUTENÇÃO, TÉCNICO e EXECUTIVO."*
 *
 * ## A matriz que ele imaginou tem buracos reais, e a tela os nomeia
 *
 * Das quatro combinações pedidas, **duas não existem** — e isso foi medido, não suposto:
 *
 * | | mensal | anual |
 * |---|---|---|
 * | **geração · técnico** (`geracao`, `paradas`) | existe | **não existe** |
 * | **geração · executivo** (`resumo`) | existe | **não existe** |
 * | **manutenção · técnico** (relatório + fichas) | existe | existe |
 * | **manutenção · executivo** | **não existe em nenhuma** | — |
 *
 * O anual de geração: a aba Anual do meuWatt cria a linha, mas o gerador de PDF de lá só
 * roda para MENSAL — um relatório ANUAL nasce sem arquivo nenhum, e em produção há **zero
 * linhas ANUAL**. Existe o continente, não o conteúdo. O executivo de manutenção: varridos
 * o serviço e o PDF, **não há parâmetro de modo**.
 *
 * Uma grade que desenhasse as quatro células cheias mentiria em duas. Aqui as duas ausentes
 * dizem o que falta e **não têm botão** — botão morto é pior que a frase.
 *
 * ## Tela EMPURRADA, não a sexta aba
 *
 * A grade custa uma ida de 4,7 s morna (7 usinas, medido em 05/09/2026). Quem abriu a aba
 * Relatórios para pegar o PDF de agosto não pode pagar por isso.
 *
 * ## Nenhuma conta de conformidade acontece aqui
 *
 * O percentual do ano é o `pct_ate_hoje` do servidor, exibido **sempre** com o mês de
 * referência e o denominador colados ("41,9 % · 13 de 31 até setembro de 2026"). Foi
 * confundir esse recorte com o total do contrato que produziu "13 de 270" numa tela e
 * "41,9 %" na outra, para a mesma usina. Os dois números aparecem juntos, cada um com o
 * rótulo que o explica.
 *
 * ## O calendário é do meuPlano
 *
 * Mês `futuro` **nunca recebe cor de falta**. A classificação vem do servidor justamente
 * para isso: derivada do relógio do celular, ela acusaria de atraso um mês que ainda não
 * venceu — 62 atividades de Porto Ferreira, hoje, em out/nov/dez.
 */

import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'
import { router } from 'expo-router'
import { useEffect, useRef, useState } from 'react'
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native'

import { AbrirPdf } from '@/components/AbrirPdf'
import {
  Botao,
  CabecalhoCard,
  Card,
  Esqueleto,
  EstadoVazio,
  Num,
  Segmentado,
  StatusChip,
} from '@/components/base'
import { EscolhaEmLista } from '@/components/EscolhaEmLista'
import { Folha, LinhaPdf } from '@/components/folha'
import { Tela } from '@/components/Tela'
import { frasePecaAusente, peso, PECAS } from '@/features/relatorios'
import {
  andamentoDoPreparo,
  anosOferecidos,
  fraseAnualDeEnergia,
  frasePublicoDaManutencao,
  inventarioDeFichas,
  janelaPorExtenso,
  linhasVisiveis,
  marcaDaEnergia,
  marcaDaManutencao,
  ofertaDoPacote,
  opcoesDeUsina,
  prepararFichas,
  recorteDoAno,
  rotuloDoPublico,
  urlDoPacoteDeFichas,
  urlDoRelatorioDeManutencao,
  useGradeDoAno,
  usinaEscolhida,
  type CelulaDoAno,
  type Familia,
  type InventarioDeFichas,
  type Marca,
  type PecaDoAno,
  type PreparoDeFichas,
  type UsinaDoAno,
} from '@/features/relatorios-ano'
import { tokenDaSessao } from '@/lib/api'
import { dataPorExtenso, numero } from '@/lib/format'
import { cores, espaco, fontes, raio, tons, TOQUE_MIN, tomAlpha } from '@/theme/tokens'

/** Largura da coluna fixa da esquerda: o nome da usina. */
const LARGURA_NOME = 132
/** Largura de uma célula de mês. Cabem dois dígitos e a nota miúda embaixo. */
const LARGURA_MES = 40
/** A coluna do fecho do ano, no fim da linha. Mais larga: ela tem rótulo. */
const LARGURA_ANO = 58

const MESES_CURTOS = [
  'jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez',
]

const mesCurto = (yyyyMm: string) => MESES_CURTOS[Number(yyyyMm.slice(5, 7)) - 1] ?? yyyyMm

/** Onde a folha aberta está apontando. `null` = nenhuma. */
type Aberto =
  | { tipo: 'mes'; usina: UsinaDoAno; celula: CelulaDoAno }
  | { tipo: 'ano'; usina: UsinaDoAno }

export default function RelatoriosDoAno() {
  const anoCorrente = new Date().getFullYear()
  const [ano, setAno] = useState(anoCorrente)
  const [familia, setFamilia] = useState<Familia>('energia')
  const [usina, setUsina] = useState<string | null>(null)
  const [aberto, setAberto] = useState<Aberto | null>(null)

  const { dados, carregando, erro, offlineDesde, recarregar } = useGradeDoAno(ano)

  const usinas = dados?.usinas ?? []
  // Grampeia: uma usina guardada que saiu do escopo deixaria a tela vazia para sempre.
  const escolhida = usinaEscolhida(usinas, usina)
  const linhas = linhasVisiveis(usinas, escolhida)
  const opcoes = opcoesDeUsina(usinas, familia)

  return (
    <Tela
      titulo="Relatórios do ano"
      /* O subtítulo conta o que está NA TELA. Com uma usina escolhida, dizer "7 usinas"
         seria descrever a carteira e não o recorte — e o dono leria o número errado. */
      subtitulo={
        dados
          ? escolhida
            ? `${dados.ano} · ${linhas[0]?.nome ?? ''}`
            : `${dados.ano} · ${usinas.length} ${usinas.length === 1 ? 'usina' : 'usinas'}`
          : undefined
      }
      voltar
      offlineDesde={offlineDesde}
    >
      {carregando && !dados ? (
        <Card>
          <Esqueleto largura="45%" altura={14} forte />
          <View style={estilos.espaco}>
            <Esqueleto altura={220} />
          </View>
        </Card>
      ) : erro || !dados ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro ?? 'A grade do ano está indisponível.'}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : (
        <>
          {/* Energia e manutenção são NATUREZAS diferentes, não dois assuntos: uma é acervo
              publicado, a outra é montada sob demanda a partir do ativo. */}
          <Segmentado
            opcoes={['Energia', 'Manutenção']}
            ativo={familia === 'energia' ? 0 : 1}
            onEscolher={(i) => setFamilia(i === 0 ? 'energia' : 'manutencao')}
          />

          <View style={estilos.filtros}>
            <EscolhaEmLista
              rotulo="Ano"
              titulo="Ano do relatório"
              opcoes={anosOferecidos(anoCorrente).map((a) => ({
                valor: String(a),
                rotulo: String(a),
              }))}
              valor={String(ano)}
              aoEscolher={(v) => setAno(Number(v ?? anoCorrente))}
            />
            {/* Com uma usina só o seletor é mobília: a linha única já diz de quem é. */}
            {usinas.length > 1 ? (
              <EscolhaEmLista
                rotulo="Usina"
                titulo="Filtrar por usina"
                opcoes={opcoes}
                valor={escolhida}
                aoEscolher={setUsina}
              />
            ) : null}
          </View>

          {dados.aviso ? <Text style={estilos.aviso}>{dados.aviso}</Text> : null}

          <Card>
            <CabecalhoCard
              rotulo={familia === 'energia' ? 'Geração publicada' : 'Manutenção do contrato'}
              direita={<Text style={estilos.legendaTopo}>toque numa célula</Text>}
            />
            {linhas.length === 0 ? (
              // A lei de nunca deixar a tela vazia por filtro. Não acontece com o grampo
              // acima, mas se um dia acontecer, ela diz o que fazer.
              <Text style={estilos.semLinhas}>
                Nenhuma usina neste filtro. Escolha “Todas as usinas” para ver a carteira.
              </Text>
            ) : (
              <Grade
                meses={dados.meses}
                usinas={linhas}
                familia={familia}
                aoAbrirMes={(u, c) => setAberto({ tipo: 'mes', usina: u, celula: c })}
                aoAbrirAno={(u) => setAberto({ tipo: 'ano', usina: u })}
              />
            )}
            <Legenda familia={familia} />
          </Card>

          {familia === 'manutencao' ? (
            linhas.map((u) => <ResumoDaUsina key={u.id} usina={u} />)
          ) : linhas.length > 0 ? (
            <FechoAnualDeEnergia usinas={linhas} />
          ) : null}
        </>
      )}

      <Folha
        visivel={aberto !== null}
        aoFechar={() => setAberto(null)}
        titulo={
          aberto
            ? aberto.tipo === 'ano'
              ? `${aberto.usina.nome} · ${ano}`
              : `${aberto.usina.nome} · ${mesLongo(aberto.celula.mes)}`
            : undefined
        }
      >
        {aberto === null ? null : aberto.tipo === 'mes' ? (
          <DetalheDoMes usina={aberto.usina} celula={aberto.celula} familia={familia} />
        ) : (
          <DetalheDoAno usina={aberto.usina} />
        )}
      </Folha>
    </Tela>
  )
}

function mesLongo(yyyyMm: string): string {
  const nomes = [
    'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
  ]
  return `${nomes[Number(yyyyMm.slice(5, 7)) - 1] ?? yyyyMm} de ${yyyyMm.slice(0, 4)}`
}

/* ══════════════════════════════════════════════════════════════════════════ a grade ══ */

/**
 * A grade com a coluna de nomes FIXA e os meses rolando na horizontal.
 *
 * Doze colunas legíveis não cabem em 390 pt, e encolher a fonte até caber é como se perde a
 * leitura de relance que a tela existe para dar. O cabeçalho dos meses fica dentro do rolar
 * horizontal (acompanha até dezembro) e as duas colunas desenham a MESMA sequência de linhas
 * — se um lado tivesse um `if` a mais, a usina apareceria com a marca da vizinha, que é o
 * pior defeito possível numa tela de conformidade.
 */
function Grade({
  meses,
  usinas,
  familia,
  aoAbrirMes,
  aoAbrirAno,
}: {
  meses: string[]
  usinas: UsinaDoAno[]
  familia: Familia
  aoAbrirMes: (u: UsinaDoAno, c: CelulaDoAno) => void
  aoAbrirAno: (u: UsinaDoAno) => void
}) {
  return (
    <View style={estilos.grade}>
      <View style={{ width: LARGURA_NOME }}>
        <View style={estilos.cantoNome}>
          <Text style={estilos.cabecalhoTexto}>Usina</Text>
        </View>
        {usinas.map((u) => (
          <View key={u.id} style={estilos.celulaNome}>
            <Text style={estilos.nomeUsina} numberOfLines={2}>
              {u.nome}
            </Text>
            {/* O motivo é da MANUTENÇÃO — só aparece na aba dela. Na aba de geração,
                esta mesma linha dizia "A equipe ainda não publico…", cortada, ao lado de
                células que falam de arquivo publicado: o motivo de uma família no lugar
                onde se procura o da outra. Duas linhas, porque em uma a frase morre no
                meio e deixa de informar. */}
            {familia === 'manutencao' && u.aviso_manutencao ? (
              <Text style={estilos.avisoLinha} numberOfLines={2}>
                {u.aviso_manutencao}
              </Text>
            ) : null}
          </View>
        ))}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View>
          <View style={estilos.cabecalhoMeses}>
            {meses.map((m) => (
              <View key={m} style={estilos.cabecalhoMes}>
                <Text style={estilos.mesTexto}>{mesCurto(m)}</Text>
              </View>
            ))}
            <View style={estilos.cabecalhoAno}>
              <Text style={estilos.mesTexto}>ano</Text>
            </View>
          </View>

          {usinas.map((u) => (
            <View key={u.id} style={estilos.linha}>
              {u.meses.map((c) => (
                <Celula
                  key={c.mes}
                  marca={familia === 'energia' ? marcaDaEnergia(c.energia) : marcaDaManutencao(c.manutencao)}
                  rotuloAcessivel={`${u.nome}, ${mesLongo(c.mes)}`}
                  onPress={() => aoAbrirMes(u, c)}
                />
              ))}
              <CelulaDoFechoAnual usina={u} familia={familia} onPress={() => aoAbrirAno(u)} />
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  )
}

/**
 * Uma célula.
 *
 * `forte` preenche; sem ele, contorna. É essa diferença — e não cinco tons de cinza — que
 * separa "há coisa aqui" de "não há", e as ausências entre si.
 */
function Celula({
  marca,
  rotuloAcessivel,
  onPress,
  largura = LARGURA_MES,
}: {
  marca: Marca
  rotuloAcessivel: string
  /** Sem `onPress` a célula **não é um botão** — nem visual, nem para o leitor de tela.
   *  Uma seta ou um realce de toque é promessa de navegação: o dono toca, nada acontece, e
   *  ele conclui que o aplicativo travou. É o caso do fecho anual da geração, que não tem
   *  arquivo nenhum para abrir em lugar nenhum. */
  onPress?: () => void
  largura?: number
}) {
  const vazia = marca.letra === ''
  const miolo = (
    <>
      {vazia ? (
        <Text style={estilos.travessao}>·</Text>
      ) : (
        <View
          style={[
            estilos.pastilha,
            marca.forte
              ? { backgroundColor: tomAlpha(marca.tom, 0.18), borderColor: tomAlpha(marca.tom, 0.5) }
              : { borderColor: tomAlpha(marca.tom, 0.35) },
          ]}
        >
          <Text style={[estilos.pastilhaTexto, { color: tons[marca.tom] }]}>{marca.letra}</Text>
        </View>
      )}
      {marca.nota ? (
        <Text style={estilos.notaCelula} numberOfLines={1}>
          {marca.nota}
        </Text>
      ) : null}
    </>
  )

  if (!onPress) {
    return (
      <View
        style={[estilos.celula, { width: largura }]}
        accessibilityLabel={`${rotuloAcessivel}: ${marca.rotulo}`}
      >
        {miolo}
      </View>
    )
  }
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [estilos.celula, { width: largura }, pressed && estilos.celulaTocada]}
      accessibilityRole="button"
      accessibilityLabel={`${rotuloAcessivel}: ${marca.rotulo}`}
    >
      {miolo}
    </Pressable>
  )
}

/**
 * O fecho do ano, no fim da linha.
 *
 * **Em ENERGIA a célula NÃO é pressionável, e é de propósito.** O monitoramento não publica
 * fechamento anual em lugar nenhum — a aba Anual do meuWatt cria a linha, mas o gerador de
 * PDF de lá só roda para MENSAL, e em produção há zero linhas ANUAL. Um botão que abrisse
 * uma folha para dizer "não existe" ainda seria uma promessa de navegação; a razão sai
 * escrita, uma vez, no cartão abaixo da grade.
 *
 * Em MANUTENÇÃO ele leva ao relatório da janela real, com a janela impressa antes do botão.
 */
function CelulaDoFechoAnual({
  usina,
  familia,
  onPress,
}: {
  usina: UsinaDoAno
  familia: Familia
  onPress: () => void
}) {
  const a = familia === 'energia' ? usina.anual.energia : usina.anual.manutencao
  const marca: Marca = a.disponivel
    ? { letra: 'PDF', tom: 'ok', forte: true, rotulo: 'Relatório do ano disponível' }
    : { letra: '—', tom: 'semDados', forte: false, rotulo: a.motivo ?? 'Não disponível' }
  return (
    <Celula
      marca={marca}
      rotuloAcessivel={`${usina.nome}, fecho do ano`}
      onPress={familia === 'energia' ? undefined : onPress}
      largura={LARGURA_ANO}
    />
  )
}

/**
 * Por que a coluna "ano" da geração está toda em travessão.
 *
 * A frase vem do servidor (`anual.energia.motivo`) e as usinas são agrupadas por motivo: são
 * dois hoje — "o monitoramento ainda não publica fechamento anual" para as seis ligadas, e
 * "esta usina não está ligada ao monitoramento" para a UFV Leme. Repetir a mesma frase sete
 * vezes seria ruído; escondê-la deixaria a coluna muda.
 */
function FechoAnualDeEnergia({ usinas }: { usinas: UsinaDoAno[] }) {
  const porMotivo = new Map<string, string[]>()
  for (const u of usinas) {
    const motivo = fraseAnualDeEnergia(u.anual.energia)
    porMotivo.set(motivo, [...(porMotivo.get(motivo) ?? []), u.nome])
  }
  return (
    <Card>
      <CabecalhoCard rotulo="Fechamento anual da geração" />
      {[...porMotivo.entries()].map(([motivo, nomes]) => (
        <View key={motivo} style={estilos.motivoAnual}>
          <Text style={estilos.folhaTexto}>{motivo}</Text>
          <Text style={estilos.folhaApoio}>
            {nomes.length === usinas.length ? 'Vale para todas as usinas.' : nomes.join(' · ')}
          </Text>
        </View>
      ))}
      <Text style={estilos.folhaApoio}>
        Os fechamentos mensais continuam na grade acima, mês a mês. Não há botão nesta coluna
        porque não existe arquivo anual para abrir.
      </Text>
    </Card>
  )
}

function Legenda({ familia }: { familia: Familia }) {
  const itens =
    familia === 'energia'
      ? [
          { tom: 'ok' as const, forte: true, letra: '2', texto: 'arquivos publicados' },
          { tom: 'alerta' as const, forte: false, letra: '!', texto: 'fechado sem arquivo' },
          { tom: 'semDados' as const, forte: false, letra: '·', texto: 'mês não fechado' },
          { tom: 'semDados' as const, forte: false, letra: '—', texto: 'sem monitoramento' },
          { tom: 'tempoRuim' as const, forte: false, letra: '?', texto: 'não deu para saber' },
        ]
      : [
          { tom: 'ok' as const, forte: true, letra: '13', texto: 'mês cumprido' },
          { tom: 'parado' as const, forte: false, letra: '2', texto: 'venceu incompleto' },
          { tom: 'alerta' as const, forte: false, letra: '0', texto: 'mês em curso' },
          { tom: 'tempoRuim' as const, forte: false, letra: '13', texto: 'ainda não venceu' },
        ]
  return (
    <View style={estilos.legenda}>
      {itens.map((i) => (
        <View key={i.texto} style={estilos.legendaItem}>
          <View
            style={[
              estilos.legendaPastilha,
              i.forte
                ? { backgroundColor: tomAlpha(i.tom, 0.18), borderColor: tomAlpha(i.tom, 0.5) }
                : { borderColor: tomAlpha(i.tom, 0.35) },
            ]}
          >
            <Text style={[estilos.legendaLetra, { color: tons[i.tom] }]}>{i.letra}</Text>
          </View>
          <Text style={estilos.legendaTexto}>{i.texto}</Text>
        </View>
      ))}
    </View>
  )
}

/* ═══════════════════════════════════════════════════════════ o recorte de vigência ══ */

/**
 * O percentual do ano — **nunca sozinho**.
 *
 * Sai com o mês de referência e o denominador colados, e com o total do contrato ao lado,
 * cada um rotulado. É o mesmo `pct_ate_hoje` que a tela de Cronograma mostra, repassado do
 * meuPlano: dois números para a mesma pergunta têm de ser o mesmo número.
 */
function ResumoDaUsina({ usina }: { usina: UsinaDoAno }) {
  const r = recorteDoAno(usina)
  return (
    <Card>
      <CabecalhoCard
        rotulo={usina.nome}
        direita={
          usina.cronograma_status ? (
            <Text style={estilos.versao}>
              {usina.cronograma_status === 'CONSOLIDATED' ? 'consolidado' : 'rascunho'}
              {usina.cronograma_versao !== null ? ` · v${usina.cronograma_versao}` : ''}
            </Text>
          ) : undefined
        }
      />
      {r === null ? (
        <Text style={estilos.explicacao}>
          {usina.aviso_manutencao ??
            'A equipe ainda não publicou o cronograma deste contrato.'}
        </Text>
      ) : (
        <>
          <View style={estilos.recorte}>
            <Num style={estilos.pct}>{numero(r.pct, 1)}%</Num>
            <View style={estilos.recorteMiolo}>
              <Text style={estilos.recorteFrase}>{r.frase}</Text>
              <Text style={estilos.recorteRotulo}>cumprido do que já venceu no contrato</Text>
            </View>
          </View>
          {r.noContrato !== null ? (
            <Text style={estilos.recorteOutro}>
              O contrato prevê <Num style={estilos.recorteOutroNum}>{r.noContrato}</Num> atividades
              nos doze meses — inclusive as dos meses que ainda não chegaram, que não entram na
              conta acima.
            </Text>
          ) : null}
        </>
      )}
    </Card>
  )
}

/* ════════════════════════════════════════════════════════════════ a folha do mês ══ */

function DetalheDoMes({
  usina,
  celula,
  familia,
}: {
  usina: UsinaDoAno
  celula: CelulaDoAno
  familia: Familia
}) {
  return familia === 'energia' ? (
    <EnergiaDoMes usina={usina} celula={celula} />
  ) : (
    <ManutencaoDoMes usina={usina} celula={celula} />
  )
}

function EnergiaDoMes({ usina, celula }: { usina: UsinaDoAno; celula: CelulaDoAno }) {
  const e = celula.energia
  if (e.estado === 'publicado' && e.documento_id !== null) {
    return (
      <View style={estilos.folhaMiolo}>
        {e.publicado_em ? (
          <Text style={estilos.folhaApoio}>
            Publicado em {dataPorExtenso(e.publicado_em)} pela equipe do monitoramento.
          </Text>
        ) : null}
        {e.pecas.map((p, i) => (
          <PecaAbrivel
            key={p.tipo}
            peca={p}
            documentoId={e.documento_id as number}
            usina={usina.nome}
            mes={celula.mes}
            primeira={i === 0}
          />
        ))}
      </View>
    )
  }

  const frase =
    e.estado === 'fechamento_sem_arquivo'
      ? frasePecaAusente()
      : e.estado === 'sem_fechamento'
        ? 'O monitoramento ainda não fechou este mês para esta usina. Quando fechar e a equipe anexar os PDFs, eles aparecem aqui.'
        : e.estado === 'sem_monitoramento'
          ? 'Esta usina não está ligada ao monitoramento, que é de onde vêm os relatórios de geração.'
          : e.estado === 'indisponivel'
            ? 'Não deu para falar com o monitoramento agora. Isto não quer dizer que não haja relatório — quer dizer que não sabemos. Puxe a tela para recarregar quando houver sinal.'
            : `O servidor devolveu um estado que este aplicativo ainda não conhece: “${e.estado}”.`
  return (
    <View style={estilos.folhaMiolo}>
      <Text style={estilos.folhaTexto}>{frase}</Text>
    </View>
  )
}

/**
 * Uma peça, com o público e o peso ANTES do toque — e o toque abre o LEITOR INTERNO.
 *
 * O peso vem do servidor (`size_bytes`) e a diferença medida é de sessenta vezes — 43.238 B
 * no Resumo Executivo de Pereiras contra 2.686.172 B no Relatório de Geração de Porto
 * Ferreira. Quem está no 3G precisa saber se são dois segundos ou dois minutos.
 *
 * O destino é `/relatorio/{id}`, a MESMA rota que o card da lista abre — não uma segunda
 * cópia do caminho do PDF. Usina e competência viajam como parâmetro porque não existe
 * `GET /documents/{id}` para o cabeçalho consultar, e a grade já tem os dois na mão: sem
 * eles a tela do documento diria "Relatório de Geração" sem dizer de qual usina nem de qual
 * mês. **A sessão não vai na rota** — quem a carrega é o `LeitorPdf`, em cabeçalho.
 */
function PecaAbrivel({
  peca,
  documentoId,
  usina,
  mes,
  primeira,
}: {
  peca: PecaDoAno
  documentoId: number
  usina: string
  /** `YYYY-MM` da coluna — a competência que o cabeçalho da outra tela escreve. */
  mes: string
  primeira: boolean
}) {
  const publico = rotuloDoPublico(peca.tipo)
  const nome = PECAS[peca.tipo]?.rotulo ?? peca.nome
  const destino =
    `/relatorio/${documentoId}?tipo=${encodeURIComponent(peca.tipo)}` +
    `&nome=${encodeURIComponent(peca.nome)}` +
    `&usina=${encodeURIComponent(usina)}&competencia=${encodeURIComponent(mes)}`

  return (
    <LinhaPdf
      nome={publico ? `${nome}  ·  ${publico}` : nome}
      tamanho={peso(peca.bytes)}
      semDivisoria={primeira}
      onPress={() => router.push(destino)}
    />
  )
}

function ManutencaoDoMes({ usina, celula }: { usina: UsinaDoAno; celula: CelulaDoAno }) {
  const m = celula.manutencao
  if (!m || m.situacao === null) {
    return (
      <View style={estilos.folhaMiolo}>
        <Text style={estilos.folhaTexto}>
          Este mês não faz parte do contrato desta usina — não havia nada combinado para ele.
        </Text>
      </View>
    )
  }
  const previsto = m.previsto ?? 0
  const cumprido = m.cumprido ?? 0
  const situacao =
    m.situacao === 'futuro'
      ? 'O mês ainda não venceu'
      : m.situacao === 'corrente'
        ? 'Mês em curso'
        : m.situacao === 'fechado'
          ? 'Mês vencido'
          : m.situacao
  return (
    <View style={estilos.folhaMiolo}>
      <View style={estilos.chipLinha}>
        <StatusChip
          tom={
            m.situacao === 'futuro'
              ? 'tempoRuim'
              : m.situacao === 'corrente'
                ? 'alerta'
                : cumprido >= previsto
                  ? 'ok'
                  : 'parado'
          }
          texto={situacao}
        />
      </View>
      <Text style={estilos.folhaTexto}>
        <Num style={estilos.folhaNum}>{cumprido}</Num> de{' '}
        <Num style={estilos.folhaNum}>{previsto}</Num> atividades combinadas para este mês.
      </Text>
      {m.situacao === 'futuro' ? (
        <Text style={estilos.folhaApoio}>
          Nada é cobrado de um mês que não venceu — por isso esta célula nunca aparece como
          atraso.
        </Text>
      ) : null}
      <Text style={estilos.folhaApoio}>
        “Cumprido” soma o que foi executado e o que foi dispensado com motivo registrado. A
        diferença entre os dois existe por atividade, na tela de Cronograma da usina — este
        número é o agregado do mês, como a manutenção o registrou.
      </Text>

      {/* O RELATÓRIO DO MÊS. O pedido do dono é "mês a mês, geração E manutenção": sem
          isto, a manutenção só tinha papel na coluna do ano e esta folha explicava o mês
          sem oferecer nada para ler. É a MESMA rota do fecho do ano, com a janela de um
          mês só — medido em Porto Ferreira/agosto: 200, 408.192 B, 2,13 s.

          Mês `futuro` não ganha botão porque o servidor recusa: pedir dezembro responde
          400 "ate não pode ser um mês futuro." (medido no mesmo turno). Oferecer o botão
          ali seria vender um erro. */}
      {m.situacao === 'futuro' ? null : (
        <AbrirPdf
          url={urlDoRelatorioDeManutencao(usina.id, celula.mes, celula.mes)}
          arquivo={`relatorio-manutencao-${usina.id}-${celula.mes}.pdf`}
          titulo={`Relatório de manutenção — ${usina.nome}`}
          rotulo="Abrir o relatório deste mês"
        />
      )}
    </View>
  )
}

/* ═════════════════════════════════════════════════════════════ a folha do fecho ══ */

/** A folha do fecho do ano. Só a manutenção chega aqui: em energia a célula não abre nada. */
function DetalheDoAno({ usina }: { usina: UsinaDoAno }) {
  return <AnualDeManutencao usina={usina} />
}

function AnualDeManutencao({ usina }: { usina: UsinaDoAno }) {
  const a = usina.anual.manutencao
  const janela = janelaPorExtenso(a.de, a.ate)

  if (!a.disponivel || !a.de || !a.ate) {
    return (
      <View style={estilos.folhaMiolo}>
        <Text style={estilos.folhaTexto}>
          {a.motivo ?? 'Não há relatório de manutenção para esta usina neste ano.'}
        </Text>
      </View>
    )
  }

  return (
    <View style={estilos.folhaMiolo}>
      {/* A JANELA IMPRESSA, antes de qualquer botão. Enquanto o ano corre, "o ano" é
          janeiro..mês corrente — pedir até dezembro responde 400 no servidor, e um
          percentual sem a janela ao lado é meia frase. */}
      <View style={estilos.janela}>
        <Text style={estilos.janelaRotulo}>Período coberto</Text>
        <Text style={estilos.janelaTexto}>{janela}</Text>
      </View>

      <Text style={estilos.folhaApoio}>{frasePublicoDaManutencao()}</Text>

      {/* `AbrirPdf` é a peça única do caminho do PDF: baixa, desenha DENTRO do aplicativo
          (pdf.js) e oferece o externo como segundo botão. Uma tela própria aqui seria a
          terceira cópia desse caminho — foi ter duas que produziu a folha branca. */}
      <AbrirPdf
        url={urlDoRelatorioDeManutencao(usina.id, a.de, a.ate)}
        arquivo={`relatorio-manutencao-${usina.id}-${a.de}-${a.ate}.pdf`}
        titulo={`Relatório de manutenção — ${usina.nome}`}
        rotulo="Abrir o relatório do período"
      />

      <PacoteDeFichas usina={usina} de={a.de} ate={a.ate} />
    </View>
  )
}

/**
 * As fichas do período, em pacote — **atrás de um segundo toque, e com o inventário antes**.
 *
 * Nunca um botão que baixa algo de tamanho desconhecido: medido em Porto Ferreira no ano,
 * são **27 fichas e 27.071.615 B**. O caminho tem três atos, como o do site — inventariar,
 * preparar o que falta e baixar — porque "baixei dezessete e vieram três" é o defeito que
 * ninguém confere.
 */
function PacoteDeFichas({ usina, de, ate }: { usina: UsinaDoAno; de: string; ate: string }) {
  const [inventario, setInventario] = useState<InventarioDeFichas | null>(null)
  const [preparo, setPreparo] = useState<PreparoDeFichas | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  // O `setState` depois que a folha fecha é onde nascem os avisos de "componente que já
  // saiu"; a bandeira corta a linha de chegada tardia.
  const vivo = useRef(true)
  useEffect(() => {
    vivo.current = true
    return () => {
      vivo.current = false
    }
  }, [])

  async function inventariar() {
    setOcupado(true)
    setErro(null)
    try {
      const i = await inventarioDeFichas(usina.id, de, ate)
      if (vivo.current) setInventario(i)
    } catch (e) {
      if (vivo.current) setErro(e instanceof Error ? e.message : 'Não deu para listar as fichas.')
    } finally {
      if (vivo.current) setOcupado(false)
    }
  }

  async function preparar() {
    setOcupado(true)
    setErro(null)
    try {
      let p = await prepararFichas(usina.id, de, ate)
      // Espera de verdade, sem prometer: enquanto o meuPlano trabalha, a tela mostra
      // quantas já saíram. Teto de tentativas para o giro não ficar eterno se o preparo
      // morrer noutra réplica.
      for (let i = 0; i < 60 && !p.concluido && vivo.current; i += 1) {
        await new Promise((r) => setTimeout(r, 3000))
        if (!vivo.current) return
        p = await andamentoDoPreparo(p.preparo_id)
        if (vivo.current) setPreparo(p)
      }
      if (!vivo.current) return
      setPreparo(p)
      if (p.estado === 'falhou') {
        setErro(p.erro ?? 'O preparo das fichas não terminou. Tente de novo.')
      } else if (!p.concluido) {
        // O relógio acabou e o preparo continua. Dizer isso é diferente de dizer que
        // falhou: o trabalho pode estar correndo do outro lado, e o botão segue sendo
        // "preparar" em vez de virar um download que sairia incompleto.
        setErro(
          `Ainda faltam ${p.total - p.prontas} fichas depois de três minutos. O preparo pode ` +
            'continuar do outro lado — volte daqui a pouco ou tente de novo.',
        )
      } else {
        setInventario(await inventarioDeFichas(usina.id, de, ate))
      }
    } catch (e) {
      if (vivo.current) setErro(e instanceof Error ? e.message : 'Não deu para preparar as fichas.')
    } finally {
      if (vivo.current) setOcupado(false)
    }
  }

  async function baixar(parte: number) {
    setOcupado(true)
    setErro(null)
    const motivo = await baixarPacote(
      urlDoPacoteDeFichas(usina.id, de, ate, parte),
      `fichas-${usina.nome}-${de}-${ate}${parte > 1 ? `-parte${parte}` : ''}.zip`,
      `Fichas — ${usina.nome}`,
    )
    if (!vivo.current) return
    setErro(motivo)
    setOcupado(false)
  }

  const oferta = inventario ? ofertaDoPacote(inventario) : null

  return (
    <View style={estilos.pacote}>
      <Text style={estilos.pacoteTitulo}>Fichas preenchidas do período</Text>

      {inventario === null ? (
        <>
          <Text style={estilos.folhaApoio}>
            Todas as fichas que os técnicos preencheram no período, num arquivo só. Antes de
            baixar, o aplicativo pergunta ao servidor quantas são e quanto pesam.
          </Text>
          {ocupado ? (
            <View style={estilos.baixando}>
              <ActivityIndicator color={cores.ambar} />
              <Text style={estilos.baixandoTexto}>Conferindo…</Text>
            </View>
          ) : (
            <Botao
              titulo="Ver o que há no período"
              variante="secundario"
              onPress={() => void inventariar()}
            />
          )}
        </>
      ) : (
        <>
          <Text style={estilos.folhaTexto}>
            <Num style={estilos.folhaNum}>{inventario.total}</Num>
            {inventario.total === 1 ? ' ficha' : ' fichas'} · {peso(inventario.bytes_estimados)}
            {inventario.partes.length > 1 ? ` · ${inventario.partes.length} arquivos` : ''}
          </Text>

          {preparo && !preparo.concluido ? (
            <Text style={estilos.folhaApoio}>
              Preparando: {preparo.prontas} de {preparo.total} prontas.
            </Text>
          ) : null}

          {oferta?.tipo === 'vazio' ? (
            <Text style={estilos.folhaApoio}>{oferta.motivo}</Text>
          ) : oferta?.tipo === 'grande' ? (
            <Text style={estilos.folhaApoio}>{oferta.motivo}</Text>
          ) : ocupado ? (
            <View style={estilos.baixando}>
              <ActivityIndicator color={cores.ambar} />
              <Text style={estilos.baixandoTexto}>
                {oferta?.tipo === 'preparar' ? 'Preparando as fichas…' : 'Baixando o pacote…'}
              </Text>
            </View>
          ) : oferta?.tipo === 'preparar' ? (
            <>
              <Text style={estilos.folhaApoio}>
                {oferta.faltam === 1
                  ? '1 ficha ainda não tem PDF gerado. O pacote só sai completo depois de prepará-la.'
                  : `${oferta.faltam} fichas ainda não têm PDF gerado. O pacote só sai completo depois de prepará-las.`}
              </Text>
              <Botao titulo="Preparar as que faltam" onPress={() => void preparar()} />
            </>
          ) : oferta?.tipo === 'baixar' ? (
            oferta.partes.map((p) => (
              <View key={p.numero} style={estilos.parte}>
                <Botao
                  titulo={
                    oferta.partes.length > 1
                      ? `Baixar parte ${p.numero} · ${p.fichas} fichas · ${peso(p.bytes)}`
                      : `Baixar as ${p.fichas} fichas · ${peso(p.bytes)}`
                  }
                  onPress={() => void baixar(p.numero)}
                />
              </View>
            ))
          ) : null}
        </>
      )}

      {erro ? <Text style={estilos.erro}>{erro}</Text> : null}
    </View>
  )
}

/**
 * Baixa o ZIP e entrega ao sistema.
 *
 * É o gêmeo de `lib/pdf.abrirPdf` para um pacote — mesmo transporte (sessão em CABEÇALHO,
 * nunca na URL, que entra em log), outro tipo de arquivo: `abrirPdf` carimba `application/
 * pdf` e nomeia como PDF, e entregar um ZIP por ele faria o Android abrir o compartilhamento
 * com o aplicativo errado. **Dívida declarada:** o certo é `lib/pdf.ts` virar um
 * `lib/arquivo.ts` com o tipo por parâmetro — arquivo que não é meu nesta leva.
 */
async function baixarPacote(url: string, arquivo: string, titulo: string): Promise<string | null> {
  let bytes: Uint8Array
  try {
    const r = await fetch(url, { headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` } })
    if (!r.ok) {
      let detalhe: string | null = null
      try {
        const corpo = (await r.json()) as { detail?: unknown }
        detalhe = typeof corpo.detail === 'string' ? corpo.detail : null
      } catch {
        detalhe = null
      }
      return detalhe ?? `Não deu para baixar o pacote (erro ${r.status}).`
    }
    bytes = new Uint8Array(await r.arrayBuffer())
  } catch {
    return 'Não foi possível baixar. Verifique a conexão e tente de novo.'
  }

  try {
    const destino = new FileSystem.File(FileSystem.Paths.cache, arquivo.replace(/[^\w.-]+/g, '_'))
    // Apaga antes: o pacote é montado sob demanda e muda quando uma ficha é regerada — um
    // arquivo com o mesmo nome entregaria o ZIP de ontem sem avisar.
    if (destino.exists) destino.delete()
    destino.create()
    destino.write(bytes)
    if (!(await Sharing.isAvailableAsync())) return 'Este aparelho não tem com o que abrir o pacote.'
    await Sharing.shareAsync(destino.uri, { mimeType: 'application/zip', dialogTitle: titulo })
    return null
  } catch {
    return 'O pacote baixou, mas não deu para abri-lo neste aparelho.'
  }
}

/* ═══════════════════════════════════════════════════════════════════════ estilos ══ */

const estilos = StyleSheet.create({
  espaco: { marginTop: espaco.sm },
  filtros: { flexDirection: 'row', gap: espaco.sm },
  aviso: {
    fontFamily: fontes.ui,
    fontSize: 12.5,
    color: tons.alerta,
    lineHeight: 18,
  },
  legendaTopo: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco },
  semLinhas: {
    fontFamily: fontes.ui,
    fontSize: 13,
    color: cores.textoFraco,
    lineHeight: 19,
    paddingVertical: espaco.md,
  },

  grade: { flexDirection: 'row', marginTop: espaco.sm },
  cantoNome: {
    height: 26,
    justifyContent: 'flex-end',
    paddingBottom: 4,
    borderBottomWidth: 1,
    borderBottomColor: cores.bordaFraca,
  },
  cabecalhoTexto: {
    fontFamily: fontes.ui,
    fontSize: 10,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: cores.textoRotulo,
  },
  cabecalhoMeses: {
    flexDirection: 'row',
    height: 26,
    alignItems: 'flex-end',
    paddingBottom: 4,
    borderBottomWidth: 1,
    borderBottomColor: cores.bordaFraca,
  },
  cabecalhoMes: { width: LARGURA_MES, alignItems: 'center' },
  cabecalhoAno: { width: LARGURA_ANO, alignItems: 'center' },
  mesTexto: { fontFamily: fontes.ui, fontSize: 10.5, color: cores.textoFraco },

  celulaNome: {
    height: TOQUE_MIN + 6,
    justifyContent: 'center',
    paddingRight: espaco.sm,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  nomeUsina: { fontFamily: fontes.uiMedio, fontSize: 12.5, color: cores.textoCorpo },
  avisoLinha: { fontFamily: fontes.ui, fontSize: 9.5, color: cores.textoFraco, marginTop: 1 },

  linha: {
    flexDirection: 'row',
    height: TOQUE_MIN + 6,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  celula: { alignItems: 'center', justifyContent: 'center', gap: 1 },
  celulaTocada: { backgroundColor: cores.superficie },
  pastilha: {
    minWidth: 26,
    height: 22,
    paddingHorizontal: 5,
    borderRadius: 6,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pastilhaTexto: { fontFamily: fontes.monoSemi, fontSize: 11.5 },
  notaCelula: { fontFamily: fontes.ui, fontSize: 8.5, color: cores.textoFraco },
  travessao: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoFraco, opacity: 0.5 },

  legenda: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: espaco.sm,
    marginTop: espaco.md,
    paddingTop: espaco.sm,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  legendaItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendaPastilha: {
    minWidth: 20,
    height: 17,
    paddingHorizontal: 4,
    borderRadius: 5,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  legendaLetra: { fontFamily: fontes.monoSemi, fontSize: 9.5 },
  legendaTexto: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco },

  versao: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco },
  explicacao: {
    fontFamily: fontes.ui,
    fontSize: 13,
    color: cores.textoFraco,
    lineHeight: 19,
    marginTop: espaco.xs,
  },
  recorte: { flexDirection: 'row', alignItems: 'center', gap: espaco.sm, marginTop: espaco.xs },
  pct: { fontFamily: fontes.monoSemi, fontSize: 30, color: cores.textoForte },
  recorteMiolo: { flex: 1 },
  recorteFrase: { fontFamily: fontes.uiMedio, fontSize: 13.5, color: cores.textoCorpo },
  recorteRotulo: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoFraco, marginTop: 1 },
  recorteOutro: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoFraco,
    lineHeight: 18,
    marginTop: espaco.sm,
  },
  recorteOutroNum: { fontSize: 12, color: cores.textoCorpo },

  folhaMiolo: { gap: espaco.sm, paddingTop: espaco.xs, paddingBottom: espaco.md },
  folhaTexto: { fontFamily: fontes.ui, fontSize: 14, color: cores.textoCorpo, lineHeight: 20 },
  folhaNum: { fontSize: 14, color: cores.textoForte },
  folhaApoio: { fontFamily: fontes.ui, fontSize: 12.5, color: cores.textoFraco, lineHeight: 19 },
  chipLinha: { flexDirection: 'row' },

  janela: {
    padding: espaco.sm,
    borderRadius: raio.campo,
    borderWidth: 1,
    borderColor: cores.borda,
    backgroundColor: cores.afundado,
  },
  janelaRotulo: {
    fontFamily: fontes.ui,
    fontSize: 10,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: cores.textoRotulo,
  },
  janelaTexto: {
    fontFamily: fontes.uiMedio,
    fontSize: 14,
    color: cores.textoForte,
    marginTop: 2,
  },

  pacote: {
    gap: espaco.sm,
    marginTop: espaco.sm,
    paddingTop: espaco.md,
    borderTopWidth: 1,
    borderTopColor: cores.bordaFraca,
  },
  pacoteTitulo: { fontFamily: fontes.uiSemi, fontSize: 14.5, color: cores.textoForte },
  parte: { marginTop: espaco.xs },
  motivoAnual: { gap: 2, marginTop: espaco.xs },

  baixando: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: espaco.xs,
    paddingVertical: 12,
  },
  baixandoTexto: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoRotulo },
  erro: { fontFamily: fontes.ui, fontSize: 12, color: tons.parado, lineHeight: 17 },
})
