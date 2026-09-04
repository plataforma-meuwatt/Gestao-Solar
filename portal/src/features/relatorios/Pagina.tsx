/**
 * Relatórios — O que eu levo para a diretoria?
 *
 * Dois documentos, duas origens, dois blocos que NÃO se derrubam:
 *
 * 1. **Relatório de manutenção do período** — o que a equipe executou contra o que o
 *    contrato previa (`RelatorioManutencao`). Nasce no meuPlano, lido do próprio ativo.
 * 2. **Relatórios de geração publicados** — os fechamentos que a equipe publica pelo
 *    meuWatt, com o PDF de geração e o anexo de paradas.
 *
 * Cada bloco tem a SUA leitura e os seus quatro estados. É deliberado: o cliente que abre
 * esta tela numa usina sem cronograma consolidado precisa continuar baixando os relatórios
 * de geração — juntar os dois numa leitura só faria a falha de um apagar o outro, e é
 * exatamente o caso que acontece primeiro (contrato novo, geração já publicada).
 *
 * Nenhum PDF é um link comum. As rotas de arquivo do BFF exigem a sessão em CABEÇALHO, e a
 * saída fácil — token na query string — é a proibida: endereço entra em log e em histórico.
 * Por isso tudo passa por `abrirPdf` (fetch + Bearer + blob em aba nova).
 */

import { useParams } from 'react-router-dom'

import { Aviso, Botao, Cartao, Num, Pagina, Tela4Estados, Vazio } from '@/components/base'
import { dataCurta, dataPorExtenso } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import {
  caminhoDoArquivo,
  chaveDocumentos,
  NOME_DO_ARQUIVO,
  type Documento,
  type DocumentosOut,
} from '@/features/relatorios/api'
import { RelatorioManutencao, useBaixarPdf } from '@/features/relatorios/RelatorioManutencao'

const TITULO = 'Relatórios'
const PERGUNTA = 'O que eu levo para a diretoria?'

export default function Relatorios() {
  const { id } = useParams()
  const usinaId = Number(id)

  if (!Number.isFinite(usinaId) || usinaId <= 0) {
    return (
      <Pagina titulo={TITULO} subtitulo={PERGUNTA}>
        <Vazio
          titulo="Usina não encontrada"
          descricao="Escolha uma usina na barra do topo para ver os relatórios dela."
        />
      </Pagina>
    )
  }

  return (
    <Pagina titulo={TITULO} subtitulo={PERGUNTA}>
      <div className="space-y-10">
        <RelatorioManutencao usinaId={usinaId} />
        <DocumentosPublicados usinaId={usinaId} />
      </div>
    </Pagina>
  )
}

/* ------------------------------------------------------------------ bloco 2 */

function CartaoDoDocumento({
  d,
  baixando,
  aoBaixar,
}: {
  d: Documento
  baixando: string | null
  aoBaixar: (marca: string, caminho: string, nome: string) => void
}) {
  return (
    <Cartao>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium text-forte">{d.nome}</h3>
          <p className="mt-0.5 text-xs text-fraco">
            {d.periodo ? `${d.periodo} · ` : ''}
            <Num>{dataCurta(d.de)}</Num> a <Num>{dataCurta(d.ate)}</Num>
          </p>
        </div>
        <span className="text-xs text-fraco">
          publicado em {dataPorExtenso(d.publicado_em)}
        </span>
      </div>

      {d.arquivos.length === 0 ? (
        // O fechamento existe mas nenhum arquivo veio junto: dizer isso é melhor que
        // oferecer um botão que devolveria 404.
        <p className="mt-3 text-sm text-fraco">Este fechamento não tem arquivo publicado.</p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {d.arquivos.map((a) => {
            const marca = `${d.id}-${a.tipo}`
            return (
              <Botao
                key={marca}
                variante="secundario"
                desabilitado={baixando !== null}
                onClick={() =>
                  aoBaixar(
                    marca,
                    caminhoDoArquivo(d.id, a.tipo),
                    a.nome ? a.nome : `${marca}.pdf`,
                  )
                }
              >
                {baixando === marca
                  ? 'Abrindo…'
                  : (NOME_DO_ARQUIVO[a.tipo] ?? a.nome ?? a.tipo)}
              </Botao>
            )
          })}
        </div>
      )}
    </Cartao>
  )
}

function DocumentosPublicados({ usinaId }: { usinaId: number }) {
  const leitura = useLeitura<DocumentosOut>(chaveDocumentos(usinaId))
  const pdf = useBaixarPdf()

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-forte">Relatórios de geração publicados</h2>
        <p className="text-sm text-fraco">
          Os fechamentos que a equipe publicou para esta usina, com o anexo de paradas.
        </p>
      </div>

      {pdf.erro === null ? null : <Aviso tom="parado">{pdf.erro}</Aviso>}

      <Tela4Estados leitura={leitura}>
        {(dados) => (
          <div className="space-y-4">
            {dados.aviso === null ? null : <Aviso>{dados.aviso}</Aviso>}
            {dados.documentos.length === 0 ? (
              <Vazio
                titulo="Nenhum relatório publicado"
                // Vazio ≠ erro: o servidor respondeu, e a resposta é que ainda não há
                // fechamento publicado para esta usina.
                descricao="Quando a equipe publicar um fechamento de geração, ele aparece aqui para baixar."
              />
            ) : (
              dados.documentos.map((d) => (
                <CartaoDoDocumento
                  key={d.id}
                  d={d}
                  baixando={pdf.baixando}
                  aoBaixar={(marca, caminho, nome) => pdf.baixar(marca, caminho, nome)}
                />
              ))
            )}
          </div>
        )}
      </Tela4Estados>
    </section>
  )
}
