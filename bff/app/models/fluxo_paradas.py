"""A classificação de paradas pelo WhatsApp, em andamento — uma por pessoa (`assistente_paradas`).

O passo a passo (o resumo, a parada da vez, a pergunta da cascata, o que já foi escolhido, o placar) mora aqui, e
não em memória: o dono classifica as paradas de um dia de várias usinas, com pausas, e um deploy no meio não pode
apagar onde ele estava. Vale `assistente_paradas.VALIDADE` (12 h); começar outra substitui esta.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FluxoParadas(Base):
    __tablename__ = "gs_fluxos_paradas"

    id: Mapped[int] = mapped_column(primary_key=True)
    gs_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("gs_users.id", ondelete="CASCADE"), unique=True)
    #: JSON com o estado inteiro (ver `assistente_paradas`): a fila de paradas, a etapa, as escolhas e o placar.
    estado: Mapped[str] = mapped_column(Text)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
