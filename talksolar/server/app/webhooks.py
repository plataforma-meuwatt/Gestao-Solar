# -*- coding: utf-8 -*-
"""O worker que entrega os webhooks.

Separado do pedido HTTP por um motivo prático: se o meuWatt estiver fora do ar, quem mandou a
mensagem não pode esperar 10 s por isso. **A conversa é síncrona; o aviso é assíncrono.**

O laço é uma thread simples, e isso é suficiente aqui: o volume é de dezenas de entregas por
hora, não milhares por segundo. Trocar por uma fila de verdade (Celery, RQ) é uma decisão para
o dia em que o volume justificar — e, se esse dia chegar, só este arquivo muda.

⚠ **Com duas instâncias, as duas entregariam a mesma coisa.** Enquanto o serviço for uma
instância só, tudo bem; quando não for, a saída é o `FOR UPDATE SKIP LOCKED` na busca dos
pendentes (uma linha nesta consulta) — e está anotado aqui para quem chegar depois não precisar
descobrir sozinho.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

from . import config, integracao
from .models import Entrega

log = logging.getLogger("talksolar.webhooks")

_ligado = False


def pendentes_agora(db, limite: int = 20):
    """As entregas cuja hora chegou. (Com N instâncias: `.with_for_update(skip_locked=True)`.)"""
    return (db.query(Entrega)
            .filter(Entrega.estado == "pendente",
                    Entrega.proxima_em.isnot(None),
                    Entrega.proxima_em <= datetime.utcnow())
            .order_by(Entrega.id).limit(limite).all())


def rodada() -> int:
    """Uma passada. Devolve quantas foram entregues — usado no teste e no laço."""
    db = config.sessao_direta()
    entregues = 0
    try:
        for e in pendentes_agora(db):
            try:
                if integracao.entregar(db, e):
                    entregues += 1
            except Exception:                  # noqa: BLE001
                # o worker NUNCA morre por causa de uma entrega: a próxima ainda precisa sair
                log.warning("entrega_quebrou id=%s", e.id, exc_info=True)
                e.estado = "falhou"
                e.resposta = "erro inesperado no worker"
                e.terminada_em = datetime.utcnow()
            db.commit()
    finally:
        db.close()
    return entregues


def _laco() -> None:
    while True:
        try:
            rodada()
        except Exception:                      # noqa: BLE001
            log.warning("laco_webhooks", exc_info=True)
        time.sleep(5)


def iniciar_worker() -> None:
    """Liga o laço uma vez. `TALK_SEM_WORKER=1` desliga (útil em teste e em script)."""
    global _ligado
    if _ligado or os.getenv("TALK_SEM_WORKER") == "1":
        return
    _ligado = True
    threading.Thread(target=_laco, name="talk-webhooks", daemon=True).start()
    log.info("worker de webhooks ligado")
