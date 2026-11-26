"""oem-gs › Automações (Plano Assistente GS, 26/11/2026): as regras que as pessoas da empresa criaram pelo bot.

O gerente vê todas as da empresa dele, liga, pausa, põe em ensaio e apaga, e lê o que cada uma mandou (ou guardou).
Criar é pelo bot (Fase 1). O recorte sai da SESSÃO (`empresas.no_escopo`): regra de outra empresa é 404 sem nome, e a
rota nunca aceita empresa de quem chama.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import gestor_empresa_atual
from app.models.automacao import Automacao, AutomacaoDisparo
from app.models.plant import PlantLink
from app.models.user import User
from app.services import automacoes as auto
from app.services import empresas as svc

router = APIRouter(prefix="/api/empresa/automacoes", tags=["empresa · automações"])

#: Os rótulos moram aqui (o vocabulário é traduzido uma vez, no BFF): a tela mostra o que vem, nunca o código.
SITUACAO = {"ligada": "Ligada", "ensaio": "Em ensaio", "pausada": "Pausada", "concluida": "Concluída"}
EVENTO = {"disparo": "Aviso", "voltou": "Voltou ao normal", "cega": "Ficou cega (sem dado)", "enxergou": "Voltou a ler",
          "sem_dado": "Sem dado para conferir", "perdida": "Horário perdido", "erro": "Erro", "teste": "Teste"}
STATUS = {"enviada": "Enviado", "entregue": "Entregue na mensagem seguinte", "adiada": "Esperando a pessoa falar",
          "venceu": "Venceu sem chegar", "simulada": "Só no registro (ensaio)", "falhou": "Falhou",
          "recusada": "Recusado", "pendente": "Enviando"}
CANAL = {"whatsapp": "WhatsApp", "push": "Aplicativo", "whatsapp+push": "WhatsApp e aplicativo", "adiado": "—",
         "nenhum": "—"}


class UltimoDisparoOut(BaseModel):
    em: datetime
    evento: str
    evento_rotulo: str
    status: str
    status_rotulo: str


class RegraOut(BaseModel):
    id: int
    dono: str
    dono_apelido: str
    nome: str
    quando: str
    situacao: str
    situacao_rotulo: str
    texto_original: str | None
    proxima_em: datetime | None
    ultima_volta_em: datetime | None
    ultimo_disparo: UltimoDisparoOut | None
    cega: str | None
    ensaio_segurados: int
    ultimo_erro: str | None
    criada_em: datetime


class MotorOut(BaseModel):
    #: a volta de um minuto está ligada neste servidor (o motor e o interruptor)
    ligado: bool
    #: a última volta deste processo (desde o último deploy); None = ainda não deu a primeira
    ultima_volta: datetime | None


class ListaOut(BaseModel):
    regras: list[RegraOut]
    motor: MotorOut


class DisparoOut(BaseModel):
    id: int
    em: datetime
    evento: str
    evento_rotulo: str
    ensaio: bool
    texto: str
    canal: str | None
    canal_rotulo: str
    status: str
    status_rotulo: str
    erro: str | None
    usina: str | None
    leitura: dict[str, Any] | None


class MudarIn(BaseModel):
    situacao: Literal["ligada", "pausada", "ensaio"]


def _da_empresa(db: Session, gerente: User, regra_id: int) -> Automacao:
    regra = db.scalar(svc.no_escopo(select(Automacao), Automacao.empresa_id, gerente)
                      .where(Automacao.id == regra_id, Automacao.apagada_em.is_(None)))
    if regra is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regra não encontrada.")
    return regra


def _cega(regra: Automacao) -> str | None:
    from app.services.assistente_automacoes import _cega as cega

    return cega(regra)


def _saida(db: Session, regra: Automacao, donos: dict[int, User]) -> RegraOut:
    d = auto.ultimo_disparo(db, regra)
    dono = donos.get(regra.user_id)
    return RegraOut(
        id=regra.id, dono=dono.nome if dono else "—", dono_apelido=dono.apelido if dono else "—", nome=regra.nome,
        quando=auto.descrever(regra), situacao=regra.situacao,
        situacao_rotulo=SITUACAO.get(regra.situacao, regra.situacao), texto_original=regra.texto_original,
        proxima_em=auto._utc(regra.proxima_em) if regra.situacao in ("ligada", "ensaio") else None,
        ultima_volta_em=auto._utc(regra.ultima_volta_em),
        ultimo_disparo=UltimoDisparoOut(em=auto._utc(d.em), evento=d.evento, evento_rotulo=EVENTO.get(d.evento, d.evento),
                                        status=d.status, status_rotulo=STATUS.get(d.status, d.status)) if d else None,
        cega=_cega(regra), ensaio_segurados=auto.segurados(db, regra) if regra.situacao == "ensaio" else 0,
        ultimo_erro=regra.ultimo_erro, criada_em=auto._utc(regra.criada_em))


@router.get("", response_model=ListaOut)
def listar(db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)) -> ListaOut:
    regras = db.scalars(svc.no_escopo(select(Automacao), Automacao.empresa_id, gerente)
                        .where(Automacao.apagada_em.is_(None)).order_by(Automacao.id.desc())).all()
    donos = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in regras}))).all()}
    s = get_settings()
    return ListaOut(regras=[_saida(db, r, donos) for r in regras],
                    motor=MotorOut(ligado=s.gs_motor_minutos > 0 and not s.gs_automacoes_desligadas,
                                   ultima_volta=auto.ULTIMA_VOLTA))


@router.patch("/{regra_id}", response_model=RegraOut)
def mudar(regra_id: int, corpo: MudarIn, db: Session = Depends(get_db),
          gerente: User = Depends(gestor_empresa_atual)) -> RegraOut:
    regra = _da_empresa(db, gerente, regra_id)
    if regra.situacao == "concluida":
        raise HTTPException(status.HTTP_409_CONFLICT, "Este lembrete já tocou: não há o que ligar.")
    auto.mudar(db, regra, corpo.situacao)
    return _saida(db, regra, {u.id: u for u in [db.get(User, regra.user_id)] if u})


@router.delete("/{regra_id}", status_code=status.HTTP_204_NO_CONTENT)
def apagar(regra_id: int, db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)) -> None:
    auto.apagar(db, _da_empresa(db, gerente, regra_id))


@router.get("/{regra_id}/disparos", response_model=list[DisparoOut])
def disparos(regra_id: int, db: Session = Depends(get_db),
             gerente: User = Depends(gestor_empresa_atual)) -> list[DisparoOut]:
    regra = _da_empresa(db, gerente, regra_id)
    linhas = db.scalars(select(AutomacaoDisparo).where(AutomacaoDisparo.automacao_id == regra.id)
                        .order_by(AutomacaoDisparo.id.desc()).limit(50)).all()
    usinas = {u.id: u.nome for u in db.scalars(select(PlantLink).where(
        PlantLink.id.in_({d.plant_link_id for d in linhas if d.plant_link_id}))).all()}
    return [DisparoOut(id=d.id, em=auto._utc(d.em), evento=d.evento, evento_rotulo=EVENTO.get(d.evento, d.evento),
                       ensaio=bool(d.ensaio), texto=d.texto, canal=d.canal, canal_rotulo=CANAL.get(d.canal or "", "—"),
                       status=d.status, status_rotulo=STATUS.get(d.status, d.status), erro=d.erro,
                       usina=usinas.get(d.plant_link_id), leitura=d.leitura) for d in linhas]
