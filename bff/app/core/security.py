"""Emissão e verificação do JWT que o BFF entrega ao app."""

from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models.user import User

ALGORITMO = "HS256"
_bearer = HTTPBearer(auto_error=False)


def criar_token(user_id: int) -> tuple[str, datetime]:
    s = get_settings()
    expira = datetime.now(UTC) + timedelta(hours=s.gs_jwt_expira_horas)
    token = jwt.encode(
        {"sub": str(user_id), "exp": expira}, s.gs_jwt_secret, algorithm=ALGORITMO
    )
    return token, expira


def usuario_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(
            cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO]
        )
        user_id = int(dados["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc

    usuario = db.get(User, user_id)
    if usuario is None or not usuario.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")
    return usuario
