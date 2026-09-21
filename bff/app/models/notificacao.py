"""O que cada cliente recebe, de quais usinas — e o registro do que já foi enviado.

**Preferência é presença de linha**, como a permissão do aplicativo: marcar cria, desmarcar
apaga. Não há coluna `ativo`, pelo mesmo motivo de lá — um booleano criaria três estados
("marcada", "desmarcada" e "nunca decidida") que se comportam igual em toda consulta e
divergem só na leitura humana.

**A linha carrega a usina.** O cliente com dez usinas quase nunca quer o mesmo aviso das
dez: ele quer parada das duas que operam no limite e energia mensal de todas. Uma
preferência por tipo apenas — sem usina — obrigaria o gestor a escolher tudo ou nada, que é
a forma mais rápida de alguém desligar o canal inteiro.

**O tipo é texto, não enum de banco.** O catálogo vive em `services/notificacoes.py`, em
código: tipo novo é uma linha lá, sem migração. O preço é o banco aceitar um tipo que o
catálogo não conhece — inofensivo por construção, porque a tela só oferece o que está no
catálogo e o motor só percorre o catálogo.

**Nada nasce ligado.** Cliente recém-cadastrado não tem linha nenhuma: sem o gestor marcar,
ele não recebe nada. É a mesma regra das usinas e das permissões.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class NotificacaoPreferencia(Base):
    """Este cliente quer ESTE aviso DESTA usina."""

    __tablename__ = "gs_notificacao_preferencias"
    __table_args__ = (
        # Marcar duas vezes é o gestor clicando de novo porque a tela demorou — vira no-op,
        # não linha duplicada (que faria a revogação apagar uma e deixar a outra valendo).
        UniqueConstraint("user_id", "tipo", "plant_link_id", name="uq_gs_notificacao_pref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    #: Chave do catálogo: `parada`, `energia_dia`… Ver `services/notificacoes.py`.
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    #: A usina a que este aviso se refere. CASCADE porque preferência de usina apagada não
    #: significa nada — e deixá-la viva faria o motor procurar uma usina que não existe.
    plant_link_id: Mapped[int] = mapped_column(
        ForeignKey("gs_plant_links.id", ondelete="CASCADE"), index=True
    )

    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: Quem marcou. Nulo quando veio de migração ou de processo automático.
    criada_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    usuario: Mapped["object"] = relationship("User", foreign_keys=[user_id])
    usina: Mapped["object"] = relationship("PlantLink", foreign_keys=[plant_link_id])


class NotificacaoEnviada(Base):
    """Trava de repetição e histórico do que saiu para o cliente.

    A `chave` identifica o EVENTO, não a mensagem: `parada:4:slot-11@2026-09-15T17:57` é a
    mesma parada em qualquer volta do motor, e a UNIQUE com o usuário é o que impede o
    celular dele tocar duas vezes pelo mesmo fato. Ela é gravada ANTES do envio — se o
    envio falhar, a linha fica com `status='falhou'` e o erro, que é informação; gravar
    depois abriria a janela de duas voltas simultâneas enviando o mesmo aviso.

    `destino` guarda o número para onde foi, e não é decoração: o cliente troca de telefone,
    e o histórico precisa dizer para onde a mensagem antiga foi, não para onde iria hoje.
    """

    __tablename__ = "gs_notificacoes_enviadas"
    __table_args__ = (
        # Duas travas, uma por tipo de destinatário. `NULL` nunca colide com `NULL` num
        # índice único, então as linhas de contato (com `user_id` nulo) não disputam a
        # trava do cliente, e vice-versa.
        UniqueConstraint("user_id", "chave", name="uq_gs_notificacao_enviada"),
        UniqueConstraint("contato_id", "chave", name="uq_gs_notificacao_contato"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Nulo quando quem recebeu foi um CONTATO da usina, e não a conta do cliente. Os dois
    #: nunca vêm preenchidos juntos: uma linha é de um destinatário só.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    contato_id: Mapped[int | None] = mapped_column(
        ForeignKey("gs_contatos_usina.id", ondelete="CASCADE"), index=True, nullable=True
    )
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    #: `{tipo}:{usina}:{o que torna este evento único}`.
    chave: Mapped[str] = mapped_column(String(160), index=True)
    #: SET NULL: apagar a usina não apaga o registro de que o cliente foi avisado.
    plant_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("gs_plant_links.id", ondelete="SET NULL"), nullable=True
    )

    #: `whatsapp` hoje. Nomeado porque o mesmo evento pode sair por outro canal amanhã, e
    #: aí a trava precisa distinguir "já mandei por WhatsApp" de "já mandei por push".
    canal: Mapped[str] = mapped_column(String(20), default="whatsapp", server_default="whatsapp")
    #: O número para onde foi, em E.164.
    destino: Mapped[str | None] = mapped_column(String(20), nullable=True)

    #: `pendente` → `enviada` → `entregue` → `lida`, ou `falhou`. O gateway atualiza.
    status: Mapped[str] = mapped_column(String(20), default="pendente", server_default="pendente")
    status_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Id da mensagem no WhatsApp — é por ele que o status volta.
    wamid: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    usina: Mapped["object"] = relationship("PlantLink", foreign_keys=[plant_link_id])
