/**
 * O seletor de usina da barra do topo — o contexto de tudo o que vem abaixo.
 *
 * Três decisões que valem a pena guardar:
 *
 * **Os nomes são DADO.** Vêm de `GET /api/v1/plants`, a mesma leitura que a Visão geral usa
 * (o cache do TanStack não a busca duas vezes). Nome de usina escrito no código é a violação
 * mais fácil de cometer e a mais difícil de perceber: funciona até o cliente seguinte.
 *
 * **Trocar de usina mantém a SEÇÃO.** Quem está comparando o cronograma de uma continua no
 * cronograma da outra. Voltar para a home a cada troca obrigaria a refazer o caminho, e é
 * exatamente o que um diretor com cinco usinas faz o dia inteiro.
 *
 * **Uma usina só não vira pergunta.** Com um item, o seletor é um rótulo — oferecer escolha
 * onde não há escolha é ruído.
 */

import { useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Combobox } from '@/components/base'
import { useLeitura } from '@/lib/leitura'
import { secaoDoCaminho } from '@/shell/menu'
import { useAuth } from '@/store/auth'
import { useUsina } from '@/store/usina'

export type UsinaDaLista = {
  id: number
  nome: string
  cidade: string | null
  uf: string | null
}

export type UsinasOut = { usinas: UsinaDaLista[] }

export function SeletorUsina({ atual }: { atual: number | null }) {
  const navigate = useNavigate()
  const local = useLocation()
  const usuario = useAuth((s) => s.usuario)
  const escolher = useUsina((s) => s.escolher)

  const { dados } = useLeitura<UsinasOut>('plants')
  const usinas = dados?.usinas ?? []

  const opcoes = useMemo(
    () =>
      usinas.map((u) => ({
        valor: String(u.id),
        rotulo: u.nome,
        detalhe: [u.cidade, u.uf].filter(Boolean).join(', ') || undefined,
      })),
    [usinas],
  )

  if (opcoes.length === 0) return null

  const escolhida = usinas.find((u) => u.id === atual) ?? null

  if (opcoes.length === 1) {
    const unica = usinas[0]
    return (
      <button
        type="button"
        onClick={() => navigate(`/usinas/${unica.id}${secaoDoCaminho(local.pathname)}`)}
        className="truncate text-sm text-corpo hover:text-forte"
        title={unica.nome}
      >
        {unica.nome}
      </button>
    )
  }

  return (
    <Combobox
      opcoes={opcoes}
      valor={escolhida ? String(escolhida.id) : null}
      onEscolher={(valor) => {
        const novo = Number(valor)
        escolher(novo, usuario?.id ?? null)
        navigate(`/usinas/${novo}${secaoDoCaminho(local.pathname)}`)
      }}
      placeholder="Escolher usina…"
      className="w-full max-w-[18rem]"
    />
  )
}
