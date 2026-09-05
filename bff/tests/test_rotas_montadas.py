"""Todo router escrito está MONTADO — o defeito que passou por 847 testes verdes.

O caso real, em 05/09/2026: `app/api/v1/relatorios_ano.py` definia
`GET /api/v1/relatorios/ano`, tinha 30 testes próprios passando e **não estava no
`main.py`**. A tela do ano, que é o coração da entrega, respondia `404 Not Found` para
todo mundo. Nenhum gate deste repositório enxergava isso:

- a suíte não via, porque cada arquivo de teste montava o seu próprio `FastAPI()`;
- a sonda não vê, porque ela vigia os UPSTREAMS (meuWatt, meuPlano), nunca as rotas do
  próprio BFF;
- o `tsc` do aplicativo não vê, porque para ele é uma string.

Este arquivo fecha o buraco pelo lado que importa: ele não confere uma lista escrita à
mão (que envelheceria calada), e sim **descobre** os módulos de `app/api/v1` que expõem
um `router` e exige que cada um tenha ao menos um caminho vivo na aplicação real.
Acrescentar um router novo e esquecer de montá-lo reprova aqui, dizendo o nome do arquivo.
"""

import importlib
import pkgutil

from fastapi import APIRouter

import app.api.v1 as pacote_v1
from app.main import app


def _modulos_com_router() -> dict[str, APIRouter]:
    """Os módulos de `app/api/v1` que expõem um `router`, descobertos — nunca listados."""
    achados: dict[str, APIRouter] = {}
    for info in pkgutil.iter_modules(pacote_v1.__path__):
        modulo = importlib.import_module(f"{pacote_v1.__name__}.{info.name}")
        router = getattr(modulo, "router", None)
        if isinstance(router, APIRouter):
            achados[info.name] = router
    return achados


def test_todo_router_de_api_v1_esta_montado():
    """O DEFEITO: router escrito, testado e nunca alcançável. Reprova com o nome do arquivo."""
    montados = {rota.path for rota in app.routes}
    orfaos = sorted(
        nome
        for nome, router in _modulos_com_router().items()
        # Um router sem rota nenhuma não é órfão, é vazio — não é este o assunto.
        if router.routes and not any(r.path in montados for r in router.routes)
    )
    assert not orfaos, (
        f"router(es) escrito(s) e NÃO montado(s) em app/main.py: {orfaos}. "
        "Quem chamar a rota recebe 404, e nenhum outro teste desta suíte percebe."
    )


def test_a_descoberta_realmente_acha_os_routers():
    """Guarda o guarda: se `_modulos_com_router` parasse de achar (renomearam a pasta,
    o `iter_modules` mudou), o teste acima passaria a ser um `assert not []` — verde,
    inútil e mudo. O BFF tem dezenas de módulos de rota; menos de dez é sinal de que a
    varredura quebrou, não de que o projeto encolheu."""
    achados = _modulos_com_router()
    assert len(achados) >= 10, f"a varredura achou só {len(achados)} módulos com router"
    assert "relatorios_ano" in achados
