"""tabelas do gateway: credenciais, eventos do webhook e mensagens

As quatro tabelas nascem vazias e o serviço sobe sem nenhuma delas preenchida: as
credenciais da Meta são cadastradas na tela de administração do WhatsApp, no painel, e até
lá o webhook e o envio respondem 503 dizendo isso.

Revision ID: a1f2c3d4e5b6
Revises:
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f2c3d4e5b6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wa_credenciais',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escopo', sa.String(length=20), server_default='padrao', nullable=False),
        sa.Column('phone_number_id', sa.String(length=40), nullable=True),
        sa.Column('waba_id', sa.String(length=40), nullable=True),
        sa.Column('app_id', sa.String(length=40), nullable=True),
        sa.Column('numero_exibicao', sa.String(length=32), nullable=True),
        sa.Column('token_cifrado', sa.Text(), nullable=True),
        sa.Column('token_prefixo', sa.String(length=16), nullable=True),
        sa.Column('token_gravado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('app_secret_cifrado', sa.Text(), nullable=True),
        sa.Column('verify_token_cifrado', sa.Text(), nullable=True),
        sa.Column('estado', sa.String(length=20), server_default='nunca', nullable=False),
        sa.Column('detalhe', sa.Text(), nullable=True),
        sa.Column('testada_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('atualizada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('atualizada_por', sa.String(length=120), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('escopo', name='uq_wa_credencial_escopo'),
    )

    op.create_table(
        'wa_credencial_eventos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('evento', sa.String(length=30), nullable=False),
        sa.Column('ocorrido_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ator', sa.String(length=120), nullable=True),
        sa.Column('token_prefixo', sa.String(length=16), nullable=True),
        sa.Column('detalhe', sa.Text(), nullable=True),
        sa.Column('numeros_visiveis', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_wa_credencial_eventos_evento'), 'wa_credencial_eventos', ['evento'])
    op.create_index(
        op.f('ix_wa_credencial_eventos_ocorrido_em'), 'wa_credencial_eventos', ['ocorrido_em']
    )

    op.create_table(
        'wa_webhook_eventos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recebido_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('corpo', sa.JSON(), nullable=False),
        sa.Column('processado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tentativas', sa.Integer(), server_default='0', nullable=False),
        sa.Column('erro', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_wa_webhook_eventos_recebido_em'), 'wa_webhook_eventos', ['recebido_em'])
    op.create_index(
        op.f('ix_wa_webhook_eventos_processado_em'), 'wa_webhook_eventos', ['processado_em']
    )

    op.create_table(
        'wa_mensagens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('wamid', sa.String(length=80), nullable=True),
        sa.Column('direcao', sa.String(length=10), nullable=False),
        sa.Column('wa_id', sa.String(length=32), nullable=False),
        sa.Column('telefone', sa.String(length=20), nullable=True),
        sa.Column('nome_perfil', sa.String(length=120), nullable=True),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('template', sa.String(length=80), nullable=True),
        sa.Column('texto', sa.Text(), nullable=True),
        sa.Column('ocorrida_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pendente', nullable=False),
        sa.Column('status_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('erro_codigo', sa.String(length=20), nullable=True),
        sa.Column('erro_detalhe', sa.Text(), nullable=True),
        sa.Column('origem', sa.String(length=40), nullable=True),
        sa.Column('notificada_bff_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('criada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        # UNIQUE com nulos: a mensagem de saída fica sem wamid enquanto está `pendente`, e
        # vários nulos convivem numa coluna única tanto no Postgres quanto no SQLite.
        sa.UniqueConstraint('wamid', name='uq_wa_mensagem_wamid'),
    )
    op.create_index(op.f('ix_wa_mensagens_direcao'), 'wa_mensagens', ['direcao'])
    op.create_index(op.f('ix_wa_mensagens_wa_id'), 'wa_mensagens', ['wa_id'])
    op.create_index(op.f('ix_wa_mensagens_ocorrida_em'), 'wa_mensagens', ['ocorrida_em'])


def downgrade() -> None:
    op.drop_index(op.f('ix_wa_mensagens_ocorrida_em'), table_name='wa_mensagens')
    op.drop_index(op.f('ix_wa_mensagens_wa_id'), table_name='wa_mensagens')
    op.drop_index(op.f('ix_wa_mensagens_direcao'), table_name='wa_mensagens')
    op.drop_table('wa_mensagens')

    op.drop_index(op.f('ix_wa_webhook_eventos_processado_em'), table_name='wa_webhook_eventos')
    op.drop_index(op.f('ix_wa_webhook_eventos_recebido_em'), table_name='wa_webhook_eventos')
    op.drop_table('wa_webhook_eventos')

    op.drop_index(op.f('ix_wa_credencial_eventos_ocorrido_em'), table_name='wa_credencial_eventos')
    op.drop_index(op.f('ix_wa_credencial_eventos_evento'), table_name='wa_credencial_eventos')
    op.drop_table('wa_credencial_eventos')

    op.drop_table('wa_credenciais')
