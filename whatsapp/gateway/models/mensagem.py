"""O que entra e o que sai pelo WhatsApp.

**O evento cru é gravado ANTES de responder 200.** A Meta reenvia o que não recebe resposta
rápida, e reenvio vira mensagem repetida no celular de alguém; mas processar antes de
responder atrasa a resposta e provoca o reenvio do mesmo jeito. A saída é gravar o corpo —
um INSERT, milissegundos —, responder, e processar depois. Se o processo cair no meio, a
linha continua lá com `processado_em` nulo e a varredura a retoma. É a fila que este serviço
não tem, e não precisa ter.

**O `wamid` é a identidade da mensagem.** UNIQUE: reentrega da Meta vira no-op em vez de
segunda linha. Ele é nulo enquanto a mensagem está `pendente` — o id só existe depois de a
Graph aceitar —, e por isso a coluna aceita nulo com UNIQUE (vários nulos convivem em
Postgres e em SQLite).

**Status só avança.** `pendente → enviada → entregue → lida`. Os avisos de status chegam
fora de ordem com frequência (a leitura antes da entrega, por exemplo), e regravar o valor
anterior faria a tela do gestor dizer "enviada" sobre uma mensagem que o cliente já leu.
`falhou` é diferente: grava sempre, porque erro novo é informação nova.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from gateway.core.db import Base

#: A ordem que o status pode percorrer. `falhou` fica fora: ele não avança, ele interrompe.
ORDEM_DO_STATUS = ("pendente", "enviada", "entregue", "lida")


def avanca(atual: str, novo: str) -> bool:
    """O status pode passar de `atual` para `novo`?"""
    if novo == "falhou":
        return True
    if atual == "falhou":
        return False
    try:
        return ORDEM_DO_STATUS.index(novo) > ORDEM_DO_STATUS.index(atual)
    except ValueError:
        return False


class WebhookEvento(Base):
    """A entrega crua da Meta, como ela chegou."""

    __tablename__ = "wa_webhook_eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    recebido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    #: O corpo inteiro. Guardado porque é a única prova do que a Meta mandou quando algo
    #: sair errado — e porque é dele que a varredura reprocessa.
    corpo: Mapped[dict] = mapped_column(JSON)

    processado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    tentativas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)


class Mensagem(Base):
    """Uma mensagem, em qualquer direção."""

    __tablename__ = "wa_mensagens"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Id da Meta. Nulo só enquanto `pendente`; UNIQUE porque reentrega não pode duplicar.
    wamid: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    #: `entrada` (o cliente escreveu) ou `saida` (a empresa mandou).
    direcao: Mapped[str] = mapped_column(String(10), index=True)

    #: O identificador do contato no WhatsApp, como a Meta manda — a chave da conversa.
    wa_id: Mapped[str] = mapped_column(String(32), index=True)
    #: O mesmo número em E.164, quando dá para normalizar. Serve para casar com o cadastro.
    telefone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nome_perfil: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: `text`, `template`, `image`, `audio`… O que a Meta disse que é.
    tipo: Mapped[str] = mapped_column(String(20), default="text")
    #: Nome do template, quando a mensagem foi enviada por modelo aprovado.
    template: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: O texto em si. Nulo em tipo não suportado — e a tela mostra "Áudio", não vazio.
    texto: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Hora do evento SEGUNDO A META, não a do servidor. É ela que a janela de 24 h conta.
    ocorrida_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    status: Mapped[str] = mapped_column(String(20), default="pendente", server_default="pendente")
    status_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erro_codigo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    erro_detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Quem pediu o envio: `bff`, `robo`, ou o que mais vier. Vazio na entrada.
    origem: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Quando o BFF foi avisado desta mensagem. Nulo = a varredura ainda deve avisar.
    notificada_bff_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
