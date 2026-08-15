"""Permissões do aplicativo e dispositivos que recebem push.

**Permissão é presença de linha.** Conceder cria, revogar apaga. Não há coluna
`ativo`, e a ausência dela é deliberada: um booleano cria três estados na cabeça
de quem lê o banco — concedida, revogada e nunca decidida — e os dois últimos se
comportam igual em toda consulta, mas divergem em auditoria e em migração de
dados. Linha existe ou não existe responde a pergunta de uma vez.

**Categoria e subcategoria são texto, não enum de banco.** O catálogo do que pode
ser concedido mora em `app/services/permissoes.py`, em código. Um enum no
Postgres exigiria migração para cada permissão nova — e permissões novas são
justamente o que se espera que aconteça toda semana. O preço é que o banco
aceita um par que o catálogo não conhece; o painel só oferece o que está no
catálogo, e a checagem de permissão nunca vê essa linha órfã.

**Dispositivo é por token, não por usuário.** A mesma pessoa pode ter celular e
tablet, e trocar de aparelho sem avisar. O token do Expo identifica a
instalação; a chave única é ele, e não o par usuário-plataforma — senão instalar
no segundo aparelho derrubaria o push do primeiro em silêncio.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Permissao(Base):
    """Uma permissão concedida a um usuário do aplicativo."""

    __tablename__ = "gs_user_permissions"
    __table_args__ = (
        # Conceder duas vezes não é erro do gestor: ele clica de novo porque a tela
        # demorou. A unicidade transforma isso em no-op em vez de linha duplicada,
        # que faria a revogação apagar uma e deixar a outra valendo.
        UniqueConstraint("user_id", "categoria", "subcategoria", name="uq_gs_permissao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    #: Ex.: `notificacao`.
    categoria: Mapped[str] = mapped_column(String(40), index=True)
    #: Ex.: `usina_parada`.
    subcategoria: Mapped[str] = mapped_column(String(60))

    concedida_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: Quem concedeu. Nulo quando a linha veio de migração ou de processo automático.
    concedida_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    usuario: Mapped["object"] = relationship("User", foreign_keys=[user_id])


class Dispositivo(Base):
    """Uma instalação do aplicativo apta a receber push."""

    __tablename__ = "gs_push_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    #: `ExponentPushToken[...]`. Único: é ele que identifica a instalação.
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    plataforma: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Para saber qual versão do app está instalada quando um push falhar.
    versao_app: Mapped[str | None] = mapped_column(String(32), nullable=True)

    registrado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: Atualizado a cada abertura do app. Token parado há meses é aparelho trocado.
    visto_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AvisoEnviado(Base):
    """Trava de idempotência dos avisos por push.

    Sem esta tabela, cada execução do disparador reenviaria o aviso da MESMA parada:
    a cada 10 minutos o dono receberia de novo que o inversor 3 está parado, e em uma
    noite acumularia dezenas de avisos idênticos — o caminho mais curto para ele
    desligar a notificação e nunca mais ver a que importa.

    A chave carrega `down_since`, então o mesmo inversor parando OUTRA vez, depois de
    voltar, é evento novo e avisa de novo. É a diferença entre "silenciar repetição" e
    "silenciar o assunto".
    """

    __tablename__ = "gs_avisos_enviados"
    __table_args__ = (
        UniqueConstraint("user_id", "chave", name="uq_gs_aviso_enviado"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    #: `{usina}:{equipamento}:{parado_desde}` — estável enquanto for a mesma parada.
    chave: Mapped[str] = mapped_column(String(120), index=True)
    enviado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

