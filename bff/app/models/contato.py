"""Quem mais precisa saber, além do dono da conta.

A notificação nasceu apontando para a CONTA do cliente — uma pessoa, um telefone. A
realidade da usina é outra: quem cuida no dia a dia costuma ser um time — o dono, o
gerente da planta, o engenheiro responsável, às vezes o contador para a parte financeira.
Avisar só a conta faz o recado parar numa pessoa, e o pedido que originou isto foi
literalmente "avise no grupo do cliente".

**Grupo de WhatsApp não é caminho** (a API oficial só fala com grupos que ela mesma cria,
com oito participantes e exigindo Conta Comercial Oficial). O que substitui o grupo é
esta tabela: N contatos por usina, cada um recebendo no privado. Troca-se um grupo por
duas coisas que o grupo não dá — **log por pessoa** (quem recebeu, quem leu) e **escolha
por pessoa** (cada um marca o que quer).

**O contato é da USINA, não do cliente.** A mesma empresa pode ter um responsável em cada
planta, e é da planta que ele quer notícia. Quando a usina muda de dono, os contatos dela
vão junto — e é por isso que a exclusão é em cascata pela usina.

**Aceite é por contato.** A autorização de receber mensagem é de quem recebe; herdar o
aceite do dono da conta colocaria no WhatsApp de terceiros uma mensagem que ninguém
autorizou.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ContatoUsina(Base):
    """Uma pessoa que recebe avisos de uma usina, além do dono da conta."""

    __tablename__ = "gs_contatos_usina"
    __table_args__ = (
        # O mesmo telefone não entra duas vezes na mesma usina: cadastrar de novo é o
        # gestor corrigindo o nome, não criando um segundo destinatário — e sem a trava o
        # cliente receberia o aviso em duplicata.
        UniqueConstraint("plant_link_id", "telefone", name="uq_gs_contato_usina"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_link_id: Mapped[int] = mapped_column(
        ForeignKey("gs_plant_links.id", ondelete="CASCADE"), index=True
    )
    nome: Mapped[str] = mapped_column(String(120))
    #: E.164, normalizado em `core/telefone.py` — um número, um formato.
    telefone: Mapped[str] = mapped_column(String(20), index=True)
    #: "Síndico", "Engenheiro responsável", "Financeiro". Texto livre porque é como a
    #: pessoa é chamada naquela usina, e um enum viraria dívida na primeira exceção.
    papel: Mapped[str | None] = mapped_column(String(60), nullable=True)

    #: Quando ficou registrado que esta pessoa concordou em receber. Nulo = não recebe
    #: nada, por mais que esteja marcado — mesma régua do `whatsapp_aceite_em` do cliente.
    aceite_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aceite_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    criado_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    preferencias: Mapped[list["ContatoPreferencia"]] = relationship(
        back_populates="contato", cascade="all, delete-orphan"
    )

    @property
    def apto(self) -> bool:
        return self.ativo and bool(self.telefone) and self.aceite_em is not None

    @property
    def motivo_de_nao_receber(self) -> str | None:
        if not self.ativo:
            return "O contato está desativado."
        if not self.telefone:
            return "Falta o telefone."
        if self.aceite_em is None:
            return "Falta registrar o aceite deste contato."
        return None


class ContatoPreferencia(Base):
    """O que ESTE contato quer receber desta usina.

    Só o tipo: a usina já está no contato. Presença de linha é a permissão, como em todo
    o resto do sistema — conceder cria, revogar apaga, e não existe o terceiro estado.
    """

    __tablename__ = "gs_contato_preferencias"
    __table_args__ = (UniqueConstraint("contato_id", "tipo", name="uq_gs_contato_pref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contato_id: Mapped[int] = mapped_column(
        ForeignKey("gs_contatos_usina.id", ondelete="CASCADE"), index=True
    )
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contato: Mapped["ContatoUsina"] = relationship(back_populates="preferencias")
