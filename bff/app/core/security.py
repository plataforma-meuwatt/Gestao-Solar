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


def gerar_senha_provisoria() -> str:
    """Senha forte que uma pessoa consegue ditar por telefone.

    O alfabeto exclui os pares que se confundem falados ou escritos à mão — `0/O`, `1/I/L`,
    `5/S`, `2/Z` — e os grupos de quatro com hífen evitam que alguém perca a conta ao
    transcrever. Três grupos do alfabeto de 26 dão ~56 bits: é provisória, será trocada no
    primeiro acesso, e o custo de errar ao ditar é maior que o de encurtar.
    """
    alfabeto = "ABCDEFGHJKMNPQRTUVWXY346789"
    grupos = ["".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3)]
    return "-".join(grupos)


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
    """Guarda do cliente (app e portal). Só aceita a sessão emitida por `criar_token`.

    A promessa "um token do app não abre o painel, e vice-versa" era cumprida pela metade:
    `gestor_atual` recusava o token do cliente, mas esta função lia só o `sub` e deixava um
    token de painel entrar em `/api/v1/*` em nome do gestor. Passou despercebido enquanto
    o gestor não tinha usina concedida — a lista vinha vazia e ninguém reclamava. Com o
    portal do cliente e o painel em domínios separados (app.gestao.solar × adm.gestao.solar),
    uma sessão não pode valer nos dois: quem cola o token do painel aqui recebe 401, e o
    portal manda a pessoa entrar com a conta de cliente.
    """
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(
            cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO]
        )
        user_id = int(dados["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc

    # Qualquer `escopo` no JWT é sessão de outro portão — hoje só existe `painel`, e o
    # teste é pela PRESENÇA da claim de propósito: um escopo novo no futuro nasce recusado
    # aqui, em vez de entrar por omissão.
    if "escopo" in dados:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Esta sessão é do painel do gestor"
        )

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
    ainda abrir o painel — quem perdeu o cargo perde o acesso na requisição seguinte, sem
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
    if usuario is None or not usuario.ativo or not usuario.abre_painel:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito à administração")
    return usuario


def administrador_atual(gestor: User = Depends(gestor_atual)) -> User:
    """Guarda das telas que mexem no que quebra tudo: as pontes com os produtos (que
    guardam credencial de serviço) e a própria equipe. Atendimento cuida de cliente e
    diagnóstico, e não passa daqui."""
    if not gestor.e_administrador:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta área é restrita a administradores.",
        )
    return gestor
