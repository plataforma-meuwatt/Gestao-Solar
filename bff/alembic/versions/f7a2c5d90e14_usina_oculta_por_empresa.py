"""A empresa pode esconder da lista a usina que não lhe interessa

Revision ID: f7a2c5d90e14
Revises: e5c9a71d3b82
Create Date: 2026-09-29

O token de uma empresa alcança tudo o que a conta dela enxerga nos produtos — no primeiro
caso real, 6 usinas no meuWatt e 17 no meuPlano. Boa parte não interessa, e sem um jeito de
dizer "esta não" elas ficam para sempre na lista de trazer.

É preferência de TELA, desta empresa: nenhuma outra consulta do sistema lê esta tabela.
Esconder uma usina não pode mudar o que o dono dela vê no aplicativo.
"""

import sqlalchemy as sa
from alembic import op

revision = "f7a2c5d90e14"
down_revision = "e5c9a71d3b82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_usinas_ocultas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("produto", sa.String(length=20), nullable=False),
        sa.Column("identificador", sa.String(length=120), nullable=False),
        sa.Column(
            "ocultada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["gs_empresas.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("empresa_id", "produto", "identificador", name="uq_gs_usina_oculta"),
    )
    op.create_index("ix_gs_usinas_ocultas_empresa_id", "gs_usinas_ocultas", ["empresa_id"])


def downgrade() -> None:
    op.drop_index("ix_gs_usinas_ocultas_empresa_id", table_name="gs_usinas_ocultas")
    op.drop_table("gs_usinas_ocultas")
