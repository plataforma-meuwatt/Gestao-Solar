"""O que cada pessoa do staff abre no painel.

**Acesso é presença de linha**, pela mesma razão que vale para as permissões do
aplicativo (`models/permissao.py`): conceder cria, revogar apaga, e não existe o
terceiro estado "nunca decidido" que um booleano inventaria.

Tabela separada de `gs_user_permissions` de propósito, e não é preciosismo: lá
mora o que o CLIENTE recebe no celular, e a tela que grava aquilo substitui a
lista inteira do usuário (`PUT /clientes/{id}/permissoes`). Se as duas coisas
dividissem a tabela, salvar as notificações de um cliente apagaria os acessos de
painel de quem por acaso tivesse os dois — silenciosamente, e só se descobriria
quando alguém do staff perdesse metade do menu.

`area` é texto, não enum de banco: o catálogo mora em
`app/services/areas_painel.py`, e tela nova do painel é coisa que aparece a toda
hora. Um enum no Postgres cobraria uma migration por tela.

**O administrador não tem linha nenhuma aqui, e abre tudo.** Ele é o superusuário
por perfil (`gs_users.perfil`), e essa é a chave do desenho: quem administra não
depende de concessão para destravar o painel de volta — senão um acesso revogado
por engano trancaria todo mundo do lado de fora.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AcessoPainel(Base):
    """Uma área do painel concedida a um membro do staff."""

    __tablename__ = "gs_painel_acessos"
    __table_args__ = (
        # Conceder duas vezes é o gestor clicando de novo porque a tela demorou, não
        # erro: a unicidade faz disso um no-op em vez de duas linhas, das quais revogar
        # apagaria só uma e deixaria a outra valendo.
        UniqueConstraint("user_id", "area", name="uq_gs_painel_acesso"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    #: Chave do catálogo — `clientes`, `usinas`, `whatsapp`… Ver `services/areas_painel.py`.
    area: Mapped[str] = mapped_column(String(40), index=True)

    concedido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: Quem concedeu. Nulo quando a linha veio da migração que preservou o acesso antigo.
    concedido_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    usuario: Mapped["object"] = relationship("User", foreign_keys=[user_id])
