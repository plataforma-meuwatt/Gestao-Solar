/**
 * Registro de acessos — quem entrou, onde e de onde (pedido do dono, 24/11/2026: "o GS é o detentor dos acessos, quero
 * que ele tenha a auditoria completa dos logs de acessos de cada pessoa").
 *
 * Toda entrada em qualquer sistema da família passa pelo GS, então o registro está aqui: a entrada no GS, a entrada em
 * cada sistema pelo GS (meuWatt, meuPlano, meuGuarda, TermoVision, o conector do Claude), as senhas erradas e os
 * bloqueios, as trocas de senha e as mudanças de acesso, com quem fez. A mesma tela nos dois portões: no adm-gs, tudo
 * (e por empresa); no oem-gs, só as pessoas da empresa. Os filtros vão ao servidor e moram no endereço (a tela
 * Usuários abre aqui com `?usuario=`); os textos vêm prontos do servidor.
 */

import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio, type Tom } from '@/components/base'
import {
  acessosDaEmpresa,
  acessosDaPlataforma,
  listarEmpresas,
  type Acesso,
  type FiltroAcessos,
} from '@/features/api'
import { quando } from '@/features/rotulos'
import { mensagemDeErro } from '@/lib/api'

function tom(a: Acesso): Tom {
  if (!a.ok) return 'parado'
  return a.acao === 'senha' || a.acao === 'acesso' ? 'alerta' : 'ok'
}

export function Acessos({ daEmpresa }: { daEmpresa: boolean }) {
  const [params, setParams] = useSearchParams()
  // `de` ausente = o período padrão do servidor (os últimos 30 dias, pela data dele); `de=` vazio = sem limite
  const dePedido = params.get('de')
  const ate = params.get('ate') ?? ''
  const empresa = params.get('empresa') ?? ''
  const usuario = params.get('usuario') ?? ''
  const sistema = params.get('sistema') ?? ''
  const soRecusas = params.get('recusas') === '1'
  const busca = params.get('busca') ?? ''
  const [digitada, setDigitada] = useState(busca)

  function mudar(chave: string, valor: string) {
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        if (valor || chave === 'de') n.set(chave, valor)
        else n.delete(chave)
        return n
      },
      { replace: true },
    )
  }

  // a busca vai ao servidor depois de uma pausa na digitação, não a cada letra; o endereço que muda por fora (o menu)
  // traz o campo junto
  useEffect(() => setDigitada(busca), [busca])
  useEffect(() => {
    if (digitada.trim() === busca) return
    const t = setTimeout(() => mudar('busca', digitada.trim()), 400)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `mudar` só escreve no endereço
  }, [digitada])

  const { data: empresas } = useQuery({
    queryKey: ['empresas'],
    queryFn: listarEmpresas,
    enabled: !daEmpresa,
  })
  const filtro: FiltroAcessos = {
    empresa_id: !daEmpresa && empresa ? Number(empresa) : undefined,
    usuario_id: usuario ? Number(usuario) : undefined,
    sistema: sistema || undefined,
    so_recusas: soRecusas || undefined,
    de: dePedido || undefined,
    todo_periodo: dePedido === '' || undefined,
    ate: ate || undefined,
    busca: busca || undefined,
    limite: 1000,
  }
  const { data, isLoading, isFetching, isPlaceholderData, error } = useQuery({
    queryKey: ['acessos', daEmpresa ? 'empresa' : 'plataforma', filtro],
    queryFn: () => (daEmpresa ? acessosDaEmpresa(filtro) : acessosDaPlataforma(filtro)),
    placeholderData: (anterior) => anterior,
  })

  const linhas = data?.acessos ?? []
  const entradas = linhas.filter((a) => a.ok && a.acao === 'entrou').length
  const passes = linhas.filter((a) => a.ok && a.acao === 'passe').length
  const recusas = linhas.filter((a) => !a.ok).length
  // o período aplicado é o que o servidor diz (o padrão dele quando a tela não pediu um)
  const de = dePedido ?? data?.de ?? ''
  const filtrando = Boolean(empresa || usuario || sistema || soRecusas || de || ate || busca)

  return (
    <Pagina
      titulo="Registro de acessos"
      apoio={
        daEmpresa
          ? 'Quem da empresa entrou no Gestão Solar e a que sistema o GS entregou o passe, de onde e com que aparelho, as senhas erradas e os bloqueios, as trocas de senha e as mudanças de acesso, com quem fez. Se o sistema aceitou o passe, e o login direto na tela de cada sistema, ficam no registro dele.'
          : 'Tudo o que passa pelo GS: quem entrou no Gestão Solar e a que sistema o GS entregou o passe, de onde e com que aparelho, as senhas erradas (inclusive de login que não é conta) e os bloqueios, as trocas de senha e as mudanças de acesso, com quem fez. Se o sistema aceitou o passe, e o login direto na tela de cada sistema, ficam no registro dele.'
      }
    >
      {usuario ? (
        <div className="flex flex-wrap items-center gap-2 mb-3 text-sm">
          <span className="text-corpo break-words">
            Só os acessos de{' '}
            <span className="text-forte">
              {isPlaceholderData || (isFetching && !data?.pessoa) ? '…' : data?.pessoa ?? 'uma pessoa fora do seu alcance'}
            </span>
          </span>
          <button className="btn-fantasma" onClick={() => mudar('usuario', '')}>
            <X size={13} />
            Ver de todos
          </button>
        </div>
      ) : null}
      <div className={`grid gap-3 mb-3 ${daEmpresa ? 'sm:grid-cols-2' : 'sm:grid-cols-3'}`}>
        {!daEmpresa ? (
          <select
            className="campo"
            value={empresa}
            onChange={(e) => mudar('empresa', e.target.value)}
            aria-label="Empresa"
          >
            <option value="">Todas as empresas</option>
            {(empresas ?? []).map((e) => (
              <option key={e.id} value={e.id}>
                {e.nome}
              </option>
            ))}
          </select>
        ) : null}
        <select className="campo" value={sistema} onChange={(e) => mudar('sistema', e.target.value)} aria-label="Sistema">
          <option value="">Todos os sistemas</option>
          {(data?.sistemas ?? []).map((s) => (
            <option key={s.chave} value={s.chave}>
              {s.rotulo}
            </option>
          ))}
        </select>
        <input
          className="campo"
          placeholder="buscar pessoa, login, IP ou motivo"
          value={digitada}
          onChange={(e) => setDigitada(e.target.value)}
          aria-label="Buscar nos acessos"
        />
      </div>
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <label className="grid gap-1">
          <span className="rotulo-campo">De</span>
          <input type="date" className="campo" value={de} onChange={(e) => mudar('de', e.target.value)} />
        </label>
        <label className="grid gap-1">
          <span className="rotulo-campo">Até</span>
          <input type="date" className="campo" value={ate} onChange={(e) => mudar('ate', e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm text-corpo pb-2">
          <input type="checkbox" checked={soRecusas} onChange={(e) => mudar('recusas', e.target.checked ? '1' : '')} />
          Só recusas e bloqueios
        </label>
        {data ? (
          <p className="text-xs text-fraco pb-2 sm:ml-auto">
            {isFetching ? 'atualizando… · ' : ''}
            {linhas.length.toLocaleString('pt-BR')} registro(s) · {entradas.toLocaleString('pt-BR')} entrada(s) no GS ·{' '}
            {passes.toLocaleString('pt-BR')} passe(s) · {recusas.toLocaleString('pt-BR')} recusa(s)
            {linhas.length >= data.limite
              ? ` · são os ${data.limite.toLocaleString('pt-BR')} mais recentes: encurte o período para ver os anteriores`
              : ''}
          </p>
        ) : null}
      </div>

      <Cartao>
        {isLoading ? (
          <Carregando />
        ) : error ? (
          <div className="p-5">
            <Erro>{mensagemDeErro(error)}</Erro>
          </div>
        ) : !linhas.length ? (
          <Vazio
            titulo={filtrando ? 'Nenhum acesso com esses filtros' : 'Nenhum acesso registrado ainda'}
            descricao={
              filtrando
                ? `${dePedido === null && de ? 'A tela abre nos últimos 30 dias. ' : ''}Mude o período ou limpe os filtros para ver mais.`
                : 'Cada entrada no Gestão Solar e em cada sistema pelo GS aparece aqui na hora.'
            }
          />
        ) : (
          linhas.map((a, i) => <LinhaDoAcesso key={a.id} acesso={a} primeiro={i === 0} daEmpresa={daEmpresa} />)
        )}
      </Cartao>
    </Pagina>
  )
}

/** Um acesso. Fechado: quando, quem, o quê, onde; aberto: o que foi digitado e o aparelho inteiro. */
function LinhaDoAcesso({ acesso: a, primeiro, daEmpresa }: { acesso: Acesso; primeiro: boolean; daEmpresa: boolean }) {
  const [aberta, setAberta] = useState(false)
  return (
    <div className={primeiro ? '' : 'border-t border-borda'}>
      <button
        className="w-full text-left px-5 py-3 flex items-start gap-3 hover:bg-superficie-alta"
        onClick={() => setAberta((v) => !v)}
        aria-expanded={aberta}
      >
        {aberta ? (
          <ChevronDown size={14} className="shrink-0 text-fraco mt-1" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-fraco mt-1" />
        )}
        <span className="min-w-0 flex-1 grid gap-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-sm text-forte break-words">{a.quem}</span>
            {!daEmpresa && a.empresa ? <span className="text-xs text-fraco">{a.empresa}</span> : null}
            <Selo tom={tom(a)}>{a.acao_rotulo}</Selo>
            <span className="text-xs text-rotulo">{a.sistema_rotulo}</span>
          </span>
          {a.motivo || a.por ? (
            <span className="text-xs text-corpo break-words">
              {a.motivo}
              {a.por ? `${a.motivo ? ' · ' : ''}feito por ${a.por}` : ''}
            </span>
          ) : null}
          <span className="text-xs text-fraco break-words">
            {quando(a.em)} · {a.ip ? `${a.ip} · ` : ''}
            {a.aparelho}
          </span>
        </span>
      </button>
      {aberta ? (
        <div className="px-5 pb-4 pl-12 grid gap-2 text-xs text-rotulo">
          <p className="break-words">
            <span className="rotulo-campo">Digitado no login</span> {a.login || '—'}
          </p>
          <p className="break-words">
            <span className="rotulo-campo">Aparelho (como o navegador se apresentou)</span>{' '}
            {a.aparelho_completo || 'não informado'}
          </p>
        </div>
      ) : null}
    </div>
  )
}
