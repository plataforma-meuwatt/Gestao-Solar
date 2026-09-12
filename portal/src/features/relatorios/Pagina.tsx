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
 * **Manutenção — três blocos, leituras independentes.** O relatório mensal LIBERADO
 * (`RelatorioMensal`), a consulta por período (`RelatorioManutencao`, lida ao vivo do
 * próprio ativo no meuPlano) e o pacote de fichas (`PacoteDeFichas`). Cada um com os seus
 * quatro estados: juntá-los numa leitura só faria a falha de um apagar o outro, e é o caso
 * que acontece primeiro (contrato novo, fichas já geradas).
 *
 * **E a ordem dos dois primeiros é a resposta à pergunta do título.** "O que eu levo para a
 * diretoria?" se responde com o documento que a equipe aprovou e ENTREGOU — o mensal, que
 * por isso vem primeiro. A consulta por período continua indispensável (é a única resposta
 * possível para "e este mês, como vai?", que ainda não fechou), mas é a segunda melhor: ela
 * é montada na hora e ninguém a assinou. Os dois saem da mesma apuração no meuPlano, então
 * não são dois cálculos; podem divergir com o TEMPO, e é por isso que cada um carrega o seu
 * carimbo — "publicado em" num, "montado agora" no outro.
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
 * ✅ A ABA ENERGIA DEIXOU DE ABRIR VAZIA (conferido em 12/09/2026, no upstream real): Porto
 * Ferreira tem o fechamento de agosto publicado com as TRÊS peças, e a tela as mostra. O
 * aviso abaixo fica como história do caso e como diagnóstico para a usina que ainda estiver
 * sem arquivo — o sintoma é idêntico, e a causa não é deste lado.
 *
 * ⚠ POR QUE A ABA ENERGIA ABRIA VAZIA (medido em 05/09/2026, no upstream real). O
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
  Pagina,
  Segmentado,
  Tela4Estados,
  Vazio,
} from '@/components/base'
import { AnelGS } from '@/components/marca'
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
import { RelatorioMensal } from '@/features/relatorios/RelatorioMensal'
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
          {/* O documento entregue vem antes da consulta ao vivo — ver o cabeçalho. */}
          <RelatorioMensal usinaId={usinaId} />
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

/**
 * O que cada peça do fechamento contém, em uma frase.
 *
 * É descrição do PRODUTO — o que aquele documento é, sempre —, e não dado de medição: o
 * "Anexo de paradas" contém as paradas do mês em qualquer usina e em qualquer competência.
 * Por isso pode morar aqui, ao lado do nome que já mora. O que nunca moraria aqui é um
 * número, uma contagem ou uma data: essas vêm do servidor, no `Documento`.
 */
const O_QUE_CONTEM: Record<string, string> = {
  geracao: 'A energia medida do mês contra a meta do projeto, dia a dia e por inversor.',
  paradas: 'Cada parada do mês: quando começou, quanto durou e quanta energia deixou de gerar.',
  resumo: 'As duas páginas que vão à diretoria — o veredito do mês, sem o detalhamento.',
}

/** O nome que o cliente lê. Kind desconhecido sai com o nome que o servidor mandou. */
function nomeDaPeca(tipo: string, arquivo: ArquivoDoDocumento | null): string {
  const conhecido = NOME_DO_ARQUIVO[tipo]
  if (conhecido) return conhecido
  if (arquivo !== null && arquivo.nome) return arquivo.nome
  return tipo
}

/**
 * O cartão de UMA peça do fechamento — publicada ou não.
 *
 * **A peça que falta não desaparece e não fica cinza-morta.** Ela aparece com a capa vazada,
 * a frase que explica o que ela seria, e o caminho para pedi-la. Escondê-la deixaria o
 * cliente sem saber se o Resumo Executivo não existe naquele mês ou se a tela esqueceu de
 * mostrá-lo — e é justamente o resumo que a diretoria pede.
 *
 * A capa tem o anel da marca porque um PDF não tem miniatura antes de ser aberto, e uma
 * caixa vazia de 132px se lê como imagem que não carregou.
 */
function CartaoDaPeca({
  tipo,
  arquivo,
  documentoId,
  tom,
  baixando,
  aoBaixar,
}: {
  tipo: string
  arquivo: ArquivoDoDocumento | null
  documentoId: number
  tom?: string
  baixando: string | null
  aoBaixar: (marca: string, caminho: string, nome: string) => void
}) {
  const nome = nomeDaPeca(tipo, arquivo)
  const marca = `${documentoId}-${tipo}`
  const publicada = arquivo !== null
  return (
    <div
      className={`overflow-hidden rounded-card border ${
        publicada ? 'border-borda bg-superficie' : 'border-dashed border-borda'
      }`}
    >
      <div
        className={`flex h-[132px] items-center justify-center ${publicada ? 'bg-afundado' : ''}`}
        style={
          publicada
            ? undefined
            : {
                // A hachura diz "vazio de propósito". Um fundo chapado diria "carregando".
                backgroundImage:
                  'repeating-linear-gradient(135deg, rgba(255,255,255,.035) 0 6px, transparent 6px 12px)',
              }
        }
      >
        <AnelGS tom={publicada ? tom : undefined} tracejado={!publicada} />
      </div>
      <div className="border-t border-borda p-5">
        <p className="rotulo-secao">{publicada ? 'Publicado' : 'Não publicado'}</p>
        <h4 className="mt-2 text-base font-semibold text-forte">{nome}</h4>
        {O_QUE_CONTEM[tipo] ? (
          <p className="mt-1.5 text-[13px] leading-relaxed text-fraco">{O_QUE_CONTEM[tipo]}</p>
        ) : null}
        <div className="mt-4">
          {publicada ? (
            <Botao
              variante="secundario"
              desabilitado={baixando !== null}
              onClick={() =>
                aoBaixar(
                  marca,
                  caminhoDoArquivo(documentoId, tipo),
                  arquivo.nome ? arquivo.nome : `${marca}.pdf`,
                )
              }
            >
              {baixando === marca ? 'Abrindo…' : 'Abrir PDF'}
            </Botao>
          ) : (
            // Não é botão: não há rota de pedido no BFF, e um botão que não faz nada é pior
            // que nenhum. É a frase que diz a quem pedir.
            <p className="text-[13px] text-fraco">
              Para publicar esta peça, peça ao seu gestor de conta — ela é gerada no meuWatt.
            </p>
          )}
        </div>
      </div>
    </div>
  )
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
    <Cartao className="p-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-forte">{d.nome}</h3>
          <p className="mono mt-1 text-xs text-fraco">
            {d.periodo ? `${d.periodo} · ` : ''}
            {dataCurta(d.de)} a {dataCurta(d.ate)}
          </p>
        </div>
        <span className="text-xs text-fraco">publicado em {dataPorExtenso(d.publicado_em)}</span>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {PECAS_DO_FECHAMENTO.map((tipo) => (
          <CartaoDaPeca
            key={tipo}
            tipo={tipo}
            arquivo={porTipo.get(tipo) ?? null}
            documentoId={d.id}
            // O anexo de paradas fala de interrupção, e o tom dele diz isso na capa. Não é
            // veredito sobre o mês: é a espécie do documento, que é fixa.
            tom={tipo === 'paradas' ? 'parado' : undefined}
            baixando={baixando}
            aoBaixar={aoBaixar}
          />
        ))}
        {extras.map((a) => (
          <CartaoDaPeca
            key={a.tipo}
            tipo={a.tipo}
            arquivo={a}
            documentoId={d.id}
            baixando={baixando}
            aoBaixar={aoBaixar}
          />
        ))}
      </div>
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
