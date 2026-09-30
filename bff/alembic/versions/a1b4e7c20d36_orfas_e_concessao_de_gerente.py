"""A usina sem dono deixa de existir, e o gerente deixa de ter concessão.

Duas sobras do dia em que o sistema virou multiempresa, e as duas apareciam juntas na
mesma tela, como o erro que o dono viu ao salvar as usinas de um cliente:

    "Esta usina ainda não é da sua empresa: UFV Leme. Traga em Usinas, ou desmarque."

1. **`PlantLink` com `empresa_id` nulo** é usina de antes do multiempresa. A tela de
   Usinas monta o catálogo a partir do upstream, e uma herdada só do meuPlano não tem
   `mw_slug` — então "traga em Usinas" mandava o gerente a um lugar onde ela não estava.
   Aqui ela é adotada pela empresa que JÁ a enxerga (alguém dela a recebe concedida). A
   que ninguém concede fica nula: é da plataforma mesmo, e adivinhar dono é pior.

2. **Concessão a quem é GERENTE** virou ruído no dia em que ele passou a ver a carteira
   inteira da empresa por ser gerente. Pior que ruído: era por essa concessão que a
   herdada chegava à tela dele. A rota já recusa conceder a gerente; isto limpa o que
   ficou.

Revisão: a1b4e7c20d36
Anterior: f7a2c5d90e14
"""

from alembic import op

revision = "a1b4e7c20d36"
down_revision = "f7a2c5d90e14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A órfã concedida a gente de UMA empresa só é dela. Concedida por duas, fica nula —
    # neste banco não acontece, e escolher uma seria decidir no lugar de quem decide.
    op.execute(
        """
        UPDATE gs_plant_links p
           SET empresa_id = d.empresa_id
          FROM (SELECT a.plant_link_id, MIN(u.empresa_id) AS empresa_id
                  FROM gs_user_plant_access a
                  JOIN gs_users u ON u.id = a.user_id
                 WHERE u.empresa_id IS NOT NULL
                 GROUP BY a.plant_link_id
                HAVING COUNT(DISTINCT u.empresa_id) = 1) d
         WHERE p.id = d.plant_link_id
           AND p.empresa_id IS NULL
        """
    )
    op.execute(
        """
        DELETE FROM gs_user_plant_access a
         USING gs_users u
         WHERE u.id = a.user_id
           AND u.perfil = 'GESTOR_EMPRESA'
        """
    )


def downgrade() -> None:
    # Não há volta: qual usina era órfã e qual concessão era do gerente não fica gravado
    # em lugar nenhum, e inventar um estado anterior é pior do que não ter downgrade.
    pass
