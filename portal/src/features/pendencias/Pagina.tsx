/**
 * Pendências — a pendência que eu cobrei está andando?
 *
 * UMA pergunta, e a resposta cabe numa linha por pendência: em que etapa está, se o prazo
 * venceu e quando mexeram por último. O detalhe (o que a equipe respondeu, o que publicou e
 * que ordem de serviço resolve) abre na gaveta, sem tirar o cliente da lista.
 *
 * ## O que mudou, e por quê
 *
 * O dono, vendo esta tela: *"coloque FILTROS, coloque versão KANBAN, veja como está no
 * meuPlano — da forma que você fez está muito simples"*. Ele estava certo pelo número: eram
 * **18 linhas sem um único filtro, 15 delas concluídas** — 83 % da tela era histórico, e não
 * havia como perguntar "o que está vencido?". Os campos já vinham do servidor; faltava a
 * ferramenta.
 *
 * **Os seis cortes** vivem em `Filtros.tsx`, o **quadro** em `Kanban.tsx`, e nenhum dos dois
 * refaz conta: cor, frase, coluna e escala de criticidade continuam vindo do BFF. A gaveta
 * (`Drawer.tsx`) não foi tocada — a lista e o quadro abrem a MESMA, pela mesma rota.
 *
 * **A lista e o quadro mostram exatamente o mesmo conjunto.** Alternar a vista muda como se
 * vê, nunca o que se vê; os filtros valem nas duas. Vista e filtros viajam na URL, então o
 * endereço que o cliente copia abre no destinatário a tela que ele estava olhando.
 *
 * **O segmento "Cobradas por mim" ficou, mas deixou de ser o padrão.** Ele existia porque a
 * tela não tinha outro corte e 18 linhas cruas eram ilegíveis; hoje quem faz esse serviço é
 * "Em aberto", que é a pergunta real. Abrir com dois recortes empilhados mostraria um punhado
 * de linhas sem explicar por quê — e o cliente leria "quase não há pendência" quando o que há
 * é um filtro duplo. Continua a um clique, e a tarja diz quando está ligado.
 *
 * **Os quatro cartões do topo descrevem o conjunto inteiro, e agora dizem isso por escrito.**
 * São contagem do servidor sobre tudo o que está compartilhado; se encolhessem junto com o
 * filtro, "Prazo vencido: 0" passaria a significar "nenhuma vencida NESTE recorte" — que é
 * outra frase, e a mais perigosa das duas.
 */

import { useMemo } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import {
  Aviso,
  Botao,
  CabecalhoCard,
  Cartao,
  Esqueleto,
  Kpi,
  Num,
  Pagina,
  Segmentado,
  Selo,
  Tabela,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { dataCurta, inteiro, quando } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import { Drawer } from '@/features/pendencias/Drawer'
import {
  BarraDeFiltros,
  aplicar,
  cortesLigados,
  filtrosDaVista,
  escreverFiltros,
  lerFiltrosDaUrl,
  semCorte,
  type Filtros,
  type Segmento,
  type Vista,
} from '@/features/pendencias/Filtros'
import { Kanban } from '@/features/pendencias/Kanban'
import {
  caminhoDaLista,
  rotuloDaCriticidade,
  type Pendencia,
  type PendenciasOut,
} from '@/features/pendencias/api'

const VISTAS: { valor: Vista; rotulo: string }[] = [
  { valor: 'lista', rotulo: 'Lista' },
  { valor: 'kanban', rotulo: 'Quadro' },
]

/** As chaves que "Limpar filtros" apaga da URL. */
const CHAVES_DE_FILTRO = [
  'situacao',
  'prazo',
  'usina',
  'criticidade',
  'parada',
  'busca',
  'cobranca',
]

function EsqueletoDaLista() {
  return (
    <div className="space-y-4">
      <Cartao>
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="space-y-2">
              <Esqueleto altura={10} largura="60%" />
              <Esqueleto altura={24} largura="40%" />
            </div>
          ))}
        </div>
      </Cartao>
      <Cartao>
        <div className="space-y-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <Esqueleto key={i} altura={14} />
          ))}
        </div>
      </Cartao>
    </div>
  )
}

function Contadores({ dados }: { dados: PendenciasOut }) {
  return (
    <Cartao>
      <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
        <Kpi rotulo="Abertas" valor={inteiro(dados.abertas)} />
        <Kpi
          rotulo="Prazo vencido"
          valor={inteiro(dados.prazo_vencido)}
          // O tom só entra quando há de fato prazo vencido: pintar um zero de vermelho
          // ensina o cliente a ignorar a cor.
          tom={dados.prazo_vencido !== null && dados.prazo_vencido > 0 ? 'parado' : undefined}
        />
        <Kpi rotulo="Concluídas" valor={inteiro(dados.concluidas)} />
        <Kpi rotulo="Total compartilhado" valor={inteiro(dados.total)} />
      </div>
      {/* Dito por escrito, e não deduzido do fato de os números não se mexerem: quem filtra
          e vê o cartão parado precisa saber que é assim de propósito. */}
      <p className="mt-4 text-xs text-fraco">
        Estes quatro números descrevem TODAS as pendências compartilhadas com você — os
        filtros abaixo recortam a lista, não os cartões.
      </p>
    </Cartao>
  )
}

/** A tarja: quantas linhas de quantas, por quais cortes, e como desligar tudo. */
function Tarja({
  mostrando,
  total,
  cortes,
  aoLimpar,
}: {
  mostrando: number
  total: number
  cortes: string[]
  aoLimpar: () => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-borda bg-afundado px-4 py-2.5 text-sm">
      <span className="text-corpo">
        Mostrando <Num className="text-forte">{inteiro(mostrando)}</Num> de{' '}
        <Num className="text-forte">{inteiro(total)}</Num>
        {cortes.length > 0 ? <span className="text-fraco"> · {cortes.join(' · ')}</span> : null}
      </span>
      <Botao variante="discreto" onClick={aoLimpar}>
        Limpar filtros
      </Botao>
    </div>
  )
}

function Lista({ linhas, aoAbrir }: { linhas: Pendencia[]; aoAbrir: (p: Pendencia) => void }) {
  const colunas = [
    {
      titulo: 'Nº',
      celula: (p: Pendencia) => (
        // Identificador não leva separador de milhar: "#1.042" não é o nome que a equipe e o
        // cliente usam para se referir à pendência.
        <Num className="text-fraco">{p.numero === null ? '—' : `#${p.numero}`}</Num>
      ),
    },
    {
      titulo: 'Pendência',
      celula: (p: Pendencia) => (
        // `max-w` porque a tabela cresce até caber o conteúdo: sem teto, um título longo
        // esticaria a linha inteira e devolveria a rolagem que ninguém pediu.
        <span className="block min-w-0 max-w-[24rem]">
          <span className="block truncate font-medium text-forte" title={p.titulo}>
            {p.titulo}
          </span>
          {p.equipamento ? (
            <span className="block truncate text-xs text-fraco" title={p.equipamento}>
              {p.equipamento}
              {p.equip_count !== null && p.equip_count > 1 ? ` +${inteiro(p.equip_count - 1)}` : ''}
            </span>
          ) : null}
          {p.cobrada_pelo_cliente ? (
            <span className="block text-xs text-fraco">cobrada por você</span>
          ) : null}
        </span>
      ),
    },
    {
      titulo: 'Etapa',
      celula: (p: Pendencia) => <span className="text-fraco">{p.etapa ?? '—'}</span>,
    },
    { titulo: 'Situação', celula: (p: Pendencia) => <Selo tom={p.tom}>{p.situacao}</Selo> },
    {
      titulo: 'Criticidade',
      celula: (p: Pendencia) => {
        const rotulo = rotuloDaCriticidade(p.criticidade)
        if (!rotulo || !p.criticidade_tom) return <span className="text-fraco">—</span>
        return <Selo tom={p.criticidade_tom}>{rotulo}</Selo>
      },
    },
    {
      titulo: 'Prazo',
      celula: (p: Pendencia) => (
        // Vermelho só quando o SERVIDOR diz que venceu (`tom = 'parado'` já embute "e não
        // concluiu"). Uma pendência concluída depois do prazo não é cobrança pendente.
        <Num className={p.tom === 'parado' ? 'text-tom-parado' : 'text-corpo'}>
          {dataCurta(p.prazo)}
        </Num>
      ),
    },
    {
      titulo: 'Última atividade',
      alinhar: 'dir' as const,
      celula: (p: Pendencia) => (
        <span className="text-fraco">{quando(p.ultima_atividade_em ?? p.aberta_em)}</span>
      ),
    },
  ]

  return (
    <Cartao semPadding>
      <div className="px-2 py-3">
        <Tabela colunas={colunas} linhas={linhas} chave={(p) => p.id} aoClicar={aoAbrir} />
      </div>
    </Cartao>
  )
}

/**
 * O recorte ficou vazio — e a tela DIZ o que aconteceu, em vez de emudecer.
 *
 * A frase muda com o corte que está ligado: "em aberto" com tudo concluído é uma boa
 * notícia, e sair na mesma cor apagada de "nada encontrado" desperdiça a única coisa que o
 * cliente queria saber.
 */
function RecorteVazio({
  filtros,
  total,
  aoLimpar,
}: {
  filtros: Filtros
  total: number
  aoLimpar: () => void
}) {
  const soEmAberto =
    filtros.situacao === 'abertas' &&
    filtros.prazo === 'todos' &&
    filtros.usina === 'todas' &&
    filtros.criticidade === 'todas' &&
    filtros.parada === 'todas' &&
    filtros.busca.trim() === '' &&
    filtros.segmento === 'todas'

  return (
    <Vazio
      tom={soEmAberto ? 'ok' : undefined}
      titulo={
        soEmAberto ? 'Nenhuma pendência em aberto' : 'Nenhuma pendência com os filtros escolhidos'
      }
      descricao={
        soEmAberto
          ? `Tudo o que está compartilhado com você já foi concluído — são ${inteiro(total)} no histórico.`
          : `Há ${inteiro(total)} pendência(s) compartilhada(s) aqui; nenhuma delas passa por este recorte.`
      }
      acao={
        <Botao variante="secundario" onClick={aoLimpar}>
          {soEmAberto ? `Ver as ${inteiro(total)} compartilhadas` : 'Limpar filtros'}
        </Botao>
      }
    />
  )
}

export default function Pendencias() {
  const { id, cid } = useParams<{ id: string; cid?: string }>()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const usinaId = Number(id)
  const usinaValida = Number.isFinite(usinaId) && usinaId > 0
  const leitura = useLeitura<PendenciasOut>(caminhoDaLista(usinaId), { ativo: usinaValida })

  const aberta = cid ? Number(cid) : null
  const base = `/usinas/${usinaId}/manutencao/pendencias`

  const pedidos = useMemo(() => lerFiltrosDaUrl(params), [params])
  const vista: Vista = params.get('vista') === 'kanban' ? 'kanban' : 'lista'
  // No quadro a situação é o EIXO DAS COLUNAS, não um corte: mantê-la ligada esvaziaria por
  // construção as colunas não escolhidas — foi assim que o Quadro abriu com duas das três
  // dizendo "Nenhuma aqui" com CONCLUÍDAS 15 no cartão logo acima. O filtro pedido continua
  // guardado na URL (`pedidos`), para voltar inteiro ao trocar de volta para a lista.
  const filtros = useMemo(() => filtrosDaVista(pedidos, vista), [pedidos, vista])

  // Ajustar um filtro é refinar a MESMA pergunta: com `push`, seis cliques de refino
  // deixariam o botão Voltar inútil. Trocar de VISTA é navegação, e o Voltar a desfaz.
  const definirFiltros = (novo: Filtros) =>
    setParams(escreverFiltros(params, { ...pedidos, ...novo }), { replace: true })

  const definirVista = (v: Vista) => {
    const p = new URLSearchParams(params)
    if (v === 'lista') p.delete('vista')
    else p.set('vista', v)
    setParams(p)
  }

  const limpar = () => {
    const p = new URLSearchParams(params)
    for (const c of CHAVES_DE_FILTRO) p.delete(c)
    // "Limpar" é limpar mesmo: sem esta linha o padrão "Em aberto" voltaria e o cliente veria
    // a lista continuar recortada logo depois de mandar tirar os filtros.
    p.set('situacao', 'todas')
    setParams(p, { replace: true })
  }

  if (!usinaValida) {
    return (
      <Pagina titulo="Pendências" subtitulo="A pendência que eu cobrei está andando?">
        <Vazio
          titulo="Usina não encontrada"
          descricao="O endereço não aponta para uma usina válida. Escolha uma usina na barra do topo."
        />
      </Pagina>
    )
  }

  return (
    <Pagina
      titulo="Pendências"
      subtitulo="A pendência que eu cobrei está andando?"
      acoes={<Segmentado opcoes={VISTAS} valor={vista} onEscolher={definirVista} />}
    >
      <Tela4Estados leitura={leitura} esqueleto={<EsqueletoDaLista />}>
        {(dados) => {
          const todas = dados.pendencias
          const linhas = aplicar(todas, filtros)
          const cortes = cortesLigados(filtros, todas)
          const abrir = (p: Pendencia) => navigate(`${base}/${p.id}`)

          return (
            <div className="space-y-4">
              {/* O aviso do servidor (usina sem o lado da manutenção, consulta que falhou)
                  fica acima dos números: sem ele, contador nulo pareceria tela quebrada. */}
              {dados.aviso && todas.length > 0 ? <Aviso>{dados.aviso}</Aviso> : null}

              <Contadores dados={dados} />

              {todas.length === 0 ? (
                <Vazio
                  titulo="Nenhuma pendência compartilhada nesta usina"
                  descricao={
                    dados.aviso ??
                    'Quando a equipe compartilhar uma pendência desta usina, ela aparece aqui.'
                  }
                />
              ) : (
                <>
                  <Cartao>
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                      <CabecalhoCard rotulo="Filtrar" className="mb-0" />
                      <Segmentado
                        opcoes={[
                          {
                            valor: 'cobradas' as Segmento,
                            rotulo:
                              dados.cobradas_abertas === null
                                ? 'Cobradas por mim'
                                : `Cobradas por mim (${inteiro(dados.cobradas_abertas)} abertas)`,
                          },
                          { valor: 'todas' as Segmento, rotulo: 'Todas as compartilhadas' },
                        ]}
                        valor={filtros.segmento}
                        onEscolher={(v) => definirFiltros({ ...filtros, segmento: v })}
                      />
                    </div>
                    <BarraDeFiltros
                      linhas={todas}
                      filtros={filtros}
                      aoMudar={definirFiltros}
                      // Controle que não faz nada é pior que controle ausente: no quadro,
                      // quem responde pela situação são as três colunas.
                      ocultar={vista === 'kanban' ? ['situacao'] : []}
                    />
                  </Cartao>

                  {semCorte(filtros) ? null : (
                    <Tarja
                      mostrando={linhas.length}
                      total={todas.length}
                      cortes={cortes}
                      aoLimpar={limpar}
                    />
                  )}

                  {linhas.length === 0 ? (
                    <RecorteVazio filtros={filtros} total={todas.length} aoLimpar={limpar} />
                  ) : vista === 'kanban' ? (
                    <Kanban linhas={linhas} aoAbrir={abrir} />
                  ) : (
                    <Lista linhas={linhas} aoAbrir={abrir} />
                  )}

                  <Cartao>
                    <CabecalhoCard rotulo="O que aparece aqui" />
                    <p className="text-sm text-fraco">
                      Só as pendências que a equipe compartilhou com você. Clique numa linha
                      para ver o que ela respondeu, os documentos publicados e as ordens de
                      serviço vinculadas. Quem move uma pendência de coluna é a equipe — o
                      quadro aqui é de leitura.
                    </p>
                  </Cartao>
                </>
              )}
            </div>
          )
        }}
      </Tela4Estados>

      {/* A gaveta é irmã da lista: um link direto para `/pendencias/:cid` abre as duas, e uma
          falha na lista não impede o cliente de ler a pendência que recebeu por e-mail. */}
      {aberta !== null && Number.isFinite(aberta) ? (
        <Drawer usinaId={usinaId} cid={aberta} aoFechar={() => navigate(base)} />
      ) : null}
    </Pagina>
  )
}
