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

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.plants import usinas_do_usuario
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · documentos"])


class ArquivoOut(BaseModel):
    #: `geracao` (Relatório de Geração) ou `paradas` (Anexo de Paradas).
    tipo: str
    nome: str


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


class DocumentosOut(BaseModel):
    documentos: list[DocumentoOut] = []
    aviso: str | None = None


@router.get("/documents", response_model=DocumentosOut)
async def meus_documentos(
    usina_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> DocumentosOut:
    """Os relatórios que o gestor publicou para as usinas desta pessoa.

    `usina_id` (o id do vínculo) recorta a UMA usina — é como a tela de Relatórios do
    portal do cliente pede. Fora do escopo desta conta responde **404**, pela mesma razão
    de `_usina_no_escopo`: "proibido" confirmaria que a usina existe. O corte por
    `mw_plant_slug` continua sendo a barreira contra o vazamento; o filtro só o estreita.
    """
    links = usinas_do_usuario(db, usuario)
    if usina_id is not None:
        alvo = next((l for l in links if l.id == usina_id), None)
        if alvo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")
        if not alvo.mw_plant_slug:
            return DocumentosOut(
                aviso="Esta usina não está ligada ao meuWatt, de onde vêm os relatórios."
            )
        links = [alvo]
    meus_slugs = {l.mw_plant_slug for l in links if l.mw_plant_slug}

    if not meus_slugs:
        return DocumentosOut(
            aviso="Nenhuma das suas usinas está ligada ao meuWatt, de onde vêm os relatórios."
        )

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        portal = await cliente.portal_relatorios()
    except Exception as exc:  # noqa: BLE001
        return DocumentosOut(aviso=f"Relatórios indisponíveis: {exc}")

    relatorios = portal.get("reports") if isinstance(portal, dict) else None
    if not isinstance(relatorios, list):
        return DocumentosOut(aviso="O meuWatt não devolveu relatórios.")

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
                    ArquivoOut(tipo=str(f.get("kind")), nome=str(f.get("filename") or ""))
                    for f in (r.get("files") or [])
                    if isinstance(f, dict) and f.get("kind")
                ],
            )
        )

    saida.sort(key=lambda d: d.publicado_em, reverse=True)
    return DocumentosOut(documentos=saida)


@router.get("/documents/{documento_id}/file")
async def arquivo_do_documento(
    documento_id: int,
    tipo: Literal["geracao", "paradas"] = "geracao",
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
    de escopo do resto do BFF.

    A segunda tranca é o cruzamento com os arquivos daquele documento: mesmo entre os dois
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
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Não foi possível baixar: {exc}"
        ) from exc

    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="relatorio-{documento_id}.pdf"'},
    )
