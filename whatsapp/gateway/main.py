"""Gateway de WhatsApp do Gestão Solar — recebe da Meta, envia pela Meta.

Serviço próprio, com banco próprio e deploy próprio. Ele não conhece cliente, usina nem
regra de notificação: guarda mensagem, entrega template e avisa o BFF, que é quem decide.

**Não serve tela e não fala com navegador**, então não há CORS aqui. Quem o chama é a Meta
(webhook, autenticado por assinatura) e o BFF (porta interna, autenticada por chave).

A varredura periódica é a rede de segurança dos dois caminhos assíncronos: eventos gravados
e não processados, e mensagens recebidas que o BFF ainda não viu. Sem ela, um deploy no
instante errado deixaria a mensagem do cliente parada no banco, invisível.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gateway.api import interno, webhook
from gateway.core.config import get_settings
from gateway.core.db import SessionLocal
from gateway.services import notificacao_bff, recebimento

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")

settings = get_settings()
settings.validar_producao()

#: De quanto em quanto tempo a varredura roda. Um minuto é curto o bastante para o atraso
#: não ser sentido e longo o bastante para não pesar no banco compartilhado com o BFF.
INTERVALO_DA_VARREDURA_S = 60


async def _varredura() -> None:
    while True:
        await asyncio.sleep(INTERVALO_DA_VARREDURA_S)
        db = SessionLocal()
        try:
            retomados = recebimento.varrer(db)
            avisados = await notificacao_bff.avisar_pendentes(db)
            if retomados or avisados:
                log.info("varredura: %s evento(s) retomado(s), %s aviso(s)", retomados, avisados)
        except Exception:  # noqa: BLE001 — uma volta ruim não pode matar o laço
            log.exception("varredura falhou")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    tarefa = asyncio.create_task(_varredura())
    try:
        yield
    finally:
        tarefa.cancel()


app = FastAPI(
    title="Gestão Solar — gateway de WhatsApp",
    version="0.1.0",
    lifespan=lifespan,
    # Em produção a documentação fica fechada: ela descreveria a porta interna inteira para
    # quem topar com o endereço do serviço.
    docs_url=None if settings.producao else "/docs",
    redoc_url=None,
)

app.include_router(webhook.router)
app.include_router(interno.router)


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    """Sonda de saúde: é sobre o processo estar de pé, não sobre o WhatsApp estar
    configurado. Para essa outra pergunta existe a tela de administração, que lê
    `/interno/credenciais`."""
    return {"status": "ok", "ambiente": settings.environment}
