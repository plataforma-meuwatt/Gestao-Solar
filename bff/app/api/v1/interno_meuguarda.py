"""O meuGuarda lê a POSIÇÃO das câmeras dele no mapa único da usina (18/11/2026).

O dono: "o mapa pode ser tipo gestao.solar/mapa/usina … o meuGuarda pode ficar da forma que está, mas no fundo ele só
consome o mapa"; e "o meuGuarda vê se tem coisa desatualizada e fala se quer atualizar lá". A posição mora no mapa
único (lido pelo sistema de manutenção, que diz qual câmera do meuGuarda cada ponto é: `mg_camera_id`); o meuGuarda
compara com a dele e oferece atualizar lá.

Quem chama é a API do meuGuarda (máquina), no padrão de `interno_whatsapp.py`: a chave própria em cabeçalho
(`X-Chave-Interna`, comparação de tempo constante; sem a chave configurada a rota recusa tudo) e o apelido da pessoa
que está com a tela aberta. O recorte é DELA: a usina tem de estar entre as que ela vê no mapa e o meuGuarda liberado
para ela — a mesma régua de `mapa.py`. Só leitura.
"""

import hmac
import math
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1 import mapa
from app.api.v1.manutencao import MANUTENCAO
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import _da_empresa, _empresa_ativa
from app.models.user import User

#: a MESMA resposta para pessoa e usina que não servem: a porta não confirma quem existe
_NAO = "Pessoa ou usina não encontrada (ou sem as câmeras liberadas)."

router = APIRouter(prefix="/api/v1/interno/meuguarda", tags=["interno · meuGuarda"])


def _porta(x_chave_interna: str | None = Header(default=None, alias="X-Chave-Interna")) -> None:
    esperada = get_settings().meuguarda_chave_interna
    if not esperada:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Porta interna das câmeras não configurada (MEUGUARDA_CHAVE_INTERNA ausente).")
    if not hmac.compare_digest(x_chave_interna or "", esperada):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave inválida.")


def _ponto(o: dict) -> tuple[float, float] | None:
    """(lat, lng) do ponto, ou None (não é ponto, ou a coordenada não é um número de verdade)."""
    g = o.get("geometria") or {}
    c = g.get("coordinates")
    if g.get("type") != "Point" or not isinstance(c, list) or len(c) != 2:
        return None
    try:
        lng, lat = float(c[0]), float(c[1])
    except (TypeError, ValueError):
        return None
    return (lat, lng) if math.isfinite(lat) and math.isfinite(lng) else None


@router.get("/usinas/{usina_id}/cameras", dependencies=[Depends(_porta)])
async def posicoes(usina_id: int, pessoa: str, db: Session = Depends(get_db)) -> dict:
    """As câmeras do meuGuarda marcadas no mapa único desta usina (`usina_id` = o `gs_usina_id` de lá), com a posição,
    para a pessoa `pessoa` (apelido do GS). Sem leitura do mapa é erro (502), nunca uma lista vazia que parece certa."""
    user = db.scalar(select(User).where(User.apelido == (pessoa or "").strip().lower()))
    if user is None or not user.ativo or not user.entra_no_meuguarda:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    try:                                                    # a empresa desativada para de ler, como nas sessões
        _da_empresa(db, user) if user.perfil in mapa._O_E_M else _empresa_ativa(db, user)
        link = mapa._usina(db, user, usina_id)              # fora das usinas dela
    except HTTPException as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO) from exc
    o_e_m = user.perfil in mapa._O_E_M
    base = {"usina": {"id": link.id, "nome": link.nome}, "lido_em": datetime.now(timezone.utc).isoformat()}
    if link.mp_usina_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina ainda não está ligada ao {MANUTENCAO}: sem mapa.")
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        cliente = cliente_meuplano(db, user.id)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc) if o_e_m else
                            f"O {MANUTENCAO} desta pessoa não está conectado.") from exc
    db.commit()                                             # solta a conexão enquanto o outro sistema responde
    try:
        lido = await cliente.mapa_da_usina(link.mp_usina_id)
    except httpx.HTTPError as exc:
        raise mapa._do_upstream(exc, MANUTENCAO) from exc
    if lido.get("vinculado") is False:                     # sem mapa não é "nenhuma câmera no mapa"
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta usina ainda não tem o mapa ligado: sem posições.")
    if lido.get("aviso") and not lido.get("objetos"):       # o mapa não foi lido: dizer, não devolver vazio
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "O mapa não pôde ser lido agora"
                            + (f": {lido['aviso']}" if o_e_m else "."))
    cameras = []
    for o in lido.get("objetos") or []:
        if not o.get("mg_camera_id"):
            continue
        p = _ponto(o)
        forma = (o.get("geometria") or {}).get("type")
        # a câmera desenhada como linha/área (ou com coordenada estragada) vem SEM posição e dizendo por quê
        cameras.append({"mg_camera_id": o["mg_camera_id"], "nome": o.get("node_nome") or o.get("nome"),
                        "lat": p[0] if p else None, "lng": p[1] if p else None,
                        "sem_posicao": None if p else ("desenhada como " + ("área" if forma == "Polygon" else "linha")
                                                       if forma in ("Polygon", "LineString") else "coordenada inválida")})
    aviso = lido.get("aviso")
    if aviso and not o_e_m:
        aviso = "O mapa foi lido em parte: algumas marcações podem faltar."
    return {**base, "cameras": cameras, "aviso": aviso}
