"""Acessos: quem fez a mudança (a senha redefinida por outra pessoa, o acesso mudado, a origem da troca de papel) e
em qual empresa ela aconteceu.

A tela Acessos (24/11/2026) diz "por quem"; a conta da plataforma aparece como "equipe da plataforma" para a empresa.

Revisão: f3c5e7a9b1d3
Anterior: d4f6b8c0e2a4
"""

import sqlalchemy as sa
from alembic import op

revision = "f3c5e7a9b1d3"
down_revision = "d4f6b8c0e2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # idempotente: as colunas entraram em produção antes do deploy (aditivas, o código anterior não as lê)
    tem = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("gs_acessos")}
    if "por_id" not in tem:
        op.add_column("gs_acessos", sa.Column("por_id", sa.Integer(),
                                              sa.ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True))
    if "empresa_id" not in tem:
        op.add_column("gs_acessos", sa.Column("empresa_id", sa.Integer(),
                                              sa.ForeignKey("gs_empresas.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("gs_acessos", "empresa_id")
    op.drop_column("gs_acessos", "por_id")
