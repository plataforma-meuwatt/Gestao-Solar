"""TermoVision: o ACESSO pelo Gestão Solar, como o do meuGuarda.

Pedido do dono (11/11/2026): "quero login do termovision pelo GESTÃO SOLAR igual tem no meuguarda. Hoje tem meuplano,
mas vai passar a ser GESTÃO SOLAR". O gerente libera aqui (tela Usuários); vai na asserção do "Entrar com o Gestão
Solar" e o TermoVision recusa o falso. Quem já existe fica liberado; conta nova nasce sem.

Revisão: e4a6c8d0f2b4
Anterior: d1f3a5b7c9e2
"""

import sqlalchemy as sa
from alembic import op

revision = "e4a6c8d0f2b4"
down_revision = "d1f3a5b7c9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gs_users", sa.Column("termovision_liberado", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column("gs_users", "termovision_liberado", server_default=sa.false())


def downgrade() -> None:
    op.drop_column("gs_users", "termovision_liberado")
