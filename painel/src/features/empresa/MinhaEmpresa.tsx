/**
 * As telas do gerente da empresa de O&M — o outro portão, dentro do mesmo painel.
 *
 * Três listas finas sobre `/api/empresa/*`, num arquivo só pelo mesmo motivo de
 * `features/api.ts`: espalhá-las esconderia que são a mesma coisa vista por três
 * recortes, e é justamente o recorte que precisa ficar visível.
 *
 * **Nenhuma delas manda o identificador da empresa.** O servidor o tira da sessão. Se uma
 * tela daqui passasse a aceitar "qual empresa", a próxima pessoa a mexer nela acharia
 * natural deixar isso vir da URL — e aí a carteira do concorrente estaria a um número de
 * distância.
 *
 * Não existe um quarto front para isto. Painel, portal e app já repetem a camada de API
 * sem lugar comum, e as divergências começaram; a quarta cópia seria a quarta chance de
 * corrigir defeito em três lugares e esquecer o quarto. A separação que importa é a do
 * servidor — prefixo, escopo e o recorte único —, e no front ela aparece como o nome da
 * empresa fixo no alto da tela.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserCog, UserPlus, Users } from 'lucide-react'

import { Aviso, Campo, Cartao, Carregando, Erro, Modal, Pagina, Selo, Vazio } from '@/components/base'
import {
  clientesDaEmpresa,
  criarClienteDaEmpresa,
  usuariosDaEmpresa,
  type ClienteDaEmpresa,
  type UsuarioDaEmpresa,
} from '@/features/api'
import { useState } from 'react'

import { UsinasDoUsuario } from '@/features/empresa/Usuarios'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

/** O invólucro comum: título, o nome da empresa no apoio, e os quatro estados. */
function Lista<T>({
  titulo,
  apoio,
  chave,
  buscar,
  vazio,
  desenhar,
  acao,
}: {
  titulo: string
  apoio: string
  chave: string
  buscar: () => Promise<T[]>
  vazio: { titulo: string; descricao: string }
  desenhar: (item: T) => React.ReactNode
  acao?: React.ReactNode
}) {
  const empresa = useAuth((s) => s.empresa)
  const { data, isLoading, error } = useQuery({ queryKey: ['empresa', chave], queryFn: buscar })

  return (
    <Pagina titulo={titulo} apoio={empresa ? `${apoio} · ${empresa}` : apoio} acao={acao}>
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : !data?.length ? (
        <Vazio titulo={vazio.titulo} descricao={vazio.descricao} />
      ) : (
        <div className="grid gap-3">{data.map(desenhar)}</div>
      )}
    </Pagina>
  )
}

/**
 * Os clientes da empresa — cadastrados AQUI, pelo gerente.
 *
 * A primeira versão era só leitura e dizia "clientes aparecem assim que forem cadastrados",
 * sem dizer por quem: o gerente não tinha como cadastrar ninguém, e a plataforma não
 * cadastra cliente de inquilino. Ficava um beco.
 *
 * Quem cadastra é quem atende, e é ele também quem concede as usinas — dentre as da
 * própria empresa, porque conceder a usina de outra faria o dono dela ver, no aplicativo,
 * dados de uma carteira que não é a sua.
 */
export function ClientesDaEmpresa() {
  const [novo, setNovo] = useState(false)
  const [usinasDe, setUsinasDe] = useState<ClienteDaEmpresa | null>(null)

  return (
    <>
      {novo ? <NovoCliente aoFechar={() => setNovo(false)} /> : null}
      {usinasDe ? (
        <UsinasDoUsuario
          usuario={{ id: usinasDe.id, nome: usinasDe.nome, usinas: usinasDe.usinas }}
          aoFechar={() => setUsinasDe(null)}
        />
      ) : null}

    <Lista<ClienteDaEmpresa>
      titulo="Clientes"
      apoio="Os donos de usina que a sua empresa atende"
      chave="clientes"
      buscar={clientesDaEmpresa}
      acao={
        <button className="btn-primario" onClick={() => setNovo(true)}>
          <UserPlus size={16} />
          Novo cliente
        </button>
      }
      vazio={{
        titulo: 'Nenhum cliente nesta empresa',
        descricao: 'Cadastre o primeiro em “Novo cliente”. Ele entra no aplicativo com o apelido e a senha que você entrega.',
      }}
      desenhar={(c) => (
        <Cartao key={c.id}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-3">
              <Users size={18} className="text-rotulo mt-1 shrink-0" />
              <div>
                <p className="text-forte font-semibold">{c.nome}</p>
                <p className="text-sm text-rotulo mt-0.5">
                  {c.apelido}
                  {c.email ? ` · ${c.email}` : ''}
                </p>
                <p className="text-sm text-rotulo mt-2">
                  {c.usinas} {c.usinas === 1 ? 'usina concedida' : 'usinas concedidas'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Selo tom={c.ativo ? 'ok' : 'sem-dados'}>{c.ativo ? 'Ativo' : 'Inativo'}</Selo>
              <button className="btn-fantasma" onClick={() => setUsinasDe(c)}>
                Usinas
              </button>
            </div>
          </div>
        </Cartao>
      )}
    />
    </>
  )
}

const PAPEL: Record<string, string> = {
  gestor_empresa: 'Gerente da empresa',
  tecnico: 'Técnico',
  cliente: 'Dono de usina',
}

export function UsuariosDaEmpresa() {
  return (
    <Lista<UsuarioDaEmpresa>
      titulo="Usuários"
      apoio="Quem é da sua empresa"
      chave="usuarios"
      buscar={usuariosDaEmpresa}
      vazio={{
        titulo: 'Nenhum usuário nesta empresa',
        descricao: 'A sua própria conta deveria aparecer aqui — se não aparece, avise a plataforma.',
      }}
      desenhar={(u) => (
        <Cartao key={u.id}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-3">
              <UserCog size={18} className="text-rotulo mt-1 shrink-0" />
              <div>
                <p className="text-forte font-semibold">{u.nome}</p>
                <p className="text-sm text-rotulo mt-0.5">{u.apelido}</p>
                {/* O papel sai traduzido: o código cru na tela é o defeito que o
                    CLAUDE.md nomeia — rótulo que alguém lê é dado, não enum. */}
                <p className="text-sm text-rotulo mt-2">{PAPEL[u.perfil] ?? u.perfil}</p>
              </div>
            </div>
            <Selo tom={u.ativo ? 'ok' : 'sem-dados'}>{u.ativo ? 'Ativo' : 'Inativo'}</Selo>
          </div>
        </Cartao>
      )}
    />
  )
}


/** Cadastro do dono de usina, com a senha provisória mostrada uma vez. */
function NovoCliente({ aoFechar }: { aoFechar: () => void }) {
  const qc = useQueryClient()
  const [nome, setNome] = useState('')
  const [apelido, setApelido] = useState('')
  const [email, setEmail] = useState('')
  const [criado, setCriado] = useState<{ apelido: string; senha: string } | null>(null)

  const criar = useMutation({
    mutationFn: () => criarClienteDaEmpresa({ nome, apelido, email: email || null }),
    onSuccess: (r) => {
      setCriado({ apelido: r.apelido, senha: r.senha })
      qc.invalidateQueries({ queryKey: ['empresa'] })
    },
  })

  if (criado) {
    return (
      <Modal titulo="Cliente cadastrado" aoFechar={aoFechar}>
        <div className="grid gap-4">
          <Aviso>
            Anote agora: a senha não é guardada em texto e não dá para vê-la de novo.
          </Aviso>
          <Cartao>
            <p className="text-sm text-rotulo">Entra com o apelido</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.apelido}</p>
            <p className="text-sm text-rotulo mt-4">Senha provisória</p>
            <p className="text-forte font-semibold text-lg mt-1">{criado.senha}</p>
          </Cartao>
          <p className="text-xs text-fraco">
            Entregue as duas coisas juntas. O e-mail é só contato — quem autentica é o apelido.
          </p>
          <div className="flex justify-end">
            <button className="btn-primario" onClick={aoFechar}>
              Fechar
            </button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal titulo="Novo cliente" aoFechar={aoFechar}>
      <div className="grid gap-4">
        <Campo rotulo="Nome" value={nome} onChange={(e) => setNome(e.target.value)} />
        <Campo
          rotulo="Apelido (é com ele que entra)"
          value={apelido}
          onChange={(e) => setApelido(e.target.value)}
        />
        <Campo
          rotulo="E-mail (opcional)"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          nota="Contato apenas. Serve para achar a conta dele no meuWatt e no meuPlano."
        />

        {criar.error ? <Erro>{mensagemDeErro(criar.error)}</Erro> : null}
        {!nome.trim() || !apelido.trim() ? (
          <p className="text-xs text-rotulo">Preencha nome e apelido para cadastrar.</p>
        ) : null}

        <div className="flex justify-end gap-2">
          <button className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            className="btn-primario"
            onClick={() => criar.mutate()}
            disabled={!nome.trim() || !apelido.trim() || criar.isPending}
          >
            {criar.isPending ? 'Cadastrando…' : 'Cadastrar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
