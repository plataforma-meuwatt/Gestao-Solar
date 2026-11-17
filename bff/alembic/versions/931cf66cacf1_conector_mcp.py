"""Conector do Claude pelo Gestão Solar: os tokens que o Claude de cada pessoa guarda.

Pedido do dono (17/11/2026): "E se fizer isso como se fosse mcp do gestao solar ai fica um so para todos sistemas.
Igual é o bot hoje". Só o hash do token fica aqui (`api/v1/mcp.py`).

Revisão: 931cf66cacf1
Anterior: e4a6c8d0f2b4
"""

import sqlalchemy as sa
from alembic import op

revision = "931cf66cacf1"
down_revision = "e4a6c8d0f2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_mcp_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revogado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_uso_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gs_mcp_tokens_user_id", "gs_mcp_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_gs_mcp_tokens_user_id", table_name="gs_mcp_tokens")
    op.drop_table("gs_mcp_tokens")
