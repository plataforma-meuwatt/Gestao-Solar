"""O índice de dispositivos pela porta da máquina (guarda-chuva, fase 2, 26/11/2026): o servidor do sistema manda, só
com a chave dele (`X-Sistema` + `X-Chave-Interna`, sem pessoa), a lista INTEIRA das posições de equipamento de uma
usina ligada a ele, e recebe de volta o número de cada uma no GS (`GD-000123`) para guardar ao lado do registro dele.

É a única ESCRITA que a chave faz sozinha, e é estreita de propósito: o sistema grava só as referências DELE de
dispositivo, só nas usinas ligadas a ele, nunca um dado da usina e nunca a referência de outro sistema. A regra da
lista (o que nasce, o que muda, o que fica ausente, o que recusa) está em `services/dispositivos.py`.

- `PUT /maquina/usinas/{gs}/dispositivos`: a lista inteira. Idempotente: a mesma lista de novo não muda nada.
- `GET /maquina/usinas/{gs}/dispositivos`: o que o GS guarda daquela usina para o sistema que chama, com os ausentes.

- `PUT /maquina/usinas/{gs}/dispositivos/nos`: o meuPlano liga os nós dele aos dispositivos que já existem (não cria
  dispositivo), pela referência padrão. Grava só a coluna DELE (`mp_node_id`).

Quem manda a lista é só o meuWatt (transformadores e inversores); quem liga nós é só o meuPlano; os dois leem. Uma
linha no Registro de acessos por sistema, usina e hora.
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


class NoDoMeuPlano(BaseModel):
    node_id: int


class NoIn(BaseModel):
    model_config = {"extra": "forbid"}
    #: o dispositivo, pela referência padrão (`inv:99`, `trafo:41`)
    ref: str = Field(max_length=60)
    #: o `nodes.id` do meuPlano naquela posição; nulo desliga
    node_id: int | None = Field(ge=1, le=2_147_483_647)


class NosIn(BaseModel):
    model_config = {"extra": "forbid"}
    nos: list[NoIn] = Field(max_length=dispositivos.TETO)


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
    #: para o meuWatt, só a referência dele. Para o meuPlano, as duas: a do meuWatt (a chave comum, que ele mandou) e o
    #: nó dele, nulo quando a posição ainda não tem nó
    meuwatt: RefDoDispositivo | None = None
    meuplano: NoDoMeuPlano | None = None


class DispositivosOut(BaseModel):
    dispositivos: list[DispositivoOut]


class GravadosOut(DispositivosOut):
    #: o que ESTE pedido fez: os que ganharam número, os que mudaram (nome, tipo, pai, ou voltaram) e os que ficaram
    #: ausentes agora
    criados: int
    alterados: int
    ausentes: int


class NosLigadosOut(DispositivosOut):
    #: o que ESTE pedido fez: os dispositivos que ganharam (ou trocaram de) nó e os que perderam o nó
    ligados: int
    desligados: int
    #: as referências do pedido que não são de dispositivo desta usina (não é erro: ficam sem nó)
    sem_dispositivo: list[str]


def _usina(db: Session, request: Request, gs: int, abertos: tuple[str, ...], recusa: str) -> tuple[str, PlantLink]:
    """Quem chama (pela chave), que tem de ser um dos `abertos` (senão 403 com a `recusa`), e a usina, que tem de estar
    ligada a ELE. A que não existe e a que não é dele respondem igual (a porta não confirma o que existe)."""
    quem = sistema(request)
    if quem not in REFERENCIA:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este sistema usa as usinas do GS: não tem usina ligada a ele.")
    if quem not in abertos:
        raise HTTPException(status.HTTP_403_FORBIDDEN, recusa.format(nome=NOMES[quem]))
    usina = db.get(PlantLink, gs)
    if usina is None or getattr(usina, REFERENCIA[quem]) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    return quem, usina


#: as recusas (403) de quem tem usina no GS mas não entra naquela rota
_AINDA_NAO = "O índice de dispositivos ainda não recebe do {nome}: por enquanto, só do meuWatt."
_SO_O_MEUPLANO = "Quem liga nós aos dispositivos é o meuPlano: o {nome} não tem nó a ligar."


def _saida(db: Session, quem: str, usina: PlantLink) -> list[DispositivoOut]:
    """Para o meuWatt, os dispositivos com referência dele, e só ela. Para o meuPlano, TODOS os da usina (para ele
    guardar o número do GS em cada nó e ver o que ainda está sem nó), com a referência do meuWatt e o nó dele."""
    def comum(x: DeviceLink) -> dict:
        return dict(gd=x.id, codigo=codigo_do_dispositivo(x.id), tipo=x.tipo, nome=x.nome, pai=x.pai_id,
                    ativo=bool(x.ativo))
    if quem in dispositivos.LIGA_NOS:
        return [DispositivoOut(**comum(x), meuwatt=RefDoDispositivo(ref=x.mw_ref) if x.mw_ref else None,
                               meuplano=NoDoMeuPlano(node_id=x.mp_node_id) if x.mp_node_id is not None else None)
                for x in dispositivos.todos_da_usina(db, usina)]
    campo = dispositivos.REFERENCIA[quem]
    return [DispositivoOut(**comum(x), **{quem: RefDoDispositivo(ref=getattr(x, campo))})
            for x in dispositivos.da_usina(db, quem, usina)]


@router.get("/usinas/{gs}/dispositivos", response_model=DispositivosOut, response_model_exclude_unset=True)
def dispositivos_da_usina(gs: int, request: Request, db: Session = Depends(get_db)) -> DispositivosOut:
    quem, usina = _usina(db, request, gs, (*dispositivos.GRAFIA, *dispositivos.LIGA_NOS), _AINDA_NAO)
    acessos.registrar(db, request, acao="leitura", sistema=quem, agrupar_s=3600,
                      motivo=f"{NOMES[quem]} leu pela porta da máquina (só a chave, sem pessoa): os dispositivos da "
                             f"usina {codigo(usina.id)}")
    return DispositivosOut(dispositivos=_saida(db, quem, usina))


@router.put("/usinas/{gs}/dispositivos", response_model=GravadosOut, response_model_exclude_unset=True)
def gravar_dispositivos(gs: int, body: ListaIn, request: Request, db: Session = Depends(get_db)) -> GravadosOut:
    quem, usina = _usina(db, request, gs, tuple(dispositivos.GRAFIA), _AINDA_NAO)
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
    return GravadosOut(dispositivos=_saida(db, quem, usina), **feito)


@router.put("/usinas/{gs}/dispositivos/nos", response_model=NosLigadosOut, response_model_exclude_unset=True)
def ligar_nos(gs: int, body: NosIn, request: Request, db: Session = Depends(get_db)) -> NosLigadosOut:
    """O meuPlano diz em qual dispositivo (pela referência padrão) está cada nó dele. Só mexe no que veio no pedido; o
    nó nulo desliga. Idempotente."""
    quem, usina = _usina(db, request, gs, dispositivos.LIGA_NOS, _SO_O_MEUPLANO)
    itens = [d.model_dump() for d in body.nos]
    try:
        dispositivos.conferir_nos(itens)
    except dispositivos.ListaInvalida as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    acessos.registrar(db, request, acao="gravacao", sistema=quem, agrupar_s=3600,
                      motivo=f"{NOMES[quem]} gravou pela porta da máquina (só a chave, sem pessoa): os nós dele nos "
                             f"dispositivos da usina {codigo(usina.id)}")
    try:
        feito = dispositivos.ligar_nos(db, usina, itens)
        db.commit()
    except dispositivos.NoDeOutro as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"O nó {exc.no} já está no dispositivo {codigo_do_dispositivo(exc.gd)}. Um nó é uma posição "
                            "só: desligue-o de lá no mesmo pedido. Nada foi gravado.") from exc
    except IntegrityError:                                 # o mesmo nó entrou por outro pedido, agora
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Outro pedido ligou os mesmos nós agora: nada foi gravado, mande de novo.") from None
    return NosLigadosOut(dispositivos=_saida(db, quem, usina), **feito)
