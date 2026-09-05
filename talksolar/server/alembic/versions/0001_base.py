# -*- coding: utf-8 -*-
"""Talk Solar — o banco inteiro, do zero.

Uma migration só de propósito: este projeto está nascendo, e a primeira coisa que o próximo
programador vai fazer é rodar `alembic upgrade head` num banco vazio (o do Gestão Solar). Sete
migrations de 3 linhas cada só atrapalhariam essa leitura.

Todas as tabelas com prefixo `ts_`: elas vão conviver com as tabelas do Gestão Solar no mesmo
banco, e o prefixo é a diferença entre "as tabelas do Talk Solar" e "umas tabelas soltas que
ninguém sabe de quem são".

Revision ID: 0001_base
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ts_apps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(30), nullable=False, unique=True),
        sa.Column("nome", sa.String(80), nullable=False),
        sa.Column("secret", sa.String(80), nullable=False),
        # (1) de quem é este token? — o único endpoint obrigatório do contrato
        sa.Column("identidade_url", sa.String(400), nullable=False),
        # (2) e (3): busca e rótulo dos alvos citáveis. Sem eles, o sistema integra sem citação.
        sa.Column("refs_busca_url", sa.String(400), nullable=True),
        sa.Column("refs_label_url", sa.String(400), nullable=True),
        sa.Column("webhook_url", sa.String(400), nullable=True),
        sa.Column("webhook_eventos", sa.JSON(), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "ts_usuarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("ts_apps.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # STRING de propósito: um sistema usa int, outro usa UUID
        sa.Column("externo_id", sa.String(60), nullable=False),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("email", sa.String(150), nullable=True),
        sa.Column("avatar_url", sa.String(400), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("visto_em", sa.DateTime(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("app_id", "externo_id", name="uq_ts_usuario"),
    )

    op.create_table(
        "ts_sessoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("ts_usuarios.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # guardamos o SHA-256; o valor em claro aparece uma vez, na criação
        sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("dispositivo", sa.String(120), nullable=True),
        sa.Column("criada_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("usada_em", sa.DateTime(), nullable=True),
        sa.Column("revogada_em", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "ts_canais",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("ts_apps.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("tipo", sa.String(10), nullable=False, server_default="publico"),
        sa.Column("nome", sa.String(120), nullable=True),
        sa.Column("topico", sa.String(300), nullable=True),
        # o canal INTEIRO de uma usina/OS — `tipo`+`id` OPACOS, o vocabulário é do sistema
        sa.Column("alvo_tipo", sa.String(30), nullable=True),
        sa.Column("alvo_id", sa.String(60), nullable=True),
        sa.Column("alvo_label", sa.String(200), nullable=True),
        sa.Column("alvo_url", sa.String(400), nullable=True),
        sa.Column("criado_por", sa.Integer(),
                  sa.ForeignKey("ts_usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("arquivado_em", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ts_canal_alvo", "ts_canais", ["app_id", "alvo_tipo", "alvo_id"])

    op.create_table(
        "ts_membros",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canal_id", sa.Integer(), sa.ForeignKey("ts_canais.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("usuario_id", sa.Integer(),
                  sa.ForeignKey("ts_usuarios.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("papel", sa.String(10), nullable=False, server_default="membro"),
        # o "não lido" é uma comparação de id — não uma tabela que cresce com gente × mensagens
        sa.Column("ultima_lida_id", sa.Integer(), nullable=True),
        sa.Column("silenciado", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("entrou_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("canal_id", "usuario_id", name="uq_ts_membro"),
    )

    op.create_table(
        "ts_mensagens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canal_id", sa.Integer(), sa.ForeignKey("ts_canais.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("usuario_id", sa.Integer(),
                  sa.ForeignKey("ts_usuarios.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("conteudo", sa.Text(), nullable=False, server_default=""),
        sa.Column("responde_a", sa.Integer(),
                  sa.ForeignKey("ts_mensagens.id", ondelete="CASCADE"), nullable=True, index=True),
        # mensagem escrita pelo SISTEMA (webhook de volta: "OS fechada"), não por gente
        sa.Column("do_sistema", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("editada_em", sa.DateTime(), nullable=True),
        # apagar é MARCAR: numa conversa de trabalho o buraco precisa ser visível
        sa.Column("apagada_em", sa.DateTime(), nullable=True),
        sa.Column("criada_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ts_msg_canal", "ts_mensagens", ["canal_id", "id"])

    op.create_table(
        "ts_anexos",
        sa.Column("id", sa.Integer(), primary_key=True),
        # NOT NULL: não existe anexo órfão — ele nasce junto da mensagem, na mesma requisição
        sa.Column("mensagem_id", sa.Integer(),
                  sa.ForeignKey("ts_mensagens.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("caminho", sa.String(500), nullable=False),
        sa.Column("thumb_caminho", sa.String(500), nullable=True),
        sa.Column("tipo", sa.String(100), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("largura", sa.Integer(), nullable=True),
        sa.Column("altura", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "ts_citacoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mensagem_id", sa.Integer(),
                  sa.ForeignKey("ts_mensagens.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("ts_apps.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("alvo_tipo", sa.String(30), nullable=False),
        sa.Column("alvo_id", sa.String(60), nullable=False),
        # CONGELADOS: a conversa de ontem mostra o nome que a coisa tinha ontem, e a citação
        # sobrevive ao registro apagado
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("url", sa.String(400), nullable=True),
        sa.Column("criada_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    # a pergunta INVERSA — "o que já se falou sobre esta OS?" — é metade do valor de citar
    op.create_index("ix_ts_citacao_alvo", "ts_citacoes", ["app_id", "alvo_tipo", "alvo_id"])

    op.create_table(
        "ts_entregas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("ts_apps.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("evento", sa.String(40), nullable=False),
        # o uuid que vai no cabeçalho — é por ele que o outro lado fica idempotente
        sa.Column("ref", sa.String(40), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("estado", sa.String(12), nullable=False, server_default="pendente"),
        sa.Column("tentativas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proxima_em", sa.DateTime(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("resposta", sa.String(500), nullable=True),
        sa.Column("criada_em", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("terminada_em", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ts_entrega_pendente", "ts_entregas", ["estado", "proxima_em"])


def downgrade() -> None:
    for t in ("ts_entregas", "ts_citacoes", "ts_anexos", "ts_mensagens", "ts_membros",
              "ts_canais", "ts_sessoes", "ts_usuarios", "ts_apps"):
        op.drop_table(t)
