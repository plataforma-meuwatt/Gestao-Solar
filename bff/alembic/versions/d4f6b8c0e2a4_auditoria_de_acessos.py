"""GS: a auditoria dos acessos (cada entrada e cada passe a outro sistema, por pessoa).

Pedido do dono (24/11/2026): "o GS é o detentor dos acessos, quero que ele tenha a auditoria completa dos logs de
acessos de cada pessoa".

Revisão: d4f6b8c0e2a4
Anterior: c3e5a7b9d1f2
"""

import sqlalchemy as sa
from alembic import op

revision = "d4f6b8c0e2a4"
down_revision = "c3e5a7b9d1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_acessos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gs_user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("login", sa.String(160), nullable=False, server_default=""),
        sa.Column("acao", sa.String(20), nullable=False),
        sa.Column("sistema", sa.String(20), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("motivo", sa.String(200), nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("aparelho", sa.String(300), nullable=False, server_default=""),
    )
    op.create_index("ix_gs_acessos_conta_em", "gs_acessos", ["gs_user_id", "em"])
    op.create_index("ix_gs_acessos_em", "gs_acessos", ["em"])


def downgrade() -> None:
    op.drop_index("ix_gs_acessos_em", "gs_acessos")
    op.drop_index("ix_gs_acessos_conta_em", "gs_acessos")
    op.drop_table("gs_acessos")
