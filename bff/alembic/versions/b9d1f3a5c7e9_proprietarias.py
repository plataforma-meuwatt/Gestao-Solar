"""GS: as proprietárias (as donas das usinas) moram no GS, ligadas à organização delas no meuPlano (Plano Casa GS, R11).

24/11/2026. Aditiva: nasce `gs_proprietarias`; a usina e a pessoa ganham `proprietaria_id` (nulo para todas: a
importação do meuPlano preenche). E a trava única do slug do meuWatt e do número do meuPlano em `gs_plant_links` (sem
duplicados em produção, conferido em 24/11). Idempotente.

Revisão: b9d1f3a5c7e9
Anterior: a7c9e1b3d5f7
"""

import sqlalchemy as sa
from alembic import op

revision = "b9d1f3a5c7e9"
down_revision = "a7c9e1b3d5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "gs_proprietarias" not in set(insp.get_table_names()):
        op.create_table(
            "gs_proprietarias",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nome", sa.String(255), nullable=False),
            sa.Column("documento", sa.String(20), nullable=True),
            sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("gs_empresas.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("mp_owner_id", sa.Integer(), nullable=True),
            sa.Column("mw_enterprise_id", sa.Integer(), nullable=True),
            sa.Column("ativa", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("criada_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("empresa_id", "nome", name="uq_gs_proprietaria_nome"),
        )
        op.create_index("ix_gs_proprietarias_empresa_id", "gs_proprietarias", ["empresa_id"])
        op.create_index("uq_gs_proprietaria_mp", "gs_proprietarias", ["mp_owner_id"], unique=True,
                        postgresql_where=sa.text("mp_owner_id IS NOT NULL"),
                        sqlite_where=sa.text("mp_owner_id IS NOT NULL"))
    # o R10 revisto: a mesma usina de um produto numa usina daqui só (a corrida do registro duplicava)
    indices = {i["name"] for i in insp.get_indexes("gs_plant_links")}
    for nome, coluna in (("ux_gs_plant_links_mw_slug", "mw_plant_slug"), ("ux_gs_plant_links_mp_usina", "mp_usina_id")):
        if nome not in indices:
            op.create_index(nome, "gs_plant_links", [coluna], unique=True,
                            postgresql_where=sa.text(f"{coluna} IS NOT NULL"),
                            sqlite_where=sa.text(f"{coluna} IS NOT NULL"))
    for tabela in ("gs_plant_links", "gs_users"):
        if "proprietaria_id" not in {c["name"] for c in insp.get_columns(tabela)}:
            op.add_column(tabela, sa.Column("proprietaria_id", sa.Integer(),
                                            sa.ForeignKey("gs_proprietarias.id", ondelete="SET NULL"), nullable=True))
            op.create_index(f"ix_{tabela}_proprietaria_id", tabela, ["proprietaria_id"])


def downgrade() -> None:
    op.drop_index("ux_gs_plant_links_mp_usina", "gs_plant_links")
    op.drop_index("ux_gs_plant_links_mw_slug", "gs_plant_links")
    for tabela in ("gs_users", "gs_plant_links"):
        op.drop_index(f"ix_{tabela}_proprietaria_id", tabela)
        op.drop_column(tabela, "proprietaria_id")
    op.drop_table("gs_proprietarias")
