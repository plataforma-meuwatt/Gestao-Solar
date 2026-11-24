"""As sessões abertas de cada pessoa (R4) e o encerrar: uma, ou todas de uma vez. Ver `models/sessao.py`."""
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.sessao import SessaoGS
from app.models.user import User

#: o portão de cada sessão, como a tela diz
PORTAO = {"cliente": "portal ou aplicativo", "painel": "adm-gs", "empresa": "oem-gs", "tecnico": "oem-gs, técnico",
          "entrada": "entrada do gestao.solar"}


def _com_fuso(quando: datetime | None) -> datetime | None:
    return quando if quando is None or quando.tzinfo else quando.replace(tzinfo=UTC)


def abertas(db: Session, pessoa: User) -> list[SessaoGS]:
    """As que ainda valem: não encerradas, não vencidas e de depois do último "encerrar todas"; a usada por último
    primeiro."""
    agora = datetime.now(UTC)
    linhas = db.scalars(select(SessaoGS).where(
        SessaoGS.gs_user_id == pessoa.id, SessaoGS.encerrada_em.is_(None),
        or_(SessaoGS.expira_em.is_(None), SessaoGS.expira_em > agora)).order_by(SessaoGS.ultimo_uso_em.desc())).all()
    desde = _com_fuso(pessoa.sessoes_desde)
    return [s for s in linhas if desde is None or _com_fuso(s.criada_em) >= desde]


def encerrar(db: Session, sessao: SessaoGS, *, por: User | None, motivo: str) -> None:
    """Não confirma."""
    if sessao.encerrada_em is None:
        sessao.encerrada_em = datetime.now(UTC)
        sessao.encerrada_por_id = por.id if por is not None else None
        sessao.motivo = (motivo or "")[:120]


def encerrar_todas_de(db: Session, pessoa: User, por: User | None, onde_: str) -> int:
    """Encerra todas e deixa no Registro de acessos. CONFIRMA. Toda senha trocada por outra pessoa passa por aqui (a
    sessão de quem roubou a senha não sobrevive à troca)."""
    from app.services import acessos
    n = encerrar_todas(db, pessoa, por=por, motivo=f"todas encerradas no {onde_}")
    db.commit()
    acessos.registrar(db, None, acao="acesso", user=pessoa, por=por,
                      motivo=f"todas as sessões encerradas no {onde_} ({n} aberta(s))")
    return n


def encerrar_todas(db: Session, pessoa: User, *, por: User | None, motivo: str) -> int:
    """Todo token emitido até agora deixa de valer (`sessoes_desde`), inclusive o que nunca foi usado. Devolve quantas
    sessões abertas foram encerradas. Não confirma."""
    n = 0
    for s in abertas(db, pessoa):
        encerrar(db, s, por=por, motivo=motivo)
        n += 1
    pessoa.sessoes_desde = datetime.now(UTC).replace(microsecond=0)   # o token emitido logo depois (iat inteiro) vale
    return n
