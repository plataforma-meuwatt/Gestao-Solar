"""Usina que a empresa NÃO quer ver na lista de trazer.

O token de uma empresa alcança tudo o que a conta dela enxerga nos produtos — 6 usinas no
meuWatt e 17 no meuPlano, no primeiro caso real. Boa parte não interessa: são de outro
contrato, de teste, ou simplesmente não entram neste sistema. Sem um jeito de dizer "esta
não", elas ficam para sempre na tela, e a lista de trazer vira uma lista de rolar.

**Ocultar não apaga nada e não sai do produto de origem.** É uma preferência de TELA, desta
empresa, e por isso a tabela é só isto: um par (produto, identificador) por empresa. Nenhuma
outra consulta do sistema a lê — esconder uma usina não pode, jamais, mudar o que o dono
dela vê no aplicativo.

**É reversível, e a tela diz quantas estão escondidas.** Uma lista que some sem contador faz
alguém procurar a usina que "sumiu" — e a resposta certa ("você a ocultou") tem de estar na
mesma tela, não na memória de quem clicou.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.integracao import Produto


class UsinaOculta(Base):
    """Uma usina que esta empresa escolheu não ver na lista."""

    __tablename__ = "gs_usinas_ocultas"
    __table_args__ = (
        UniqueConstraint("empresa_id", "produto", "identificador", name="uq_gs_usina_oculta"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("gs_empresas.id", ondelete="CASCADE"), index=True
    )
    produto: Mapped[Produto] = mapped_column(Enum(Produto, native_enum=False, length=20))
    #: O `slug` no meuWatt, o `id` no meuPlano — como texto, porque os dois produtos
    #: identificam usina de formas diferentes e esta tabela não precisa saber qual é qual.
    identificador: Mapped[str] = mapped_column(String(120))
    ocultada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
