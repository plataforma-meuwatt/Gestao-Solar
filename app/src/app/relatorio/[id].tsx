/**
 * Um relatório aberto — o PDF desenhado dentro do aplicativo.
 *
 * Esta tela já foi três coisas erradas, e a terceira é a que interessa.
 *
 * 1. Uma **maquete**: duas folhas A4 com blocos de texto falsos e um "3 de 13" igual para
 *    todo cliente.
 * 2. Uma `WebView` apontada para o PDF — o que parecia certo e era pior, porque falhava em
 *    silêncio: o WebView do Android não desenha PDF, o `onLoadEnd` disparava mesmo assim, e
 *    o dono ficava olhando uma folha branca.
 * 3. Um **degrau**: um texto explicando que o documento "será baixado" e um botão para
 *    baixá-lo. Esse degrau nunca existiu por necessidade técnica — existiu porque o desenho
 *    era impossível. Com o `LeitorPdf` (pdf.js embutido) a razão acabou, e o degrau com ela:
 *    o card da lista leva direto ao documento desenhado, em **um toque**.
 *
 * ## O que esta tela faz, e o que ela não faz
 *
 * Ela é a **moldura**: o cabeçalho que diz o que está aberto, e o botão de voltar. Baixar,
 * desenhar, contar páginas, mostrar o erro do servidor palavra por palavra e oferecer o
 * "Abrir em outro app" é tudo do `LeitorPdf` — que é a mesma peça usada pelo botão
 * `AbrirPdf` da OS e da tarefa. Uma fonte só para o caminho do PDF; foi ter duas que
 * produziu o defeito que este arquivo conserta.
 *
 * ## Por que o cabeçalho recebe parâmetros
 *
 * A tela antiga conhecia `id` e `tipo` e nada mais: dizia "Relatório de Geração" sem dizer
 * de qual usina nem de qual mês, e para a peça `resumo` — que ela nem conhecia — dizia
 * "Documento". Não existe `GET /documents/{id}` no BFF para consultar, e inventar uma
 * segunda leitura só para o cabeçalho seria uma ida à rede para escrever um título. A
 * lista já tem tudo isso na mão, então ela passa adiante — é o caminho rápido, sem esperar
 * nada.
 *
 * Quando os parâmetros não vêm — um link guardado antes desta entrega, ou uma notificação
 * que só saiba o número —, a tela **não** inventa nem fica muda: procura o fechamento no
 * mesmo acervo que a lista já leu (`useRelatorios`, chave de cache `'documents'`, a mesma
 * leitura em disco). Isso é de propósito a MESMA fonte da lista: um segundo caminho de
 * leitura daria duas respostas para "de que mês é este relatório". Se nem o acervo houver —
 * primeira abertura, sem rede —, o cabeçalho encolhe com honestidade para o nome da peça:
 * diz menos, nunca diz errado, e **nunca** diz "Documento".
 */

import { router, useLocalSearchParams } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { LeitorPdf } from '@/components/LeitorPdf'
import {
  gavetaDoRelatorio,
  rotuloDaGaveta,
  rotuloDaPeca,
  urlDoArquivo,
  useRelatorios,
  type Relatorio as RelatorioDoAcervo,
} from '@/features/relatorios'
import { cores, espaco, fontes, TOQUE_MIN } from '@/theme/tokens'

/**
 * O que o cabeçalho escreve — função pura, para o teste conferir sem aparelho.
 *
 * O rótulo da peça sai de `PECAS` (via `rotuloDaPeca`), que é a fonte única: era este mapa
 * duplicado em dois arquivos, com duas entradas cada num acervo de três peças, que fazia o
 * Resumo Executivo aparecer aqui como "Documento" e na lista como nome de arquivo cru.
 *
 * O período passa por `rotuloDaGaveta`, que sabe a diferença entre `2026-08` e `ano:2026` —
 * e é a MESMA régua que rotula a gaveta na lista, para o mês não ter dois nomes no app.
 * Minúscula porque é aposto do título, como já se faz no subtítulo da aba.
 */
export function cabecalhoDoRelatorio(p: {
  tipo: string
  /** Nome do arquivo no monitoramento, quando a peça é de um vocabulário que não conhecemos. */
  nome?: string | null
  usina?: string | null
  /** `YYYY-MM` ou `ano:2026`, como a lista agrupa. */
  competencia?: string | null
}): { titulo: string; subtitulo: string | null; completo: string } {
  const titulo = rotuloDaPeca({
    tipo: p.tipo,
    // 'Relatório' é o mesmo fallback que o BFF usa para um fechamento sem nome. Nunca
    // 'Documento': era ele que aparecia no lugar de "Resumo Executivo".
    nome: p.nome?.trim() || 'Relatório',
    bytes: null,
  })

  const partes = [
    p.usina?.trim() || null,
    p.competencia?.trim() ? rotuloDaGaveta(p.competencia.trim()).toLowerCase() : null,
  ].filter((x): x is string => Boolean(x))

  const subtitulo = partes.length > 0 ? partes.join(' · ') : null
  return { titulo, subtitulo, completo: [titulo, ...partes].join(' · ') }
}

/** A gaveta do fechamento, quando ela existe de verdade. */
function gavetaOuNada(r: RelatorioDoAcervo | null): string | null {
  if (!r) return null
  const chave = gavetaDoRelatorio(r)
  return chave === 'sem-data' ? null : chave
}

export default function Relatorio() {
  const { id, tipo, nome, usina, competencia } = useLocalSearchParams<{
    id: string
    tipo?: string
    nome?: string
    usina?: string
    competencia?: string
  }>()
  const insets = useSafeAreaInsets()
  // O acervo que a lista já leu. Só é consultado para preencher o que não veio na rota;
  // o TanStack devolve a mesma leitura, sem uma segunda ida à rede.
  const { dados } = useRelatorios()
  const doAcervo = dados?.documentos.find((r) => String(r.id) === String(id)) ?? null

  const peca = tipo ?? 'geracao'
  const { titulo, subtitulo, completo } = cabecalhoDoRelatorio({
    tipo: peca,
    nome: nome ?? doAcervo?.arquivos.find((a) => a.tipo === peca)?.nome,
    usina: usina ?? doAcervo?.usina,
    // `gavetaDoRelatorio` e não `mesDoRelatorio`: o ANUAL não tem mês (cobre doze) e
    // perderia o período no cabeçalho. 'sem-data' vira nada — "Sem período" num título
    // ocupa uma linha para não dizer nada.
    competencia: competencia ?? gavetaOuNada(doAcervo),
  })

  return (
    <View style={[estilos.raiz, { paddingTop: insets.top }]}>
      <View style={estilos.barra}>
        <Pressable
          onPress={() => router.back()}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Voltar"
          style={estilos.voltar}
        >
          <View style={estilos.seta} />
        </Pressable>
        <View style={estilos.barraMiolo}>
          <Text style={estilos.titulo} numberOfLines={1} accessibilityLabel={completo}>
            {titulo}
          </Text>
          {subtitulo ? (
            <Text style={estilos.subtitulo} numberOfLines={1}>
              {subtitulo}
            </Text>
          ) : null}
        </View>
      </View>

      <LeitorPdf
        url={urlDoArquivo(Number(id), peca)}
        arquivo={`relatorio-${id}-${peca}.pdf`}
        titulo={completo}
      />
    </View>
  )
}

const estilos = StyleSheet.create({
  raiz: { flex: 1, backgroundColor: cores.fundo },
  barra: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: espaco.md,
    paddingVertical: 6,
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: cores.bordaFraca,
  },
  voltar: { width: 26, height: TOQUE_MIN, justifyContent: 'center' },
  seta: {
    width: 11,
    height: 11,
    borderLeftWidth: 2,
    borderBottomWidth: 2,
    borderColor: cores.textoForte,
    transform: [{ rotate: '45deg' }],
    marginLeft: 4,
  },
  barraMiolo: { flex: 1 },
  titulo: { fontFamily: fontes.uiSemi, fontSize: 14.5, color: cores.textoForte },
  subtitulo: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoRotulo, marginTop: 2 },
})
