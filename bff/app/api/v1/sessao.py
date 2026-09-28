"""Trocar de papel — a rota que atravessa os três portões.

É o único lugar do sistema que aceita sessão de qualquer portão, e por um motivo estreito:
ela não devolve dado nenhum. Recebe um token válido, confere que a conta de destino é do
mesmo humano e emite o token DAQUELE portão. Nada de empresa, nada de usina, nada de
cliente passa por aqui.

A guarda é montada à mão em vez de reusar `usuario_atual`/`gestor_atual`/`gestor_empresa_atual`:
cada uma delas recusa, de propósito, as sessões dos outros dois — e essa recusa é o que
sustenta a separação. Uma quarta guarda que aceita todas não a enfraquece **porque não
serve dado**; o que ela faz é dizer quem está falando.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import ALGORITMO
from app.models.user import User
from app.services import pessoas

router = APIRouter(prefix="/api/sessao", tags=["sessão · papéis"])

_bearer = HTTPBearer(auto_error=False)


def sessao_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Quem está falando, venha do portão que vier. Não autoriza nada por si."""
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO])
        usuario = db.get(User, int(dados["sub"]))
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc

    if usuario is None or not usuario.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")
    return usuario


class ContaOut(BaseModel):
    apelido: str
    nome: str
    #: `painel`, `empresa` ou `cliente` — o portão que esta conta abre.
    escopo: str
    perfil: str
    empresa: str | None = None
    #: A conta desta sessão.
    atual: bool = False
    #: Trocar para esta conta exige a senha dela. Verdadeiro nas contas da PLATAFORMA:
    #: sem isso, uma sessão de aplicativo roubada viraria sessão de administrador sem
    #: ninguém precisar saber nenhuma senha.
    exige_senha: bool = False


@router.get("/papeis", response_model=list[ContaOut])
def papeis(
    db: Session = Depends(get_db), usuario: User = Depends(sessao_atual)
) -> list[ContaOut]:
    """Os papéis desta pessoa. Sem agrupamento, devolve só o papel atual."""
    return [
        ContaOut(
            apelido=c.apelido,
            nome=c.nome,
            escopo=pessoas.escopo_do_perfil(c.perfil),
            perfil=c.perfil.value,
            empresa=pessoas.nome_da_empresa(db, c),
            atual=c.id == usuario.id,
            exige_senha=c.perfil in pessoas.DA_PLATAFORMA,
        )
        for c in pessoas.contas_da_pessoa(db, usuario)
    ]


class TrocaIn(BaseModel):
    apelido: str
    #: Só quando o destino é da plataforma. Ver a regra em `services/pessoas`.
    senha: str | None = None


class TrocaOut(BaseModel):
    token: str
    expira_em: datetime
    apelido: str
    nome: str
    escopo: str
    perfil: str
    empresa: str | None = None


@router.post("/trocar", response_model=TrocaOut)
def trocar(
    body: TrocaIn, db: Session = Depends(get_db), usuario: User = Depends(sessao_atual)
) -> TrocaOut:
    """Emite a sessão do outro papel da MESMA pessoa.

    A sessão anterior não é invalidada: as duas valem até expirar, cada uma no portão
    dela. Derrubá-la seria impedir o caso que motivou tudo isto — o painel da plataforma
    aberto numa aba e o da empresa em outra.
    """
    destino = pessoas.trocar(db, usuario, body.apelido, body.senha)
    token, expira = pessoas.emitir(destino)
    return TrocaOut(
        token=token,
        expira_em=expira,
        apelido=destino.apelido,
        nome=destino.nome,
        escopo=pessoas.escopo_do_perfil(destino.perfil),
        perfil=destino.perfil.value,
        empresa=pessoas.nome_da_empresa(db, destino),
    )
