"""A ponte do Gestão Solar com cada produto.

Antes isto vivia no `.env` (`MEUWATT_SERVICE_PASSWORD` e companhia). Passou para o banco
por um motivo prático: quem configura é o gestor, pela tela, e ele precisa **testar** —
digitar, ver se responde, corrigir. Um segredo em variável de ambiente exige redeploy a
cada tentativa.

A senha nunca é lida de volta pela tela. Ela entra, é cifrada e some; o painel mostra
apenas se o último teste passou e quando.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Produto(StrEnum):
    MEUWATT = "meuwatt"
    MEUPLANO = "meuplano"


class EstadoTeste(StrEnum):
    NUNCA = "nunca"
    OK = "ok"
    FALHOU = "falhou"


class Integracao(Base):
    """Uma linha por produto conectado. `produto` é a chave — não há duas do mesmo."""

    __tablename__ = "gs_integracoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto: Mapped[Produto] = mapped_column(
        Enum(Produto, native_enum=False, length=20), unique=True
    )

    base_url: Mapped[str] = mapped_column(String(500))
    usuario_servico: Mapped[str] = mapped_column(String(255))
    senha_cifrada: Mapped[str] = mapped_column(Text)

    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    # Resultado do último teste. Guardado para o painel abrir já dizendo o estado, sem
    # bater nos upstreams a cada carregamento de página.
    estado: Mapped[EstadoTeste] = mapped_column(
        Enum(EstadoTeste, native_enum=False, length=20), default=EstadoTeste.NUNCA
    )
    testada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detalhe_teste: Mapped[str | None] = mapped_column(Text, nullable=True)
    usinas_visiveis: Mapped[int | None] = mapped_column(nullable=True)

    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
