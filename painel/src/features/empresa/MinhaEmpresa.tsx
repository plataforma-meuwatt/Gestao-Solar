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

import { useQuery } from '@tanstack/react-query'
import { Sun, UserCog, Users } from 'lucide-react'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio } from '@/components/base'
import {
  clientesDaEmpresa,
  usinasDaEmpresa,
  usuariosDaEmpresa,
  type ClienteDaEmpresa,
  type UsinaDaEmpresa,
  type UsuarioDaEmpresa,
} from '@/features/api'
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
}: {
  titulo: string
  apoio: string
  chave: string
  buscar: () => Promise<T[]>
  vazio: { titulo: string; descricao: string }
  desenhar: (item: T) => React.ReactNode
}) {
  const empresa = useAuth((s) => s.empresa)
  const { data, isLoading, error } = useQuery({ queryKey: ['empresa', chave], queryFn: buscar })

  return (
    <Pagina titulo={titulo} apoio={empresa ? `${apoio} · ${empresa}` : apoio}>
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

export function UsinasDaEmpresa() {
  return (
    <Lista<UsinaDaEmpresa>
      titulo="Usinas"
      apoio="As usinas operadas pela sua empresa"
      chave="usinas"
      buscar={usinasDaEmpresa}
      vazio={{
        titulo: 'Nenhuma usina ligada à sua empresa',
        descricao: 'Quem liga usina à empresa é quem administra a plataforma. Fale com eles.',
      }}
      desenhar={(u) => (
        <Cartao key={u.id}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-3">
              <Sun size={18} className="text-rotulo mt-1 shrink-0" />
              <div>
                <p className="text-forte font-semibold">{u.nome}</p>
                <p className="text-sm text-rotulo mt-0.5">
                  {[u.cidade, u.uf].filter(Boolean).join(' · ') || 'sem cidade cadastrada'}
                  {u.kwp ? ` · ${u.kwp.toLocaleString('pt-BR')} kWp` : ''}
                </p>
                <p className="text-sm text-rotulo mt-2">
                  {u.clientes} {u.clientes === 1 ? 'cliente recebe' : 'clientes recebem'} esta
                  usina no aplicativo
                </p>
              </div>
            </div>
            {/* Desligada continua na lista de propósito: sumir seria responder "não
                existe" a algo que existe e que pode ser religado. */}
            <Selo tom={u.ativo ? 'ok' : 'sem-dados'}>{u.ativo ? 'No app' : 'Desligada'}</Selo>
          </div>
        </Cartao>
      )}
    />
  )
}

export function ClientesDaEmpresa() {
  return (
    <Lista<ClienteDaEmpresa>
      titulo="Clientes"
      apoio="Os donos de usina que a sua empresa atende"
      chave="clientes"
      buscar={clientesDaEmpresa}
      vazio={{
        titulo: 'Nenhum cliente nesta empresa',
        descricao: 'Clientes aparecem aqui assim que forem cadastrados na sua empresa.',
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
            <Selo tom={c.ativo ? 'ok' : 'sem-dados'}>{c.ativo ? 'Ativo' : 'Inativo'}</Selo>
          </div>
        </Cartao>
      )}
    />
  )
}

const PAPEL: Record<string, string> = {
  gestor_empresa: 'Gerente da empresa',
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
