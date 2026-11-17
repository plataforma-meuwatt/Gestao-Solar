"""O medidor de tokens do bot: o gasto de IA de cada mensagem no log (`gs_bot_registros`).

Pedido do dono (17/11/2026): "Quero que você instale um medidor de tokens e deixe isso para o gestor … dados por dia, mês
e tudo". Linhas de antes ficam nulas (não medidas).

Revisão: 1ca500d053c3
Anterior: 931cf66cacf1
"""

import sqlalchemy as sa
from alembic import op

revision = "1ca500d053c3"
down_revision = "931cf66cacf1"
branch_labels = None
depends_on = None

COLUNAS = ("chamadas_ia", "tokens_entrada", "tokens_cache", "tokens_saida")


def upgrade() -> None:
    for c in COLUNAS:
        op.add_column("gs_bot_registros", sa.Column(c, sa.Integer(), nullable=True))


def downgrade() -> None:
    for c in COLUNAS:
        op.drop_column("gs_bot_registros", c)
