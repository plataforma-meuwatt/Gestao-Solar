"""oem-gs › Usinas › Equipamentos: o gerente diz qual nó do meuPlano é qual dispositivo do índice (fase 3, 2ª fatia,
27/11/2026).

O meuPlano não tem os inversores e os transformadores casados com o meuWatt, então a porta da máquina não ligou nenhum.
Aqui o GS mostra os dispositivos da usina (a árvore: o transformador com os inversores dele), os nós CANDIDATOS lidos na
hora do meuPlano com a conta da empresa, e uma SUGESTÃO por dispositivo, com o porquê (`services/sugestao_de_nos.py`).
A sugestão nunca se aplica sozinha: quem grava é a pessoa, com a mesma regra da porta da máquina
(`dispositivos.aplicar_nos`: um nó é uma posição só; a troca cabe num pedido), e cada mudança entra no histórico da
usina com quem fez.

- `GET /api/empresa/usinas/{id}/dispositivos`
- `PUT /api/empresa/usinas/{id}/dispositivos/nos`

Quem pode: o mesmo da tela Dados (o gerente da O&M da usina; `gestor_empresa_atual` + a usina no escopo da empresa).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.interno_sistemas import codigo, codigo_do_dispositivo
from app.core.db import get_db
from app.core.security import gestor_empresa_atual
from app.models.plant import DeviceLink, PlantLink
from app.models.user import User
from app.services import dados_da_usina, dispositivos, integracoes, sugestao_de_nos
from app.services import empresas as svc

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/empresa", tags=["empresa · O&M"])

#: os tipos de dispositivo que têm nó candidato no meuPlano (os outros aparecem na árvore, sem lista)
ROTULO_DO_TIPO = {"transformador": "Transformador", "inversor": "Inversor"}


class NoOut(BaseModel):
    id: int
    #: o nome do nó, o código e onde fica na árvore, numa frase só; nulo quando o meuPlano não foi lido
    rotulo: str | None = None


class SugestaoOut(BaseModel):
    node_id: int
    #: numero (os dois lados têm os mesmos números) ou ordem (a ordem da árvore): a ordem é o palpite mais fraco
    base: str
    #: o porquê, em palavras ("pelo número", "pela ordem, entre os inversores de TR-01")
    motivo: str


class DispositivoOut(BaseModel):
    gd: int
    codigo: str
    tipo: str
    tipo_rotulo: str
    nome: str
    #: falso = não veio na última lista do meuWatt (a posição fica, com o mesmo número)
    ativo: bool
    #: o nó do meuPlano já gravado (confirmado)
    no: NoOut | None = None
    #: o nó que o GS propõe, só para o ativo ainda sem nó; nunca é gravado sem a pessoa salvar
    sugestao: SugestaoOut | None = None
    #: os dispositivos debaixo dele (os inversores do transformador)
    filhos: list["DispositivoOut"] = []


class CandidatoOut(BaseModel):
    id: int
    codigo: str
    nome: str
    #: onde fica na árvore, sem a usina e sem o próprio nome ("Skid 1 > Inversores")
    local: str
    rotulo: str


class EquipamentosOut(BaseModel):
    usina_id: int
    usina_codigo: str
    usina_nome: str
    dispositivos: list[DispositivoOut]
    #: os nós do meuPlano que podem ser cada tipo de dispositivo: `{"transformador": [...], "inversor": [...]}`
    candidatos: dict[str, list[CandidatoOut]]
    #: falso = os nós não foram lidos agora (os dispositivos vêm assim mesmo, sem candidatos e sem sugestão)
    meuplano_lido: bool
    #: por que não (a frase vai à tela)
    aviso: str | None = None
    #: `ligados` e `total` contam só os transformadores e os inversores (os que a tela mostra)
    ligados: int
    total: int
    #: quantas strings ativas a usina tem no índice (a tela só diz o número: elas não entram na lista)
    strings: int = 0


class NoDoDispositivoIn(BaseModel):
    model_config = {"extra": "forbid"}
    gd: int
    #: o nó do meuPlano naquela posição; nulo desliga
    node_id: int | None = Field(ge=1, le=2_147_483_647)


class NosIn(BaseModel):
    model_config = {"extra": "forbid"}
    nos: list[NoDoDispositivoIn] = Field(max_length=dispositivos.TETO)


def _usina(db: Session, gerente: User, usina_id: int) -> PlantLink:
    link = db.scalar(svc.no_escopo(select(PlantLink).where(PlantLink.id == usina_id), PlantLink.empresa_id, gerente))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada nesta empresa")
    return link


async def _nos_do_meuplano(db: Session, gerente: User, usina: PlantLink) -> tuple[list[dict] | None, str | None]:
    """Os nós da usina no meuPlano, lidos com a conta DA EMPRESA; ou nulo e o porquê."""
    if usina.mp_usina_id is None:
        return None, "Esta usina não está ligada ao meuPlano: não há nós para ligar."
    try:
        cliente = await integracoes.cliente_meuplano(db, svc.empresa_exigida(gerente))
        nos = await cliente.nos_da_usina(usina.mp_usina_id)
    except RuntimeError as exc:                            # a empresa sem a conta do meuPlano: a frase já é para a tela
        if type(exc) is RuntimeError:
            return None, str(exc)
        log.warning("equipamentos: meuPlano sem leitura para a usina %s (%s)", usina.id, type(exc).__name__)
        return None, "O meuPlano não respondeu agora: os nós para escolher não vieram. Tente de novo em instantes."
    except Exception as exc:  # noqa: BLE001 — a tela abre com o meuPlano fora
        log.warning("equipamentos: meuPlano sem leitura para a usina %s (%s)", usina.id, type(exc).__name__)
        return None, "O meuPlano não respondeu agora: os nós para escolher não vieram. Tente de novo em instantes."
    return [n for n in nos if isinstance(n, dict) and isinstance(n.get("id"), int)], None


def _local(no: dict) -> str:
    partes = [p.strip() for p in str(no.get("path") or "").split(">") if p.strip()]
    return " > ".join(partes[1:-1])


def _rotulo(no: dict) -> str:
    return " · ".join(p for p in (str(no.get("display_name") or ""), str(no.get("code") or ""), _local(no)) if p)


def _montar(usina: PlantLink, todas: list[DeviceLink], nos: list[dict] | None, aviso: str | None) -> EquipamentosOut:
    # a tela é dos transformadores e dos inversores: as strings (centenas por usina) só entram na contagem, e o nó
    # delas será ligado sozinho numa fase seguinte
    linhas = [x for x in todas if x.tipo in sugestao_de_nos.TIPO_DO_NO]
    por_no = {n["id"]: n for n in nos or []}
    planos = [{"gd": x.id, "tipo": x.tipo, "nome": x.nome, "pai": x.pai_id, "ativo": bool(x.ativo),
               "node_id": x.mp_node_id} for x in linhas]
    sugestoes = sugestao_de_nos.sugerir(planos, nos) if nos else {}
    saida = {x.id: DispositivoOut(
        gd=x.id, codigo=codigo_do_dispositivo(x.id), tipo=x.tipo, tipo_rotulo=ROTULO_DO_TIPO.get(x.tipo, x.tipo),
        nome=x.nome, ativo=bool(x.ativo),
        no=NoOut(id=x.mp_node_id, rotulo=_rotulo(por_no[x.mp_node_id]) if x.mp_node_id in por_no else None)
        if x.mp_node_id is not None else None,
        sugestao=SugestaoOut(**sugestoes[x.id]) if x.id in sugestoes else None) for x in linhas}
    raizes = []
    for x in linhas:                                       # a árvore: quem tem pai nesta usina vai debaixo dele
        (saida[x.pai_id].filhos if x.pai_id in saida else raizes).append(saida[x.id])
    return EquipamentosOut(
        usina_id=usina.id, usina_codigo=codigo(usina.id), usina_nome=usina.nome, dispositivos=raizes,
        candidatos={tipo: [CandidatoOut(id=n["id"], codigo=str(n.get("code") or ""),
                                        nome=str(n.get("display_name") or ""), local=_local(n), rotulo=_rotulo(n))
                           for n in sugestao_de_nos.candidatos(nos or [], tipo)] for tipo in sugestao_de_nos.TIPO_DO_NO},
        meuplano_lido=nos is not None, aviso=aviso,
        ligados=sum(1 for x in linhas if x.mp_node_id is not None), total=len(linhas),
        strings=sum(1 for x in todas if x.tipo == "string" and x.ativo))


@router.get("/usinas/{usina_id}/dispositivos", response_model=EquipamentosOut)
async def equipamentos_da_usina(usina_id: int, db: Session = Depends(get_db),
                                gerente: User = Depends(gestor_empresa_atual)) -> EquipamentosOut:
    """Os dispositivos da usina no índice (a árvore), o nó do meuPlano de cada um, os nós candidatos lidos agora e a
    sugestão do GS. Sem o meuPlano, os dispositivos vêm assim mesmo, com o `aviso`."""
    usina = _usina(db, gerente, usina_id)
    nos, aviso = await _nos_do_meuplano(db, gerente, usina)
    return _montar(usina, dispositivos.todos_da_usina(db, usina), nos, aviso)


def _no_em_palavras(no: int | None, por_no: dict[int, dict]) -> str:
    if no is None:
        return "sem nó"
    return f"nó {no}" + (f" ({por_no[no].get('display_name')})" if no in por_no and por_no[no].get("display_name") else "")


@router.put("/usinas/{usina_id}/dispositivos/nos", response_model=EquipamentosOut)
async def gravar_nos_da_usina(usina_id: int, body: NosIn, db: Session = Depends(get_db),
                              gerente: User = Depends(gestor_empresa_atual)) -> EquipamentosOut:
    """A pessoa confirma o nó de cada dispositivo que veio no pedido (nulo desliga); o que não veio fica como está.
    O nó tem de ser desta usina no meuPlano e do tipo do dispositivo. Devolve a tela de novo."""
    usina = _usina(db, gerente, usina_id)
    linhas = {x.id: x for x in dispositivos.todos_da_usina(db, usina)}
    gds = [d.gd for d in body.nos]
    nos_pedidos = [d.node_id for d in body.nos if d.node_id is not None]
    if len(set(gds)) != len(gds):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O mesmo equipamento veio mais de uma vez.")
    if len(set(nos_pedidos)) != len(nos_pedidos):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O mesmo nó foi escolhido para mais de um equipamento: um nó é "
                                                         "uma posição só.")
    if any(gd not in linhas for gd in gds):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado nesta usina")
    nos, aviso = await _nos_do_meuplano(db, gerente, usina)
    por_no = {n["id"]: n for n in nos or []}
    pedido = {linhas[d.gd]: d.node_id for d in body.nos}
    for linha, no in pedido.items():                       # o nó novo é conferido contra o meuPlano; desligar não precisa
        if no is None or no == linha.mp_node_id:
            continue
        if nos is None:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                (aviso or "O meuPlano não respondeu agora.") + " Nada foi gravado.")
        if por_no.get(no, {}).get("type_code") != sugestao_de_nos.TIPO_DO_NO.get(linha.tipo):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"O nó {no} não é um {ROTULO_DO_TIPO.get(linha.tipo, linha.tipo).lower()} desta usina "
                                "no meuPlano. Nada foi gravado.")
    antes = {linha: linha.mp_node_id for linha in pedido}
    try:
        dispositivos.aplicar_nos(db, pedido)
        for linha, era in antes.items():                   # quem mudou o quê: no histórico da usina, como os dados dela
            if linha.mp_node_id != era:
                quem = f"{codigo_do_dispositivo(linha.id)} {linha.nome}: "
                dados_da_usina.historico(db, usina, "no_do_dispositivo", quem + _no_em_palavras(era, por_no),
                                         quem + _no_em_palavras(linha.mp_node_id, por_no), por=gerente, sistema="gs")
        db.commit()
    except dispositivos.NoDeOutro as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"O nó {exc.no} já está no equipamento {codigo_do_dispositivo(exc.gd)}. Um nó é uma posição "
                            "só: tire-o de lá no mesmo salvar. Nada foi gravado.") from exc
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Outra pessoa ligou os mesmos nós agora: nada foi gravado. Abra de novo e confira.") from None
    return _montar(usina, dispositivos.todos_da_usina(db, usina), nos, aviso)
