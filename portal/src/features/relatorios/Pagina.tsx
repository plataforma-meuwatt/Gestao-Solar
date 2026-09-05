/**
 * Relatórios — O que eu levo para a diretoria?
 *
 * É a única tela do portal que guarda as DUAS famílias, e por isso ela mesma as separa: um
 * segmentado no topo escolhe entre **Energia** e **Manutenção**. Sem a separação, quem vinha
 * buscar o fechamento de geração passava por cima do cronograma cumprido, e quem vinha buscar
 * as fichas da inspeção rolava a página inteira antes de achá-las — os dois assuntos têm
 * donos diferentes na empresa do cliente.
 *
 * **Abre em Energia.** É o documento mensal, o que mais gente vem buscar. A escolha vive na
 * URL (`?aba=`) porque link de relatório é colado em e-mail: o endereço tem de reabrir na
 * mesma metade.
 *
 * **Energia — os três PDFs consolidados.** Cada fechamento publicado pode trazer três peças:
 * o Relatório de Geração, o Anexo de Paradas e o Resumo Executivo. A terceira só existe
 * quando o mês teve o resumo gerado, então **peça ausente é estado normal, nunca erro**: o
 * botão que falta vira uma frase dizendo que aquela peça não foi publicada. E a lista vazia
 * também não é falha — aqui só aparece o fechamento que a equipe ENVIOU ao cliente.
 *
 * **Manutenção — dois blocos, leituras independentes.** O relatório do período
 * (`RelatorioManutencao`, lido do próprio ativo no meuPlano) e o pacote de fichas
 * (`PacoteDeFichas`). Cada um com os seus quatro estados: juntá-los numa leitura só faria a
 * falha de um apagar o outro, e é o caso que acontece primeiro (contrato novo, fichas já
 * geradas).
 *
 * Só a aba aberta é montada. Ler as quatro origens de uma vez custaria caro à toa — o
 * inventário de fichas mede o tamanho de cada PDF no armazenamento — e o cliente que veio
 * buscar o fechamento de agosto não pediu nada disso.
 *
 * Nenhum PDF é link comum. As rotas de arquivo do BFF exigem a sessão em CABEÇALHO, e a saída
 * fácil — token na query string — é a proibida: endereço entra em log e em histórico. Por
 * isso tudo passa por `abrirPdf`/`baixarArquivo` (fetch + Bearer + blob).
 */

import { useParams, useSearchParams } from 'react-router-dom'

import { Aviso, Botao, Cartao, Num, Pagina, Segmentado, Tela4Estados, Vazio } from '@/components/base'
import { dataCurta, dataPorExtenso } from '@/lib/format'
import { useLeitura } from '@/lib/leitura'
import {
  caminhoDoArquivo,
  chaveDocumentos,
  NOME_DO_ARQUIVO,
  PECAS_DO_FECHAMENTO,
  type ArquivoDoDocumento,
  type Documento,
  type DocumentosOut,
} from '@/features/relatorios/api'
import { PacoteDeFichas } from '@/features/relatorios/PacoteDeFichas'
import { RelatorioManutencao, useBaixarPdf } from '@/features/relatorios/RelatorioManutencao'

const TITULO = 'Relatórios'
const PERGUNTA = 'O que eu levo para a diretoria?'

type Aba = 'energia' | 'manutencao'

const ABAS: { valor: Aba; rotulo: string }[] = [
  { valor: 'energia', rotulo: 'Energia' },
  { valor: 'manutencao', rotulo: 'Manutenção' },
]

export default function Relatorios() {
  const { id } = useParams()
  const usinaId = Number(id)
  const [params, setParams] = useSearchParams()

  // Qualquer outro valor cai em Energia: um `?aba=` datilografado errado não pode deixar a
  // tela em branco. E a troca é `replace` — a escolha de metade não é um passo de histórico,
  // senão o botão "voltar" do navegador andaria aba por aba antes de sair da tela.
  const aba: Aba = params.get('aba') === 'manutencao' ? 'manutencao' : 'energia'
  function escolher(nova: Aba) {
    const novos = new URLSearchParams(params)
    novos.set('aba', nova)
    setParams(novos, { replace: true })
  }

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
    <Pagina
      titulo={TITULO}
      subtitulo={PERGUNTA}
      acoes={<Segmentado opcoes={ABAS} valor={aba} onEscolher={escolher} />}
    >
      {aba === 'energia' ? (
        <DocumentosPublicados usinaId={usinaId} />
      ) : (
        <div className="space-y-10">
          <RelatorioManutencao usinaId={usinaId} />
          <PacoteDeFichas usinaId={usinaId} />
        </div>
      )}
    </Pagina>
  )
}

/* ------------------------------------------------------------------ energia */

/** O nome que o cliente lê. Kind desconhecido sai com o nome que o servidor mandou. */
function nomeDaPeca(tipo: string, arquivo: ArquivoDoDocumento | null): string {
  const conhecido = NOME_DO_ARQUIVO[tipo]
  if (conhecido) return conhecido
  if (arquivo !== null && arquivo.nome) return arquivo.nome
  return tipo
}

function CartaoDoDocumento({
  d,
  baixando,
  aoBaixar,
}: {
  d: Documento
  baixando: string | null
  aoBaixar: (marca: string, caminho: string, nome: string) => void
}) {
  const porTipo = new Map(d.arquivos.map((a) => [a.tipo, a]))
  // Primeiro as três peças que o meuWatt publica, na ordem do documento; depois o que ele
  // vier a publicar amanhã. Um kind novo não pode sumir da tela só por ser desconhecido.
  const extras = d.arquivos.filter(
    (a) => !(PECAS_DO_FECHAMENTO as readonly string[]).includes(a.tipo),
  )

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
        <span className="text-xs text-fraco">publicado em {dataPorExtenso(d.publicado_em)}</span>
      </div>

      {d.arquivos.length === 0 ? (
        // O fechamento existe mas nenhum arquivo veio junto: dizer isso é melhor que
        // oferecer um botão que devolveria 404.
        <p className="mt-3 text-sm text-fraco">Este fechamento não tem arquivo publicado.</p>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {PECAS_DO_FECHAMENTO.map((tipo) => {
            const a = porTipo.get(tipo) ?? null
            const nome = nomeDaPeca(tipo, a)
            if (a === null) {
              // Peça que falta é ESTADO, não erro: o Resumo Executivo só existe quando o mês
              // teve o resumo gerado no meuWatt, e escondê-la deixaria o cliente sem saber se
              // ela não existe ou se a tela esqueceu de mostrá-la.
              return (
                <span
                  key={tipo}
                  className="inline-flex min-h-[38px] items-center rounded-campo border border-dashed border-borda px-3.5 text-sm text-fraco"
                >
                  {nome} · não publicado neste fechamento
                </span>
              )
            }
            const marca = `${d.id}-${tipo}`
            return (
              <Botao
                key={marca}
                variante="secundario"
                desabilitado={baixando !== null}
                onClick={() =>
                  aoBaixar(marca, caminhoDoArquivo(d.id, tipo), a.nome ? a.nome : `${marca}.pdf`)
                }
              >
                {baixando === marca ? 'Abrindo…' : nome}
              </Botao>
            )
          })}

          {extras.map((a) => {
            const marca = `${d.id}-${a.tipo}`
            return (
              <Botao
                key={marca}
                variante="secundario"
                desabilitado={baixando !== null}
                onClick={() =>
                  aoBaixar(marca, caminhoDoArquivo(d.id, a.tipo), a.nome ? a.nome : `${marca}.pdf`)
                }
              >
                {baixando === marca ? 'Abrindo…' : nomeDaPeca(a.tipo, a)}
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
        <h2 className="text-lg font-semibold text-forte">Fechamentos de geração publicados</h2>
        <p className="text-sm text-fraco">
          Os três documentos de cada mês: o relatório de geração, o anexo de paradas e o resumo
          executivo.
        </p>
      </div>

      {/* A frase é do SERVIDOR. Reabrir um fechamento no meuWatt o tira do portal sem apagar
          os arquivos, e o BFF responde isso com todas as letras — traduzir aqui viraria
          "erro de rede", mandando o cliente procurar o problema no lugar errado. */}
      {pdf.erro === null ? null : <Aviso tom="parado">{pdf.erro}</Aviso>}

      <Tela4Estados leitura={leitura}>
        {(dados) => (
          <div className="space-y-4">
            {dados.aviso === null ? null : <Aviso>{dados.aviso}</Aviso>}
            {dados.documentos.length === 0 ? (
              <Vazio
                titulo="Nenhum fechamento publicado"
                // Vazio ≠ erro: o servidor respondeu. E a resposta tem um porquê preciso —
                // esta lista mostra só o que a equipe ENVIOU ao cliente; um fechamento
                // gerado e não enviado não aparece, e nada está quebrado.
                descricao="Aqui aparece o fechamento depois que a equipe o envia. Assim que o primeiro for enviado, os PDFs ficam disponíveis nesta tela."
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
