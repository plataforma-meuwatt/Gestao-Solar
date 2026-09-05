/**
 * O menu é a única peça do portal que três larguras diferentes leem, e o que ele decide não
 * aparece como erro de compilação: um sufixo errado não quebra o `tsc`, só manda o cliente
 * para a tela errada quando ele troca de usina.
 *
 * É isso que este teste guarda:
 *
 * - **o filho não é engolido pelo pai** — `/energia/paradas` é "Paradas", não "Painel", e
 *   `/manutencao/ordens/12/tarefas/99` continua sendo "Ordens de serviço". Sem a ordem do
 *   mais específico para o menos, o seletor de usina levaria quem estava na ficha de uma
 *   tarefa para o painel de energia da outra usina;
 * - **nenhum sufixo é vazio.** Enquanto a Energia morava na raiz da usina, o item dela tinha
 *   `fim: ''` e casava com tudo — e o endereço não dizia de que assunto era;
 * - **o padrão é explícito.** Caminho que não é seção nenhuma cai no Painel; devolver vazio
 *   mandaria o cliente para a raiz da usina, que é só um redirecionamento;
 * - **toda seção tem família e todo grupo tem seções**, que é o que sustenta a separação
 *   entre Geração de energia e Manutenção nas três larguras.
 */

import { describe, expect, it } from 'vitest'

import {
  GRUPOS,
  SECAO_PADRAO,
  SECOES,
  casamentoExato,
  secoesDaFamilia,
  sufixoDaSecao,
} from '@/shell/menu'

describe('sufixo da seção', () => {
  it('não deixa o pai engolir o filho', () => {
    expect(sufixoDaSecao('/usinas/3/energia/paradas')).toBe('/energia/paradas')
    expect(sufixoDaSecao('/usinas/3/energia')).toBe('/energia')
  })

  it('reconhece a seção nas telas mais fundas dela', () => {
    expect(sufixoDaSecao('/usinas/3/manutencao/ordens/12/tarefas/99')).toBe('/manutencao/ordens')
    expect(sufixoDaSecao('/usinas/3/manutencao/ordens/12')).toBe('/manutencao/ordens')
    expect(sufixoDaSecao('/usinas/3/manutencao/pendencias/44')).toBe('/manutencao/pendencias')
    expect(sufixoDaSecao('/usinas/3/manutencao/cronograma')).toBe('/manutencao/cronograma')
    expect(sufixoDaSecao('/usinas/3/relatorios')).toBe('/relatorios')
  })

  it('cai no Painel quando o caminho não é seção nenhuma', () => {
    expect(SECAO_PADRAO).toBe('/energia')
    expect(sufixoDaSecao('/usinas/3')).toBe(SECAO_PADRAO)
    expect(sufixoDaSecao('/')).toBe(SECAO_PADRAO)
    expect(sufixoDaSecao('/conta')).toBe(SECAO_PADRAO)
    // Endereço antigo: quem trocar de usina a partir dele vai para o Painel da nova, e não
    // para uma rota que só existe como redirecionamento.
    expect(sufixoDaSecao('/usinas/3/ordens/12')).toBe(SECAO_PADRAO)
  })
})

describe('catálogo das seções', () => {
  it('nenhum sufixo é vazio, e todos começam com barra', () => {
    for (const s of SECOES) {
      expect(s.fim.length).toBeGreaterThan(0)
      expect(s.fim.startsWith('/')).toBe(true)
    }
  })

  it('não repete sufixo nem rótulo', () => {
    expect(new Set(SECOES.map((s) => s.fim)).size).toBe(SECOES.length)
    expect(new Set(SECOES.map((s) => s.rotulo)).size).toBe(SECOES.length)
  })

  it('toda seção declara a família a que pertence', () => {
    for (const s of SECOES) expect(['geracao', 'manutencao', 'geral']).toContain(s.familia)
  })

  it('a URL nomeia a família', () => {
    for (const s of secoesDaFamilia('geracao')) expect(s.fim.startsWith('/energia')).toBe(true)
    for (const s of secoesDaFamilia('manutencao')) expect(s.fim.startsWith('/manutencao')).toBe(true)
  })

  it('todo grupo tem pelo menos uma seção, e nenhuma seção fica de fora de um grupo', () => {
    const emGrupos = GRUPOS.flatMap((g) => secoesDaFamilia(g.familia))
    expect(emGrupos).toHaveLength(SECOES.length)
    for (const g of GRUPOS) expect(secoesDaFamilia(g.familia).length).toBeGreaterThan(0)
  })

  it('as duas famílias têm nome e ícone-cabeçalho — é o que o trilho estreito mostra', () => {
    const nomeadas = GRUPOS.filter((g) => g.nome)
    expect(nomeadas.map((g) => g.nome)).toEqual(['Geração de energia', 'Manutenção'])
    for (const g of nomeadas) expect(g.icone).not.toBeNull()
  })
})

describe('destaque no menu', () => {
  it('exige casamento exato só de quem tem seção morando debaixo', () => {
    // Sem isto, "Painel" ficaria aceso enquanto o cliente lê "Paradas".
    expect(casamentoExato('/energia')).toBe(true)
    // E com isto de mais, "Ordens de serviço" apagaria na ficha de uma tarefa.
    expect(casamentoExato('/manutencao/ordens')).toBe(false)
    expect(casamentoExato('/manutencao/pendencias')).toBe(false)
    expect(casamentoExato('/relatorios')).toBe(false)
  })
})
