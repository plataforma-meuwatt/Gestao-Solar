"""Relatórios publicados para o dono da usina — DUAS famílias, na mesma ida.

A primeira é a **geração**, e vem do Portal do Cliente do meuWatt (`/reports/portal`). Ele
tem uma característica que **obriga** a filtrar aqui: quando quem chama é administrador,
devolve as usinas todas — é a pré-visualização que o gestor usa. O BFF chama com um token
pessoal que costuma ser de administrador, então repassar a resposta crua entregaria a este
cliente os relatórios de todos os outros.

Por isso nada sai daqui sem passar por `usinas_do_usuario`: o corte é feito por
`mw_plant_slug`, contra o que o gestor concedeu a esta conta. É o mesmo princípio das
outras rotas — a autorização é do BFF, nunca do upstream.

A segunda é o **relatório mensal de MANUTENÇÃO**, que o meuPlano passou a liberar
(`visao-cliente/usinas/{id}/relatorios-mensais`). Ela entra aqui por ADIÇÃO — `documentos`
não muda um byte — porque a aba de Relatórios do aplicativo lê **uma** fonte
(`fetchWithCache('documents')`) e a carteira desta conta tem sete usinas: pedir o mensal do
celular seria sete conexões e a quebra da chave de cache única. A lição já foi paga em
`relatorios_ano.py` ("9 chamadas, 3.511 ms para extrair um número por mês"). **A composição
é do servidor.**

### O corte do mensal não mora aqui, e é de propósito

O meuPlano só deixa atravessar a porta `visao-cliente` o que foi **liberado** — e o degrau
chamado "aprovado" *não* é liberado, é conversa interna. Este módulo **não conhece outra
porta**: ele chama `vc_relatorios_mensais` e mais nada. Reimplementar a régua aqui criaria
uma segunda resposta para "este documento pode ser mostrado?", e a errada seria a que
entrega ao cliente um relatório que ninguém liberou.

### As duas famílias falham separado, e cada motivo diz de quem é

`aviso` continua sendo o da geração e `aviso_mensais` nasce ao lado — nunca um campo só com
a família escrita na prosa. Foi exatamente esse atalho que fez o aplicativo arrancar o
prefixo "Manutenção:" com expressão regular e mostrar a frase nas duas abas (ver
`UsinaAnoOut.aviso_manutencao`). Motivo de uma família não viaja num campo que não diz de
qual família ele é.
"""

import asyncio
import hashlib
from datetime import date, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, computed_field
from sqlalchemy.orm import Session

from app.api.v1.plants import usinas_do_usuario
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import vinculos

router = APIRouter(prefix="/api/v1", tags=["app · documentos"])

#: Quantas usinas o mensal consulta ao mesmo tempo. Mesma cerca de `relatorios_ano.LARGURA`:
#: a Visão geral já custou 22 s por abrir ~64 chamadas de uma vez. O semáforo nasce POR
#: PEDIDO — um objeto de módulo atravessaria laços de eventos diferentes (o de cada teste,
#: entre outros) —, e quem já tem um semáforo aberto para o meuPlano passa o seu, para as
#: duas famílias dividirem as mesmas vagas em vez de somarem rajadas.
LARGURA = 6

#: A ordem dos dois documentos do mês, **igual no portal e no aplicativo**. O executivo vem
#: primeiro porque a diretoria é o destino que o próprio meuPlano declara para ele ("nível
#: gestor que tem cinco minutos"); o técnico é o laudo, e vem logo abaixo. Uma ordem por
#: frente daria duas respostas para a mesma pergunta. Tipo desconhecido vai para o fim —
#: cru, nunca engolido: o dia em que o meuPlano criar um terceiro, ele aparece.
ORDEM_DO_TIPO = {"executivo": 0, "tecnico": 1}


def _inteiro(valor: Any) -> int | None:
    """Número inteiro do upstream, ou nada.

    Ausência é `None`, **jamais** `0`: zero é uma resposta ("arquivo vazio") e a tela a
    desenharia como tal. Nulo é o travessão. `bool` sai fora antes de tudo porque em
    Python `True` vira `1` sem reclamar.
    """
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _texto(valor: Any) -> str | None:
    """Texto do upstream, ou nada. Vazio é ausência — e ausência é travessão na tela."""
    if not isinstance(valor, str):
        return None
    limpo = valor.strip()
    return limpo or None


class ArquivoOut(BaseModel):
    #: `geracao` (Relatório de Geração), `paradas` (Anexo de Paradas) ou `resumo`
    #: (Resumo Executivo). Um fechamento pode ter qualquer subconjunto delas: o Resumo só
    #: existe quando o mês teve a análise concluída, e peça ausente é estado normal.
    tipo: str
    nome: str
    #: O peso do PDF, como o monitoramento o declara (`files[].size_bytes`), e conferido
    #: contra o `Content-Length` do download: as três peças medidas hoje batem exatamente.
    #:
    #: Existe porque a diferença é de SESSENTA VEZES — o Resumo Executivo de Pereiras tem
    #: 43.238 B e o Relatório de Geração de Porto Ferreira tem 2.686.172 B. Sem isto quem
    #: está no 3G entre duas usinas toca no PDF sem saber se são dois segundos ou dois
    #: minutos. O campo já era mandado pelo upstream e jogado fora aqui.
    #:
    #: Nulo é ausência, e a tela mostra travessão — nunca `0`, que afirmaria arquivo vazio.
    bytes: int | None = None


class DocumentoOut(BaseModel):
    id: int
    nome: str
    usina: str
    #: `id` do vínculo neste sistema — o portal do cliente é por usina, e sem isto a tela de
    #: Relatórios não saberia de qual usina é cada fechamento sem comparar nomes.
    plant_id: int | None = None
    #: `DIÁRIO` · `SEMANAL` · `MENSAL` · `ANUAL` — o vocabulário é do meuWatt.
    periodo: str
    de: date
    ate: date
    publicado_em: datetime
    arquivos: list[ArquivoOut] = []

    #: ────────────────────────────────────────────────────────────────────────────────
    #: O EIXO DO TEMPO: a régua mora aqui, e é derivada — não há como divergir de `de`.
    #:
    #: `publicado_em` é a data do ENVIO, e a lista vem ordenada por ela. Medido hoje: os
    #: fechamentos 35 (Porto Ferreira) e 36 (Pereiras) cobrem **agosto** e foram publicados
    #: em **05/09**. Uma tela que agrupasse pelo campo com que a lista vem ordenada poria o
    #: fechamento de agosto na gaveta de setembro — e o cliente não encontraria o relatório
    #: do mês que ele foi procurar. O mês é o do PERÍODO COBERTO, e ele sai de `de`.
    #:
    #: São `@computed_field` de propósito: ninguém consegue construir um `DocumentoOut`
    #: cuja competência discorde do seu `de`. É a mesma régua, escrita uma vez, no servidor
    #: — e não a mesma pergunta respondida duas vezes por dois lados.
    #: ────────────────────────────────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def competencia(self) -> str | None:
        """O mês coberto, `YYYY-MM`, para o que tem mês. Nulo no ANUAL.

        O ANUAL cobre doze meses: dar-lhe uma competência o trancaria na gaveta de
        janeiro e o esconderia dos outros onze. Ele responde por `ano`.

        Um `SEMANAL` de 29/jun a 5/jul pertence a dois meses e cai em **junho** — a
        âncora é sempre o começo do período coberto, nunca o fim.
        """
        if self.periodo.strip().upper() == "ANUAL":
            return None
        return self.de.strftime("%Y-%m")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ano(self) -> int | None:
        """O ano coberto, só para o ANUAL. Nulo no resto.

        Exatamente um dos dois campos é preenchido, sempre: `competencia` diz "este é um
        documento de mês", `ano` diz "este é o documento do ano". A tela do ano não precisa
        adivinhar a espécie a partir do rótulo de `periodo`.
        """
        if self.periodo.strip().upper() != "ANUAL":
            return None
        return self.de.year


class RelatorioMensalOut(BaseModel):
    """Um relatório mensal de MANUTENÇÃO já liberado ao cliente.

    Não é uma peça de fechamento de geração e não se mistura com `DocumentoOut`: são dois
    acervos, de dois sistemas, com dois ciclos de publicação. O que eles têm em comum é a
    competência, e é por ela que a tela os põe lado a lado.
    """

    #: O id do relatório **no meuPlano** — é o que `/relatorios-mensais/{id}/pdf` aceita.
    id: int
    #: O id do vínculo **neste sistema**, o mesmo de `DocumentoOut.plant_id` e o mesmo que
    #: as rotas de manutenção aceitam em `?usina_id=`. **Não** é o `usina_id` do meuPlano:
    #: os dois são inteiros pequenos e trocá-los abriria a usina errada sem erro nenhum.
    usina_id: int
    usina: str
    #: `YYYY-MM`, o mês que o relatório fecha. Vem pronto do meuPlano — aqui ninguém deriva
    #: competência de data nenhuma, ao contrário do fechamento de geração (que só tem `de`).
    competencia: str
    #: `executivo` (o resumo da diretoria) ou `tecnico` (o laudo). Repassado CRU: um valor
    #: novo do meuPlano tem de chegar à tela, não sumir num mapa deste lado.
    tipo: str
    #: Quando a equipe LIBEROU o documento — a única data que sai para o cliente, e a tela
    #: a rotula "publicado". `aprovado_em`, `apurado_em` e `aprovado_por` ficam de fora de
    #: propósito: o último é nome de funcionário da executora (entregaria o organograma
    #: interno e criaria endereço para cobrança pessoal), e os dois primeiros respondem
    #: "quando os números foram calculados", que não é "de quando é este documento". Três
    #: datas na mesma linha fazem o leitor não saber qual delas responde à pergunta dele.
    #:
    #: Texto ISO repassado como veio: convertê-lo aqui inventaria um fuso que o upstream
    #: não declarou. Nulo é ausência, e a tela mostra travessão.
    liberado_em: str | None = None


class DocumentosOut(BaseModel):
    documentos: list[DocumentoOut] = []
    aviso: str | None = None
    #: Os relatórios mensais de manutenção liberados, de TODAS as usinas do recorte. Lista
    #: vazia é o estado normal e honesto de hoje: medido em 06/09/2026 contra as 22 usinas
    #: visíveis, **zero** liberados — os 26 relatórios de agosto/2026 existem e estão todos
    #: em rascunho. A tela diz isso com uma frase; não desenha uma tela vazia que pareça
    #: defeito.
    mensais: list[RelatorioMensalOut] = []
    #: O que falhou na família MENSAL — e só nela. Ver o cabeçalho do módulo: `aviso` é da
    #: geração, e juntar os dois obrigaria a tela a reinterpretar prosa para separá-los.
    #:
    #: Só nasce em FALHA (uma usina que não respondeu). Usina sem manutenção contratada não
    #: é falha, é ausência de contrato — e não gera frase aqui.
    aviso_mensais: str | None = None


def _etag_de(saida: DocumentosOut) -> str:
    """A impressão digital da resposta — sha256 do JSON que sairia pela porta.

    Do CORPO, e não de uma data de publicação: assim ela cobre tudo o que o cliente vê
    (o peso de uma peça mudou? um fechamento foi despublicado? o vínculo foi renomeado?)
    sem que ninguém precise lembrar de listar os campos que entram na conta.
    """
    return '"' + hashlib.sha256(saida.model_dump_json().encode("utf-8")).hexdigest() + '"'


def _cliente_ja_tem(cabecalho: str | None, etag: str) -> bool:
    """`If-None-Match` casa com o que temos?

    O cabeçalho é uma LISTA e pode vir com o prefixo fraco `W/` (posto por proxies e por
    alguns clientes HTTP). Comparar a string crua com `==` faria a revalidação falhar em
    silêncio: nada quebraria, e o 304 simplesmente nunca aconteceria — o defeito mais
    caro de diagnosticar, porque a tela continua certa e só a rede continua cara.
    """
    if not cabecalho:
        return False
    for parte in cabecalho.split(","):
        candidato = parte.strip()
        if candidato == "*":
            return True
        if candidato.startswith("W/"):
            candidato = candidato[2:]
        if candidato == etag:
            return True
    return False


# ── os relatórios mensais de manutenção ─────────────────────────────────────


def _mensal_out(bruto: Any, link: PlantLink) -> RelatorioMensalOut | None:
    """Uma linha do meuPlano virando o que o cliente lê. `None` quando não dá para confiar.

    Item sem `id`, sem `competencia` ou sem `tipo` é descartado em silêncio — e isso é
    deliberado: os três são a identidade do documento, e um card sem eles ofereceria um
    toque que não abre nada. Nenhum campo é inventado no lugar (Regra 0).
    """
    if not isinstance(bruto, dict):
        return None
    identificador = _inteiro(bruto.get("id"))
    competencia = _texto(bruto.get("competencia"))
    tipo = _texto(bruto.get("tipo"))
    if identificador is None or competencia is None or tipo is None:
        return None
    return RelatorioMensalOut(
        id=identificador,
        # O id do VÍNCULO, não o do meuPlano: ver `RelatorioMensalOut.usina_id`.
        usina_id=link.id,
        usina=link.nome,
        competencia=competencia,
        tipo=tipo,
        liberado_em=_texto(bruto.get("liberado_em")),
    )


def ordenar_mensais(relatorios: list[RelatorioMensalOut]) -> list[RelatorioMensalOut]:
    """Competência mais recente primeiro; **dentro** do mês, executivo antes do técnico.

    São dois sentidos opostos na mesma lista, e é por isso que são duas passadas em vez de
    um `reverse=True`: aquele inverteria a chave INTEIRA e poria o técnico antes do
    executivo — a ordem que o produto decidiu que não existe. O `sort` do Python é estável,
    então a segunda passada reordena os meses preservando o que a primeira decidiu dentro
    de cada um.

    A ordenação é TOTAL de propósito (nome da usina e id desempatam): a etiqueta da
    resposta é o sha256 do corpo, e uma ordem que dependesse da chegada das respostas em
    paralelo faria o `ETag` mudar sem nada ter mudado — a revalidação nunca daria 304 e
    ninguém descobriria, porque a tela continuaria certa.
    """
    ordenados = sorted(
        relatorios,
        # A USINA vem antes do tipo: os dois documentos de um mês são UM cartão com duas
        # linhas, e ordenar por tipo primeiro os separaria — "executivo de Porto Ferreira,
        # técnico de Pereiras, técnico de Porto Ferreira" na mesma faixa do mês.
        key=lambda r: (r.usina, ORDEM_DO_TIPO.get(r.tipo, len(ORDEM_DO_TIPO)), r.id),
    )
    ordenados.sort(key=lambda r: r.competencia, reverse=True)
    return ordenados


async def _mensais_de_uma(
    cliente: Any, link: PlantLink, vagas: asyncio.Semaphore
) -> list[RelatorioMensalOut] | Exception:
    """O acervo liberado de UMA usina, com a falha dela virando valor em vez de exceção.

    `Exception`, nunca `BaseException`: capturar a base engoliria também o `CancelledError`
    que o laço usa para DESISTIR. Quem fecha a aba no meio derrubaria a própria requisição,
    mas as sete chamadas ao meuPlano seguiriam até o fim — trabalho pago por ninguém, e um
    cancelamento que não cancela. A promessa da função ("a queda de uma não derruba as
    outras") é sobre a falha da ponte, não sobre o desligamento do laço.
    """
    async with vagas:
        try:
            brutos = await cliente.vc_relatorios_mensais(link.mp_usina_id)
        except Exception as exc:  # noqa: BLE001 — a queda de uma não derruba as outras
            return exc
    if not isinstance(brutos, list):
        return []
    achados = [_mensal_out(b, link) for b in brutos]
    return [r for r in achados if r is not None]


async def mensais_das_usinas(
    db: Session,
    links: list[PlantLink],
    usuario: User,
    *,
    vagas: asyncio.Semaphore | None = None,
) -> tuple[dict[int, list[RelatorioMensalOut]], str | None]:
    """O acervo mensal liberado de cada usina, indexado pelo id do VÍNCULO.

    Uma ida por usina, em paralelo e com semáforo — em série, sete usinas seriam sete
    latências somadas numa tela que abre a frio. `vagas` existe para quem já tem um
    semáforo aberto contra o meuPlano (a grade do ano pede cronograma e mensal na mesma
    rajada) poder passar o seu, em vez de as duas famílias abrirem seis conexões cada.

    **Fonte única do fan-out**: a rota de documentos e a grade do ano chamam esta função, e
    não duas cópias — senão a lista do acervo e a oferta na célula do ano poderiam divergir
    sobre quais relatórios existem, que é a lição mais cara do projeto.

    Devolve também o aviso da família. Usina sem `mp_usina_id` simplesmente não é
    perguntada: não ter manutenção contratada é ausência de contrato, não falha.
    """
    com_manutencao = [l for l in links if l.mp_usina_id]
    if not com_manutencao:
        return {}, None

    try:
        cliente = vinculos.cliente_meuplano(db, usuario.id)
    except Exception as exc:  # noqa: BLE001
        return {}, f"Relatórios mensais indisponíveis: {exc}"

    if vagas is None:
        vagas = asyncio.Semaphore(LARGURA)
    respostas = await asyncio.gather(
        *(_mensais_de_uma(cliente, l, vagas) for l in com_manutencao),
        return_exceptions=True,
    )

    por_usina: dict[int, list[RelatorioMensalOut]] = {}
    falharam: list[str] = []
    for link, resposta in zip(com_manutencao, respostas, strict=True):
        if isinstance(resposta, BaseException):
            # A usina que caiu é NOMEADA. "Relatórios mensais indisponíveis" sem dizer de
            # qual usina faria o dono achar que a família inteira sumiu, quando faltou uma.
            falharam.append(link.nome)
            continue
        por_usina[link.id] = ordenar_mensais(resposta)

    aviso = None
    if falharam:
        aviso = "Não deu para buscar os relatórios mensais de: " + ", ".join(sorted(falharam))
    return por_usina, aviso


# ── a listagem ──────────────────────────────────────────────────────────────


def _links_do_recorte(db: Session, usuario: User, usina_id: int | None) -> list[PlantLink]:
    """As usinas desta pessoa, opcionalmente estreitadas a uma.

    Fora do escopo desta conta responde **404**, pela mesma razão de `_usina_no_escopo`:
    "proibido" confirmaria que a usina existe, e quem trocou o número na URL não tem por
    que descobrir isso.
    """
    links = usinas_do_usuario(db, usuario)
    if usina_id is None:
        return links
    alvo = next((l for l in links if l.id == usina_id), None)
    if alvo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")
    return [alvo]


async def _geracao(
    db: Session, links: list[PlantLink], usuario: User, *, filtrada: bool
) -> DocumentosOut:
    """Só a família da GERAÇÃO, do jeito que sempre foi. Nada aqui mudou nesta leva.

    `filtrada` diz se veio `?usina_id=` — e não se `links` tem um item só. Uma carteira com
    UMA usina e sem filtro continua ouvindo "nenhuma das suas usinas", que é a frase que o
    aplicativo já tem gravada; deduzir o recorte do tamanho da lista trocaria a frase numa
    carteira pequena sem ninguém ter pedido.
    """
    meus_slugs = {l.mw_plant_slug for l in links if l.mw_plant_slug}
    if not meus_slugs:
        # A frase muda conforme o recorte: com UMA usina pedida, dizer "nenhuma das suas"
        # seria falso; sem filtro, dizer "esta usina" não teria referente.
        if filtrada:
            return DocumentosOut(
                aviso="Esta usina não está ligada ao monitoramento, de onde vêm os relatórios."
            )
        return DocumentosOut(
            aviso="Nenhuma das suas usinas está ligada ao monitoramento, de onde vêm os relatórios."
        )

    try:
        cliente = vinculos.cliente_meuwatt(db, usuario.id)
        portal = await cliente.portal_relatorios()
    except Exception as exc:  # noqa: BLE001
        return DocumentosOut(aviso=f"Relatórios indisponíveis: {exc}")

    relatorios = portal.get("reports") if isinstance(portal, dict) else None
    if not isinstance(relatorios, list):
        return DocumentosOut(aviso="O monitoramento não devolveu relatórios.")

    # O corte que impede o vazamento: fora do escopo desta conta, não existe.
    nome_por_slug = {l.mw_plant_slug: l.nome for l in links if l.mw_plant_slug}
    id_por_slug = {l.mw_plant_slug: l.id for l in links if l.mw_plant_slug}

    saida: list[DocumentoOut] = []
    for r in relatorios:
        slug = r.get("plant_slug")
        if slug not in meus_slugs:
            continue
        saida.append(
            DocumentoOut(
                id=int(r["id"]),
                nome=str(r.get("name") or "Relatório"),
                # O nome que o cliente conhece é o do vínculo, não o do upstream.
                usina=nome_por_slug.get(slug) or str(r.get("plant_name") or ""),
                plant_id=id_por_slug.get(slug),
                periodo=str(r.get("period") or ""),
                de=r["date_from"],
                ate=r["date_to"],
                publicado_em=r["sent_at"],
                arquivos=[
                    ArquivoOut(
                        tipo=str(f.get("kind")),
                        nome=str(f.get("filename") or ""),
                        bytes=_inteiro(f.get("size_bytes")),
                    )
                    for f in (r.get("files") or [])
                    if isinstance(f, dict) and f.get("kind")
                ],
            )
        )

    # A ordem é por PUBLICAÇÃO (o que chegou por último aparece primeiro) — não por
    # competência. Quem quer o acervo por mês agrupa por `competencia`, que é outro eixo
    # e está aí em cima justamente para as duas coisas não se confundirem.
    saida.sort(key=lambda d: d.publicado_em, reverse=True)
    return DocumentosOut(documentos=saida)


async def documentos_de_geracao(
    usina_id: int | None, db: Session, usuario: User
) -> DocumentosOut:
    """A família da geração sozinha — para quem chama por DENTRO e não precisa do mensal.

    Existe porque `meus_documentos` passou a compor duas famílias, e há dois chamadores
    internos que não querem a segunda: `arquivo_do_documento`, que só refaz a autorização
    antes de servir um PDF de geração, e a grade do ano, que pede o mensal por conta
    própria (com o semáforo dela). Sem esta porta, autorizar um download passaria a custar
    uma ida ao meuPlano **por usina da carteira** — sete round-trips para conferir um id
    que já está na resposta do meuWatt.
    """
    links = _links_do_recorte(db, usuario, usina_id)
    return await _geracao(db, links, usuario, filtrada=usina_id is not None)


@router.get("/documents", response_model=DocumentosOut)
async def meus_documentos(
    usina_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
    # Injetados pelo FastAPI quando isto é uma ROTA. Ficam `None` quando `meus_documentos`
    # é chamado como função, e ali não existe pedido HTTP nenhum a revalidar.
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    """Os relatórios que o gestor publicou para as usinas desta pessoa — as DUAS famílias.

    `documentos` é o fechamento de GERAÇÃO do meuWatt e não mudou nada nesta leva.
    `mensais` é o relatório mensal de MANUTENÇÃO que o meuPlano liberou, e entra por
    adição: uma ida da tela, duas famílias, para o aplicativo não precisar de sete
    conexões nem de uma segunda chave de cache.

    As duas são buscadas **em paralelo** e falham separado — a queda do monitoramento não
    pode apagar o acervo de manutenção, e vice-versa. Cada motivo viaja no campo da sua
    família (`aviso` e `aviso_mensais`).

    `usina_id` (o id do vínculo) recorta a UMA usina — é como a tela de Relatórios do
    portal do cliente pede. Fora do escopo desta conta responde **404**, pela mesma razão
    de `_usina_no_escopo`: "proibido" confirmaria que a usina existe. O corte por
    `mw_plant_slug` continua sendo a barreira contra o vazamento da geração; o do mensal é
    `mp_usina_id` contra os vínculos desta conta, e o meuPlano ainda aplica o dele por
    cima (só o LIBERADO atravessa a porta `visao-cliente`).

    **Não há filtro de período aqui, de propósito.** A carteira inteira desta conta são
    1.564 bytes, e `usina_id` já não poupa uma única ida ao meuWatt — `portal_relatorios()`
    busca tudo de qualquer jeito e o corte é feito nesta máquina. Um filtro de mês no
    servidor custaria uma ida à rede e um arquivo de cache POR combinação escolhida, e a
    primeira escolha de cada filtro seria sempre fria: quem está em campo perderia o
    offline exatamente na interação nova. O corte do mês é do cliente, sobre o array que
    ele já tem em disco.

    **`ETag` + `If-None-Match`** é o que muda a vida de quem está no carro entre duas
    usinas: hoje o cache do app ou baixa tudo de novo ou mostra o velho, sem poder
    perguntar "mudou?". O acervo desta conta tem seis documentos e quatro deles são de
    junho — a revisita passa a custar 304 e zero byte de corpo.
    """

    def _entregar(saida: DocumentosOut) -> Any:
        """Uma saída só para todos os `return` desta rota — inclusive os avisos.

        O aviso também é uma resposta, e também revalida: "o monitoramento continua fora
        do ar" não precisa de corpo novo.
        """
        if request is None:  # chamada interna: não há pedido HTTP a revalidar
            return saida
        etag = _etag_de(saida)
        if _cliente_ja_tem(request.headers.get("if-none-match"), etag):
            # 304 vai SEM corpo e COM o ETag (RFC 9110 §15.4.5) — quem revalidou de novo
            # amanhã precisa continuar tendo a etiqueta para perguntar de novo.
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={"ETag": etag, "Cache-Control": "private, no-cache"},
            )
        if response is not None:
            response.headers["ETag"] = etag
            # `private` porque a resposta é RECORTADA POR PESSOA — um cache compartilhado
            # que a guardasse entregaria os relatórios desta conta à próxima. `no-cache`
            # não proíbe guardar: obriga a revalidar, que é exatamente o que o ETag serve.
            response.headers["Cache-Control"] = "private, no-cache"
        return saida

    links = _links_do_recorte(db, usuario, usina_id)

    # As duas famílias em paralelo, cada uma falhando por conta própria. `gather` sem
    # `return_exceptions` aqui de propósito: as duas já apanham o que é delas e devolvem
    # aviso em vez de exceção — o 404 de escopo, que é a única exceção legítima daqui, já
    # subiu em `_links_do_recorte`, antes de qualquer ida à rede.
    geracao, (mensais_por_usina, aviso_mensais) = await asyncio.gather(
        _geracao(db, links, usuario, filtrada=usina_id is not None),
        mensais_das_usinas(db, links, usuario),
    )
    geracao.mensais = ordenar_mensais(
        [r for lista in mensais_por_usina.values() for r in lista]
    )
    geracao.aviso_mensais = aviso_mensais
    return _entregar(geracao)


@router.get("/documents/{documento_id}/file")
async def arquivo_do_documento(
    documento_id: int,
    tipo: Literal["geracao", "paradas", "resumo"] = "geracao",
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """Os bytes do PDF.

    A autorização é refeita aqui, e não herdada da listagem: sem isto, trocar o número na
    URL baixaria o relatório de outro cliente — e um PDF de geração carrega o nome da
    usina, a produção e a perda do mês.

    **O `tipo` é `Literal`, e isso é defesa, não estilo.** Ele acabava interpolado na URL
    do upstream (`/reports/{id}/files/{kind}`), numa chamada feita com o token de serviço —
    que costuma ser de administrador. Como texto livre, `../../../admin/users` normalizava
    para outra rota da mw-api e devolvia os bytes: qualquer cliente com um único documento
    lia a plataforma inteira com credencial de admin. Uma linha anulava toda a disciplina
    de escopo do resto do BFF. Por isso o Resumo Executivo entrou ACRESCENTANDO um valor à
    lista, e não trocando o `Literal` por `str`.

    A segunda tranca é o cruzamento com os arquivos daquele documento: mesmo entre os três
    valores válidos, só se baixa a peça que o relatório realmente tem.

    Chama `documentos_de_geracao`, e não a rota: o que se autoriza aqui é um PDF de
    GERAÇÃO, e o acervo mensal de manutenção não diz nada sobre ele. Compor a segunda
    família faria cada download pagar uma ida ao meuPlano por usina da carteira — sete
    round-trips para conferir um id que já está na resposta do meuWatt.
    """
    docs = await documentos_de_geracao(None, db, usuario)
    alvo = next((d for d in docs.documentos if d.id == documento_id), None)
    if alvo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado.")
    if alvo.arquivos and not any(a.tipo == tipo for a in alvo.arquivos):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado.")

    try:
        cliente = vinculos.cliente_meuwatt(db, usuario.id)
        conteudo = await cliente.arquivo_relatorio(documento_id, tipo)
    except httpx.HTTPStatusError as exc:
        # Recusa por PUBLICAÇÃO não é falha de rede, e o cliente precisa ler a diferença.
        # Reabrir um fechamento no monitoramento zera o "enviado ao cliente" mas NÃO apaga
        # os arquivos: o link que o cliente guardou continua existindo e passa a responder
        # **403** (lá em cima o PDF só abre para relatório publicado). O **404** é o irmão
        # disso — o relatório sumiu, ou a peça foi retirada dele (medido: o fechamento 36
        # tem o Resumo e responde 404 na Geração). Achatar os dois no 503 genérico mandava
        # a pessoa procurar defeito onde houve decisão de quem publica.
        if exc.response.status_code in (403, 404):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Este relatório não está mais publicado, ou este arquivo foi retirado dele.",
            ) from exc
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Não foi possível baixar: {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Não foi possível baixar: {exc}"
        ) from exc

    return Response(
        content=conteudo,
        media_type="application/pdf",
        # O `tipo` entra no nome porque um fechamento tem até três peças: sem ele, as três
        # chegariam ao computador do cliente com o mesmo nome de arquivo.
        headers={
            "Content-Disposition": f'inline; filename="relatorio-{documento_id}-{tipo}.pdf"'
        },
    )
