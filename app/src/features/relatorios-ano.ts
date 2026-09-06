/**
 * A grade do ano — usina × mês — e as réguas de como desenhá-la.
 *
 * O pedido do dono: *"faça uma versão da tela para o usuário ver facilmente os relatórios
 * do ANO, MÊS A MÊS, e aí, no final do ano, o RELATÓRIO ANUAL — isso POR USINA. Tanto
 * GERAÇÃO quanto MANUTENÇÃO, TÉCNICO e EXECUTIVO."*
 *
 * ## Por que é uma tela empurrada, e não a sexta aba
 *
 * A grade custa **uma ida de 4,7 s** contra a carteira real de sete usinas (medido em
 * 05/09/2026, morno, desta máquina contra Railway/Supabase). Quem abre a aba Relatórios
 * para pegar o PDF de agosto não pode pagar por isso — e a barra de abas responde "que
 * assunto?", não "que tela?". Daí a aba abrir na lista e um item fixo levar aqui.
 *
 * ## As duas famílias NÃO se misturam
 *
 * Energia é **acervo publicado**: existe porque alguém do monitoramento publicou; vazio quer
 * dizer "a equipe ainda não publicou". Manutenção é **montada sob demanda** a partir do
 * ativo: vazio quer dizer "não houve manutenção no período". Uma tem `publicado_em`, a outra
 * tem janela de contrato. Por isso o segmentado, e por isso as duas viajam separadas dentro
 * da mesma resposta — fundi-las faria a falha de uma apagar a outra, que é o caso que
 * acontece primeiro (medido hoje: quatro fechamentos sem arquivo e um só cronograma
 * consolidado em sete usinas).
 *
 * ## Aqui não se faz UMA conta de conformidade
 *
 * `pct_ate_hoje`, `previsto_ate_hoje`, `cumprido_ate_hoje`, `mes_referencia` e
 * `previsto_no_contrato` chegam prontos do meuPlano, atravessam o BFF sem serem tocados e
 * saem desta tela do mesmo jeito. Refazer a divisão aqui criaria a TERCEIRA resposta para
 * "está sendo feito?" — a lição de **"13 de 270" numa tela e "41,9 %" na outra**, para a
 * mesma usina, no mesmo dia. O percentual nunca aparece sozinho: vai sempre com o
 * denominador e o mês de referência colados.
 *
 * ## O calendário não vem do relógio do celular
 *
 * Quais meses já venceram é decisão do meuPlano (`situacao`: `fechado` · `corrente` ·
 * `futuro`), repassada. Derivar isso de `new Date()` aqui acusaria de atraso um mês que
 * ainda não venceu — e, com o aparelho noutro fuso, no dia 1º acusaria o mês inteiro.
 *
 * **Este arquivo não importa nada do React Native** de propósito, salvo o gancho de leitura:
 * as réguas abaixo são texto e aritmética, e é assim que `tests/relatorios-ano.test.ts`
 * consegue exercitá-las no Node sem subir um aparelho.
 */

import {
  DESTINO_DO_MENSAL,
  NOME_CURTO_DO_MENSAL,
  PECAS,
  ROTULO_DO_PUBLICO,
  type Publico,
} from '@/features/relatorios'
import { baseURL, tokenDaSessao } from '@/lib/api'
import { fetchWithCache, type Leitura } from '@/lib/cache'
import { competencia } from '@/lib/format'
import type { Tom } from '@/theme/tokens'

/* ═════════════════════════════════════════════════════════════ o que o BFF manda ══ */

export type PecaDoAno = {
  /** `geracao` · `paradas` · `resumo`. É o `tipo` que `/documents/{id}/file` aceita. */
  tipo: string
  nome: string
  /** Peso declarado pelo monitoramento. **Nulo é ausência** e vira travessão, nunca `0`. */
  bytes: number | null
}

/**
 * Os cinco nomes da geração naquele mês.
 *
 * São cinco porque são cinco situações diferentes, e a tela antiga tinha **uma frase** para
 * todas ("Sem arquivo anexado") — que o dono lia como "o aplicativo não baixou".
 */
export type EstadoDaEnergia =
  /** Há fechamento e ele tem ao menos uma peça para abrir. */
  | 'publicado'
  /** Alguém fechou o mês e o arquivo não subiu (ou foi retirado depois). */
  | 'fechamento_sem_arquivo'
  /** O mês não foi fechado. A única das cinco que é ausência de dado. */
  | 'sem_fechamento'
  /** A usina não está ligada ao monitoramento; não há de onde vir. */
  | 'sem_monitoramento'
  /** A ponte não respondeu NESTE pedido. "Não sabemos" ≠ "ninguém publicou". */
  | 'indisponivel'

export type EnergiaDoMes = {
  estado: EstadoDaEnergia | string
  documento_id: number | null
  /** Quando o fechamento foi ENVIADO. Não é o mês da célula — esse é a coluna. */
  publicado_em: string | null
  pecas: PecaDoAno[]
}

/**
 * Um relatório mensal de manutenção **já liberado ao cliente**, na medida da célula.
 *
 * Só o par que a folha precisa para oferecer o toque: qual dos dois documentos é, e qual id
 * abrir. O resto do cartão — usina, competência, data de publicação — viaja completo em
 * `/documents`, e repeti-lo aqui daria duas cópias da mesma verdade no mesmo pedido.
 *
 * **Não tem peso.** O BFF não manda bytes nesta lista, e inventar um número para mostrar
 * antes do toque seria exatamente o que a Regra 0 proíbe.
 */
export type MensalDaCelula = {
  /** `executivo` · `tecnico`, **cru**. Um valor novo do meuPlano chega à tela, não some. */
  tipo: string
  /** O id do relatório **no meuPlano** — o que a rota do PDF mensal aceita. */
  relatorio_id: number
}

export type ManutencaoDoMes = {
  /** `fechado` · `corrente` · `futuro`, como o meuPlano classificou. */
  situacao: string | null
  /** Σ de X previstos no mês. Nulo = não disse; **zero é resposta**. */
  previsto: number | null
  cumprido: number | null
  /**
   * Os relatórios mensais liberados daquele mês, **executivo primeiro** — a ordem é do BFF
   * e não se refaz aqui: duas ordens seriam duas respostas para a mesma pergunta.
   *
   * ⚠ **Não entra na marca da célula.** A cor responde "foi feito?" (conformidade, dos três
   * campos acima); isto responde "há papel sobre isso?". Se a existência do documento
   * pintasse a célula, a grade responderia duas perguntas com uma cor só — e hoje ficaria
   * inteira em travessão nas 22 usinas, porque o acervo liberado começou este mês.
   */
  mensais?: MensalDaCelula[]
}

export type CelulaDoAno = {
  /** `YYYY-MM`. */
  mes: string
  energia: EnergiaDoMes
  /**
   * Ausente quando o mês não pertence ao contrato **e** não há relatório liberado nele —
   * nunca um bloco de zeros.
   *
   * ⚠ **`manutencao != null` deixou de significar "mês do contrato".** O mês fora da
   * vigência que tem documento liberado (acontece assim que o contrato vira e o
   * `meses_estado` passa a cobrir outra janela) ganha um bloco trazendo **só** `mensais`,
   * com `situacao`/`previsto`/`cumprido` ausentes — senão o relatório que a equipe
   * entregou sumiria da grade do ano em que foi entregue. Quem pergunta "é mês do
   * contrato?" testa `manutencao.situacao`, não a presença do bloco.
   */
  manutencao: ManutencaoDoMes | null
}

export type AnualDeEnergia = {
  disponivel: boolean
  /** Por que não há o que abrir. Preenchido sempre que `disponivel` é falso. */
  motivo: string | null
  estado: string | null
  documento_id: number | null
  pecas: PecaDoAno[]
}

export type AnualDeManutencao = {
  disponivel: boolean
  motivo: string | null
  /** `YYYY-MM`. Nulos quando `disponivel` é falso. */
  de: string | null
  ate: string | null
}

export type UsinaDoAno = {
  id: number
  nome: string
  tem_monitoramento: boolean
  tem_manutencao: boolean
  contrato: string | null
  contrato_id: number | null
  cronograma_status: string | null
  cronograma_versao: number | null

  /* ── o recorte de vigência: chega PRONTO e é só repassado ─────────────────── */
  mes_referencia: string | null
  previsto_ate_hoje: number | null
  cumprido_ate_hoje: number | null
  pct_ate_hoje: number | null
  /** Σ de X dos 12 meses do contrato — o "269" da aba Cronograma. */
  previsto_no_contrato: number | null

  meses: CelulaDoAno[]
  anual: { energia: AnualDeEnergia; manutencao: AnualDeManutencao }
  /**
   * O que falhou na MANUTENÇÃO desta usina. A queda de uma não apaga as outras seis.
   *
   * O nome diz a família de propósito. Antes o campo se chamava `aviso` e trazia a
   * família escrita na prosa (`"Manutenção: ..."`); a tela arrancava o prefixo com uma
   * expressão regular e imprimia a frase nas DUAS abas — na coluna de geração o dono lia
   * "a equipe ainda não publicou o cronograma", cortado em uma linha, ao lado de uma
   * célula que falava de outra coisa. Motivo só aparece na aba de que ele é.
   */
  aviso_manutencao: string | null
  /**
   * O que falhou ao buscar o **acervo mensal liberado** desta usina.
   *
   * Campo próprio, e não um pedaço de `aviso_manutencao`, porque as duas coisas respondem
   * a perguntas diferentes: "a equipe publicou o cronograma?" (conformidade) × "o
   * documento do mês está disponível?" (papel). Juntá-las repetiria, com outro nome, o
   * defeito que este módulo já pagou uma vez.
   */
  aviso_mensais: string | null
}

export type GradeDoAnoOut = {
  ano: number
  /** Os 12 rótulos `YYYY-MM`, na ordem das colunas. */
  meses: string[]
  usinas: UsinaDoAno[]
  /** O que falhou para TODA a carteira. Falha de manutenção mora em
   *  `UsinaDoAno.aviso_manutencao`. */
  aviso: string | null
}

/**
 * A grade de um ano.
 *
 * **O ano entra na CHAVE do cache**, e não só na URL: com uma chave só, abrir 2025 e voltar
 * para 2026 leria do disco a grade do ano errado — e no modo avião leria para sempre.
 *
 * O prazo maior que o padrão de 12 s vem de medição, não de palpite: a grade custou 4,7 s
 * morna e 8,5 s fria contra a carteira real. Com os 12 s de sempre, a primeira abertura numa
 * rede de campo desistiria de uma resposta que estava a caminho.
 */
export function useGradeDoAno(ano: number): Leitura<GradeDoAnoOut> {
  return fetchWithCache<GradeDoAnoOut>(`relatorios/ano-${ano}`, {
    caminho: `/api/v1/relatorios/ano?ano=${ano}`,
    prazoMs: 45000,
  })
}

/* ══════════════════════════════════════════════════════════════ a marca da célula ══ */

/**
 * O desenho de uma célula.
 *
 * `forte` distingue **preenchido** (há coisa) de **contornado** (não há) — é o que impede as
 * cinco ausências de virarem cinco tons do mesmo cinza. `nota` é o denominador miúdo sob o
 * número, para o mês da manutenção dizer "13" e "de 13" sem virar uma coluna de 60 pt.
 */
export type Marca = {
  letra: string
  tom: Tom
  forte: boolean
  /** O que a célula significa, por extenso. Vai para o leitor de tela e para a folha. */
  rotulo: string
  nota?: string
}

/** Célula sem nada a desenhar: mês fora do contrato. Não é falta — é ausência de combinado. */
const VAZIA: Marca = { letra: '', tom: 'semDados', forte: false, rotulo: 'Fora do contrato' }

/**
 * A marca da geração. Cinco estados, cinco desenhos.
 *
 * O número dentro da célula preenchida é a **quantidade de peças** — é a diferença entre o
 * fechamento de Porto Ferreira em agosto (Geração + Paradas) e o de Pereiras no mesmo mês
 * (só o Resumo Executivo), que a tela precisa mostrar sem obrigar a abrir os dois.
 */
export function marcaDaEnergia(e: EnergiaDoMes | null | undefined): Marca {
  if (!e) return VAZIA
  switch (e.estado) {
    case 'publicado': {
      const n = e.pecas.length
      return {
        letra: String(n),
        tom: 'ok',
        forte: true,
        rotulo: n === 1 ? '1 arquivo publicado' : `${n} arquivos publicados`,
      }
    }
    case 'fechamento_sem_arquivo':
      return { letra: '!', tom: 'alerta', forte: false, rotulo: 'Fechado, sem arquivo anexado' }
    case 'sem_fechamento':
      return { letra: '·', tom: 'semDados', forte: false, rotulo: 'Mês não fechado' }
    case 'sem_monitoramento':
      return { letra: '—', tom: 'semDados', forte: false, rotulo: 'Usina sem monitoramento' }
    case 'indisponivel':
      return { letra: '?', tom: 'tempoRuim', forte: false, rotulo: 'Não deu para saber agora' }
    default:
      // Estado novo do servidor aparece como desconhecido em vez de ser achatado num dos
      // cinco. Achatar seria afirmar uma coisa que ninguém disse.
      return { letra: '?', tom: 'semDados', forte: false, rotulo: e.estado || 'Desconhecido' }
  }
}

/**
 * A marca da manutenção no mês.
 *
 * **`futuro` nunca é vermelho.** Não se cobra o que não venceu; pintar de falta um mês que
 * ainda nem chegou é a acusação falsa que esta régua existe para impedir. Medido hoje em
 * Porto Ferreira: out (13), nov (31) e dez (18) estão nesse estado e somam 62 atividades que
 * a tela desenharia como atraso se a régua saísse do relógio do celular.
 *
 * O `cumprido` do meuPlano **já soma executado e dispensado-com-motivo** — a diferença entre
 * os dois existe por atividade, na tela de Cronograma, e não neste agregado mensal. A folha
 * diz isso em vez de a tela fingir que só há uma coisa lá dentro.
 */
export function marcaDaManutencao(m: ManutencaoDoMes | null | undefined): Marca {
  if (!m || m.situacao === null) return VAZIA

  const previsto = m.previsto ?? 0
  const cumprido = m.cumprido ?? 0
  if (previsto === 0) {
    return { letra: '·', tom: 'semDados', forte: false, rotulo: 'Nada previsto neste mês' }
  }

  const nota = `de ${previsto}`
  switch (m.situacao) {
    case 'futuro':
      return {
        letra: String(previsto),
        tom: 'tempoRuim',
        forte: false,
        rotulo: `${previsto} previstas — o mês ainda não venceu`,
        nota: 'previstas',
      }
    case 'corrente':
      return {
        letra: String(cumprido),
        tom: cumprido >= previsto ? 'ok' : 'alerta',
        forte: cumprido >= previsto,
        rotulo: `${cumprido} de ${previsto} — mês em curso`,
        nota,
      }
    case 'fechado':
      return {
        letra: String(cumprido),
        tom: cumprido >= previsto ? 'ok' : 'parado',
        forte: cumprido >= previsto,
        rotulo:
          cumprido >= previsto
            ? `${cumprido} de ${previsto} — mês cumprido`
            : `${cumprido} de ${previsto} — o mês venceu incompleto`,
        nota,
      }
    default:
      return {
        letra: String(cumprido),
        tom: 'semDados',
        forte: false,
        rotulo: `${cumprido} de ${previsto} · ${m.situacao}`,
        nota,
      }
  }
}

/* ═══════════════════════════════════════════════════════════ o recorte de vigência ══ */

export type Recorte = {
  pct: number
  cumprido: number
  previsto: number
  mesReferencia: string
  /** "13 de 31 até setembro de 2026" — o percentual nunca sai sem isto ao lado. */
  frase: string
  /** O outro número, com o rótulo que o explica. Nulo quando o servidor não o mandou. */
  noContrato: number | null
}

/**
 * O recorte de vigência da usina, pronto para a tela — **sem uma divisão sequer**.
 *
 * Devolve `null` quando o meuPlano não calculou (é o caso de cinco das seis usinas com
 * contrato hoje, que ainda não têm cronograma consolidado). Nulo aqui vira "a equipe ainda
 * não publicou o cronograma", nunca "0 %".
 */
export function recorteDoAno(u: UsinaDoAno): Recorte | null {
  const { pct_ate_hoje: pct, previsto_ate_hoje: previsto, cumprido_ate_hoje: cumprido } = u
  if (pct === null || previsto === null || cumprido === null || !u.mes_referencia) return null
  return {
    pct,
    cumprido,
    previsto,
    mesReferencia: u.mes_referencia,
    frase: `${cumprido} de ${previsto} até ${competencia(u.mes_referencia).toLowerCase()}`,
    noContrato: u.previsto_no_contrato,
  }
}

/* ══════════════════════════════════════════════════════════════════════ a janela ══ */

const MESES_LONGOS = [
  'janeiro',
  'fevereiro',
  'março',
  'abril',
  'maio',
  'junho',
  'julho',
  'agosto',
  'setembro',
  'outubro',
  'novembro',
  'dezembro',
]

/**
 * A janela do relatório anual, POR EXTENSO — impressa, nunca implícita.
 *
 * "O ano" é `janeiro..mês corrente` enquanto o ano corre: medido hoje, pedir
 * `2026-01..2026-12` responde **400 "ate não pode ser um mês futuro."** O servidor declara a
 * janela e a tela a escreve ao lado do botão, porque foi a falta desse recorte que produziu
 * "13 de 270" numa tela e "41,9 %" na outra.
 *
 * Fatia de string, **nunca `new Date`**: `new Date('2026-01')` é UTC e no Brasil volta para
 * dezembro do ano anterior.
 */
export function janelaPorExtenso(de: string | null, ate: string | null): string | null {
  if (!de || !ate) return null
  const nome = (m: string) => MESES_LONGOS[Number(m.slice(5, 7)) - 1] ?? m.slice(5, 7)
  const ano = (m: string) => m.slice(0, 4)
  if (de === ate) return `${nome(de)} de ${ano(de)}`
  if (ano(de) === ano(ate)) return `${nome(de)} a ${nome(ate)} de ${ano(de)}`
  return `${nome(de)} de ${ano(de)} a ${nome(ate)} de ${ano(ate)}`
}

/* ═════════════════════════════════════════════════════════════ o filtro de usina ══ */

export type OpcaoDeUsina = { valor: string | null; rotulo: string; contagem: number }

export type Familia = 'energia' | 'manutencao'

/** Quantos meses desta usina têm coisa nesta família. É o que a opção promete ANTES do toque. */
export function mesesComConteudo(u: UsinaDoAno, familia: Familia): number {
  return u.meses.filter((c) =>
    familia === 'energia' ? c.energia.estado === 'publicado' : c.manutencao?.situacao != null,
  ).length
}

/**
 * As opções do seletor de usina, com contagem — **lista suspensa, nunca chip**.
 *
 * "Todas" é uma escolha legítima e vem primeiro. Opção com zero **continua na lista**: sumir
 * faria quem procura por ela concluir que o aplicativo perdeu a usina.
 */
export function opcoesDeUsina(usinas: UsinaDoAno[], familia: Familia): OpcaoDeUsina[] {
  return [
    {
      valor: null,
      rotulo: 'Todas as usinas',
      contagem: usinas.reduce((s, u) => s + mesesComConteudo(u, familia), 0),
    },
    ...usinas.map((u) => ({
      valor: String(u.id),
      rotulo: u.nome,
      contagem: mesesComConteudo(u, familia),
    })),
  ]
}

/**
 * Grampeia a escolha contra o que existe.
 *
 * Sem isto, uma usina guardada que saiu do escopo — ou que não veio nesta resposta — deixa a
 * tela vazia para sempre, sem explicação. É a mesma trava que a aba Manutenção já usa.
 */
export function usinaEscolhida(usinas: UsinaDoAno[], valor: string | null): string | null {
  if (valor === null) return null
  return usinas.some((u) => String(u.id) === valor) ? valor : null
}

export function linhasVisiveis(usinas: UsinaDoAno[], escolhida: string | null): UsinaDoAno[] {
  const alvo = usinaEscolhida(usinas, escolhida)
  return alvo === null ? usinas : usinas.filter((u) => String(u.id) === alvo)
}

/**
 * Os anos que o seletor oferece.
 *
 * O servidor aceita de 2000 até o ano seguinte (medido: com 2026 corrente, `ano=2027`
 * responde 200 e `ano=2028` responde **400 "Ano fora do alcance"**). Oferecer um ano que o
 * servidor recusa seria construir um erro para o dono achar.
 */
export function anosOferecidos(anoCorrente: number, quantos = 4): number[] {
  const anos: number[] = [anoCorrente + 1]
  for (let i = 0; anos.length < quantos; i += 1) anos.push(anoCorrente - i)
  return anos
}

/* ══════════════════════════════════════════════════════════════ o público da peça ══ */

/**
 * "TÉCNICO"/"EXECUTIVO" de uma peça — a metade do pedido que **existe**.
 *
 * A classificação mora em `features/relatorios.ts`, fonte única, e é lida daqui em vez de
 * copiada: duas cópias é o mesmo que duas respostas, e esse mapa já esteve duplicado uma vez.
 */
export function publicoDaPeca(tipo: string): Publico | null {
  return PECAS[tipo]?.publico ?? null
}

export function rotuloDoPublico(tipo: string): string | null {
  const p = publicoDaPeca(tipo)
  return p ? ROTULO_DO_PUBLICO[p].toUpperCase() : null
}

/**
 * Onde mora o executivo da manutenção — e por que esta consulta continua saindo num formato só.
 *
 * A frase anterior dizia, numa tela em produção, que *"uma versão executiva, resumida para a
 * diretoria, ainda não existe no sistema"*. **Existe**: o meuPlano ganhou o relatório mensal
 * em dois documentos (`executivo` e `tecnico`), e o executivo de Porto Ferreira de agosto foi
 * medido em 403.775 B, 3 páginas.
 *
 * Mas apagar a frase deixaria o buraco sem nome, porque a metade que **continua** faltando é
 * outra: **não há parâmetro de modo nesta consulta**. A janela livre (`de`..`ate`) sai num
 * formato só, e o executivo não é um modo dela — é outro documento, de outro fluxo, que
 * nasce no fechamento de um mês e passa por liberação. Manter a frase mentiria; apagá-la
 * esconderia o limite. Ela passa a apontar onde o executivo mora.
 */
export function frasePublicoDaManutencao(): string {
  return 'Esta consulta sai num formato só: o relatório técnico da janela escolhida. A versão executiva, resumida para a diretoria, é outro documento — ela existe no relatório mensal liberado, mês a mês, e aparece na folha do mês assim que a equipe o libera.'
}

/* ═════════════════════════════════════════════════════ o relatório mensal liberado ══ */

/**
 * Como se chama cada um dos dois documentos do mês — **lido da fonte única**
 * (`features/relatorios`), nunca copiado.
 *
 * Aqui vale o nome CURTO ("Executivo"), porque ele entra dentro de um botão cujo cabeçalho
 * já disse que a folha é de manutenção; na lista do acervo vale o nome inteiro ("Relatório
 * executivo"). São dois comprimentos do mesmo nome, decididos num arquivo só — o mapa já
 * esteve duplicado nesta base, e duas cópias é o mesmo que duas respostas.
 *
 * O BFF repassa o `tipo` **cru** de propósito — um valor novo do meuPlano tem de chegar à
 * tela, não sumir num mapa deste lado. Por isso tipo desconhecido devolve `null`, e a tela
 * escreve o código como veio em vez de achatá-lo num dos dois nomes.
 */
export function rotuloDoMensal(tipo: string): string | null {
  return NOME_CURTO_DO_MENSAL[tipo] ?? null
}

/** Para quem cada um dos dois foi escrito — a MESMA frase do portal e da lista do acervo. */
export function destinoDoMensal(tipo: string): string | null {
  return DESTINO_DO_MENSAL[tipo] ?? null
}

/**
 * Os documentos liberados de um mês, na ordem em que o servidor os mandou.
 *
 * **Não reordena.** A ordem é uma decisão só, e ela é do BFF (`ORDEM_DO_TIPO`, executivo
 * antes de técnico, porque a diretoria é o destino declarado do executivo). Refazê-la aqui
 * criaria a segunda fonte da mesma regra — e no dia em que as duas discordassem, o portal e
 * o celular mostrariam ordens diferentes para o mesmo mês.
 */
export function mensaisDoMes(m: ManutencaoDoMes | null | undefined): MensalDaCelula[] {
  return m?.mensais ?? []
}

/**
 * Por que a folha do mês não tem documento liberado para oferecer.
 *
 * Duas razões diferentes, e a tela **nunca fica muda** com nenhuma delas: ou a ponte não
 * respondeu (aí a frase é a do servidor, que sabe o que caiu), ou ninguém liberou ainda —
 * que foi o estado de **toda a base** no dia desta entrega (os 26 relatórios de agosto/2026
 * estavam em rascunho, e a rota do cliente respondia 200 com lista vazia, corretamente).
 *
 * Uma tela vazia ali se leria como defeito do aplicativo. E a frase manda para a saída que
 * existe: a consulta logo abaixo, que monta os mesmos números agora.
 */
export function fraseSemMensal(mes: string, avisoDaUsina: string | null): string {
  if (avisoDaUsina) return avisoDaUsina
  return `O relatório de ${competencia(mes).toLowerCase()} ainda não foi liberado pela equipe. A consulta abaixo monta os mesmos números agora.`
}

/**
 * A frase que fica embaixo da consulta — e por que ela tem DUAS versões.
 *
 * O defeito, medido na tela pelo dono (06/09/2026): na folha de setembro, que não tem
 * documento liberado, o rodapé continuava dizendo *"o relatório liberado **acima**"* — não
 * havia nada acima. Uma tela que aponta para o que não está nela é pior que uma tela muda:
 * manda procurar.
 *
 * Com documento liberado, a frase existe para o caso em que os dois números discordam: são
 * a MESMA apuração lida em tempos diferentes, e dizer isso é o que impede a pergunta "qual
 * é o certo?". Sem documento, ela diz onde o do fechamento vai aparecer.
 */
export function fraseDaConsulta(temLiberado: boolean): string {
  if (temLiberado) {
    return 'A consulta é montada agora, com o que o sistema sabe hoje. O relatório liberado acima é o do fechamento: se os dois discordarem, a diferença é o tempo entre um e outro, não erro de nenhum deles.'
  }
  return 'A consulta é montada agora, com o que o sistema sabe hoje. Quando a equipe liberar o relatório deste mês, ele aparece aqui em cima — e é ele o documento do fechamento, assinado.'
}

/**
 * O PDF de um relatório mensal liberado.
 *
 * O id é o do **relatório no meuPlano**, não o do vínculo: os dois são inteiros pequenos e
 * trocá-los abriria outro documento sem erro nenhum. A sessão vai em cabeçalho, como todo
 * arquivo deste aplicativo — token nunca entra em URL, que vai para log.
 */
export function urlDoRelatorioMensal(relatorioId: number): string {
  return `${baseURL}/api/v1/manutencao/relatorios-mensais/${relatorioId}/pdf`
}

/**
 * O nome com que o arquivo desce.
 *
 * Distinto do da consulta por janela (`relatorio-manutencao-…`) **de propósito**: dois
 * arquivos homônimos na pasta de Downloads do cliente é como a pergunta "qual é o certo?"
 * começa. Um é o documento assinado do fechamento; o outro é uma leitura ao vivo.
 */
export function arquivoDoMensal(usinaId: number, mes: string, tipo: string): string {
  return `relatorio-mensal-${tipo}-${usinaId}-${mes}.pdf`
}

/** Por que não há fechamento anual de geração — e por que não existe botão nessa célula. */
export function fraseAnualDeEnergia(a: AnualDeEnergia): string {
  return a.motivo ?? 'O monitoramento ainda não publica fechamento anual.'
}

/* ═══════════════════════════════════════════════════════════════ o pacote de fichas ══ */

export type ParteDoPacote = { numero: number; fichas: number; bytes: number | null }

export type InventarioDeFichas = {
  usina: string
  usina_id: number
  de: string
  ate: string
  /** Quantas fichas o filtro pegou. Zero é resposta legítima. */
  total: number
  /** Quantas já têm PDF. `prontas < total` = o botão é "Preparar", não "Baixar". */
  prontas: number
  /** Nulo quando nada está pronto — a tela escreve travessão, nunca "0 MB". */
  bytes_estimados: number | null
  partes: ParteDoPacote[]
  aviso: string | null
}

export type PreparoDeFichas = {
  preparo_id: string
  total: number
  prontas: number
  concluido: boolean
  /** `andando` · `pronto` · `falhou`. `concluido` sozinho não separa "terminou" de "parou". */
  estado: string
  erro: string | null
  erros: unknown[]
  aviso: string | null
}

/**
 * Acima disto o pacote não desce no celular.
 *
 * O download passa o ZIP inteiro por um `ArrayBuffer` em memória. O pacote do ano de Porto
 * Ferreira mede **27.071.615 B** (27 fichas) e cabe; um contrato com o dobro de equipamentos
 * não caberia, e o aplicativo morreria sem dizer por quê. Acima do teto a tela manda para o
 * site em vez de oferecer um botão que derruba o aparelho.
 */
export const TETO_DO_PACOTE = 60_000_000

/**
 * O que a tela oferece diante de um inventário — decidido aqui, e não no meio do JSX.
 *
 * Medido hoje em Porto Ferreira (jan..set): **27 fichas, 26 prontas, 27.071.615 B, 1 parte**.
 * Uma ficha sem PDF é o suficiente para o pacote sair incompleto — e "baixei dezessete e
 * vieram três" é exatamente o defeito que o caminho de três atos existe para evitar.
 */
export type Oferta =
  | { tipo: 'vazio'; motivo: string }
  | { tipo: 'grande'; motivo: string }
  | { tipo: 'preparar'; faltam: number }
  | { tipo: 'baixar'; partes: ParteDoPacote[] }

export function ofertaDoPacote(i: InventarioDeFichas): Oferta {
  if (i.total <= 0) {
    return { tipo: 'vazio', motivo: i.aviso ?? 'Nenhuma ficha registrada neste período.' }
  }
  const bytes = i.bytes_estimados
  if (bytes !== null && bytes > TETO_DO_PACOTE) {
    return {
      tipo: 'grande',
      motivo:
        'O pacote deste período é grande demais para baixar no celular. Ele continua disponível pelo site.',
    }
  }
  if (i.prontas < i.total) return { tipo: 'preparar', faltam: i.total - i.prontas }
  const partes = i.partes.length
    ? i.partes
    : [{ numero: 1, fichas: i.total, bytes: i.bytes_estimados }]
  return { tipo: 'baixar', partes }
}

async function pedir<T>(caminho: string, metodo: 'GET' | 'POST' = 'GET'): Promise<T> {
  const r = await fetch(`${baseURL}${caminho}`, {
    method: metodo,
    headers: { Authorization: `Bearer ${tokenDaSessao() ?? ''}` },
  })
  if (!r.ok) {
    // A frase é a do SERVIDOR. Adivinhar pelo número do status foi o defeito que `lib/pdf`
    // já corrigiu uma vez: uma questão de permissão chegava como "não conseguiu gerar".
    let detalhe: string | null = null
    try {
      const corpo = (await r.json()) as { detail?: unknown }
      detalhe = typeof corpo.detail === 'string' ? corpo.detail : null
    } catch {
      detalhe = null
    }
    throw new Error(detalhe ?? `Não deu para falar com o servidor (erro ${r.status}).`)
  }
  return (await r.json()) as T
}

const janela = (usinaId: number, de: string, ate: string) =>
  `usina_id=${usinaId}&de=${encodeURIComponent(de)}&ate=${encodeURIComponent(ate)}`

/**
 * O que o pacote traria — respondido ANTES de qualquer download.
 *
 * Não passa pelo cache em disco de propósito: é consulta pontual, feita no toque, e guardá-la
 * encheria o cache com uma entrada por usina tocada. E um inventário velho prometeria um
 * tamanho que o pacote não tem mais.
 */
export function inventarioDeFichas(
  usinaId: number,
  de: string,
  ate: string,
): Promise<InventarioDeFichas> {
  return pedir<InventarioDeFichas>(`/api/v1/manutencao/fichas?${janela(usinaId, de, ate)}`)
}

export function prepararFichas(usinaId: number, de: string, ate: string): Promise<PreparoDeFichas> {
  return pedir<PreparoDeFichas>(
    `/api/v1/manutencao/fichas/preparar?${janela(usinaId, de, ate)}`,
    'POST',
  )
}

export function andamentoDoPreparo(preparoId: string): Promise<PreparoDeFichas> {
  return pedir<PreparoDeFichas>(`/api/v1/manutencao/fichas/preparo/${encodeURIComponent(preparoId)}`)
}

export function urlDoPacoteDeFichas(usinaId: number, de: string, ate: string, parte = 1): string {
  return `${baseURL}/api/v1/manutencao/fichas/pacote?${janela(usinaId, de, ate)}&parte=${parte}`
}

/** O relatório de manutenção da janela, em PDF. A sessão vai em cabeçalho, nunca na URL. */
export function urlDoRelatorioDeManutencao(usinaId: number, de: string, ate: string): string {
  return `${baseURL}/api/v1/manutencao/relatorio/pdf?${janela(usinaId, de, ate)}`
}

/* ══════════════════════════════════════════════════════════════ guarda de contrato ══ */

/**
 * Os campos que esta tela LÊ do BFF, por modelo Pydantic.
 *
 * O teste confere um a um contra `bff/app/api/v1/relatorios_ano.py`. É a família que teria
 * pegado, no minuto da renomeação, o "Contrato nº undefined" que chegou à tela do dono: o
 * BFF renomeou um campo, o portal acompanhou porque tem suíte, e o celular seguiu lendo um
 * nome que não existia mais — com o cache em disco fazendo o defeito piscar.
 */
export const CAMPOS_LIDOS = {
  RelatoriosAnoOut: ['ano', 'meses', 'usinas', 'aviso'],
  UsinaAnoOut: [
    'id',
    'nome',
    'tem_monitoramento',
    'tem_manutencao',
    'contrato',
    'cronograma_status',
    'cronograma_versao',
    'mes_referencia',
    'previsto_ate_hoje',
    'cumprido_ate_hoje',
    'pct_ate_hoje',
    'previsto_no_contrato',
    'meses',
    'anual',
    'aviso_manutencao',
    'aviso_mensais',
  ],
  CelulaOut: ['mes', 'energia', 'manutencao'],
  EnergiaCelulaOut: ['estado', 'documento_id', 'publicado_em', 'pecas'],
  ManutencaoCelulaOut: ['situacao', 'previsto', 'cumprido', 'mensais'],
  MensalNaCelulaOut: ['tipo', 'relatorio_id'],
  PecaOut: ['tipo', 'nome', 'bytes'],
  AnualEnergiaOut: ['disponivel', 'motivo', 'estado', 'documento_id', 'pecas'],
  AnualManutencaoOut: ['disponivel', 'motivo', 'de', 'ate'],
  InventarioOut: ['usina', 'usina_id', 'de', 'ate', 'total', 'prontas', 'bytes_estimados', 'partes', 'aviso'],
  ParteOut: ['numero', 'fichas', 'bytes'],
  PreparoOut: ['preparo_id', 'total', 'prontas', 'concluido', 'estado', 'erro', 'erros', 'aviso'],
} as const
