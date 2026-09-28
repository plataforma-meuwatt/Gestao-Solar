"""Empresas de O&M — a tela da PLATAFORMA que cria e desliga inquilino.

Fica em `/api/painel/*` porque é da plataforma: quem abre isto vê a lista inteira de
empresas, e nenhuma delas deve saber que as outras existem. A área é `empresas`, do grupo
Sistema, pelo mesmo motivo de `conexoes`: criar inquilino é decisão de quem administra.

**Desligar, não apagar.** `ativa=false` tira a empresa de operação — o gerente dela para
de entrar na requisição seguinte — e preserva usina, cliente e histórico. Apagar levaria
junto o que alguém ainda precisa auditar, e a chave estrangeira é `RESTRICT` justamente
para o banco recusar a tentativa em vez de arrastar o resto.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import exige_area
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import empresas as svc

router = APIRouter(prefix="/api/painel", tags=["painel · empresas"])

EXIGE_EMPRESAS = exige_area("empresas")


class EmpresaOut(BaseModel):
    id: int
    nome: str
    documento: str | None = None
    ativa: bool
    #: Contagens para a lista responder "posso desligar?" sem abrir a empresa.
    usuarios: int = 0
    usinas: int = 0


def _saida(db: Session, e: Empresa) -> EmpresaOut:
    return EmpresaOut(
        id=e.id,
        nome=e.nome,
        documento=e.documento,
        ativa=e.ativa,
        usuarios=db.scalar(
            select(func.count()).select_from(User).where(User.empresa_id == e.id)
        )
        or 0,
        usinas=db.scalar(
            select(func.count()).select_from(PlantLink).where(PlantLink.empresa_id == e.id)
        )
        or 0,
    )


@router.get("/empresas", response_model=list[EmpresaOut])
def listar(
    db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> list[EmpresaOut]:
    empresas = db.scalars(select(Empresa).order_by(Empresa.nome)).all()
    return [_saida(db, e) for e in empresas]


class EmpresaIn(BaseModel):
    nome: str
    documento: str | None = None


@router.post("/empresas", response_model=EmpresaOut, status_code=201)
def criar(
    body: EmpresaIn, db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> EmpresaOut:
    empresa = svc.criar(db, body.nome, body.documento)
    db.commit()
    return _saida(db, empresa)


class EmpresaPatch(BaseModel):
    nome: str | None = None
    documento: str | None = None
    ativa: bool | None = None


@router.patch("/empresas/{empresa_id}", response_model=EmpresaOut)
def editar(
    empresa_id: int,
    body: EmpresaPatch,
    db: Session = Depends(get_db),
    _gestor: User = Depends(EXIGE_EMPRESAS),
) -> EmpresaOut:
    empresa = svc.por_id(db, empresa_id)
    if body.nome is not None:
        empresa.nome = body.nome.strip() or empresa.nome
    if body.documento is not None:
        empresa.documento = body.documento.strip() or None
    if body.ativa is not None:
        empresa.ativa = body.ativa
    db.commit()
    return _saida(db, empresa)


# ------------------------------------------------------------------- carteira


class ItemDaCarteira(BaseModel):
    id: int
    nome: str
    detalhe: str | None = None
    #: De qual empresa é hoje. `null` = de ninguém — o estado de tudo o que existia antes
    #: do multiempresa, e o motivo de esta tela existir.
    empresa_id: int | None = None
    empresa_nome: str | None = None


class CarteiraOut(BaseModel):
    usinas: list[ItemDaCarteira]
    clientes: list[ItemDaCarteira]


def _nomes(db: Session) -> dict[int, str]:
    return {e.id: e.nome for e in db.scalars(select(Empresa)).all()}


@router.get("/empresas/{empresa_id}/carteira", response_model=CarteiraOut)
def carteira(
    empresa_id: int, db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> CarteiraOut:
    """Tudo o que PODE ser atribuído, com o dono atual de cada item ao lado.

    A lista é a do sistema inteiro, e não só a desta empresa, porque a pergunta que a tela
    responde é "de quem é o quê" — e mostrar apenas o que já é dela esconderia exatamente
    o que falta atribuir. O dono atual vem escrito: mudar usina de empresa é uma decisão,
    não um clique distraído.

    # ponytail: carrega tudo de uma vez. Com 17 usinas e 7 clientes é uma consulta; se um
    # dia forem milhares, isto vira busca paginada — e aí a tela também muda.
    """
    svc.por_id(db, empresa_id)  # 404 se a empresa não existe
    nomes = _nomes(db)

    usinas = [
        ItemDaCarteira(
            id=u.id,
            nome=u.nome,
            detalhe=" · ".join(p for p in (u.cidade, u.uf) if p) or None,
            empresa_id=u.empresa_id,
            empresa_nome=nomes.get(u.empresa_id) if u.empresa_id else None,
        )
        for u in db.scalars(select(PlantLink).order_by(PlantLink.nome)).all()
    ]
    clientes = [
        ItemDaCarteira(
            id=c.id,
            nome=c.nome,
            detalhe=c.apelido,
            empresa_id=c.empresa_id,
            empresa_nome=nomes.get(c.empresa_id) if c.empresa_id else None,
        )
        for c in db.scalars(
            select(User).where(User.perfil.in_([Perfil.CLIENTE, Perfil.GESTOR_EMPRESA])).order_by(User.nome)
        ).all()
    ]
    return CarteiraOut(usinas=usinas, clientes=clientes)


class CarteiraIn(BaseModel):
    #: As listas COMPLETAS do que passa a ser desta empresa. O que sai delas fica **sem
    #: dono** — e não volta para outra empresa por conta própria, porque adivinhar o
    #: destino de um item removido seria decidir no lugar de quem decide.
    usinas: list[int]
    clientes: list[int]


@router.put("/empresas/{empresa_id}/carteira", response_model=CarteiraOut)
def salvar_carteira(
    empresa_id: int,
    body: CarteiraIn,
    db: Session = Depends(get_db),
    _gestor: User = Depends(EXIGE_EMPRESAS),
) -> CarteiraOut:
    """Grava de quem é o quê.

    Duas regras que não devem ser "simplificadas":

    - **Só mexe no que é desta empresa ou de ninguém.** Um item que pertence a OUTRA
      empresa é ignorado em silêncio, e é assim de propósito: a tela mostra o dono atual
      ao lado de cada linha, então marcar o item de outro é engano, e um engano não pode
      transferir carteira. Para mudar de dono, tira-se lá e põe-se aqui — dois passos,
      duas decisões.
    - **Tirar da lista deixa sem dono, não em outra empresa.** É reversível e visível: o
      item volta a aparecer como "de ninguém" na próxima abertura da tela.
    """
    svc.por_id(db, empresa_id)

    for modelo, coluna, escolhidos in (
        (PlantLink, PlantLink.empresa_id, set(body.usinas)),
        (User, User.empresa_id, set(body.clientes)),
    ):
        for item in db.scalars(
            select(modelo).where(coluna.is_(None) | (coluna == empresa_id))
        ).all():
            item.empresa_id = empresa_id if item.id in escolhidos else None

    db.commit()
    return carteira(empresa_id, db=db, _gestor=_gestor)
