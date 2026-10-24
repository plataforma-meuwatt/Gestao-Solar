"""`wa_mensagens.wamid` de 80 para 255 caracteres.

Em 22–24/10/2026 a Meta passou a mandar `wamid` de 82 caracteres. O INSERT estourava
(StringDataRightTruncation), o evento ficava parado com `tentativas=0` e — porque a varredura
e o aviso ao BFF rodavam no mesmo `try` — nenhuma mensagem chegava mais ao bot.

Revisão: c5e7a9b1d3f2
Anterior: b3c4d5e6f7a8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e7a9b1d3f2"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "wa_mensagens", "wamid", type_=sa.String(255), existing_type=sa.String(80), existing_nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "wa_mensagens", "wamid", type_=sa.String(80), existing_type=sa.String(255), existing_nullable=True
    )
