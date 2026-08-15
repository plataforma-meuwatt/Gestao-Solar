/**
 * Escolha do período — dia, mês e ano.
 *
 * Três recortes, um controle só. O passo (‹ ›) resolve o caso comum, que é olhar o dia
 * anterior ou o mês passado; o calendário resolve o caso de ir longe, que no passo levaria
 * dezenas de toques.
 *
 * **Futuro é bloqueado na origem.** O monitoramento não tem leitura do que ainda não
 * aconteceu, e deixar avançar devolveria uma tela de "sem dados" que se lê como falha do
 * app. O BFF também recusa (`referencia não pode ser futura`) — as duas guardas existem de
 * propósito: a daqui evita a viagem, a de lá vale para qualquer cliente da API.
 *
 * As datas viajam como `YYYY-MM-DD` e são construídas com `new Date(ano, mes, dia)`, que é
 * meia-noite LOCAL. `new Date('2026-08-15')` seria meia-noite UTC e, no fuso do Brasil,
 * voltaria 15 de agosto como dia 14 — o clássico erro de um dia a menos.
 */

import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { Card } from '@/components/base'
import { cores, espaco, fontes, raio } from '@/theme/tokens'

export type Recorte = 'dia' | 'mes' | 'ano'

const MESES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]
const MESES_CURTOS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
const DIAS_SEMANA = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S']

/** `YYYY-MM-DD` → Date na meia-noite local. */
export function daData(iso: string): Date {
  const [a, m, d] = iso.split('-').map(Number)
  return new Date(a, m - 1, d)
}

/** Date → `YYYY-MM-DD`, sem passar por UTC. */
export function paraIso(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function hojeIso(): string {
  return paraIso(new Date())
}

/** Rótulo do período escolhido, no formato que cada recorte pede. */
export function rotuloDoPeriodo(iso: string, recorte: Recorte): string {
  const d = daData(iso)
  if (recorte === 'ano') return String(d.getFullYear())
  if (recorte === 'mes') return `${MESES[d.getMonth()]} de ${d.getFullYear()}`
  const hoje = hojeIso()
  if (iso === hoje) return 'Hoje'
  return `${String(d.getDate()).padStart(2, '0')} de ${MESES_CURTOS[d.getMonth()]} de ${d.getFullYear()}`
}

/** Anda um passo no recorte. Passo de mês/ano preserva o dia 1 para não estourar mês curto. */
function passo(iso: string, recorte: Recorte, direcao: 1 | -1): string {
  const d = daData(iso)
  if (recorte === 'dia') return paraIso(new Date(d.getFullYear(), d.getMonth(), d.getDate() + direcao))
  if (recorte === 'mes') return paraIso(new Date(d.getFullYear(), d.getMonth() + direcao, 1))
  return paraIso(new Date(d.getFullYear() + direcao, 0, 1))
}

/** O período escolhido contém uma data futura? */
function passaDeHoje(iso: string, recorte: Recorte): boolean {
  const d = daData(iso)
  const hoje = new Date()
  if (recorte === 'ano') return d.getFullYear() > hoje.getFullYear()
  if (recorte === 'mes') {
    return d.getFullYear() > hoje.getFullYear()
      || (d.getFullYear() === hoje.getFullYear() && d.getMonth() > hoje.getMonth())
  }
  return paraIso(d) > paraIso(hoje)
}

export function SeletorPeriodo({
  valor,
  recorte,
  onEscolher,
}: {
  /** Data de referência em `YYYY-MM-DD`. No recorte mês/ano, qualquer dia dentro dele serve. */
  valor: string
  recorte: Recorte
  onEscolher: (iso: string) => void
}) {
  const [aberto, setAberto] = useState(false)

  const anterior = passo(valor, recorte, -1)
  const proximo = passo(valor, recorte, 1)
  const podeAvancar = !passaDeHoje(proximo, recorte)

  return (
    <View>
      <View style={estilos.barra}>
        <Passo texto="‹" onPress={() => onEscolher(anterior)} />
        <Pressable style={estilos.centro} onPress={() => setAberto((a) => !a)} hitSlop={6}>
          <Text style={estilos.rotulo}>{rotuloDoPeriodo(valor, recorte)}</Text>
          <Text style={estilos.dica}>{aberto ? 'fechar' : 'escolher'}</Text>
        </Pressable>
        <Passo texto="›" onPress={() => onEscolher(proximo)} desabilitado={!podeAvancar} />
      </View>

      {aberto ? (
        <Card elevado>
          {recorte === 'dia' ? (
            <Calendario valor={valor} onEscolher={(iso) => { onEscolher(iso); setAberto(false) }} />
          ) : recorte === 'mes' ? (
            <GradeMeses valor={valor} onEscolher={(iso) => { onEscolher(iso); setAberto(false) }} />
          ) : (
            <GradeAnos valor={valor} onEscolher={(iso) => { onEscolher(iso); setAberto(false) }} />
          )}
        </Card>
      ) : null}
    </View>
  )
}

function Passo({
  texto,
  onPress,
  desabilitado,
}: {
  texto: string
  onPress: () => void
  desabilitado?: boolean
}) {
  return (
    <Pressable
      onPress={desabilitado ? undefined : onPress}
      hitSlop={10}
      style={[estilos.passo, desabilitado && estilos.passoInerte]}
    >
      <Text style={[estilos.passoTexto, desabilitado && estilos.passoTextoInerte]}>{texto}</Text>
    </Pressable>
  )
}

/** Grade do mês. Só o mês visível navega — o dia escolhido não muda ao virar a página. */
function Calendario({ valor, onEscolher }: { valor: string; onEscolher: (iso: string) => void }) {
  const escolhido = daData(valor)
  const [pagina, setPagina] = useState(new Date(escolhido.getFullYear(), escolhido.getMonth(), 1))
  const hoje = hojeIso()

  const primeiro = new Date(pagina.getFullYear(), pagina.getMonth(), 1)
  const diasNoMes = new Date(pagina.getFullYear(), pagina.getMonth() + 1, 0).getDate()
  // Casas vazias antes do dia 1, para o dia cair na coluna do seu dia da semana.
  const vazios = primeiro.getDay()

  const mesAtualOuFuturo =
    pagina.getFullYear() > new Date().getFullYear()
    || (pagina.getFullYear() === new Date().getFullYear() && pagina.getMonth() >= new Date().getMonth())

  return (
    <View>
      <View style={estilos.barra}>
        <Passo
          texto="‹"
          onPress={() => setPagina(new Date(pagina.getFullYear(), pagina.getMonth() - 1, 1))}
        />
        <Text style={estilos.rotulo}>
          {MESES[pagina.getMonth()]} {pagina.getFullYear()}
        </Text>
        <Passo
          texto="›"
          onPress={() => setPagina(new Date(pagina.getFullYear(), pagina.getMonth() + 1, 1))}
          desabilitado={mesAtualOuFuturo}
        />
      </View>

      <View style={estilos.semana}>
        {DIAS_SEMANA.map((d, i) => (
          <Text key={`${d}-${i}`} style={estilos.semanaTexto}>
            {d}
          </Text>
        ))}
      </View>

      <View style={estilos.grade}>
        {Array.from({ length: vazios }).map((_, i) => (
          <View key={`vazio-${i}`} style={estilos.celula} />
        ))}
        {Array.from({ length: diasNoMes }).map((_, i) => {
          const iso = paraIso(new Date(pagina.getFullYear(), pagina.getMonth(), i + 1))
          const futuro = iso > hoje
          const marcado = iso === valor
          return (
            <Pressable
              key={iso}
              style={[estilos.celula, marcado && estilos.celulaMarcada]}
              onPress={futuro ? undefined : () => onEscolher(iso)}
            >
              <Text
                style={[
                  estilos.celulaTexto,
                  futuro && estilos.celulaTextoInerte,
                  marcado && estilos.celulaTextoMarcado,
                  iso === hoje && !marcado && estilos.celulaTextoHoje,
                ]}
              >
                {i + 1}
              </Text>
            </Pressable>
          )
        })}
      </View>
    </View>
  )
}

function GradeMeses({ valor, onEscolher }: { valor: string; onEscolher: (iso: string) => void }) {
  const escolhido = daData(valor)
  const [ano, setAno] = useState(escolhido.getFullYear())
  const agora = new Date()

  return (
    <View>
      <View style={estilos.barra}>
        <Passo texto="‹" onPress={() => setAno(ano - 1)} />
        <Text style={estilos.rotulo}>{ano}</Text>
        <Passo texto="›" onPress={() => setAno(ano + 1)} desabilitado={ano >= agora.getFullYear()} />
      </View>
      <View style={estilos.grade}>
        {MESES_CURTOS.map((m, i) => {
          const futuro = ano > agora.getFullYear() || (ano === agora.getFullYear() && i > agora.getMonth())
          const marcado = ano === escolhido.getFullYear() && i === escolhido.getMonth()
          return (
            <Pressable
              key={m}
              style={[estilos.celulaLarga, marcado && estilos.celulaMarcada]}
              onPress={futuro ? undefined : () => onEscolher(paraIso(new Date(ano, i, 1)))}
            >
              <Text
                style={[
                  estilos.celulaTexto,
                  futuro && estilos.celulaTextoInerte,
                  marcado && estilos.celulaTextoMarcado,
                ]}
              >
                {m}
              </Text>
            </Pressable>
          )
        })}
      </View>
    </View>
  )
}

/**
 * Doze anos para trás. Não há como o app saber quando a usina entrou em operação — isso é
 * dado do meuWatt e não vem nesta tela —, então a janela é generosa e um ano sem leitura
 * responde honestamente "sem dados" em vez de sumir da lista.
 */
function GradeAnos({ valor, onEscolher }: { valor: string; onEscolher: (iso: string) => void }) {
  const escolhido = daData(valor).getFullYear()
  const atual = new Date().getFullYear()
  const anos = Array.from({ length: 12 }, (_, i) => atual - i)

  return (
    <View style={estilos.grade}>
      {anos.map((a) => (
        <Pressable
          key={a}
          style={[estilos.celulaLarga, a === escolhido && estilos.celulaMarcada]}
          onPress={() => onEscolher(paraIso(new Date(a, 0, 1)))}
        >
          <Text style={[estilos.celulaTexto, a === escolhido && estilos.celulaTextoMarcado]}>
            {a}
          </Text>
        </Pressable>
      ))}
    </View>
  )
}

const estilos = StyleSheet.create({
  barra: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  centro: { alignItems: 'center', flex: 1 },
  rotulo: { fontFamily: fontes.ui, fontSize: 14, color: cores.textoForte },
  dica: { fontFamily: fontes.ui, fontSize: 10, color: cores.textoFraco, marginTop: 1 },

  passo: {
    width: 34,
    height: 34,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: raio.chip,
    backgroundColor: cores.superficieElevada,
  },
  passoInerte: { backgroundColor: 'transparent' },
  passoTexto: { fontFamily: fontes.ui, fontSize: 18, color: cores.textoForte, lineHeight: 22 },
  passoTextoInerte: { color: cores.bordaFraca },

  semana: { flexDirection: 'row', marginTop: espaco.sm },
  semanaTexto: {
    width: `${100 / 7}%`,
    textAlign: 'center',
    fontFamily: fontes.ui,
    fontSize: 10,
    color: cores.textoFraco,
  },

  grade: { flexDirection: 'row', flexWrap: 'wrap', marginTop: espaco.xs },
  celula: { width: `${100 / 7}%`, height: 38, alignItems: 'center', justifyContent: 'center' },
  celulaLarga: { width: `${100 / 4}%`, height: 42, alignItems: 'center', justifyContent: 'center' },
  celulaMarcada: { backgroundColor: cores.ambar, borderRadius: raio.chip },
  celulaTexto: { fontFamily: fontes.ui, fontSize: 13, color: cores.textoCorpo },
  celulaTextoInerte: { color: cores.bordaFraca },
  celulaTextoMarcado: { color: cores.fundo },
  celulaTextoHoje: { color: cores.ambar },
})
