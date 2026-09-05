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

import logging
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import (
    auth,
    billing,
    carteira,
    documents,
    energia,
    equipamentos,
    avisos,
    home,
    manutencao,
    permissoes,
    notifications,
    pacotes,
    painel,
    painel_clientes,
    paradas,
    pendencias,
    plants,
    relatorio,
    resumo,
)
from app.clients import http as http_upstream
from app.core.config import get_settings

settings = get_settings()
settings.validar_producao()

@asynccontextmanager
async def _ciclo_de_vida(_app: FastAPI):
    """As sessões com os upstreams vivem enquanto o processo vive (keep-alive, ver
    `clients/http.py`); no desligamento elas são devolvidas, para não ficar conexão
    pendurada."""
    yield
    await http_upstream.fechar_sessoes()


app = FastAPI(
    title="Gestão Solar API",
    version="0.1.0",
    lifespan=_ciclo_de_vida,
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

_log = logging.getLogger("gs.erro")


async def _erro_com_cors(request: Request, chamar_proximo):
    """Todo erro não previsto vira 500 com corpo — e com os cabeçalhos de CORS.

    Sem isto, uma exceção não tratada sobe até o `ServerErrorMiddleware`, que fica ACIMA
    do CORS: a resposta sai sem `Access-Control-Allow-Origin`, o navegador a classifica
    como falha de rede e o portal exibe "Sem conexão com o servidor." — mandando o
    cliente corporativo culpar a própria internet por um defeito nosso. Foi exatamente o
    que aconteceu com o 500 do "Ficha em PDF" (nome de tarefa com travessão no
    `Content-Disposition`): o defeito era do servidor e a tela acusava a rede.

    Este middleware é registrado ANTES do CORS de propósito — no Starlette o último
    `add_middleware` é o mais externo, então o CORS envolve este e carimba a resposta.
    """
    try:
        return await chamar_proximo(request)
    except Exception:  # noqa: BLE001
        referencia = uuid.uuid4().hex[:8]
        _log.error(
            "erro nao tratado ref=%s %s %s\n%s",
            referencia,
            request.method,
            request.url.path,
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "O servidor não conseguiu concluir esta operação. "
                    f"Tente de novo; se continuar, informe o código {referencia}."
                )
            },
        )


app.add_middleware(BaseHTTPMiddleware, dispatch=_erro_com_cors)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origens,
    allow_origin_regex=_regex_local,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Em origem cruzada o navegador ESCONDE do JavaScript todo cabeçalho que não esteja
    # aqui — o corpo chega, os cabeçalhos não. O portal baixaria a parte 1 de 2 do pacote
    # de fichas sem ter como descobrir que existe uma parte 2, e sem o nome do arquivo. A
    # lista mora junto de quem escreve esses cabeçalhos (`api/v1/pacotes.py`); uma segunda
    # cópia aqui divergiria no dia em que um deles fosse acrescentado.
    expose_headers=pacotes.CABECALHOS_EXPOSTOS,
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
app.include_router(pacotes.router)
app.include_router(pendencias.router)
app.include_router(permissoes.router)
app.include_router(avisos.router)
app.include_router(documents.router)
app.include_router(energia.router)
app.include_router(resumo.router)
app.include_router(relatorio.router)
app.include_router(carteira.router)


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
