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


class RegistroBot(Base):
    """Uma volta do assistente — o log que a plataforma lê no adm-gs ("vejo log dos bots").

    Uma linha por mensagem recebida: de quem (telefone, conta, empresa de origem), o que
    aconteceu (`resultado`), que partes e ferramentas foram usadas, quanto levou, e o
    começo da pergunta e da resposta. Número sem conta também entra: é o que diz à
    plataforma quem está tentando falar com o bot sem cadastro.
    """

    __tablename__ = "gs_bot_registros"

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    telefone: Mapped[str] = mapped_column(String(20))
    gs_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    empresa_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("gs_empresas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: `respondeu` | `sem_conta` | `nao_liberado` | `erro`
    resultado: Mapped[str] = mapped_column(String(20))
    #: As ferramentas chamadas nesta volta, separadas por vírgula.
    ferramentas: Mapped[str | None] = mapped_column(Text, nullable=True)
    pergunta: Mapped[str | None] = mapped_column(Text, nullable=True)
    resposta: Mapped[str | None] = mapped_column(Text, nullable=True)
    duracao_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
