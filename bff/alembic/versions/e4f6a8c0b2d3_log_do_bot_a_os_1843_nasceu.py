"""Log do bot: a linha 56 diz "Nada foi feito", e a OS 1843 nasceu naquele momento.

O Sim de 24/10/2026 09:29 recebeu "❌ O meuPlano recusou: … 'Depends' object has no attribute
'all'. Nada foi feito." — mas o meuPlano já tinha gravado a OS 1843 (vazia) quando o passo
seguinte quebrou (avaliação 15). A resposta fica como foi mandada (é o registro do que a pessoa
leu); o campo do erro, que a tela mostra embaixo dela, passa a dizer o que de fato aconteceu.
Só a linha com aquela resposta: num banco sem ela, nada muda.

Revisão: e4f6a8c0b2d3
Anterior: d0e2f4a6b8c1
"""

import sqlalchemy as sa
from alembic import op

revision = "e4f6a8c0b2d3"
down_revision = "d0e2f4a6b8c1"
branch_labels = None
depends_on = None

ERRO = ("O bot respondeu «Nada foi feito», mas o meuPlano já tinha criado a OS 1843, vazia: o erro veio "
        "depois de gravá-la. Ela foi completada em 24/10/2026 com a tarefa 9330 e está PROGRAMADA.")


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE gs_bot_registros SET erro = :erro WHERE id = 56 AND ferramentas = 'confirmacao' "
        "AND resposta LIKE '❌ O meuPlano recusou: Erro ao aplicar a ação: ''Depends''%'"), {"erro": ERRO})


def downgrade() -> None:
    # Sem volta: a frase antiga ("Nada foi feito") era a falsa.
    pass
