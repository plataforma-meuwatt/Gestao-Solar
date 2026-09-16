"""O gateway avisa que chegou mensagem de WhatsApp.

Quem chama é o gateway, não um humano: a porta é a mesma chave interna que o BFF usa para
falar com ele, no padrão de `avisos.py` — segredo em cabeçalho, comparação de tempo
constante, e **sem a chave configurada a rota recusa tudo**.

**Nesta fase o BFF só registra.** Responder ao cliente é a frente do robô, que ainda não
existe; e atender número desconhecido é decisão de negócio ("só cliente cadastrado recebe e
envia"). Deixar a rota pronta agora tem um motivo prático: sem ela, o gateway tentaria
avisar a cada volta da varredura e acumularia tentativa para sempre — e quando o robô
chegar, o caminho já estará provado.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.core.config import get_settings

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
