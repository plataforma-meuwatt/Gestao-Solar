"""Os pedidos de "Processar <usina>" que o bot fez ao TermoVision (`assistente_termovision`).

O processamento roda horas nos PCs e o TermoVision avisa a cada etapa: o pedido mora aqui, e não em memória, para o
aviso achar quem pediu depois de um deploy. Só o `token` de um pedido daqui é aceito no aviso.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProcessamentoTV(Base):
    __tablename__ = "gs_processamentos_tv"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(80), unique=True)
    gs_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("gs_users.id", ondelete="CASCADE"))
    telefone: Mapped[str] = mapped_column(String(30))
    usina: Mapped[str] = mapped_column(String(200))
    #: o último estado avisado (estado + etapa): o mesmo de novo não vira mensagem
    avisado: Mapped[str] = mapped_column(String(300), default="", server_default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
