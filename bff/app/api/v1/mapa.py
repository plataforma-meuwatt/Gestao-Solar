"""O MAPA ÚNICO da usina — gestao.solar/mapa/<usina> (o dono, 18/11/2026: "o mapa pode ser tipo gestao.solar/mapa/usina
… todos usam o mesmo … o meuGuarda só consome o mapa"; escolheu: página no GS, a O&M edita, o dono da usina só vê).

De onde vem cada coisa — nada fica guardado aqui:
- o voo (ortomosaico) e a posição de cada equipamento moram no mapa do meuWatt; o meuPlano o lê e liga cada objeto ao
  equipamento da árvore (`GET /usinas/{id}/mapa` de lá, a ligação pela origem `meuplano:node:<id>` ou pelo nome). Aqui a
  leitura é a desse mapa, com o token da PESSOA, senão o da empresa que a atende (`vinculos.token_do_cliente`, a régua
  do portal) — nunca uma credencial de plataforma;
- marcar e mover é da O&M (gerente e técnico), com o token PESSOAL do meuPlano de quem edita: a permissão dele lá
  (`meuacesso.usinas.coordenada`) decide, e o histórico diz quem foi. A posição vai ao mapa do meuWatt pela rota do
  meuPlano (`POST /usinas/{id}/mapa/ponto`), sem segunda cópia em lugar nenhum.

Quem abre: as três sessões do GS valem (a do portal, a do gerente e a do técnico). O dono vê as usinas dele; a O&M, as da
empresa dela.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.plants import usinas_do_usuario
from app.core.db import get_db
from app.core.security import _bearer, gestor_empresa_atual, tecnico_atual, usuario_atual
from app.api.v1.manutencao import MANUTENCAO
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import empresas, integracoes

router = APIRouter(prefix="/api/v1/mapa", tags=["mapa"])

_O_E_M = (Perfil.GESTOR_EMPRESA, Perfil.TECNICO)


def quem_abre(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    """A sessão do portal (dono), a do gerente ou a do técnico: cada guarda confere a sua, e a primeira que aceita vale."""
    for guarda in (usuario_atual, gestor_empresa_atual, tecnico_atual):
        try:
            return guarda(cred, db)
        except HTTPException:
            continue
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")


def usinas_do_mapa(db: Session, user: User) -> list[PlantLink]:
    """O dono: as dele (a régua do portal). A O&M: as da empresa — o técnico também, que trabalha nelas."""
    if user.perfil in _O_E_M:
        minhas = empresas.empresas_da_conta(db, user)
        return list(db.scalars(select(PlantLink).where(PlantLink.empresa_id.in_(minhas or [-1]), PlantLink.ativo)
                               .order_by(PlantLink.nome)).all())
    return usinas_do_usuario(db, user)


def _usina(db: Session, user: User, usina_id: int) -> PlantLink:
    link = next((u for u in usinas_do_mapa(db, user) if u.id == usina_id), None)
    if link is None:                                       # 404 e não 403: não confirma que a usina existe
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")
    return link


def _edita(user: User) -> str | None:
    """Por que esta pessoa NÃO edita o mapa (None = edita)."""
    if user.perfil not in _O_E_M:
        return "O mapa é editado pela equipe de O&M."
    if not user.tem_token(Produto.MEUPLANO):
        return f"Para marcar no mapa, a sua conta precisa do token do {MANUTENCAO} (o gerente cola em Usuários)."
    return None


def _do_upstream(exc: httpx.HTTPError, quem: str) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        frase = integracoes.detalhe_do_upstream(exc.response)
        codigo = exc.response.status_code
        return HTTPException(codigo if codigo in (400, 403, 404, 409, 424) else status.HTTP_502_BAD_GATEWAY,
                             frase or f"O {quem} respondeu {codigo}.")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"O {quem} não respondeu agora.")


class UsinaDoMapa(BaseModel):
    id: int
    nome: str
    mp_usina_id: int | None = None
    mw_slug: str | None = None


@router.get("/usinas", response_model=list[UsinaDoMapa])
def listar(db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> list[UsinaDoMapa]:
    """As usinas que esta pessoa abre no mapa — e a ponte para o endereço vindo de outro produto
    (`/mapa?meuplano=<id>` do meuPlano, `?meuwatt=<slug>` do meuWatt)."""
    return [UsinaDoMapa(id=u.id, nome=u.nome, mp_usina_id=u.mp_usina_id, mw_slug=u.mw_plant_slug)
            for u in usinas_do_mapa(db, user)]


@router.get("/usinas/{usina_id}")
async def mapa_da_usina(usina_id: int, db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> dict:
    """O mapa: o pino e o contorno da usina, o voo, cada equipamento marcado (com o nó do meuPlano que ele é) e se esta
    pessoa pode editar. O meuWatt fora ou recusando vira `aviso` — nunca um mapa vazio que parece certo."""
    link = _usina(db, user, usina_id)
    por_que = _edita(user)
    base = {"usina": {"id": link.id, "nome": link.nome}, "pode_editar": por_que is None, "por_que_nao_edita": por_que,
            "mapa": None, "aviso": None}
    if link.mp_usina_id is None:
        return {**base, "aviso": f"Esta usina ainda não está ligada ao {MANUTENCAO}: o mapa dela ainda não existe."}
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        cliente = cliente_meuplano(db, user.id)
    except SemConexao as exc:
        return {**base, "aviso": str(exc)}
    db.commit()                                            # solta a conexão enquanto o meuPlano responde
    try:
        mapa = await cliente.mapa_da_usina(link.mp_usina_id)
    except httpx.HTTPError as exc:
        return {**base, "aviso": _do_upstream(exc, MANUTENCAO).detail}
    aviso = mapa.get("aviso")
    if aviso and user.perfil not in _O_E_M:                # o motivo de lá cita os produtos: ao dono, o serviço
        aviso = "O mapa desta usina não pôde ser lido agora: o voo e as marcações voltam quando o serviço responder."
    return {**base, "mapa": mapa, "aviso": aviso}


def _meuplano_da_pessoa(db: Session, user: User):
    from app.services.vinculos import SemConexao, cliente_meuplano
    if (motivo := _edita(user)) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, motivo)
    try:
        return cliente_meuplano(db, user.id, so_proprio=True)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/usinas/{usina_id}/equipamentos")
async def equipamentos(usina_id: int, nome: str, db: Session = Depends(get_db),
                       user: User = Depends(quem_abre)) -> dict:
    """O equipamento pelo nome (o "Câmera 01" acha com "câmera 1"), para marcar no mapa — como a pessoa (O&M)."""
    link = _usina(db, user, usina_id)
    if link.mp_usina_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina não está ligada ao {MANUTENCAO}.")
    if not (nome or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Diga o nome do equipamento.")
    mp = _meuplano_da_pessoa(db, user)
    db.commit()
    try:
        return await mp.equipamento_pelo_nome(link.mp_usina_id, nome.strip()[:120])
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MANUTENCAO) from exc


class PontoIn(BaseModel):
    node_id: int
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@router.post("/usinas/{usina_id}/ponto")
async def marcar(usina_id: int, body: PontoIn, db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> dict:
    """Marca (ou move) o equipamento no mapa — como a pessoa (O&M), pela rota do meuPlano; a posição vai ao mapa do
    meuWatt, a única."""
    link = _usina(db, user, usina_id)
    if link.mp_usina_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina não está ligada ao {MANUTENCAO}.")
    mp = _meuplano_da_pessoa(db, user)
    db.commit()
    try:
        return await mp.marcar_no_mapa(link.mp_usina_id, body.node_id, body.lat, body.lng)
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MANUTENCAO) from exc
