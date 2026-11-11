"""Bot: a parte das CÂMERAS (meuGuarda), ligada para todos que já usam o bot.

Decisão do dono (11/11/2026): "ligar para todos". Quem o bot já atende (celular e uma parte ligada com o token
dela) passa a ter também a do meuGuarda; o gerente desliga pessoa a pessoa no oem-gs (Bot do WhatsApp). Não pede
token: o meuGuarda confere a sessão do GS da própria pessoa.

Revisão: c9e1a3b5d7f2
Anterior: b7d9f1a3c5e8
"""

import sqlalchemy as sa
from alembic import op

revision = "c9e1a3b5d7f2"
down_revision = "b7d9f1a3c5e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gs_users", sa.Column("bot_meuguarda", sa.Boolean(), nullable=False, server_default=sa.false()))
    # "Já usa" = o bot responde hoje: celular e uma parte ligada COM o token dela (`User.bot_ativo`). Quem estava parado
    # por falta de token não passa a ser atendido só pelas câmeras.
    op.execute("""
        UPDATE gs_users u SET bot_meuguarda = true
        WHERE u.telefone IS NOT NULL AND EXISTS (
            SELECT 1 FROM gs_vinculos_produto v WHERE v.gs_user_id = u.id AND v.token_cifrado IS NOT NULL
              AND ((v.produto = 'meuplano' AND u.bot_meuplano) OR (v.produto = 'meuwatt' AND (u.bot_meuwatt OR u.bot_helper))))
    """)


def downgrade() -> None:
    op.drop_column("gs_users", "bot_meuguarda")
