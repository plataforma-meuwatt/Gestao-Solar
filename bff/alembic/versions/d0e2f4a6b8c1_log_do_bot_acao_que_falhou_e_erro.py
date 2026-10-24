"""Log do bot: a confirmação cuja ação FALHOU aparece como erro também nas linhas antigas.

Até a avaliação 12, o "Sim" que recebia "❌ O meuPlano recusou…" ficava verde, "Respondeu" (a linha
do Sim que deixou a OS 1843 vazia, 24/10/2026). O código grava `erro` desde então; esta passa as
antigas uma vez, com a primeira linha da resposta no campo do erro. Só turno de confirmação
(`ferramentas` = confirmacao / senha_de_atuacao): resposta da IA que comece por ❌ não é ação.

Revisão: d0e2f4a6b8c1
Anterior: c6d8e0f2a4b6
"""

import sqlalchemy as sa
from alembic import op

revision = "d0e2f4a6b8c1"
down_revision = "c6d8e0f2a4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    linhas = conn.execute(sa.text(
        "SELECT id, resposta FROM gs_bot_registros WHERE resultado = 'respondeu' "
        "AND ferramentas IN ('confirmacao', 'senha_de_atuacao') "
        "AND (resposta LIKE '❌%' OR resposta LIKE '⚠️%')")).all()
    for id_, resposta in linhas:
        conn.execute(sa.text("UPDATE gs_bot_registros SET resultado = 'erro', erro = :erro WHERE id = :id"),
                     {"erro": resposta.split("\n")[0][:1000], "id": id_})


def downgrade() -> None:
    # Sem volta: não fica registrado quais eram, e voltá-las a "respondeu" só esconderia a falha.
    pass
