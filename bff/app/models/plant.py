"""Vínculo entre a usina do meuWatt e a do meuPlano.

Os dois sistemas nunca se falaram: o `Usina.plant_code` do meuPlano existe "p/ reconciliação
futura" mas está vazio, e não há FK entre eles. Este é o ponto único que amarra os dois
lados — preenchido por seed ou pela tela de admin, não automaticamente.

Uma usina pode existir só de um lado (`mw_plant_slug` ou `mp_usina_id` nulo); nesse caso o
app esconde a aba correspondente.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PlantLink(Base):
    __tablename__ = "gs_plant_links"
    # a mesma usina de um produto numa usina daqui só: o `salvar_usina` já confere, e o registro pela porta dos
    # sistemas, com dois pedidos ao mesmo tempo, precisava da trava no banco (o avaliador do R10, 24/11/2026)
    __table_args__ = (
        Index("ux_gs_plant_links_mw_slug", "mw_plant_slug", unique=True,
              postgresql_where=text("mw_plant_slug IS NOT NULL"), sqlite_where=text("mw_plant_slug IS NOT NULL")),
        Index("ux_gs_plant_links_mp_usina", "mp_usina_id", unique=True,
              postgresql_where=text("mp_usina_id IS NOT NULL"), sqlite_where=text("mp_usina_id IS NOT NULL")),
    )

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
    #: Plano Casa GS (24/11/2026): os dados básicos da usina moram no GS (nome, endereço, coordenada) e o mapa mora no
    #: TermoVision. `tv_codigo` é o código da usina lá, gravado pelo "Enviar ao GS" do TermoVision
    #: (`api/v1/interno_termovision.py`); um código só por usina, e uma usina só por código.
    tv_codigo: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    endereco: Mapped[str | None] = mapped_column(String(300), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: a DONA da usina (Plano Casa GS, R11): uma só por usina, como a PROPRIETARIA do meuPlano
    proprietaria_id: Mapped[int | None] = mapped_column(
        ForeignKey("gs_proprietarias.id", ondelete="SET NULL"), index=True, nullable=True
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: quando um dado básico mudou por último (`services/dados_da_usina.alterar`): os sistemas releem com
    #: `GET /api/v1/interno/usinas?alteradas_desde=`
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

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


class HistoricoDaUsina(Base):
    """Cada mudança de um dado básico da usina (Plano Casa GS, 24/11/2026: "com histórico: quem mudou, de qual sistema,
    o antes e o depois"). Uma linha por campo."""

    __tablename__ = "gs_usinas_historico"

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_link_id: Mapped[int] = mapped_column(ForeignKey("gs_plant_links.id", ondelete="CASCADE"), index=True)
    campo: Mapped[str] = mapped_column(String(40))
    antes: Mapped[str | None] = mapped_column(String(400), nullable=True)
    depois: Mapped[str | None] = mapped_column(String(400), nullable=True)
    por_id: Mapped[int | None] = mapped_column(ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True)
    #: de onde veio: gs (as telas daqui), meuwatt, meuplano, meuguarda, termovision
    sistema: Mapped[str] = mapped_column(String(20))
    motivo: Mapped[str] = mapped_column(String(200), default="", server_default="")
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UsinaAConfirmar(Base):
    """Usina criada em outro sistema que parece uma que já existe no GS (nome ou distância): fica aqui até o gerente da
    O&M dizer se é a mesma, se é outra ou se descarta (Plano Casa GS). Uma linha por usina de lá (`sistema` +
    `referencia`): pedir de novo devolve a decisão."""

    __tablename__ = "gs_usinas_a_confirmar"
    __table_args__ = (UniqueConstraint("empresa_id", "sistema", "referencia",
                                       name="ux_gs_usinas_a_confirmar_empresa_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("gs_empresas.id", ondelete="CASCADE"), index=True)
    sistema: Mapped[str] = mapped_column(String(20))
    #: o id da usina lá (o slug no meuWatt, o número no meuPlano, o código no TermoVision)
    referencia: Mapped[str] = mapped_column(String(120))
    #: o que o sistema mandou: nome, cidade, uf, endereco, latitude, longitude, kwp
    dados: Mapped[dict] = mapped_column(JSON)
    #: as do GS que parecem ser ela, no momento do pedido
    parecidas: Mapped[list] = mapped_column(JSON)
    pedido_por_id: Mapped[int | None] = mapped_column(ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True)
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: nula enquanto espera; mesma, outra ou descartada
    decisao: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: a usina do GS que ficou: a mesma escolhida, ou a criada
    usina_id: Mapped[int | None] = mapped_column(ForeignKey("gs_plant_links.id", ondelete="SET NULL"), nullable=True)
    decidido_por_id: Mapped[int | None] = mapped_column(ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True)
    decidido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
