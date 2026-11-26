"""GS: automações (gatilho, condição, ação, entrega) e a memória do bot por pessoa. Plano Assistente GS, 26/11/2026.

Aditiva: nascem `gs_automacoes` (a regra), `gs_automacao_disparos` (todo disparo, inclusive em ensaio) e
`gs_bot_memorias` (o que a pessoa pediu para o bot lembrar, cifrado). Nenhuma regra nasce com a migração: o motor de
um minuto não faz nada até alguém pedir uma pelo bot. Idempotente.

Revisão: a7c9e1b3d5f8
Anterior: c2e4a6b8d0f2
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c9e1b3d5f8"
down_revision = "c2e4a6b8d0f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tabelas = set(sa.inspect(op.get_bind()).get_table_names())
    agora = sa.func.now()
    if "gs_automacoes" not in tabelas:
        op.create_table(
            "gs_automacoes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("gs_empresas.id", ondelete="SET NULL"), nullable=True),
            sa.Column("nome", sa.String(160), nullable=False),
            sa.Column("texto_original", sa.Text(), nullable=True),
            sa.Column("gatilho", sa.JSON(), nullable=False),
            sa.Column("condicoes", sa.JSON(), nullable=True),
            sa.Column("escopo", sa.JSON(), nullable=True),
            sa.Column("acao", sa.JSON(), nullable=False),
            sa.Column("entrega", sa.JSON(), nullable=True),
            sa.Column("situacao", sa.String(20), nullable=False),
            sa.Column("estado", sa.JSON(), nullable=True),
            sa.Column("proxima_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rodando_ate", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ultima_volta_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ultimo_erro", sa.Text(), nullable=True),
            sa.Column("origem", sa.String(20), nullable=False, server_default="bot"),
            sa.Column("criada_em", sa.DateTime(timezone=True), server_default=agora, nullable=False),
            sa.Column("atualizada_em", sa.DateTime(timezone=True), server_default=agora, nullable=False),
            sa.Column("apagada_em", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_gs_automacoes_user_id", "gs_automacoes", ["user_id"])
        op.create_index("ix_gs_automacoes_empresa_id", "gs_automacoes", ["empresa_id"])
        op.create_index("ix_gs_automacoes_situacao", "gs_automacoes", ["situacao"])
        op.create_index("ix_gs_automacoes_proxima_em", "gs_automacoes", ["proxima_em"])
    if "gs_automacao_disparos" not in tabelas:
        op.create_table(
            "gs_automacao_disparos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("automacao_id", sa.Integer(), sa.ForeignKey("gs_automacoes.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("plant_link_id", sa.Integer(), sa.ForeignKey("gs_plant_links.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("em", sa.DateTime(timezone=True), server_default=agora, nullable=False),
            sa.Column("evento", sa.String(20), nullable=False),
            sa.Column("ensaio", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("chave", sa.String(200), nullable=False),
            sa.Column("texto", sa.Text(), nullable=False),
            sa.Column("leitura", sa.JSON(), nullable=True),
            sa.Column("canal", sa.String(30), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("erro", sa.Text(), nullable=True),
            sa.Column("notificacao_id", sa.Integer(),
                      sa.ForeignKey("gs_notificacoes_enviadas.id", ondelete="SET NULL"), nullable=True),
            sa.Column("entregue_em", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("automacao_id", "chave", "user_id", "ensaio", name="uq_gs_automacao_disparo"),
        )
        op.create_index("ix_gs_automacao_disparos_automacao_id", "gs_automacao_disparos", ["automacao_id"])
        op.create_index("ix_gs_automacao_disparos_em", "gs_automacao_disparos", ["em"])
    if "gs_bot_memorias" not in tabelas:
        op.create_table(
            "gs_bot_memorias",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tipo", sa.String(20), nullable=False),
            sa.Column("texto_cifrado", sa.Text(), nullable=False),
            sa.Column("origem", sa.String(20), nullable=False, server_default="bot"),
            sa.Column("criada_em", sa.DateTime(timezone=True), server_default=agora, nullable=False),
            sa.Column("atualizada_em", sa.DateTime(timezone=True), server_default=agora, nullable=False),
            sa.Column("apagada_em", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_gs_bot_memorias_user_id", "gs_bot_memorias", ["user_id"])


def downgrade() -> None:
    op.drop_table("gs_bot_memorias")
    op.drop_table("gs_automacao_disparos")
    op.drop_table("gs_automacoes")
