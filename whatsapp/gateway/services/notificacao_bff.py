"""Avisar o BFF de que chegou mensagem.

O gateway não sabe quem é cliente, nem o que responder — isso é regra de negócio, e mora no
BFF. Aqui ele só empurra o fato: "chegou isto, deste número".

Melhor esforço, com marca no banco. A falha não derruba o recebimento (a mensagem já está
gravada) e não se perde: `notificada_bff_em` fica nulo e a varredura tenta de novo. É a
mesma escolha do webhook — quem garante é o estado no banco, não a chamada.

Sem `BFF_URL` configurada, nada é tentado e as mensagens ficam marcadas como avisadas. É o
estado correto enquanto o motor do outro lado não existe: sem isso, toda mensagem recebida
acumularia uma tentativa de rede a cada volta, para sempre.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.core.config import get_settings
from gateway.core.seguranca import CABECALHO_CHAVE_INTERNA
from gateway.models.mensagem import Mensagem

log = logging.getLogger(__name__)

TIMEOUT_S = 10.0
CAMINHO = "/api/v1/interno/whatsapp/evento"
LOTE = 50


def _corpo(m: Mensagem) -> dict:
    return {
        "id": m.id,
        "wamid": m.wamid,
        "wa_id": m.wa_id,
        "telefone": m.telefone,
        "nome_perfil": m.nome_perfil,
        "tipo": m.tipo,
        "texto": m.texto,
        "ocorrida_em": m.ocorrida_em.isoformat() if m.ocorrida_em else None,
    }


async def avisar_pendentes(db: Session, limite: int = LOTE) -> int:
    """Manda ao BFF o que ele ainda não viu. Devolve quantas mensagens foram avisadas."""
    s = get_settings()
    pendentes = list(
        db.scalars(
            select(Mensagem)
            .where(
                Mensagem.direcao == "entrada",
                Mensagem.notificada_bff_em.is_(None),
            )
            .order_by(Mensagem.id)
            .limit(limite)
        ).all()
    )
    if not pendentes:
        return 0

    if not s.bff_url or not s.whatsapp_chave_interna:
        # Nada para onde avisar: marca como avisadas para a varredura não ficar tentando a
        # mesma coisa a cada volta. A mensagem continua no banco, inteira.
        agora = datetime.now(UTC)
        for m in pendentes:
            m.notificada_bff_em = agora
        db.commit()
        return 0

    url = s.bff_url.rstrip("/") + CAMINHO
    enviadas = 0
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
        for m in pendentes:
            try:
                r = await cliente.post(
                    url,
                    json=_corpo(m),
                    headers={CABECALHO_CHAVE_INTERNA: s.whatsapp_chave_interna},
                )
                r.raise_for_status()
            except httpx.HTTPError as e:
                # Fica pendente de propósito: a próxima volta tenta de novo.
                log.warning("aviso ao BFF falhou (mensagem %s): %s", m.id, e)
                continue
            m.notificada_bff_em = datetime.now(UTC)
            enviadas += 1
    db.commit()
    return enviadas
