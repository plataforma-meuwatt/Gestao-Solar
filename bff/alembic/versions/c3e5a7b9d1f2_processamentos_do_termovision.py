"""Bot: os pedidos de "Processar <usina>" ao TermoVision (o aviso de cada etapa acha quem pediu).

Revisão: c3e5a7b9d1f2
Anterior: 1ca500d053c3
"""

import sqlalchemy as sa
from alembic import op

revision = "c3e5a7b9d1f2"
down_revision = "1ca500d053c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_processamentos_tv",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(80), nullable=False, unique=True),
        sa.Column("gs_user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telefone", sa.String(30), nullable=False),
        sa.Column("usina", sa.String(200), nullable=False),
        sa.Column("avisado", sa.String(300), nullable=False, server_default=""),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gs_processamentos_tv")
