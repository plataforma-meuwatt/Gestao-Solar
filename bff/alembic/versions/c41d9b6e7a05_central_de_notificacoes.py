"""central de notificações: telefone e aceite do cliente, preferências e envios

Aditiva por construção: as colunas novas em `gs_users` nascem nulas (ninguém tem telefone
nem aceite até o gestor preencher) e as duas tabelas nascem vazias — nada começa ligado, que
é a regra da central.

Revision ID: c41d9b6e7a05
Revises: b6e2d94f1a70
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c41d9b6e7a05'
down_revision: Union[str, None] = 'b6e2d94f1a70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('gs_users', sa.Column('telefone', sa.String(length=20), nullable=True))
    op.add_column(
        'gs_users', sa.Column('whatsapp_aceite_em', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('gs_users', sa.Column('whatsapp_aceite_por', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_gs_users_whatsapp_aceite_por',
        'gs_users',
        'gs_users',
        ['whatsapp_aceite_por'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_table(
        'gs_notificacao_preferencias',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=40), nullable=False),
        sa.Column('plant_link_id', sa.Integer(), nullable=False),
        sa.Column(
            'criada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column('criada_por', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['criada_por'], ['gs_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['plant_link_id'], ['gs_plant_links.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['gs_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'tipo', 'plant_link_id', name='uq_gs_notificacao_pref'),
    )
    op.create_index(
        op.f('ix_gs_notificacao_preferencias_user_id'),
        'gs_notificacao_preferencias',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_gs_notificacao_preferencias_tipo'),
        'gs_notificacao_preferencias',
        ['tipo'],
        unique=False,
    )
    op.create_index(
        op.f('ix_gs_notificacao_preferencias_plant_link_id'),
        'gs_notificacao_preferencias',
        ['plant_link_id'],
        unique=False,
    )

    op.create_table(
        'gs_notificacoes_enviadas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=40), nullable=False),
        sa.Column('chave', sa.String(length=160), nullable=False),
        sa.Column('plant_link_id', sa.Integer(), nullable=True),
        sa.Column('canal', sa.String(length=20), server_default='whatsapp', nullable=False),
        sa.Column('destino', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pendente', nullable=False),
        sa.Column('status_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('wamid', sa.String(length=80), nullable=True),
        sa.Column('erro', sa.Text(), nullable=True),
        sa.Column(
            'criada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['plant_link_id'], ['gs_plant_links.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['gs_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'chave', name='uq_gs_notificacao_enviada'),
    )
    op.create_index(
        op.f('ix_gs_notificacoes_enviadas_user_id'),
        'gs_notificacoes_enviadas',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_gs_notificacoes_enviadas_tipo'), 'gs_notificacoes_enviadas', ['tipo'], unique=False
    )
    op.create_index(
        op.f('ix_gs_notificacoes_enviadas_chave'),
        'gs_notificacoes_enviadas',
        ['chave'],
        unique=False,
    )
    op.create_index(
        op.f('ix_gs_notificacoes_enviadas_wamid'),
        'gs_notificacoes_enviadas',
        ['wamid'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_gs_notificacoes_enviadas_wamid'), table_name='gs_notificacoes_enviadas')
    op.drop_index(op.f('ix_gs_notificacoes_enviadas_chave'), table_name='gs_notificacoes_enviadas')
    op.drop_index(op.f('ix_gs_notificacoes_enviadas_tipo'), table_name='gs_notificacoes_enviadas')
    op.drop_index(op.f('ix_gs_notificacoes_enviadas_user_id'), table_name='gs_notificacoes_enviadas')
    op.drop_table('gs_notificacoes_enviadas')

    op.drop_index(
        op.f('ix_gs_notificacao_preferencias_plant_link_id'),
        table_name='gs_notificacao_preferencias',
    )
    op.drop_index(
        op.f('ix_gs_notificacao_preferencias_tipo'), table_name='gs_notificacao_preferencias'
    )
    op.drop_index(
        op.f('ix_gs_notificacao_preferencias_user_id'), table_name='gs_notificacao_preferencias'
    )
    op.drop_table('gs_notificacao_preferencias')

    op.drop_constraint('fk_gs_users_whatsapp_aceite_por', 'gs_users', type_='foreignkey')
    op.drop_column('gs_users', 'whatsapp_aceite_por')
    op.drop_column('gs_users', 'whatsapp_aceite_em')
    op.drop_column('gs_users', 'telefone')
