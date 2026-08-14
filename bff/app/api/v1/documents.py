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
    db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)
) -> DocumentosOut:
    """Os relatórios que o gestor publicou para as usinas desta pessoa."""
    links = usinas_do_usuario(db, usuario)
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
    tipo: str = "geracao",
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """Os bytes do PDF.

    A autorização é refeita aqui, e não herdada da listagem: sem isto, trocar o número na
    URL baixaria o relatório de outro cliente — e um PDF de geração carrega o nome da
    usina, a produção e a perda do mês.
    """
    docs = await meus_documentos(db=db, usuario=usuario)
    if not any(d.id == documento_id for d in docs.documentos):
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
