/**
 * Empresas — a tela de entrada do adm-gs.
 *
 * Os clientes da PLATAFORMA são as empresas de O&M, e as empresas têm usuários (o modelo do
 * dono, 23/10/2026: "USUÁRIOS são as EMPRESAS de O&M e as empresas possuem USUÁRIOS, e eu
 * entro nas empresas e vejo usuários"). Daqui se entra em cada uma (`/empresas/:id`). A
 * lista inversa — todos os usuários, com a(s) empresa(s) de cada um — é a tela Usuários.
 *
 * É a única tela que mostra a lista inteira de empresas: nenhuma empresa sabe que as outras
 * existem, e por isso ela vive em `/api/painel/*`, atrás da área `empresas`.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, ChevronRight, Sun, Users } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio } from '@/components/base'
import { criarEmpresa, listarEmpresas, type Empresa } from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Empresas() {
  const { data, isLoading, error } = useQuery({ queryKey: ['empresas'], queryFn: listarEmpresas })
  const [novaAberta, setNovaAberta] = useState(false)

  return (
    <Pagina
      titulo="Empresas"
      apoio="Os clientes da plataforma: as empresas de O&M. Entre numa empresa para ver e cuidar dos usuários dela — gerentes, técnicos e donos de usina."
      acao={
        <button className="btn-primario" onClick={() => setNovaAberta(true)}>
          Cadastrar empresa
        </button>
      }
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : !data?.length ? (
        <Vazio
          titulo="Nenhuma empresa cadastrada"
          descricao="Cadastre a primeira empresa de O&M; depois, entre nela e crie o gerente."
        />
      ) : (
        <div className="grid gap-3">
          {data.map((e) => (
            <LinhaDaEmpresa key={e.id} empresa={e} />
          ))}
        </div>
      )}

      {novaAberta ? <Nova aoFechar={() => setNovaAberta(false)} /> : null}
    </Pagina>
  )
}

/** "conectada" / "com problema" / "não conectada" — só o estado da conta DA EMPRESA no
 *  produto; o token é dela, e o adm não tem token. */
export function estadoDaConexao(estado: string | null): string {
  if (estado === 'ok') return 'conectado'
  if (estado === 'falhou') return 'com problema'
  if (estado === 'nunca') return 'nunca testado'
  return 'não conectado'
}

function plural(n: number, um: string, varios: string) {
  return `${n} ${n === 1 ? um : varios}`
}

function LinhaDaEmpresa({ empresa }: { empresa: Empresa }) {
  return (
    <Link to={`/empresas/${empresa.id}`} className="block group">
      <Cartao className="px-5 py-4 group-hover:border-borda-forte transition-colors">
        <div className="flex items-start gap-3">
          <Building2 size={18} className="text-rotulo mt-1 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <p className="text-forte font-semibold">{empresa.nome}</p>
              <Selo tom={empresa.ativa ? 'ok' : 'sem-dados'}>
                {empresa.ativa ? 'Ativa' : 'Desligada'}
              </Selo>
            </div>
            <p className="text-sm text-rotulo mt-0.5">{empresa.documento ?? 'sem CNPJ cadastrado'}</p>
            <div className="flex items-center gap-x-5 gap-y-1 mt-2 text-sm text-rotulo flex-wrap">
              <span className="flex items-center gap-1.5">
                <Users size={14} />
                {plural(empresa.gerentes, 'gerente', 'gerentes')} ·{' '}
                {plural(empresa.tecnicos, 'técnico', 'técnicos')} ·{' '}
                {plural(empresa.donos, 'dono de usina', 'donos de usina')}
              </span>
              <span className="flex items-center gap-1.5">
                <Sun size={14} /> {plural(empresa.usinas, 'usina', 'usinas')}
              </span>
              <span>
                meuWatt: {estadoDaConexao(empresa.conexao_meuwatt)} · meuPlano:{' '}
                {estadoDaConexao(empresa.conexao_meuplano)}
              </span>
            </div>
          </div>
          <ChevronRight size={18} className="text-fraco mt-1 shrink-0 group-hover:text-forte" />
        </div>
      </Cartao>
    </Link>
  )
}

function Nova({ aoFechar }: { aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [documento, setDocumento] = useState('')

  const criar = useMutation({
    mutationFn: () => criarEmpresa({ nome, documento: documento || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresas'] })
      aoFechar()
    },
  })

  return (
    <Modal titulo="Cadastrar empresa de O&M" aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Aviso>
          O nome é único. “Splendor O&M” e “splendor o&amp;m” são a mesma empresa — era
          exatamente isso que o cadastro por texto livre deixava passar.
        </Aviso>

        <Campo
          rotulo="Nome"
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="Splendor O&M"
        />
        <Campo
          rotulo="CNPJ (opcional)"
          value={documento}
          onChange={(e) => setDocumento(e.target.value)}
          placeholder="00.000.000/0001-00"
        />

        {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}

        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            className="btn-primario"
            onClick={() => criar.mutate()}
            disabled={!nome.trim() || criar.isPending}
          >
            {criar.isPending ? 'Cadastrando…' : 'Cadastrar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
