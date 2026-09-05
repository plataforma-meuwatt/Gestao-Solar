/**
 * Ordens de serviço — "tem alguém trabalhando nesta usina agora, e o que já foi concluído?"
 *
 * É a tela que responde à pergunta do dono depois que a fatura da manutenção chega. Ela NÃO
 * é o laudo: medição, checklist e foto vivem no PDF da tarefa (a tela da OS os oferece), e
 * trazê-los para cá transformaria o acompanhamento em análise de equipamento — que é
 * trabalho da equipe, não do cliente corporativo.
 *
 * Três decisões:
 *
 * **"Acontecendo agora" só aparece quando existe.** Um cartão zerado ("0 de 0 tarefas") se lê
 * como abandono; a ausência do cartão se lê como "nada em curso", que é a verdade.
 *
 * **Situação e cor vêm do servidor.** A tela nunca reescreve "FECHADA" — o BFF já entrega a
 * frase ("Em verificação", "Executada · aguardando verificação") e o tom. O código cru
 * continua no dado, para auditoria, e não na tela.
 *
 * **Nenhuma OS some calada.** Os blocos são "Em andamento" e "Concluídas"; uma OS cancelada
 * não é nenhum dos dois e não vira aba — ela é CONTADA no rodapé ("6 no total · 2
 * canceladas"). Dar aba a ela foi o que pôs duas ordens de teste da equipe na frente do
 * cliente, e a pergunta desta tela é "está sendo feito?", que cancelada não responde. Um
 * estado NOVO do meuPlano, esse sim, abre a terceira aba: desconhecido tem de aparecer. E o
 * bloco vazio nunca deixa a tela em branco — diz o que houve e leva ao bloco com conteúdo.
 */

import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  AtualizadoAs,
  Aviso,
  Barra,
  CabecalhoCard,
  Cartao,
  Botao,
  Num,
  Pagina,
  Segmentado,
  Selo,
  Tabela,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { dataCurta, duracao, inteiro } from '@/lib/format'
import {
  blocoDaOrdem,
  dataDaOrdem,
  pctDeTarefas,
  rotuloDaClasse,
  tomDaClasse,
  useOrdens,
  type Bloco,
  type Ordem,
  type OrdensOut,
} from '@/features/ordens/api'

/** "12 de 17" — e "—" quando o servidor não informou a contagem (≠ "nenhuma tarefa"). */
function tarefasTexto(o: Ordem): string {
  if (o.tarefas === null && o.tarefas_feitas === null) return '—'
  return `${inteiro(o.tarefas_feitas)} de ${inteiro(o.tarefas)}`
}

/** O título da coluna de data muda com o bloco: agendada é promessa, concluída é fato. */
function tituloDaData(bloco: Bloco): string {
  if (bloco === 'andamento') return 'Agendada para'
  if (bloco === 'concluidas') return 'Concluída em'
  return 'Data'
}

export default function Ordens() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const usinaId = id ? Number(id) : null
  const leitura = useOrdens(usinaId)

  // Nulo = ninguém escolheu ainda, e a tela abre no bloco que tem conteúdo. Guardar a escolha
  // do cliente separada do padrão é o que permite ele ficar num bloco vazio de propósito
  // ("não há nada em andamento") em vez de ser jogado de volta a cada atualização.
  const [escolhido, setEscolhido] = useState<Bloco | null>(null)

  const abrir = (o: Ordem) => navigate(`/usinas/${o.usina_id}/ordens/${o.id}`)

  return (
    <Pagina
      titulo="Ordens de serviço"
      subtitulo="Tem alguém trabalhando nesta usina agora e o que já foi concluído?"
      acoes={<AtualizadoAs em={leitura.atualizadoEm} offlineDesde={leitura.offlineDesde} />}
    >
      {usinaId === null ? (
        <Vazio
          titulo="Escolha uma usina"
          descricao="As ordens de serviço são de uma usina por vez — escolha uma no alto da tela."
        />
      ) : (
        <Tela4Estados<OrdensOut> leitura={leitura}>
          {(dados) => {
            // `total` nulo é o contrato do BFF para "nenhuma usina respondeu". Zero seria a
            // afirmação oposta — "não há OS" — e é a leitura mais cara desta tela.
            if (dados.total === null) {
              return (
                <Vazio
                  titulo="Não deu para consultar as ordens de serviço"
                  descricao={
                    dados.aviso ??
                    'O sistema de manutenção não respondeu agora. Tente de novo em instantes.'
                  }
                  acao={
                    <Botao variante="secundario" onClick={leitura.recarregar}>
                      Tentar de novo
                    </Botao>
                  }
                />
              )
            }

            if (dados.ordens.length === 0) {
              return (
                <Vazio
                  titulo="Nenhuma ordem de serviço nesta usina"
                  descricao={
                    dados.aviso ??
                    'Quando a equipe abrir uma ordem de serviço para esta usina, ela aparece aqui.'
                  }
                />
              )
            }

            const porBloco: Record<Bloco, Ordem[]> = {
              andamento: [],
              concluidas: [],
              outras: [],
              cancelada: [],
            }
            for (const o of dados.ordens) porBloco[blocoDaOrdem(o)].push(o)

            const canceladas = porBloco.cancelada.length
            // As listadas são as que respondem à pergunta da tela; as canceladas ficam no
            // rodapé, contadas, para o total continuar batendo sem virar aba.
            const listadas = dados.ordens.length - canceladas

            const opcoes: { valor: Bloco; rotulo: string }[] = [
              { valor: 'andamento', rotulo: `Em andamento (${inteiro(porBloco.andamento.length)})` },
              { valor: 'concluidas', rotulo: `Concluídas (${inteiro(porBloco.concluidas.length)})` },
              // Só um estado que este portal não conhece abre a terceira aba.
              ...(porBloco.outras.length > 0
                ? [{ valor: 'outras' as Bloco, rotulo: `Outras (${inteiro(porBloco.outras.length)})` }]
                : []),
            ]

            if (listadas === 0) {
              return (
                <Vazio
                  titulo="Nenhuma ordem de serviço em aberto nesta usina"
                  descricao={
                    canceladas > 0
                      ? `As ${inteiro(canceladas)} ordens desta usina foram canceladas pela equipe.`
                      : 'Quando a equipe abrir uma ordem de serviço para esta usina, ela aparece aqui.'
                  }
                />
              )
            }

            const padrao: Bloco = porBloco.andamento.length > 0 ? 'andamento' : 'concluidas'
            const bloco = escolhido ?? padrao
            const linhas = porBloco[bloco]
            // Para onde mandar quem caiu num bloco vazio: o primeiro que tem conteúdo.
            const alternativa = opcoes.find((op) => op.valor !== bloco && porBloco[op.valor].length > 0)

            const emCurso = dados.em_andamento

            return (
              <>
                {dados.aviso ? <Aviso>{dados.aviso}</Aviso> : null}

                {emCurso ? (
                  <Cartao semPadding>
                    <button
                      type="button"
                      onClick={() => abrir(emCurso)}
                      className="w-full rounded-card p-5 text-left transition hover:bg-superficie-alta"
                    >
                      <CabecalhoCard
                        rotulo="Acontecendo agora"
                        direita={
                          <Selo tom={tomDaClasse(emCurso.classificacao)}>
                            {rotuloDaClasse(emCurso.classificacao)}
                          </Selo>
                        }
                      />
                      <p className="text-lg font-semibold text-forte">{emCurso.objetivo}</p>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Selo tom={emCurso.tom}>{emCurso.situacao}</Selo>
                        {emCurso.tecnico ? (
                          <span className="text-sm text-fraco">{emCurso.tecnico}</span>
                        ) : null}
                        {/* aqui a data é sempre a de AGENDAMENTO, escrita por extenso: a OS
                            está em curso, e mostrar uma data de conclusão junto de "acontecendo
                            agora" seria contraditório. */}
                        {emCurso.agendada_para ? (
                          <span className="text-sm text-fraco">
                            agendada para <Num>{dataCurta(emCurso.agendada_para)}</Num>
                          </span>
                        ) : null}
                      </div>

                      <div className="mt-4">
                        <div className="mb-1.5 flex items-center justify-between text-xs text-fraco">
                          <span>Tarefas</span>
                          <Num>{tarefasTexto(emCurso)}</Num>
                        </div>
                        {pctDeTarefas(emCurso) === null ? null : (
                          <Barra pct={pctDeTarefas(emCurso)} />
                        )}
                      </div>
                    </button>
                  </Cartao>
                ) : null}

                <Cartao semPadding>
                  <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
                    <Segmentado opcoes={opcoes} valor={bloco} onEscolher={setEscolhido} />
                    <span className="text-xs text-fraco">
                      <Num>{inteiro(listadas)}</Num> no total
                      {canceladas > 0 ? (
                        <>
                          {' · '}
                          <Num>{inteiro(canceladas)}</Num>
                          {canceladas === 1 ? ' cancelada' : ' canceladas'}
                        </>
                      ) : null}
                    </span>
                  </div>

                  <div className="px-2 pb-2 pt-3">
                    <Tabela<Ordem>
                      colunas={[
                        {
                          titulo: 'Ordem',
                          celula: (o) => (
                            <span className="block min-w-0">
                              <span className="block truncate font-medium text-forte">
                                {o.objetivo}
                              </span>
                              {/* o número da OS é IDENTIDADE, não quantidade: vai sem separador
                                  de milhar (a OS 1016 não é "1.016") e é por ele que o cliente
                                  fala da ordem com a equipe. */}
                              <span className="block text-xs text-fraco">
                                OS <Num>{o.id}</Num>
                              </span>
                            </span>
                          ),
                        },
                        {
                          titulo: tituloDaData(bloco),
                          celula: (o) => <Num>{dataCurta(dataDaOrdem(o))}</Num>,
                        },
                        { titulo: 'Situação', celula: (o) => <Selo tom={o.tom}>{o.situacao}</Selo> },
                        {
                          titulo: 'Classificação',
                          celula: (o) => (
                            <Selo tom={tomDaClasse(o.classificacao)}>
                              {rotuloDaClasse(o.classificacao)}
                            </Selo>
                          ),
                        },
                        {
                          titulo: 'Técnico',
                          celula: (o) => <span className="text-fraco">{o.tecnico ?? '—'}</span>,
                        },
                        {
                          titulo: 'Execução',
                          alinhar: 'dir',
                          celula: (o) => <Num>{duracao(o.execucao_min)}</Num>,
                        },
                        {
                          titulo: 'Tarefas',
                          alinhar: 'dir',
                          celula: (o) => <Num>{tarefasTexto(o)}</Num>,
                        },
                      ]}
                      linhas={linhas}
                      chave={(o) => o.id}
                      aoClicar={abrir}
                      vazio={
                        <div className="px-3 py-6">
                          <Vazio
                            titulo={
                              bloco === 'andamento'
                                ? 'Nenhuma ordem em andamento agora'
                                : bloco === 'concluidas'
                                  ? 'Nenhuma ordem concluída ainda'
                                  : 'Nenhuma ordem neste grupo'
                            }
                            descricao={
                              alternativa
                                ? 'Esta usina tem ordens de serviço em outro grupo.'
                                : undefined
                            }
                            acao={
                              alternativa ? (
                                <Botao
                                  variante="secundario"
                                  onClick={() => setEscolhido(alternativa.valor)}
                                >
                                  Ver {alternativa.rotulo}
                                </Botao>
                              ) : undefined
                            }
                          />
                        </div>
                      }
                    />
                  </div>
                </Cartao>
              </>
            )
          }}
        </Tela4Estados>
      )}
    </Pagina>
  )
}
