"""A empresa daqui aponta para a do meuWatt e para a do meuPlano

Revision ID: d4b6e2f81a09
Revises: c2f8a3b91e47
Create Date: 2026-09-28

`gs_empresas` nasceu como cadastro e vira **vínculo**, que é o papel que ela precisa ter:
o meuWatt já tem `enterprises` (com usina e funcionário pendurados) e o meuPlano tem
`tenants`, os dois independentes de propósito — alguém pode contratar só a manutenção e
nunca existir no monitoramento.

Nenhum dos dois é "o certo", e nenhum dos dois sabe do outro. O que faltava é quem diga
que aquela empresa de lá e aquela de lá são a mesma — e é isto. Mesmo papel de
`gs_plant_links` para usina, com os mesmos três casos: nos dois, só num, só no outro.

Únicos parciais pelo mesmo motivo de `gs_integracoes`: no Postgres dois NULL não colidem,
e o índice parcial diz a intenção por escrito. Duas linhas daqui apontando para a mesma
empresa de lá seriam dois inquilinos lendo a mesma carteira.
"""

import sqlalchemy as sa
from alembic import op

revision = "d4b6e2f81a09"
down_revision = "c2f8a3b91e47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gs_empresas", sa.Column("mw_enterprise_id", sa.Integer(), nullable=True))
    op.add_column("gs_empresas", sa.Column("mp_tenant_id", sa.Integer(), nullable=True))

    op.create_index("ix_gs_empresas_mw_enterprise_id", "gs_empresas", ["mw_enterprise_id"])
    op.create_index("ix_gs_empresas_mp_tenant_id", "gs_empresas", ["mp_tenant_id"])

    op.create_index(
        "uq_gs_empresa_mw",
        "gs_empresas",
        ["mw_enterprise_id"],
        unique=True,
        postgresql_where=sa.text("mw_enterprise_id IS NOT NULL"),
        sqlite_where=sa.text("mw_enterprise_id IS NOT NULL"),
    )
    op.create_index(
        "uq_gs_empresa_mp",
        "gs_empresas",
        ["mp_tenant_id"],
        unique=True,
        postgresql_where=sa.text("mp_tenant_id IS NOT NULL"),
        sqlite_where=sa.text("mp_tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_gs_empresa_mp", table_name="gs_empresas")
    op.drop_index("uq_gs_empresa_mw", table_name="gs_empresas")
    op.drop_index("ix_gs_empresas_mp_tenant_id", table_name="gs_empresas")
    op.drop_index("ix_gs_empresas_mw_enterprise_id", table_name="gs_empresas")
    op.drop_column("gs_empresas", "mp_tenant_id")
    op.drop_column("gs_empresas", "mw_enterprise_id")
