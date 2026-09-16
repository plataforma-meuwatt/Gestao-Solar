"""As credenciais da Meta, cadastradas pela tela e guardadas cifradas.

**Uma linha só.** Não há credencial por cliente nem por usina: o WhatsApp é um número da
empresa, com um app na Meta. A unicidade é imposta por `escopo`, que vale sempre `padrao` e
é UNIQUE — o mesmo truque do `produto` em `gs_integracoes`, e é o que impede duas linhas
divergindo em silêncio depois de alguém gravar duas vezes.

**O que fica em claro e o que é cifrado.** Em claro: número, WABA, app, o prefixo do token e
o resultado do último teste — nada disso dá acesso a nada, e é o que a tela precisa mostrar
para o gestor reconhecer qual credencial está lá. Cifrados: o token, o segredo do app e o
token de verificação.

**O prefixo existe para reconhecer, não para usar.** `EAAG1ab…` na tela é o que permite
achar o token certo na lista do Gerenciador da Meta na hora de revogar. Sem ele, revogar
vira tentativa e erro — e errar aqui derruba o envio da empresa inteira.

**O histórico é append-only.** Quem gravou, quando, o que o teste respondeu. É o que
responde "desde quando parou?" — a pergunta que o estado atual nunca responde.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from gateway.core.db import Base

#: Valor único do escopo enquanto existir um número só. A coluna existe para que um dia
#: haver dois números seja uma linha nova, e não uma migração.
ESCOPO_PADRAO = "padrao"


class Credencial(Base):
    """O app da Meta que este gateway usa."""

    __tablename__ = "wa_credenciais"
    __table_args__ = (UniqueConstraint("escopo", name="uq_wa_credencial_escopo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    escopo: Mapped[str] = mapped_column(String(20), default=ESCOPO_PADRAO, server_default=ESCOPO_PADRAO)

    # ── identificadores, em claro ────────────────────────────────────────────
    #: O número de onde a mensagem sai (Phone Number ID, não o telefone).
    phone_number_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Só para a tela dizer qual conta e qual app estão configurados.
    waba_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    app_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: `+55 16 99999-8888`, o número em si — o que o gestor reconhece. Não é usado no envio.
    numero_exibicao: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ── segredos, cifrados ───────────────────────────────────────────────────
    token_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `EAAG1ab` em claro: identifica o token na lista da Meta, para revogar o certo.
    token_prefixo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    token_gravado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Segredo do APP. É com ele que a assinatura de cada entrega do webhook é conferida.
    app_secret_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O que a Meta manda em `hub.verify_token` ao registrar a URL de callback.
    verify_token_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── resultado do último teste ────────────────────────────────────────────
    #: `nunca` | `ok` | `falhou`. Guardado para a tela abrir dizendo o estado sem bater na
    #: Meta a cada carregamento.
    estado: Mapped[str] = mapped_column(String(20), default="nunca", server_default="nunca")
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    testada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    #: Quem gravou, como o painel informou (e-mail ou apelido do gestor).
    atualizada_por: Mapped[str | None] = mapped_column(String(120), nullable=True)

    @property
    def envio_pronto(self) -> bool:
        return bool(self.token_cifrado and self.phone_number_id)

    @property
    def webhook_pronto(self) -> bool:
        return bool(self.app_secret_cifrado and self.verify_token_cifrado)


class CredencialEvento(Base):
    """O que aconteceu com a credencial — append-only, por convenção."""

    __tablename__ = "wa_credencial_eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: `gravada` · `testada_ok` · `testada_falhou` · `removida` · `webhook_verificado`.
    evento: Mapped[str] = mapped_column(String(30), index=True)
    ocorrido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    ator: Mapped[str | None] = mapped_column(String(120), nullable=True)
    token_prefixo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Quantos números o app respondeu no teste — o "alcance", como as usinas visíveis do BFF.
    numeros_visiveis: Mapped[int | None] = mapped_column(Integer, nullable=True)
