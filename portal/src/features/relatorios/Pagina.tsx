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
 * **Energia — e a ponte para a planilha.** Muita gente vem procurar aqui os números brutos
 * para trabalhar no Excel, e é o instinto certo: é nesta tela que se buscam arquivos. Mas
 * aquilo é só GERAÇÃO e mora em `/energia/dados` ("Baixar dados"). No pé da aba fica uma
 * linha dizendo onde é — `PonteParaDados`, fora do `Tela4Estados`, porque a lista de
 * fechamentos vazia é justamente quando saber disso mais importa.
 *
 * Só a aba aberta é montada. Ler as quatro origens de uma vez custaria caro à toa — o
 * inventário de fichas mede o tamanho de cada PDF no armazenamento — e o cliente que veio
 * buscar o fechamento de agosto não pediu nada disso.
 *
 * Nenhum PDF é link comum. As rotas de arquivo do BFF exigem a sessão em CABEÇALHO, e a saída
 * fácil — token na query string — é a proibida: endereço entra em log e em histórico. Por
 * isso tudo passa por `abrirPdf`/`baixarArquivo` (fetch + Bearer + blob).
 *
 * ⚠ POR QUE A ABA ENERGIA AINDA ABRE VAZIA (medido em 05/09/2026, no upstream real). O
 * caminho está inteiro deste lado: o BFF aceita as três peças (`geracao`, `paradas`,
 * `resumo`), recusa qualquer outra com 422, e a tela nomeia cada uma. O que não existe é o
 * ARQUIVO: `GET /reports/portal` do meuWatt devolve hoje cinco fechamentos — Tietê, Ouro
 * Fino, Pirapozinho, Pereiras e Pirassununga —, **todos com `sent_at` preenchido e todos com
 * `files: []`**. Nenhum PDF publicado. Isso não se conserta em código: alguém com perfil de
 * administrador no meuWatt precisa regerar e enviar os fechamentos. Até lá, o vazio que esta
 * tela mostra é a verdade medida, não uma falha a caçar aqui. (Reabrir um fechamento zera o
 * envio sem apagar os arquivos — por isso o reenvio é preciso mesmo onde o PDF já existiu.)
 */

import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import {
  Aviso,
  Botao,
  Cartao,
  LinhaNavegacao,
  Num,
  Pagina,
  Segmentado,
  Tela4Estados,
  Vazio,
} from '@/components/base'
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
import { SECOES, paraDaSecao } from '@/shell/menu'

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
        <div className="space-y-10">
          <DocumentosPublicados usinaId={usinaId} />
          <PonteParaDados usinaId={usinaId} />
        </div>
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

/**
 * A ponte para "Baixar dados" — a tela que NÃO mora aqui.
 *
 * Procurar a planilha em Relatórios é o instinto certo: é aqui que o cliente vem quando
 * precisa de um arquivo. Mas a exportação de dados brutos é só de GERAÇÃO (o contrato do
 * meuWatt não tem uma linha de manutenção), e esta tela é a única de família `geral`
 * justamente por guardar as duas — pôr a planilha dentro dela faria "nenhum fechamento
 * publicado" e "sem dados brutos" parecerem o mesmo problema, quando são coisas opostas:
 * aqui só entra o PDF que a equipe PUBLICOU; lá nada foi publicado, o cliente é quem monta.
 *
 * Então em vez de uma segunda tela, uma linha que **diz onde mora** — a regra da casa
 * aplicada à navegação. Ela fica FORA do `Tela4Estados`: a lista de fechamentos vazia (ou
 * fora do ar) é exatamente o momento em que o cliente mais precisa saber que os números
 * existem noutro lugar.
 *
 * O endereço vem de `paraDaSecao`, nunca de `/usinas/${id}/energia/dados` escrito à mão —
 * foi a concatenação crua que já mandou item de menu para uma rota que só existe como
 * redirecionamento. Sem a entrada no catálogo (ou sem usina), não há destino e a linha não
 * aparece: seta sem clique é promessa que o portal não cumpre.
 */
function PonteParaDados({ usinaId }: { usinaId: number }) {
  const navegar = useNavigate()
  const secao = SECOES.find((s) => s.fim === '/energia/dados')
  const para = secao ? paraDaSecao(secao, usinaId) : null
  if (para === null) return null

  return (
    <Cartao>
      <LinhaNavegacao
        titulo="Baixar dados desta usina"
        detalhe="Precisa dos números para a sua planilha? A exportação em XLSX fica na Geração de energia."
        aoAbrir={() => navegar(para)}
      />
    </Cartao>
  )
}

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
