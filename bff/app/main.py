"""BFF do Gestão Solar — a API, e só a API.

Agrega a mw-api (meuWatt) e o backend do meuPlano num contrato só, aplica a autorização do
dono da usina e hospeda o financeiro de mensalidades — que não existe em nenhum dos dois.

**Este serviço não serve tela.** O painel do gestor é uma aplicação própria, num serviço
próprio (`painel/`), e o aplicativo é nativo. Cada um no seu quadrado: a API escala pelo
volume de requisição, o painel é arquivo estático servido por um servidor estático, e um
deploy de tela não reinicia o processo que atende o aplicativo de ninguém.

O preço disso é que toda chamada do painel é origem cruzada — daí o CORS abaixo, com lista
explícita de origens (`GS_CORS_ORIGENS`).

Contrato completo em `docs/CONTRATO_API.md`.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    auth,
    billing,
    documents,
    equipamentos,
    avisos,
    home,
    manutencao,
    permissoes,
    notifications,
    painel,
    painel_clientes,
    paradas,
    pendencias,
    plants,
    relatorio,
    resumo,
)
from app.core.config import get_settings

settings = get_settings()
settings.validar_producao()

app = FastAPI(
    title="Gestão Solar API",
    version="0.1.0",
    # Em produção o Swagger fica fora — mesma postura da mw-api.
    docs_url=None if settings.producao else "/docs",
    redoc_url=None,
    openapi_url=None if settings.producao else "/openapi.json",
)

# Em produção vale exatamente o que `GS_CORS_ORIGENS` disser — e `validar_producao` recusa
# subir com a lista vazia. Em desenvolvimento, além dela, qualquer porta local: o painel
# roda em 5180, o Expo web sorteia a sua, e o celular com Expo Go entra pelo IP da rede.
_origens = settings.cors_origens
_regex_local = None if settings.producao else r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origens,
    allow_origin_regex=_regex_local,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(painel.router)
app.include_router(painel_clientes.router)
app.include_router(plants.router)
app.include_router(paradas.router)
app.include_router(billing.router)
app.include_router(home.router)
app.include_router(equipamentos.router)
app.include_router(notifications.router)
app.include_router(manutencao.router)
app.include_router(pendencias.router)
app.include_router(permissoes.router)
app.include_router(avisos.router)
app.include_router(documents.router)
app.include_router(resumo.router)
app.include_router(relatorio.router)


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    """Sonda de saúde do serviço. Responde sem tocar no banco nem nos upstreams — é sobre
    o processo estar de pé, não sobre o sistema estar inteiro. Para essa outra pergunta
    existem as telas de Conexões e Rotas."""
    return {"status": "ok", "ambiente": settings.environment}


# Os routers do app entram aqui conforme as fases avançam:
#   Fase 1  auth ✔, plants
#   Fase 2  generation
#   Fase 3  equipment
#   Fase 4  maintenance
#   Fase 5  documents
#   Fase 6  billing
#   Fase 7  assistant, notifications
