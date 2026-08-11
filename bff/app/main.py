"""BFF do Gestão Solar.

Agrega a mw-api (meuWatt) e o backend do meuPlano num contrato só, aplica a autorização do
dono da usina e hospeda o financeiro de mensalidades — que não existe em nenhum dos dois.

Contrato completo em `docs/CONTRATO_API.md`.
"""

from fastapi import FastAPI

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


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "ambiente": settings.environment}


# Os routers de feature entram aqui conforme as fases avançam:
#   Fase 1  auth, plants
#   Fase 2  generation
#   Fase 3  equipment
#   Fase 4  maintenance
#   Fase 5  documents
#   Fase 6  billing
#   Fase 7  assistant, notifications
