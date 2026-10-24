"""Log do bot: as mensagens de antes do cadastro passam à conta que hoje tem o número.

As 17 do celular do Kewyn (gerente da Splendor O&M) ficavam como número solto no Log do bot
e fora do oem da empresa dele: chegaram quando o número ainda não era de ninguém aqui. A
adoção do código (`cadastro.adotar_mensagens`) vale quando o celular muda; esta passa as
antigas uma vez. Só número com UMA conta ativa (o celular é único entre as ativas).

Revisão: c6d8e0f2a4b6
Anterior: b3c5d7e9f1a2
"""

from alembic import op

revision = "c6d8e0f2a4b6"
down_revision = "b3c5d7e9f1a2"
branch_labels = None
depends_on = None


#: Subconsultas, e não UPDATE … FROM: com mais de uma linha casando, o FROM escolhe uma ao acaso;
#: aqui a contagem garante que a conta ativa do número é UMA só.
SQL = """
    UPDATE gs_bot_registros SET
        gs_user_id = (SELECT u.id FROM gs_users u WHERE u.telefone = gs_bot_registros.telefone AND u.ativo),
        empresa_id = (SELECT u.empresa_id FROM gs_users u WHERE u.telefone = gs_bot_registros.telefone AND u.ativo)
    WHERE gs_user_id IS NULL
      AND (SELECT count(*) FROM gs_users u WHERE u.telefone = gs_bot_registros.telefone AND u.ativo) = 1
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    # Sem volta: não fica registrado quais estavam soltas, e soltá-las de novo não protege nada.
    pass
