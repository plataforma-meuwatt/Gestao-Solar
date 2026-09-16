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

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from gateway.core.db import SessionLocal, get_db
from gateway.core.seguranca import CABECALHO_ASSINATURA, assinatura_confere
from gateway.models.mensagem import WebhookEvento
from gateway.services import credenciais, recebimento

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


@router.post("/webhook")
async def receber(
    request: Request,
    tarefas: BackgroundTasks,
    db: Session = Depends(get_db),
    assinatura: str | None = Header(default=None, alias=CABECALHO_ASSINATURA),
) -> dict[str, bool]:
    segredo = credenciais.em_uso(db).app_secret
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

    evento = recebimento.guardar(db, dados)
    tarefas.add_task(_processar_depois, evento.id)
    return {"ok": True}
