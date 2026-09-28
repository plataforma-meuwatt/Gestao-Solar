"""A empresa de O&M como inquilino: gs_empresas e empresa_id

Revision ID: b1e7c9a24d03
Revises: a9d4e6f1c2b7
Create Date: 2026-09-28

Primeiro passo do multiempresa. Faz o mínimo que não quebra nada em produção:

- cria `gs_empresas`;
- acrescenta `empresa_id` **nulo** em usuários, usinas e integrações.

**Nada é preenchido aqui, e a coluna nasce nula de propósito.** Preencher exigiria decidir,
dentro de uma migration, de qual empresa é cada linha — e é decisão de quem opera, não de
quem migra. Com a coluna nula o sistema segue funcionando exatamente como antes: as rotas
da plataforma veem tudo, como sempre viram, e o portão da empresa recusa conta sem
vínculo (`gestor_empresa_atual`), que é o comportamento certo enquanto ninguém foi ligado.

`gs_users.empresa` (o texto livre) **continua existindo**. Sai numa migration posterior,
depois de a coluna nova estar em uso e conferida — é o que mantém este passo reversível.

As chaves são `RESTRICT`: apagar empresa com usuário ou usina é recusado pelo banco. O
caminho de tirar uma empresa de operação é `ativa=false`, que preserva o histórico.
"""

import sqlalchemy as sa
from alembic import op

revision = "b1e7c9a24d03"
down_revision = "a9d4e6f1c2b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_empresas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("documento", sa.String(length=20), nullable=True),
        sa.Column("ativa", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_gs_empresas_nome", "gs_empresas", ["nome"], unique=True)

    for tabela in ("gs_users", "gs_plant_links", "gs_integracoes"):
        op.add_column(tabela, sa.Column("empresa_id", sa.Integer(), nullable=True))
        op.create_index(f"ix_{tabela}_empresa_id", tabela, ["empresa_id"])
        op.create_foreign_key(
            f"fk_{tabela}_empresa",
            tabela,
            "gs_empresas",
            ["empresa_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    for tabela in ("gs_integracoes", "gs_plant_links", "gs_users"):
        op.drop_constraint(f"fk_{tabela}_empresa", tabela, type_="foreignkey")
        op.drop_index(f"ix_{tabela}_empresa_id", table_name=tabela)
        op.drop_column(tabela, "empresa_id")

    op.drop_index("ix_gs_empresas_nome", table_name="gs_empresas")
    op.drop_table("gs_empresas")
