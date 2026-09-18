"""Usuários do sistema — quem opera o painel, e o que cada um abre.

Esta é a tela do **staff**, não a de clientes: aqui nascem as contas que entram em
`/entrar` do painel, com apelido e senha. Cliente é `painel_clientes.py`, e um não vira
o outro (`POST` recusa perfil `cliente`, `PATCH` não acha quem for cliente).

**A tela inteira é de administrador**, e isso não é uma área concedível — ver o item 3 de
`services/areas_painel`: conceder "mexer em quem administra" a quem não administra é
conceder tudo, porque a pessoa se promove no primeiro clique.

O que se concede aqui são as ÁREAS de cada membro: Clientes, Usinas, Diagnóstico,
Notificações, Rotas, Conexões e WhatsApp. Administrador abre todas por perfil e não tem
linha gravada — por isso a tela desenha as caixinhas dele marcadas e desligadas, em vez
de fingir que dá para desmarcar.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.apelido import ApelidoInvalido
from app.core.apelido import normalizar as normalizar_apelido
from app.core.db import get_db
from app.core.security import administrador_atual, gerar_hash_senha
from app.models.user import Perfil, User
from app.services import areas_painel

router = APIRouter(prefix="/api/painel", tags=["painel · usuários do sistema"])


class AreaOut(BaseModel):
    chave: str
    rotulo: str
    descricao: str
    grupo: str


@router.get("/areas", response_model=list[AreaOut])
def catalogo_de_areas(_: User = Depends(administrador_atual)) -> list[AreaOut]:
    """Tudo que pode ser concedido. É a fonte das caixinhas da tela.

    Devolver o catálogo inteiro, e não só o concedido, é o que permite desenhar o que
    FALTA conceder — uma lista só do concedido não teria como mostrar o resto.
    """
    return [
        AreaOut(chave=a.chave, rotulo=a.rotulo, descricao=a.descricao, grupo=a.grupo)
        for a in areas_painel.CATALOGO
    ]


class MembroOut(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    perfil: str
    ativo: bool
    ultimo_login: datetime | None = None
    #: O que está GRAVADO para esta pessoa. Vem vazio para administrador, que abre tudo
    #: por perfil — ver o docstring do módulo.
    areas: list[str] = []


def _membro_out(db: Session, m: User) -> MembroOut:
    return MembroOut(
        id=m.id,
        nome=m.nome,
        apelido=m.apelido,
        email=m.email,
        perfil=m.perfil.value,
        ativo=m.ativo,
        ultimo_login=m.ultimo_login,
        areas=sorted(areas_painel.concedidas(db, m)),
    )


@router.get("/usuarios", response_model=list[MembroOut])
def listar(
    db: Session = Depends(get_db), _: User = Depends(administrador_atual)
) -> list[MembroOut]:
    lista = db.scalars(
        select(User).where(User.perfil != Perfil.CLIENTE).order_by(User.nome)
    ).all()
    return [_membro_out(db, m) for m in lista]


class MembroIn(BaseModel):
    nome: str = Field(min_length=2)
    apelido: str = Field(min_length=3)
    email: EmailStr | None = None
    perfil: Perfil = Perfil.ATENDIMENTO
    senha: str = Field(min_length=8)
    #: Com o que a pessoa já nasce podendo abrir. Vazio é o padrão e é honesto: conta nova
    #: sem área entra no painel e não vê nada além do aviso de que falta acesso — melhor
    #: do que herdar em silêncio o que o último membro tinha.
    areas: list[str] = []


@router.post("/usuarios", response_model=MembroOut, status_code=201)
def criar(
    body: MembroIn,
    db: Session = Depends(get_db),
    admin: User = Depends(administrador_atual),
) -> MembroOut:
    if body.perfil is Perfil.CLIENTE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Use a tela de clientes para criar um cliente."
        )
    try:
        apelido = normalizar_apelido(body.apelido)
    except ApelidoInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if db.scalar(select(User).where(User.apelido == apelido)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"O apelido “{apelido}” já está em uso."
        )

    membro = User(
        apelido=apelido,
        email=str(body.email).strip().lower() if body.email else None,
        nome=body.nome.strip(),
        perfil=body.perfil,
        senha_hash=gerar_hash_senha(body.senha),
    )
    db.add(membro)
    db.flush()

    if body.areas:
        try:
            areas_painel.definir(db, membro, set(body.areas), admin)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    db.commit()
    db.refresh(membro)
    return _membro_out(db, membro)


class MembroPatch(BaseModel):
    perfil: Perfil | None = None
    ativo: bool | None = None
    #: A lista COMPLETA de áreas, não um acréscimo: o que não vier é revogado. É o mesmo
    #: contrato da tela de permissões do cliente — a tela manda o estado das caixinhas.
    #: Ausente (`None`) não mexe em acesso nenhum.
    areas: list[str] | None = None


@router.patch("/usuarios/{membro_id}", response_model=MembroOut)
def editar(
    membro_id: int,
    body: MembroPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(administrador_atual),
) -> MembroOut:
    membro = db.get(User, membro_id)
    if membro is None or membro.perfil is Perfil.CLIENTE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")

    # Rebaixar ou desativar a si mesmo tranca o painel para fora — e se for o último
    # administrador, tranca para todo mundo.
    if membro.id == admin.id and (body.ativo is False or body.perfil is Perfil.ATENDIMENTO):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Você não pode remover o próprio acesso de administrador.",
        )

    if body.perfil is not None:
        membro.perfil = body.perfil
    if body.ativo is not None:
        membro.ativo = body.ativo

    if body.areas is not None:
        try:
            areas_painel.definir(db, membro, set(body.areas), admin)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    restantes = db.scalar(
        select(User).where(
            User.perfil == Perfil.ADMINISTRADOR, User.ativo, User.id != membro.id
        )
    )
    if restantes is None and membro.perfil is not Perfil.ADMINISTRADOR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Precisa sobrar ao menos um administrador ativo.",
        )

    db.commit()
    db.refresh(membro)
    return _membro_out(db, membro)
