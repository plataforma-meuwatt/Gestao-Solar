/**
 * Uma ordem de serviço, aberta pelo dono da usina.
 *
 * A lista responde "está sendo feita?". Esta tela responde "o que exatamente foi
 * feito?" — e é a pergunta que o dono faz quando a fatura da manutenção chega.
 *
 * As tarefas vêm agrupadas por seção (Transformador, Inversor, Módulos…), que é como a
 * própria OS do meuPlano as organiza. Duas telas que agrupam o mesmo dado de formas
 * diferentes viram duas versões da verdade na cabeça de quem lê as duas.
 *
 * O ✓ é `feita`, decidido no servidor a partir de `REALIZADA`/`APROVADA`. O parecer
 * ("Aprovado com ressalva") só aparece quando existe ficha respondida: tarefa de
 * serviço não tem parecer, e desenhar um vazio sugeriria que faltou preencher.
 */

import { router, useLocalSearchParams } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { AbrirPdf } from '@/components/AbrirPdf'
import { CabecalhoCard, Card, Esqueleto, EstadoVazio, Num, StatusChip } from '@/components/base'
import { Tela } from '@/components/Tela'
import { urlDoPdfDaOrdem, useOrdem, type Tarefa } from '@/features/manutencao'
import { dataPorExtenso, duracao } from '@/lib/format'
import { cores, espaco, fontes, tipo, tons, type Tom } from '@/theme/tokens'

/** Corretiva é conserto (algo quebrou); preventiva é rotina cumprida. */
function tomDaClasse(c: string | null): Tom {
  const v = (c ?? '').toUpperCase()
  if (v.includes('CORRETIVA')) return 'alerta'
  if (v.includes('PREVENTIVA')) return 'ok'
  return 'semDados'
}

function rotuloDaClasse(c: string | null): string {
  if (!c) return 'sem classificação'
  const limpo = c.replace(/_/g, ' ').toLowerCase()
  return limpo.charAt(0).toUpperCase() + limpo.slice(1)
}

/** Ressalva não é reprovação, e nem uma nem outra é "aprovado". Três cores. */
function tomDoParecer(p: string | null): Tom {
  if (!p) return 'semDados'
  if (/reprov/i.test(p)) return 'parado'
  if (/ressalva/i.test(p)) return 'alerta'
  return 'ok'
}

export default function OrdemDeServico() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { dados: o, carregando, erro, offlineDesde, recarregar } = useOrdem(id)

  // Seções na ordem em que vieram — o servidor já ordenou por grupo e nome.
  const secoes = new Map<string, Tarefa[]>()
  for (const t of o?.itens ?? []) {
    const chave = t.grupo ?? 'Outras'
    const atual = secoes.get(chave)
    if (atual) atual.push(t)
    else secoes.set(chave, [t])
  }

  return (
    <Tela
      titulo={o ? `OS ${o.id}` : 'Ordem de serviço'}
      subtitulo={o ? <Text style={tipo.secundario}>{o.usina}</Text> : undefined}
      voltar
      offlineDesde={offlineDesde}
    >
      {carregando && !o ? (
        <>
          <Card>
            <Esqueleto largura="70%" altura={16} forte />
            <View style={estilos.espaco}>
              <Esqueleto altura={60} />
            </View>
          </Card>
          <Card>
            <Esqueleto altura={120} />
          </Card>
        </>
      ) : erro || !o ? (
        <EstadoVazio
          tom="parado"
          titulo="Não deu para carregar"
          descricao={erro ?? 'Ordem de serviço indisponível.'}
          acao={{ titulo: 'Tentar de novo', onPress: recarregar }}
        />
      ) : (
        <>
          <Card>
            <View style={estilos.topo}>
              <Text style={estilos.objetivo}>{o.objetivo}</Text>
              <StatusChip
                tom={tomDaClasse(o.classificacao)}
                texto={rotuloDaClasse(o.classificacao)}
              />
            </View>

            {/* A situação é a frase do servidor, não o status cru: "Executada ·
                aguardando verificação" diz o que `EM_EXECUCAO` esconderia. */}
            <View style={estilos.situacao}>
              <StatusChip tom={o.tom} texto={o.situacao} grande />
            </View>

            <View style={estilos.linhas}>
              <Linha rotulo="Técnico" valor={o.tecnico ?? '—'} />
              {o.numero !== null ? <Linha rotulo="Contrato" valor={`nº ${o.numero}`} /> : null}
              <Linha
                rotulo="Agendada"
                valor={o.agendada_para ? dataPorExtenso(o.agendada_para) : '—'}
              />
              {o.concluida_em ? (
                <Linha rotulo="Concluída" valor={dataPorExtenso(o.concluida_em)} />
              ) : null}
              {o.aprovada_em ? (
                <Linha rotulo="Verificada" valor={dataPorExtenso(o.aprovada_em)} />
              ) : null}
              <Linha rotulo="Execução" valor={duracao(o.execucao_min)} />
            </View>

            {o.resumo ? <Text style={estilos.resumo}>{o.resumo}</Text> : null}
          </Card>

          <Card>
            <CabecalhoCard
              rotulo="O que foi feito"
              direita={
                o.tarefas ? (
                  <Text style={estilos.contagem}>
                    <Num style={estilos.contagemNum}>{o.tarefas_feitas ?? 0}</Num>
                    {` de ${o.tarefas}`}
                  </Text>
                ) : undefined
              }
            />

            {/* `null` é "não deu para buscar as tarefas"; `[]` seria "a OS não tem
                nenhuma". Duas frases, porque são duas situações. */}
            {o.itens === null ? (
              <Text style={tipo.fraco}>
                Não deu para carregar as tarefas desta ordem. O resto da ficha está acima.
              </Text>
            ) : o.itens.length === 0 ? (
              <Text style={tipo.fraco}>Esta ordem não tem tarefas registradas.</Text>
            ) : (
              [...secoes.entries()].map(([secao, itens]) => (
                <View key={secao} style={estilos.secao}>
                  <Text style={estilos.secaoTitulo}>{secao}</Text>
                  {itens.map((t, i) => (
                    <ItemTarefa key={t.id ?? `${secao}-${i}`} tarefa={t} osId={o.id} />
                  ))}
                </View>
              ))
            )}
          </Card>

          <Card>
            <CabecalhoCard rotulo="Ficha em PDF" />
            <Text style={estilos.explicacao}>
              A ordem completa, com as tarefas e as fichas preenchidas pelo técnico. O
              arquivo é baixado e aberto no leitor do seu aparelho.
            </Text>
            <View style={estilos.espaco}>
              <AbrirPdf
                url={urlDoPdfDaOrdem(o.id)}
                arquivo={`os-${o.id}.pdf`}
                titulo={`OS ${o.id} — ${o.usina}`}
                rotulo="Abrir a OS em PDF"
              />
            </View>
          </Card>
        </>
      )}
    </Tela>
  )
}

/**
 * A linha da tarefa ABRE a tarefa. Antes era uma `<View>` — o dono tentou tocar e nada
 * acontecia: *"as tarefas não são clicáveis, são como checklist"* (03/09/2026). Tarefa sem
 * `id` (caso raro do upstream) segue como texto: um botão que não leva a lugar nenhum é pior
 * do que nenhum botão.
 */
function ItemTarefa({ tarefa: t, osId }: { tarefa: Tarefa; osId: number }) {
  const conteudo = (
    <>
      {/* O ✓ vem do servidor (`feita`), não de comparar textos de status aqui. */}
      <View style={[estilos.marca, t.feita ? estilos.marcaFeita : estilos.marcaAberta]}>
        {t.feita ? <Text style={estilos.marcaTexto}>✓</Text> : null}
      </View>

      <View style={estilos.tarefaMiolo}>
        <Text style={[estilos.tarefaNome, !t.feita && estilos.tarefaNomeAberta]}>{t.nome}</Text>

        {t.equipamento ? (
          <Text style={estilos.equipamento} numberOfLines={2}>
            {t.equipamento}
          </Text>
        ) : null}

        <View style={estilos.selos}>
          {/* Situação só quando NÃO está feita: no item com ✓ a palavra "Executada"
              repete o que o próprio ✓ acabou de dizer. */}
          {!t.feita ? <Text style={estilos.situacaoTarefa}>{t.situacao}</Text> : null}
          {t.parecer ? (
            <Text style={[estilos.parecer, { color: tons[tomDoParecer(t.parecer)] }]}>
              {t.parecer}
            </Text>
          ) : null}
        </View>
      </View>

      {/* a seta diz, sem palavra nenhuma, que a linha leva a algum lugar */}
      {t.id ? <Text style={estilos.seta}>›</Text> : null}
    </>
  )

  if (!t.id) return <View style={estilos.tarefa}>{conteudo}</View>

  return (
    <Pressable
      style={({ pressed }) => [estilos.tarefa, pressed && estilos.tarefaTocada]}
      onPress={() => router.push(`/tarefa/${t.id}?os=${osId}`)}
      accessibilityRole="button"
      accessibilityLabel={`Abrir a tarefa ${t.nome}`}
    >
      {conteudo}
    </Pressable>
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

  topo: { flexDirection: 'row', alignItems: 'flex-start', gap: espaco.xs },
  objetivo: {
    fontFamily: fontes.uiSemi,
    fontSize: 16,
    color: cores.textoForte,
    flex: 1,
    lineHeight: 22,
  },
  situacao: { marginTop: espaco.sm, alignSelf: 'flex-start' },

  linhas: { marginTop: espaco.sm, gap: espaco.xs },
  linha: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  linhaValor: { fontSize: 12, color: cores.textoForte, flexShrink: 1 },

  resumo: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoCorpo,
    lineHeight: 17,
    marginTop: espaco.sm,
  },

  contagem: { fontFamily: fontes.ui, fontSize: 12, color: cores.textoRotulo },
  contagemNum: { fontSize: 14, color: cores.textoForte },

  secao: { marginTop: espaco.sm },
  secaoTitulo: {
    fontFamily: fontes.ui,
    fontSize: 11,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: cores.textoRotulo,
    marginBottom: 6,
  },

  tarefa: { flexDirection: 'row', gap: espaco.xs, paddingVertical: 7, alignItems: 'center' },
  tarefaTocada: { opacity: 0.6 },
  seta: { fontFamily: fontes.ui, fontSize: 20, color: cores.textoFraco, paddingLeft: 2 },
  marca: {
    width: 18,
    height: 18,
    borderRadius: 5,
    marginTop: 1,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
  marcaFeita: { backgroundColor: tons.ok, borderColor: tons.ok },
  marcaAberta: { backgroundColor: 'transparent', borderColor: cores.bordaForte },
  marcaTexto: { fontFamily: fontes.uiSemi, fontSize: 11, color: cores.fundo, lineHeight: 14 },

  tarefaMiolo: { flex: 1, minWidth: 0 },
  tarefaNome: { fontFamily: fontes.ui, fontSize: 13.5, color: cores.textoCorpo, lineHeight: 19 },
  tarefaNomeAberta: { color: cores.textoFraco },
  equipamento: {
    fontFamily: fontes.ui,
    fontSize: 11,
    color: cores.textoFraco,
    marginTop: 1,
    lineHeight: 15,
  },
  selos: { flexDirection: 'row', flexWrap: 'wrap', gap: espaco.xs, marginTop: 3 },
  situacaoTarefa: { fontFamily: fontes.ui, fontSize: 11, color: cores.textoRotulo },
  parecer: { fontFamily: fontes.uiSemi, fontSize: 11 },

  explicacao: {
    fontFamily: fontes.ui,
    fontSize: 12,
    color: cores.textoCorpo,
    lineHeight: 17,
    marginTop: 4,
  },
})
