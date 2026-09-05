/**
 * As fotos de uma ficha — a evidência do que o técnico viu.
 *
 * O portal mostrava a tarefa como um item de lista com um botão de PDF; a foto que prova o
 * ponto de aquecimento ou o cabo solto só existia dentro do documento. Aqui ela aparece na
 * tela, ao lado da resposta que a explica.
 *
 * Quatro decisões que não são detalhe:
 *
 * **A imagem é BAIXADA, não apontada.** A rota é autenticada e a sessão vai em cabeçalho;
 * `<img src>` não manda cabeçalho e token em URL é proibido. Ver `imagem.ts`.
 *
 * **Miniatura na grade, original só ao clicar.** A ficha coletiva dos inversores de Porto
 * Ferreira tem 61 fotos: baixar todas em tamanho cheio para desenhar quadrados de 92 px
 * gastaria a rede do cliente para não mostrar nada a mais.
 *
 * **Poucas de cada vez.** Sessenta e uma miniaturas pedidas ao mesmo tempo formam uma fila
 * que o servidor não vence, e o que aparece é o quadro escuro em TODAS — inclusive nas que
 * teriam vindo. Seis por bloco, e o resto sob um clique.
 *
 * **Falha de imagem se explica.** Um quadrado vazio não diz se a foto sumiu, se a sessão
 * venceu ou se a rede caiu; o quadro mostra o MOTIVO que o servidor escreveu e aceita um
 * clique para tentar de novo.
 */

import { useEffect, useState } from 'react'

import { Modal } from '@/components/base'
import { mensagemDeErro } from '@/lib/api'
import { bytesDaImagem } from '@/features/tarefa/imagem'
import { type Foto } from '@/features/tarefa/api'

/** Quantas miniaturas nascem carregando. O resto espera o clique em "ver todas". */
const DE_CARA = 6

/**
 * O endereço local da imagem: `null` enquanto baixa, o motivo em texto quando não vem.
 *
 * O `blob:` criado aqui é REVOGADO na limpeza do efeito — sem isso, cada foto aberta segura
 * os próprios bytes até a aba fechar, e numa ficha de 61 fotos isso é a ficha inteira presa
 * na memória do cliente.
 *
 * `tentativa` no fim das dependências é o que faz "clique para tentar" tentar de novo; sem
 * ela o efeito não roda outra vez e o botão seria enfeite.
 */
function useImagem(caminho: string, chave: string, tentativa: number) {
  const [url, setUrl] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    let vivo = true
    let criada: string | null = null
    setErro(null)
    // O `blob:` anterior é revogado na limpeza, e um `<img>` apontado para endereço revogado
    // fica quebrado em silêncio — então a imagem some junto com ele.
    setUrl(null)

    bytesDaImagem(caminho, chave)
      .then((blob) => {
        if (!vivo) return
        criada = URL.createObjectURL(blob)
        setUrl(criada)
      })
      .catch((e: unknown) => {
        if (vivo) setErro(mensagemDeErro(e))
      })

    return () => {
      vivo = false
      if (criada) URL.revokeObjectURL(criada)
    }
  }, [caminho, chave, tentativa])

  return { url, erro }
}

export function Fotos({ fotos, titulo }: { fotos: Foto[] | number; titulo?: string }) {
  const [aberta, setAberta] = useState<Foto | null>(null)
  const [todas, setTodas] = useState(false)

  /*
   * O tipo aceita `number` de propósito.
   *
   * O deploy do BFF não é instantâneo: por alguns minutos a tela nova conversa com o servidor
   * antigo, onde `fotos` do equipamento ainda podia ser a CONTAGEM. Sem esta porta, o `.map`
   * de um número derrubaria a ficha inteira — e a tela quebrada duraria mais que a janela do
   * deploy, porque o cache de leitura guarda a resposta antiga em disco.
   */
  const lista = Array.isArray(fotos) ? fotos : []
  if (lista.length === 0) return null

  const visiveis = todas ? lista : lista.slice(0, DE_CARA)
  const escondidas = lista.length - visiveis.length

  return (
    <div className="mt-3">
      {titulo ? (
        <p className="mb-1.5 text-[11px] uppercase tracking-wide text-rotulo">
          {titulo} · {lista.length}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        {visiveis.map((f) => (
          <Miniatura key={f.id} foto={f} aoAbrir={() => setAberta(f)} />
        ))}

        {escondidas > 0 ? (
          <button
            type="button"
            onClick={() => setTodas(true)}
            className="flex h-[92px] w-[92px] flex-col items-center justify-center gap-0.5 rounded-chip border border-borda bg-superficie-alta text-center transition hover:border-borda-forte"
          >
            <span className="font-mono text-base font-semibold text-ambar-texto">
              +{escondidas}
            </span>
            <span className="text-[10px] text-fraco">ver todas</span>
          </button>
        ) : null}
      </div>

      <Modal
        titulo={aberta?.legenda ?? 'Foto da ficha'}
        aberto={aberta !== null}
        aoFechar={() => setAberta(null)}
        largura="max-w-4xl"
      >
        {aberta ? <Ampliada foto={aberta} /> : null}
      </Modal>
    </div>
  )
}

/** Um quadrado da grade, com os três estados que ele pode ter. */
function Miniatura({ foto, aoAbrir }: { foto: Foto; aoAbrir: () => void }) {
  const [tentativa, setTentativa] = useState(0)
  const { url, erro } = useImagem(foto.thumb_url, `${foto.id}-thumb`, tentativa)

  if (erro) {
    return (
      <button
        type="button"
        onClick={() => setTentativa((n) => n + 1)}
        className="flex h-[92px] w-[92px] flex-col items-center justify-center gap-1 rounded-chip border border-tom-parado/30 bg-tom-parado/10 px-1.5 text-center"
      >
        {/* O MOTIVO, não "falhou". Um quadrado que só diz que deu errado manda todo mundo
            adivinhar entre sessão vencida, foto apagada e rede caída. */}
        <span className="line-clamp-3 text-[10px] leading-tight text-corpo">{erro}</span>
        <span className="text-[10px] text-fraco">clique para tentar</span>
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={aoAbrir}
      disabled={url === null}
      className="h-[92px] w-[92px] overflow-hidden rounded-chip border border-borda bg-superficie-alta transition hover:border-borda-forte disabled:cursor-default"
    >
      {url ? (
        <img
          src={url}
          alt={foto.legenda ?? 'Foto da ficha'}
          className="h-full w-full object-cover"
        />
      ) : (
        <span className="block h-full w-full animate-pulse bg-superficie-destacada" />
      )}
    </button>
  )
}

/**
 * A foto em tamanho cheio, dentro da `Modal` do produto (fecha no ESC e prende o foco).
 *
 * `object-contain` mostra a foto inteira, que é o que se quer de uma evidência: cortar para
 * preencher a caixa esconderia justamente a borda onde costuma estar o dano.
 */
function Ampliada({ foto }: { foto: Foto }) {
  const { url, erro } = useImagem(foto.url, `${foto.id}-cheia`, 0)

  return (
    <div>
      {erro ? (
        <p className="py-10 text-center text-sm text-tom-parado">
          Não deu para carregar esta foto: {erro}
        </p>
      ) : url ? (
        <img
          src={url}
          alt={foto.legenda ?? 'Foto da ficha'}
          className="max-h-[70vh] w-full object-contain"
        />
      ) : (
        <div className="h-[40vh] animate-pulse rounded-campo bg-superficie-alta" />
      )}
      {foto.legenda ? <p className="mt-3 text-sm text-corpo">{foto.legenda}</p> : null}
    </div>
  )
}
