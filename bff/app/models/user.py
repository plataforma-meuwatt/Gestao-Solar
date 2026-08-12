"""Identidade do usuário no Gestão Solar.

O usuário não tem senha aqui: quem valida a credencial são os upstreams (mw-api e
meuPlano). Este registro só guarda a identidade resolvida e a que usinas ela tem direito.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.plant import PlantLink


class User(Base):
    __tablename__ = "gs_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(255))
    empresa: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Identificadores do mesmo humano em cada upstream. Um dos dois pode ser nulo — há
    # proprietário que só existe num dos sistemas.
    mw_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    mp_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Espelho do `AppUser.nivel_acesso` do meuPlano (0-5), usado para decidir se o
    # assistente pode revelar uma credencial. Fonte da verdade continua sendo lá.
    nivel_acesso: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Senha do Gestão Solar. Nula para quem ainda não definiu — o cliente entra pela
    # conexão com os upstreams enquanto não criar a dele.
    senha_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Acesso ao painel de administração (configurar integrações, conciliar usinas).
    # É o time interno, não o dono da usina.
    is_gestor: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    acessos: Mapped[list["UserPlantAccess"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )


class UserPlantAccess(Base):
    """Escopo capturado no login: a que usinas este usuário tem direito.

    Recalculado a cada login e revalidado a cada 24 h. Se o dono perder acesso a uma usina
    no upstream, perde aqui no próximo ciclo — é intencional que haja essa janela, em troca
    de não depender do token do usuário para toda leitura.
    """

    __tablename__ = "gs_user_plant_access"
    __table_args__ = (UniqueConstraint("user_id", "plant_link_id", name="uq_user_plant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    plant_link_id: Mapped[int] = mapped_column(ForeignKey("gs_plant_links.id", ondelete="CASCADE"))
    revalidado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    usuario: Mapped["User"] = relationship(back_populates="acessos")
    usina: Mapped["PlantLink"] = relationship()
