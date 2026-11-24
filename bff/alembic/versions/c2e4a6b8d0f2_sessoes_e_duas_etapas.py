"""GS: as sessões abertas de cada pessoa (R4) e a verificação em duas etapas (R12). Plano Casa GS, 24/11/2026.

Aditiva: nasce `gs_sessoes` (a linha de cada sessão nasce no primeiro uso dela); a conta ganha `sessoes_desde` (o
"encerrar todas"), os campos do autenticador (`totp_*`, o segredo cifrado) e nasce `gs_redefinicoes_senha` (o
"esqueci a senha"). O pedido de usina "a confirmar" passa a ser único por empresa. Tudo nulo: ninguém perde a sessão na
subida, e a verificação em duas etapas só é pedida no próximo login (e pode ser desligada por `GS_2FA_DESLIGADA`).
Idempotente.

Revisão: c2e4a6b8d0f2
Anterior: b9d1f3a5c7e9
"""

import sqlalchemy as sa
from alembic import op

revision = "c2e4a6b8d0f2"
down_revision = "b9d1f3a5c7e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "gs_sessoes" not in set(insp.get_table_names()):
        op.create_table(
            "gs_sessoes",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("gs_user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("escopo", sa.String(20), nullable=False),
            sa.Column("criada_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("expira_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ultimo_uso_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("ip", sa.String(64), nullable=False, server_default=""),
            sa.Column("aparelho", sa.String(300), nullable=False, server_default=""),
            sa.Column("encerrada_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("encerrada_por_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("motivo", sa.String(120), nullable=False, server_default=""),
        )
        op.create_index("ix_gs_sessoes_gs_user_id", "gs_sessoes", ["gs_user_id"])
        op.create_index("ix_gs_sessoes_ultimo_uso_em", "gs_sessoes", ["ultimo_uso_em"])
    if "gs_redefinicoes_senha" not in set(insp.get_table_names()):     # o "esqueci a senha"
        op.create_table(
            "gs_redefinicoes_senha",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("gs_user_id", sa.Integer(), sa.ForeignKey("gs_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("canal", sa.String(20), nullable=False),
            sa.Column("criada_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
            sa.Column("usada_em", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_gs_redefinicoes_senha_gs_user_id", "gs_redefinicoes_senha", ["gs_user_id"])
    colunas = {c["name"] for c in insp.get_columns("gs_users")}
    for nome, tipo in (("sessoes_desde", sa.DateTime(timezone=True)), ("totp_segredo_cifrado", sa.String(300)),
                       ("totp_ativo_em", sa.DateTime(timezone=True)), ("totp_ultimo_passo", sa.BigInteger())):
        if nome not in colunas:
            op.add_column("gs_users", sa.Column(nome, tipo, nullable=True))
    # o pedido de usina "a confirmar" é de cada empresa: o descartado por uma não some quando outra registra a mesma
    # usina de lá (avaliação de 24/11/2026)
    unicas = {u["name"] for u in insp.get_unique_constraints("gs_usinas_a_confirmar")}
    if "ux_gs_usinas_a_confirmar_ref" in unicas:
        op.drop_constraint("ux_gs_usinas_a_confirmar_ref", "gs_usinas_a_confirmar", type_="unique")
    if "ux_gs_usinas_a_confirmar_empresa_ref" not in unicas:
        op.create_unique_constraint("ux_gs_usinas_a_confirmar_empresa_ref", "gs_usinas_a_confirmar",
                                    ["empresa_id", "sistema", "referencia"])


def downgrade() -> None:
    op.drop_constraint("ux_gs_usinas_a_confirmar_empresa_ref", "gs_usinas_a_confirmar", type_="unique")
    op.create_unique_constraint("ux_gs_usinas_a_confirmar_ref", "gs_usinas_a_confirmar", ["sistema", "referencia"])
    op.drop_table("gs_redefinicoes_senha")
    for nome in ("totp_ultimo_passo", "totp_ativo_em", "totp_segredo_cifrado", "sessoes_desde"):
        op.drop_column("gs_users", nome)
    op.drop_table("gs_sessoes")
