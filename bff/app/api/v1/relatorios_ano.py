"""A grade do ano — usina × mês, geração e manutenção lado a lado, numa ida só.

O pedido do dono: *"faça uma versão da tela para o usuário ver facilmente os relatórios do
ANO, MÊS A MÊS, e aí, no final do ano, o RELATÓRIO ANUAL — isso POR USINA. Tanto GERAÇÃO
quanto MANUTENÇÃO"*.

### Por que uma rota, e não a tela montando o eixo

As duas formas óbvias estão medidas e as duas são ruins para quem está em campo:

* perguntar mês a mês ao `/manutencao/relatorio` custa **9 chamadas, 3.511 ms e 84,5 KB**
  para extrair um número por mês;
* o `meses_estado` — que já traz os 12 meses classificados `fechado`/`corrente`/`futuro`
  com previsto e cumprido, exatamente a faixa que esta tela quer — vem escondido dentro
  dos **127.668 bytes** de `/manutencao/cronograma`, dos quais ele é **880**: 0,6 %. Um
  celular baixaria 130 KB por usina para usar 6 KB, pagando 7 idas.

Daí esta rota: **o eixo montado num lugar só**, para as duas famílias não se contradizerem
na última milha.

### O que este módulo NÃO faz

**Nenhuma aritmética de conformidade.** `situacao`, `previsto` e `cumprido` de cada célula
são o `meses_estado` do meuPlano **repassado cru**, e `previsto_ate_hoje` e companhia vêm
do mesmo lugar, prontos. Refazer a conta aqui criaria a TERCEIRA resposta para "está sendo
feito?" — a lição de **"13 de 270" numa tela e "41,9 %" na outra**, para a mesma usina, no
mesmo dia. Por isso o teste `test_a_soma_das_celulas_bate_com_o_recorte_de_vigencia` existe:
ele prova que os dois números que esta rota entrega para a MESMA pergunta são o mesmo número.

E a prova de que não recalcular não é preguiça: medido em Porto Ferreira hoje,
`previsto_ate_hoje` = **31** = 13 (agosto, `fechado`) **+ 18** (setembro, `corrente`, o
`mes_referencia`). Somar só os meses `fechado` daria 13 — um percentual de 100 % onde o
meuPlano diz 41,9 %. A régua "até hoje" inclui o mês em curso, e ela é de lá.

### Composição por DENTRO

`documentos_de_geracao`, `mensais_das_usinas` e `cronograma_da_usina` são chamados como
**funções**, nunca por HTTP contra o próprio serviço — o padrão já estabelecido em
`carteira.py`. É `documentos_de_geracao` e não a rota `/documents` de propósito: a rota
compõe a família mensal por conta dela, e chamá-la aqui buscaria o mesmo acervo duas vezes
no mesmo pedido.

A energia é **uma** ida ao meuWatt para a carteira inteira (`portal_relatorios` busca tudo
de qualquer jeito); a manutenção é uma ida por usina para o cronograma **mais uma** para o
acervo mensal, as duas dividindo o mesmo semáforo — a Visão geral já custou 22 s por
disparar ~64 chamadas de uma vez.

### As cinco ausências da geração têm cinco nomes

`sem_fechamento` ≠ `fechamento_sem_arquivo` ≠ `sem_monitoramento` ≠ `indisponivel`, e a
tela desenha cada uma diferente. Medido hoje na carteira desta conta: 2 usinas com peça,
**4 fechamentos publicados com zero arquivos**, 1 usina sem fechamento nenhum e 1 sem
monitoramento. São situações diferentes que hoje chegam à tela como a mesma frase muda
("Sem arquivo anexado"), e o dono lê todas como "o aplicativo não baixou".

### O relatório mensal de manutenção é OFERTA, nunca cor

A célula do ano ganhou `manutencao.mensais`: quais relatórios mensais **liberados** existem
naquele mês, para a folha oferecer o toque. Ele **não pinta nada**. A cor sai de
`situacao`/`previsto`/`cumprido` — que respondem *"foi feito?"*, conformidade — e o PDF
responde *"há papel sobre isso?"*, que é outra pergunta. Se a existência do documento
mexesse na cor, a grade responderia duas perguntas com uma cor só; e como hoje **zero**
relatórios estão liberados (medido em 06/09/2026 nas 22 usinas visíveis), a grade inteira
ficaria em travessão. `test_a_marca_da_celula_nao_depende_do_documento` é o cadeado.

Um relatório liberado num mês **fora do contrato** — o que acontece assim que a vigência
vira e o `meses_estado` passa a cobrir outra janela — não pode sumir da grade. Nesse caso a
célula ganha um bloco de manutenção que traz **só** o documento: `situacao`, `previsto` e
`cumprido` continuam ausentes, então nenhuma conta nasce e nenhuma cor muda.

### Nada de PDF aqui

Esta rota diz **onde há** documento e **que janela** o relatório de manutenção cobriria.
Os bytes continuam saindo por `/documents/{id}/file`, por `/manutencao/relatorio/pdf` e
pela rota do relatório mensal, onde a autorização é refeita.
"""

import asyncio
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.documents import (
    ORDEM_DO_TIPO,
    DocumentoOut,
    DocumentosOut,
    RelatorioMensalOut,
    # A leitura do `If-None-Match` é REUSADA, e não recopiada: o cabeçalho é uma lista e
    # pode vir com o prefixo fraco `W/`. Duas implementações da mesma comparação dariam
    # duas rotas com comportamentos de revalidação diferentes — e a que estivesse errada
    # falharia em silêncio (a tela continua certa, só a rede continua cara).
    _cliente_ja_tem,
    # A GERAÇÃO sozinha: esta rota pede o acervo mensal por conta própria, com o semáforo
    # dela. Chamar a rota inteira faria a mesma família ser buscada duas vezes no mesmo
    # pedido — catorze idas ao meuPlano onde bastam sete.
    documentos_de_geracao,
    # O fan-out do mensal é FONTE ÚNICA, compartilhada com `/documents`: duas cópias
    # poderiam divergir sobre quais relatórios existem, e a aba de Relatórios e a grade do
    # ano dariam duas respostas para a mesma pergunta.
    mensais_das_usinas,
)
from app.api.v1.manutencao import CronogramaOut, cronograma_da_usina
from app.api.v1.plants import usinas_do_usuario
from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User

router = APIRouter(prefix="/api/v1/relatorios", tags=["app · relatórios"])


#: Quantas usinas o cronograma consulta ao mesmo tempo. A Visão geral já custou 22 s por
#: abrir ~64 chamadas de uma vez; sete usinas cabem folgadas em seis vagas e o upstream
#: não vê uma rajada. O semáforo nasce POR PEDIDO de propósito: um objeto de módulo
#: atravessaria laços de eventos diferentes (o de cada teste, entre outros).
LARGURA = 6

#: O ano mais antigo que a grade aceita. Não é regra de negócio, é cerca contra `ano=1`
#: virar 12 rótulos sem sentido.
ANO_MINIMO = 2000


# ── formato ─────────────────────────────────────────────────────────────────


class PecaOut(BaseModel):
    """Uma peça do fechamento do mês, do jeito que a célula precisa para oferecer o toque."""

    #: `geracao` · `paradas` · `resumo`. É o `tipo` que `/documents/{id}/file` aceita.
    tipo: str
    nome: str
    #: O peso declarado pelo monitoramento. **Nulo é ausência e a tela mostra travessão** —
    #: nunca `0`, que afirmaria arquivo vazio. Medido: de 43.238 B (Resumo Executivo de
    #: Pereiras) a 2.686.172 B (Relatório de Geração de Porto Ferreira), sessenta vezes de
    #: diferença; quem está no 3G precisa saber em qual dos dois vai tocar.
    bytes: int | None = None


class EnergiaCelulaOut(BaseModel):
    """A geração daquele mês naquela usina — e, quando não há, QUAL ausência é.

    O acervo de geração é **publicado**: ele existe porque alguém do monitoramento o
    publicou. Vazio aqui quer dizer "ninguém publicou", nunca "não houve energia".
    """

    #: * `publicado` — há fechamento e ele tem ao menos uma peça para abrir.
    #: * `fechamento_sem_arquivo` — o fechamento existe e está sem peça nenhuma. É o caso
    #:   dos quatro fechamentos de maio medidos hoje, e é diferente de não haver
    #:   fechamento: alguém fechou o mês e o arquivo não subiu (ou foi retirado).
    #: * `sem_fechamento` — o mês não foi fechado. A única das cinco que é ausência de dado.
    #: * `sem_monitoramento` — a usina não está ligada ao meuWatt; não há de onde vir.
    #: * `indisponivel` — a ponte com o monitoramento não respondeu NESTE pedido. Achatar
    #:   isto em `sem_fechamento` afirmaria que ninguém publicou, que é o contrário de
    #:   "não sabemos"; o motivo viaja no `aviso` do topo.
    estado: str
    #: O id que `/documents/{id}/file` aceita. Nulo em tudo que não seja fechamento.
    documento_id: int | None = None
    #: Quando o fechamento foi enviado ao cliente. **Não** é o mês da célula — o mês vem
    #: de `competencia` (que sai de `de`), e os fechamentos 35 e 36 medidos hoje cobrem
    #: agosto e foram publicados em 05/09: agrupar pela publicação poria agosto em setembro.
    publicado_em: str | None = None
    pecas: list[PecaOut] = []


class MensalNaCelulaOut(BaseModel):
    """Um relatório mensal liberado, na medida da célula: o que abrir, e qual dos dois é.

    Só o par que a folha precisa para oferecer o toque. O resto do cartão — a usina, a
    competência, a data de publicação — já viaja completo em `/documents.mensais`, e
    repeti-lo aqui daria duas cópias da mesma verdade dentro do mesmo pedido.
    """

    #: `executivo` (o resumo da diretoria) ou `tecnico` (o laudo). Cru, como veio.
    tipo: str
    #: O id do relatório **no meuPlano** — o mesmo `RelatorioMensalOut.id`, e o que a rota
    #: do PDF mensal aceita. **Não** é o id do vínculo.
    relatorio_id: int


class ManutencaoCelulaOut(BaseModel):
    """O mês do contrato, como o meuPlano o classificou. Repassado, nunca recalculado."""

    #: `fechado` (venceu dentro da vigência: entra na cobrança) · `corrente` (o mês em
    #: curso) · `futuro` (não se cobra o que não venceu). Situação fora deste vocabulário
    #: viaja crua — engoli-la deixaria a coluna sem estado sem ninguém saber por quê.
    situacao: str | None = None
    #: Σ de X previstos no mês e quantos foram cumpridos, do `meses_estado`. Nulo é "o
    #: meuPlano não disse"; **zero é resposta** ("nada previsto neste mês").
    previsto: int | None = None
    cumprido: int | None = None
    #: Os relatórios mensais LIBERADOS daquele mês, **executivo primeiro** — a mesma ordem
    #: do portal, porque a diretoria é o destino declarado do executivo e duas ordens
    #: dariam duas respostas para a mesma pergunta.
    #:
    #: ⚠ **Não entra na cor da célula.** Ver o cabeçalho do módulo: a marca responde "foi
    #: feito?" e sai dos três campos acima; isto responde "há papel sobre isso?".
    mensais: list[MensalNaCelulaOut] = []


class CelulaOut(BaseModel):
    """Um mês do ano civil, para uma usina."""

    mes: str  # "YYYY-MM"
    energia: EnergiaCelulaOut
    #: Nulo quando o mês **não pertence ao contrato** e não há relatório mensal liberado
    #: nele. Medido: o contrato de Porto Ferreira vai de 2026-08 a 2027-07 — de janeiro a
    #: julho de 2026 não há nada combinado, e um bloco de zeros ali se leria como "estava
    #: previsto e não foi feito".
    #:
    #: A exceção é o mês fora do contrato que TEM documento liberado (acontece assim que a
    #: vigência vira e o `meses_estado` passa a cobrir outra janela): aí o bloco existe
    #: trazendo **só** `mensais`, com `situacao`/`previsto`/`cumprido` ausentes. Sem isso o
    #: relatório que a equipe entregou sumiria da grade do ano em que ele foi entregue.
    manutencao: ManutencaoCelulaOut | None = None


class AnualEnergiaOut(BaseModel):
    """O fechamento do ANO no monitoramento — que hoje não existe, e a célula diz isso.

    A aba Anual do meuWatt cria a linha, mas o gerador de PDF de lá só roda para MENSAL:
    um relatório ANUAL nasce sem arquivo nenhum, e em produção há **zero linhas ANUAL**.
    Existe o continente, não o conteúdo — e um botão morto seria pior que a frase.
    """

    disponivel: bool = False
    #: Por que não há o que abrir. Preenchido sempre que `disponivel` é falso.
    motivo: str | None = None
    #: Os mesmos cinco nomes de `EnergiaCelulaOut.estado`, quando há uma linha ANUAL.
    estado: str | None = None
    documento_id: int | None = None
    pecas: list[PecaOut] = []


class AnualManutencaoOut(BaseModel):
    """A janela que `/manutencao/relatorio` cobriria para o ano — impressa, não implícita.

    **`ate` nunca é um mês futuro.** Medido: pedir `2026-01..2026-12` hoje responde
    **400 "ate não pode ser um mês futuro."**. Enquanto o ano corre, "o ano" é
    `janeiro..mês corrente`, e a tela imprime a janela ao lado do número — foi a falta
    desse recorte que produziu "13 de 270" numa tela e "41,9 %" na outra.
    """

    disponivel: bool = False
    motivo: str | None = None
    #: `YYYY-MM`. Os dois nulos quando `disponivel` é falso.
    de: str | None = None
    ate: str | None = None


class AnualOut(BaseModel):
    energia: AnualEnergiaOut = AnualEnergiaOut()
    manutencao: AnualManutencaoOut = AnualManutencaoOut()


class UsinaAnoOut(BaseModel):
    """Uma linha da grade: os 12 meses de uma usina, mais o fecho do ano."""

    id: int
    nome: str
    #: A usina está ligada ao monitoramento (de onde vem a geração publicada)?
    tem_monitoramento: bool = False
    #: A usina tem manutenção contratada (de onde vem o cronograma)?
    tem_manutencao: bool = False

    contrato: str | None = None
    contrato_id: int | None = None
    #: `CONSOLIDATED` ou nulo. Nulo = a equipe ainda não publicou o cronograma — é o caso
    #: de 5 das 6 usinas com manutenção medidas hoje, e é normal no início do contrato.
    cronograma_status: str | None = None
    cronograma_versao: int | None = None

    # ── o recorte de vigência, calculado NO meuPlano e só repassado ─────────────
    #
    # Cinco leituras, nenhuma soma. Ver o cabeçalho do módulo: a conta tem UM dono.
    #: Até que mês a conta olha (`YYYY-MM`). Percentual sem a janela é meia frase.
    mes_referencia: str | None = None
    #: O denominador honesto — o previsto nos meses que JÁ venceram dentro da vigência.
    #: Vai à tela ao lado do percentual ("13/31"). Medido em Porto Ferreira: 31.
    previsto_ate_hoje: int | None = None
    cumprido_ate_hoje: int | None = None
    #: 0–100, como o meuPlano calculou.
    pct_ate_hoje: float | None = None
    #: Σ de X dos 12 meses do contrato — o "270" da aba Cronograma. Viaja junto para as
    #: duas telas exibirem o MESMO número e explicarem a diferença para o "31" do recorte.
    previsto_no_contrato: int | None = None

    #: 12 células, de janeiro a dezembro do ano pedido, sempre nesta ordem.
    meses: list[CelulaOut] = []
    anual: AnualOut = AnualOut()
    #: O que falhou na MANUTENÇÃO desta usina. A queda de uma não pode apagar as outras seis.
    #:
    #: O nome diz a FAMÍLIA porque a tela tem duas abas (energia e manutenção) e este
    #: motivo só vale para uma delas. Antes o campo se chamava `aviso` e trazia a família
    #: escrita no texto ("Manutenção: ..."); o aplicativo arrancava o prefixo com uma
    #: expressão regular e mostrava a frase nas DUAS abas — o dono lia "a equipe ainda não
    #: publicou o cronograma" enquanto olhava a coluna de geração. Motivo de uma família
    #: não pode viajar num campo que não diz de qual família ele é; quando existir um
    #: motivo de energia por usina, ele nasce como `aviso_energia` e ninguém precisa
    #: reinterpretar prosa para separá-los.
    aviso_manutencao: str | None = None
    #: O que falhou no acervo de RELATÓRIOS MENSAIS desta usina — a terceira família, e o
    #: campo próprio que a nota acima previu. `aviso_manutencao` fala do cronograma (a
    #: conformidade); este fala do documento. Um relatório mensal que não veio não diz nada
    #: sobre a manutenção ter sido feita, e vice-versa.
    #:
    #: Nulo é o normal, inclusive quando não há nada liberado: **ausência de documento não
    #: é falha**, e é o estado medido hoje em toda a base.
    aviso_mensais: str | None = None


class RelatoriosAnoOut(BaseModel):
    ano: int
    #: Os 12 rótulos `YYYY-MM` do ano civil, na ordem das colunas.
    meses: list[str] = []
    usinas: list[UsinaAnoOut] = []
    #: O que falhou para TODA a carteira — hoje, só a ponte da geração, que é uma ida só
    #: para todas as usinas. Falha de manutenção é por usina e mora em
    #: `UsinaAnoOut.aviso_manutencao`.
    aviso: str | None = None


# ── leitura ─────────────────────────────────────────────────────────────────


def _competencia_de_hoje() -> str:
    """O mês corrente **na usina**, `YYYY-MM`.

    O relógio é o de `app.core.datas` — o mesmo de `periodo_pedido`, que é quem recusa mês
    futuro lá no relatório. Com `date.today()` o contêiner (UTC) viraria o mês três horas
    antes do Brasil e a janela do ano pediria um mês que o meuPlano recusaria com 400.
    """
    return hoje_na_usina().strftime("%Y-%m")


def _falha(resultado: Any) -> str | None:
    """A frase de uma exceção apanhada pelo `gather`, ou `None` quando o bloco respondeu."""
    if isinstance(resultado, HTTPException):
        return str(resultado.detail)
    if isinstance(resultado, BaseException):
        return str(resultado) or resultado.__class__.__name__
    return None


def _pecas(documento: DocumentoOut) -> list[PecaOut]:
    return [PecaOut(tipo=a.tipo, nome=a.nome, bytes=a.bytes) for a in documento.arquivos]


def _celula_de_energia(
    documento: DocumentoOut | None, *, monitorada: bool, indisponivel: bool
) -> EnergiaCelulaOut:
    """Qual das cinco ausências é esta — nomeada, nunca achatada numa frase só."""
    if documento is not None:
        pecas = _pecas(documento)
        return EnergiaCelulaOut(
            estado="publicado" if pecas else "fechamento_sem_arquivo",
            documento_id=documento.id,
            publicado_em=documento.publicado_em.isoformat(),
            pecas=pecas,
        )
    if not monitorada:
        return EnergiaCelulaOut(estado="sem_monitoramento")
    # "Não sabemos" e "ninguém publicou" são coisas diferentes, e só a segunda é ausência.
    if indisponivel:
        return EnergiaCelulaOut(estado="indisponivel")
    return EnergiaCelulaOut(estado="sem_fechamento")


def _anual_de_energia(
    documento: DocumentoOut | None, *, monitorada: bool, indisponivel: bool
) -> AnualEnergiaOut:
    if not monitorada:
        return AnualEnergiaOut(
            estado="sem_monitoramento",
            motivo="Esta usina não está ligada ao monitoramento, de onde vêm os relatórios.",
        )
    if indisponivel:
        return AnualEnergiaOut(
            estado="indisponivel",
            motivo="Não deu para falar com o monitoramento agora.",
        )
    if documento is None:
        return AnualEnergiaOut(
            estado="sem_fechamento",
            motivo="O monitoramento ainda não publica fechamento anual.",
        )
    pecas = _pecas(documento)
    return AnualEnergiaOut(
        disponivel=bool(pecas),
        estado="publicado" if pecas else "fechamento_sem_arquivo",
        motivo=None if pecas else "O fechamento do ano existe, mas está sem arquivo anexado.",
        documento_id=documento.id,
        pecas=pecas,
    )


def _anual_de_manutencao(link: PlantLink, ano: int, mes_corrente: str) -> AnualManutencaoOut:
    """A janela do ano para `/manutencao/relatorio` — travada em hoje, e escrita.

    Não há chamada nenhuma aqui: esta rota **diz** que janela o relatório cobriria, e é a
    tela que a pede quando o cliente toca. Montar `ate=YYYY-12` num ano em curso seria um
    400 garantido no primeiro toque.
    """
    if not link.mp_usina_id:
        return AnualManutencaoOut(motivo="Esta usina não tem manutenção contratada.")
    inicio = f"{ano}-01"
    if inicio > mes_corrente:
        return AnualManutencaoOut(motivo="Este ano ainda não começou.")
    fim = min(f"{ano}-12", mes_corrente)
    return AnualManutencaoOut(disponivel=True, de=inicio, ate=fim)


async def _cronograma(
    link: PlantLink, db: Session, usuario: User, vagas: asyncio.Semaphore
) -> CronogramaOut | BaseException:
    """O cronograma de UMA usina, com a falha dela virando valor em vez de exceção.

    O `return_exceptions` do `gather` de cima já faria isto; apanhar aqui dentro mantém a
    forma da lista alinhada com `com_manutencao` mesmo que o semáforo mude de dono.
    """
    async with vagas:
        try:
            return await cronograma_da_usina(usina_id=link.id, db=db, usuario=usuario)
        except BaseException as exc:  # noqa: BLE001 — a queda de uma não derruba as outras
            return exc


def _mensais_por_mes(
    relatorios: list[RelatorioMensalOut],
) -> dict[str, list[MensalNaCelulaOut]]:
    """Os relatórios liberados agrupados pelo mês que fecham, executivo antes do técnico.

    A competência vem PRONTA do meuPlano (`YYYY-MM`) — aqui ninguém a deriva de data
    nenhuma. Competência fora dos doze rótulos do ano simplesmente não encontra célula, e
    isso é correto: ela pertence a outro ano da grade.
    """
    por_mes: dict[str, list[MensalNaCelulaOut]] = {}
    for r in relatorios:
        por_mes.setdefault(r.competencia, []).append(
            MensalNaCelulaOut(tipo=r.tipo, relatorio_id=r.id)
        )
    for lista in por_mes.values():
        # Ordem total: o tipo manda, o id desempata. A etiqueta da resposta é o sha256 do
        # corpo — uma ordem instável faria o `ETag` mudar sem nada ter mudado, e a
        # revalidação nunca daria 304 sem ninguém perceber (a tela continua certa).
        lista.sort(key=lambda m: (ORDEM_DO_TIPO.get(m.tipo, len(ORDEM_DO_TIPO)), m.relatorio_id))
    return por_mes


def _linha(
    link: PlantLink,
    *,
    ano: int,
    meses: list[str],
    docs_por_mes: dict[str, DocumentoOut],
    doc_anual: DocumentoOut | None,
    cronograma: CronogramaOut | BaseException | None,
    mensais: list[RelatorioMensalOut] | None,
    falha_mensais: str | None,
    energia_indisponivel: bool,
    mes_corrente: str,
) -> UsinaAnoOut:
    monitorada = bool(link.mw_plant_slug)
    linha = UsinaAnoOut(
        id=link.id,
        nome=link.nome,
        tem_monitoramento=monitorada,
        tem_manutencao=bool(link.mp_usina_id),
    )
    motivos: list[str] = []

    por_mes: dict[str, ManutencaoCelulaOut] = {}
    if cronograma is not None:
        if (falha := _falha(cronograma)) is not None:
            motivos.append(falha)
        elif isinstance(cronograma, CronogramaOut):
            linha.contrato = cronograma.contrato
            linha.contrato_id = cronograma.contrato_id
            linha.cronograma_status = cronograma.status
            linha.cronograma_versao = cronograma.versao
            # Cinco cópias. Nenhuma conta: ver o cabeçalho do módulo.
            linha.mes_referencia = cronograma.mes_referencia
            linha.previsto_ate_hoje = cronograma.previsto_ate_hoje
            linha.cumprido_ate_hoje = cronograma.cumprido_ate_hoje
            linha.pct_ate_hoje = cronograma.pct_ate_hoje
            linha.previsto_no_contrato = cronograma.previsto_no_contrato
            por_mes = {
                m.mes: ManutencaoCelulaOut(
                    situacao=m.situacao, previsto=m.previsto, cumprido=m.cumprido
                )
                for m in cronograma.meses_estado
            }
            if cronograma.aviso:
                motivos.append(cronograma.aviso)

    # A falha do acervo mensal ganha campo PRÓPRIO — não entra em `aviso_manutencao`. As
    # duas coisas são de famílias diferentes: uma responde "a equipe publicou o cronograma?"
    # (conformidade) e a outra "o documento do mês está disponível?" (papel). Juntá-las
    # repetiria o defeito que este módulo já pagou uma vez: o aplicativo lendo "a equipe
    # ainda não publicou o cronograma" enquanto o que faltou foi o PDF.
    if link.mp_usina_id and mensais is None:
        linha.aviso_mensais = (
            falha_mensais or "Não deu para buscar os relatórios mensais desta usina."
        )
    mensais_por_mes = _mensais_por_mes(mensais or [])

    def _manutencao(mes: str) -> ManutencaoCelulaOut | None:
        celula = por_mes.get(mes)
        do_mes = mensais_por_mes.get(mes)
        if celula is None:
            # Mês fora do contrato: só nasce bloco se houver documento liberado nele, e
            # ainda assim SEM situação/previsto/cumprido — nenhuma conta, nenhuma cor.
            return ManutencaoCelulaOut(mensais=do_mes) if do_mes else None
        if do_mes:
            celula.mensais = do_mes
        return celula

    linha.meses = [
        CelulaOut(
            mes=mes,
            energia=_celula_de_energia(
                docs_por_mes.get(mes),
                monitorada=monitorada,
                indisponivel=energia_indisponivel,
            ),
            # Ausente = mês fora do contrato e sem documento. Ver `CelulaOut.manutencao`.
            manutencao=_manutencao(mes),
        )
        for mes in meses
    ]
    linha.anual = AnualOut(
        energia=_anual_de_energia(
            doc_anual, monitorada=monitorada, indisponivel=energia_indisponivel
        ),
        manutencao=_anual_de_manutencao(link, ano, mes_corrente),
    )
    linha.aviso_manutencao = " · ".join(motivos) or None
    return linha


def _etag_de(saida: RelatoriosAnoOut) -> str:
    """A impressão digital do CORPO — a mesma régua de `/documents`, sobre outro modelo.

    Do corpo inteiro, e não de uma data: assim ela cobre tudo o que o cliente vê (uma peça
    mudou de peso? um mês virou `fechado`? o contrato foi renomeado?) sem que ninguém
    precise lembrar de listar os campos que entram na conta.

    `exclude_none` porque é assim que o corpo sai pela porta (ver `response_model_
    exclude_none` na rota): uma impressão digital de um texto que ninguém recebe seria
    tecnicamente estável e semanticamente errada no dia em que as duas formas divergissem.
    """
    corpo = saida.model_dump_json(exclude_none=True).encode("utf-8")
    return '"' + hashlib.sha256(corpo).hexdigest() + '"'


# ── a rota ──────────────────────────────────────────────────────────────────


@router.get("/ano", response_model=RelatoriosAnoOut, response_model_exclude_none=True)
async def grade_do_ano(
    ano: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
    # Injetados pelo FastAPI quando isto é uma ROTA; ficam `None` quando a função é
    # chamada por dentro. É o mesmo arranjo de `meus_documentos`.
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    """A grade `usina × mês` do ano, com o fecho anual de cada usina.

    Uma ida à rede para a tela inteira. `ano` ausente = o ano corrente **na usina**.

    O que sai daqui é ONDE há relatório e QUE janela ele cobre — os bytes continuam saindo
    por `/documents/{id}/file` e `/manutencao/relatorio/pdf`, que refazem a autorização.

    **`ETag` + `If-None-Match`.** O acervo desta conta tem seis documentos e quatro deles
    são de junho; um cronograma consolidado muda quando alguém executa uma atividade. A
    revisita de quem está entre duas usinas passa a custar 304 e zero byte de corpo, em
    vez de baixar a grade inteira de novo ou mostrar o retrato velho sem poder perguntar
    "mudou?".

    **`response_model_exclude_none`** não é enfeite: a grade é 84 células e a maioria
    delas é ausência. Medido contra a carteira real (7 usinas, ano de 2026): **15.724 B
    com os nulos escritos, 9.863 B sem** — 37 % do corpo eram as palavras `null` numa tela
    que o dono abre no carro. Nada se perde: campo ausente e campo nulo se leem igual do
    outro lado (`?? '—'`), e o que é ZERO — `previsto: 0`, `disponivel: false` — continua
    saindo, porque zero é resposta e não ausência.
    """
    corrente = _competencia_de_hoje()
    ano_corrente = int(corrente[:4])
    if ano is None:
        ano = ano_corrente
    # A cerca é contra `ano=1` virar rótulos sem sentido, não regra de negócio. O ano
    # seguinte é aceito de propósito: perguntar pelo ano que vem é legítimo, e a resposta
    # honesta é "nada publicado ainda" — não um erro.
    if ano < ANO_MINIMO or ano > ano_corrente + 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Ano fora do alcance: use de {ANO_MINIMO} a {ano_corrente + 1}.",
        )

    links = usinas_do_usuario(db, usuario)
    meses = [f"{ano}-{m:02d}" for m in range(1, 13)]
    saida = RelatoriosAnoOut(ano=ano, meses=meses)

    # UMA ida para a geração da carteira inteira; uma por usina para a manutenção, com
    # semáforo. As duas famílias em paralelo e cada uma falhando por conta própria: a
    # queda do monitoramento não pode apagar o cronograma, que é o caso que acontece
    # primeiro (medido: 4 fechamentos sem arquivo e 1 cronograma consolidado).
    #
    # O acervo mensal entra na MESMA rajada e divide as MESMAS vagas do cronograma: os dois
    # batem no meuPlano, e dois semáforos de seis dariam doze conexões simultâneas ao mesmo
    # upstream — exatamente a rajada que este semáforo existe para evitar. É uma ida a mais
    # por usina, e a lista completa de cada usina de uma vez: o filtro `?competencia=` é
    # opcional lá, então não são doze idas por usina para montar doze colunas.
    vagas = asyncio.Semaphore(LARGURA)
    com_manutencao = [l for l in links if l.mp_usina_id]
    documentos, mensais, *cronogramas = await asyncio.gather(
        documentos_de_geracao(None, db, usuario),
        mensais_das_usinas(db, links, vagas=vagas),
        *(_cronograma(l, db, usuario, vagas) for l in com_manutencao),
        return_exceptions=True,
    )

    # `mensais_das_usinas` já apanha o que é dela e devolve aviso; o `isinstance` é o cinto
    # contra a surpresa — sem ele, uma exceção inesperada viraria `tuple` inexistente e
    # derrubaria a grade inteira por causa de uma família secundária.
    if isinstance(mensais, tuple):
        mensais_por_usina, falha_mensais = mensais
    else:
        mensais_por_usina, falha_mensais = {}, _falha(mensais) or None
        if falha_mensais:
            falha_mensais = f"Relatórios mensais indisponíveis: {falha_mensais}"

    energia_indisponivel = False
    docs: list[DocumentoOut] = []
    if (falha := _falha(documentos)) is not None:
        saida.aviso = f"Relatórios de geração indisponíveis: {falha}"
        energia_indisponivel = True
    elif isinstance(documentos, DocumentosOut):
        docs = documentos.documentos
        if documentos.aviso:
            saida.aviso = documentos.aviso
            # Sem uma única usina ligada ao monitoramento, "ninguém publicou" é a verdade e
            # cada célula já dirá `sem_monitoramento` por conta própria; com usina ligada,
            # o aviso é falha da ponte e as células não podem afirmar que ninguém publicou.
            energia_indisponivel = any(l.mw_plant_slug for l in links)
    else:  # pragma: no cover — só se `documentos_de_geracao` mudar de forma
        saida.aviso = "O monitoramento não devolveu relatórios."
        energia_indisponivel = True

    # O mês do documento é `competencia`, que sai de `de` e mora no servidor
    # (`DocumentoOut.competencia`). O ANUAL não tem competência — ele responde por `ano`.
    do_ano = set(meses)
    por_usina_mes: dict[tuple[int | None, str], DocumentoOut] = {}
    anual_por_usina: dict[int | None, DocumentoOut] = {}
    for d in docs:
        if d.competencia in do_ano:
            # Mais de um fechamento no mesmo mês: fica o publicado por último, que é a
            # ordem em que `documentos_de_geracao` já entrega a lista.
            por_usina_mes.setdefault((d.plant_id, d.competencia), d)
        elif d.ano == ano:
            anual_por_usina.setdefault(d.plant_id, d)

    por_id = dict(zip((l.id for l in com_manutencao), cronogramas, strict=True))
    saida.usinas = [
        _linha(
            l,
            ano=ano,
            meses=meses,
            docs_por_mes={
                m: d for m in meses if (d := por_usina_mes.get((l.id, m))) is not None
            },
            doc_anual=anual_por_usina.get(l.id),
            cronograma=por_id.get(l.id),
            # Ausente do mapa = a usina não respondeu. Lista vazia = respondeu e não há
            # nada liberado, que é o estado normal de hoje. As duas coisas são diferentes
            # e a linha diz qual é.
            mensais=mensais_por_usina.get(l.id),
            falha_mensais=falha_mensais,
            energia_indisponivel=energia_indisponivel,
            mes_corrente=corrente,
        )
        for l in links
    ]

    etag = _etag_de(saida)
    if response is not None:
        response.headers["ETag"] = etag
    if request is not None and _cliente_ja_tem(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return saida
