"""áreas do painel por membro do staff

Revision ID: e7c1a4d93b58
Revises: c41d9b6e7a05
Create Date: 2026-09-18

Antes daqui o painel tinha dois degraus fixos: atendimento via clientes, usinas,
diagnóstico e notificações; administrador via isso mais Conexões, WhatsApp e Equipe.
Agora cada tela é uma área concedível, marcada por membro em Usuários do sistema.

**O seed importa tanto quanto a tabela.** Área é presença de linha, então uma tabela
vazia deixaria todo mundo que é atendimento sem NADA no menu — a pessoa entraria amanhã
num painel em branco, sem erro nenhum na tela para explicar. O `INSERT` abaixo concede
aos atendimentos existentes exatamente as quatro áreas que eles já abriam hoje, e a
mudança fica invisível para quem já usava. Administrador não recebe linha: ele abre tudo
por perfil (ver `services/areas_painel`).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7c1a4d93b58"
down_revision: Union[str, None] = "c41d9b6e7a05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: O que atendimento abria antes desta migration. Fonte: as guardas `gestor_atual` das
#: rotas de clientes, usinas, diagnóstico e notificações, que agora pedem área.
AREAS_DE_ATENDIMENTO = ("clientes", "usinas", "diagnostico", "notificacoes")


def upgrade() -> None:
    op.create_table(
        "gs_painel_acessos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(length=40), nullable=False),
        sa.Column(
            "concedido_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("concedido_por", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["concedido_por"], ["gs_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["gs_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "area", name="uq_gs_painel_acesso"),
    )
    op.create_index(
        op.f("ix_gs_painel_acessos_area"), "gs_painel_acessos", ["area"], unique=False
    )
    op.create_index(
        op.f("ix_gs_painel_acessos_user_id"), "gs_painel_acessos", ["user_id"], unique=False
    )

    # `concedido_por` fica nulo de propósito: ninguém concedeu isto, a migration preservou
    # o que já valia — e a auditoria não deve atribuir a decisão a um administrador.
    for area in AREAS_DE_ATENDIMENTO:
        op.execute(
            sa.text(
                "INSERT INTO gs_painel_acessos (user_id, area) "
                "SELECT id, :area FROM gs_users WHERE perfil = 'ATENDIMENTO'"
            ).bindparams(area=area)
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_gs_painel_acessos_user_id"), table_name="gs_painel_acessos")
    op.drop_index(op.f("ix_gs_painel_acessos_area"), table_name="gs_painel_acessos")
    op.drop_table("gs_painel_acessos")
