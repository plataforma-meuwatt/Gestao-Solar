"""O WhatsApp Business de cada técnico, conectado pelo Embedded Signup.

**Uma linha por NÚMERO**, não por pessoa nem por empresa. É o `phone_number_id` que a Meta
põe em cada entrega do webhook (`value.metadata.phone_number_id`), então é por ele que a
mensagem acha o dono — e é por isso que ele é UNIQUE: um número com dois donos faria a
conversa do técnico A aparecer para o técnico B.

**O dono e o inquilino são referências opacas.** `gs_user_id` e `empresa_id` são ids do
BFF, que o gateway guarda sem conhecer: ele "não conhece cliente nem usina" (ver
`main.py`), e uma FK para `gs_users` amarraria duas cadeias de migration que vivem
separadas de propósito (`alembic_version_gateway`).

**O app da Meta é da PLATAFORMA, o número é do técnico.** O `app_secret` e o
`verify_token` continuam na linha `padrao` de `wa_credenciais` — um app, uma callback.
Aqui fica só o que é do número: o token que o Embedded Signup devolveu para ele.

Ver `docs/PLANO_WHATSAPP_TECNICOS.md` no repositório.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from gateway.core.db import Base


class Conta(Base):
    """Um número de WhatsApp Business conectado ao app da plataforma."""

    __tablename__ = "wa_contas"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ── a Meta ──────────────────────────────────────────────────────────────
    phone_number_id: Mapped[str] = mapped_column(String(40), unique=True)
    #: Indexado porque a DESCONEXÃO chega por ele: `account_update` / `PARTNER_REMOVED`
    #: traz `waba_info.waba_id`, e não o número.
    waba_id: Mapped[str] = mapped_column(String(40), index=True)
    business_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: `+55 16 99999-8888` — o que o técnico reconhece na tela. Não é usado no envio.
    numero_exibicao: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nome_verificado: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: O número continua no aplicativo do celular (`FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`).
    #: Muda duas coisas: NÃO se chama `/register`, e o celular parado ~14 dias desconecta.
    coexistencia: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # ── o segredo do número ─────────────────────────────────────────────────
    #: O token que a troca do `code` devolveu. Cifrado; nulo depois de desconectar.
    token_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_prefixo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: O PIN de duas etapas que NÓS escolhemos no `/register` — só existe fora da
    #: coexistência. Guardado porque registrar de novo o mesmo número pede o mesmo PIN.
    pin_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── de quem é ───────────────────────────────────────────────────────────
    gs_user_id: Mapped[int] = mapped_column(Integer, index=True)
    empresa_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # ── estado ──────────────────────────────────────────────────────────────
    #: `conectada` · `desconectada`. A Meta desconecta sozinha (celular parado, número
    #: trocado) e avisa por `account_update` — a tela precisa dizer isso ao técnico.
    estado: Mapped[str] = mapped_column(String(20), default="conectada", server_default="conectada")
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    conectada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    desconectada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def conectada(self) -> bool:
        return self.estado == "conectada" and bool(self.token_cifrado)
