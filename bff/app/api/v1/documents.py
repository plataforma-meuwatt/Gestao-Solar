"""Relatórios publicados para o dono da usina.

A fonte é o Portal do Cliente do meuWatt (`/reports/portal`), e ele tem uma característica
que **obriga** a filtrar aqui: quando quem chama é administrador, ele devolve as usinas
todas — é a pré-visualização que o gestor usa. O BFF chama com um token pessoal que
costuma ser de administrador, então repassar a resposta crua entregaria a este cliente os
relatórios de todos os outros.

Por isso nada sai daqui sem passar por `usinas_do_usuario`: o corte é feito por
`mw_plant_slug`, contra o que o gestor concedeu a esta conta. É o mesmo princípio das
outras rotas — a autorização é do BFF, nunca do upstream.
"""

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
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · documentos"])


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


class DocumentosOut(BaseModel):
    documentos: list[DocumentoOut] = []
    aviso: str | None = None


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


@router.get("/documents", response_model=DocumentosOut)
async def meus_documentos(
    usina_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
    # Injetados pelo FastAPI quando isto é uma ROTA. Ficam `None` quando `meus_documentos`
    # é chamado como função — é o que `arquivo_do_documento` faz para refazer a
    # autorização, e ali não existe pedido HTTP nenhum a revalidar.
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    """Os relatórios que o gestor publicou para as usinas desta pessoa.

    `usina_id` (o id do vínculo) recorta a UMA usina — é como a tela de Relatórios do
    portal do cliente pede. Fora do escopo desta conta responde **404**, pela mesma razão
    de `_usina_no_escopo`: "proibido" confirmaria que a usina existe. O corte por
    `mw_plant_slug` continua sendo a barreira contra o vazamento; o filtro só o estreita.

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

    links = usinas_do_usuario(db, usuario)
    if usina_id is not None:
        alvo = next((l for l in links if l.id == usina_id), None)
        if alvo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")
        if not alvo.mw_plant_slug:
            return _entregar(
                DocumentosOut(
                    aviso="Esta usina não está ligada ao monitoramento, de onde vêm os relatórios."
                )
            )
        links = [alvo]
    meus_slugs = {l.mw_plant_slug for l in links if l.mw_plant_slug}

    if not meus_slugs:
        return _entregar(
            DocumentosOut(
                aviso="Nenhuma das suas usinas está ligada ao monitoramento, de onde vêm os relatórios."
            )
        )

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        portal = await cliente.portal_relatorios()
    except Exception as exc:  # noqa: BLE001
        return _entregar(DocumentosOut(aviso=f"Relatórios indisponíveis: {exc}"))

    relatorios = portal.get("reports") if isinstance(portal, dict) else None
    if not isinstance(relatorios, list):
        return _entregar(DocumentosOut(aviso="O monitoramento não devolveu relatórios."))

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
    return _entregar(DocumentosOut(documentos=saida))


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
    """
    docs = await meus_documentos(db=db, usuario=usuario)
    alvo = next((d for d in docs.documentos if d.id == documento_id), None)
    if alvo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado.")
    if alvo.arquivos and not any(a.tipo == tipo for a in alvo.arquivos):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado.")

    try:
        cliente = await integracoes.cliente_meuwatt(db)
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
