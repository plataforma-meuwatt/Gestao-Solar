"""BFF do Gestão Solar.

Agrega a mw-api (meuWatt) e o backend do meuPlano num contrato só, aplica a autorização do
dono da usina e hospeda o financeiro de mensalidades — que não existe em nenhum dos dois.

Serve também o painel do gestor em `/painel`: cadastro de clientes, vínculo com os
produtos, conciliação de usinas e diagnóstico.

Contrato completo em `docs/CONTRATO_API.md`.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

_WEB = Path(__file__).parent / "web"
_PAINEL = _WEB / "painel"


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "ambiente": settings.environment}


# As seis faces da marca, servidas pelo próprio BFF: a fonte é parte da identidade e não
# pode depender de CDN de terceiro.
if (_WEB / "fontes").is_dir():
    app.mount("/painel/fontes", StaticFiles(directory=_WEB / "fontes"), name="fontes-painel")

if (_PAINEL / "assets").is_dir():
    app.mount("/painel/assets", StaticFiles(directory=_PAINEL / "assets"), name="painel-assets")


@app.get("/painel", include_in_schema=False)
@app.get("/painel/{caminho:path}", include_in_schema=False)
def pagina_painel(caminho: str = "") -> FileResponse:
    """O painel é uma aplicação de página única: toda rota devolve o mesmo HTML, e o
    roteamento acontece no navegador. Sem isso, recarregar em `/painel/clientes/3` daria
    404 — e o gestor não conseguiria favoritar nem voltar pelo botão do navegador.

    `caminho` existe para o FastAPI aceitar as sub-rotas; o conteúdo é sempre o mesmo.
    """
    _ = caminho
    indice = _PAINEL / "index.html"
    if not indice.is_file():
        raise HTTPException(
            503,
            "O painel ainda não foi construído. Rode `npm run build` em painel/.",
        )
    return FileResponse(indice, media_type="text/html")


# Os routers do app entram aqui conforme as fases avançam:
#   Fase 1  auth, plants
#   Fase 2  generation
#   Fase 3  equipment
#   Fase 4  maintenance
#   Fase 5  documents
#   Fase 6  billing
#   Fase 7  assistant, notifications
