"""contas por técnico: o WhatsApp Business de cada um, conectado pelo Embedded Signup

`wa_contas` guarda um número por linha, com o técnico como dono. `wa_mensagens` ganha o
`phone_number_id` — por qual dos nossos números a mensagem passou —, que com um número só
era implícito. `wa_credenciais` ganha o `es_config_id`, a configuração do Embedded Signup,
que é do app da plataforma.

Tudo nasce vazio ou nulo: nenhuma linha existente muda de significado.

Revision ID: b3c4d5e6f7a8
Revises: a1f2c3d4e5b6
Create Date: 2026-10-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a1f2c3d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wa_contas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phone_number_id', sa.String(length=40), nullable=False),
        sa.Column('waba_id', sa.String(length=40), nullable=False),
        sa.Column('business_id', sa.String(length=40), nullable=True),
        sa.Column('numero_exibicao', sa.String(length=32), nullable=True),
        sa.Column('nome_verificado', sa.String(length=120), nullable=True),
        sa.Column('coexistencia', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('token_cifrado', sa.Text(), nullable=True),
        sa.Column('token_prefixo', sa.String(length=16), nullable=True),
        sa.Column('pin_cifrado', sa.Text(), nullable=True),
        sa.Column('gs_user_id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=True),
        sa.Column('estado', sa.String(length=20), server_default='conectada', nullable=False),
        sa.Column('detalhe', sa.Text(), nullable=True),
        sa.Column('conectada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('desconectada_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('atualizada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('phone_number_id'),
    )
    op.create_index('ix_wa_contas_waba_id', 'wa_contas', ['waba_id'])
    op.create_index('ix_wa_contas_gs_user_id', 'wa_contas', ['gs_user_id'])
    op.create_index('ix_wa_contas_empresa_id', 'wa_contas', ['empresa_id'])

    op.add_column('wa_mensagens', sa.Column('phone_number_id', sa.String(length=40), nullable=True))
    op.create_index('ix_wa_mensagens_phone_number_id', 'wa_mensagens', ['phone_number_id'])

    op.add_column('wa_credenciais', sa.Column('es_config_id', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('wa_credenciais', 'es_config_id')
    op.drop_index('ix_wa_mensagens_phone_number_id', table_name='wa_mensagens')
    op.drop_column('wa_mensagens', 'phone_number_id')
    op.drop_index('ix_wa_contas_empresa_id', table_name='wa_contas')
    op.drop_index('ix_wa_contas_gs_user_id', table_name='wa_contas')
    op.drop_index('ix_wa_contas_waba_id', table_name='wa_contas')
    op.drop_table('wa_contas')
