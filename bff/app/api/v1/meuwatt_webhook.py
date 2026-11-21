"""O meuWatt avisa que CONFIRMOU uma parada (ou que um tracker travou/voltou), e o aviso sai na hora.

O dono, 21/11/2026: "preciso que as notificações de desligamentos sejam instantâneas". Antes o GS só descobria a
parada perguntando (o motor de 10 min) e ainda esperava ela durar 20 min (`avisos.PERSISTENCIA_MINUTOS`): até meia
hora depois. Agora quem confirma avisa: o `src/integrations/paradas_webhook.py` do mw-api (o mesmo que avisa o
meuPlano) chama esta rota, e a usina dele é varrida já sem a persistência daqui — a régua é a confirmação de lá.

O corpo só informa QUAL usina: quem decide o que avisar e a quem é a varredura de sempre, lendo o meuWatt de novo
com o token de quem enxerga a usina. Assinatura HMAC-SHA256 com `MEUWATT_WEBHOOK_SECRET` sobre
`"{timestamp}.{corpo}"` (cabeçalhos `X-MeuWatt-Timestamp` e `X-MeuWatt-Signature: sha256=<hex>`); carimbo a mais de
5 min é recusado (reenvio de aviso capturado); sem o segredo, 503. O motor de 10 min segue como rede de segurança.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter(prefix="/api/v1/interno/meuwatt", tags=["interno · meuWatt"])
_log = logging.getLogger(__name__)

TOLERANCIA_S = 300
#: Numa queda regional chegam vários avisos em segundos: uma varredura só cobre todos.
ATRASO_S = 5.0

_pendentes: set[str] = set()
_agendada: asyncio.Task | None = None


def assinatura_valida(segredo: str, timestamp: str | None, corpo: bytes, assinatura: str | None,
                      agora: float | None = None) -> bool:
    if not segredo or not timestamp or not assinatura:
        return False
    try:
        carimbo = int(timestamp)
    except ValueError:
        return False
    if abs((time.time() if agora is None else agora) - carimbo) > TOLERANCIA_S:
        return False
    esperado = "sha256=" + hmac.new(segredo.encode(), timestamp.encode() + b"." + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, assinatura.strip())


async def _varrer() -> None:
    from app.api.v1.avisos import TRAVA, disparar
    from app.core.db import SessionLocal
    from app.services import motor

    global _agendada
    await asyncio.sleep(ATRASO_S)
    # Solta ANTES de varrer: um aviso que chegue durante a varredura agenda a próxima.
    slugs = frozenset(_pendentes)
    _pendentes.clear()
    _agendada = None
    try:
        with SessionLocal() as db:
            async with TRAVA:
                r = await disparar(db, imediatas=slugs)
                rel = await motor.disparar(db, tipos=["parada"], imediatas=slugs)
        _log.info("meuwatt_webhook: %s → push %s enviados (%s repetidos), whatsapp %s enviadas",
                  sorted(slugs), r.enviados, r.repetidos, rel.enviadas)
    except Exception:  # noqa: BLE001 — o motor de 10 min cobre o que falhar aqui
        _log.exception("meuwatt_webhook: a varredura falhou")


@router.post("/paradas")
async def paradas_confirmadas(
    request: Request,
    x_meuwatt_timestamp: str | None = Header(default=None),
    x_meuwatt_signature: str | None = Header(default=None),
) -> dict:
    global _agendada
    segredo = (os.environ.get("MEUWATT_WEBHOOK_SECRET") or "").strip()
    if not segredo:
        raise HTTPException(503, "Webhook do meuWatt não configurado (MEUWATT_WEBHOOK_SECRET ausente).")
    corpo = await request.body()
    if not assinatura_valida(segredo, x_meuwatt_timestamp, corpo, x_meuwatt_signature):
        raise HTTPException(401, "Assinatura inválida.")
    try:
        slug = (json.loads(corpo or b"{}").get("plant") or {}).get("slug")
    except (ValueError, AttributeError, TypeError):
        slug = None
    if isinstance(slug, str) and slug:
        _pendentes.add(slug)
    if _agendada is None:
        _agendada = asyncio.create_task(_varrer())
    return {"ok": True}
