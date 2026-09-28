"""A empresa de O&M — o inquilino do sistema.

Até aqui o Gestão Solar era de um inquilino só: a operação de quem o construiu. Usina,
integração e conversa não tinham dono, e `gs_users.empresa` era **texto livre** — com o
qual nada pode ser filtrado, porque "Splendor O&M" e "Splendor OM" são a mesma empresa
para o olho e duas para o banco.

**O nulo é a plataforma.** Conta de `atendimento` ou `administrador` não pertence a
empresa nenhuma: `empresa_id` nulo diz isso, e não "vê todas". Quem decide o alcance é o
perfil, e a leitura acontece num lugar só — `services/empresas.no_escopo`. Espalhar
`if empresa_id is None` pelas consultas seria reescrever a regra em cada uma delas, e é
na cópia esquecida que o dado do vizinho aparece.

**Desligar não apaga.** `ativa` tira a empresa de operação preservando usina, cliente e
histórico. Apagar linha de empresa levaria junto o que outra pessoa precisa auditar.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Empresa(Base):
    """Uma empresa de O&M que opera dentro da plataforma."""

    __tablename__ = "gs_empresas"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Como a empresa se chama para quem a atende. Único: duas linhas com o mesmo nome
    #: são o mesmo cadastro feito duas vezes, e foi exatamente isso que o texto livre
    #: em `gs_users.empresa` permitia.
    nome: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    #: CNPJ, quando houver. Não é a chave: empresa nova costuma ser cadastrada antes de
    #: alguém procurar o documento, e uma obrigatoriedade aqui adiaria o cadastro.
    documento: Mapped[str | None] = mapped_column(String(20), nullable=True)

    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
