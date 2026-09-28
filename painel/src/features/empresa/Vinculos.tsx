/**
 * Qual empresa do meuWatt e qual do meuPlano são esta — a sua.
 *
 * **Quem casa é quem tem o token, e é você.** A plataforma cadastra a empresa e o usuário
 * dela; ela não tem credencial nos produtos. Montar esta lista com a credencial de serviço
 * mostraria a carteira de quem a gerou — que não é a sua. Aqui a leitura sai com o token
 * desta empresa, então o que aparece é exatamente o que a sua conta alcança lá.
 *
 * **Os dois cadastros são independentes.** Dá para contratar só a manutenção e nunca
 * existir no monitoramento: ter só um dos lados é normal. O que não pode é não ter
 * nenhum — sem vínculo, as telas desta empresa vêm vazias, porque não há de onde ler.
 *
 * Falta o token de um dos produtos? A lista dele vem vazia com a frase que o produto
 * escreveu ("Token revogado", "conta sem acesso"), e o conserto é em Conexões.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Aviso, Carregando, Erro, Pagina } from '@/components/base'
import {
  catalogoDeVinculos,
  salvarVinculos,
  type EmpresaDoProduto,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

export function VinculosDaEmpresa() {
  const empresa = useAuth((s) => s.empresa)
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['empresa', 'vinculos'],
    queryFn: catalogoDeVinculos,
  })

  // `undefined` = ainda não mexi; o que vale é o que veio do servidor.
  const [mw, setMw] = useState<number | null | undefined>(undefined)
  const [mp, setMp] = useState<number | null | undefined>(undefined)

  const escolhidoMw = mw === undefined ? (data?.mw_enterprise_id ?? null) : mw
  const escolhidoMp = mp === undefined ? (data?.mp_tenant_id ?? null) : mp

  const salvar = useMutation({
    mutationFn: () =>
      salvarVinculos({ mw_enterprise_id: escolhidoMw, mp_tenant_id: escolhidoMp }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresa'] })
    },
  })

  const semNenhum = escolhidoMw === null && escolhidoMp === null

  return (
    <Pagina
      titulo="Vínculos"
      apoio={
        empresa
          ? `Qual empresa do meuWatt e do meuPlano é ${empresa}`
          : 'Qual empresa do meuWatt e do meuPlano é a sua'
      }
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : (
        <div className="grid gap-5 max-w-3xl">
          <Aviso>
            Ter só um dos lados é normal — dá para contratar só a manutenção. O que não pode
            é não ter nenhum: sem vínculo, as telas desta empresa vêm vazias.
          </Aviso>

          {(data?.avisos ?? []).map((a) => (
            <Erro key={a}>{a}</Erro>
          ))}

          <Escolha
            titulo="Empresa no meuWatt"
            itens={data?.meuwatt ?? []}
            escolhido={escolhidoMw}
            aoEscolher={setMw}
          />
          <Escolha
            titulo="Empresa no meuPlano"
            itens={data?.meuplano ?? []}
            escolhido={escolhidoMp}
            aoEscolher={setMp}
          />

          {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
          {salvar.isSuccess && !salvar.isPending ? (
            <p className="text-sm text-ok">Vínculo salvo.</p>
          ) : null}
          {semNenhum ? (
            <p className="text-xs text-rotulo">
              Sem nenhum dos dois, as telas desta empresa continuarão vazias.
            </p>
          ) : null}

          <div className="flex justify-end">
            <button
              className="btn-primario"
              onClick={() => salvar.mutate()}
              disabled={salvar.isPending}
            >
              {salvar.isPending ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </div>
      )}
    </Pagina>
  )
}

function Escolha({
  titulo,
  itens,
  escolhido,
  aoEscolher,
}: {
  titulo: string
  itens: EmpresaDoProduto[]
  escolhido: number | null
  aoEscolher: (v: number | null) => void
}) {
  if (!itens.length) {
    return (
      <div>
        <p className="rotulo-campo">{titulo}</p>
        <p className="text-sm text-rotulo mt-1">
          Nada para escolher — ou o produto não respondeu (veja o aviso acima e o token em
          Conexões), ou a sua conta não enxerga nenhuma empresa lá.
        </p>
      </div>
    )
  }
  return (
    <div>
      <p className="rotulo-campo">{titulo}</p>
      <ul className="mt-2 grid gap-1">
        <li>
          <label className="flex items-center gap-2.5 px-3 py-2 rounded-campo hover:bg-superficie cursor-pointer">
            <input type="radio" checked={escolhido === null} onChange={() => aoEscolher(null)} />
            <span className="text-sm text-rotulo">Nenhuma</span>
          </label>
        </li>
        {itens.map((i) => (
          <li key={i.id}>
            <label className="flex items-center gap-2.5 px-3 py-2 rounded-campo hover:bg-superficie cursor-pointer">
              <input
                type="radio"
                checked={escolhido === i.id}
                onChange={() => aoEscolher(i.id)}
              />
              <span className="text-sm text-forte">{i.nome}</span>
              {i.documento ? <span className="text-xs text-fraco">{i.documento}</span> : null}
              {i.usinas !== null ? (
                <span className="text-xs text-fraco">
                  {i.usinas} usina(s) · {i.pessoas} pessoa(s)
                </span>
              ) : null}
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}
