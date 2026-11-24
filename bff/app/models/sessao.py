"""As sessões abertas de cada pessoa no GS (Plano Casa GS, R4: "a auditoria completa dos acessos de cada pessoa (cada
entrada, cada passe, de onde, falhas, sessões)").

Cada sessão emitida leva um `sid` no token; a linha nasce no primeiro uso (é quando se sabe de onde ela fala) e guarda o
último uso (de 5 em 5 minutos). Encerrar uma é marcar `encerrada_em`: a guarda recusa na requisição seguinte. Encerrar
TODAS é `gs_users.sessoes_desde`: todo token emitido antes vale nada, inclusive os que nunca foram usados e os de antes
das sessões existirem (sem `sid`)."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SessaoGS(Base):
    __tablename__ = "gs_sessoes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    gs_user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    #: o portão: cliente (aplicativo e portal), painel, empresa, tecnico ou entrada (o gestao.solar)
    escopo: Mapped[str] = mapped_column(String(20))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expira_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_uso_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ip: Mapped[str] = mapped_column(String(64), default="", server_default="")
    aparelho: Mapped[str] = mapped_column(String(300), default="", server_default="")
    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    encerrada_por_id: Mapped[int | None] = mapped_column(ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True)
    motivo: Mapped[str] = mapped_column(String(120), default="", server_default="")


class RedefinicaoDeSenha(Base):
    """O link de criar a senha nova ("esqueci a senha", R12: "pelo e-mail e pelo WhatsApp do bot"): 30 minutos, uma vez
    só. Guarda-se só o hash do token; o novo apaga os de antes que ainda não foram usados."""

    __tablename__ = "gs_redefinicoes_senha"

    id: Mapped[int] = mapped_column(primary_key=True)
    gs_user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    #: por onde o link foi: whatsapp ou email
    canal: Mapped[str] = mapped_column(String(20))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    usada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
