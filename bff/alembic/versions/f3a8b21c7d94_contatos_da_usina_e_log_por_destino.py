"""contatos da usina, e o log apontando para quem recebeu

Revision ID: f3a8b21c7d94
Revises: e7c1a4d93b58
Create Date: 2026-09-21

Duas mudanças que andam juntas:

1. **`gs_contatos_usina` + `gs_contato_preferencias`** — quem mais recebe aviso daquela
   usina, além do dono da conta. Substitui o "manda no grupo do cliente", que a API
   oficial do WhatsApp não permite (só grupos criados por ela, com oito participantes e
   exigindo Conta Comercial Oficial).

2. **`gs_notificacoes_enviadas` passa a apontar para os dois tipos de destinatário.**
   `user_id` vira anulável e entra `contato_id`, cada um com a sua trava de repetição.

**Por que duas UNIQUEs e não uma coluna "destino" genérica:** a chave estrangeira é o que
faz o banco recusar log órfão, e uma coluna de texto do tipo `"c:5"` desistiria disso em
troca de uma linha a menos de migration. E funciona nos dois bancos porque `NULL` nunca
colide com `NULL` num índice único — as linhas de contato têm `user_id` nulo e não
disputam a trava do cliente.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a8b21c7d94"
down_revision: Union[str, None] = "e7c1a4d93b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gs_contatos_usina",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plant_link_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("telefone", sa.String(length=20), nullable=False),
        sa.Column("papel", sa.String(length=60), nullable=True),
        sa.Column("aceite_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aceite_por", sa.Integer(), nullable=True),
        sa.Column("ativo", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("criado_por", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["aceite_por"], ["gs_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["criado_por"], ["gs_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plant_link_id"], ["gs_plant_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plant_link_id", "telefone", name="uq_gs_contato_usina"),
    )
    op.create_index(op.f("ix_gs_contatos_usina_plant_link_id"), "gs_contatos_usina", ["plant_link_id"])
    op.create_index(op.f("ix_gs_contatos_usina_telefone"), "gs_contatos_usina", ["telefone"])

    op.create_table(
        "gs_contato_preferencias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contato_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("criada_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contato_id"], ["gs_contatos_usina.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contato_id", "tipo", name="uq_gs_contato_pref"),
    )
    op.create_index(op.f("ix_gs_contato_preferencias_contato_id"), "gs_contato_preferencias", ["contato_id"])
    op.create_index(op.f("ix_gs_contato_preferencias_tipo"), "gs_contato_preferencias", ["tipo"])

    op.add_column("gs_notificacoes_enviadas", sa.Column("contato_id", sa.Integer(), nullable=True))
    op.alter_column("gs_notificacoes_enviadas", "user_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        "fk_gs_notificacoes_contato",
        "gs_notificacoes_enviadas",
        "gs_contatos_usina",
        ["contato_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_gs_notificacao_contato", "gs_notificacoes_enviadas", ["contato_id", "chave"]
    )
    op.create_index(
        op.f("ix_gs_notificacoes_enviadas_contato_id"), "gs_notificacoes_enviadas", ["contato_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_gs_notificacoes_enviadas_contato_id"), table_name="gs_notificacoes_enviadas")
    op.drop_constraint("uq_gs_notificacao_contato", "gs_notificacoes_enviadas", type_="unique")
    op.drop_constraint("fk_gs_notificacoes_contato", "gs_notificacoes_enviadas", type_="foreignkey")
    op.alter_column("gs_notificacoes_enviadas", "user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("gs_notificacoes_enviadas", "contato_id")
    op.drop_table("gs_contato_preferencias")
    op.drop_table("gs_contatos_usina")
