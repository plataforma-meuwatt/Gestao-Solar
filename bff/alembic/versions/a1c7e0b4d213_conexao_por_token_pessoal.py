"""conexao por token pessoal + historico das pontes

A ponte com cada produto deixa de exigir usuário e senha de serviço: alguém gera um token
pessoal no meuWatt e no meuPlano e cola no painel. O BFF passa a não ver a senha de
ninguém, trocar a senha lá não derruba a integração, e o acesso vira revogável do lado de
origem por quem o emitiu.

As colunas antigas (`usuario_servico`, `senha_cifrada`) viram anuláveis em vez de sumir:
as conexões já gravadas continuam funcionando enquanto não forem trocadas por token.
Apagá-las agora derrubaria a integração no mesmo deploy que entrega o substituto.

`gs_integracao_eventos` guarda o histórico. O estado na `gs_integracoes` diz se funciona
agora; o histórico diz desde quando parou e o que mudou antes — que é o que distingue "o
token foi trocado por engano na quinta" de "o produto saiu do ar", dois cartões vermelhos
idênticos na tela.

Revision ID: a1c7e0b4d213
Revises: 7f19c7de9682
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7e0b4d213"
down_revision: Union[str, None] = "7f19c7de9682"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table: o BFF roda em SQLite no desenvolvimento, e lá um ALTER de
    # nulidade só existe via recriação da tabela.
    with op.batch_alter_table("gs_integracoes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("token_cifrado", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("token_prefixo", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("token_dono_nome", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("token_dono_email", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("token_gravado_em", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.alter_column("usuario_servico", existing_type=sa.String(length=255), nullable=True)
        batch_op.alter_column("senha_cifrada", existing_type=sa.Text(), nullable=True)

    op.create_table(
        "gs_integracao_eventos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "produto",
            sa.Enum("MEUWATT", "MEUPLANO", name="produto", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("evento", sa.String(length=30), nullable=False),
        sa.Column(
            "ocorrido_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("ator_email", sa.String(length=255), nullable=True),
        # Nunca o valor do token — só o prefixo, que identifica sem revelar.
        sa.Column("token_prefixo", sa.String(length=16), nullable=True),
        sa.Column("detalhe", sa.Text(), nullable=True),
        sa.Column("usinas_visiveis", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("gs_integracao_eventos", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_gs_integracao_eventos_produto"), ["produto"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_gs_integracao_eventos_ocorrido_em"), ["ocorrido_em"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("gs_integracao_eventos", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_gs_integracao_eventos_ocorrido_em"))
        batch_op.drop_index(batch_op.f("ix_gs_integracao_eventos_produto"))
    op.drop_table("gs_integracao_eventos")

    with op.batch_alter_table("gs_integracoes", schema=None) as batch_op:
        # A volta só é possível se nenhuma linha estiver sem usuário/senha — uma conexão
        # criada por token não tem o que preencher aqui.
        batch_op.alter_column("senha_cifrada", existing_type=sa.Text(), nullable=False)
        batch_op.alter_column(
            "usuario_servico", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.drop_column("token_gravado_em")
        batch_op.drop_column("token_dono_email")
        batch_op.drop_column("token_dono_nome")
        batch_op.drop_column("token_prefixo")
        batch_op.drop_column("token_cifrado")
