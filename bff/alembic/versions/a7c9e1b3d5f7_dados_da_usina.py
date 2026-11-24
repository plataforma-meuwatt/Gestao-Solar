"""GS: os dados básicos da usina com histórico, o "atualizado em" e as usinas a confirmar (Plano Casa GS, R10).

24/11/2026. Aditiva: a usina ganha `atualizado_em` (o de agora para as que existem); nascem o histórico (uma linha por
campo mudado: quem, de qual sistema, o antes e o depois) e a fila das usinas criadas em outro sistema que parecem uma
que já existe (o gerente da O&M decide). Idempotente: confere antes de criar.

Revisão: a7c9e1b3d5f7
Anterior: e6a8c0d2f4b6
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c9e1b3d5f7"
down_revision = "e6a8c0d2f4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "atualizado_em" not in {c["name"] for c in insp.get_columns("gs_plant_links")}:
        op.add_column("gs_plant_links", sa.Column("atualizado_em", sa.DateTime(timezone=True),
                                                  server_default=sa.func.now(), nullable=False))
        op.create_index("ix_gs_plant_links_atualizado_em", "gs_plant_links", ["atualizado_em"])
    tabelas = set(insp.get_table_names())
    if "gs_usinas_historico" not in tabelas:
        op.create_table(
            "gs_usinas_historico",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("plant_link_id", sa.Integer(), sa.ForeignKey("gs_plant_links.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("campo", sa.String(40), nullable=False),
            sa.Column("antes", sa.String(400), nullable=True),
            sa.Column("depois", sa.String(400), nullable=True),
            sa.Column("por_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("sistema", sa.String(20), nullable=False),
            sa.Column("motivo", sa.String(200), nullable=False, server_default=""),
            sa.Column("em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_gs_usinas_historico_plant_link_id", "gs_usinas_historico", ["plant_link_id"])
        op.create_index("ix_gs_usinas_historico_em", "gs_usinas_historico", ["em"])
    if "gs_usinas_a_confirmar" not in tabelas:
        op.create_table(
            "gs_usinas_a_confirmar",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("gs_empresas.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sistema", sa.String(20), nullable=False),
            sa.Column("referencia", sa.String(120), nullable=False),
            sa.Column("dados", sa.JSON(), nullable=False),
            sa.Column("parecidas", sa.JSON(), nullable=False),
            sa.Column("pedido_por_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("decisao", sa.String(20), nullable=True),
            sa.Column("usina_id", sa.Integer(), sa.ForeignKey("gs_plant_links.id", ondelete="SET NULL"), nullable=True),
            sa.Column("decidido_por_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("decidido_em", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("sistema", "referencia", name="ux_gs_usinas_a_confirmar_ref"),
        )
        op.create_index("ix_gs_usinas_a_confirmar_empresa_id", "gs_usinas_a_confirmar", ["empresa_id"])


def downgrade() -> None:
    op.drop_table("gs_usinas_a_confirmar")
    op.drop_table("gs_usinas_historico")
    op.drop_index("ix_gs_plant_links_atualizado_em", "gs_plant_links")
    op.drop_column("gs_plant_links", "atualizado_em")
