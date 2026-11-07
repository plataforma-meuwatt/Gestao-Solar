"""Bot: a classificação de paradas pelo WhatsApp guarda onde a pessoa está (uma por pessoa, vale 12 h).

Pedido do dono (07/11/2026): "Caíram várias usinas hoje, quero um fluxo HIPER COMPLETO e DIDÁTICO no WhatsApp para eu
classificar as paradas sem precisar ir no site." O passo a passo é do sistema (não da IA) e sobrevive a um deploy.

Revisão: b7d9f1a3c5e8
Anterior: f5a7c9e1b3d4
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d9f1a3c5e8"
down_revision = "f5a7c9e1b3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_fluxos_paradas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gs_user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False,
                  unique=True),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gs_fluxos_paradas")
