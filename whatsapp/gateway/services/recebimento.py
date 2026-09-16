"""O que fazer com a entrega da Meta — depois de já ter respondido 200 a ela.

## A ordem, e por que ela é essa

1. gravar o corpo cru (`wa_webhook_eventos`) — um INSERT, milissegundos;
2. responder 200 à Meta;
3. processar.

Quem responde devagar é reenviado, e reenvio vira mensagem repetida no celular de alguém.
Quem processa antes de responder é lento por construção. Gravando primeiro, uma queda no
meio do passo 3 não perde nada: a linha fica com `processado_em` nulo e a varredura a retoma.

## Idempotência

`wamid` é UNIQUE. Reentrega da mesma mensagem não cria linha nova — e não é erro: é o
comportamento normal da Meta quando a resposta demora. Status repetido também não regride o
que já avançou (ver `models.mensagem.avanca`).

## Tipo não suportado não é mensagem perdida

Imagem, áudio e documento entram com o `tipo` preenchido e `texto` nulo. Quem exibe escreve
"Áudio — não exibido nesta fase". Descartar aqui apagaria do histórico uma mensagem que o
cliente mandou, e ninguém saberia que ela existiu.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.core.telefone import normalizar
from gateway.meta import payload as parser
from gateway.models.mensagem import Mensagem, WebhookEvento, avanca

log = logging.getLogger(__name__)

#: Quantos eventos pendentes a varredura pega por volta. Teto para uma fila acumulada não
#: virar uma transação gigante que trava o resto.
LOTE_DA_VARREDURA = 50


def guardar(db: Session, corpo: dict[str, Any]) -> WebhookEvento:
    """Grava a entrega crua e devolve a linha. É o que acontece ANTES do 200."""
    evento = WebhookEvento(corpo=corpo)
    db.add(evento)
    db.commit()
    db.refresh(evento)
    return evento


def _aplicar_mensagem(db: Session, m: parser.MensagemRecebida) -> bool:
    """Grava a mensagem recebida. Devolve `True` quando ela é nova."""
    existente = db.scalar(select(Mensagem).where(Mensagem.wamid == m.wamid))
    if existente is not None:
        # Reentrega: atualiza só o que pode ter chegado depois (o nome do perfil costuma
        # vir na segunda). Não toca em texto nem em hora — a primeira versão é a boa.
        if m.nome_perfil and not existente.nome_perfil:
            existente.nome_perfil = m.nome_perfil
        return False

    db.add(
        Mensagem(
            wamid=m.wamid,
            direcao="entrada",
            wa_id=m.wa_id,
            telefone=_telefone(m.wa_id),
            nome_perfil=m.nome_perfil,
            tipo=m.tipo,
            texto=m.texto,
            ocorrida_em=m.ocorrida_em,
            # Mensagem recebida não tem status de entrega: ela chegou. `lida` seria mentira
            # (ninguém do lado de cá leu ainda) e `pendente` faria a tela cobrar um envio.
            status="recebida",
            status_em=m.ocorrida_em,
        )
    )
    return True


def _telefone(wa_id: str) -> str | None:
    try:
        return normalizar(wa_id)
    except ValueError:
        # `wa_id` que não vira E.164 (número de outro país, por exemplo) fica sem telefone:
        # a conversa continua chaveada pelo `wa_id`, que é o que a Meta usa.
        return None


def _aplicar_status(db: Session, s: parser.AvisoDeStatus) -> None:
    mensagem = db.scalar(select(Mensagem).where(Mensagem.wamid == s.wamid))
    if mensagem is None:
        # Status de mensagem que não é nossa (outro sistema usando o mesmo número) — não é
        # erro, e criar linha aqui inventaria uma mensagem que este gateway nunca mandou.
        return
    if not avanca(mensagem.status, s.status):
        return
    mensagem.status = s.status
    mensagem.status_em = s.ocorrida_em
    if s.status == "falhou":
        mensagem.erro_codigo = s.erro_codigo
        mensagem.erro_detalhe = s.erro_detalhe


def processar(db: Session, evento: WebhookEvento) -> dict[str, int]:
    """Aplica uma entrega. Idempotente: rodar duas vezes não duplica nada."""
    contagem = {"mensagens": 0, "novas": 0, "status": 0}
    try:
        leitura = parser.ler(evento.corpo or {})
        for m in leitura.mensagens:
            contagem["mensagens"] += 1
            if _aplicar_mensagem(db, m):
                contagem["novas"] += 1
        for s in leitura.status:
            contagem["status"] += 1
            _aplicar_status(db, s)

        evento.processado_em = datetime.now(UTC)
        evento.erro = None
    except Exception as exc:  # noqa: BLE001 — a varredura tenta de novo
        db.rollback()
        evento.tentativas = (evento.tentativas or 0) + 1
        evento.erro = f"{type(exc).__name__}: {exc}"[:500]
        log.exception("webhook: falha ao processar evento %s", evento.id)
    else:
        evento.tentativas = (evento.tentativas or 0) + 1
    db.commit()
    return contagem


def varrer(db: Session, limite: int = LOTE_DA_VARREDURA) -> int:
    """Reprocessa o que ficou para trás. Devolve quantos eventos foram tocados.

    É a rede de segurança do processamento em segundo plano: deploy no meio, exceção, banco
    fora do ar por um instante. Sem ela, a mensagem do cliente ficaria gravada e invisível.
    """
    pendentes = list(
        db.scalars(
            select(WebhookEvento)
            .where(WebhookEvento.processado_em.is_(None))
            .order_by(WebhookEvento.id)
            .limit(limite)
        ).all()
    )
    for evento in pendentes:
        processar(db, evento)
    return len(pendentes)
