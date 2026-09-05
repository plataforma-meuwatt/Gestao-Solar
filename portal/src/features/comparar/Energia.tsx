/**
 * Comparar usinas — **qual gera mais, e qual rende melhor?**
 *
 * É a pergunta do diretor com sete usinas, e até aqui ela não tinha tela em lugar nenhum: a
 * Visão geral responde "como está tudo AGORA", uma linha por usina no mês corrente; esta
 * responde "qual delas", e para isso exige um PERÍODO e uma régua que não minta quando as
 * usinas são desiguais.
 *
 * Por isso é rota de CARTEIRA (`/comparar/energia`), fora de `/usinas/:id`: não há usina no
 * endereço porque a pergunta não cabe dentro de uma. Ela entra como primeiro item da família
 * Geração porque é lá que quem pergunta está olhando.
 *
 * ### As quatro regras de não mentir comparando usinas diferentes
 *
 * Todas moram no servidor (`bff/app/services/carteira.py`); aqui elas aparecem escritas na
 * tela, que é onde o cliente precisa lê-las:
 *
 * 1. **Capacidade diferente resolve-se com kWh/kWp.** A produtividade é o ranking padrão — e
 *    o padrão é o do servidor, não desta tela: abrir por energia entregaria todo dia o mesmo
 *    pódio, o das usinas maiores, e "qual rende melhor" nunca chegaria a ser perguntado. A
 *    energia absoluta fica ao lado, respondendo a OUTRA pergunta, e as duas vêm rotuladas
 *    com a pergunta que respondem.
 * 2. **Data de entrada diferente resolve-se com JANELA COMUM** — a interseção dos meses
 *    realmente medidos. O rodapé é fixo e NOMEIA a usina que encolheu o período: sem o nome,
 *    o cliente lê "jun a set" e conclui que o portal perdeu dados.
 * 3. **Usina sem dado, sem capacidade ou sem PR sai do ranking**, com o motivo escrito — em
 *    vez de aparecer como zero no fim, que é a leitura mais injusta possível de uma ausência
 *    e a mais difícil de desconfiar, porque parece um número.
 * 4. **A irradiação viaja junto como contexto**, porque "rende melhor" ainda contém "teve
 *    mais sol".
 *
 * **Período por mês ou ano, nunca datas livres.** Não é preciosismo de interface: as datas
 * são as mesmas que `/plants/{id}/desempenho` usa, e é isso que faz a leitura cair no cache
 * de 10 min já quente do monitoramento em vez de provocar um `miss` por usina a cada
 * abertura. O período e a ordenação moram na URL — o diretor manda o link pronto ao time.
 *
 * **A tela não soma e não ordena.** Todo total vem de `totais`, toda ordem vem de
 * `rankings[].itens`. Somar aqui daria o segundo número para a mesma pergunta, que é o
 * defeito mais caro deste projeto.
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
import { energia as fmtEnergia, inteiro, numero, porcento } from '@/lib/format'
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
  type UsinaEnergiaOut,
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

/** Cidade e UF, quando o cadastro tem. Usina sem cidade não ganha vírgula solta. */
function local(u: UsinaEnergiaOut): string | null {
  const partes = [u.cidade, u.uf].filter(Boolean)
  return partes.length ? partes.join(', ') : null
}

/**
 * O posto da usina neste ranking — "1º", "2º"… e "=" quando há empate.
 *
 * O empate DIVIDE a posição no servidor (1, 1, 3) porque desempatar por nome coroaria uma
 * usina pela inicial dela. O sinal existe para o cliente não achar que a tela errou a
 * contagem ao ver dois primeiros lugares.
 */
function Posto({ posicao, empatado }: { posicao: number; empatado: boolean }) {
  return (
    <span className="whitespace-nowrap text-sm text-fraco" title="Posição no ranking do servidor">
      <Num className="text-forte">{inteiro(posicao)}º</Num>
      {empatado ? <span className="ml-1 text-xs text-rotulo">=</span> : null}
    </span>
  )
}

/** A célula de uma usina sem número neste recorte: travessão e o porquê, nunca zero. */
function SemNumero({ motivo }: { motivo: string | null }) {
  return (
    <span className="text-fraco" title={motivo ?? undefined}>
      —
    </span>
  )
}

export default function CompararEnergia() {
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
    padrao: 'produtividade',
    valido: CHAVE_DE_REGUA,
  })

  const { de, ate } = useMemo(() => intervaloDe(referencia, recorte), [referencia, recorte])
  const leitura = useComparativo('energia', de, ate)

  return (
    <Pagina
      titulo="Comparar usinas"
      subtitulo="Qual gera mais, e qual rende melhor?"
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
          const bloco = d.energia
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
                descricao="A sua conta tem uma usina só — comparar uma coisa com ela mesma não é comparação. O painel dela responde a mesma pergunta com muito mais detalhe."
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

              {/* 1 — a carteira somada, com o "de N" que impede o total de parecer o todo */}
              <Cartao>
                <CabecalhoCard
                  rotulo={`A carteira · ${d.janela.rotulo ?? ''}`}
                  direita={
                    <>
                      <Num>{inteiro(totais.usinas_no_total)}</Num> de{' '}
                      <Num>{inteiro(d.usinas_no_escopo)}</Num> usinas com medição
                    </>
                  }
                />
                {/*
                  Os TRÊS números da esquerda são da MESMA população e da MESMA janela — a
                  que o cabeçalho acabou de nomear. Antes, energia e capacidade vinham do
                  período pedido e de todas as usinas, e a produtividade da janela comum e
                  só das comparáveis: em fev/2026 o cartão dizia "3 de 7", somava a energia
                  de 3 usinas e a capacidade de 6, e quem dividisse os dois achava 18,6 com
                  59,6 impresso ao lado. Divisão feita na cabeça tem de fechar.
                */}
                <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
                  <Kpi
                    rotulo="Energia gerada"
                    valor={fmtEnergia(totais.energia_comparavel_kwh)}
                    tamanho="grande"
                    detalhe={`nas ${inteiro(totais.usinas_no_total)} usinas comparáveis`}
                  />
                  <Kpi
                    rotulo="Produtividade da carteira"
                    valor={numero(totais.produtividade_kwh_kwp, 1)}
                    unidade="kWh/kWp"
                    detalhe="energia ÷ capacidade, as duas acima"
                  />
                  <Kpi
                    rotulo="Capacidade comparável"
                    valor={numero(totais.capacidade_comparavel_kwp, 1)}
                    unidade="kWp"
                    detalhe="das mesmas usinas da energia"
                  />
                  <Kpi
                    rotulo="Perdas por paradas"
                    valor={fmtEnergia(totais.perdas_paradas_kwh)}
                    detalhe="energia que deixou de ser gerada"
                  />
                </div>
                {/*
                  A pergunta do período INTEIRO existe e é legítima — só não é a manchete, e
                  não divide nada com os números de cima. Ela só aparece quando é DIFERENTE
                  da manchete; repetida, seria ruído com cara de contradição.
                */}
                {!d.janela.completa &&
                totais.energia_kwh !== null &&
                totais.energia_kwh !== totais.energia_comparavel_kwh ? (
                  <p className="mt-4 text-xs text-fraco">
                    No período inteiro que você pediu, as{' '}
                    <Num>{inteiro(d.usinas_no_escopo)}</Num> usinas somaram{' '}
                    <Num>{fmtEnergia(totais.energia_kwh)}</Num>, sobre{' '}
                    <Num>{numero(totais.capacidade_kwp, 1)}</Num> kWp instalados — outra
                    pergunta, e por isso fora da conta acima.
                  </p>
                ) : null}
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
                  <Tabela<UsinaEnergiaOut>
                    linhas={linhas}
                    chave={(u) => u.id}
                    aoClicar={(u) => navigate(`/usinas/${u.id}/energia`)}
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
                          // Largura presa: sem ela, o aviso longo de uma usina empurra as
                          // colunas de número para fora da tela — e o número é o que o
                          // cliente veio ver. Mesma lição da tabela da Visão geral.
                          <div className="min-w-0 max-w-[16rem]">
                            <span className="block truncate font-medium text-forte">{u.nome}</span>
                            {local(u) ? (
                              <span className="block truncate text-xs text-fraco">{local(u)}</span>
                            ) : null}
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
                        titulo: 'Produtividade',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            <Num>{numero(u.produtividade_kwh_kwp, 1)}</Num>
                            <span className="block text-xs text-fraco">kWh/kWp</span>
                          </>
                        ),
                      },
                      {
                        titulo: 'Energia',
                        alinhar: 'dir',
                        // `energia_comparavel_kwh`, NUNCA `energia_kwh`. A linha imprime
                        // energia, capacidade e produtividade lado a lado, e a
                        // produtividade sai da JANELA COMUM: com a energia do período
                        // pedido ao lado, a divisão que o leitor faz na cabeça não fecha —
                        // Ibitinga imprimia 328,7 kWh/kWp com 1.196,5 MWh sobre 1.289,9 kWp
                        // (que dá 927,6). Quando a janela cobre o período inteiro as duas
                        // são o mesmo número; é quando ela encolhe que a escolha aparece, e
                        // aí a certa é a que o ranking usou — a mesma que o app já mostra.
                        celula: (u) =>
                          u.energia_comparavel_kwh === null ? (
                            <SemNumero motivo={u.motivo ?? 'Sem medição na janela comum.'} />
                          ) : (
                            <>
                              <Num>{fmtEnergia(u.energia_comparavel_kwh)}</Num>
                              <span className="block text-xs text-fraco">
                                {u.capacidade_kwp === null ? (
                                  'sem capacidade declarada'
                                ) : (
                                  <>
                                    <Num>{numero(u.capacidade_kwp, 1)}</Num> kWp
                                  </>
                                )}
                              </span>
                            </>
                          ),
                      },
                      {
                        titulo: 'PR',
                        alinhar: 'dir',
                        celula: (u) =>
                          // Sem POA medida não existe PR — e 0 % não é uma medição, é a
                          // ausência dela. A usina fica com travessão aqui e sai do ranking
                          // de PR pelo servidor, com o motivo listado logo abaixo.
                          u.pr_pct === null ? (
                            <SemNumero motivo="Sem irradiância medida no período." />
                          ) : (
                            <Num>{porcento(u.pr_pct, 1)}</Num>
                          ),
                      },
                      {
                        titulo: 'Disponibilidade',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            <Num>{porcento(u.disponibilidade_real_pct, 1)}</Num>
                            <span className="block text-xs text-fraco">
                              contratual{' '}
                              <Num>{porcento(u.disponibilidade_contratual_pct, 1)}</Num>
                            </span>
                            {u.paradas_pendentes ? (
                              <span className="block text-xs text-tom-alerta">
                                <Num>{inteiro(u.paradas_pendentes)}</Num> parada(s) sem
                                classificação
                              </span>
                            ) : null}
                          </>
                        ),
                      },
                      {
                        // O contexto que impede a leitura errada do ranking: uma usina pode
                        // render mais porque recebeu mais sol, não porque é melhor.
                        titulo: 'Irradiação',
                        alinhar: 'dir',
                        celula: (u) => (
                          <>
                            <Num>{numero(u.irradiacao_hpoa, 1)}</Num>
                            <span className="block text-xs text-fraco">
                              POA · GHI <Num>{numero(u.irradiacao_ghi, 1)}</Num>
                            </span>
                          </>
                        ),
                      },
                      {
                        titulo: 'Perdas',
                        alinhar: 'dir',
                        celula: (u) => <Num>{fmtEnergia(u.perdas_paradas_kwh)}</Num>,
                      },
                    ]}
                  />
                </div>

                {ranking && ranking.fora.length > 0 ? (
                  <ForaDoRanking ranking={ranking} />
                ) : null}
              </Cartao>

              {/* 3 — o rodapé fixo: de que janela esta comparação está falando */}
              <RodapeDaJanela janela={d.janela} escopo={d.usinas_no_escopo} />
            </>
          )
        }}
      </Tela4Estados>
    </Pagina>
  )
}

/**
 * O rodapé fixo: de que janela esta comparação está falando.
 *
 * É fixo de propósito — não é um aviso que aparece quando algo dá errado. Uma comparação
 * entre usinas que entraram em operação em datas diferentes é uma armadilha permanente, e o
 * cliente precisa saber sempre, e não só nos meses ruins, qual recorte está lendo.
 *
 * As FRASES vêm de `frasesDaJanela` (em `api.ts`), compartilhadas com o comparativo de
 * manutenção: o desenho pode diferir entre as duas telas, a afirmação sobre a janela não —
 * duas telas dizendo coisas diferentes sobre o mesmo período é o defeito mais caro deste
 * projeto. (Elas mereciam um módulo próprio; ficaram em `api.ts` porque esta leva não podia
 * criar arquivo novo na pasta.)
 */
function RodapeDaJanela({ janela, escopo }: { janela: JanelaOut; escopo: number }) {
  const meses = mesesDaJanela(janela)
  return (
    <Cartao>
      <CabecalhoCard rotulo="A janela desta comparação" />
      <ul className="space-y-1">
        {frasesDaJanela(janela, escopo).map((f) => (
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

/**
 * Quem ficou de fora deste ranking, com o motivo.
 *
 * Sem esta lista a ausência vira suspeita de erro da tela: o cliente conta cinco usinas na
 * carteira, vê quatro no pódio e não tem como saber se a quinta sumiu ou se não tinha o
 * número. Com o motivo escrito, a ausência é um fato do dado, não um defeito do portal.
 */
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
