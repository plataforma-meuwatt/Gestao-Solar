"""O TermoVision e as usinas do GS (Plano Casa GS, 24/11/2026: "o TermoVision tem o mapa dele, e posso gerar no
TermoVision e enviar para o GS, onde ele vai pedir qual usina do GS; aí ele mostra as referências: usinas meuWatt,
meuPlano etc.; se for a mesma em todas, o link já vai existir. Se não tiver, ele não exporta, porque é preciso criar
primeiro").

O contrato é o que o TermoVision propôs (o "Enviar ao GS" de lá), com a pessoa junto, no padrão da porta das câmeras
(`interno_meuguarda.py`). Quem chama é o servidor do TermoVision, provado pela chave dele (`X-Sistema: termovision` e
`X-Chave-Interna`, a mesma prova do repasse do login, `acessos.repasse`), em nome de QUEM está com a tela aberta
(`X-Usuario-GS`, o `sub` do passe dela, e `X-Empresa-GS`, o `empresa_id` do passe). A chave sozinha não basta:
- a pessoa tem de ter entrado no TermoVision pelo GS nas últimas 12 h (um passe registrado em `gs_acessos`): a chave
  vazada não fala em nome de quem não está usando o TermoVision;
- só a equipe da O&M (gerente e técnico, `mapa._O_E_M`) usa estas rotas, e só as usinas de uma empresa ATIVA da
  pessoa (a de `X-Empresa-GS`, ou a de origem sem o cabeçalho). O dono e a plataforma recebem 403.

- `GET /usinas[?ids=12,15]`: as usinas, com as referências da mesma usina em cada sistema e os dados básicos.
- `POST /usinas/{gs}/mapa {termovision}`: liga o mapa. Idempotente pelo valor; o mesmo mapa em outra usina, ou outro
  mapa já ligado, é 409 (o nome da outra usina só quando é da mesma empresa). O GS guarda só o vínculo.
- `DELETE /usinas/{gs}/mapa?termovision=`: desliga (o "Desligar do GS"); já desligada, responde a usina (idempotente).

Pessoa (inexistente, desativada, sem o TermoVision), empresa ou usina que não serve é 404 com a mesma frase. O dono e a
plataforma recebem 403 (o mapa se liga pela O&M); sem entrada no TermoVision pelo GS nas últimas 12 h, 403 "entre de
novo pelo GS". A empresa (`X-Empresa-GS`) é conferida contra as empresas ativas da pessoa, não contra o passe.
"""
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1 import mapa
from app.core.config import get_settings
from app.core.db import get_db
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import User
from app.services import acessos, empresas

_NAO = "Pessoa ou usina não encontrada."
#: há quanto tempo a pessoa entrou no TermoVision pelo GS para o TermoVision falar por ela
JANELA_DO_PASSE = timedelta(hours=12)

router = APIRouter(prefix="/api/v1/interno", tags=["interno · TermoVision"])
Codigo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]


def _porta(request: Request) -> None:
    if not get_settings().termovision_chave_interna:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Porta interna do TermoVision não configurada (TERMOVISION_CHAVE_INTERNA ausente).")
    if acessos.repasse(request) != "termovision":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave inválida.")


def _pessoa(db: Session, x_usuario_gs: str | None) -> User:
    """A pessoa, ativa, com o TermoVision liberado, da O&M e que entrou nele pelo GS há pouco."""
    texto = (x_usuario_gs or "").strip()
    u = db.get(User, int(texto)) if texto.isdecimal() else None
    if u is None or not u.ativo or not u.entra_no_termovision:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    if u.perfil not in mapa._O_E_M:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "O mapa se liga pela equipe da O&M da usina.")
    # só a entrada da PRÓPRIA pessoa (com o IP dela): o bot e o conector também entram lá por ela, sem pedido
    # (registro sem IP), e não abrem esta janela
    recente = db.scalar(select(AcessoGS.id).where(
        AcessoGS.gs_user_id == u.id, AcessoGS.sistema == "termovision", AcessoGS.acao == "passe", AcessoGS.ok,
        AcessoGS.ip != "", AcessoGS.em >= datetime.now(UTC) - JANELA_DO_PASSE).limit(1))
    if recente is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Esta pessoa não entrou no TermoVision pelo Gestão Solar nas últimas 12 horas: "
                            "entre de novo pelo GS.")
    return u


def _empresa(db: Session, pessoa: User, x_empresa_gs: str | None) -> int:
    """A empresa do passe (`X-Empresa-GS`), ou a de origem sem ele; tem de ser da pessoa e estar ativa."""
    texto = (x_empresa_gs or "").strip()
    pedida = int(texto) if texto.isdecimal() else (pessoa.empresa_id if not texto else None)
    ativas = set(db.scalars(select(Empresa.id).where(Empresa.id.in_(empresas.empresas_da_conta(db, pessoa) or [-1]),
                                                     Empresa.ativa)))
    if pedida is None or pedida not in ativas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    return pedida


def _da_empresa(db: Session, empresa_id: int, so_ativas: bool = True) -> list[PlantLink]:
    """As usinas da empresa: as ativas para listar e ligar; todas para desligar e para dizer o nome no conflito (a usina
    desligada no GS não pode prender o mapa dos dois lados)."""
    q = select(PlantLink).where(PlantLink.empresa_id == empresa_id)
    return list(db.scalars((q.where(PlantLink.ativo) if so_ativas else q).order_by(PlantLink.nome)).all())


def _da_pessoa(db: Session, x_usuario_gs: str | None, x_empresa_gs: str | None, gs: int, so_ativas: bool = True
               ) -> tuple[PlantLink, list[PlantLink]]:
    """A usina pedida e TODAS as da empresa (para o nome no conflito)."""
    todas = _da_empresa(db, _empresa(db, _pessoa(db, x_usuario_gs), x_empresa_gs), so_ativas=False)
    link = next((u for u in todas if u.id == gs and (u.ativo or not so_ativas)), None)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    return link, todas


class RefMeuWatt(BaseModel):
    slug: str


class RefMeuPlano(BaseModel):
    id: int


class RefTermoVision(BaseModel):
    codigo: str


class UsinaDoGS(BaseModel):
    gs: int
    nome: str
    empresa: str | None = None
    #: a MESMA usina em cada sistema (nulo = não está lá)
    meuwatt: RefMeuWatt | None = None
    meuplano: RefMeuPlano | None = None
    termovision: RefTermoVision | None = None
    cidade: str | None = None
    uf: str | None = None
    endereco: str | None = None
    latitude: float | None = None
    longitude: float | None = None


def _saida(db: Session, u: PlantLink) -> UsinaDoGS:
    empresa = db.get(Empresa, u.empresa_id) if u.empresa_id else None
    return UsinaDoGS(
        gs=u.id, nome=u.nome, empresa=empresa.nome if empresa else None,
        meuwatt=RefMeuWatt(slug=u.mw_plant_slug) if u.mw_plant_slug else None,
        meuplano=RefMeuPlano(id=u.mp_usina_id) if u.mp_usina_id is not None else None,
        termovision=RefTermoVision(codigo=u.tv_codigo) if u.tv_codigo else None,
        cidade=u.cidade, uf=u.uf, endereco=u.endereco, latitude=u.latitude, longitude=u.longitude)


def _ocupado(outra: PlantLink | None, visiveis: list[PlantLink]) -> HTTPException:
    """O mapa já ligado a outra usina: o nome dela só quando é da empresa (a de outra empresa não se nomeia)."""
    nome = f" ({outra.nome})" if outra is not None and any(u.id == outra.id for u in visiveis) else ""
    return HTTPException(status.HTTP_409_CONFLICT, f"Este mapa do TermoVision já está ligado a outra usina do GS{nome}.")


def _ligar(db: Session, link: PlantLink, codigo: str, visiveis: list[PlantLink]) -> PlantLink:
    """Grava o vínculo só se a usina ainda está sem mapa (dois pedidos ao mesmo tempo: um ganha, o outro é 409)."""
    try:
        gravou = db.execute(update(PlantLink).where(PlantLink.id == link.id, PlantLink.tv_codigo.is_(None))
                            .values(tv_codigo=codigo)).rowcount
        db.commit()
    except IntegrityError:                                 # o mesmo mapa entrou em outra usina no meio do caminho
        db.rollback()
        raise _ocupado(db.scalar(select(PlantLink).where(PlantLink.tv_codigo == codigo)), visiveis) from None
    db.refresh(link)
    if not gravou and link.tv_codigo != codigo:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina do GS já está ligada ao mapa {link.tv_codigo} "
                                                      "do TermoVision: desligue esse antes.")
    return link


@router.get("/usinas", response_model=list[UsinaDoGS], dependencies=[Depends(_porta)])
def usinas_da_pessoa(
    ids: str | None = None,
    x_usuario_gs: str | None = Header(default=None, alias="X-Usuario-GS"),
    x_empresa_gs: str | None = Header(default=None, alias="X-Empresa-GS"),
    db: Session = Depends(get_db),
) -> list[UsinaDoGS]:
    visiveis = _da_empresa(db, _empresa(db, _pessoa(db, x_usuario_gs), x_empresa_gs))
    if ids is None:
        return [_saida(db, u) for u in visiveis]
    pedidas = {int(x) for x in ids.split(",") if x.strip().isdecimal()}
    return [_saida(db, u) for u in visiveis if u.id in pedidas]


class LigarMapaIn(BaseModel):
    termovision: Codigo


@router.post("/usinas/{gs}/mapa", response_model=UsinaDoGS, dependencies=[Depends(_porta)])
def ligar_mapa(
    gs: int,
    body: LigarMapaIn,
    x_usuario_gs: str | None = Header(default=None, alias="X-Usuario-GS"),
    x_empresa_gs: str | None = Header(default=None, alias="X-Empresa-GS"),
    db: Session = Depends(get_db),
) -> UsinaDoGS:
    link, visiveis = _da_pessoa(db, x_usuario_gs, x_empresa_gs, gs)
    if link.tv_codigo == body.termovision:
        return _saida(db, link)                            # idempotente
    if link.tv_codigo:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina do GS já está ligada ao mapa {link.tv_codigo} "
                                                      "do TermoVision: desligue esse antes.")
    outra = db.scalar(select(PlantLink).where(PlantLink.tv_codigo == body.termovision))
    if outra is not None:
        raise _ocupado(outra, visiveis)
    return _saida(db, _ligar(db, link, body.termovision, visiveis))


@router.delete("/usinas/{gs}/mapa", response_model=UsinaDoGS, dependencies=[Depends(_porta)])
def desligar_mapa(
    gs: int,
    termovision: Codigo,
    x_usuario_gs: str | None = Header(default=None, alias="X-Usuario-GS"),
    x_empresa_gs: str | None = Header(default=None, alias="X-Empresa-GS"),
    db: Session = Depends(get_db),
) -> UsinaDoGS:
    link, _ = _da_pessoa(db, x_usuario_gs, x_empresa_gs, gs, so_ativas=False)   # a desligada no GS também solta o mapa
    if link.tv_codigo is None:
        return _saida(db, link)                            # já desligada: repetir o pedido não é erro
    if link.tv_codigo != termovision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta usina do GS está ligada a outro mapa do TermoVision.")
    db.execute(update(PlantLink).where(PlantLink.id == link.id, PlantLink.tv_codigo == termovision)
               .values(tv_codigo=None))
    db.commit()
    db.refresh(link)
    return _saida(db, link)
