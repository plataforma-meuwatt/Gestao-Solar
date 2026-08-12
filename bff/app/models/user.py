"""Quem usa o Gestão Solar.

Uma tabela só para cliente e gestor: os dois entram com e-mail e senha, e o que muda é o
`perfil`. Separar em duas tabelas duplicaria autenticação, senha e sessão para ganhar
nada — a diferença entre eles é o que a tela abre, não como entram.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.plant import PlantLink


class Perfil(StrEnum):
    """O que a conta abre.

    `cliente` entra no app e vê as usinas dele. `atendimento` abre o painel e cuida de
    cliente e diagnóstico. `administrador` faz tudo, inclusive mexer nas pontes com os
    produtos e na própria equipe — é a conta que, se comprometida, dá acesso às
    credenciais de serviço dos dois sistemas.
    """

    CLIENTE = "cliente"
    ATENDIMENTO = "atendimento"
    ADMINISTRADOR = "administrador"


class User(Base):
    __tablename__ = "gs_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(255))
    empresa: Mapped[str | None] = mapped_column(String(255), nullable=True)

    perfil: Mapped[Perfil] = mapped_column(
        Enum(Perfil, native_enum=False, length=20), default=Perfil.CLIENTE
    )

    senha_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Enquanto verdadeiro, o app leva o cliente para a troca de senha antes de qualquer
    # tela. É o que fecha o ciclo da senha provisória entregue pelo gestor.
    trocar_senha: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Espelho do `AppUser.nivel_acesso` do meuPlano (0-5), usado para decidir se o
    # assistente pode revelar uma credencial. Fonte da verdade continua sendo lá.
    nivel_acesso: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    acessos: Mapped[list["UserPlantAccess"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    # `foreign_keys` é obrigatório aqui: VinculoProduto aponta duas vezes para gs_users —
    # o cliente dono do vínculo e o gestor que o criou. Sem isto o SQLAlchemy não sabe
    # qual das duas define a relação.
    vinculos: Mapped[list["VinculoProduto"]] = relationship(
        back_populates="usuario",
        cascade="all, delete-orphan",
        foreign_keys="VinculoProduto.gs_user_id",
    )

    @property
    def abre_painel(self) -> bool:
        return self.perfil in (Perfil.ATENDIMENTO, Perfil.ADMINISTRADOR)

    @property
    def e_administrador(self) -> bool:
        return self.perfil is Perfil.ADMINISTRADOR


class VinculoProduto(Base):
    """Qual conta deste cliente em cada produto.

    Guarda o e-mail e o nome de lá junto do id: o painel precisa mostrar *quem* foi
    vinculado sem ir buscar no upstream a cada carregamento de tela, e o registro
    continua legível mesmo se a conta sumir de lá.
    """

    __tablename__ = "gs_vinculos_produto"
    __table_args__ = (UniqueConstraint("gs_user_id", "produto", name="uq_usuario_produto"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    gs_user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    produto: Mapped[str] = mapped_column(String(20))

    usuario_remoto_id: Mapped[str] = mapped_column(String(64))
    usuario_remoto_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    usuario_remoto_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)

    vinculado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    vinculado_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    usuario: Mapped["User"] = relationship(back_populates="vinculos", foreign_keys=[gs_user_id])


class SenhaProvisoria(Base):
    """Registro de que um acesso foi entregue — não a senha.

    A senha só existe no `senha_hash` do usuário e no momento em que o painel a exibe.
    Esta tabela responde a pergunta operacional: "entreguei o acesso a este cliente? ele
    já usou?" — que é o que evita cobrar alguém que nunca recebeu nada.
    """

    __tablename__ = "gs_senhas_provisorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    gs_user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    gerada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    gerada_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )
    usada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserPlantAccess(Base):
    """A que usinas este usuário tem direito.

    Para cliente, é o que o gestor definiu no painel — e uma usina só pode estar em um
    cliente (a regra é aplicada no serviço, não no banco, para a mensagem de erro poder
    dizer de quem é a usina).
    """

    __tablename__ = "gs_user_plant_access"
    __table_args__ = (UniqueConstraint("user_id", "plant_link_id", name="uq_user_plant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    plant_link_id: Mapped[int] = mapped_column(ForeignKey("gs_plant_links.id", ondelete="CASCADE"))
    concedido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    usuario: Mapped["User"] = relationship(back_populates="acessos")
    usina: Mapped["PlantLink"] = relationship()
