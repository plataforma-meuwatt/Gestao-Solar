"""`wa_mensagens.botao`: o id do botão tocado ("sim:<código do resumo>").

O título ("Sim") não diz de QUAL resumo era o botão, e o WhatsApp mantém os botões das mensagens
antigas: o toque no Sim de um resumo antigo confirmava a ação de agora (avaliação 13). Guardado
aqui para a varredura também o repassar ao bot.

Revisão: e2b4d6f8a0c1
Anterior: d8f1a3c5e7b9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2b4d6f8a0c1"
down_revision: Union[str, None] = "d8f1a3c5e7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wa_mensagens", sa.Column("botao", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("wa_mensagens", "botao")
