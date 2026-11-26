"""O índice de dispositivos pela porta da máquina (guarda-chuva, fase 2, 26/11/2026): o servidor do sistema manda, só
com a chave dele (`X-Sistema` + `X-Chave-Interna`, sem pessoa), a lista INTEIRA das posições de equipamento de uma
usina ligada a ele, e recebe de volta o número de cada uma no GS (`GD-000123`) para guardar ao lado do registro dele.

É a única ESCRITA que a chave faz sozinha, e é estreita de propósito: o sistema grava só as referências DELE de
dispositivo, só nas usinas ligadas a ele, nunca um dado da usina e nunca a referência de outro sistema. A regra da
lista (o que nasce, o que muda, o que fica ausente, o que recusa) está em `services/dispositivos.py`.

- `PUT /maquina/usinas/{gs}/dispositivos`: a lista inteira. Idempotente: a mesma lista de novo não muda nada.
- `GET /maquina/usinas/{gs}/dispositivos`: o que o GS guarda daquela usina para o sistema que chama, com os ausentes.

Nesta fase só o meuWatt (transformadores e inversores). Uma linha no Registro de acessos por sistema, usina e hora.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.interno_sistemas import _NAO, NOMES, REFERENCIA, codigo, codigo_do_dispositivo, sistema
from app.core.db import get_db
from app.models.plant import DeviceLink, PlantLink
from app.services import acessos, dispositivos

router = APIRouter(prefix="/api/v1/interno/maquina", tags=["interno · sistemas da família"])


class DispositivoIn(BaseModel):
    model_config = {"extra": "forbid"}
    #: a referência no sistema que manda, na grafia padrão (`trafo:41`, `inv:99`)
    ref: str = Field(max_length=60)
    tipo: str = Field(max_length=20)
    #: o rótulo que o sistema usa ("TR-01", "INV12")
    nome: str = Field(max_length=160)
    #: a referência do dispositivo acima, da MESMA lista (o transformador do inversor), ou nulo
    pai: str | None = Field(default=None, max_length=60)

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("o dispositivo precisa de um nome")
        return v


class ListaIn(BaseModel):
    model_config = {"extra": "forbid"}
    dispositivos: list[DispositivoIn] = Field(max_length=dispositivos.TETO)


class RefDoDispositivo(BaseModel):
    ref: str | int


class DispositivoOut(BaseModel):
    #: o número do dispositivo no GS
    gd: int
    codigo: str
    tipo: str
    nome: str
    #: o `gd` do dispositivo acima, ou nulo
    pai: int | None
    #: falso = não veio na última lista (a linha fica, com o mesmo número)
    ativo: bool
    #: a referência no sistema que chama, no campo dele (só a dele)
    meuwatt: RefDoDispositivo | None = None
    meuplano: RefDoDispositivo | None = None
    termovision: RefDoDispositivo | None = None


class DispositivosOut(BaseModel):
    dispositivos: list[DispositivoOut]


class GravadosOut(DispositivosOut):
    #: o que ESTE pedido fez: os que ganharam número, os que mudaram (nome, tipo, pai, ou voltaram) e os que ficaram
    #: ausentes agora
    criados: int
    alterados: int
    ausentes: int


def _usina(db: Session, request: Request, gs: int) -> tuple[str, PlantLink]:
    """Quem chama (pela chave) e a usina, que tem de estar ligada a ELE. A que não existe e a que não é dele respondem
    igual (a porta não confirma o que existe)."""
    quem = sistema(request)
    if quem not in REFERENCIA:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este sistema usa as usinas do GS: não tem usina ligada a ele.")
    if quem not in dispositivos.GRAFIA:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"O índice de dispositivos ainda não recebe do {NOMES[quem]}: por enquanto, só do meuWatt.")
    usina = db.get(PlantLink, gs)
    if usina is None or getattr(usina, REFERENCIA[quem]) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    return quem, usina


def _saida(quem: str, linhas: list[DeviceLink]) -> list[DispositivoOut]:
    campo = dispositivos.REFERENCIA[quem]
    return [DispositivoOut(gd=x.id, codigo=codigo_do_dispositivo(x.id), tipo=x.tipo, nome=x.nome, pai=x.pai_id,
                           ativo=bool(x.ativo), **{quem: RefDoDispositivo(ref=getattr(x, campo))}) for x in linhas]


@router.get("/usinas/{gs}/dispositivos", response_model=DispositivosOut, response_model_exclude_unset=True)
def dispositivos_da_usina(gs: int, request: Request, db: Session = Depends(get_db)) -> DispositivosOut:
    quem, usina = _usina(db, request, gs)
    acessos.registrar(db, request, acao="leitura", sistema=quem, agrupar_s=3600,
                      motivo=f"{NOMES[quem]} leu pela porta da máquina (só a chave, sem pessoa): os dispositivos da "
                             f"usina {codigo(usina.id)}")
    return DispositivosOut(dispositivos=_saida(quem, dispositivos.da_usina(db, quem, usina)))


@router.put("/usinas/{gs}/dispositivos", response_model=GravadosOut, response_model_exclude_unset=True)
def gravar_dispositivos(gs: int, body: ListaIn, request: Request, db: Session = Depends(get_db)) -> GravadosOut:
    quem, usina = _usina(db, request, gs)
    itens = [d.model_dump() for d in body.dispositivos]
    try:
        dispositivos.conferir(quem, itens)
    except dispositivos.ListaInvalida as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    acessos.registrar(db, request, acao="gravacao", sistema=quem, agrupar_s=3600,
                      motivo=f"{NOMES[quem]} gravou pela porta da máquina (só a chave, sem pessoa): os dispositivos da "
                             f"usina {codigo(usina.id)}")
    try:
        feito = dispositivos.gravar(db, quem, usina, itens)
        db.commit()
    except dispositivos.DeOutraUsina as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IntegrityError:                                 # a mesma referência nasceu em outro pedido, agora
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Outro pedido gravou os mesmos dispositivos agora: nada foi gravado, mande de novo.") from None
    return GravadosOut(dispositivos=_saida(quem, dispositivos.da_usina(db, quem, usina)), **feito)
