"""Os contatos de uma usina — quem mais recebe aviso, além do dono da conta.

Substitui o "avise no grupo do cliente", que a API oficial do WhatsApp não permite. Cada
pessoa cadastrada aqui recebe no privado, com o seu próprio aceite e as suas próprias
escolhas — e é isso que mantém o log respondendo por pessoa.

**Aceite é por contato, e o gestor registra.** A autorização é a mesma do cliente: a
cláusula do contrato, ou o "pode mandar no meu WhatsApp" dito por quem vai receber. Herdar
o aceite do dono da conta colocaria mensagem no telefone de terceiro sem ninguém ter dito
que podia.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import exige_area
from app.core.telefone import TelefoneInvalido, exibir
from app.core.telefone import normalizar as normalizar_telefone
from app.models.contato import ContatoPreferencia, ContatoUsina
from app.models.plant import PlantLink
from app.models.user import User
from app.services import notificacoes as catalogo

router = APIRouter(prefix="/api/painel", tags=["painel · contatos da usina"])

EXIGE_NOTIFICACOES = exige_area("notificacoes")


class ContatoOut(BaseModel):
    id: int
    plant_link_id: int
    nome: str
    telefone: str
    telefone_exibicao: str
    papel: str | None = None
    ativo: bool
    aceite_em: datetime | None = None
    #: Os tipos que este contato recebe.
    tipos: list[str] = []
    #: `None` quando está tudo certo; senão, a frase do que falta resolver.
    impedimento: str | None = None


def _out(c: ContatoUsina) -> ContatoOut:
    return ContatoOut(
        id=c.id,
        plant_link_id=c.plant_link_id,
        nome=c.nome,
        telefone=c.telefone,
        telefone_exibicao=exibir(c.telefone) or c.telefone,
        papel=c.papel,
        ativo=c.ativo,
        aceite_em=c.aceite_em,
        tipos=sorted(p.tipo for p in c.preferencias),
        impedimento=c.motivo_de_nao_receber,
    )


def _usina(db: Session, usina_id: int) -> PlantLink:
    usina = db.get(PlantLink, usina_id)
    if usina is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")
    return usina


def _contato(db: Session, contato_id: int) -> ContatoUsina:
    c = db.get(ContatoUsina, contato_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contato não encontrado.")
    return c


@router.get("/usinas/{usina_id}/contatos", response_model=list[ContatoOut])
def listar(
    usina_id: int, db: Session = Depends(get_db), _: User = Depends(EXIGE_NOTIFICACOES)
) -> list[ContatoOut]:
    _usina(db, usina_id)
    contatos = db.scalars(
        select(ContatoUsina)
        .where(ContatoUsina.plant_link_id == usina_id)
        .order_by(ContatoUsina.nome)
    ).all()
    return [_out(c) for c in contatos]


class ContatoIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    telefone: str = Field(min_length=8)
    papel: str | None = Field(default=None, max_length=60)
    #: Marcar o aceite já na criação é o caso comum: o gestor cadastra depois de a pessoa
    #: autorizar, ao telefone. Sem ele o contato entra mudo, e a tela diz o que falta.
    aceite: bool = False
    tipos: list[str] = []


def _definir_tipos(db: Session, contato: ContatoUsina, tipos: list[str]) -> None:
    desejados = set(tipos)
    desconhecidos = desejados - set(catalogo.TIPOS)
    if desconhecidos:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Tipo de notificação desconhecido: {', '.join(sorted(desconhecidos))}.",
        )
    atuais = {p.tipo: p for p in contato.preferencias}
    for tipo, linha in atuais.items():
        if tipo not in desejados:
            db.delete(linha)
    for tipo in desejados - set(atuais):
        db.add(ContatoPreferencia(contato_id=contato.id, tipo=tipo))


@router.post("/usinas/{usina_id}/contatos", response_model=ContatoOut, status_code=201)
def criar(
    usina_id: int,
    corpo: ContatoIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_NOTIFICACOES),
) -> ContatoOut:
    _usina(db, usina_id)
    try:
        telefone = normalizar_telefone(corpo.telefone)
    except TelefoneInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    existente = db.scalar(
        select(ContatoUsina).where(
            ContatoUsina.plant_link_id == usina_id, ContatoUsina.telefone == telefone
        )
    )
    if existente is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Este telefone já está cadastrado nesta usina, como “{existente.nome}”.",
        )

    contato = ContatoUsina(
        plant_link_id=usina_id,
        nome=corpo.nome.strip(),
        telefone=telefone,
        papel=(corpo.papel or "").strip() or None,
        criado_por=gestor.id,
        aceite_em=datetime.now(UTC) if corpo.aceite else None,
        aceite_por=gestor.id if corpo.aceite else None,
    )
    db.add(contato)
    db.commit()
    db.refresh(contato)

    _definir_tipos(db, contato, corpo.tipos)
    db.commit()
    db.refresh(contato)
    return _out(contato)


class ContatoPatch(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=120)
    telefone: str | None = None
    papel: str | None = None
    ativo: bool | None = None
    aceite: bool | None = None
    #: A lista COMPLETA. Ausente não mexe; vazia desliga tudo.
    tipos: list[str] | None = None


@router.patch("/contatos/{contato_id}", response_model=ContatoOut)
def editar(
    contato_id: int,
    corpo: ContatoPatch,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_NOTIFICACOES),
) -> ContatoOut:
    contato = _contato(db, contato_id)

    if corpo.nome is not None:
        contato.nome = corpo.nome.strip()
    if corpo.papel is not None:
        contato.papel = corpo.papel.strip() or None
    if corpo.ativo is not None:
        contato.ativo = corpo.ativo
    if corpo.telefone is not None:
        try:
            contato.telefone = normalizar_telefone(corpo.telefone)
        except TelefoneInvalido as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if corpo.aceite is not None:
        # Desmarcar é caminho legítimo: quem pede para sair para de receber sem perder o
        # que escolheu, e volta a receber se autorizar de novo.
        contato.aceite_em = datetime.now(UTC) if corpo.aceite else None
        contato.aceite_por = gestor.id if corpo.aceite else None
    if corpo.tipos is not None:
        _definir_tipos(db, contato, corpo.tipos)

    db.commit()
    db.refresh(contato)
    return _out(contato)


@router.delete("/contatos/{contato_id}", status_code=204)
def remover(
    contato_id: int, db: Session = Depends(get_db), _: User = Depends(EXIGE_NOTIFICACOES)
) -> None:
    """Apaga o contato e o que ele escolhia. O log do que já foi enviado permanece.

    Desativar (`ativo: false`) é o caminho usual — apagar some com a pessoa da tela, e o
    histórico de quem recebeu o quê continua respondendo pelo `destino` gravado na linha.
    """
    db.delete(_contato(db, contato_id))
    db.commit()
