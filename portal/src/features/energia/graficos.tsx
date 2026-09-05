/**
 * As peças de desenho do Painel de energia — e só dele.
 *
 * Elas moram AQUI, e não em `components/base.tsx`, por uma razão simples: são específicas
 * de um assunto (geração fotovoltaica) e nenhuma outra tela do portal as usa. Peça
 * compartilhada é contrato com o produto inteiro; peça de uma tela é só desta tela, e
 * mover para o vocabulário comum é decisão para quando a segunda tela precisar.
 *
 * Nada de biblioteca de gráfico: o portal não tem nenhuma no `package.json` e o desenho
 * cabe em `div` e `svg`. Nada de hexadecimal: as cores são as classes do
 * `tailwind.config.js`, e as de tom só aparecem com opacidade 10/20/30/40, que é o que a
 * `safelist` garante — fora dela a classe some do CSS sem erro nenhum de compilação.
 *
 * Duas regras herdadas de `components/base.tsx`, que valem em cada peça daqui:
 *
 * **Ponto sem leitura NÃO vira barra rasteira.** Ele fica vazio. Barra no zero se lê como
 * "a usina não gerou", que é uma afirmação diferente de "não medimos" — e é o erro mais
 * caro que este portal pode cometer.
 *
 * **O esperado é uma marca, não uma segunda barra.** A pergunta é "cheguei lá?", e duas
 * barras lado a lado transformam isso em comparação de tamanhos. O dia que ainda não
 * aconteceu é a exceção declarada: sem medição para desenhar, ele sai como o CONTORNO
 * tracejado da meta — mostra o que se espera dele sem afirmar nada sobre o que houve.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'

import { Botao, CabecalhoCard, Esqueleto, Kpi, Num } from '@/components/base'
import { energia, numero, porcento } from '@/lib/format'
import type { Leitura } from '@/lib/leitura'

/* ------------------------------------------------------------------ estados */

/**
 * Um bloco que depende da própria leitura: esqueleto, erro com "Tentar de novo", conteúdo.
 *
 * O quarto estado (offline) fica no nível da PÁGINA — quando a rede cai, cai para todas as
 * leituras ao mesmo tempo, e repetir o selo em cada cartão viraria ruído sobre o mesmo fato.
 */
export function Bloco<T>({
  leitura,
  altura = 200,
  children,
}: {
  leitura: Leitura<T>
  altura?: number
  children: (dados: T) => ReactNode
}) {
  if (leitura.carregando) return <Esqueleto altura={altura} />
  if (leitura.dados === null) {
    return (
      <div>
        <p className="text-sm text-tom-parado">
          {leitura.erro ?? 'O servidor não devolveu dados para este período.'}
        </p>
        <div className="mt-3">
          <Botao variante="secundario" onClick={leitura.recarregar}>
            Tentar de novo
          </Botao>
        </div>
      </div>
    )
  }
  return <>{children(leitura.dados)}</>
}

/**
 * Capacidade instalada — kWp abaixo de 1 MWp, MWp acima.
 *
 * `potencia()` de `lib/format` não serve: ela escreveria "3,00 MW" onde a unidade é MWp, e
 * potência instantânea e capacidade instalada são grandezas que ninguém deve confundir numa
 * tela que compara as duas lado a lado.
 */
export function capacidade(kwp: number | null): string {
  if (kwp === null) return '—'
  return kwp >= 1000 ? `${numero(kwp / 1000, 2)} MWp` : `${numero(kwp, 1)} kWp`
}

/** Frase curta para quando o bloco não tem o que desenhar. Não é erro — é ausência. */
export function SemDado({ children }: { children: ReactNode }) {
  return <p className="text-sm text-fraco">{children}</p>
}

/* ------------------------------------------------------------------ medidas */

/**
 * A largura útil do contêiner, para o SVG.
 *
 * O `svg` precisa de um número; `100%` não serve para calcular coordenada. A medida vem do
 * layout e se refaz no `resize` — sem isso o gráfico nasce com a largura da primeira
 * renderização e encolhe ou transborda quando a janela muda.
 */
export function useLargura() {
  const caixa = useRef<HTMLDivElement>(null)
  const [largura, setLargura] = useState(0)
  useEffect(() => {
    const medir = () => setLargura(caixa.current?.clientWidth ?? 0) // regra0: largura medida do layout, não dado da API
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, [])
  return { caixa, largura }
}

/** O maior valor de uma lista, ignorando o que não é número. Zero quando não há nenhum. */
function maximoDe(valores: (number | null | undefined)[]): number {
  const numeros = valores.filter((v): v is number => typeof v === 'number')
  return numeros.length > 0 ? Math.max(...numeros) : 0
}

/** Um rótulo a cada N, para o eixo não virar um borrão em séries longas. */
function passoDeRotulo(quantidade: number, cabem = 12): number {
  return Math.max(1, Math.ceil(quantidade / cabem))
}

/* ------------------------------------------------------------------ legenda */

export function Legenda({ itens }: { itens: { marca: ReactNode; texto: string }[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-fraco">
      {itens.map((i) => (
        <span key={i.texto} className="inline-flex items-center gap-1.5">
          {i.marca}
          {i.texto}
        </span>
      ))}
    </div>
  )
}

const MARCA_MEDIDO = <span className="inline-block h-2 w-3 rounded-[2px] bg-ambar" />
const MARCA_PROJETO = <span className="inline-block h-0 w-3 border-t border-dashed border-forte" />
const MARCA_FUTURO = (
  <span className="inline-block h-2.5 w-3 rounded-[2px] border border-dashed border-fraco" />
)

/* ------------------------------------------------------------------ período */

export type PontoDoPeriodo = {
  chave: string
  rotulo: string
  /** Nulo = não medimos. Fica SEM barra. */
  medido: number | null
  /** A meta do projeto para o mesmo ponto. Vira a marca tracejada. */
  projeto: number | null
  /** Dia (ou mês) que ainda não aconteceu: contorno tracejado, nunca barra no chão. */
  futuro?: boolean
}

/**
 * A série do período: medido contra a meta do projeto, ponto a ponto.
 *
 * Serve ao "geração diária" do Mês e ao "geração mensal" do Ano — é a mesma pergunta em
 * duas escalas, e duas peças diferentes divergiriam com o tempo.
 */
export function BarrasDoPeriodo({
  pontos,
  altura = 200,
  unidade = 'kWh',
  rotuloMedido = 'medido',
}: {
  pontos: PontoDoPeriodo[]
  altura?: number
  unidade?: string
  /** O que a barra representa, quando não é "medido" (a série de uma unidade, por exemplo). */
  rotuloMedido?: string
}) {
  const [marcado, setMarcado] = useState<number | null>(null)
  if (pontos.length === 0) return null

  const maximo = maximoDe(pontos.flatMap((p) => [p.medido, p.projeto]))
  const alturaDe = (v: number | null) =>
    maximo > 0 && typeof v === 'number' ? (v / maximo) * altura : 0
  const lido = marcado !== null ? pontos[marcado] : null
  const passo = passoDeRotulo(pontos.length)
  const temFuturo = pontos.some((p) => p.futuro)
  // A legenda só nomeia o que está desenhado. Anunciar "meta do projeto" onde não há meta
  // nenhuma faria o cliente procurar na tela um traço que não existe.
  const temProjeto = pontos.some((p) => typeof p.projeto === 'number')

  return (
    <div>
      <div className="mb-2 min-h-[1.25rem] text-xs text-corpo">
        {lido ? (
          <>
            {lido.rotulo} ·{' '}
            {lido.futuro ? (
              <span className="text-fraco">ainda não aconteceu</span>
            ) : (
              <>
                <Num>{numero(lido.medido, 1)}</Num> {unidade}
              </>
            )}
            {typeof lido.projeto === 'number' ? (
              <span className="text-fraco">
                {' '}
                · projeto <Num>{numero(lido.projeto, 1)}</Num>
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-fraco">passe o mouse num ponto para ver os valores</span>
        )}
      </div>

      <div className="flex items-end gap-1" style={{ height: altura }}>
        {pontos.map((p, i) => (
          <div
            key={p.chave}
            onMouseEnter={() => setMarcado(i)}
            onMouseLeave={() => setMarcado(null)}
            className="relative flex flex-1 cursor-default items-end justify-center"
            style={{ height: altura }}
          >
            {typeof p.medido === 'number' ? (
              <div
                data-testid={`barra-${p.chave}`}
                className={`w-full rounded-t-[3px] ${marcado === i ? 'bg-ambar' : 'bg-ambar/70'}`}
                style={{ height: Math.max(2, alturaDe(p.medido)) }}
              />
            ) : null}
            {/* O dia que ainda não veio: o contorno da meta, tracejado. Sem medição não há
                o que afirmar, e uma barra rasteira afirmaria "não gerou". */}
            {p.futuro && typeof p.projeto === 'number' && maximo > 0 ? (
              <div
                data-testid={`futuro-${p.chave}`}
                className="w-full rounded-t-[3px] border border-dashed border-fraco"
                style={{ height: Math.max(2, alturaDe(p.projeto)) }}
              />
            ) : null}
            {!p.futuro && typeof p.projeto === 'number' && maximo > 0 ? (
              <div
                className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-forte"
                style={{ bottom: alturaDe(p.projeto) }}
              />
            ) : null}
          </div>
        ))}
      </div>

      <div className="mt-2 flex gap-1">
        {pontos.map((p, i) => (
          <div key={`r-${p.chave}`} className="flex-1 text-center text-[10px] text-fraco">
            {i % passo === 0 ? p.rotulo : ''}
          </div>
        ))}
      </div>

      <Legenda
        itens={[
          { marca: MARCA_MEDIDO, texto: rotuloMedido },
          ...(temProjeto ? [{ marca: MARCA_PROJETO, texto: 'meta do projeto' }] : []),
          ...(temFuturo ? [{ marca: MARCA_FUTURO, texto: 'ainda não aconteceu' }] : []),
        ]}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ PR */

export type PontoPr = {
  chave: string
  rotulo: string
  /** Nulo = sem PR. NUNCA vira 0%. */
  pr: number | null
  /** O monitoramento descartou a leitura por implausibilidade. */
  descartado?: boolean
}

/**
 * O PR dia a dia, com a linha de referência do período.
 *
 * Dia sem PR fica **sem barra**, e quando o monitoramento descartou a leitura o eixo diz
 * "descartada" no lugar do valor. Desenhar 0% ali seria a afirmação mais grave que este
 * gráfico pode fazer: "a usina rendeu zero" quando o que houve foi um sensor mudo.
 */
export function BarrasPr({
  pontos,
  referencia,
  rotuloReferencia,
  altura = 180,
}: {
  pontos: PontoPr[]
  /** A régua do período — o PR do mês, vindo do servidor. Nulo = sem linha. */
  referencia: number | null
  rotuloReferencia: string
  altura?: number
}) {
  const [marcado, setMarcado] = useState<number | null>(null)
  if (pontos.length === 0) return null

  const maximo = Math.max(maximoDe([...pontos.map((p) => p.pr), referencia]), 1)
  const alturaDe = (v: number) => (v / maximo) * altura
  const lido = marcado !== null ? pontos[marcado] : null
  const passo = passoDeRotulo(pontos.length)
  const descartados = pontos.filter((p) => p.descartado).length

  return (
    <div>
      <div className="mb-2 min-h-[1.25rem] text-xs text-corpo">
        {lido ? (
          <>
            {lido.rotulo} ·{' '}
            {lido.descartado ? (
              <span className="text-tom-alerta">leitura descartada pelo monitoramento</span>
            ) : lido.pr === null ? (
              <span className="text-fraco">sem irradiação medida neste dia</span>
            ) : (
              <Num>{porcento(lido.pr)}</Num>
            )}
          </>
        ) : (
          <span className="text-fraco">passe o mouse num dia para ver o valor</span>
        )}
      </div>

      <div className="relative flex items-end gap-1" style={{ height: altura }}>
        {typeof referencia === 'number' ? (
          <div
            className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-forte"
            style={{ bottom: alturaDe(referencia) }}
          />
        ) : null}
        {pontos.map((p, i) => (
          <div
            key={p.chave}
            onMouseEnter={() => setMarcado(i)}
            onMouseLeave={() => setMarcado(null)}
            className="relative flex flex-1 cursor-default items-end justify-center"
            style={{ height: altura }}
          >
            {typeof p.pr === 'number' ? (
              <div
                data-testid={`pr-${p.chave}`}
                className={`w-full rounded-t-[3px] ${marcado === i ? 'bg-ambar' : 'bg-ambar/70'}`}
                style={{ height: Math.max(2, alturaDe(p.pr)) }}
              />
            ) : null}
          </div>
        ))}
      </div>

      <div className="mt-2 flex gap-1">
        {pontos.map((p, i) => (
          <div key={`r-${p.chave}`} className="flex-1 text-center text-[10px] text-fraco">
            {i % passo === 0 ? p.rotulo : ''}
          </div>
        ))}
      </div>

      <Legenda
        itens={[
          { marca: MARCA_MEDIDO, texto: 'PR do dia' },
          ...(typeof referencia === 'number'
            ? [{ marca: MARCA_PROJETO, texto: rotuloReferencia }]
            : []),
        ]}
      />
      {descartados > 0 ? (
        <p className="mt-1 text-[11px] text-tom-alerta">
          {descartados === 1
            ? 'Um dia teve a leitura de PR descartada pelo monitoramento e ficou sem barra.'
            : `${descartados} dias tiveram a leitura de PR descartada pelo monitoramento e ficaram sem barra.`}
        </p>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------ rosca */

/**
 * O fechamento do período em uma rosca: quanto do projeto já foi entregue.
 *
 * Sem percentual não há arco — e não há rosca vazia, que se leria como zero. O número
 * grande vem escrito de fora, formatado pelos helpers de `lib/format`.
 */
export function Rosca({
  pct,
  centro,
  detalhe,
  tamanho = 148,
}: {
  pct: number | null
  centro: string
  detalhe?: ReactNode
  tamanho?: number
}) {
  const raio = tamanho / 2 - 10
  const volta = 2 * Math.PI * raio
  const cheio = pct === null ? 0 : Math.max(0, Math.min(100, pct))
  const arco = (volta * cheio) / 100

  return (
    <div className="flex items-center gap-4">
      <svg width={tamanho} height={tamanho} role="img" aria-label={`Desempenho: ${centro}`}>
        <circle
          cx={tamanho / 2}
          cy={tamanho / 2}
          r={raio}
          className="stroke-borda-forte"
          strokeWidth={12}
          fill="none"
        />
        {pct === null ? null : (
          <circle
            cx={tamanho / 2}
            cy={tamanho / 2}
            r={raio}
            className="stroke-ambar"
            strokeWidth={12}
            strokeLinecap="round"
            fill="none"
            strokeDasharray={`${arco} ${volta}`}
            transform={`rotate(-90 ${tamanho / 2} ${tamanho / 2})`}
          />
        )}
        <text
          x={tamanho / 2}
          y={tamanho / 2 + 6}
          textAnchor="middle"
          className="fill-forte font-mono text-lg font-semibold"
        >
          {centro}
        </text>
      </svg>
      {detalhe ? <div className="min-w-0 text-xs text-fraco">{detalhe}</div> : null}
    </div>
  )
}

/* ------------------------------------------------------------------ tabela */

export type ColunaLonga<T> = {
  /** Chave própria — o TÍTULO não serve de identidade: duas colunas "Data" numa tabela
   *  produziriam chave repetida e célula trocada na re-renderização, sem erro nenhum. */
  chave: string
  titulo: string
  alinhar?: 'esq' | 'dir'
  celula: (item: T) => ReactNode
}

/**
 * A tabela longa do detalhamento, com rodapé de total.
 *
 * `components/base.tsx` já tem uma `Tabela`, e ela continua sendo a peça do produto — mas
 * não tem rodapé, e o total do período é justamente a linha que o cliente lê primeiro numa
 * tabela de doze meses.
 */
export function TabelaLonga<T>({
  colunas,
  linhas,
  chave,
  rodape,
  destacar,
}: {
  colunas: ColunaLonga<T>[]
  linhas: T[]
  chave: (item: T) => string | number
  /** Uma célula por coluna, na mesma ordem. Ausente = sem rodapé. */
  rodape?: ReactNode[]
  /** Marca a linha do período em curso, para o cliente não a ler como fechada. */
  destacar?: (item: T) => boolean
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="border-b border-borda">
            {colunas.map((c) => (
              <th
                key={c.chave}
                className={`whitespace-nowrap px-3 py-2 text-xs font-medium uppercase tracking-wide text-rotulo ${
                  c.alinhar === 'dir' ? 'text-right' : 'text-left'
                }`}
              >
                {c.titulo}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {linhas.map((item) => (
            <tr
              key={chave(item)}
              className={`border-b border-borda-fraca last:border-0 ${
                destacar?.(item) ? 'bg-superficie-alta' : ''
              }`}
            >
              {colunas.map((c) => (
                <td
                  key={c.chave}
                  className={`whitespace-nowrap px-3 py-2.5 align-middle text-corpo ${
                    c.alinhar === 'dir' ? 'text-right' : ''
                  }`}
                >
                  {c.celula(item)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {rodape ? (
          <tfoot>
            <tr className="border-t border-borda-forte">
              {colunas.map((c, i) => (
                <td
                  key={`t-${c.chave}`}
                  className={`whitespace-nowrap px-3 py-2.5 text-sm font-medium text-forte ${
                    c.alinhar === 'dir' ? 'text-right' : ''
                  }`}
                >
                  {rodape[i]}
                </td>
              ))}
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ meteo */

export type PontoDaMeteo = {
  chave: string
  rotulo: string
  hpoa: number | null
  hpoa_projeto: number | null
  ghi: number | null
  t_amb: number | null
  t_mod: number | null
}

/**
 * Irradiação e temperatura no mesmo eixo do tempo, com escalas opostas.
 *
 * Duas grandezas de ordens de grandeza diferentes: juntá-las numa escala só faria a
 * temperatura virar uma reta colada no chão. A irradiação é barra (é acúmulo), a
 * temperatura é linha (é estado), e a meta de irradiação do projeto é a marca tracejada.
 */
export function GraficoMeteo({
  pontos,
  altura = 200,
}: {
  pontos: PontoDaMeteo[]
  altura?: number
}) {
  const { caixa, largura } = useLargura()
  const [marcado, setMarcado] = useState<number | null>(null)
  if (pontos.length === 0) return null

  const irradiacaoMax = Math.max(
    maximoDe(pontos.flatMap((p) => [p.hpoa, p.ghi, p.hpoa_projeto])),
    0.001,
  )
  const temperaturas = pontos.flatMap((p) => [p.t_amb, p.t_mod])
  const temTemperatura = temperaturas.some((v) => typeof v === 'number')
  const tempMax = Math.max(maximoDe(temperaturas), 1)

  const largo = largura > 0 ? largura : 0
  const passoX = pontos.length > 0 ? largo / pontos.length : 0
  const centroX = (i: number) => passoX * i + passoX / 2
  const yIrradiacao = (v: number) => altura - (v / irradiacaoMax) * altura
  const yTemperatura = (v: number) => altura - (v / tempMax) * altura
  const passo = passoDeRotulo(pontos.length)
  const lido = marcado !== null ? pontos[marcado] : null

  // Lacuna: a linha PARA e recomeça. Ligar os dois lados desenharia uma reta atravessando
  // o buraco, que é interpolação inventada — proibida pela REGRA 0.
  const caminho = (pega: (p: PontoDaMeteo) => number | null) => {
    let d = ''
    let aberto = false
    pontos.forEach((p, i) => {
      const v = pega(p)
      if (typeof v !== 'number') {
        aberto = false
        return
      }
      d += `${aberto ? 'L' : 'M'}${centroX(i)} ${yTemperatura(v)} `
      aberto = true
    })
    return d.trim()
  }

  return (
    <div>
      <div className="mb-2 min-h-[1.25rem] text-xs text-corpo">
        {lido ? (
          <>
            {lido.rotulo} · HPOA <Num>{numero(lido.hpoa, 2)}</Num> kWh/m²
            {typeof lido.ghi === 'number' ? (
              <span className="text-fraco">
                {' '}
                · GHI <Num>{numero(lido.ghi, 2)}</Num>
              </span>
            ) : null}
            {typeof lido.t_amb === 'number' ? (
              <span className="text-fraco">
                {' '}
                · ambiente <Num>{numero(lido.t_amb, 1)}</Num> °C
              </span>
            ) : null}
            {typeof lido.t_mod === 'number' ? (
              <span className="text-fraco">
                {' '}
                · módulo <Num>{numero(lido.t_mod, 1)}</Num> °C
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-fraco">passe o mouse num ponto para ver as condições</span>
        )}
      </div>

      <div className="flex gap-2">
        <div className="flex w-12 flex-col justify-between text-right" style={{ height: altura }}>
          {[1, 0.75, 0.5, 0.25, 0].map((f) => (
            <Num key={`i-${f}`} className="text-[10px] text-fraco">
              {numero(irradiacaoMax * f, 1)}
            </Num>
          ))}
        </div>

        <div ref={caixa} className="relative flex-1" style={{ height: altura }}>
          {largo > 0 ? (
            <svg width={largo} height={altura}>
              {[0, 0.25, 0.5, 0.75, 1].map((f) => (
                <line
                  key={`g-${f}`}
                  x1={0}
                  y1={altura - f * altura}
                  x2={largo}
                  y2={altura - f * altura}
                  className="stroke-borda-fraca"
                  strokeWidth={0.5}
                />
              ))}
              {pontos.map((p, i) => (
                <g key={p.chave} onMouseEnter={() => setMarcado(i)} onMouseLeave={() => setMarcado(null)}>
                  <rect
                    x={passoX * i}
                    y={0}
                    width={Math.max(1, passoX)}
                    height={altura}
                    className="fill-transparent"
                  />
                  {typeof p.hpoa === 'number' ? (
                    <rect
                      x={passoX * i + passoX * 0.2}
                      y={yIrradiacao(p.hpoa)}
                      width={Math.max(1, passoX * 0.6)}
                      height={altura - yIrradiacao(p.hpoa)}
                      className={marcado === i ? 'fill-ambar' : 'fill-ambar/70'}
                    />
                  ) : null}
                  {typeof p.hpoa_projeto === 'number' ? (
                    <line
                      x1={passoX * i + passoX * 0.1}
                      y1={yIrradiacao(p.hpoa_projeto)}
                      x2={passoX * i + passoX * 0.9}
                      y2={yIrradiacao(p.hpoa_projeto)}
                      className="stroke-forte"
                      strokeWidth={1}
                      strokeDasharray="3 3"
                    />
                  ) : null}
                </g>
              ))}
              {temTemperatura ? (
                <>
                  <path
                    d={caminho((p) => p.t_amb)}
                    className="stroke-tom-tempoRuim"
                    strokeWidth={1.5}
                    fill="none"
                  />
                  <path
                    d={caminho((p) => p.t_mod)}
                    className="stroke-tom-multiplos"
                    strokeWidth={1.5}
                    fill="none"
                  />
                </>
              ) : null}
            </svg>
          ) : null}
        </div>

        {temTemperatura ? (
          <div className="flex w-10 flex-col justify-between" style={{ height: altura }}>
            {[1, 0.75, 0.5, 0.25, 0].map((f) => (
              <Num key={`t-${f}`} className="text-[10px] text-fraco">
                {numero(tempMax * f, 0)}
              </Num>
            ))}
          </div>
        ) : null}
      </div>

      <div className="mt-2 flex gap-0" style={{ paddingLeft: 56 }}>
        {pontos.map((p, i) => (
          <div key={`r-${p.chave}`} className="flex-1 text-center text-[10px] text-fraco">
            {i % passo === 0 ? p.rotulo : ''}
          </div>
        ))}
      </div>

      <Legenda
        itens={[
          { marca: MARCA_MEDIDO, texto: 'HPOA medida (kWh/m², esquerda)' },
          { marca: MARCA_PROJETO, texto: 'HPOA do projeto' },
          ...(temTemperatura
            ? [
                {
                  marca: <span className="inline-block h-0 w-3 border-t-2 border-tom-tempoRuim" />,
                  texto: 'temperatura ambiente (°C, direita)',
                },
                {
                  marca: <span className="inline-block h-0 w-3 border-t-2 border-tom-multiplos" />,
                  texto: 'temperatura do módulo (°C, direita)',
                },
              ]
            : []),
        ]}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ timeline */

/**
 * A cor de cada estado do inversor. As classes estão escritas por extenso de propósito: o
 * Tailwind precisa enxergar a string no fonte, e a `safelist` só cobre as opacidades
 * 10/20/30/40 — uma classe montada com `/60` compilaria e sairia sem cor nenhuma.
 */
const CLASSE_DO_ESTADO: Record<string, string> = {
  operando: 'bg-tom-ok',
  potencia_zero: 'bg-tom-parado',
  falha_comunicacao: 'bg-tom-multiplos',
  nao_instalado: 'bg-tom-semDados/20',
  sem_dado: 'bg-tom-semDados/40',
}

const NOME_DO_ESTADO: Record<string, string> = {
  operando: 'Operando',
  potencia_zero: 'Sem produção',
  falha_comunicacao: 'Falha de comunicação',
  nao_instalado: 'Não instalado',
  sem_dado: 'Sem dado',
}

export type LinhaDaTimeline = {
  nome: string
  disponibilidade_pct: number | null
  faixas: { de: string; ate: string; dias: number; estado: string }[]
}

/**
 * Tempo de pé, inversor por inversor, ao longo do período.
 *
 * Cada faixa é um trecho contínuo no mesmo estado — é assim que a resposta vem do BFF, e é
 * também a forma que a barra precisa: ela pinta trechos, não pontos. A largura de cada
 * faixa é a fração de dias que ela cobre, então a linha inteira soma sempre 100% do período.
 */
export function LinhaDoTempo({ inversores }: { inversores: LinhaDaTimeline[] }) {
  if (inversores.length === 0) return null
  const estadosUsados = Array.from(
    new Set(inversores.flatMap((i) => i.faixas.map((f) => f.estado))),
  )

  return (
    <div>
      <div className="space-y-1.5">
        {inversores.map((inv) => {
          const total = inv.faixas.reduce((soma, f) => soma + f.dias, 0)
          return (
            <div key={inv.nome} className="flex items-center gap-3">
              <span className="w-28 shrink-0 truncate text-xs text-corpo" title={inv.nome}>
                {inv.nome}
              </span>
              <div className="flex h-4 flex-1 overflow-hidden rounded-barra bg-afundado">
                {inv.faixas.map((f) => (
                  <div
                    key={`${inv.nome}-${f.de}`}
                    title={`${NOME_DO_ESTADO[f.estado] ?? f.estado} · ${f.de} a ${f.ate}`}
                    className={CLASSE_DO_ESTADO[f.estado] ?? CLASSE_DO_ESTADO.sem_dado}
                    style={{ width: total > 0 ? `${(f.dias / total) * 100}%` : '0%' }}
                  />
                ))}
              </div>
              <Num className="w-16 shrink-0 text-right text-xs text-corpo">
                {porcento(inv.disponibilidade_pct)}
              </Num>
            </div>
          )
        })}
      </div>

      <Legenda
        itens={estadosUsados.map((e) => ({
          marca: (
            <span
              className={`inline-block h-2.5 w-3 rounded-[2px] ${
                CLASSE_DO_ESTADO[e] ?? CLASSE_DO_ESTADO.sem_dado
              }`}
            />
          ),
          texto: NOME_DO_ESTADO[e] ?? e,
        }))}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ arco */

/** Um arco de disponibilidade por unidade consumidora. Sem percentual, não há arco. */
export function Arco({ pct, rotulo }: { pct: number | null; rotulo: string }) {
  const tamanho = 92
  const raio = tamanho / 2 - 8
  const meia = Math.PI * raio
  const cheio = pct === null ? 0 : Math.max(0, Math.min(100, pct))
  const arco = (meia * cheio) / 100
  const cx = tamanho / 2
  const cy = tamanho / 2 + 12

  return (
    <div className="flex flex-col items-center">
      <svg width={tamanho} height={tamanho * 0.7} role="img" aria-label={`${rotulo}: ${porcento(pct)}`}>
        <path
          d={`M${cx - raio} ${cy} A${raio} ${raio} 0 0 1 ${cx + raio} ${cy}`}
          className="stroke-borda-forte"
          strokeWidth={8}
          fill="none"
        />
        {pct === null ? null : (
          <path
            d={`M${cx - raio} ${cy} A${raio} ${raio} 0 0 1 ${cx + raio} ${cy}`}
            className="stroke-ambar"
            strokeWidth={8}
            strokeLinecap="round"
            fill="none"
            strokeDasharray={`${arco} ${meia}`}
          />
        )}
      </svg>
      <Num className="-mt-3 text-sm font-semibold text-forte">{porcento(pct)}</Num>
      <span className="mt-0.5 max-w-[7rem] truncate text-center text-[11px] text-fraco" title={rotulo}>
        {rotulo}
      </span>
    </div>
  )
}

/* ------------------------------------------------------------------ faísca */

/**
 * O traço do dia de uma unidade consumidora.
 *
 * Lacuna continua lacuna: a fatia em que a UC não reportou não recebe traço, e a linha
 * recomeça depois dela.
 */
export function Faisca({
  valores,
  largura = 120,
  altura = 26,
}: {
  valores: (number | null)[]
  largura?: number
  altura?: number
}) {
  const numeros = valores.filter((v): v is number => typeof v === 'number')
  if (numeros.length < 2) return <span className="text-xs text-fraco">—</span>
  const maximo = Math.max(...numeros, 0.001)
  const passoX = valores.length > 1 ? largura / (valores.length - 1) : largura

  let d = ''
  let aberto = false
  valores.forEach((v, i) => {
    if (typeof v !== 'number') {
      aberto = false
      return
    }
    d += `${aberto ? 'L' : 'M'}${passoX * i} ${altura - (v / maximo) * altura} `
    aberto = true
  })

  return (
    <svg width={largura} height={altura} aria-hidden>
      <path d={d.trim()} className="stroke-ambar" strokeWidth={1.5} fill="none" />
    </svg>
  )
}

/* ------------------------------------------------------------------ ranking */

export type ItemDoRanking = {
  chave: string
  nome: string
  /** Nulo = sem medida. A linha aparece, com travessão e sem barra — sumir com ela faria o
   *  cliente concluir que a UC não existe. */
  valor: number | null
  texto: string
}

export function RankingBarras({
  itens,
  referencia,
  rotuloReferencia,
}: {
  itens: ItemDoRanking[]
  /** Uma régua de mercado, quando existe (a linha de 80% do PR). */
  referencia?: number | null
  rotuloReferencia?: string
}) {
  if (itens.length === 0) return null
  const maximo = Math.max(maximoDe([...itens.map((i) => i.valor), referencia]), 0.001)

  return (
    <div className="space-y-2">
      {itens.map((i) => (
        <div key={i.chave} className="flex items-center gap-3">
          <span className="w-28 shrink-0 truncate text-xs text-corpo" title={i.nome}>
            {i.nome}
          </span>
          <div className="relative h-3 flex-1 overflow-hidden rounded-barra bg-afundado">
            {typeof i.valor === 'number' ? (
              <div
                className="h-full rounded-barra bg-ambar/70"
                style={{ width: `${Math.max(0, Math.min(100, (i.valor / maximo) * 100))}%` }}
              />
            ) : null}
            {typeof referencia === 'number' ? (
              <div
                className="absolute inset-y-0 border-l border-dashed border-forte"
                style={{ left: `${Math.max(0, Math.min(100, (referencia / maximo) * 100))}%` }}
              />
            ) : null}
          </div>
          <Num className="w-24 shrink-0 text-right text-xs text-corpo">{i.texto}</Num>
        </div>
      ))}
      {typeof referencia === 'number' && rotuloReferencia ? (
        <Legenda itens={[{ marca: MARCA_PROJETO, texto: rotuloReferencia }]} />
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------ composições */
/*
 * Daqui para baixo não são mais peças de desenho, e sim os BLOCOS que o Mês e o Ano
 * mostram iguais: as fórmulas, os desvios, a conciliação com a conta de energia e a
 * meteorologia. Ficam juntos porque a alternativa era copiá-los nos dois arquivos — e
 * cópia de bloco é como o mesmo número acaba escrito de dois jeitos na mesma tela.
 */

/**
 * Percentual COM SINAL — "+3,2%", "−1,5%".
 *
 * O sinal é a informação: o servidor manda o desvio como `(aferido − referência) ÷
 * referência`, então positivo é acima da meta. Sem o "+" explícito, quem lê "3,2%" não sabe
 * de que lado está.
 *
 * O sinal negativo usa o traço de menos (U+2212), não o hífen: com fonte tabular o hífen
 * fica curto demais e a coluna de números perde o alinhamento óptico.
 */
export function comSinal(valor: number | null, casas = 1): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return '—'
  if (valor < 0) return `−${numero(Math.abs(valor), casas)}%`
  return `+${numero(valor, casas)}%`
}

/**
 * As fórmulas, escritas pelo servidor, em linguagem de cliente.
 *
 * Não é decoração: é o que sustenta o número contratual. Um percentual de disponibilidade
 * sem a fórmula ao lado é um número que o cliente não tem como conferir — e é justamente o
 * número que ele leva para a reunião.
 */
export function CartaoRegra({
  regra,
  perdida,
  perdidaExterna,
}: {
  regra: { disponibilidade: string; contratual: string; perda_distribuida: string; origem: string }
  perdida: number | null
  perdidaExterna: number | null
}) {
  return (
    <div className="rounded-card border border-borda-fraca bg-afundado p-4">
      <div className="grid gap-4 text-sm text-corpo md:grid-cols-2">
        <div className="space-y-2">
          <p>{regra.disponibilidade}</p>
          <p>{regra.contratual}</p>
        </div>
        <div className="space-y-2">
          <p>{regra.perda_distribuida}</p>
          <p className="text-fraco">{regra.origem}</p>
        </div>
      </div>
      <p className="mt-3 border-t border-borda-fraca pt-3 text-xs text-fraco">
        Energia perdida no período: <Num>{energia(perdida)}</Num> · por causa externa:{' '}
        <Num>{energia(perdidaExterna)}</Num>
      </p>
    </div>
  )
}

/**
 * Os desvios estruturais do período, com sinal: três de ENERGIA e dois de IRRADIAÇÃO.
 *
 * Os de irradiação são o que separa "o sol não veio" de "a usina não rendeu" — sem eles,
 * um mês fraco tem duas explicações possíveis e nenhuma escrita. Só aparecem quando a
 * usina tem irradiação de projeto cadastrada; sem ela, a linha some inteira, em vez de
 * mostrar um travessão que ninguém sabe ler.
 */
export function CartaoDesvios({
  desvios,
}: {
  desvios: {
    medido_vs_projeto_pct: number | null
    medido_vs_previsto_pct: number | null
    previsto_vs_projeto_pct: number | null
    hpoa_vs_projeto_pct: number | null
    ghi_vs_projeto_pct: number | null
  }
}) {
  const linhas = [
    {
      chave: 'projeto',
      titulo: 'Medido × projeto',
      detalhe: 'quanto a usina ficou acima ou abaixo da meta do PVsyst',
      valor: desvios.medido_vs_projeto_pct,
    },
    {
      chave: 'previsto',
      titulo: 'Medido × previsto pela irradiação',
      detalhe: 'quanto a usina rendeu diante do sol que realmente houve',
      valor: desvios.medido_vs_previsto_pct,
    },
    {
      chave: 'clima',
      titulo: 'Previsto × projeto',
      detalhe: 'o efeito do clima — sol acima ou abaixo do que o projeto supôs',
      valor: desvios.previsto_vs_projeto_pct,
    },
    ...(desvios.hpoa_vs_projeto_pct === null
      ? []
      : [
          {
            chave: 'hpoa',
            titulo: 'Sol medido × projeto (plano dos módulos)',
            detalhe: 'quanta irradiação chegou de fato, contra a que o projeto supôs',
            valor: desvios.hpoa_vs_projeto_pct,
          },
        ]),
    ...(desvios.ghi_vs_projeto_pct === null
      ? []
      : [
          {
            chave: 'ghi',
            titulo: 'Sol medido × projeto (plano horizontal)',
            detalhe: 'a mesma comparação no plano horizontal, como o projeto a declara',
            valor: desvios.ghi_vs_projeto_pct,
          },
        ]),
  ]

  return (
    <div className="divide-y divide-borda-fraca">
      {linhas.map((l) => (
        <div key={l.chave} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
          <span className="min-w-0">
            <span className="block text-sm text-corpo">{l.titulo}</span>
            <span className="block text-xs text-fraco">{l.detalhe}</span>
          </span>
          {/* Sem cor de propósito: o servidor não classifica desvio, e um limiar inventado
              aqui pintaria de vermelho uma usina que o contrato considera em dia. O sinal
              já diz o lado. */}
          <Num className="ml-auto text-lg font-semibold text-forte">{comSinal(l.valor)}</Num>
        </div>
      ))}
    </div>
  )
}

/**
 * O tom da conciliação.
 *
 * O vocabulário é fechado e pertence ao SERVIDOR; aqui só se escolhe a cor de cada um dos
 * três valores possíveis. Valor desconhecido cai em `semDados` — a ausência de cor, nunca
 * uma cor errada, que é a mesma regra de `lib/tons`.
 */
export function tomDaConciliacao(situacao: string | null): string {
  if (situacao === 'Conciliado') return 'ok'
  if (situacao === 'Pequena divergência') return 'alerta'
  if (situacao === 'Divergência relevante') return 'parado'
  return 'semDados'
}

/* ------------------------------------------------------------------ meteo */

/**
 * As condições do período: números em cima, gráfico embaixo.
 *
 * Sem estação solarimétrica o bloco inteiro não aparece — quatro travessões em fila não
 * informam nada e ainda ocupam o lugar do que informa.
 */
export function BlocoMeteo({
  meteo,
  rotuloDoGrafico,
}: {
  meteo: {
    tem_estacao: boolean
    tem_sensor_temperatura: boolean
    hpoa: number | null
    ghi: number | null
    razao: number | null
    hpoa_projeto: number | null
    ghi_projeto: number | null
    t_amb_media: number | null
    t_amb_max: number | null
    t_mod_media: number | null
    t_mod_max: number | null
    pontos: PontoDaMeteo[]
  }
  rotuloDoGrafico: string
}) {
  if (!meteo.tem_estacao) return null
  return (
    <>
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          rotulo="HPOA (plano dos módulos)"
          valor={`${numero(meteo.hpoa, 1)} kWh/m²`}
          detalhe={
            meteo.hpoa_projeto === null ? undefined : (
              <>
                projeto <Num>{numero(meteo.hpoa_projeto, 1)}</Num> kWh/m²
              </>
            )
          }
        />
        <Kpi
          rotulo="GHI (plano horizontal)"
          valor={`${numero(meteo.ghi, 1)} kWh/m²`}
          detalhe={
            // O projeto, quando existe, é a comparação que importa; a razão entre os planos
            // é curiosidade útil e fica como segunda opção.
            meteo.ghi_projeto !== null ? (
              <>
                projeto <Num>{numero(meteo.ghi_projeto, 1)}</Num> kWh/m²
              </>
            ) : meteo.razao === null ? undefined : (
              <>
                o plano inclinado ganha <Num>{numero(meteo.razao, 2)}</Num>×
              </>
            )
          }
        />
        {meteo.tem_sensor_temperatura ? (
          <>
            {/* Um dos dois sensores pode faltar sozinho — e falta mesmo: em Porto Ferreira
                o relé de ambiente só devolve o valor de fábrica (o servidor descarta a
                série inteira e manda nulo) enquanto o do módulo mede. Sem este ramo, o
                card sairia "— °C" ao lado de um número, que parece defeito da tela; com
                ele, diz o que houve. */}
            <Kpi
              rotulo="Temperatura ambiente"
              valor={
                meteo.t_amb_media === null ? 'sem leitura' : `${numero(meteo.t_amb_media, 1)} °C`
              }
              detalhe={
                meteo.t_amb_media === null ? (
                  'o sensor de ambiente não mediu no período'
                ) : meteo.t_amb_max === null ? undefined : (
                  <>
                    máxima <Num>{numero(meteo.t_amb_max, 1)}</Num> °C
                  </>
                )
              }
            />
            <Kpi
              rotulo="Temperatura do módulo"
              valor={
                meteo.t_mod_media === null ? 'sem leitura' : `${numero(meteo.t_mod_media, 1)} °C`
              }
              detalhe={
                meteo.t_mod_media === null ? (
                  'o sensor do módulo não mediu no período'
                ) : meteo.t_mod_max === null ? undefined : (
                  <>
                    máxima <Num>{numero(meteo.t_mod_max, 1)}</Num> °C
                  </>
                )
              }
            />
          </>
        ) : (
          <div className="sm:col-span-2">
            <p className="text-sm text-fraco">
              Esta usina não tem sensor de temperatura — só a irradiação é medida.
            </p>
          </div>
        )}
      </div>

      {meteo.pontos.length > 0 ? (
        <div className="mt-5">
          <CabecalhoCard rotulo={rotuloDoGrafico} />
          <GraficoMeteo pontos={meteo.pontos} />
        </div>
      ) : null}
    </>
  )
}
