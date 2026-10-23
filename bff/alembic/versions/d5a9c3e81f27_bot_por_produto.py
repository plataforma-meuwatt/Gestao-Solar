"""Acesso ao assistente do WhatsApp POR PRODUTO: meuPlano, meuWatt, helper.

O gerente da O&M libera um, dois ou todos no oem-gs. Quem tinha a chave única
(`bot_whatsapp`) fica com meuPlano e meuWatt — o que o bot respondia até aqui.

Revisão: d5a9c3e81f27
Anterior: c3f8a1d27e60
"""

import sqlalchemy as sa
from alembic import op

revision = "d5a9c3e81f27"
down_revision = "c3f8a1d27e60"
branch_labels = None
depends_on = None

_PRODUTOS = ("bot_meuplano", "bot_meuwatt", "bot_helper")


def upgrade() -> None:
    for c in _PRODUTOS:
        op.add_column("gs_users", sa.Column(c, sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE gs_users SET bot_meuplano = bot_whatsapp, bot_meuwatt = bot_whatsapp")
    # `bot_whatsapp` fica (sem uso) até a próxima migration: apagá-la aqui derrubaria a versão
    # anterior, ainda no ar durante a troca de contêiner, em toda leitura de conta.


def downgrade() -> None:
    op.execute("UPDATE gs_users SET bot_whatsapp = (bot_meuplano OR bot_meuwatt OR bot_helper)")
    for c in _PRODUTOS:
        op.drop_column("gs_users", c)
