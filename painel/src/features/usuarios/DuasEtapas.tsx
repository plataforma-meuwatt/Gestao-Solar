/**
 * A verificação em duas etapas de uma conta (R12): a situação, e o "refazer" para quem perdeu o celular do
 * autenticador (no próximo login a pessoa cadastra de novo, e as sessões abertas dela acabam). A situação vem pronta da
 * API: `desligada` (o GS não pede o código agora), `ativa`, `a_cadastrar` (exigida e ainda sem o autenticador) ou
 * `nao_exigida`.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { refazerDuasEtapas } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const TEXTO: Record<string, string> = {
  ativa: 'Duas etapas: ativa',
  a_cadastrar: 'Duas etapas: cadastra no próximo login',
  desligada: 'Duas etapas: desligada no GS agora (ninguém precisa do código)',
}

export function DuasEtapasDaConta({
  situacao,
  conta,
  daEmpresa,
}: {
  situacao: string | undefined
  conta: number
  daEmpresa: boolean
}) {
  const qc = useQueryClient()
  const [confirmando, setConfirmando] = useState(false)
  const refazer = useMutation({
    mutationFn: () => refazerDuasEtapas(daEmpresa, conta),
    onSuccess: () => {
      setConfirmando(false)
      void qc.invalidateQueries()
    },
  })
  if (!situacao || !TEXTO[situacao]) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span>{TEXTO[situacao]}</span>
      {situacao === 'ativa' ? (
        confirmando ? (
          <>
            <span className="text-corpo">Refazer? Ela cadastra o autenticador de novo e sai de todos os aparelhos.</span>
            <button className="btn-fantasma" disabled={refazer.isPending} onClick={() => refazer.mutate()}>
              Refazer
            </button>
            <button className="btn-fantasma" onClick={() => setConfirmando(false)}>
              Não
            </button>
          </>
        ) : (
          <button className="btn-fantasma" onClick={() => setConfirmando(true)}>
            Refazer
          </button>
        )
      ) : null}
      {refazer.error ? <span className="text-parado">{mensagemDeErro(refazer.error)}</span> : null}
    </span>
  )
}
