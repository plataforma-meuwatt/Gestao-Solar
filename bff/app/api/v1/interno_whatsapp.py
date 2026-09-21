"""O gateway avisa que chegou mensagem de WhatsApp.

Quem chama é o gateway, não um humano: a porta é a mesma chave interna que o BFF usa para
falar com ele, no padrão de `avisos.py` — segredo em cabeçalho, comparação de tempo
constante, e **sem a chave configurada a rota recusa tudo**.

São duas rotas, e elas respondem perguntas diferentes:

- **`/evento`** — chegou mensagem DE um cliente. Nesta fase o BFF só registra: responder é
  a frente do atendimento, e atender número desconhecido é decisão de negócio.
- **`/status`** — o que aconteceu com o que NÓS mandamos: entregue, lida, falhou. Esta
  fecha o log de notificações, que sem ela pararia em "mandei" e nunca saberia se chegou.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.services import motor

router = APIRouter(prefix="/api/v1/interno/whatsapp", tags=["interno · whatsapp"])
log = logging.getLogger("gs.whatsapp")


def _porta(x_chave_interna: str | None = Header(default=None, alias="X-Chave-Interna")) -> None:
    esperada = get_settings().whatsapp_chave_interna
    if not esperada:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Porta interna do WhatsApp não configurada (WHATSAPP_CHAVE_INTERNA ausente).",
        )
    # `compare_digest` em vez de `==`: a comparação ingênua vaza o segredo pelo tempo de
    # resposta, um caractere por vez.
    if not hmac.compare_digest(x_chave_interna or "", esperada):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave inválida.")


class EventoIn(BaseModel):
    id: int
    wamid: str | None = None
    wa_id: str
    telefone: str | None = None
    nome_perfil: str | None = None
    tipo: str = "text"
    texto: str | None = None
    ocorrida_em: str | None = None


@router.post("/evento", status_code=202, dependencies=[Depends(_porta)])
def receber_evento(corpo: EventoIn) -> dict[str, bool]:
    """Aceita o aviso e registra. 202: recebido, ainda não há o que fazer com ele.

    O 202 não é enfeite — ele diz ao gateway "não precisa reenviar", e ao mesmo tempo não
    promete resposta ao cliente, que é exatamente o estado desta fase.
    """
    log.info(
        "whatsapp recebido: wa_id=%s tipo=%s mensagem=%s",
        corpo.wa_id,
        corpo.tipo,
        corpo.id,
    )
    return {"ok": True}


class StatusIn(BaseModel):
    wamid: str
    #: `enviada` · `entregue` · `lida` · `falhou`, como o gateway já normalizou.
    status: str
    erro_codigo: str | None = None
    erro_detalhe: str | None = None
    ocorrida_em: str | None = None


@router.post("/status", status_code=202, dependencies=[Depends(_porta)])
def receber_status(corpo: StatusIn, db: Session = Depends(get_db)) -> dict[str, bool]:
    """A Meta disse o que aconteceu com uma mensagem nossa.

    Responde 202 mesmo quando o `wamid` não casa com notificação nenhuma — e isso é comum
    e correto: o teste enviado pela tela e o atendimento humano saem pelo mesmo número e
    não têm linha no log de notificações. Devolver erro faria o gateway reenviar para
    sempre um aviso que não tem dono.
    """
    casou = motor.registrar_status(
        db,
        corpo.wamid,
        corpo.status,
        erro=(corpo.erro_detalhe or corpo.erro_codigo),
    )
    log.info("whatsapp status: wamid=%s status=%s casou=%s", corpo.wamid, corpo.status, casou)
    return {"ok": True, "atualizou": casou}
