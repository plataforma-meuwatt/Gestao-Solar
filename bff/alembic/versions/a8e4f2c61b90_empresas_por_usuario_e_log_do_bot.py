"""Usuário em mais de uma empresa, log do bot, e a plataforma sem token.

Pedidos do dono (23/10/2026):

- "um usuário pode estar em mais de uma empresa" → `gs_usuario_empresas` (a empresa de
  origem continua em `gs_users.empresa_id`; aqui ficam as outras);
- "vejo log dos bots" (adm-gs) → `gs_bot_registros`, uma linha por mensagem recebida;
- "adm não tem token" → a linha da PLATAFORMA em `gs_integracoes` (`empresa_id` nulo) fica
  só com o endereço dos produtos. Quem lê o meuWatt e o meuPlano é a conta de cada empresa.

E a limpeza prometida em `d5a9c3e81f27`: `gs_users.bot_whatsapp` sai (sem uso desde lá).

Revisão: a8e4f2c61b90
Anterior: d5a9c3e81f27
"""

import sqlalchemy as sa
from alembic import op

revision = "a8e4f2c61b90"
down_revision = "d5a9c3e81f27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gs_usuario_empresas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("gs_empresas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("criado_por", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("user_id", "empresa_id", name="uq_usuario_empresa"),
    )
    op.create_index("ix_gs_usuario_empresas_user_id", "gs_usuario_empresas", ["user_id"])
    op.create_index("ix_gs_usuario_empresas_empresa_id", "gs_usuario_empresas", ["empresa_id"])

    op.create_table(
        "gs_bot_registros",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("telefone", sa.String(20), nullable=False),
        sa.Column("gs_user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("gs_empresas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resultado", sa.String(20), nullable=False),
        sa.Column("ferramentas", sa.Text(), nullable=True),
        sa.Column("pergunta", sa.Text(), nullable=True),
        sa.Column("resposta", sa.Text(), nullable=True),
        sa.Column("duracao_ms", sa.Integer(), nullable=True),
        sa.Column("erro", sa.Text(), nullable=True),
    )
    op.create_index("ix_gs_bot_registros_em", "gs_bot_registros", ["em"])
    op.create_index("ix_gs_bot_registros_gs_user_id", "gs_bot_registros", ["gs_user_id"])
    op.create_index("ix_gs_bot_registros_empresa_id", "gs_bot_registros", ["empresa_id"])

    # A plataforma não tem token: a linha dela guarda só o endereço de cada produto.
    op.execute(
        "UPDATE gs_integracoes SET token_cifrado = NULL, token_prefixo = NULL, "
        "token_dono_nome = NULL, token_dono_email = NULL, token_gravado_em = NULL, "
        "usuario_servico = NULL, senha_cifrada = NULL, estado = 'NUNCA', testada_em = NULL, "
        "detalhe_teste = NULL, usinas_visiveis = NULL WHERE empresa_id IS NULL"
    )

    op.drop_column("gs_users", "bot_whatsapp")


def downgrade() -> None:
    op.add_column(
        "gs_users", sa.Column("bot_whatsapp", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.execute("UPDATE gs_users SET bot_whatsapp = (bot_meuplano OR bot_meuwatt OR bot_helper)")
    # O token da plataforma não volta: ele foi apagado de propósito, e quem quiser um cola de novo.
    op.drop_table("gs_bot_registros")
    op.drop_table("gs_usuario_empresas")
