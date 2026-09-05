/**
 * O RELATÓRIO — a quinta aba: o fechamento do mês, sem a fábrica de PDF.
 *
 * As outras quatro abas respondem "gerei o que era esperado?" por quatro lentes. Esta
 * responde a pergunta seguinte, e é a única que responde: **o mês rendeu menos por falta de
 * sol ou por parada?** — e o que a equipe que esteve lá escreveu sobre ele.
 *
 * Ela é a §1 e a §5 do relatório do meuWatt, e nada mais. Ficaram deliberadamente de fora,
 * porque já são outras abas e repeti-las obrigaria o cliente a comparar dois lugares que
 * dizem a mesma coisa: os gráficos diários e o histórico mensal (são Mês e Ano), os
 * rankings por UC (são Unidades), a geração por skid e por inversor (são o comparativo de
 * equipamentos) e as caixas de observação por seção (`dash:detalhamento`, `dash:ucs`,
 * `dash:paradas`, `dash:meteo`, `dash:desvio`), que são conversa interna de operação — só a
 * `dash:gerais` é dirigida ao cliente, e é a que aparece aqui.
 *
 * Quatro decisões que não devem ser "simplificadas" depois:
 *
 * **O potencial não é uma segunda medição.** `potencial_kwh` vem do servidor já somado a
 * partir do MESMO painel que a aba Mês publica — é `medido + perdido`, o mesmo byte, não um
 * parecido. Refazer a soma aqui abriria a porta para o portal ter duas respostas para a
 * mesma perda, que é exatamente como ele já exibiu −64,3% numa tela e +101,7% na outra.
 *
 * **A perda diz sobre que base foi tirada.** O mesmo percentual muda conforme se divide
 * pela medição da fronteira ou pela dos inversores. O servidor escolhe (a fronteira manda
 * quando existe e cobre o mês inteiro) e manda a escolha em `perda_base`; a tela ESCREVE
 * "base fronteira" ou "base inversor" ao lado do número. Percentual sem base declarada é um
 * número que o cliente não tem como conferir.
 *
 * **As considerações são somente leitura.** Escrever é trabalho de operação: um campo de
 * edição aqui poria o cliente dentro do caderno da equipe. Não há `<textarea>` nem `<input>`
 * nesta tela inteira — e há teste que falha se algum aparecer.
 *
 * **Aqui não se gera documento.** Nada de capa, contracapa, marca d'água, QR, botão de
 * imprimir, `beforeprint` ou folha A4: isso é maquinário de impressão, e o dono mandou não
 * trazer. Os documentos fechados — relatório de geração, anexo de paradas e resumo
 * executivo — o cliente baixa prontos em Relatórios. Há teste que falha se as palavras da
 * fábrica de impressão voltarem ao DOM.
 *
 * A tela nunca inventa a leitura dos números: não pinta desvio, não classifica mês bom ou
 * ruim e não reescala a soma das causas pela perda do monitoramento. Quando as duas leituras
 * da mesma perda não podem ser o mesmo número (elas vêm de janelas diferentes do upstream),
 * a tela diz de que janela cada uma saiu — que é o que o servidor já declara em
 * `causas_conferem`, `perda_origem` e `causas_origem`.
 */

import { Aviso, Barra, CabecalhoCard, Cartao, Kpi, Num, Selo, Tabela } from '@/components/base'
import { dataCurta, dataHora, energia, inteiro, numero, porcento } from '@/lib/format'

import type { CausaDaParada, EventoDeParada, MarcoDaTimeline, Painel, RelatorioMes } from './api'
import { SemDado, comSinal } from './graficos'

/* ------------------------------------------------------------------ palavras */

/**
 * Horas, com uma casa: "141,6 h". `duracao()` de `lib/format` fala em MINUTOS e escreveria
 * "5 d 21 h" — e a régua desta seção compara horas paradas com horas de sol possíveis, onde
 * "dias" leem-se como dias de calendário e não como o somatório por inversor que o número é.
 */
function horas(valor: number | null): string {
  if (valor === null) return '—'
  return `${numero(valor, 1)} h`
}

/**
 * A frase da base da perda. O vocabulário é FECHADO e pertence ao servidor; aqui só se
 * escreve. Base desconhecida não vira uma explicação inventada — vira a ausência dela.
 */
export function fraseDaBase(base: string | null): string | null {
  if (base === 'fronteira') return 'base fronteira · a medição do ponto de entrega'
  if (base === 'inversor') return 'base inversor · a medição dos inversores'
  return null
}

/**
 * O tom do card da timeline.
 *
 * O meuWatt usa um vocabulário NARRATIVO (`parada`, `retomada`, `normalizado`, …) que não é
 * o dos seis tons do portal. Passá-lo direto para `classesDoTom` pintaria a timeline inteira
 * de cinza, porque nenhum daqueles nomes existe na régua de cor. A tradução é explícita e
 * fechada; nome novo cai em `semDados`, que é o neutro — nunca uma cor errada.
 */
export function tomDoMarco(tom: string): string {
  if (tom === 'parada') return 'parado'
  if (tom === 'degradacao' || tom === 'recorrente') return 'alerta'
  if (tom === 'retomada' || tom === 'normalizado') return 'ok'
  return 'semDados'
}

/** O selo da classificação de uma causa ou parada. Sem classificação NÃO é "interna". */
function SeloDaClassificacao({
  externa,
  classificada,
}: {
  externa: boolean
  classificada: boolean
}) {
  if (!classificada) return <Selo tom="semDados">Não classificada</Selo>
  if (externa) return <Selo tom="tempoRuim">Externa</Selo>
  return <Selo tom="alerta">Interna</Selo>
}

/* ------------------------------------------------------------------ a aba */

export function AbaRelatorio({
  relatorio,
  painel,
}: {
  relatorio: RelatorioMes
  /**
   * O painel do MESMO mês, quando já foi lido — é dele que sai a disponibilidade que as
   * causas explicam. Nulo enquanto a leitura não chegou (ou se ela falhou): aí o bloco de
   * disponibilidade simplesmente não aparece, em vez de mostrar um travessão que se lê como
   * "a usina não teve disponibilidade".
   */
  painel: Painel | null
}) {
  const r = relatorio
  const base = fraseDaBase(r.perda_base)
  const semParadas = r.paradas_origem === null

  return (
    <>
      {r.aviso ? <Aviso>{r.aviso}</Aviso> : null}

      {/* ─────────────────────────────────────────── sol ou parada */}
      <Cartao>
        <CabecalhoCard
          rotulo={`O fechamento de ${r.rotulo}`}
          direita={
            r.em_curso
              ? r.dia_de_corte === null
                ? 'mês em curso'
                : `acumulado até o dia ${r.dia_de_corte}`
              : 'mês fechado'
          }
        />
        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            rotulo="Medido (inversores)"
            valor={energia(r.medido_inversores_kwh)}
            tamanho="grande"
            detalhe="o que a usina de fato entregou"
          />
          <Kpi
            rotulo="Energia potencial"
            valor={energia(r.potencial_kwh)}
            tamanho="grande"
            detalhe={
              <>
                medido + <Num>{energia(r.perdida_kwh)}</Num> perdidos em paradas
              </>
            }
          />
          {/* Os dois desvios saem do servidor prontos e NÃO são pintados: um limiar
              inventado aqui coloriria de vermelho uma usina que o contrato considera em
              dia. Cor, neste produto, significa estado — e estado quem decide é quem tem o
              dado inteiro. */}
          <Kpi
            rotulo="Medido vs projeto"
            valor={comSinal(r.medido_vs_projeto_pct)}
            tamanho="grande"
            detalhe={
              r.projeto_proporcional_kwh === null ? (
                'sem meta de projeto para o período'
              ) : (
                <>
                  sobre <Num>{energia(r.projeto_proporcional_kwh)}</Num> de projeto
                </>
              )
            }
          />
          <Kpi
            rotulo="Potencial vs projeto"
            valor={comSinal(r.potencial_vs_projeto_pct)}
            tamanho="grande"
            detalhe="o mês se a usina não tivesse parado"
          />
        </div>

        <p className="mt-4 border-t border-borda-fraca pt-3 text-sm text-corpo">
          Os dois desvios lado a lado separam CLIMA de PARADA. Quando o de potencial fica bem
          acima do de medido, o que faltou no mês foi tempo de usina de pé — a energia estava
          disponível e não foi colhida. Quando os dois caem juntos, a usina estava de pé e o
          que faltou foi sol.
        </p>
        <p className="mt-2 text-xs text-fraco">{r.regra.potencial}</p>
      </Cartao>

      {/* ─────────────────────────────────────────── perdas */}
      <Cartao>
        <CabecalhoCard rotulo="A energia que se perdeu em paradas" />
        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            rotulo="Energia perdida"
            valor={energia(r.perdida_kwh)}
            tamanho="grande"
            detalhe={r.perda_origem === null ? undefined : `origem: ${r.perda_origem}`}
          />
          <Kpi
            rotulo="Da geração do mês"
            valor={porcento(r.perda_pct)}
            tamanho="grande"
            /* A base é obrigatória junto do percentual: dividir pela fronteira ou pelos
               inversores dá números diferentes para a mesma pergunta, e sem a palavra
               escrita o cliente não tem como conferir qual das duas falou. */
            detalhe={base ?? 'sem base declarada para o percentual'}
          />
          <Kpi
            rotulo="Horas paradas"
            valor={horas(r.horas_paradas)}
            tamanho="grande"
            detalhe={
              r.horas_possiveis === null ? (
                'sem o total de horas possíveis do período'
              ) : (
                <>
                  de <Num>{horas(r.horas_possiveis)}</Num> possíveis
                </>
              )
            }
          />
          <Kpi
            rotulo="Inversores no denominador"
            valor={inteiro(r.inversores_considerados)}
            detalhe="horas de sol decorridas × inversores"
          />
        </div>

        {/* A régua. Sem ela o absoluto assusta: 141 h soam como uma semana parada, quando
            são a soma do tempo de CADA inversor afetado dentro do horário de sol. */}
        {r.horas_paradas !== null && r.horas_possiveis !== null && r.horas_possiveis > 0 ? (
          <div className="mt-4" data-testid="regua-horas">
            {/* A largura da barra é a razão entre os DOIS números impressos logo abaixo
                — não um número novo: quem lê confere a régua contra o texto. */}
            <Barra pct={(r.horas_paradas / r.horas_possiveis) * 100} tom="parado" />
            <p className="mt-2 text-xs text-fraco">
              <Num>{horas(r.horas_paradas)}</Num> paradas de{' '}
              <Num>{horas(r.horas_possiveis)}</Num> possíveis no período.
            </p>
          </div>
        ) : null}

        {r.eventos_sem_duracao > 0 ? (
          <p className="mt-3 text-sm text-tom-alerta">
            {r.eventos_sem_duracao === 1
              ? 'Uma parada veio sem duração calculada pelo monitoramento'
              : `${inteiro(r.eventos_sem_duracao)} paradas vieram sem duração calculada pelo monitoramento`}{' '}
            — por isso o total de horas sai em travessão em vez de sair menor do que foi.
          </p>
        ) : null}

        <p className="mt-3 border-t border-borda-fraca pt-3 text-xs text-fraco">
          {r.regra.perda} {r.regra.horas}
        </p>
      </Cartao>

      {/* ─────────────────────────────────────────── considerações */}
      <Cartao>
        <CabecalhoCard
          rotulo={`Considerações gerais de ${r.rotulo}`}
          direita={
            r.consideracoes && (r.consideracoes.autor || r.consideracoes.em) ? (
              <>
                {r.consideracoes.autor ?? 'equipe de operação'}
                {r.consideracoes.em ? ` · ${dataHora(r.consideracoes.em)}` : ''}
              </>
            ) : null
          }
        />
        {r.consideracoes === null ? (
          <SemDado>
            A equipe ainda não escreveu o fechamento deste mês. Quando escrever, o texto
            aparece aqui como foi assinado.
          </SemDado>
        ) : (
          /*
            Texto puro, com as quebras de linha preservadas. Não há editor: escrever o
            fechamento é trabalho de operação, e o valor deste bloco para o cliente é
            justamente ser o que a equipe assinou — não um campo que ele possa mexer.
          */
          <p
            className="whitespace-pre-wrap text-sm leading-relaxed text-corpo"
            data-testid="consideracoes"
          >
            {r.consideracoes.texto}
          </p>
        )}
      </Cartao>

      {/* ─────────────────────────────────────────── causas */}
      <Cartao>
        <CabecalhoCard
          rotulo="Por que a usina parou"
          direita={
            r.causas.length === 0 ? null : `${inteiro(r.causas.length)} categorias`
          }
        />

        {/* A disponibilidade fica AQUI e não num cartão próprio: é o número de teor
            contratual que estas causas explicam. Ele vem do painel do mesmo mês — o mesmo
            byte que a aba Mês publica —, e não de uma segunda conta. */}
        {painel === null ? null : (
          <div className="mb-4 grid gap-6 sm:grid-cols-3">
            <Kpi
              rotulo="Disponibilidade real"
              valor={porcento(painel.disponibilidade_real_pct)}
              detalhe="considera todas as paradas"
            />
            <Kpi
              rotulo="Disponibilidade contratual"
              valor={porcento(painel.disponibilidade_contratual_pct)}
              detalhe="desconta as causas externas listadas abaixo"
            />
            <Kpi
              rotulo="Paradas sem causa"
              valor={inteiro(painel.paradas_pendentes)}
              detalhe={
                painel.paradas_pendentes > 0
                  ? 'enquanto houver, a contratual está incompleta'
                  : 'toda parada do período foi classificada'
              }
            />
          </div>
        )}

        {semParadas ? (
          <SemDado>
            As paradas classificadas não puderam ser lidas neste período. Lista vazia aqui
            significaria "a usina não parou", e não é o que sabemos.
          </SemDado>
        ) : r.causas.length === 0 ? (
          <SemDado>Nenhuma parada registrada no período.</SemDado>
        ) : (
          <Tabela<CausaDaParada>
            colunas={[
              {
                titulo: 'Causa',
                celula: (c) => (
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-corpo">{c.categoria}</span>
                    <SeloDaClassificacao externa={c.externa} classificada={c.classificada} />
                  </span>
                ),
              },
              {
                titulo: 'Eventos',
                alinhar: 'dir',
                celula: (c) => <Num>{inteiro(c.eventos)}</Num>,
              },
              {
                titulo: 'Energia perdida',
                alinhar: 'dir',
                celula: (c) => <Num>{energia(c.energia_kwh)}</Num>,
              },
              {
                titulo: 'Horas',
                alinhar: 'dir',
                celula: (c) => <Num>{horas(c.horas)}</Num>,
              },
            ]}
            linhas={r.causas}
            chave={(c) => c.categoria}
          />
        )}

        {/*
          As duas leituras da MESMA perda vêm de janelas diferentes do upstream (a do
          monitoramento e a dos alertas). Quando não batem, a tela DIZ isso e nomeia cada
          janela — reescalar uma pela outra produziria um kWh que ninguém mediu.
        */}
        {r.causas_conferem === false ? (
          <p className="mt-3 text-sm text-tom-alerta">
            A soma das causas (<Num>{energia(r.causas_total_kwh)}</Num>, de{' '}
            {r.causas_origem ?? 'outra leitura'}) não fecha com a energia perdida do período (
            <Num>{energia(r.perdida_kwh)}</Num>, de {r.perda_origem ?? 'outra leitura'}). São
            duas janelas do monitoramento; o número que sustenta a disponibilidade é o
            segundo.
          </p>
        ) : null}

        <p className="mt-3 border-t border-borda-fraca pt-3 text-xs text-fraco">
          {r.regra.causas}
        </p>
      </Cartao>

      {/* ─────────────────────────────────────────── eventos */}
      {semParadas || r.eventos.length === 0 ? null : (
        <Cartao>
          <CabecalhoCard
            rotulo="As paradas do mês"
            direita={`${inteiro(r.eventos.length)} registradas`}
          />
          <Tabela<EventoDeParada & { ordem: number }>
            colunas={[
              {
                titulo: 'Período',
                celula: (e) => (
                  <span className="whitespace-nowrap">
                    <Num>{dataCurta(e.inicio)}</Num>
                    {e.em_aberto ? (
                      <span className="ml-2 text-tom-alerta">em aberto</span>
                    ) : e.fim && e.fim !== e.inicio ? (
                      <>
                        {' a '}
                        <Num>{dataCurta(e.fim)}</Num>
                      </>
                    ) : null}
                  </span>
                ),
              },
              {
                titulo: 'Tipo',
                celula: (e) =>
                  e.tipo === 'degradacao' ? (
                    <Selo tom="alerta">Baixa geração</Selo>
                  ) : (
                    <Selo tom="parado">Parada</Selo>
                  ),
              },
              { titulo: 'Unidade', celula: (e) => e.unidade ?? '—' },
              {
                titulo: 'Causa',
                celula: (e) => (
                  <span className="flex flex-wrap items-center gap-2">
                    <span>{e.causa ?? '—'}</span>
                    <SeloDaClassificacao externa={e.externa} classificada={e.classificada} />
                  </span>
                ),
              },
              {
                titulo: 'Inversores',
                alinhar: 'dir',
                celula: (e) => <Num>{inteiro(e.inversores_afetados)}</Num>,
              },
              { titulo: 'Horas', alinhar: 'dir', celula: (e) => <Num>{horas(e.horas)}</Num> },
              {
                titulo: 'Energia',
                alinhar: 'dir',
                celula: (e) => <Num>{energia(e.energia_kwh)}</Num>,
              },
            ]}
            /* A parada não tem id no contrato, e os CAMPOS não a identificam: em Porto
               Ferreira as seis paradas do mês têm início, unidade, causa, horas e tipo
               iguais, então a chave montada com eles repetia seis vezes — o React avisava
               e podia reaproveitar a linha errada ao reordenar. A posição na lista que o
               servidor mandou é a única identidade que existe aqui, e ela é estável porque
               esta tabela não ordena nada. */
            linhas={r.eventos.map((e, i) => ({ ...e, ordem: i }))}
            chave={(e) => e.ordem}
          />
          {/* A limitação do agrupamento é declarada pelo SERVIDOR, porque é limitação da
              fonte: se ela mudar, muda lá e chega aqui pronta. */}
          <p className="mt-3 text-xs text-fraco">{r.eventos_agrupamento}</p>
        </Cartao>
      )}

      {/* ─────────────────────────────────────────── timeline curada */}
      {r.timeline.exibir && r.timeline.marcos.length > 0 ? (
        <Cartao>
          <CabecalhoCard
            rotulo="A história do mês"
            direita="linha do tempo escrita pela operação"
          />
          <ol className="space-y-3" data-testid="timeline">
            {r.timeline.marcos.map((m: MarcoDaTimeline) => (
              <li key={m.id} className="flex gap-3">
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full bg-tom-${tomDoMarco(m.tom)}`}
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {m.chip ? <Selo tom={tomDoMarco(m.tom)}>{m.chip}</Selo> : null}
                    <span className="text-sm font-medium text-corpo">{m.titulo}</span>
                    <span className="text-xs text-fraco">
                      <Num>{dataHora(m.em)}</Num>
                    </span>
                  </div>
                  {m.sub ? <p className="mt-0.5 text-sm text-fraco">{m.sub}</p> : null}
                </div>
              </li>
            ))}
          </ol>
        </Cartao>
      ) : null}
    </>
  )
}
