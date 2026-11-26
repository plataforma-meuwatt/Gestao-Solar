"""oem-gs › Automações (Plano Assistente GS, 26/11/2026): as regras que as pessoas da empresa criaram pelo bot.

O gerente vê todas as da empresa dele, liga, pausa, põe em ensaio e apaga, e lê o que cada uma mandou (ou guardou).
Criar é pelo bot (Fase 1). O recorte sai da SESSÃO (`empresas.no_escopo`): regra de outra empresa é 404 sem nome, e a
rota nunca aceita empresa de quem chama. Toda frase que a tela mostra sai daqui (o vocabulário é traduzido uma vez):
a tela não monta texto a partir de código.
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

SITUACAO = {"ligada": "Ligada", "ensaio": "Em ensaio", "pausada": "Pausada", "concluida": "Concluída"}
#: O que cada situação quer dizer, numa linha (o "ensaio" não se explica sozinho, e o toque não tem `title`).
AJUDA = {"ligada": "Os avisos saem para a pessoa.",
         "ensaio": "Só o 1º aviso sai para a pessoa; os outros ficam só no registro.",
         "pausada": "Não confere nem avisa.", "concluida": "O lembrete já tocou."}
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
    #: o gatilho em palavras ("tensão do Relé Skid 1 abaixo de 1.000 V (ou fase zerada) por 10 min")
    quando: str
    #: em quais usinas, em palavras ("todas as usinas menos Tiete"); None no lembrete
    onde: str | None
    #: por onde avisa ("WhatsApp e aplicativo")
    entrega_rotulo: str
    #: horario | uma_vez | leitura | camera
    gatilho_tipo: str
    situacao: str
    #: "Ligada", "Em ensaio"… e " · cega" quando alguma usina da regra está sem dado
    situacao_rotulo: str
    situacao_ajuda: str
    #: a agenda em palavras: "Próxima vez: 26/11 19:00", "Última conferência: 04:37", "Ainda não conferida"…
    agenda_rotulo: str
    texto_original: str | None
    proxima_em: datetime | None
    ultima_volta_em: datetime | None
    ultimo_disparo: UltimoDisparoOut | None
    #: onde está cega e as que leem ("Cega em Pirapozinho desde 04:12 (motivo) · as outras 4 usinas leem")
    cega: str | None
    ensaio_segurados: int
    ultimo_erro: str | None
    criada_em: datetime


class MotorOut(BaseModel):
    #: a volta de um minuto está configurada neste servidor (o motor e o interruptor)
    ligado: bool
    #: a última volta deste processo (desde o último deploy); None = ainda não deu a primeira
    ultima_volta: datetime | None
    #: quando a tarefa do motor subiu neste processo; None = não subiu
    iniciado_em: datetime | None
    #: a hora do servidor agora: a tela compara a última volta com ela, não com o relógio do navegador
    agora: datetime


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
    #: os valores lidos que provaram o disparo, em linhas prontas ("Fase A: 0 V (ok)", "Leitura de 14:12")
    leitura_linhas: list[str]
    leitura: dict[str, Any] | None


class MudarIn(BaseModel):
    situacao: Literal["ligada", "pausada", "ensaio"]


def _status(d: AutomacaoDisparo) -> str:
    """O teste nunca manda nada: o rótulo diz só isso (o evento já diz "Teste")."""
    return "Nada foi mandado" if d.evento == "teste" else STATUS.get(d.status, d.status)


def _da_empresa(db: Session, gerente: User, regra_id: int) -> Automacao:
    regra = db.scalar(svc.no_escopo(select(Automacao), Automacao.empresa_id, gerente)
                      .where(Automacao.id == regra_id, Automacao.apagada_em.is_(None)))
    if regra is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regra não encontrada.")
    return regra


def _cega(db: Session, regra: Automacao) -> str | None:
    """Onde a regra está cega (a usina pelo nome) e quantas das outras leem, pelo estado de cada alvo."""
    alvos = (regra.estado or {}).get("alvos") or {}
    cegos = [(k, st) for k, st in alvos.items() if st.get("cega")]
    if not cegos:
        return None
    nomes = {u.id: u.nome for u in db.scalars(select(PlantLink).where(PlantLink.id.in_(
        {int(k.split(":")[0]) for k, _ in cegos if k.split(":")[0].isdigit()})))}
    partes = []
    for k, st in cegos:
        ref = k.split(":")[0]
        onde = (nomes.get(int(ref)) if ref.isdigit() else
                "o meuGuarda" if ref == "meuguarda" else "todas as usinas da regra")
        desde = auto._ts(st.get("sem_dado_desde"))
        partes.append(f"cega em {onde or 'uma usina'} desde {auto._hora(desde)} ({st.get('porque') or 'sem dado'})")
    usinas_cegas = {k.split(":")[0] for k, _ in cegos}
    lendo = {k.split(":")[0] for k, st in alvos.items() if not st.get("cega")} - usinas_cegas
    texto = "; ".join(partes)
    if lendo:
        texto += f" · as outras {len(lendo)} leem" if len(lendo) > 1 else " · a outra lê"
    return texto[:1].upper() + texto[1:]


def _agenda(regra: Automacao) -> str:
    tipo = (regra.gatilho or {}).get("tipo")
    if regra.situacao == "concluida":
        return "O lembrete já tocou"
    if regra.situacao == "pausada":
        return "Pausada: não confere"
    if tipo in ("horario", "uma_vez"):
        prox = auto._utc(regra.proxima_em)
        return f"Próxima vez: {auto._hora(prox, com_dia=True)}" if prox else "Sem próxima vez"
    volta = auto._utc(regra.ultima_volta_em)
    return f"Última conferência: {auto._hora(volta)}" if volta else "Ainda não conferida"


def _entrega(regra: Automacao) -> str:
    canais = set((regra.entrega or {}).get("canais") or ["whatsapp", "push"])
    return ("WhatsApp e aplicativo" if {"whatsapp", "push"} <= canais else "WhatsApp" if "whatsapp" in canais
            else "Aplicativo")


def _saida(db: Session, regra: Automacao, donos: dict[int, User]) -> RegraOut:
    d = auto.ultimo_disparo(db, regra)
    dono = donos.get(regra.user_id)
    cega = _cega(db, regra) if regra.situacao in ("ligada", "ensaio") else None
    return RegraOut(
        id=regra.id, dono=dono.nome if dono else "—", dono_apelido=dono.apelido if dono else "—", nome=regra.nome,
        quando=auto.descrever(regra), onde=auto.onde(db, regra), entrega_rotulo=_entrega(regra),
        gatilho_tipo=str((regra.gatilho or {}).get("tipo") or ""), situacao=regra.situacao,
        situacao_rotulo=SITUACAO.get(regra.situacao, regra.situacao) + (" · cega" if cega else ""),
        situacao_ajuda=AJUDA.get(regra.situacao, ""), agenda_rotulo=_agenda(regra),
        texto_original=regra.texto_original,
        proxima_em=(auto._utc(regra.proxima_em) if regra.situacao in ("ligada", "ensaio")
                    and (regra.gatilho or {}).get("tipo") in ("horario", "uma_vez") else None),
        ultima_volta_em=auto._utc(regra.ultima_volta_em),
        ultimo_disparo=UltimoDisparoOut(em=auto._utc(d.em), evento=d.evento, evento_rotulo=EVENTO.get(d.evento, d.evento),
                                        status=d.status, status_rotulo=_status(d)) if d else None,
        cega=cega, ensaio_segurados=auto.segurados(db, regra) if regra.situacao == "ensaio" else 0,
        ultimo_erro=regra.ultimo_erro, criada_em=auto._utc(regra.criada_em))


def _linhas_da_leitura(leitura: dict | None) -> list[str]:
    """O que provou o disparo, em linhas: as fases do relé, as sondas do trafo, os inversores parados, o evento."""
    if not leitura:
        return []
    linhas = []
    for f, x in (leitura.get("fases") or {}).items():
        linhas.append(f"Fase {f.upper()}: {auto._n(x.get('valor'), 0)} V ({x.get('estado') or '—'})")
    for s, v in (leitura.get("sondas") or {}).items():
        linhas.append(f"Sonda {s}: {auto._n(v, 1)} °C")
    if leitura.get("parados"):
        linhas.append("Parados: " + ", ".join(sorted(leitura["parados"])))
    if (ev := leitura.get("evento")):
        linhas.append(f"Evento do meuGuarda: {ev.get('tipo')} na {ev.get('camera') or 'câmera'}")
    if leitura.get("leitura_em"):
        linhas.append(f"Leitura de {auto._hora(auto._ts(leitura['leitura_em']), com_dia=True)}")
    return linhas


@router.get("", response_model=ListaOut)
def listar(db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)) -> ListaOut:
    regras = db.scalars(svc.no_escopo(select(Automacao), Automacao.empresa_id, gerente)
                        .where(Automacao.apagada_em.is_(None)).order_by(Automacao.id.desc())).all()
    donos = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in regras}))).all()}
    s = get_settings()
    return ListaOut(regras=[_saida(db, r, donos) for r in regras],
                    motor=MotorOut(ligado=s.gs_motor_minutos > 0 and not s.gs_automacoes_desligadas,
                                   ultima_volta=auto.ULTIMA_VOLTA, iniciado_em=auto.INICIADO_EM, agora=auto._agora()))


@router.patch("/{regra_id}", response_model=RegraOut)
def mudar(regra_id: int, corpo: MudarIn, db: Session = Depends(get_db),
          gerente: User = Depends(gestor_empresa_atual)) -> RegraOut:
    regra = _da_empresa(db, gerente, regra_id)
    if regra.situacao == "concluida":
        raise HTTPException(status.HTTP_409_CONFLICT, "Este lembrete já tocou: não há o que ligar.")
    try:
        auto.mudar(db, regra, corpo.situacao)
    except auto.RegraInvalida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
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
                       status=d.status, status_rotulo=_status(d), erro=d.erro, usina=usinas.get(d.plant_link_id),
                       leitura_linhas=_linhas_da_leitura(d.leitura), leitura=d.leitura) for d in linhas]
