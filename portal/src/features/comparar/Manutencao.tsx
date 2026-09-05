/**
 * Comparar manutenção — **qual usina está mais atrasada?**
 *
 * A irmã do comparativo de geração, na outra família. Mesma forma (rota de carteira, período
 * na URL, ordenação do servidor, rodapé fixo de janela) e a mesma recusa em fabricar número.
 * O que muda é a régua, e ela tem três decisões que a tela precisa mostrar por escrito:
 *
 * **O ranking é por ATRASADAS, em número absoluto — nunca por percentual puro.** Uma usina
 * com 2 de 4 atrasadas (50 %) não está pior do que uma com 30 de 300 (10 %): o percentual
 * sozinho premia o contrato pequeno. O cumprimento existe, e é a segunda régua da lista.
 *
 * **Todo percentual vem com o denominador impresso ao lado** ("13 de 31"), montado no
 * servidor. Foi a falta disso que produziu "13 de 270" (4,8 %) numa tela e "41,9 %" na
 * outra, para uma usina sem uma única atividade atrasada — dois números respondendo à mesma
 * pergunta, no mesmo portal. A frase e o número saem juntos daqui em diante.
 *
 * **Dispensado nunca funde com feito.** São afirmações diferentes: "foi executado" e "foi
 * dispensado com motivo registrado". A barra mostra as três fatias separadas, e o que ainda
 * está NO PRAZO fica fora da conta — no denominador ele acusaria o prestador de não ter
 * feito o que ainda não venceu. Quando algo é excluído, a linha diz quanto e por quê
 * (`fora_da_conta`).
 *
 * **Usina sem contrato ou sem cronograma publicado aparece com travessão e o motivo escrito,
 * e fica FORA dos totais** — cujo cabeçalho diz de quantas usinas ele fala. Zero atrasadas
 * numa usina sem cronograma se leria como "está tudo em dia", que é a leitura mais cara que
 * esta tela pode induzir.
 *
 * O que a tela NÃO promete: "em curso" (ordens em andamento, pendências abertas) é foto de
 * hoje, não do período — está escrito no rodapé, porque um número de hoje ao lado de números
 * de agosto se lê como se todos fossem de agosto.
 */

import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  Aviso,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  Combobox,
  Kpi,
  Num,
  Pagina,
  Tabela,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { SeletorPeriodo } from '@/components/SeletorPeriodo'
import { inteiro, porcento } from '@/lib/format'
import { hojeIso, type Recorte } from '@/lib/periodo'
import { useEstadoNaUrl, useTextoNaUrl } from '@/lib/urlestado'
import {
  RECORTES_ACEITOS,
  dataIso,
  frasesDaJanela,
  intervaloDe,
  legendaDoPosto,
  mesesDaJanela,
  naOrdemDoRanking,
  posicoesDo,
  rankingEscolhido,
  useComparativo,
  type ComparativoOut,
  type JanelaOut,
  type RankingOut,
  type UsinaManutencaoOut,
} from '@/features/comparar/api'

/**
 * A chave da régua escolhida, guardada na URL.
 *
 * A validação NÃO é uma lista de chaves escrita aqui: quem diz que réguas existem é o
 * servidor, e uma cópia dessa lista no portal ficaria defasada em silêncio — a régua nova
 * apareceria na lista suspensa e, ao ser escolhida, cairia de volta na padrão sem explicação.
 * Aqui só se recusa o que nem parece uma chave (endereço truncado pelo cliente de e-mail); a
 * conferência de verdade é `rankingEscolhido`, contra o que veio na resposta.
 */
const CHAVE_DE_REGUA = (v: string) => /^[a-z][a-z0-9_]{0,40}$/.test(v)

function Posto({ posicao, empatado }: { posicao: number; empatado: boolean }) {
  return (
    <span
      className="whitespace-nowrap text-sm text-fraco"
      title="Posição no ranking do servidor"
    >
      <Num className="text-forte">{inteiro(posicao)}º</Num>
      {empatado ? <span className="ml-1 text-xs text-rotulo">=</span> : null}
    </span>
  )
}

function SemNumero({ motivo }: { motivo: string | null }) {
  return (
    <span className="text-fraco" title={motivo ?? undefined}>
      —
    </span>
  )
}

/**
 * A barra de três fatias: feito · dispensado · atrasado.
 *
 * As três são desenhadas SEPARADAS de propósito. Somar dispensado com feito daria uma barra
 * mais bonita e uma afirmação falsa — o meuPlano recusou fundir os dois no cronograma pelo
 * mesmo motivo, e o portal não pode desfazer essa decisão no desenho.
 *
 * Nada é calculado a partir de percentual: as fatias saem das CONTAGENS sobre o denominador
 * que o servidor mandou, então a barra e o "13 de 31" ao lado nunca podem discordar.
 *
 * **Uma guarda só, e ela é daqui.** Quem decide se há barra quando NÃO há denominador é a
 * célula — ela precisa decidir de qualquer modo, para mostrar o travessão com o motivo. Se
 * este componente repetisse a checagem, as duas se cobririam e nenhum teste conseguiria
 * provar qualquer uma das duas: era exatamente o que acontecia, e por isso o `total` chega
 * aqui como `number`, não como `number | null`. O que sobra é a guarda que só existe aqui: se
 * uma das três contagens faltar, não há barra — desenhar a fatia ausente com largura zero
 * representaria "não sabemos" como "não houve", e o desenho afirmaria mais do que o número
 * ao lado dele.
 */
function BarraDoCumprimento({
  total,
  feitas,
  dispensadas,
  atrasadas,
}: {
  total: number
  feitas: number | null
  dispensadas: number | null
  atrasadas: number | null
}) {
  if (feitas === null || dispensadas === null || atrasadas === null) return null
  const fatia = (n: number) => (n / total) * 100
  const fatias = [
    { chave: 'feito', largura: fatia(feitas), cor: 'bg-tom-ok', rotulo: 'executadas' },
    {
      chave: 'dispensado',
      largura: fatia(dispensadas),
      cor: 'bg-tom-tempoRuim',
      rotulo: 'dispensadas',
    },
    {
      chave: 'atrasado',
      largura: fatia(atrasadas),
      cor: 'bg-tom-parado',
      rotulo: 'atrasadas',
    },
  ]
  return (
    <div
      className="flex h-1.5 w-32 overflow-hidden rounded-barra bg-afundado"
      title={fatias.map((f) => `${f.rotulo}`).join(' · ')}
    >
      {fatias.map((f) => (
        <div key={f.chave} className={f.cor} style={{ width: `${f.largura}%` }} />
      ))}
    </div>
  )
}

export default function CompararManutencao() {
  const navigate = useNavigate()

  const [recorte, setRecorte] = useEstadoNaUrl<Recorte>({
    chave: 'recorte',
    padrao: 'mes',
    aceitos: RECORTES_ACEITOS,
  })
  const [referencia, setReferencia] = useTextoNaUrl({
    chave: 'em',
    padrao: hojeIso(),
    valido: dataIso,
  })
  const [ordem, setOrdem] = useTextoNaUrl({
    chave: 'ordenar',
    padrao: 'atraso',
    valido: CHAVE_DE_REGUA,
  })

  const { de, ate } = useMemo(() => intervaloDe(referencia, recorte), [referencia, recorte])
  const leitura = useComparativo('manutencao', de, ate)

  return (
    <Pagina
      titulo="Comparar manutenção"
      subtitulo="Qual usina está mais atrasada — e quanto do combinado já foi feito?"
      acoes={
        <SeletorPeriodo
          recorte={recorte}
          referencia={referencia}
          onRecorte={setRecorte}
          onReferencia={(iso) => setReferencia(iso, 'replace')}
          recortes={[...RECORTES_ACEITOS]}
        />
      }
    >
      <Tela4Estados
        leitura={leitura}
        esqueleto={
          <div className="space-y-4">
            <CarregandoCartao linhas={2} />
            <CarregandoCartao linhas={6} />
          </div>
        }
      >
        {(d: ComparativoOut) => {
          const bloco = d.manutencao
          if (!bloco || bloco.usinas.length === 0) {
            return (
              <Vazio
                titulo="Nada para comparar neste período"
                descricao={
                  d.aviso ??
                  'Não há usina liberada para a sua conta. Fale com o seu gestor de conta.'
                }
              />
            )
          }
          if (d.usinas_no_escopo < 2) {
            return (
              <Vazio
                titulo="Comparar exige mais de uma usina"
                descricao="A sua conta tem uma usina só. O cronograma dela responde a mesma pergunta com muito mais detalhe."
              />
            )
          }

          const ranking = rankingEscolhido(bloco.rankings, ordem)
          const postos = posicoesDo(ranking)
          const { ranqueadas, semNumero } = naOrdemDoRanking(bloco.usinas, ranking)
          const linhas = [...ranqueadas, ...semNumero]
          const totais = bloco.totais

          return (
            <>
              {d.aviso ? <Aviso>{d.aviso}</Aviso> : null}

              {/* 1 — a carteira somada. O cabeçalho diz de quantas usinas o total fala. */}
              <Cartao>
                <CabecalhoCard
                  rotulo={`A carteira · ${d.janela.rotulo ?? ''}`}
                  direita={
                    <>
                      <Num>{inteiro(totais.usinas_no_total)}</Num> de{' '}
                      <Num>{inteiro(d.usinas_no_escopo)}</Num> usinas com cronograma publicado
                    </>
                  }
                />
                <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
                  <Kpi
                    rotulo="Atividades atrasadas"
                    valor={inteiro(totais.atrasadas)}
                    tamanho="grande"
                    tom={totais.atrasadas ? 'parado' : undefined}
                    detalhe="o prazo do cronograma já passou"
                  />
                  <Kpi
                    rotulo="Cumprimento"
                    valor={porcento(totais.cumprimento_pct, 1)}
                    // O denominador ao lado do percentual, sempre. Sozinho, 41,9 % não quer
                    // dizer nada — e foi por isso que duas telas já discordaram.
                    detalhe={totais.cumprimento_rotulo ?? 'sem cronograma publicado'}
                  />
                  <Kpi
                    rotulo="Ordens em andamento"
                    valor={inteiro(totais.os_em_andamento)}
                    detalhe="agora, não no período"
                  />
                  <Kpi
                    rotulo="Pendências abertas"
                    valor={inteiro(totais.pendencias_abertas)}
                    detalhe={
                      <>
                        <Num>{inteiro(totais.pendencias_vencidas)}</Num> com prazo vencido
                      </>
                    }
                  />
                </div>
              </Cartao>

              {/* 2 — a pergunta escolhida, escrita; e a lista na ordem que o servidor deu */}
              <Cartao semPadding>
                <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold text-forte">
                      {ranking ? ranking.titulo : 'Usinas'}
                    </h2>
                    {ranking ? (
                      <p className="mt-0.5 text-sm text-corpo">{ranking.pergunta}</p>
                    ) : null}
                    {ranking?.nota ? (
                      <p className="mt-1 max-w-2xl text-xs text-fraco">{ranking.nota}</p>
                    ) : null}
                    {legendaDoPosto(ranking) ? (
                      <p className="mt-1 max-w-2xl text-xs text-rotulo">
                        {legendaDoPosto(ranking)}
                      </p>
                    ) : null}
                  </div>
                  <label className="flex items-center gap-2 text-xs text-rotulo">
                    <span className="uppercase tracking-wide">Ordenar por</span>
                    <Combobox
                      opcoes={bloco.rankings.map((r) => ({
                        valor: r.chave,
                        rotulo: r.titulo,
                        detalhe: r.pergunta,
                      }))}
                      valor={ranking ? ranking.chave : null}
                      onEscolher={(v) => setOrdem(v, 'push')}
                      placeholder="Escolher a régua"
                      className="w-56"
                      larguraMenu="w-80"
                    />
                  </label>
                </div>

                <div className="px-2 pb-2 pt-3">
                  <Tabela<UsinaManutencaoOut>
                    linhas={linhas}
                    chave={(u) => u.id}
                    aoClicar={(u) => navigate(`/usinas/${u.id}/manutencao/cronograma`)}
                    colunas={[
                      {
                        titulo: '#',
                        celula: (u) => {
                          const posto = postos.get(u.id)
                          return posto ? (
                            <Posto posicao={posto.posicao} empatado={posto.empatado} />
                          ) : (
                            <SemNumero motivo={u.motivo} />
                          )
                        },
                      },
                      {
                        titulo: 'Usina',
                        celula: (u) => (
                          <div className="min-w-0 max-w-[16rem]">
                            <span className="block truncate font-medium text-forte">{u.nome}</span>
                            <span className="block truncate text-xs text-fraco">
                              {u.contrato ?? 'sem contrato de O&M cadastrado'}
                            </span>
                            {u.motivo ? (
                              <span
                                title={u.motivo}
                                className="mt-0.5 block truncate text-xs text-tom-alerta"
                              >
                                {u.motivo}
                              </span>
                            ) : null}
                          </div>
                        ),
                      },
                      {
                        titulo: 'Atrasadas',
                        alinhar: 'dir',
                        celula: (u) =>
                          u.atrasadas === null ? (
                            <SemNumero motivo={u.motivo} />
                          ) : (
                            <Num className={u.atrasadas > 0 ? 'text-tom-parado' : undefined}>
                              {inteiro(u.atrasadas)}
                            </Num>
                          ),
                      },
                      {
                        // Percentual e denominador na MESMA célula: separá-los é justamente
                        // o que permite ler um sem o outro.
                        titulo: 'Cumprimento',
                        alinhar: 'dir',
                        celula: (u) =>
                          u.denominador === null ? (
                            <SemNumero motivo={u.motivo} />
                          ) : (
                            <div className="flex flex-col items-end gap-1">
                              <span>
                                <Num>{porcento(u.cumprimento_pct, 1)}</Num>{' '}
                                <span className="text-xs text-fraco">
                                  {u.cumprimento_rotulo}
                                </span>
                              </span>
                              <BarraDoCumprimento
                                total={u.denominador}
                                feitas={u.feitas}
                                dispensadas={u.dispensadas}
                                atrasadas={u.atrasadas}
                              />
                              {u.fora_da_conta ? (
                                <span className="text-xs text-fraco">{u.fora_da_conta}</span>
                              ) : null}
                            </div>
                          ),
                      },
                      {
                        titulo: 'Feitas · dispensadas',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            <Num>{inteiro(u.feitas)}</Num>
                            <span className="block text-xs text-fraco">
                              {/* A dispensa aparece separada SEMPRE. Fundi-la com o feito
                                  apagaria a diferença entre executar e dispensar. */}
                              <Num>{inteiro(u.dispensadas)}</Num> dispensada(s) · previsto{' '}
                              <Num>{inteiro(u.previsto)}</Num>
                            </span>
                          </>
                        ),
                      },
                      {
                        titulo: 'OS em andamento',
                        alinhar: 'dir',
                        celula: (u) => <Num>{inteiro(u.os_em_andamento)}</Num>,
                      },
                      {
                        titulo: 'Pendências',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            <Num>{inteiro(u.pendencias_abertas)}</Num>
                            <span className="block text-xs text-fraco">abertas</span>
                            {u.pendencias_vencidas ? (
                              <span className="block text-xs text-tom-parado">
                                <Num>{inteiro(u.pendencias_vencidas)}</Num> com prazo vencido
                              </span>
                            ) : null}
                          </>
                        ),
                      },
                      {
                        titulo: 'Críticas · cobradas',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            {/* "Críticas", e não "urgentes": a ordem de serviço que chega a
                                este portal não tem campo de prioridade, e o servidor usou a
                                criticidade da pendência em vez de inventar um. A tela repete
                                a palavra do servidor pelo mesmo motivo. */}
                            <Num>{inteiro(u.pendencias_criticas)}</Num>
                            <span className="block text-xs text-fraco">
                              <Num>{inteiro(u.pendencias_cobradas)}</Num> cobradas por você
                            </span>
                          </>
                        ),
                      },
                    ]}
                  />
                </div>

                {ranking && ranking.fora.length > 0 ? <ForaDoRanking ranking={ranking} /> : null}
              </Cartao>

              {/* 3 — o rodapé fixo, com a ressalva do "em curso" */}
              <RodapeDaJanela janela={d.janela} escopo={d.usinas_no_escopo} />
            </>
          )
        }}
      </Tela4Estados>
    </Pagina>
  )
}

/**
 * O rodapé fixo desta tela.
 *
 * As frases da janela são as MESMAS do comparativo de geração (`frasesDaJanela`, em
 * `api.ts`) — o desenho pode diferir, a afirmação sobre o período não. A esta lista se
 * acrescentam as duas ressalvas que só valem para manutenção: o que conta é o cronograma
 * dentro da janela (é esse recorte que impede o "13 de 270" de voltar) e o que está "em
 * curso" é foto de hoje, não do período comparado.
 */
function RodapeDaJanela({ janela, escopo }: { janela: JanelaOut; escopo: number }) {
  const meses = mesesDaJanela(janela)
  const frases = [
    ...frasesDaJanela(janela, escopo),
    'A conta considera só os meses da janela em que o contrato existe — atividade de mês fora da vigência não entra no previsto nem no atraso.',
    'Ordens em andamento e pendências abertas são a situação de HOJE, não do período comparado.',
  ]
  return (
    <Cartao>
      <CabecalhoCard rotulo="A janela desta comparação" />
      <ul className="space-y-1">
        {frases.map((f) => (
          <li key={f} className="text-sm text-fraco">
            {f}
          </li>
        ))}
      </ul>
      {meses ? (
        <p className="mt-2 border-t border-borda-fraca pt-2 text-xs text-rotulo">
          Meses comparados: {meses}
        </p>
      ) : null}
    </Cartao>
  )
}

/** Quem ficou de fora deste ranking, com o motivo — a ausência é um fato, não um defeito. */
function ForaDoRanking({ ranking }: { ranking: RankingOut }) {
  return (
    <div className="border-t border-borda-fraca px-5 py-3">
      <p className="text-xs uppercase tracking-wide text-rotulo">
        Fora deste ranking ({inteiro(ranking.fora.length)})
      </p>
      <ul className="mt-1 space-y-0.5">
        {ranking.fora.map((f) => (
          <li key={f} className="text-xs text-fraco">
            {f}
          </li>
        ))}
      </ul>
    </div>
  )
}
