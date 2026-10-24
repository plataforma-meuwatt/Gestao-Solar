"""Senha de atuação: a que o bot pede antes de qualquer AÇÃO (helper ou meuPlano).

Pedido do dono (24/10/2026): "é preciso que o bot peça senha para qualquer ação que envolva
atuação (desligar, ligar, gravar); ler não precisa". Só números (4 a 8), guardada como a
senha de login (pbkdf2), separada dela — a de login nunca é digitada no WhatsApp.

Revisão: b3c5d7e9f1a2
Anterior: a8e4f2c61b90
"""

import sqlalchemy as sa
from alembic import op

revision = "b3c5d7e9f1a2"
down_revision = "a8e4f2c61b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gs_users", sa.Column("senha_atuacao_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("gs_users", "senha_atuacao_hash")
