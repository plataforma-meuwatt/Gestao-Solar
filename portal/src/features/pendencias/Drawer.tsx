/**
 * O detalhe de UMA pendência, na gaveta lateral.
 *
 * Gaveta e não página: o cliente percorre a lista, abre uma, fecha e continua de onde
 * estava. Uma página inteira o faria perder o lugar a cada item — e a lista atrás continua
 * carregada, então fechar não recarrega nada.
 *
 * Ele responde três perguntas, nesta ordem: **em que pé está** (etapa, situação, prazo, quem
 * responde), **o que a equipe respondeu** (o parecer, em texto) e **o que dá para levar**
 * (documentos publicados e a ordem de serviço que resolve). Nada de editar, comentar ou
 * aprovar: aqui o cliente lê o andamento do que cobrou.
 *
 * O endereço é próprio (`/usinas/:id/pendencias/:cid`), então um link colado no e-mail abre
 * a lista E a gaveta certa — por isso a leitura do detalhe é independente da lista: se a
 * lista falhar, a gaveta ainda abre.
 */

import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  Aviso,
  Botao,
  CabecalhoCard,
  Cartao,
  Gaveta,
  Num,
  Selo,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { dataCurta, dataPorExtenso, inteiro, quando } from '@/lib/format'
import { useLeitura, type Leitura } from '@/lib/leitura'
import {
  abrirDocumento,
  caminhoDoDetalhe,
  rotuloDaCriticidade,
  type DocumentoPendencia,
  type OrdemVinculada,
  type PendenciaDetalhe,
} from '@/features/pendencias/api'

/** Um par rótulo/valor da ficha. Valor ausente vira "—", nunca some da lista. */
function Campo({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs uppercase tracking-wide text-rotulo">{rotulo}</div>
      <div className="mt-0.5 text-sm text-corpo">{children}</div>
    </div>
  )
}

/**
 * A gaveta trata "não encontrada" como VAZIO, não como erro.
 *
 * O BFF responde 404 tanto para número inexistente quanto para pendência que saiu da lista
 * compartilhada (ou que nunca foi de quem está lendo — lá o 404 é proposital, para não
 * confirmar que ela existe). Nos três casos "Tentar de novo" é um convite a repetir algo que
 * nunca vai dar certo, então a tela diz o que aconteceu e oferece voltar para a lista.
 *
 * Quem decide é o STATUS. A primeira versão casava a FRASE do servidor, o que prendia a
 * gaveta à prosa do BFF — reescrever a mensagem faria o vazio virar erro genérico sem nada
 * quebrar e sem ninguém notar. `Leitura.status` nasceu deste caso.
 */
function ehSumida(leitura: Leitura<unknown>): boolean {
  return leitura.dados === null && leitura.status === 404
}

function Documento({ doc }: { doc: DocumentoPendencia }) {
  const [abrindo, setAbrindo] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  return (
    <li className="border-b border-borda-fraca py-2 last:border-0">
      <button
        type="button"
        disabled={abrindo}
        onClick={() => {
          setErro(null)
          setAbrindo(true)
          abrirDocumento(doc)
            .catch((e: unknown) => setErro(e instanceof Error ? e.message : 'Não deu para abrir o arquivo.'))
            .finally(() => setAbrindo(false))
        }}
        className="flex w-full items-center gap-3 text-left text-sm text-corpo transition hover:text-forte disabled:opacity-50"
      >
        <span className="min-w-0 flex-1 truncate">{doc.nome}</span>
        <span className="shrink-0 text-xs text-fraco">
          {abrindo ? 'abrindo…' : doc.publicado_em ? dataCurta(doc.publicado_em) : ''}
        </span>
      </button>
      {erro ? <p className="mt-1 text-xs text-tom-parado">{erro}</p> : null}
    </li>
  )
}

function OrdemLinha({ ordem, aoAbrir }: { ordem: OrdemVinculada; aoAbrir: () => void }) {
  return (
    <li className="border-b border-borda-fraca last:border-0">
      <button
        type="button"
        onClick={aoAbrir}
        className="flex w-full items-center gap-3 py-2.5 text-left transition hover:text-forte"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-corpo">{ordem.objetivo}</span>
          <span className="block truncate text-xs text-fraco">
            {/* A OS se identifica pelo `id` — é o único número que ela tem. Aqui saía
                `contrato_numero` como "OS #665": o número do CONTRATO. Toda ordem daquele
                contrato virava "OS #665", e o cliente não achava na lista de Ordens. */}
            OS <Num>{ordem.id}</Num>
            {ordem.classificacao ? ` · ${ordem.classificacao}` : ''}
            {ordem.agendada_para ? ` · ${dataCurta(ordem.agendada_para)}` : ''}
          </span>
        </span>
        <Selo tom={ordem.tom}>{ordem.situacao}</Selo>
        <span aria-hidden className="text-fraco">
          ›
        </span>
      </button>
    </li>
  )
}

function Conteudo({
  pendencia,
  usinaId,
  aoAbrirOrdem,
}: {
  pendencia: PendenciaDetalhe
  usinaId: number
  aoAbrirOrdem: (osId: number) => void
}) {
  const criticidade = rotuloDaCriticidade(pendencia.criticidade)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Selo tom={pendencia.tom}>{pendencia.situacao}</Selo>
        {criticidade && pendencia.criticidade_tom ? (
          <Selo tom={pendencia.criticidade_tom}>{criticidade}</Selo>
        ) : null}
        {pendencia.cobrada_pelo_cliente ? (
          <span className="text-xs text-fraco">cobrada por você</span>
        ) : null}
      </div>

      <Cartao>
        <div className="grid grid-cols-2 gap-4">
          <Campo rotulo="Número">
            <Num>{pendencia.numero === null ? '—' : `#${pendencia.numero}`}</Num>
          </Campo>
          <Campo rotulo="Etapa">{pendencia.etapa ?? '—'}</Campo>
          <Campo rotulo="Prazo">
            {/* Vermelho é do servidor: `tom = 'parado'` já quer dizer "venceu e não concluiu". */}
            <span className={pendencia.tom === 'parado' ? 'text-tom-parado' : undefined}>
              <Num>{dataCurta(pendencia.prazo)}</Num>
            </span>
          </Campo>
          <Campo rotulo="Responsável">{pendencia.responsavel ?? '—'}</Campo>
          <Campo rotulo="Aberta em">
            <Num>{dataPorExtenso(pendencia.aberta_em)}</Num>
          </Campo>
          <Campo rotulo="Última atividade">{quando(pendencia.ultima_atividade_em)}</Campo>
          {pendencia.concluida_em ? (
            <Campo rotulo="Concluída em">
              <Num>{dataPorExtenso(pendencia.concluida_em)}</Num>
            </Campo>
          ) : null}
        </div>
      </Cartao>

      {pendencia.descricao ? (
        <Cartao>
          <CabecalhoCard rotulo="O que foi pedido" />
          {/* `pre-line`: o BFF entrega texto com as quebras do editor preservadas — é o que
              deixa o recado legível sem colocar marcação alguma no DOM. */}
          <p className="whitespace-pre-line text-sm text-corpo">{pendencia.descricao}</p>
        </Cartao>
      ) : null}

      <Cartao>
        <CabecalhoCard rotulo="O que a equipe respondeu" />
        {pendencia.parecer ? (
          <p className="whitespace-pre-line text-sm text-corpo">{pendencia.parecer}</p>
        ) : (
          <p className="text-sm text-fraco">
            A equipe ainda não registrou uma resposta para esta pendência.
          </p>
        )}
      </Cartao>

      <Cartao>
        <CabecalhoCard
          rotulo="Documentos publicados"
          direita={
            pendencia.documentos_publicados.length > 0 ? (
              <Num>{inteiro(pendencia.documentos_publicados.length)}</Num>
            ) : undefined
          }
        />
        {pendencia.documentos_publicados.length === 0 ? (
          <p className="text-sm text-fraco">
            Nenhum documento publicado nesta pendência até agora.
          </p>
        ) : (
          <ul>
            {pendencia.documentos_publicados.map((d) => (
              <Documento key={d.id} doc={d} />
            ))}
          </ul>
        )}
      </Cartao>

      <Cartao>
        <CabecalhoCard rotulo="Ordens de serviço vinculadas" />
        {pendencia.ordens.length === 0 ? (
          <p className="text-sm text-fraco">
            Nenhuma ordem de serviço vinculada a esta pendência.
          </p>
        ) : (
          <ul>
            {pendencia.ordens.map((o) => (
              <OrdemLinha key={o.id} ordem={o} aoAbrir={() => aoAbrirOrdem(o.id)} />
            ))}
          </ul>
        )}
      </Cartao>

      {/* O portal mostra a pendência da usina em que o cliente está; o id do vínculo é o
          mesmo que a URL carrega, e uma divergência aqui seria erro de navegação. */}
      {pendencia.usina_id !== usinaId ? (
        <Aviso tom="semDados">Esta pendência é da usina {pendencia.usina}.</Aviso>
      ) : null}
    </div>
  )
}

export function Drawer({
  usinaId,
  cid,
  aoFechar,
}: {
  usinaId: number
  cid: number
  aoFechar: () => void
}) {
  const navigate = useNavigate()
  const leitura = useLeitura<PendenciaDetalhe>(caminhoDoDetalhe(cid))
  const sumida = ehSumida(leitura)

  return (
    <Gaveta
      aberta
      aoFechar={aoFechar}
      titulo={leitura.dados ? leitura.dados.titulo : `Pendência ${cid}`}
    >
      {sumida ? (
        <Vazio
          titulo="Pendência não encontrada"
          descricao="Ela pode ter deixado de ser compartilhada, ou o endereço aponta para outro número."
          acao={
            <Botao variante="secundario" onClick={aoFechar}>
              Voltar para a lista
            </Botao>
          }
        />
      ) : (
        // Os outros três estados (esqueleto, erro com "Tentar de novo", cache com o selo de
        // offline) são os mesmos de toda tela do portal.
        <Tela4Estados leitura={leitura}>
          {(d) => (
            <Conteudo
              pendencia={d}
              usinaId={usinaId}
              aoAbrirOrdem={(osId) => navigate(`/usinas/${usinaId}/ordens/${osId}`)}
            />
          )}
        </Tela4Estados>
      )}
    </Gaveta>
  )
}
