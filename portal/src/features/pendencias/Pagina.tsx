/**
 * Pendências — a pendência que eu cobrei está andando?
 *
 * UMA pergunta, e a resposta cabe numa linha por pendência: em que etapa está, se o prazo
 * venceu e quando mexeram por último. O detalhe (o que a equipe respondeu, o que publicou e
 * que ordem de serviço resolve) abre na gaveta, sem tirar o cliente da lista.
 *
 * **O recorte padrão é "cobradas por mim".** No meuPlano "compartilhável" é o padrão de toda
 * pendência, então a lista compartilhada traz também o que a própria equipe abriu. Quem
 * pergunta "o que EU cobrei está andando?" quer ver primeiro o que marcou como cobrado —
 * mas o outro segmento continua a um clique, porque a pendência da equipe é informação
 * legítima para o cliente.
 *
 * **Nenhum segmento deixa a tela muda.** Escolher "cobradas por mim" numa usina que não tem
 * nenhuma marcada mostra a frase explicando e o botão que troca de segmento; sem isso, o
 * cliente leria "não há nada" quando o que há é um recorte vazio.
 *
 * Cor, frase e contagem vêm todas do BFF (`situacao`, `tom`, `abertas`, `prazo_vencido`).
 * A tela não soma nem reinterpreta código nenhum — ver `api.ts`.
 */

import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

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
  caminhoDaLista,
  rotuloDaCriticidade,
  type Pendencia,
  type PendenciasOut,
} from '@/features/pendencias/api'

type Segmento = 'cobradas' | 'todas'

const OPCOES: { valor: Segmento; rotulo: string }[] = [
  { valor: 'cobradas', rotulo: 'Cobradas por mim' },
  { valor: 'todas', rotulo: 'Todas as compartilhadas' },
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
    </Cartao>
  )
}

function Lista({
  dados,
  aoAbrir,
}: {
  dados: PendenciasOut
  aoAbrir: (p: Pendencia) => void
}) {
  // `null` = o cliente ainda não escolheu; o padrão é derivado do que existe na usina.
  const [escolha, setEscolha] = useState<Segmento | null>(null)

  const todas = dados.pendencias
  const cobradas = todas.filter((p) => p.cobrada_pelo_cliente)
  const segmento: Segmento = escolha ?? (cobradas.length > 0 ? 'cobradas' : 'todas')
  const linhas = segmento === 'cobradas' ? cobradas : todas
  const caiuEmTodas = escolha === null && cobradas.length === 0 && todas.length > 0

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
        <span className="block min-w-0">
          <span className="block truncate font-medium text-forte">{p.titulo}</span>
          {/* A marca só faz sentido no segmento misto — no recorte "cobradas" seria uma
              etiqueta repetida em toda linha. */}
          {segmento === 'todas' && p.cobrada_pelo_cliente ? (
            <span className="block text-xs text-fraco">cobrada por você</span>
          ) : null}
        </span>
      ),
    },
    { titulo: 'Etapa', celula: (p: Pendencia) => <span className="text-fraco">{p.etapa ?? '—'}</span> },
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
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-3 pt-5">
        <Segmentado opcoes={OPCOES} valor={segmento} onEscolher={setEscolha} />
        <span className="text-xs text-fraco">
          <Num>{inteiro(linhas.length)}</Num> {linhas.length === 1 ? 'pendência' : 'pendências'}
        </span>
      </div>

      {caiuEmTodas ? (
        <p className="px-5 pb-3 text-sm text-fraco">
          Nenhuma pendência marcada como cobrada por você — mostrando todas as compartilhadas.
        </p>
      ) : null}

      <div className="px-2 pb-3">
        <Tabela
          colunas={colunas}
          linhas={linhas}
          chave={(p) => p.id}
          aoClicar={aoAbrir}
          vazio={
            segmento === 'cobradas' ? (
              <Vazio
                titulo="Nenhuma pendência cobrada por você"
                descricao="A equipe marca a pendência como cobrada por você quando ela nasce de um pedido seu. Há outras pendências compartilhadas nesta usina."
                acao={
                  <Botao variante="secundario" onClick={() => setEscolha('todas')}>
                    Ver todas as compartilhadas
                  </Botao>
                }
              />
            ) : (
              <Vazio
                titulo="Nenhuma pendência compartilhada nesta usina"
                descricao={
                  dados.aviso ??
                  'Quando a equipe compartilhar uma pendência desta usina, ela aparece aqui.'
                }
              />
            )
          }
        />
      </div>
    </Cartao>
  )
}

export default function Pendencias() {
  const { id, cid } = useParams<{ id: string; cid?: string }>()
  const navigate = useNavigate()

  const usinaId = Number(id)
  const usinaValida = Number.isFinite(usinaId) && usinaId > 0
  const leitura = useLeitura<PendenciasOut>(caminhoDaLista(usinaId), { ativo: usinaValida })

  const aberta = cid ? Number(cid) : null
  const base = `/usinas/${usinaId}/pendencias`

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
    <Pagina titulo="Pendências" subtitulo="A pendência que eu cobrei está andando?">
      <Tela4Estados leitura={leitura} esqueleto={<EsqueletoDaLista />}>
        {(dados) => (
          <div className="space-y-4">
            {/* O aviso do servidor (usina sem o lado da manutenção, consulta que falhou) fica
                acima dos números: sem ele, contador nulo pareceria tela quebrada. */}
            {dados.aviso && dados.pendencias.length > 0 ? <Aviso>{dados.aviso}</Aviso> : null}

            <Contadores dados={dados} />

            <Lista
              dados={dados}
              aoAbrir={(p) => navigate(`${base}/${p.id}`)}
            />

            {dados.pendencias.length > 0 ? (
              <Cartao>
                <CabecalhoCard rotulo="O que aparece aqui" />
                <p className="text-sm text-fraco">
                  Só as pendências que a equipe compartilhou com você. Clique numa linha para ver
                  o que ela respondeu, os documentos publicados e as ordens de serviço vinculadas.
                </p>
              </Cartao>
            ) : null}
          </div>
        )}
      </Tela4Estados>

      {/* A gaveta é irmã da lista: um link direto para `/pendencias/:cid` abre as duas, e uma
          falha na lista não impede o cliente de ler a pendência que recebeu por e-mail. */}
      {aberta !== null && Number.isFinite(aberta) ? (
        <Drawer usinaId={usinaId} cid={aberta} aoFechar={() => navigate(base)} />
      ) : null}
    </Pagina>
  )
}
