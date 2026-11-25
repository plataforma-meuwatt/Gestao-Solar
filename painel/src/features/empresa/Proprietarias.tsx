/**
 * As proprietárias: as donas das usinas, empresas ou pessoas clientes da O&M (Plano Casa
 * GS, R11: "O GS cadastra as empresas de O&M e as proprietárias, com o tipo"). A gestão
 * delas (equipe, contratos, financeiro, OS) continua no meuPlano.
 *
 * Cada usina tem UMA dona, e cada dono de usina é de uma proprietária. As pessoas da
 * mesma proprietária podem receber as mesmas usinas (sem ela, uma usina tem um dono só).
 * O que cada pessoa VÊ continua sendo a concessão: "Dar as usinas às pessoas" soma as
 * usinas da dona à concessão de cada uma, e nada sai.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building } from 'lucide-react'
import { useState } from 'react'

import { Campo, Carregando, Cartao, Erro, Modal, Pagina, Vazio } from '@/components/base'
import {
  alterarProprietaria,
  criarProprietaria,
  criarUsinaNova,
  darUsinasDaProprietaria,
  importarProprietarias,
  pessoasDaProprietaria,
  proprietarias,
  usinasDaEmpresa,
  usinasDaProprietaria,
  usuariosDaEmpresa,
  type Proprietaria,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

const documento = (d: string | null) => {
  if (!d) return null
  if (d.length === 14) return d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5')
  if (d.length === 11) return d.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4')
  return d
}

export function ProprietariasDaEmpresa() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['empresa', 'proprietarias'], queryFn: proprietarias })
  const [nova, setNova] = useState<{ nome: string; documento: string } | null>(null)
  const [importado, setImportado] = useState<string[] | null>(null)
  const atualizar = () => qc.invalidateQueries({ queryKey: ['empresa'] })

  const criar = useMutation({
    mutationFn: criarProprietaria,
    onSuccess: () => {
      setNova(null)
      atualizar()
    },
  })
  const importar = useMutation({
    mutationFn: importarProprietarias,
    onSuccess: (r) => {
      setImportado(r.feito)
      atualizar()
    },
  })

  return (
    <Pagina
      titulo="Proprietárias"
      apoio="As donas das usinas: empresas ou pessoas clientes da O&M. Equipe, contratos e financeiro delas continuam no meuPlano."
    >
      <div className="grid gap-4">
        <div className="flex gap-2 flex-wrap">
          <button className="btn-secundario" onClick={() => setNova({ nome: '', documento: '' })}>
            Nova proprietária
          </button>
          <button className="btn-fantasma" disabled={importar.isPending} onClick={() => importar.mutate()}>
            {importar.isPending ? 'Importando do meuPlano…' : 'Importar do meuPlano'}
          </button>
        </div>
        {importar.error ? <Erro>{mensagemDeErro(importar.error)}</Erro> : null}
        {importado ? (
          <Cartao className="px-5 py-4">
            <p className="text-forte font-semibold mb-1">Importado do meuPlano</p>
            {importado.length ? (
              <ul className="text-sm text-rotulo grid gap-0.5">
                {importado.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-rotulo">Nada novo: o que o meuPlano tem já estava aqui.</p>
            )}
          </Cartao>
        ) : null}

        {nova ? (
          <Cartao className="px-5 py-4 grid gap-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Campo rotulo="Nome" value={nova.nome} onChange={(e) => setNova({ ...nova, nome: e.target.value })} />
              <Campo
                rotulo="CNPJ ou CPF (opcional)"
                value={nova.documento}
                onChange={(e) => setNova({ ...nova, documento: e.target.value })}
                inputMode="numeric"
              />
            </div>
            {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}
            <div className="flex gap-2">
              <button
                className="btn-secundario"
                disabled={criar.isPending}
                onClick={() => criar.mutate({ nome: nova.nome, documento: nova.documento || null })}
              >
                Criar
              </button>
              <button className="btn-fantasma" onClick={() => setNova(null)}>
                Cancelar
              </button>
            </div>
          </Cartao>
        ) : null}

        {isLoading ? (
          <Carregando />
        ) : error ? (
          <Erro>{mensagemDeErro(error)}</Erro>
        ) : !data?.length ? (
          <Vazio
            titulo="Nenhuma proprietária ainda"
            descricao="Importe do meuPlano as organizações donas de usina, ou crie uma."
          />
        ) : (
          data.map((p) => <CartaoDaProprietaria key={p.id} p={p} todas={data} aoMudar={atualizar} />)
        )}
      </div>
    </Pagina>
  )
}

function CartaoDaProprietaria({
  p,
  todas,
  aoMudar,
}: {
  p: Proprietaria
  todas: Proprietaria[]
  aoMudar: () => void
}) {
  const [editando, setEditando] = useState<{ nome: string; documento: string } | null>(null)
  const [escolha, setEscolha] = useState<'usinas' | 'pessoas' | null>(null)
  const [dado, setDado] = useState<string | null>(null)
  const [nova, setNova] = useState(false)
  const salvar = useMutation({
    mutationFn: (d: { nome?: string; documento?: string | null }) => alterarProprietaria(p.id, d),
    onSuccess: () => {
      setEditando(null)
      aoMudar()
    },
  })
  const dar = useMutation({
    mutationFn: () => darUsinasDaProprietaria(p.id),
    onSuccess: (r) => {
      const n = Object.values(r.pessoas).reduce((a, b) => a + b, 0)
      setDado(
        n
          ? `Feito: ${n} concessão(ões) nova(s) para ${Object.keys(r.pessoas).length} pessoa(s).`
          : 'Todas as pessoas já recebiam as usinas desta proprietária.',
      )
      aoMudar()
    },
  })

  return (
    <Cartao className="px-5 py-4 grid gap-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="text-forte font-semibold flex items-center gap-2">
            <Building size={16} className="text-rotulo" />
            {p.nome}
          </p>
          <p className="text-sm text-rotulo mt-1">
            {[documento(p.documento), p.mp_owner_id ? `meuPlano: organização ${p.mp_owner_id}` : 'não ligada ao meuPlano']
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            className="btn-fantasma"
            onClick={() => setEditando({ nome: p.nome, documento: p.documento ?? '' })}
          >
            Editar
          </button>
        </div>
      </div>

      {editando ? (
        <div className="grid gap-3 border-t border-borda pt-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Campo rotulo="Nome" value={editando.nome} onChange={(e) => setEditando({ ...editando, nome: e.target.value })} />
            <Campo
              rotulo="CNPJ ou CPF"
              value={editando.documento}
              onChange={(e) => setEditando({ ...editando, documento: e.target.value })}
              inputMode="numeric"
            />
          </div>
          {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
          <div className="flex gap-2 flex-wrap">
            <button
              className="btn-secundario"
              disabled={salvar.isPending}
              onClick={() => salvar.mutate({ nome: editando.nome, documento: editando.documento })}
            >
              Salvar
            </button>
            <button className="btn-fantasma" onClick={() => setEditando(null)}>
              Cancelar
            </button>
          </div>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="rotulo-campo">Usinas ({p.usinas.length})</p>
          {p.usinas.length ? (
            <ul className="text-sm text-rotulo grid gap-0.5">
              {p.usinas.map((u) => (
                <li key={u.id}>
                  <span className="text-fraco">{u.codigo}</span> {u.nome}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-fraco">Nenhuma usina desta dona ainda.</p>
          )}
          <div className="flex gap-2 flex-wrap mt-2">
            <button className="btn-fantasma" onClick={() => setEscolha('usinas')}>
              Escolher as usinas
            </button>
            <button className="btn-fantasma" onClick={() => setNova(true)}>
              Nova usina
            </button>
          </div>
        </div>
        <div>
          <p className="rotulo-campo">Pessoas ({p.pessoas.length})</p>
          {p.pessoas.length ? (
            <ul className="text-sm text-rotulo grid gap-0.5">
              {p.pessoas.map((u) => (
                <li key={u.id}>
                  {u.nome} <span className="text-fraco">({u.codigo})</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-fraco">Nenhum dono de usina nesta proprietária ainda.</p>
          )}
          <button className="btn-fantasma mt-2" onClick={() => setEscolha('pessoas')}>
            Escolher as pessoas
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap border-t border-borda pt-3">
        <button
          className="btn-secundario"
          disabled={dar.isPending || !p.usinas.length || !p.pessoas.length}
          onClick={() => dar.mutate()}
        >
          {dar.isPending ? 'Dando…' : 'Dar as usinas às pessoas'}
        </button>
        <span className="text-sm text-rotulo">
          {dado ?? 'Cada pessoa passa a receber todas as usinas desta proprietária; o que ela já recebe fica.'}
        </span>
      </div>
      {dar.error ? <Erro>{mensagemDeErro(dar.error)}</Erro> : null}

      {nova ? <NovaUsina p={p} aoFechar={() => setNova(false)} aoMudar={aoMudar} /> : null}
      {escolha ? (
        <Escolha p={p} todas={todas} qual={escolha} aoFechar={() => setEscolha(null)} aoMudar={aoMudar} />
      ) : null}
    </Cartao>
  )
}

function Escolha({
  p,
  todas,
  qual,
  aoFechar,
  aoMudar,
}: {
  p: Proprietaria
  todas: Proprietaria[]
  qual: 'usinas' | 'pessoas'
  aoFechar: () => void
  aoMudar: () => void
}) {
  const usinas = useQuery({ queryKey: ['empresa', 'usinas'], queryFn: usinasDaEmpresa, enabled: qual === 'usinas' })
  const pessoas = useQuery({ queryKey: ['empresa', 'usuarios'], queryFn: usuariosDaEmpresa, enabled: qual === 'pessoas' })
  const atuais = (qual === 'usinas' ? p.usinas : p.pessoas).map((x) => x.id)
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set(atuais))
  // de quem é hoje cada usina ou pessoa: a outra proprietária é dita, e a escolha a muda
  const deOutra = new Map<number, string>()
  for (const o of todas)
    if (o.id !== p.id) for (const x of qual === 'usinas' ? o.usinas : o.pessoas) deOutra.set(x.id, o.nome)

  const salvar = useMutation({
    mutationFn: () => (qual === 'usinas' ? usinasDaProprietaria : pessoasDaProprietaria)(p.id, [...marcadas]),
    onSuccess: () => {
      aoMudar()
      aoFechar()
    },
  })

  const lista =
    qual === 'usinas'
      ? (usinas.data ?? []).map((u) => ({ id: u.id, nome: u.nome, extra: u.ativo ? null : 'desligada' }))
      : (pessoas.data ?? [])
          // quem é membro vindo de outra O&M tem a proprietária cuidada lá: não aparece para marcar aqui
          .filter((u) => u.perfil === 'cliente' && u.de_origem !== false)
          .map((u) => ({ id: u.id, nome: `${u.nome} (${u.apelido})`, extra: u.ativo ? null : 'desligada' }))
  const carregando = qual === 'usinas' ? usinas.isLoading : pessoas.isLoading
  const erro = qual === 'usinas' ? usinas.error : pessoas.error

  return (
    <Modal titulo={`${qual === 'usinas' ? 'Usinas' : 'Pessoas'} de ${p.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-3">
        <p className="text-sm text-rotulo">
          {qual === 'usinas'
            ? 'Cada usina tem uma dona só: marcar aqui tira a usina da dona de antes.'
            : 'Só donos de usina desta empresa (quem vem de outra O&M tem a proprietária cuidada lá). Marcar aqui tira a pessoa da proprietária de antes, e das usinas dela; desmarcar tira a pessoa das usinas desta.'}
        </p>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Erro>{mensagemDeErro(erro)}</Erro>
        ) : !lista.length ? (
          <p className="text-sm text-fraco">
            {qual === 'usinas' ? 'Nenhuma usina nesta empresa.' : 'Nenhum dono de usina nesta empresa.'}
          </p>
        ) : (
          <ul className="grid gap-1 max-h-[50vh] overflow-y-auto">
            {lista.map((x) => (
              <li key={x.id}>
                <label className="flex items-start gap-2 text-sm text-forte cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={marcadas.has(x.id)}
                    onChange={(e) => {
                      const n = new Set(marcadas)
                      if (e.target.checked) n.add(x.id)
                      else n.delete(x.id)
                      setMarcadas(n)
                    }}
                  />
                  <span>
                    {x.nome}
                    {x.extra ? <span className="text-fraco"> · {x.extra}</span> : null}
                    {deOutra.has(x.id) ? <span className="text-fraco"> · hoje de {deOutra.get(x.id)}</span> : null}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}
        <div className="flex gap-2">
          <button className="btn-secundario" disabled={salvar.isPending || carregando} onClick={() => salvar.mutate()}>
            Salvar
          </button>
          <button className="btn-fantasma" onClick={aoFechar}>
            Cancelar
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** A usina nasce no GS, já com esta dona, e o GS a cria no meuPlano (docs/USINA_NASCE_NO_GS.md). */
function NovaUsina({ p, aoFechar, aoMudar }: { p: Proprietaria; aoFechar: () => void; aoMudar: () => void }) {
  const [d, setD] = useState({ nome: '', cidade: '', uf: '', kwp: '' })
  const criar = useMutation({
    mutationFn: (mesmoAssim: boolean) =>
      criarUsinaNova({
        nome: d.nome,
        cidade: d.cidade || null,
        uf: d.uf || null,
        kwp: d.kwp ? Number(d.kwp.replace(',', '.')) : null,
        proprietaria_id: p.id,
        mesmo_assim: mesmoAssim,
      }),
    onSuccess: (r) => {
      if (r.id) aoMudar()
    },
  })
  const r = criar.data
  return (
    <Modal titulo={`Nova usina de ${p.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-3">
        {r?.id ? (
          <>
            <p className="text-forte font-semibold">
              Usina {r.codigo} criada
            </p>
            <ul className="text-sm text-rotulo grid gap-0.5">
              {r.sistemas.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            <button className="btn-secundario" onClick={aoFechar}>
              Fechar
            </button>
          </>
        ) : (
          <>
            <p className="text-sm text-rotulo">
              A usina nasce no GS e é criada no meuPlano com esta proprietária. O meuWatt entra quando ela tiver coletor.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Campo rotulo="Nome" value={d.nome} onChange={(e) => setD({ ...d, nome: e.target.value })} />
              <Campo rotulo="Cidade" value={d.cidade} onChange={(e) => setD({ ...d, cidade: e.target.value })} />
              <Campo rotulo="UF" value={d.uf} maxLength={2} onChange={(e) => setD({ ...d, uf: e.target.value.toUpperCase() })} />
              <Campo rotulo="Potência (kWp)" value={d.kwp} inputMode="decimal" onChange={(e) => setD({ ...d, kwp: e.target.value })} />
            </div>
            {r?.parecidas.length ? (
              <div className="text-sm text-rotulo">
                <p className="text-forte font-semibold">Parece uma usina que já existe:</p>
                <ul className="grid gap-0.5">
                  {r.parecidas.map((x) => (
                    <li key={x.gs}>
                      {x.nome}
                      {x.distancia_km != null ? ` · a ${x.distancia_km} km` : ''}
                    </li>
                  ))}
                </ul>
                <p className="mt-1">Se for uma delas, não crie: ligue a que existe. Se for outra, crie mesmo assim.</p>
              </div>
            ) : null}
            {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}
            <div className="flex gap-2 flex-wrap">
              <button
                className="btn-secundario"
                disabled={criar.isPending || d.nome.trim().length < 2}
                onClick={() => criar.mutate(Boolean(r?.parecidas.length))}
              >
                {criar.isPending ? 'Criando…' : r?.parecidas.length ? 'É outra: criar mesmo assim' : 'Criar'}
              </button>
              <button className="btn-fantasma" onClick={aoFechar}>
                Cancelar
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
