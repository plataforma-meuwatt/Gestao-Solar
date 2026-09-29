/**
 * As usinas da empresa — trazidas pelo GERENTE, com o token dele.
 *
 * A primeira versão desta tela era só leitura e dizia "quem liga usina à empresa é quem
 * administra a plataforma". Estava errada e travou o dono: quem tem credencial no meuWatt
 * e no meuPlano é a empresa, não a plataforma. Ela não tem como listar nem trazer nada.
 *
 * É a conciliação do painel, escopada: a lista sai do SEU token, então é exatamente a sua
 * carteira, e a usina nasce com a sua empresa como dona.
 *
 * **Os três grupos existem porque os três casos são reais**: usina nos dois produtos, só no
 * meuWatt (monitoramento sem manutenção contratada) e só no meuPlano (manutenção sem
 * monitoramento). O terceiro é comum, e uma tela que percorresse só o meuWatt o esconderia.
 *
 * **Usina não casada aparece duas vezes, uma em cada grupo.** O sistema não *sabe* que são
 * a mesma; esconder uma seria decidir no lugar de quem decide. O que se oferece é o
 * apontamento ("parece ser…") e o botão que casa as duas.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, Sun, Wrench } from 'lucide-react'
import { useState } from 'react'

import { Cartao, Carregando, Erro, Pagina, Selo, Vazio } from '@/components/base'
import {
  catalogoDeUsinas,
  salvarUsinaDaEmpresa,
  type LinhaDeUsina,
} from '@/features/api'
import { mensagemDeErro } from '@/lib/api'
import { useAuth } from '@/store/auth'

const GRUPOS: { origem: LinhaDeUsina['origem']; titulo: string; icone: typeof Sun; apoio: string }[] = [
  {
    origem: 'ambos',
    titulo: 'Nas duas plataformas',
    icone: Link2,
    apoio: 'Geração e manutenção da mesma usina. É o caso completo.',
  },
  {
    origem: 'meuwatt',
    titulo: 'Só no meuWatt',
    icone: Sun,
    apoio: 'Monitoramento sem manutenção contratada.',
  },
  {
    origem: 'meuplano',
    titulo: 'Só no meuPlano',
    icone: Wrench,
    apoio: 'Manutenção sem monitoramento. É um caso normal, não um erro.',
  },
]

export function UsinasDaEmpresa() {
  const empresa = useAuth((s) => s.empresa)
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['empresa', 'usinas-catalogo'],
    queryFn: catalogoDeUsinas,
  })

  const salvar = useMutation({
    mutationFn: salvarUsinaDaEmpresa,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['empresa'] }),
  })

  const linhas = data?.linhas ?? []

  return (
    <Pagina
      titulo="Usinas"
      apoio={empresa ? `As usinas de ${empresa}` : 'As usinas da sua empresa'}
    >
      {isLoading ? (
        <Carregando />
      ) : error ? (
        <Erro>{mensagemDeErro(error)}</Erro>
      ) : (
        <div className="grid gap-5">
          {(data?.avisos ?? []).map((a) => (
            <Erro key={a}>{a}</Erro>
          ))}

          {salvar.error ? <Erro>{mensagemDeErro(salvar.error)}</Erro> : null}

          {!linhas.length ? (
            <Vazio
              titulo="Nenhuma usina encontrada"
              descricao="O seu token não enxergou usina nenhuma nos produtos. Confira em Conexões."
            />
          ) : (
            GRUPOS.map(({ origem, titulo, icone: Icone, apoio }) => {
              const doGrupo = linhas.filter((l) => l.origem === origem)
              if (!doGrupo.length) return null
              return (
                <div key={origem}>
                  <div className="flex items-center gap-2 mb-1">
                    <Icone size={16} className="text-rotulo" />
                    <p className="text-forte font-semibold">{titulo}</p>
                    <span className="text-xs text-fraco">{doGrupo.length}</span>
                  </div>
                  <p className="text-sm text-rotulo mb-2">{apoio}</p>
                  <div className="grid gap-2">
                    {doGrupo.map((l) => (
                      <LinhaUsina
                        key={l.chave}
                        linha={l}
                        ocupado={salvar.isPending}
                        aoSalvar={(dados) => salvar.mutate(dados)}
                      />
                    ))}
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </Pagina>
  )
}

function LinhaUsina({
  linha,
  ocupado,
  aoSalvar,
}: {
  linha: LinhaDeUsina
  ocupado: boolean
  aoSalvar: (dados: Parameters<typeof salvarUsinaDaEmpresa>[0]) => void
}) {
  const [nome, setNome] = useState(linha.nome)
  const jaEstaAqui = linha.plant_link_id !== null

  const base = {
    plant_link_id: linha.plant_link_id,
    mw_slug: linha.mw_slug,
    mp_usina_id: linha.mp_usina_id,
    nome,
    cidade: linha.cidade,
    uf: linha.uf,
    kwp: linha.kwp,
  }

  return (
    <Cartao>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          {jaEstaAqui ? (
            <input
              className="campo h-9 text-sm"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              onBlur={() => nome !== linha.nome && aoSalvar({ ...base, no_app: linha.no_app })}
            />
          ) : (
            <p className="text-forte font-semibold">{linha.nome}</p>
          )}
          <p className="text-sm text-rotulo mt-1">
            {[linha.cidade, linha.uf].filter(Boolean).join(' · ') || 'sem cidade'}
            {linha.kwp ? ` · ${linha.kwp.toLocaleString('pt-BR')} kWp` : ''}
          </p>
          {linha.par_provavel_nome ? (
            <p className="text-xs text-ambar-texto mt-1">
              parece ser a mesma que “{linha.par_provavel_nome}” do outro produto
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          {jaEstaAqui ? (
            <>
              <Selo tom={linha.no_app ? 'ok' : 'sem-dados'}>
                {linha.no_app ? 'No app' : 'Desligada'}
              </Selo>
              <button
                className="btn-fantasma"
                disabled={ocupado}
                onClick={() => aoSalvar({ ...base, no_app: !linha.no_app })}
              >
                {linha.no_app ? 'Desligar' : 'Religar'}
              </button>
            </>
          ) : (
            <button
              className="btn-secundario"
              disabled={ocupado}
              onClick={() => aoSalvar({ ...base, no_app: true })}
            >
              Trazer para a empresa
            </button>
          )}
        </div>
      </div>
    </Cartao>
  )
}
