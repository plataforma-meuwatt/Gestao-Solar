"""apelido como identidade de login; e-mail vira contato

Quem autentica passa a ser o apelido. O e-mail deixa de ser chave e vira contato — segue
indexado, porque é por ele que se acha a conta do cliente no meuWatt e no meuPlano, mas
sem exigir unicidade.

A troca existe por um caso concreto que o modelo antigo não comportava: a mesma pessoa
pode ser o gestor do sistema e, separadamente, o dono de uma usina atendida por ele. São
dois papéis com poderes diferentes, logo duas contas — e com o e-mail como chave única a
segunda era recusada como duplicada.

As contas que já existem ganham um apelido derivado do e-mail (`fulano@x.com.br` →
`fulano`), com sufixo numérico quando dois e-mails diferentes reduzem ao mesmo apelido.
Ninguém fica sem poder entrar por causa desta migration; no máximo o apelido herdado é
feio e vale renomear pela tela de Equipe.

Revision ID: d4a80f1c9e27
Revises: a1c7e0b4d213
"""

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4a80f1c9e27"
down_revision: Union[str, None] = "a1c7e0b4d213"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _apelido_de(email: str, tomados: set[str]) -> str:
    """Mesma regra de `core.apelido.sugerir`, reescrita aqui de propósito.

    Uma migration é um registro histórico: ela precisa produzir o mesmo resultado daqui a
    um ano, mesmo que a regra da aplicação tenha mudado desde então. Importar do código
    vivo faria a migration reescrever o passado a cada refatoração.
    """
    base = (email or "").strip().lower().split("@")[0]
    base = re.sub(r"[\s_]+", ".", base)
    base = re.sub(r"[^a-z0-9._-]", "", base)
    base = re.sub(r"[._-]{2,}", ".", base).strip("._-")[:32].rstrip("._-")

    if len(base) < 3:
        base = f"conta{len(tomados) + 1}"

    candidato = base
    n = 2
    while candidato in tomados:
        candidato = f"{base[:29]}{n}"
        n += 1
    tomados.add(candidato)
    return candidato


def upgrade() -> None:
    conexao = op.get_bind()

    with op.batch_alter_table("gs_users", schema=None) as batch:
        # Nasce anulável para as linhas existentes sobreviverem ao ALTER; vira obrigatória
        # no fim, depois de preenchida.
        batch.add_column(sa.Column("apelido", sa.String(length=32), nullable=True))

    tomados: set[str] = set()
    for id_, email in conexao.execute(sa.text("SELECT id, email FROM gs_users ORDER BY id")):
        conexao.execute(
            sa.text("UPDATE gs_users SET apelido = :a WHERE id = :i"),
            {"a": _apelido_de(email or "", tomados), "i": id_},
        )

    with op.batch_alter_table("gs_users", schema=None) as batch:
        batch.alter_column("apelido", existing_type=sa.String(length=32), nullable=False)
        batch.create_index(batch.f("ix_gs_users_apelido"), ["apelido"], unique=True)

        # O e-mail perde a obrigatoriedade e a unicidade, mas não o índice: continua sendo
        # por ele que o painel procura a conta do cliente nos dois produtos.
        batch.drop_index(batch.f("ix_gs_users_email"))
        batch.alter_column("email", existing_type=sa.String(length=255), nullable=True)
        batch.create_index(batch.f("ix_gs_users_email"), ["email"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("gs_users", schema=None) as batch:
        batch.drop_index(batch.f("ix_gs_users_apelido"))
        batch.drop_column("apelido")

        batch.drop_index(batch.f("ix_gs_users_email"))
        # Volta a NOT NULL: quem tiver e-mail vazio precisa ser resolvido à mão antes de
        # descer esta migration — não há valor de aterro que sirva para um identificador.
        batch.alter_column("email", existing_type=sa.String(length=255), nullable=False)
        batch.create_index(batch.f("ix_gs_users_email"), ["email"], unique=True)
