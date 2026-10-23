"""Conversas do assistente do WhatsApp (histórico por telefone).

Revisão: b7e2d4c91a05
Anterior: a1b4e7c20d36
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e2d4c91a05"
down_revision = "a1b4e7c20d36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_whatsapp_conversas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telefone", sa.String(20), nullable=False, unique=True),
        sa.Column("gs_user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("mensagens", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("atualizada_em", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gs_whatsapp_conversas")
