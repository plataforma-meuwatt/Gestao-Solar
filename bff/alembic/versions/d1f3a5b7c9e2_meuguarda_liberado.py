"""meuGuarda: o ACESSO separado da atuação pelo WhatsApp.

Decisão do dono (11/11/2026, sobre o mockup da tela Usuários): o gerente do GS libera o meuGuarda como um dos acessos
da pessoa; lá se dão as permissões; aqui só se liga a atuação pelo WhatsApp (desarmar). "Desligar no GS = fica fora do
meuGuarda". `meuguarda_liberado` é o acesso (vai no `/eu` e na asserção do SSO); `bot_meuguarda` passa a ser só a
atuação. Quem já existe fica liberado (nada para de funcionar); conta nova nasce sem, e o gerente libera.

Revisão: d1f3a5b7c9e2
Anterior: c9e1a3b5d7f2
"""

import sqlalchemy as sa
from alembic import op

revision = "d1f3a5b7c9e2"
down_revision = "c9e1a3b5d7f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gs_users", sa.Column("meuguarda_liberado", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column("gs_users", "meuguarda_liberado", server_default=sa.false())


def downgrade() -> None:
    op.drop_column("gs_users", "meuguarda_liberado")
