"""A pessoa agrupa as contas de um mesmo humano

Revision ID: e5c9a71d3b82
Revises: d4b6e2f81a09
Create Date: 2026-09-28

Uma conta é um PAPEL, e a mesma pessoa tem uma para cada um — gestor da plataforma,
gerente de uma empresa de O&M, dono de usina. Isso já era verdade (é por isso que quem
autentica é o apelido e não o e-mail); o que faltava era o sistema saber, para a troca de
papel não exigir sair e entrar de novo.

`gs_pessoas` é só o agrupamento e **não carrega poder nenhum**: nenhuma guarda a consulta,
e a sessão continua sendo de uma conta, com um perfil e um escopo.

A coluna nasce NULA em todas as contas — quem nunca agrupou nada continua com um papel só,
que é o comportamento de hoje.
"""

import sqlalchemy as sa
from alembic import op

revision = "e5c9a71d3b82"
down_revision = "d4b6e2f81a09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_pessoas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column("gs_users", sa.Column("pessoa_id", sa.Integer(), nullable=True))
    op.create_index("ix_gs_users_pessoa_id", "gs_users", ["pessoa_id"])
    op.create_foreign_key(
        "fk_gs_users_pessoa", "gs_users", "gs_pessoas", ["pessoa_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_gs_users_pessoa", "gs_users", type_="foreignkey")
    op.drop_index("ix_gs_users_pessoa_id", table_name="gs_users")
    op.drop_column("gs_users", "pessoa_id")
    op.drop_table("gs_pessoas")
