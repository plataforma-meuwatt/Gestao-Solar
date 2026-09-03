/**
 * UMA TAREFA da ordem de serviço — o que foi feito naquele item, e a ficha em PDF.
 *
 * O dono, olhando a OS 1016 (03/09/2026): *"tem as tarefas, porém elas não são clicáveis,
 * são como checklist. Eu preciso ABRIR as tarefas e ver as respostas delas, preciso gerar os
 * PDFs delas"*. Ele estava certo: a lista da OS desenhava `<View>`, não havia rota de tarefa
 * e o único PDF era o da ordem inteira — dezenas de páginas para conferir um ensaio.
 *
 * O que esta tela responde, na ordem em que a pergunta aparece:
 *   1. o que era a tarefa e em QUAL equipamento (cinco trafos de mesmo nome se distinguem
 *      pela rota na árvore, não pelo nome);
 *   2. como terminou — executada? qual o parecer do ensaio?;
 *   3. quando, e de que mês do contrato ela é;
 *   4. a FICHA em PDF, com as respostas que o técnico registrou.
 *
 * O detalhe das respostas (cada medição, cada pergunta) mora no PDF de propósito: é o mesmo
 * documento que o meuPlano gera e que vale como laudo. Reescrever aqui uma segunda versão
 * dessa leitura criaria duas verdades sobre o mesmo ensaio.
 */

import { useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'

import { AbrirPdf } from '@/components/AbrirPdf'
import { CabecalhoCard, Card, Esqueleto, EstadoVazio, Num, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import { urlDoPdfDaTarefa, useTarefa } from '@/features/manutencao'
import { dataPorExtenso } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons, type Tom } from '@/theme/tokens'

/** A mesma régua da lista da OS: reprovado é parado, ressalva é alerta, o resto é ok. */
function tomDoParecer(p: string | null): Tom {
  if (!p) return 'semDados'
  if (/reprov/i.test(p)) return 'parado'
  if (/ressalva/i.test(p)) return 'alerta'
  return 'ok'
}

/** "2026-08" → "agosto de 2026". O mês contratual é o combinado, não a data de execução. */
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

function mesPorExtenso(yyyyMm: string | null): string | null {
  if (!yyyyMm || yyyyMm.length < 7) return null
  const m = Number(yyyyMm.slice(5, 7))
  return MESES[m - 1] ? `${MESES[m - 1]} de ${yyyyMm.slice(0, 4)}` : yyyyMm
}

export default function TarefaDaOrdem() {
  const { id, os } = useLocalSearchParams<{ id: string; os: string }>()
  const { dados: t, carregando, erro, offlineDesde, recarregar } = useTarefa(os, id)

  return (
    <Tela
      titulo="Tarefa"
      subtitulo={t ? <Text style={tipo.secundario}>{t.grupo ?? 'Ordem de serviço'}</Text> : undefined}
      voltar
      offlineDesde={offlineDesde}
    >
      {carregando && !t ? (
        <Card>
          <Esqueleto largura="70%" altura={16} forte />
          <View style={estilos.espaco}>
            <Esqueleto altura={120} />
          </View>
        </Card>
      ) : erro || !t ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro ?? 'Tarefa indisponível.'}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : (
        <>
          <Card>
            <Text style={estilos.nome}>{t.nome}</Text>

            {t.equipamento ? (
              <Text style={estilos.equipamento}>{t.equipamento}</Text>
            ) : null}

            <View style={estilos.situacao}>
              {/* O ✓ da lista vira frase aqui: "Executada" é o que o dono quer ler. */}
              <StatusChip tom={t.feita ? 'ok' : 'semDados'} texto={t.situacao} grande />
              {t.parecer ? (
                <Text style={[estilos.parecer, { color: tons[tomDoParecer(t.parecer)] }]}>
                  {t.parecer}
                </Text>
              ) : null}
            </View>

            <View style={estilos.linhas}>
              {t.natureza ? (
                <Linha rotulo="Natureza" valor={t.natureza === 'INSPECAO' ? 'Inspeção' : 'Serviço'} />
              ) : null}
              <Linha
                rotulo="Executada"
                valor={t.executada_em ? dataPorExtenso(t.executada_em) : '—'}
              />
              {mesPorExtenso(t.mes_contratual) ? (
                <Linha rotulo="Mês do contrato" valor={mesPorExtenso(t.mes_contratual) as string} />
              ) : null}
            </View>
          </Card>

          {/* O que a tarefa pedia e o que o técnico anotou. Sem os dois, o card não
              existe — em vez de um bloco vazio dizendo "—" duas vezes. */}
          {t.descricao || t.observacoes ? (
            <Card>
              <CabecalhoCard rotulo="Registro do técnico" />
              {t.descricao ? (
                <>
                  <Text style={tipo.legenda}>O que era para fazer</Text>
                  <Text style={estilos.texto}>{t.descricao}</Text>
                </>
              ) : null}
              {t.observacoes ? (
                <View style={t.descricao ? estilos.espaco : undefined}>
                  <Text style={tipo.legenda}>Observações</Text>
                  <Text style={estilos.texto}>{t.observacoes}</Text>
                </View>
              ) : null}
            </Card>
          ) : null}

          <Card>
            <CabecalhoCard
              rotulo="Ficha em PDF"
              direita={
                /* ZERO é resposta ("nada respondido ainda"); nulo é "não informado" e
                   some — a REGRA 0 não deixa `?? 0` ir para a tela. */
                typeof t.preenchimento === 'number' ? (
                  <Text style={tipo.legenda}>{t.preenchimento}% respondida</Text>
                ) : undefined
              }
            />
            <Text style={estilos.explicacao}>
              O que o técnico registrou nesta tarefa: medições, respostas e fotos. É o mesmo
              documento que vale como laudo.
            </Text>
            <View style={estilos.espaco}>
              <AbrirPdf
                url={urlDoPdfDaTarefa(Number(os), Number(id))}
                arquivo={`tarefa-${id}.pdf`}
                titulo={t.nome}
                rotulo="Abrir a ficha em PDF"
              />
            </View>
          </Card>
        </>
      )}
    </Tela>
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

  nome: {
    fontFamily: fontes.uiForte,
    fontSize: 17,
    lineHeight: 23,
    color: cores.textoForte,
  },
  equipamento: {
    fontFamily: fontes.ui,
    fontSize: 13,
    lineHeight: 18,
    color: cores.textoFraco,
    marginTop: 4,
  },

  situacao: { flexDirection: 'row', alignItems: 'center', gap: espaco.xs, marginTop: espaco.sm },
  parecer: { fontFamily: fontes.uiForte, fontSize: 12.5 },

  linhas: { marginTop: espaco.sm, gap: 6 },
  linha: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', gap: espaco.xs },
  linhaValor: { fontFamily: fontes.ui, fontSize: 13.5, color: cores.textoCorpo },

  explicacao: { fontFamily: fontes.ui, fontSize: 13, lineHeight: 19, color: cores.textoFraco },
  texto: { fontFamily: fontes.ui, fontSize: 13.5, lineHeight: 20, color: cores.textoCorpo, marginTop: 2 },
})
