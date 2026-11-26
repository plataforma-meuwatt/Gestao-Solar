"""GS: o índice de dispositivos (`gs_device_links`), o índice de usinas um andar abaixo. Guarda-chuva, fase 2, 26/11/2026.

Aditiva: nasce a tabela, vazia. Uma linha por POSIÇÃO de equipamento da usina (transformador e inversor nesta fase,
vindos do meuWatt pela porta da máquina); o tipo é conferido no código, e as colunas do meuPlano e do TermoVision já
existem para as fases seguintes não pedirem outra migração. Idempotente: confere antes de criar.

Revisão: b8d0f2a4c6e9
Anterior: a7c9e1b3d5f8
"""

import sqlalchemy as sa
from alembic import op

revision = "b8d0f2a4c6e9"
down_revision = "a7c9e1b3d5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "gs_device_links" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    agora = sa.func.now()
    op.create_table(
        "gs_device_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plant_link_id", sa.Integer(), sa.ForeignKey("gs_plant_links.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("nome", sa.String(160), nullable=False),
        sa.Column("pai_id", sa.Integer(), sa.ForeignKey("gs_device_links.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mw_ref", sa.String(60), nullable=True),
        sa.Column("mp_node_id", sa.Integer(), nullable=True),
        sa.Column("tv_ref", sa.String(60), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ausente_desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=agora, nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=agora, nullable=False),
    )
    op.create_index("ix_gs_device_links_plant_link_id", "gs_device_links", ["plant_link_id"])
    op.create_index("ix_gs_device_links_pai_id", "gs_device_links", ["pai_id"])
    op.create_index("ix_gs_device_links_atualizado_em", "gs_device_links", ["atualizado_em"])
    op.create_index("ux_gs_device_links_mw_ref", "gs_device_links", ["mw_ref"], unique=True,
                    postgresql_where=sa.text("mw_ref IS NOT NULL"), sqlite_where=sa.text("mw_ref IS NOT NULL"))
    op.create_index("ux_gs_device_links_mp_node", "gs_device_links", ["mp_node_id"], unique=True,
                    postgresql_where=sa.text("mp_node_id IS NOT NULL"), sqlite_where=sa.text("mp_node_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("gs_device_links")
