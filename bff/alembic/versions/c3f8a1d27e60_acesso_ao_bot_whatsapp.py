"""Acesso ao assistente do WhatsApp por conta (`gs_users.bot_whatsapp`).

O gerente da O&M libera no adm-oem; o bot só atende celular cadastrado com a chave ligada.

Revisão: c3f8a1d27e60
Anterior: b7e2d4c91a05
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f8a1d27e60"
down_revision = "b7e2d4c91a05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gs_users", sa.Column("bot_whatsapp", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("gs_users", "bot_whatsapp")
