"""GS: a usina ganha o código do TermoVision (o mapa mora lá), o endereço e a coordenada (os dados básicos moram aqui).

Plano Casa GS, 24/11/2026. Aditiva: nada existente muda; tudo nasce vazio.

Revisão: e6a8c0d2f4b6
Anterior: f3c5e7a9b1d3
"""

import sqlalchemy as sa
from alembic import op

revision = "e6a8c0d2f4b6"
down_revision = "f3c5e7a9b1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gs_plant_links", sa.Column("tv_codigo", sa.String(40), nullable=True))
    op.add_column("gs_plant_links", sa.Column("endereco", sa.String(300), nullable=True))
    op.add_column("gs_plant_links", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("gs_plant_links", sa.Column("longitude", sa.Float(), nullable=True))
    op.create_index("ux_gs_plant_links_tv_codigo", "gs_plant_links", ["tv_codigo"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_gs_plant_links_tv_codigo", "gs_plant_links")
    for c in ("longitude", "latitude", "endereco", "tv_codigo"):
        op.drop_column("gs_plant_links", c)
