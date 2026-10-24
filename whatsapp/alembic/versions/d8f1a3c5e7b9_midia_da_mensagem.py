"""`wa_mensagens.midia`: o arquivo de áudio, documento ou imagem que a mensagem trouxe.

A Meta não manda o conteúdo no corpo, só o id do arquivo; sem guardá-lo, o bot não tinha como
ouvir a nota de voz (avaliação 11: o bot anterior no mesmo número transcrevia áudio).

Revisão: d8f1a3c5e7b9
Anterior: c5e7a9b1d3f2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8f1a3c5e7b9"
down_revision: Union[str, None] = "c5e7a9b1d3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wa_mensagens", sa.Column("midia", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("wa_mensagens", "midia")
