"""o vinculo passa a carregar o token do proprio cliente

Até aqui o Gestão Solar lia os dois produtos com UMA credencial de serviço — o token
pessoal de um administrador, gravado em `gs_integracoes`. Todo cliente era servido por
ela, e o BFF tinha então de perguntar aos produtos *"quais usinas o usuário 45 vê?"* por
rotas de administrador. Essa pergunta indireta é a origem de um erro que apareceu em
produção: o Janderson enxerga a UFV Porto Ferreira no meuPlano pela regra da organização
dele (Eninsa), e não por concessão individual, então a rota administrativa devolvia lista
vazia e o painel concluía "nenhuma usina indicada" para alguém que vê sete.

O desenho novo troca a pergunta pela coisa certa: **cada cliente cola o próprio token**,
e o BFF lê como ele. O meuPlano responde exatamente o que o Janderson veria no site,
pela mesma regra que usa lá — não há mais tradução para errar.

## Por que as colunas entram no vínculo, e não numa tabela nova

Porque agora são a mesma informação. Antes o vínculo era uma anotação DIGITADA por um
gestor ("este cliente é aquela conta lá"), sujeita a engano e sem prova. Com o token, o
vínculo é ESTABELECIDO pelo produto: o BFF apresenta o token, o produto responde de quem
ele é, e `usuario_remoto_id` passa a ser um fato verificado em vez de um palpite. Separar
em duas tabelas permitiria as duas discordarem — um vínculo apontando para uma conta e um
token pertencente a outra —, e nada no sistema saberia qual das duas está certa.

## As colunas

* `token_cifrado` / `token_prefixo` / `token_gravado_em` — o mesmo acordo de
  `gs_integracoes`: o valor entra cifrado (Fernet) e nunca volta pela tela; o prefixo em
  claro existe para o gestor reconhecer, na lista de tokens do produto, qual é este —
  sem ele, revogar o token certo vira tentativa e erro.
* `estado` / `detalhe` / `usinas_visiveis` — o resultado do último teste, guardado para a
  tela abrir já dizendo o estado de cada cliente sem bater nos dois upstreams a cada
  carregamento.
* `login_externo_em` — quando o produto confirmou que aceita o login desta conta do
  Gestão Solar. É o que separa "o GS lê os dados dele" de "ele entra lá com a senha
  daqui": duas consequências do mesmo token, mas a segunda depende de o produto ter
  gravado a identidade, o que pode falhar sozinho.

`usuario_remoto_id` continua NOT NULL e continua sendo o id de lá. O que muda é a
procedência: antes vinha de uma busca por e-mail feita pelo gestor, agora vem da resposta
do produto ao token apresentado.

Revision ID: b6e2d94f1a70
Revises: 2f7a0b2f92b4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6e2d94f1a70"
down_revision: Union[str, None] = "2f7a0b2f92b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table pelo mesmo motivo da a1c7e0b4d213: o BFF roda em SQLite no
    # desenvolvimento e lá um ALTER só existe via recriação da tabela.
    with op.batch_alter_table("gs_vinculos_produto", schema=None) as batch_op:
        batch_op.add_column(sa.Column("token_cifrado", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("token_prefixo", sa.String(length=16), nullable=True))
        batch_op.add_column(
            sa.Column("token_gravado_em", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "estado",
                sa.String(length=20),
                nullable=False,
                server_default="nunca",
            )
        )
        batch_op.add_column(sa.Column("detalhe", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("usinas_visiveis", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("login_externo_em", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("gs_vinculos_produto", schema=None) as batch_op:
        batch_op.drop_column("login_externo_em")
        batch_op.drop_column("usinas_visiveis")
        batch_op.drop_column("detalhe")
        batch_op.drop_column("estado")
        batch_op.drop_column("token_gravado_em")
        batch_op.drop_column("token_prefixo")
        batch_op.drop_column("token_cifrado")
