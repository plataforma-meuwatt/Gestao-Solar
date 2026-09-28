/**
 * Empresas de O&M — a tela da PLATAFORMA que cria e desliga inquilino.
 *
 * É a única tela do sistema que mostra a lista inteira de empresas. Nenhuma empresa sabe
 * que as outras existem, e é por isso que ela vive em `/api/painel/*`, atrás da área
 * `empresas`, e não em lugar nenhum do portão do inquilino.
 *
 * **Desligar, não apagar.** `ativa=false` tira a empresa de operação — o gerente dela para
 * de entrar na requisição seguinte, sem esperar a sessão expirar — e preserva usina,
 * cliente e histórico. Não há botão de apagar: a chave estrangeira é `RESTRICT`, e o que
 * ela protege é o histórico que alguém ainda vai precisar auditar.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Power, Sun, Users } from 'lucide-react'
import { useState } from 'react'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio } from '@/components/base'
import {
  carteiraDaEmpresa,
  criarEmpresa,
  criarGerente,
  editarEmpresa,
  listarEmpresas,
  salvarCarteira,
  type Empresa,
  type GerenteCriado,
  type ItemDaCarteira,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'

export function Empresas() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['empresas'], queryFn: listarEmpresas })
  const [novaAberta, setNovaAberta] = useState(false)
  const [carteiraDe, setCarteiraDe] = useState<Empresa | null>(null)
  const [gerenteDe, setGerenteDe] = useState<Empresa | null>(null)

  const alternar = useMutation({
    mutationFn: ({ id, ativa }: { id: number; ativa: boolean }) => editarEmpresa(id, { ativa }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresas'] }),
  })

  return (
    <Pagina
      titulo="Empresas de O&M"
      apoio="Cada empresa é um inquilino: os usuários, as usinas e as conexões dela não aparecem para nenhuma outra."
      acao={
        <button className="botao" onClick={() => setNovaAberta(true)}>
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
          descricao="Enquanto não houver empresa, usinas e clientes ficam sem dono e só a plataforma os enxerga."
        />
      ) : (
        <div className="grid gap-3">
          {alternar.error ? <Erro>{mensagemDeErro(alternar.error)}</Erro> : null}
          {data.map((e) => (
            <Linha
              key={e.id}
              empresa={e}
              ocupado={alternar.isPending}
              aoAlternar={() => alternar.mutate({ id: e.id, ativa: !e.ativa })}
              aoAbrirCarteira={() => setCarteiraDe(e)}
              aoAbrirGerente={() => setGerenteDe(e)}
            />
          ))}
        </div>
      )}

      {novaAberta ? <Nova aoFechar={() => setNovaAberta(false)} /> : null}
      {carteiraDe ? (
        <CarteiraModal empresa={carteiraDe} aoFechar={() => setCarteiraDe(null)} />
      ) : null}
      {gerenteDe ? (
        <NovoGerente empresa={gerenteDe} aoFechar={() => setGerenteDe(null)} />
      ) : null}
    </Pagina>
  )
}

function Linha({
  empresa,
  ocupado,
  aoAlternar,
  aoAbrirCarteira,
  aoAbrirGerente,
}: {
  empresa: Empresa
  ocupado: boolean
  aoAlternar: () => void
  aoAbrirCarteira: () => void
  aoAbrirGerente: () => void
}) {
  return (
    <Cartao>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <Building2 size={18} className="text-rotulo mt-1 shrink-0" />
          <div>
            <p className="text-forte font-semibold">{empresa.nome}</p>
            <p className="text-sm text-rotulo mt-0.5">
              {empresa.documento ?? 'sem CNPJ cadastrado'}
            </p>
            <div className="flex items-center gap-4 mt-2 text-sm text-rotulo">
              <span className="flex items-center gap-1.5">
                <Users size={14} /> {empresa.usuarios}{' '}
                {empresa.usuarios === 1 ? 'usuário' : 'usuários'}
              </span>
              <span className="flex items-center gap-1.5">
                <Sun size={14} /> {empresa.usinas} {empresa.usinas === 1 ? 'usina' : 'usinas'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Selo tom={empresa.ativa ? 'ok' : 'sem-dados'}>{empresa.ativa ? 'Ativa' : 'Desligada'}</Selo>
          <button className="botao-secundario" onClick={aoAbrirGerente}>
            Novo gerente
          </button>
          <button className="botao-secundario" onClick={aoAbrirCarteira}>
            Usinas e clientes
          </button>
          <button className="botao-secundario" onClick={aoAlternar} disabled={ocupado}>
            <Power size={14} className="inline mr-1.5" />
            {empresa.ativa ? 'Desligar' : 'Religar'}
          </button>
        </div>
      </div>

      {!empresa.ativa ? (
        <p className="text-sm text-rotulo mt-3">
          O gerente desta empresa não entra enquanto ela estiver desligada. Usinas, clientes e
          histórico continuam guardados.
        </p>
      ) : null}
    </Cartao>
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
          <button className="botao-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            className="botao"
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


/**
 * De quem é o quê: as usinas e os clientes desta empresa.
 *
 * A lista é a do sistema inteiro, com o dono atual ao lado de cada linha. Mostrar só o que
 * já é dela esconderia exatamente o que falta atribuir — que é o estado de tudo o que
 * existia antes do multiempresa.
 *
 * O que pertence a OUTRA empresa aparece travado, com o nome do dono. Transferir carteira
 * com um clique distraído não é uma operação que esta tela oferece: tira-se lá, põe-se
 * aqui, duas decisões.
 */
function CarteiraModal({ empresa, aoFechar }: { empresa: Empresa; aoFechar: () => void }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['carteira', empresa.id],
    queryFn: () => carteiraDaEmpresa(empresa.id),
  })
  const [usinas, setUsinas] = useState<number[] | null>(null)
  const [clientes, setClientes] = useState<number[] | null>(null)

  // A escolha nasce do que o servidor devolveu; enquanto ela for nula, a marcação lida é
  // a do dado. Sem isso, a caixa ficaria desmarcada no primeiro quadro e um "Salvar"
  // rápido apagaria a carteira inteira.
  const marcadasUsinas = usinas ?? (data?.usinas ?? []).filter((i) => i.empresa_id === empresa.id).map((i) => i.id)
  const marcadosClientes =
    clientes ?? (data?.clientes ?? []).filter((i) => i.empresa_id === empresa.id).map((i) => i.id)

  const salvar = useMutation({
    mutationFn: () => salvarCarteira(empresa.id, { usinas: marcadasUsinas, clientes: marcadosClientes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['empresas'] })
      qc.invalidateQueries({ queryKey: ['carteira', empresa.id] })
      aoFechar()
    },
  })

  function alternarItem(lista: number[], id: number, definir: (v: number[]) => void) {
    definir(lista.includes(id) ? lista.filter((x) => x !== id) : [...lista, id])
  }

  return (
    <Modal titulo={`Usinas e clientes · ${empresa.nome}`} aoFechar={aoFechar} largura="max-w-3xl">
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : (
        <div className="grid gap-5">
          <Aviso>
            O que sair das listas fica <strong>sem dono</strong> — não volta para outra
            empresa. Linha travada já pertence a outra: tire lá antes de trazer para cá.
          </Aviso>

          <Coluna
            titulo="Usinas"
            itens={data?.usinas ?? []}
            marcados={marcadasUsinas}
            empresaId={empresa.id}
            aoAlternar={(id) => alternarItem(marcadasUsinas, id, setUsinas)}
          />
          <Coluna
            titulo="Clientes e gerentes"
            itens={data?.clientes ?? []}
            marcados={marcadosClientes}
            empresaId={empresa.id}
            aoAlternar={(id) => alternarItem(marcadosClientes, id, setClientes)}
          />

          {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}

          <div className="flex justify-end gap-2">
            <button className="botao-secundario" onClick={aoFechar}>
              Cancelar
            </button>
            <button className="botao" onClick={() => salvar.mutate()} disabled={salvar.isPending}>
              {salvar.isPending ? 'Salvando…' : 'Salvar'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Coluna({
  titulo,
  itens,
  marcados,
  empresaId,
  aoAlternar,
}: {
  titulo: string
  itens: ItemDaCarteira[]
  marcados: number[]
  empresaId: number
  aoAlternar: (id: number) => void
}) {
  if (!itens.length) {
    return (
      <div>
        <p className="rotulo-campo">{titulo}</p>
        <p className="text-sm text-rotulo mt-1">Nada cadastrado ainda.</p>
      </div>
    )
  }
  return (
    <div>
      <p className="rotulo-campo">{titulo}</p>
      <ul className="mt-2 grid gap-1 max-h-64 overflow-y-auto pr-1">
        {itens.map((i) => {
          const deOutra = i.empresa_id !== null && i.empresa_id !== empresaId
          return (
            <li key={i.id}>
              <label
                className={`flex items-center gap-2.5 px-3 py-2 rounded-campo ${
                  deOutra ? 'opacity-60' : 'hover:bg-superficie cursor-pointer'
                }`}
              >
                <input
                  type="checkbox"
                  checked={marcados.includes(i.id)}
                  disabled={deOutra}
                  onChange={() => aoAlternar(i.id)}
                />
                <span className="text-sm text-forte">{i.nome}</span>
                {i.detalhe ? <span className="text-xs text-fraco">{i.detalhe}</span> : null}
                {deOutra ? (
                  <span className="text-xs text-rotulo ml-auto">{i.empresa_nome}</span>
                ) : null}
              </label>
            </li>
          )
        })}
      </ul>
    </div>
  )
}


/**
 * O gerente da empresa nasce aqui — e não na tela de Usuários do sistema.
 *
 * Lá ele nasceria sem empresa, e uma conta de inquilino sem vínculo não entra em lugar
 * nenhum: seria uma conta que parece pronta e não abre nada. Aqui a empresa é o caminho
 * da rota, então o vínculo é obrigatório por construção.
 *
 * A senha aparece UMA vez e some. Ela é entregue junto com o **apelido**, que é o que
 * autentica — mandar o e-mail junto convidaria a tentar entrar com ele, que é exatamente
 * o que não funciona.
 */
function NovoGerente({ empresa, aoFechar }: { empresa: Empresa; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [apelido, setApelido] = useState('')
  const [email, setEmail] = useState('')
  const [criado, setCriado] = useState<GerenteCriado | null>(null)

  const criar = useMutation({
    mutationFn: () => criarGerente(empresa.id, { nome, apelido, email: email || null }),
    onSuccess: (r) => {
      setCriado(r)
      qc.invalidateQueries({ queryKey: ['empresas'] })
    },
  })

  // O apelido sugerido a partir do nome, enquanto ninguém o editou à mão. O servidor
  // normaliza e decide — isto é só conforto de digitação.
  function aoDigitarNome(valor: string) {
    const sugestaoAnterior = sugerir(nome)
    setNome(valor)
    if (!apelido || apelido === sugestaoAnterior) setApelido(sugerir(valor))
  }

  if (criado) {
    return (
      <Modal titulo="Gerente criado" aoFechar={aoFechar}>
        <div className="grid gap-4">
          <Aviso>
            Anote agora: a senha não é guardada em texto e não dá para vê-la de novo. Quem
            perder, redefine.
          </Aviso>
          <Cartao>
            <p className="text-sm text-rotulo">Entra com o apelido</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.apelido}</p>
            <p className="text-sm text-rotulo mt-4">Senha provisória</p>
            <p className="text-forte font-semibold text-lg mt-1 font-mono">{criado.senha}</p>
          </Cartao>
          <div className="flex justify-end">
            <button className="botao" onClick={aoFechar}>
              Fechar
            </button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal titulo={`Novo gerente · ${empresa.nome}`} aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Aviso>
          O gerente abre a área da empresa — usinas, clientes, usuários e as conexões dela.
          Não abre nada da plataforma.
        </Aviso>

        <Campo
          rotulo="Nome"
          value={nome}
          onChange={(e) => aoDigitarNome(e.target.value)}
          placeholder="Maria Silva"
        />
        <Campo
          rotulo="Apelido (é com ele que entra)"
          value={apelido}
          onChange={(e) => setApelido(e.target.value)}
          placeholder="maria.silva"
        />
        <Campo
          rotulo="E-mail (opcional)"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          nota="Contato apenas. Quem autentica é o apelido."
        />

        {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}

        <div className="flex justify-end gap-2">
          <button className="botao-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            className="botao"
            onClick={() => criar.mutate()}
            disabled={!nome.trim() || !apelido.trim() || criar.isPending}
          >
            {criar.isPending ? 'Criando…' : 'Criar gerente'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** A mesma régua do apelido do cliente: sem acento, sem espaço, minúsculo. */
function sugerir(nome: string): string {
  const limpo = nome
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
  const partes = limpo.split(/\s+/).filter(Boolean)
  if (partes.length === 0) return ''
  if (partes.length === 1) return partes[0].replace(/[^a-z0-9._-]/g, '')
  return `${partes[0]}.${partes[partes.length - 1]}`.replace(/[^a-z0-9._-]/g, '')
}
