/**
 * Paradas — quanto tempo e quanta energia perdi com paradas neste período, e alguma continua
 * aberta?
 *
 * É UMA pergunta, com quatro números na frente (paradas, tempo parado, energia perdida, em
 * aberto agora) e a lista do que aconteceu. Nada de causa, de peça ou de qual inversor: esta
 * tela é do dono da usina, e a análise do aparelho é trabalho da equipe.
 *
 * As decisões que valem a pena guardar:
 *
 * **Zero e "não sabemos" são telas diferentes.** `total = 0` é a boa notícia — "nenhuma parada
 * no período", em verde. `total = null` é o monitoramento fora do ar, e aí a tela mostra o
 * aviso do servidor. Trocar um pelo outro faria o portal afirmar que o mês foi tranquilo
 * quando ninguém conseguiu ler.
 *
 * **Uma parada em aberto não tem fim.** A coluna mostra "—" (nunca a hora de agora, que
 * pareceria resolvida) e a linha carrega o selo vermelho que o próprio servidor mandou.
 *
 * **O aviso da fonte é discreto, não alarmante.** Quando o BFF cai na fonte reserva, a energia
 * perdida passa a ser estimada pelo monitoramento — o dono precisa saber disso para não levar
 * o número a uma reunião como se fosse medição, mas isso é uma nota de rodapé, não um erro.
 */

import { useState } from 'react'
import { useParams } from 'react-router-dom'

import {
  AtualizadoAs,
  Aviso,
  CabecalhoCard,
  CarregandoCartao,
  Cartao,
  Esqueleto,
  Kpi,
  Num,
  Pagina,
  Selo,
  Tabela,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { SeletorPeriodo } from '@/components/SeletorPeriodo'
import { dataCurta, dataHora, duracao, energia, inteiro } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import { hojeIso, rotuloDoPeriodo } from '@/lib/periodo'
import {
  chaveDeParadas,
  rotuloDoTipo,
  type Parada,
  type ParadasOut,
  type RecorteDeParadas,
} from '@/features/paradas/api'

/** A mancha do que vai chegar: os quatro números e a lista. Nunca um spinner solto. */
function EsqueletoParadas() {
  return (
    <div className="space-y-4">
      <Cartao>
        <Esqueleto altura={14} largura="30%" />
        <div className="mt-5 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i}>
              <Esqueleto altura={11} largura="65%" />
              <div className="mt-2">
                <Esqueleto altura={28} largura="80%" />
              </div>
            </div>
          ))}
        </div>
      </Cartao>
      <CarregandoCartao linhas={5} />
    </div>
  )
}

/** Os quatro números do período, com a janela que o SERVIDOR de fato consultou. */
function Numeros({
  dados,
  atualizadoEm,
  offlineDesde,
  rotulo,
}: {
  dados: ParadasOut
  atualizadoEm?: string
  offlineDesde?: string
  rotulo: string
}) {
  const semParada = dados.total === 0

  return (
    <Cartao>
      <CabecalhoCard
        rotulo={rotulo}
        direita={<AtualizadoAs em={atualizadoEm} offlineDesde={offlineDesde} />}
      />
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          rotulo="Paradas"
          valor={inteiro(dados.total)}
          tamanho="grande"
          tom={semParada ? 'ok' : undefined}
          detalhe={`de ${dataCurta(dados.inicio)} a ${dataCurta(dados.fim)}`}
        />
        <Kpi
          rotulo="Tempo parado"
          valor={duracao(dados.tempo_parado_min)}
          // Nulo com paradas na lista não é "zero minuto": é o BFF recusando somar pela
          // metade porque uma delas veio sem duração. Dizer isso evita a leitura errada.
          detalhe={
            dados.tempo_parado_min === null && !semParada
              ? 'alguma parada veio sem o tempo'
              : undefined
          }
        />
        <Kpi
          rotulo="Energia perdida"
          valor={energia(dados.perda_kwh)}
          detalhe={
            dados.perda_kwh === null && !semParada
              ? 'alguma parada veio sem o número'
              : undefined
          }
        />
        <Kpi
          rotulo="Em aberto agora"
          valor={inteiro(dados.em_aberto)}
          tom={dados.em_aberto > 0 ? 'parado' : 'ok'}
          detalhe={
            dados.em_aberto > 0 ? (
              <Selo tom="parado">Ainda parada</Selo>
            ) : (
              'nada parado neste momento'
            )
          }
        />
      </div>
    </Cartao>
  )
}

/**
 * A lista, na ordem em que o servidor mandou (início mais recente primeiro).
 *
 * Reordenar aqui seria refazer no navegador uma decisão que o BFF já tomou — e as duas ordens
 * divergiriam no dia em que uma das duas mudasse.
 */
function Lista({ paradas }: { paradas: Parada[] }) {
  return (
    <Cartao semPadding>
      <div className="px-5 pt-5">
        <CabecalhoCard rotulo="Cada parada" />
      </div>
      <Tabela<Parada>
        linhas={paradas}
        chave={(p) => p.id}
        colunas={[
          { titulo: 'Início', celula: (p) => <Num>{dataHora(p.inicio)}</Num> },
          // Parada em aberto não tem fim: "—". Carimbar a hora de agora a faria parecer
          // resolvida, que é a leitura mais cara desta tela.
          { titulo: 'Fim', celula: (p) => <Num>{dataHora(p.fim)}</Num> },
          { titulo: 'Duração', alinhar: 'dir', celula: (p) => <Num>{duracao(p.duracao_min)}</Num> },
          {
            titulo: 'Energia perdida',
            alinhar: 'dir',
            celula: (p) => <Num>{energia(p.perda_kwh)}</Num>,
          },
          { titulo: 'Tipo', celula: (p) => rotuloDoTipo(p.tipo) },
          {
            titulo: 'Situação',
            celula: (p) => <Selo tom={p.tom}>{p.em_aberto ? 'Em aberto' : 'Resolvida'}</Selo>,
          },
        ]}
      />
    </Cartao>
  )
}

function Conteudo({
  dados,
  atualizadoEm,
  offlineDesde,
  rotulo,
}: {
  dados: ParadasOut
  atualizadoEm?: string
  offlineDesde?: string
  rotulo: string
}) {
  // Nenhuma das duas fontes respondeu: não há número nenhum para mostrar, e "nenhuma parada"
  // seria mentira para o lado bom. A frase é a do servidor, que sabe qual fonte falhou.
  if (dados.total === null) {
    return (
      <Vazio
        titulo="Não deu para ler as paradas deste período"
        descricao={dados.aviso ?? 'O monitoramento não respondeu. Tente de novo em instantes.'}
      />
    )
  }

  return (
    <>
      <Numeros
        dados={dados}
        atualizadoEm={atualizadoEm}
        offlineDesde={offlineDesde}
        rotulo={rotulo}
      />

      {/* A nota da fonte: discreta (cinza), porque é rodapé de leitura e não falha. */}
      {dados.aviso ? <Aviso tom="semDados">{dados.aviso}</Aviso> : null}

      {dados.paradas.length === 0 ? (
        <Vazio
          tom="ok"
          titulo="Nenhuma parada no período"
          descricao="A usina não registrou parada nem degradação nesta janela."
        />
      ) : (
        <Lista paradas={dados.paradas} />
      )}
    </>
  )
}

export default function Paradas() {
  const { id } = useParams<{ id: string }>()
  const usinaId = Number(id)
  const usinaValida = Number.isFinite(usinaId) && usinaId > 0

  const [recorte, setRecorte] = useState<RecorteDeParadas>('mes')
  const [referencia, setReferencia] = useState<string>(hojeIso())

  const leitura = useLeitura<ParadasOut>(chaveDeParadas(usinaId, recorte, referencia), {
    ativo: usinaValida,
  })

  return (
    <Pagina
      titulo="Paradas"
      subtitulo="Quanto tempo e quanta energia perdi com paradas neste período?"
      acoes={
        usinaValida ? (
          <SeletorPeriodo
            recorte={recorte}
            referencia={referencia}
            recortes={['mes', 'ano']}
            // O seletor fala os três recortes do produto; aqui só dois existem, e o `if`
            // guarda o estado de receber um valor que esta tela não sabe consultar.
            onRecorte={(r) => {
              if (r === 'mes' || r === 'ano') setRecorte(r)
            }}
            onReferencia={setReferencia}
          />
        ) : null
      }
    >
      {usinaValida ? (
        <Tela4Estados leitura={leitura} esqueleto={<EsqueletoParadas />}>
          {(dados) => (
            <Conteudo
              dados={dados}
              atualizadoEm={leitura.atualizadoEm}
              offlineDesde={leitura.offlineDesde}
              rotulo={rotuloDoPeriodo(referencia, recorte)}
            />
          )}
        </Tela4Estados>
      ) : (
        <Vazio
          titulo="Escolha uma usina"
          descricao="Selecione a usina na barra do topo para ver as paradas dela."
        />
      )}
    </Pagina>
  )
}
