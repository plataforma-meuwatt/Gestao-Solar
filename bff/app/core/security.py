"""Senha e sessão do Gestão Solar."""

import base64
import hashlib
import hmac
import secrets
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

# PBKDF2-SHA256 com 600 mil iterações — a recomendação do OWASP de 2023, e o mesmo
# parâmetro que o meuWatt usa. Sem dependência nova: `hashlib` basta.
_ITERACOES = 600_000


def gerar_hash_senha(senha: str) -> str:
    """Formato autodescritivo: guardar as iterações no próprio hash permite subir o custo
    no futuro sem migrar o que já está gravado."""
    sal = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, _ITERACOES)
    return (
        f"pbkdf2_sha256${_ITERACOES}$"
        f"{base64.b64encode(sal).decode()}${base64.b64encode(digest).decode()}"
    )


def conferir_senha(senha: str, guardado: str | None) -> bool:
    """Comparação em tempo constante. Hash malformado devolve `False` em silêncio — do
    ponto de vista de quem tenta entrar, é indistinguível de senha errada, que é o que
    queremos."""
    if not guardado:
        return False
    try:
        algoritmo, iteracoes, sal_b64, digest_b64 = guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode(), base64.b64decode(sal_b64), int(iteracoes)
        )
        return hmac.compare_digest(calculado, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


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


def criar_token_painel(user_id: int) -> tuple[str, datetime]:
    """Sessão do painel: curta, e marcada com `escopo=painel` para não ser confundida com
    a sessão do app. Um token do app não abre o painel, e vice-versa."""
    s = get_settings()
    expira = datetime.now(UTC) + timedelta(hours=s.gs_painel_sessao_horas)
    token = jwt.encode(
        {"sub": str(user_id), "escopo": "painel", "exp": expira},
        s.gs_jwt_secret,
        algorithm=ALGORITMO,
    )
    return token, expira


def gestor_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Guarda do painel. Exige as três coisas: token válido, escopo de painel, e a conta
    ainda ser de gestor — quem perdeu o cargo perde o painel na requisição seguinte, sem
    depender do token expirar."""
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(
            cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO]
        )
        if dados.get("escopo") != "painel":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta sessão não abre o painel")
        user_id = int(dados["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc

    usuario = db.get(User, user_id)
    if usuario is None or not usuario.ativo or not usuario.is_gestor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito à administração")
    return usuario
