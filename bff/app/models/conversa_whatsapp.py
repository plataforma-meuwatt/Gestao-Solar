"""A conversa do assistente do WhatsApp — o histórico que dá sentido a "e ontem?".

Uma linha por TELEFONE (o WhatsApp é um por número). O histórico é curto e vai inteiro ao
modelo a cada turno; guardar no banco, e não em memória, é o que faz a conversa sobreviver
a um deploy no meio do dia.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConversaWhatsapp(Base):
    __tablename__ = "gs_whatsapp_conversas"

    id: Mapped[int] = mapped_column(primary_key=True)
    telefone: Mapped[str] = mapped_column(String(20), unique=True)
    gs_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: JSON: [{"role": "user"|"assistant", "content": "..."}], só os últimos turnos.
    mensagens: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
