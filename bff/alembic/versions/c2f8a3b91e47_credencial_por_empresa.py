"""A credencial dos produtos passa a ser por empresa

Revision ID: c2f8a3b91e47
Revises: b1e7c9a24d03
Create Date: 2026-09-28

Cada empresa de O&M tem a conta dela no meuWatt e no meuPlano (decisão do dono,
28/09/2026), e `gs_integracoes` tinha `produto` **único**: uma credencial por produto no
sistema inteiro. Com ela, a segunda empresa simplesmente não conseguia gravar a conta
dela — o erro chegava como violação de constraint, longe da causa.

A unicidade vira duas, e são duas porque no Postgres **dois NULL não colidem**:

- `uq_gs_integracao_empresa` — uma linha por (produto, empresa), quando há empresa;
- `uq_gs_integracao_plataforma` — uma linha por produto entre as da plataforma.

Um `UNIQUE (produto, empresa_id)` sozinho deixaria passar duas linhas de plataforma para
o mesmo produto, que é justamente a ambiguidade que ele deveria impedir: o sistema
escolheria uma das duas credenciais por ordem de `id`, em silêncio.

Nada é movido: a linha de hoje já tem `empresa_id` nulo e continua sendo a da plataforma.
"""

import sqlalchemy as sa
from alembic import op

revision = "c2f8a3b91e47"
down_revision = "b1e7c9a24d03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # O nome do único antigo varia com quem criou o schema. No banco de produção ele é
    # `gs_integracoes_produto_key` (conferido em 28/09/2026, direto no Postgres), que é o
    # nome que o Postgres dá a um `UNIQUE` inline de coluna; num banco montado pelo
    # `create_all` ele pode ser outro. Por isso: inspeciona quando dá, e cai no nome
    # conhecido quando não dá — o modo `--sql` (`as_sql`) não tem conexão para inspecionar.
    if op.get_context().as_sql:
        op.drop_constraint("gs_integracoes_produto_key", "gs_integracoes", type_="unique")
    else:
        inspetor = sa.inspect(op.get_bind())
        for indice in inspetor.get_indexes("gs_integracoes"):
            if indice.get("unique") and indice.get("column_names") == ["produto"]:
                op.drop_index(indice["name"], table_name="gs_integracoes")
        for restricao in inspetor.get_unique_constraints("gs_integracoes"):
            if restricao.get("column_names") == ["produto"]:
                op.drop_constraint(restricao["name"], "gs_integracoes", type_="unique")

    op.create_index("ix_gs_integracoes_produto", "gs_integracoes", ["produto"])
    op.create_index(
        "uq_gs_integracao_empresa",
        "gs_integracoes",
        ["produto", "empresa_id"],
        unique=True,
        postgresql_where=sa.text("empresa_id IS NOT NULL"),
        sqlite_where=sa.text("empresa_id IS NOT NULL"),
    )
    op.create_index(
        "uq_gs_integracao_plataforma",
        "gs_integracoes",
        ["produto"],
        unique=True,
        postgresql_where=sa.text("empresa_id IS NULL"),
        sqlite_where=sa.text("empresa_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_gs_integracao_plataforma", table_name="gs_integracoes")
    op.drop_index("uq_gs_integracao_empresa", table_name="gs_integracoes")
    op.drop_index("ix_gs_integracoes_produto", table_name="gs_integracoes")
    # Só volta a ser único por produto se não houver credencial de empresa gravada — o
    # contrário apagaria a conta de alguém para caber na restrição antiga.
    op.create_index("ix_gs_integracoes_produto", "gs_integracoes", ["produto"], unique=True)
