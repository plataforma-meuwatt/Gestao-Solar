"""Assinaturas e mensalidades dos produtos meuWatt e meuPlano.

Isto não existe em nenhum dos dois upstreams: o `/api/v1/financeiro` do meuPlano é contas a
pagar interno, e o `/api/v1/client/financeiro` cobra contrato de O&M, não assinatura de
produto. Nasce aqui.

Na v1 não há gateway de pagamento — as parcelas são cadastradas e baixadas à mão. O modelo
foi desenhado para aceitar um gateway depois sem refazer as telas: bastaria preencher
`pago_em` por webhook em vez de à mão.
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Produto(StrEnum):
    MEUWATT = "meuwatt"
    MEUPLANO = "meuplano"


class SituacaoFatura(StrEnum):
    """Derivada em leitura, nunca gravada — mesmo padrão do `_situacao()` do meuPlano."""

    PAGO = "pago"
    A_VENCER = "a_vencer"
    EM_ABERTO = "em_aberto"
    VENCIDO = "vencido"


class Subscription(Base):
    __tablename__ = "gs_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # A cobrança é por CLIENTE, não por usina: um dono com três usinas paga uma assinatura
    # de cada produto, não três.
    user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    produto: Mapped[Produto] = mapped_column(Enum(Produto, native_enum=False, length=20))

    valor_mensal: Mapped[float] = mapped_column(Numeric(12, 2))
    dia_vencimento: Mapped[int] = mapped_column(Integer)
    inicio: Mapped[date] = mapped_column(Date)
    fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    faturas: Mapped[list["Invoice"]] = relationship(
        back_populates="assinatura", cascade="all, delete-orphan"
    )


class Invoice(Base):
    __tablename__ = "gs_invoices"
    __table_args__ = (
        UniqueConstraint("subscription_id", "competencia", name="uq_assinatura_competencia"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("gs_subscriptions.id", ondelete="CASCADE"), index=True
    )

    competencia: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    valor: Mapped[float] = mapped_column(Numeric(12, 2))
    vencimento: Mapped[date] = mapped_column(Date)
    pago_em: Mapped[date | None] = mapped_column(Date, nullable=True)

    comprovante_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    observacao: Mapped[str | None] = mapped_column(String(500), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assinatura: Mapped["Subscription"] = relationship(back_populates="faturas")

    def situacao(self, hoje: date | None = None) -> SituacaoFatura:
        """Pago vence tudo; depois é o vencimento contra hoje.

        "A vencer" é a janela dos próximos 7 dias — é o que a tela destaca como próximo
        compromisso. Antes disso, é só "em aberto".
        """
        if self.pago_em is not None:
            return SituacaoFatura.PAGO
        hoje = hoje or date.today()
        if self.vencimento < hoje:
            return SituacaoFatura.VENCIDO
        if (self.vencimento - hoje).days <= 7:
            return SituacaoFatura.A_VENCER
        return SituacaoFatura.EM_ABERTO
