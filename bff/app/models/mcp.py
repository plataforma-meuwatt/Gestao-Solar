"""O token do conector do Claude (`api/v1/mcp.py`): o que o Claude da pessoa guarda depois do login com a
conta do Gestão Solar. Daqui só sai o hash — o valor existe uma vez, na resposta do `/oauth/token`."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TokenMcp(Base):
    __tablename__ = "gs_mcp_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    #: SHA-256 do token `gs_mcp_…`.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Atualizado de 10 em 10 minutos no máximo: diz se o Claude da pessoa ainda usa o conector.
    ultimo_uso_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
