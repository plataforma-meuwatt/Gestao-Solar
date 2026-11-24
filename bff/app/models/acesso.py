"""A auditoria dos acessos: cada entrada no GS e cada passe que ele entregou a outro sistema (`services/acessos`).

O dono, 24/11/2026: "o GS é o detentor dos acessos, quero que ele tenha a auditoria completa dos logs de acessos de
cada pessoa". Toda entrada em qualquer sistema da família passa pelo GS, então é aqui que fica o registro: quem, quando,
em qual sistema, de onde e se deu certo. O que a pessoa faz DENTRO de cada sistema continua no registro de lá.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AcessoGS(Base):
    __tablename__ = "gs_acessos"

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: nulo quando o login digitado não é de conta nenhuma (fica o que foi digitado em `login`)
    gs_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("gs_users.id", ondelete="SET NULL"),
                                                   nullable=True)
    login: Mapped[str] = mapped_column(String(160), default="", server_default="")
    #: entrou · passe · recusado · bloqueado · senha · acesso
    acao: Mapped[str] = mapped_column(String(20))
    #: quem fez, quando não foi a própria pessoa: a senha redefinida, o acesso mudado, a origem da troca de papel
    por_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True)
    #: a empresa onde a mudança aconteceu (nula = da plataforma ou da própria pessoa): a outra empresa de quem é de duas
    #: não vê o que esta mudou (as usinas, as telas de cá)
    empresa_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("gs_empresas.id", ondelete="SET NULL"),
                                                   nullable=True)
    #: onde: gs (portal, app e painel), claude (o conector), meuwatt, meuplano, meuguarda, termovision
    sistema: Mapped[str] = mapped_column(String(20))
    ok: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    #: o porquê (o portão, a recusa) em palavras; nunca a senha
    motivo: Mapped[str] = mapped_column(String(200), default="", server_default="")
    ip: Mapped[str] = mapped_column(String(64), default="", server_default="")
    aparelho: Mapped[str] = mapped_column(String(300), default="", server_default="")

    __table_args__ = (Index("ix_gs_acessos_conta_em", "gs_user_id", "em"), Index("ix_gs_acessos_em", "em"))
