"""micro usina no vínculo da usina

Revision ID: a9d4e6f1c2b7
Revises: f3a8b21c7d94
Create Date: 2026-09-28

`gs_plant_links.mw_micro_plant_id` — o id da micro usina no MICRO do meuWatt (usinas que
vêm dos portais dos fabricantes). É o que deixa o motor avisar "usina parada" para uma
usina que o monitoramento do meuWatt não conhece, pelos alertas de `GET /micro/alerts`.
Anulável e sem UNIQUE no banco, como `mw_plant_slug` e `mp_usina_id`: o conflito (duas
usinas daqui apontando para a mesma de lá) é recusado pela rota, com o nome da outra.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4e6f1c2b7"
down_revision: Union[str, None] = "f3a8b21c7d94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gs_plant_links", sa.Column("mw_micro_plant_id", sa.Integer(), nullable=True))
    op.create_index("ix_gs_plant_links_mw_micro_plant_id", "gs_plant_links", ["mw_micro_plant_id"])


def downgrade() -> None:
    op.drop_index("ix_gs_plant_links_mw_micro_plant_id", table_name="gs_plant_links")
    with op.batch_alter_table("gs_plant_links") as batch:
        batch.drop_column("mw_micro_plant_id")
