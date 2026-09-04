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
import {
  urlDoPdfDaTarefa,
  useFicha,
  useTarefa,
  type EquipamentoDaFicha,
  type Medicao,
  type SecaoChecklist,
} from '@/features/manutencao'
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
  // A ficha é mais cara que o cabeçalho: a tela abre com o que já tem e as respostas
  // chegam em seguida, em vez de tudo esperar tudo.
  const { dados: ficha, carregando: carregandoFicha, erro: erroFicha } = useFicha(os, id)

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

          {/* AS RESPOSTAS. Antes só existiam dentro do PDF — o dono pediu para lê-las aqui
              ("quero ver detalhe na tela"). Numa tarefa coletiva há um bloco por
              equipamento; numa individual, um só. */}
          {carregandoFicha && !ficha ? (
            <Card>
              <Esqueleto largura="40%" altura={13} />
              <View style={estilos.espaco}>
                <Esqueleto altura={90} />
              </View>
            </Card>
          ) : erroFicha && !ficha ? (
            <Card>
              <CabecalhoCard rotulo="Respostas" />
              <Text style={tipo.fraco}>
                Não deu para carregar as respostas agora. A ficha em PDF, abaixo, continua
                disponível.
              </Text>
            </Card>
          ) : ficha && ficha.equipamentos.length > 0 ? (
            ficha.equipamentos.map((e, i) => (
              <BlocoEquipamento key={`${e.equipamento}-${i}`} equipamento={e} />
            ))
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

/** Um equipamento da ficha: o que foi medido e o que foi respondido nele. */
function BlocoEquipamento({ equipamento: e }: { equipamento: EquipamentoDaFicha }) {
  const nada = e.medicoes.length === 0 && e.checklist.length === 0
  return (
    <Card>
      <CabecalhoCard
        rotulo={e.equipamento}
        direita={
          e.parecer ? (
            <Text style={[estilos.parecer, { color: tons[tomDoParecer(e.parecer)] }]}>
              {e.parecer}
            </Text>
          ) : undefined
        }
      />

      {e.parecer_motivo ? <Text style={estilos.motivo}>{e.parecer_motivo}</Text> : null}

      {/* Quem fez e quando: numa coletiva cada equipamento pode ter sido feito em hora
          diferente, e é isso que explica um resultado fora da curva. */}
      {e.executado_por || e.executado_em ? (
        <Text style={estilos.autoria}>
          {[e.executado_por, e.executado_em].filter(Boolean).join(' · ')}
        </Text>
      ) : null}

      {e.medicoes.map((m, i) => (
        <BlocoMedicao key={`${m.nome}-${i}`} medicao={m} />
      ))}

      {e.checklist.map((sec, i) => (
        <BlocoChecklist key={`${sec.nome}-${i}`} secao={sec} />
      ))}

      {nada ? (
        <Text style={tipo.fraco}>Nada foi registrado nesta ficha ainda.</Text>
      ) : null}

      {e.fotos > 0 ? (
        <Text style={estilos.fotos}>
          {e.fotos === 1 ? '1 foto' : `${e.fotos} fotos`} — no PDF abaixo
        </Text>
      ) : null}
    </Card>
  )
}

/** Uma medição: cada ponto com o que foi lido. */
function BlocoMedicao({ medicao: m }: { medicao: Medicao }) {
  return (
    <View style={estilos.grupo}>
      <Text style={estilos.grupoTitulo}>
        {m.nome}
        {m.unidade ? <Text style={estilos.unidade}>{`  (${m.unidade})`}</Text> : null}
      </Text>
      {m.linhas.map((l, i) => (
        <View key={`${l.ponto}-${i}`} style={estilos.itemLinha}>
          <Text style={estilos.itemRotulo} numberOfLines={2}>{l.ponto}</Text>
          <View style={estilos.itemDireita}>
            {/* Valor ausente vira "—". Zero é medição e aparece como zero. */}
            <Num style={estilos.itemValor}>
              {l.valor ?? '—'}
              {l.valor && l.unidade ? ` ${l.unidade}` : ''}
            </Num>
            {l.aprovado === false ? <Text style={estilos.reprovado}>reprovado</Text> : null}
          </View>
        </View>
      ))}
    </View>
  )
}

/** Uma seção do checklist: a pergunta e o que foi respondido. */
function BlocoChecklist({ secao }: { secao: SecaoChecklist }) {
  return (
    <View style={estilos.grupo}>
      <Text style={estilos.grupoTitulo}>{secao.nome}</Text>
      {secao.perguntas.map((p, i) => (
        <View key={`${p.pergunta}-${i}`} style={estilos.pergunta}>
          <Text style={estilos.perguntaTexto}>{p.pergunta}</Text>
          <Text style={[estilos.resposta, p.problema && estilos.respostaProblema]}>
            {p.resposta ?? '—'}
          </Text>
          {p.observacao ? <Text style={estilos.obs}>{p.observacao}</Text> : null}
        </View>
      ))}
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

  motivo: { fontFamily: fontes.ui, fontSize: 13, lineHeight: 19, color: cores.textoCorpo, marginTop: 4 },
  autoria: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco, marginTop: 2 },
  fotos: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco, marginTop: espaco.xs },

  grupo: { marginTop: espaco.sm },
  grupoTitulo: { fontFamily: fontes.uiForte, fontSize: 12, color: cores.textoRotulo, letterSpacing: 0.3 },
  unidade: { fontFamily: fontes.ui, fontSize: 11.5, color: cores.textoFraco },

  itemLinha: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start',
    gap: espaco.xs, paddingVertical: 5,
  },
  itemRotulo: { flex: 1, fontFamily: fontes.ui, fontSize: 13, color: cores.textoCorpo, lineHeight: 18 },
  itemDireita: { alignItems: 'flex-end' },
  itemValor: { fontFamily: fontes.ui, fontSize: 13.5, color: cores.textoForte },
  reprovado: { fontFamily: fontes.uiForte, fontSize: 10.5, color: tons.parado, marginTop: 1 },

  pergunta: { paddingVertical: 6 },
  perguntaTexto: { fontFamily: fontes.ui, fontSize: 13, lineHeight: 18, color: cores.textoCorpo },
  resposta: { fontFamily: fontes.uiForte, fontSize: 13, color: cores.textoForte, marginTop: 2 },
  respostaProblema: { color: tons.parado },
  obs: { fontFamily: fontes.ui, fontSize: 12, lineHeight: 17, color: cores.textoFraco, marginTop: 2 },
  texto: { fontFamily: fontes.ui, fontSize: 13.5, lineHeight: 20, color: cores.textoCorpo, marginTop: 2 },
})
