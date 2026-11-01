"""A porta da Meta.

**GET** é a verificação feita ao registrar a URL de callback: a Meta manda `hub.mode`,
`hub.verify_token` e `hub.challenge`, e espera o challenge de volta em TEXTO PURO. Devolver
JSON aqui faz o registro falhar com uma mensagem que não explica nada. Os três parâmetros
têm ponto no nome, que não vira nome de argumento em Python — por isso são lidos de
`request.query_params`.

**POST** é a entrega. A assinatura (`X-Hub-Signature-256`) é conferida sobre os BYTES CRUS,
e por isso `await request.body()` vem antes de qualquer conversão: conferir sobre o objeto
já convertido faria a verificação falhar por formatação, não por origem.

Sem credencial cadastrada, as duas respondem 503 — o estado de quem ainda não preencheu a
tela de administração. Aceitar tudo deixaria qualquer um forjar mensagem; responder 200
calado faria a Meta acreditar que fomos avisados e nunca reenviar.

O 200 sai ANTES do processamento, que roda em `BackgroundTasks` com sessão própria. A Meta
reenvia o que demora, e reenvio é mensagem repetida no celular de alguém.
"""

import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from gateway.core.config import get_settings
from gateway.core.db import SessionLocal, get_db
from gateway.core.seguranca import CABECALHO_ASSINATURA, assinatura_confere
from gateway.meta import graph
from gateway.models.mensagem import WebhookEvento
from gateway.services import credenciais, notificacao_bff, recebimento

router = APIRouter(tags=["webhook"])
log = logging.getLogger(__name__)


@router.get("/webhook", response_class=Response)
def verificar(request: Request, db: Session = Depends(get_db)) -> Response:
    """Confirma a URL de callback para a Meta."""
    modo = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    desafio = request.query_params.get("hub.challenge") or ""

    esperado = credenciais.em_uso(db).verify_token
    if not esperado:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WhatsApp ainda não configurado: cadastre o token de verificação na tela de "
            "administração do WhatsApp, no painel.",
        )
    if modo != "subscribe" or token != esperado:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verificação recusada.")

    credenciais.registrar(db, "webhook_verificado", detalhe="A Meta confirmou a URL.")
    db.commit()
    return Response(content=desafio, media_type="text/plain")


async def _encaminhar(corpo: bytes, assinatura: str) -> None:
    """Repassa os BYTES CRUS com a assinatura da Meta: quem recebe confere o HMAC com o
    mesmo segredo do app, como se viesse dela. Melhor esforço — o evento já está guardado."""
    for url in filter(None, (u.strip() for u in get_settings().encaminhar_urls.split(","))):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(url, content=corpo, headers={
                    CABECALHO_ASSINATURA: assinatura, "Content-Type": "application/json"})
        except httpx.HTTPError:
            log.warning("webhook: encaminhar para %s falhou", url, exc_info=True)


#: O que o bot não responde (a lista do BFF, `assistente.IGNORADOS`): para esses não sai "digitando…".
SEM_RESPOSTA = {"reaction", "sticker", "system", "ephemeral", "request_welcome", "unsupported"}
#: Entrega mais velha que isto é fila atrasada (deploy, Meta reenviando): o BFF decide se responde.
RECENTE_S = 120


def _a_responder(dados: dict) -> list[str]:
    """Os wamids das mensagens novas desta entrega que o bot vai responder (status de envio não contam)."""
    agora, wamids = time.time(), []
    for e in dados.get("entry") or []:
        for c in e.get("changes") or []:
            for m in (c.get("value") or {}).get("messages") or []:
                try:
                    recente = agora - int(m.get("timestamp") or 0) < RECENTE_S
                except (TypeError, ValueError):
                    recente = False
                if m.get("id") and m.get("type") not in SEM_RESPOSTA and recente:
                    wamids.append(m["id"])
    return wamids


async def _digitando_ja(cred, dados: dict) -> None:
    """"Digitando…" no instante em que a Meta entrega, antes de qualquer ida ao banco. Antes ele só saía depois de o
    gateway gravar e avisar e de a API ler a conta e a conversa: ~20 idas ao banco dos EUA (185 ms cada, 3 s para
    reabrir a conexão), de 4 a 21 s de tela parada (medido em 01/11/2026). Melhor esforço, no máximo 3 s."""
    if not cred.envio_pronto:
        return
    for wamid in _a_responder(dados):
        try:
            await asyncio.wait_for(graph.digitando(token=cred.token, phone_number_id=cred.phone_number_id,
                                                   wamid=wamid), 3)
        except TimeoutError:
            log.warning("webhook: o digitando de %s passou de 3 s", wamid)


def _processar_depois(evento_id: int) -> None:
    """Roda fora da requisição: a sessão da rota já foi fechada quando isto começa."""
    db = SessionLocal()
    try:
        evento = db.get(WebhookEvento, evento_id)
        if evento is not None:
            recebimento.processar(db, evento)
    except Exception:  # noqa: BLE001 — a varredura pega o que falhar aqui
        log.exception("webhook: processamento em segundo plano falhou (evento %s)", evento_id)
    finally:
        db.close()


async def _avisar_o_bff() -> None:
    """Avisa o BFF NA HORA da mensagem que acabou de ser gravada. Só a varredura de 60 s
    avisava: a pessoa esperava até um minuto, e a senha mandada antes do resumo podia chegar
    ao bot depois dele (avaliação 11). A varredura continua, para o que falhar aqui."""
    db = SessionLocal()
    try:
        await notificacao_bff.avisar_pendentes(db)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("webhook: aviso imediato ao BFF falhou (a varredura tenta de novo)")
    finally:
        db.close()


@router.post("/webhook")
async def receber(
    request: Request,
    tarefas: BackgroundTasks,
    db: Session = Depends(get_db),
    assinatura: str | None = Header(default=None, alias=CABECALHO_ASSINATURA),
) -> dict[str, bool]:
    cred = credenciais.em_uso(db)
    segredo = cred.app_secret
    if not segredo:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WhatsApp ainda não configurado: cadastre o segredo do app na tela de "
            "administração do WhatsApp, no painel.",
        )

    corpo = await request.body()
    if not assinatura_confere(segredo, corpo, assinatura):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura inválida.")

    try:
        dados = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Corpo não é JSON.") from None

    await _digitando_ja(cred, dados)
    evento = recebimento.guardar(db, dados)
    tarefas.add_task(_processar_depois, evento.id)
    tarefas.add_task(_avisar_o_bff)
    tarefas.add_task(_encaminhar, corpo, assinatura)
    return {"ok": True}
