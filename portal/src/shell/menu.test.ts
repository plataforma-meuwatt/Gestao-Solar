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
 *   entre Geração de energia e Manutenção nas três larguras;
 * - **os dois comparativos são de CARTEIRA**, e o endereço deles não carrega usina. Três
 *   defeitos moram aqui, e cada um tem o seu teste: (a) montar o endereço por concatenação
 *   levaria a `/usinas/3/comparar/energia`, que só existe como redirecionamento, e o item
 *   nunca ficaria aceso; (b) `'/comparar/energia'.endsWith('/energia')` é VERDADEIRO, então
 *   a busca pelas seções de usina reconheceria o comparativo como "Painel" — e devolveria a
 *   resposta certa pelo caminho errado, de modo que no dia em que o Painel mudasse de sufixo
 *   o comparativo passaria a mandar o cliente para outra família sem nada quebrar; (c)
 *   escolher uma usina a partir de "Comparar manutenção" tem de cair no Cronograma dela, e
 *   não no painel de energia;
 * - **"Baixar dados" é seção DE USINA da família Geração** — o bloco no fim deste arquivo diz
 *   por quê, e guarda os quatro defeitos que a entrada carrega.
 */

import { describe, expect, it } from 'vitest'

import {
  GRUPOS,
  SECAO_PADRAO,
  SECOES,
  casamentoExato,
  ehDaCarteira,
  paraDaSecao,
  secoesDaFamilia,
  secoesDaUsina,
  sufixoDaSecao,
} from '@/shell/menu'

/** O endereço do item de carteira de uma família, montado como o menu o monta. */
function paraDaCarteira(familia: 'geracao' | 'manutencao'): string | null {
  const item = SECOES.find((s) => s.carteira && s.familia === familia)
  return item ? paraDaSecao(item, 7) : null
}

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

  it('a URL nomeia a família — nas seções de usina e nos comparativos', () => {
    for (const s of secoesDaUsina()) {
      if (s.familia === 'geracao') expect(s.fim.startsWith('/energia')).toBe(true)
      if (s.familia === 'manutencao') expect(s.fim.startsWith('/manutencao')).toBe(true)
    }
    // Na carteira o assunto é o segundo trecho, porque o primeiro é o verbo da pergunta.
    // Link colado num e-mail continua dizendo de que família se trata.
    expect(paraDaCarteira('geracao')).toBe('/comparar/energia')
    expect(paraDaCarteira('manutencao')).toBe('/comparar/manutencao')
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

describe('os comparativos de carteira', () => {
  it('existe um por família, e cada um é o PRIMEIRO item dela', () => {
    for (const familia of ['geracao', 'manutencao'] as const) {
      const itens = secoesDaFamilia(familia)
      expect(itens[0].carteira).toBe(true)
      expect(itens.filter((s) => s.carteira)).toHaveLength(1)
    }
  })

  it('cada um tem rótulo e ícone próprios — no trilho estreito só há o ícone', () => {
    const carteira = SECOES.filter((s) => s.carteira)
    expect(carteira.map((s) => s.rotulo)).toEqual(['Geração', 'Manutenção das usinas'])
    expect(new Set(carteira.map((s) => s.icone)).size).toBe(2)
    // E nenhum repete o ícone-cabeçalho da própria família: dois iguais empilhados
    // apagariam a separação que o cabeçalho existe para mostrar.
    for (const s of carteira) {
      const grupo = GRUPOS.find((g) => g.familia === s.familia)
      expect(s.icone).not.toBe(grupo?.icone)
    }
  })

  it('o endereço NÃO carrega usina — nem quando há uma escolhida', () => {
    expect(paraDaCarteira('geracao')).toBe('/comparar/energia')
    expect(paraDaCarteira('manutencao')).toBe('/comparar/manutencao')
    const item = SECOES.find((s) => s.carteira)
    expect(item).toBeDefined()
    expect(paraDaSecao(item!, null)).toBe('/comparar/energia')
  })

  it('a seção de usina, essa sim, é colada no /usinas/:id — e some sem usina', () => {
    const painel = secoesDaUsina().find((s) => s.fim === '/energia')
    expect(painel).toBeDefined()
    expect(paraDaSecao(painel!, 7)).toBe('/usinas/7/energia')
    // Sem usina não há para onde ir: quem desenha o menu esconde a entrada, em vez de
    // montar `/usinas/null/energia`.
    expect(paraDaSecao(painel!, null)).toBeNull()
  })

  it('trocar de usina a partir de um comparativo cai na família certa', () => {
    // `/comparar/energia` TERMINA em `/energia`: sem a checagem de carteira vir primeiro, a
    // busca pelas seções de usina o reconheceria como "Painel". Aqui a resposta bate por
    // coincidência — é a linha seguinte que separa as duas.
    expect(sufixoDaSecao('/comparar/energia')).toBe('/energia')
    // De "Comparar manutenção" o cliente cai no Cronograma daquela usina, e não no painel
    // de energia dela.
    expect(sufixoDaSecao('/comparar/manutencao')).toBe('/manutencao/cronograma')
  })

  it('o comparativo nunca exige casamento exato', () => {
    expect(casamentoExato('/comparar/energia')).toBe(false)
    expect(casamentoExato('/comparar/manutencao')).toBe(false)
  })

  it('reconhece o caminho de carteira, e só ele', () => {
    expect(ehDaCarteira('/comparar/energia')).toBe(true)
    expect(ehDaCarteira('/comparar/manutencao')).toBe(true)
    expect(ehDaCarteira('/usinas/7/energia')).toBe(false)
    expect(ehDaCarteira('/')).toBe(false)
  })

  it('as seções de usina são as mesmas de antes — nada saiu do menu', () => {
    // Nem os comparativos nem "Baixar dados" podem ter empurrado uma seção para fora: o
    // catálogo de usina cresce no fim da família a que a entrada nova pertence, e o resto
    // fica exatamente na ordem de sempre.
    expect(secoesDaUsina().map((s) => s.fim)).toEqual([
      '/energia',
      '/energia/paradas',
      '/energia/dados',
      '/manutencao/cronograma',
      '/manutencao/ordens',
      '/manutencao/pendencias',
      '/relatorios',
    ])
  })
})

/**
 * "Baixar dados" — a exportação de dados brutos da usina (`/energia/dados`).
 *
 * Quatro defeitos moram nesta entrada, e cada um tem o seu teste:
 *
 * - **o pai engole o filho.** `/usinas/3/energia/dados` contém `/energia/`, então a busca por
 *   sufixo o reconheceria como "Painel" se a ordem do mais específico para o menos falhasse —
 *   e trocar de usina a partir da tela de exportação mandaria o cliente para o painel da
 *   outra. É o mesmo defeito que Paradas já guarda, e ele volta a cada filho novo de
 *   `/energia`;
 * - **a família errada.** A rota do monitoramento é `POST /plants/{slug}/exports/raw`: existe
 *   POR USINA, e o arquivo é só de geração. Entrada de carteira prometeria uma exportação da
 *   carteira inteira que não existe; família `geral` a jogaria no balaio de Relatórios, que é
 *   `geral` justamente por guardar as duas — e ali a lista vazia de fechamentos publicados e
 *   a ausência de dados brutos pareceriam o mesmo problema;
 * - **o endereço sem usina.** Sendo seção de usina, `paraDaSecao` tem de colá-la em
 *   `/usinas/:id` e devolver `null` quando não há usina escolhida — montar
 *   `/usinas/null/energia/dados` levaria o cliente a uma tela em branco;
 * - **o ícone repetido.** No trilho estreito (768–1024 px) não cabe rótulo, e o ícone é a
 *   única âncora: repetir o `Zap` do cabeçalho da família, ou o `FileText` de Relatórios,
 *   apagaria a distinção exatamente onde ela é a única coisa que resta.
 */
describe('a entrada Baixar dados', () => {
  const dados = SECOES.find((s) => s.fim === '/energia/dados')

  it('é a quarta da Geração de energia, logo depois de Paradas', () => {
    expect(secoesDaFamilia('geracao').map((s) => s.fim)).toEqual([
      '/comparar/energia',
      '/energia',
      '/energia/paradas',
      '/energia/dados',
    ])
  })

  it('é seção DE USINA e o rótulo é o verbo — dali se sai com um arquivo', () => {
    expect(dados).toBeDefined()
    expect(dados!.carteira).toBeUndefined()
    expect(dados!.familia).toBe('geracao')
    expect(dados!.rotulo).toBe('Baixar dados')
    expect(secoesDaUsina().some((s) => s.fim === '/energia/dados')).toBe(true)
  })

  it('o Painel não a engole — nem ela às telas mais fundas dele', () => {
    expect(sufixoDaSecao('/usinas/3/energia/dados')).toBe('/energia/dados')
    // E as irmãs continuam respondendo por si.
    expect(sufixoDaSecao('/usinas/3/energia')).toBe('/energia')
    expect(sufixoDaSecao('/usinas/3/energia/paradas')).toBe('/energia/paradas')
  })

  it('o endereço é colado no /usinas/:id — e some sem usina', () => {
    expect(paraDaSecao(dados!, 7)).toBe('/usinas/7/energia/dados')
    expect(paraDaSecao(dados!, null)).toBeNull()
    // Não é carteira: `ehDaCarteira` tem de continuar dizendo não.
    expect(ehDaCarteira('/usinas/7/energia/dados')).toBe(false)
  })

  it('não exige casamento exato, e não tira o do Painel', () => {
    // Nada mora debaixo dela; o Painel, esse sim, tem duas seções debaixo.
    expect(casamentoExato('/energia/dados')).toBe(false)
    expect(casamentoExato('/energia')).toBe(true)
  })

  it('o ícone é só dela — no trilho estreito ele é a única âncora', () => {
    const grupo = GRUPOS.find((g) => g.familia === 'geracao')
    expect(dados!.icone).not.toBe(grupo?.icone)
    const irmas = SECOES.filter((s) => s.fim !== '/energia/dados')
    for (const s of irmas) expect(s.icone).not.toBe(dados!.icone)
  })
})
