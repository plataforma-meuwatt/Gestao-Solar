"""BFF do Gestão Solar.

Agrega a mw-api (meuWatt) e o backend do meuPlano num contrato só, aplica a autorização do
dono da usina e hospeda o financeiro de mensalidades — que não existe em nenhum dos dois.

Serve também o painel do gestor em `/painel`: onde as pontes com os dois produtos são
configuradas e as usinas dos dois lados são casadas.

Contrato completo em `docs/CONTRATO_API.md`.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.v1 import painel, painel_clientes
from app.core.config import get_settings

settings = get_settings()
settings.validar_producao()

app = FastAPI(
    title="Gestão Solar BFF",
    version="0.1.0",
    # Em produção o Swagger fica fora — mesma postura da mw-api.
    docs_url=None if settings.producao else "/docs",
    redoc_url=None,
    openapi_url=None if settings.producao else "/openapi.json",
)

app.include_router(painel.router)
app.include_router(painel_clientes.router)

_PAGINA_PAINEL = Path(__file__).parent / "web" / "painel.html"


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "ambiente": settings.environment}


@app.get("/painel", include_in_schema=False)
def pagina_painel() -> FileResponse:
    """Página única do painel. Servida pelo próprio BFF de propósito: é uma ferramenta
    interna de poucas telas, e um segundo projeto de front só para ela custaria mais em
    build e deploy do que entrega."""
    return FileResponse(_PAGINA_PAINEL, media_type="text/html")


# Os routers do app entram aqui conforme as fases avançam:
#   Fase 1  auth, plants
#   Fase 2  generation
#   Fase 3  equipment
#   Fase 4  maintenance
#   Fase 5  documents
#   Fase 6  billing
#   Fase 7  assistant, notifications
