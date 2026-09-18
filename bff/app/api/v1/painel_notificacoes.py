"""A central de notificações, no painel do gestor.

Uma tela responde três perguntas que andam juntas: **para onde** (telefone e aceite),
**o quê e de qual usina** (a matriz tipo × usinas) e **o que já saiu** (o histórico).
Separá-las em páginas faria o gestor marcar o aviso e esquecer o telefone — e o cliente
ficaria com tudo configurado e nada chegando.

O envio não mora aqui. Esta central grava a decisão; quem entrega é o motor, quando o
gateway de WhatsApp existir. Até lá a matriz é a verdade do que vai sair, e o histórico
abre vazio — que é honesto: nada foi enviado ainda.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import exige_area
from app.core.telefone import TelefoneInvalido
from app.core.telefone import e_celular, exibir
from app.core.telefone import normalizar as normalizar_telefone
from app.models.user import Perfil, User
from app.services import notificacoes as svc

router = APIRouter(prefix="/api/painel", tags=["painel · notificações"])

#: A central é do CLIENTE — contato, aceite e o que ele recebe. O número da empresa, por
#: onde tudo isso sai, é outra área (`whatsapp`) e outra tela.
EXIGE_NOTIFICACOES = exige_area("notificacoes")


def _cliente(db: Session, cliente_id: int) -> User:
    usuario = db.get(User, cliente_id)
    if usuario is None or usuario.perfil is not Perfil.CLIENTE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado")
    return usuario


# ── formato ─────────────────────────────────────────────────────────────────


class UsinaMarcada(BaseModel):
    plant_link_id: int
    nome: str
    marcada: bool


class TipoOut(BaseModel):
    tipo: str
    rotulo: str
    descricao: str
    origem: str
    usinas: list[UsinaMarcada] = []


class ContatoOut(BaseModel):
    """Para onde vai, e se pode ir."""

    telefone: str | None = None
    #: O mesmo número em formato de leitura — a tela não mostra E.164 cru.
    telefone_exibicao: str | None = None
    #: Fixo cadastrado é telefone legítimo e não recebe WhatsApp. A tela avisa antes.
    e_celular: bool = False
    aceite_em: datetime | None = None
    aceite_por: str | None = None
    #: Sem impedimento nenhum, este cliente receberia o que estiver marcado.
    apto: bool = False
    #: A frase do que falta, quando falta. `None` quando está apto.
    impedimento: str | None = None


class CentralOut(BaseModel):
    cliente: str
    contato: ContatoOut
    tipos: list[TipoOut]
    #: Quantos pares (tipo × usina) estão marcados — o número do título do cartão.
    marcados: int = 0
    #: O cliente sem usina concedida não tem o que marcar; a tela diz isso em vez de
    #: desenhar seis linhas vazias.
    sem_usinas: bool = False


class ParIn(BaseModel):
    tipo: str
    plant_link_id: int


class PreferenciasIn(BaseModel):
    #: A lista COMPLETA do que deve ficar marcado. Substituição, não acréscimo.
    itens: list[ParIn] = []


class ContatoIn(BaseModel):
    #: Texto livre: o gestor digita como quiser e o servidor normaliza. `null` apaga.
    telefone: str | None = Field(default=None)
    #: `true` registra o aceite (com data e autor); `false` retira.
    aceite: bool | None = None


class EnvioOut(BaseModel):
    tipo: str
    tipo_rotulo: str
    usina: str | None = None
    destino: str | None = None
    status: str
    erro: str | None = None
    criada_em: datetime


# ── leitura ─────────────────────────────────────────────────────────────────


@router.get("/notificacoes/catalogo", response_model=list[TipoOut])
def catalogo(_: User = Depends(EXIGE_NOTIFICACOES)) -> list[TipoOut]:
    """Os tipos que existem, sem cliente nenhum — é o que a tela usa para explicar."""
    return [
        TipoOut(tipo=t.tipo, rotulo=t.rotulo, descricao=t.descricao, origem=t.origem)
        for t in svc.CATALOGO
    ]


@router.get("/clientes/{cliente_id}/notificacoes", response_model=CentralOut)
def central_do_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(EXIGE_NOTIFICACOES),
) -> CentralOut:
    """A matriz inteira: todo tipo × toda usina do cliente, marcando o que está ligado.

    Devolve o catálogo completo, e não só o marcado, pelo mesmo motivo das permissões: uma
    lista do que já está ligado não teria como desenhar o que falta ligar.
    """
    cliente = _cliente(db, cliente_id)
    usinas = svc.usinas_do_cliente(db, cliente)
    ligadas = svc.marcadas(db, cliente)

    autor = db.get(User, cliente.whatsapp_aceite_por) if cliente.whatsapp_aceite_por else None

    return CentralOut(
        cliente=cliente.nome,
        contato=ContatoOut(
            telefone=cliente.telefone,
            telefone_exibicao=exibir(cliente.telefone),
            e_celular=bool(cliente.telefone) and e_celular(cliente.telefone),
            aceite_em=cliente.whatsapp_aceite_em,
            aceite_por=autor.nome if autor else None,
            apto=svc.apto(cliente),
            impedimento=svc.motivo_de_nao_receber(cliente),
        ),
        tipos=[
            TipoOut(
                tipo=t.tipo,
                rotulo=t.rotulo,
                descricao=t.descricao,
                origem=t.origem,
                usinas=[
                    UsinaMarcada(
                        plant_link_id=u.id,
                        nome=u.nome,
                        marcada=(t.tipo, u.id) in ligadas,
                    )
                    for u in usinas
                ],
            )
            for t in svc.CATALOGO
        ],
        marcados=len(ligadas),
        sem_usinas=not usinas,
    )


@router.get("/clientes/{cliente_id}/notificacoes/historico", response_model=list[EnvioOut])
def historico(
    cliente_id: int,
    limite: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(EXIGE_NOTIFICACOES),
) -> list[EnvioOut]:
    """O que já saiu para este cliente. Vazio enquanto o envio não existir."""
    cliente = _cliente(db, cliente_id)
    return [
        EnvioOut(
            tipo=e.tipo,
            tipo_rotulo=svc.TIPOS[e.tipo].rotulo if e.tipo in svc.TIPOS else e.tipo,
            usina=e.usina.nome if e.usina else None,
            destino=exibir(e.destino),
            status=e.status,
            erro=e.erro,
            criada_em=e.criada_em,
        )
        for e in svc.historico(db, cliente, min(max(limite, 1), 200))
    ]


# ── escrita ─────────────────────────────────────────────────────────────────


@router.patch("/clientes/{cliente_id}/notificacoes/contato", response_model=ContatoOut)
def salvar_contato(
    cliente_id: int,
    corpo: ContatoIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_NOTIFICACOES),
) -> ContatoOut:
    """Telefone e aceite — as duas coisas sem as quais nada sai.

    O telefone é normalizado aqui, uma vez (`core/telefone.py`), e não em cada tela: dois
    lugares normalizando é o caminho para o mesmo número virar dois destinos diferentes.
    """
    cliente = _cliente(db, cliente_id)

    # `model_fields_set`: distinguir "não mandou o campo" de "mandou null para apagar" —
    # sem isso, salvar só o aceite apagaria o telefone.
    if "telefone" in corpo.model_fields_set:
        try:
            cliente.telefone = normalizar_telefone(corpo.telefone)
        except TelefoneInvalido as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if corpo.aceite is not None:
        svc.registrar_aceite(db, cliente, aceito=corpo.aceite, por=gestor)
    else:
        db.commit()

    autor = db.get(User, cliente.whatsapp_aceite_por) if cliente.whatsapp_aceite_por else None
    return ContatoOut(
        telefone=cliente.telefone,
        telefone_exibicao=exibir(cliente.telefone),
        e_celular=bool(cliente.telefone) and e_celular(cliente.telefone),
        aceite_em=cliente.whatsapp_aceite_em,
        aceite_por=autor.nome if autor else None,
        apto=svc.apto(cliente),
        impedimento=svc.motivo_de_nao_receber(cliente),
    )


@router.put("/clientes/{cliente_id}/notificacoes", status_code=204)
def definir_preferencias(
    cliente_id: int,
    corpo: PreferenciasIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_NOTIFICACOES),
) -> None:
    """Substitui a matriz do cliente pelo que a tela enviou."""
    cliente = _cliente(db, cliente_id)
    try:
        svc.definir(
            db,
            cliente,
            [(i.tipo, i.plant_link_id) for i in corpo.itens],
            por=gestor,
        )
    except svc.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
