"""O aviso do TermoVision a cada etapa de um "Processar <usina>" pedido pelo bot (`assistente_termovision`).

O corpo do aviso não é acreditado: só o `token` serve, e só se for de um pedido daqui. O andamento é RELIDO no
TermoVision (`GET /api/processar/<token>`, público) e a mensagem sai quando a etapa muda. Responde na hora (o
TermoVision espera 5 s); o resto roda depois.
"""
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.clients import whatsapp
from app.core.db import SessionLocal
from app.models.processamento_tv import ProcessamentoTV
from app.services import assistente_termovision as tv

log = logging.getLogger(__name__)
router = APIRouter(tags=["interno"])


class Aviso(BaseModel):
    token: str


async def _repassar(token: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{tv._base()}/api/processar/{token}")
        r.raise_for_status()
        andamento = r.json()
    except httpx.HTTPError as e:
        log.warning("termovision_aviso: não releu %s…: %s", token[:8], e)
        return
    chave, texto = tv.mensagem(andamento)
    with SessionLocal() as db:
        p = db.scalar(select(ProcessamentoTV).where(ProcessamentoTV.token == token))
        if p is None or p.avisado == chave or not texto:
            return
        p.avisado = chave
        db.commit()
        telefone = p.telefone
    try:
        await whatsapp.enviar_conteudo(telefone=telefone, tipo="text", texto=texto, origem="termovision")
    except Exception:                                      # noqa: BLE001 — fora da janela de 24 h a Meta recusa
        log.warning("termovision_aviso: a mensagem de %s… não saiu", token[:8], exc_info=True)


@router.post(tv.AVISO)
def aviso(body: Aviso, tarefas: BackgroundTasks) -> dict:
    with SessionLocal() as db:
        if db.scalar(select(ProcessamentoTV.id).where(ProcessamentoTV.token == body.token)) is None:
            raise HTTPException(404, "pedido desconhecido")
    tarefas.add_task(_repassar, body.token)
    return {"ok": True}
