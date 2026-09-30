"""Vínculo entre a usina do meuWatt e a do meuPlano.

Os dois sistemas nunca se falaram: o `Usina.plant_code` do meuPlano existe "p/ reconciliação
futura" mas está vazio, e não há FK entre eles. Este é o ponto único que amarra os dois
lados — preenchido por seed ou pela tela de admin, não automaticamente.

Uma usina pode existir só de um lado (`mw_plant_slug` ou `mp_usina_id` nulo); nesse caso o
app esconde a aba correspondente.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PlantLink(Base):
    __tablename__ = "gs_plant_links"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Identificadores nos upstreams. O meuWatt endereça por slug; o meuPlano por id int.
    mw_plant_slug: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    mp_usina_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # A micro usina do MICRO (meuWatt `GET /micro/plants`, id numérico) — usina que vem dos
    # portais dos fabricantes (Solis, Canadian) e não é uma usina do monitoramento do
    # meuWatt. Opcional e ADICIONAL: por ela o motor avisa "usina parada"; as telas do
    # aplicativo continuam lendo pelo `mw_plant_slug`/`mp_usina_id`.
    mw_micro_plant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Denormalizado para a lista de usinas carregar sem depender dos dois upstreams.
    #: De qual empresa de O&M é esta usina. Nulo só existe durante a migração; usina sem
    #: dono é usina que toda empresa enxerga.
    empresa_id: Mapped[int | None] = mapped_column(
        ForeignKey("gs_empresas.id", ondelete="RESTRICT"), index=True, nullable=True
    )

    nome: Mapped[str] = mapped_column(String(255))
    cidade: Mapped[str | None] = mapped_column(String(120), nullable=True)
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)
    kwp: Mapped[float | None] = mapped_column(Float, nullable=True)

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def tem_meuwatt(self) -> bool:
        return self.mw_plant_slug is not None

    @property
    def tem_meuplano(self) -> bool:
        return self.mp_usina_id is not None

    @property
    def so_micro(self) -> bool:
        """A usina existe SÓ no portal do fabricante (Solis, Canadian, TSUN).

        **Sozinha ela já é uma usina** — há cliente cujo único monitoramento é esse. A
        pergunta mora aqui porque é feita em toda tela que decide de onde ler, e cada
        cópia dela é uma chance de uma tela dizer "não monitorada" enquanto a vizinha
        mostra a potência de agora, que foi o que aconteceu em 30/09/2026.
        """
        return self.mw_micro_plant_id is not None and self.mw_plant_slug is None
