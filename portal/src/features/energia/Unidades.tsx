/**
 * As UNIDADES CONSUMIDORAS — o comparativo entre as UCs da usina, no mês ou no ano.
 *
 * É a mesma pergunta das outras abas ("gerou o esperado?") vista por unidade, e por isso
 * ela é um RECORTE do Painel e não um item de menu à parte.
 *
 * **A cor não identifica a unidade.** Neste produto cor significa ESTADO — são seis tons e
 * nenhum a mais —, então uma paleta por UC seria uma sétima linguagem de cor na mesma
 * tela. Em vez de empilhar séries coloridas, a legenda ISOLA: clicar numa unidade desenha
 * só ela; clicar de novo volta para a soma de todas. A pergunta ("essa UC está puxando o
 * conjunto para baixo?") continua respondida, sem inventar vocabulário visual.
 *
 * **UC sem PR não entra no ranking de PR.** Ela continua na tabela, com travessão: sumir
 * com a linha faria o cliente concluir que a unidade não existe; desenhá-la no chão diria
 * que ela rendeu zero.
 */

import { useMemo, useState } from 'react'

import { CabecalhoCard, Cartao, Kpi, Num, Selo, Aviso } from '@/components/base'
import { energia, numero, porcento } from '@/lib/format'

import type { Unidades, UnidadeDoPeriodo } from './api'
import {
  Arco,
  BarrasDoPeriodo,
  RankingBarras,
  SemDado,
  TabelaLonga,
  capacidade,
  type ItemDoRanking,
  type PontoDoPeriodo,
} from './graficos'

/** "2026-08-14" → "14"; "2026-08" → "ago". O eixo é curto porque são muitos pontos. */
function rotuloDoDia(iso: string): string {
  const partes = iso.split('-')
  return partes.length >= 3 ? String(Number(partes[2])) : iso
}

/** Soma as unidades numa fatia de tempo. Nulo em todas = nulo; nunca zero fabricado. */
function somaDaFatia(serie: { valores: (number | null)[] }[], i: number): number | null {
  const numeros = serie
    .map((s) => s.valores[i])
    .filter((v): v is number => typeof v === 'number')
  return numeros.length > 0 ? numeros.reduce((a, b) => a + b, 0) : null
}

export function AbaUnidades({ unidades }: { unidades: Unidades }) {
  const u = unidades
  const [isolada, setIsolada] = useState<number | null>(null)

  const porIndice = useMemo(
    () => new Map(u.ucs.map((uc) => [uc.indice, uc])),
    [u.ucs],
  )

  const pontos: PontoDoPeriodo[] = useMemo(() => {
    const escolhida = isolada === null ? null : u.serie.find((s) => s.indice === isolada)
    return u.serie_dias.map((dia, i) => ({
      chave: dia,
      rotulo: rotuloDoDia(dia),
      medido: escolhida ? (escolhida.valores[i] ?? null) : somaDaFatia(u.serie, i),
      projeto: null,
    }))
  }, [u.serie, u.serie_dias, isolada])

  const ranking = (ordem: number[], texto: (uc: UnidadeDoPeriodo) => string, valor: (uc: UnidadeDoPeriodo) => number | null): ItemDoRanking[] =>
    ordem
      .map((i) => porIndice.get(i))
      .filter((uc): uc is UnidadeDoPeriodo => uc !== undefined)
      .map((uc) => ({ chave: String(uc.indice), nome: uc.nome, valor: valor(uc), texto: texto(uc) }))

  const nomeIsolada = isolada === null ? null : (porIndice.get(isolada)?.nome ?? null)

  return (
    <>
      {u.aviso ? <Aviso>{u.aviso}</Aviso> : null}

      {/* ───────────────────────────────────────────────── números */}
      <Cartao>
        <CabecalhoCard rotulo="As unidades desta usina" />
        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi rotulo="Unidades ativas" valor={numero(u.ucs_ativas, 0)} tamanho="grande" />
          <Kpi
            rotulo="Capacidade total"
            valor={capacidade(u.capacidade_total_kwp)}
            tamanho="grande"
          />
          <Kpi
            rotulo="Energia do período"
            valor={energia(u.energia_periodo_kwh)}
            tamanho="grande"
          />
          {/* O número grande é a participação, e o nome vem embaixo: `Kpi` escreve o valor
              em fonte mono, que é o certo para número e o errado para nome próprio. */}
          <Kpi
            rotulo="Maior contribuinte"
            valor={u.maior ? porcento(u.maior.share_pct) : '—'}
            tamanho="grande"
            detalhe={u.maior ? `da geração do período · ${u.maior.nome}` : undefined}
          />
        </div>
      </Cartao>

      {/* ───────────────────────────────────────────────── série */}
      <Cartao>
        <CabecalhoCard
          rotulo={nomeIsolada ? `Geração diária · ${nomeIsolada}` : 'Geração diária · todas as unidades'}
          direita={nomeIsolada ? 'clique na unidade de novo para ver o conjunto' : undefined}
        />
        {u.serie.length === 0 || u.serie_dias.length === 0 ? (
          <SemDado>O monitoramento não devolveu série diária por unidade neste período.</SemDado>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap gap-2">
              {u.serie.map((s) => (
                <button
                  key={s.indice}
                  type="button"
                  onClick={() => setIsolada((atual) => (atual === s.indice ? null : s.indice))}
                  aria-pressed={isolada === s.indice}
                  className={`min-h-[32px] rounded-campo border px-3 text-xs transition ${
                    isolada === s.indice
                      ? 'border-borda-forte bg-superficie-destacada text-forte'
                      : 'border-borda text-fraco hover:text-corpo'
                  }`}
                >
                  {s.nome}
                </button>
              ))}
            </div>
            <BarrasDoPeriodo
              pontos={pontos}
              rotuloMedido={nomeIsolada ? `geração de ${nomeIsolada}` : 'soma das unidades'}
            />
          </>
        )}
      </Cartao>

      {/* ───────────────────────────────────────────────── rankings */}
      <div className="grid gap-4 xl:grid-cols-3">
        <Cartao>
          <CabecalhoCard rotulo="Geração por unidade" />
          {u.ucs.length === 0 ? (
            <SemDado>Sem unidades para comparar.</SemDado>
          ) : (
            <RankingBarras
              itens={ranking(
                u.ranking_geracao,
                (uc) => energia(uc.geracao_kwh),
                (uc) => uc.geracao_kwh,
              )}
            />
          )}
        </Cartao>

        <Cartao>
          <CabecalhoCard rotulo="Performance ratio por unidade" />
          {u.ucs.length === 0 ? (
            <SemDado>Sem unidades para comparar.</SemDado>
          ) : (
            <RankingBarras
              itens={ranking(u.ranking_pr, (uc) => porcento(uc.pr_pct), (uc) => uc.pr_pct)}
              referencia={u.pr_referencia_pct}
              rotuloReferencia={`referência de mercado (${porcento(u.pr_referencia_pct, 0)})`}
            />
          )}
        </Cartao>

        <Cartao>
          <CabecalhoCard rotulo="Produtividade por unidade" />
          {u.ucs.length === 0 ? (
            <SemDado>Sem unidades para comparar.</SemDado>
          ) : (
            <RankingBarras
              itens={ranking(
                u.ranking_produtividade,
                (uc) => `${numero(uc.produtividade, 1)} kWh/kWp`,
                (uc) => uc.produtividade,
              )}
            />
          )}
        </Cartao>
      </div>

      {/* ───────────────────────────────────────────────── disponibilidade */}
      {u.ucs.length > 0 ? (
        <Cartao>
          <CabecalhoCard rotulo="Disponibilidade energética por unidade" />
          <div className="flex flex-wrap gap-6">
            {u.ucs.map((uc) => (
              <Arco key={uc.indice} pct={uc.disponibilidade_real_pct} rotulo={uc.nome} />
            ))}
          </div>
        </Cartao>
      ) : null}

      {/* ───────────────────────────────────────────────── tabela */}
      <Cartao semPadding>
        <div className="p-5 pb-0">
          <CabecalhoCard
            rotulo="Por unidade consumidora"
            direita={
              u.faturas_situacao ? <Selo tom="semDados">Fatura: {u.faturas_situacao}</Selo> : undefined
            }
          />
        </div>
        {u.ucs.length === 0 ? (
          <div className="px-5 pb-5">
            <SemDado>O monitoramento não devolveu unidades consumidoras nesta usina.</SemDado>
          </div>
        ) : (
          <div className="px-2 pb-3">
            <TabelaLonga<UnidadeDoPeriodo>
              colunas={[
                { chave: 'nome', titulo: 'Unidade', celula: (uc) => uc.nome },
                {
                  chave: 'kwp',
                  titulo: 'Capacidade',
                  alinhar: 'dir',
                  celula: (uc) => <Num>{capacidade(uc.capacidade_kwp)}</Num>,
                },
                {
                  chave: 'geracao',
                  titulo: 'Geração',
                  alinhar: 'dir',
                  celula: (uc) => <Num>{energia(uc.geracao_kwh)}</Num>,
                },
                {
                  chave: 'share',
                  titulo: 'Participação',
                  alinhar: 'dir',
                  celula: (uc) => <Num>{porcento(uc.share_pct)}</Num>,
                },
                {
                  chave: 'pr',
                  titulo: 'PR',
                  alinhar: 'dir',
                  celula: (uc) => <Num>{porcento(uc.pr_pct)}</Num>,
                },
                {
                  chave: 'disp',
                  titulo: 'Disp. real',
                  alinhar: 'dir',
                  celula: (uc) => <Num>{porcento(uc.disponibilidade_real_pct, 2)}</Num>,
                },
                {
                  chave: 'fatura',
                  titulo: 'Conta (MWh)',
                  alinhar: 'dir',
                  celula: (uc) => <Num>{numero(uc.faturado_mwh, 1)}</Num>,
                },
              ]}
              linhas={u.ucs}
              chave={(uc) => uc.indice}
            />
            {u.faturas_situacao === null ? (
              <p className="px-3 pt-2 text-xs text-fraco">
                Nenhuma fatura emitida para este período — situação normal enquanto a
                distribuidora não fecha a competência.
              </p>
            ) : null}
          </div>
        )}
      </Cartao>
    </>
  )
}
