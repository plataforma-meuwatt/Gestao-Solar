"""Cliente do gateway de WhatsApp.

O BFF não conhece o token da Meta, nem a Graph, nem o formato do webhook: ele fala com o
gateway pela porta interna, com uma chave em cabeçalho. É o que permite trocar o número, o
app ou o provedor sem tocar no painel nem no motor de notificações.

O gateway é um serviço nosso, e não um upstream de terceiro — por isso os erros dele viram
frases diretas para a tela do gestor, em vez de "erro 502". "Não configurado" (503) é o
estado mais comum enquanto ninguém preencheu a tela, e dizer isso é metade do trabalho.
"""

from typing import Any

import httpx

from app.core.config import get_settings

TIMEOUT_S = 25.0
CABECALHO_CHAVE = "X-Chave-Interna"


class GatewayIndisponivel(RuntimeError):
    """O gateway não está configurado aqui, ou não respondeu. A frase vai para a tela."""


def _base() -> str:
    s = get_settings()
    if not s.whatsapp_gateway_url:
        raise GatewayIndisponivel(
            "O gateway de WhatsApp não está configurado neste ambiente "
            "(WHATSAPP_GATEWAY_URL ausente)."
        )
    if not s.whatsapp_chave_interna:
        raise GatewayIndisponivel(
            "Falta a chave da porta interna do gateway (WHATSAPP_CHAVE_INTERNA)."
        )
    return s.whatsapp_gateway_url.rstrip("/")


async def _req(metodo: str, caminho: str, **kw: Any) -> Any:
    url = f"{_base()}{caminho}"
    cabecalhos = {CABECALHO_CHAVE: get_settings().whatsapp_chave_interna}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
            r = await cliente.request(metodo, url, headers=cabecalhos, **kw)
    except httpx.RequestError as exc:
        raise GatewayIndisponivel(
            f"Não foi possível falar com o gateway de WhatsApp: {exc}"
        ) from None

    if r.status_code == 401:
        raise GatewayIndisponivel(
            "O gateway recusou a chave interna. Confira WHATSAPP_CHAVE_INTERNA nos dois "
            "serviços — ela precisa ser a mesma."
        )
    if r.status_code >= 400:
        detalhe = ""
        try:
            corpo = r.json()
            detalhe = corpo.get("detail") if isinstance(corpo, dict) else ""
        except ValueError:
            detalhe = (r.text or "")[:200]
        raise GatewayIndisponivel(detalhe or f"O gateway respondeu {r.status_code}.")

    if not r.content:
        return None
    return r.json()


# ── credenciais (a tela de administração do WhatsApp) ───────────────────────


def url_do_webhook() -> str:
    """O endereço que vai no cadastro do webhook, no painel da Meta.

    Mora aqui porque é o cliente quem sabe onde o gateway está. A tela precisa dele para
    copiar: errar esse campo não dá erro nenhum, só silêncio — a Meta entrega em outro lugar
    e as mensagens dos clientes somem.
    """
    return f"{_base()}/webhook"


async def estado() -> dict[str, Any]:
    return await _req("GET", "/interno/credenciais")


async def salvar_credenciais(dados: dict[str, Any]) -> dict[str, Any]:
    return await _req("PUT", "/interno/credenciais", json=dados)


async def testar_credenciais(ator: str | None = None) -> dict[str, Any]:
    return await _req("POST", "/interno/credenciais/testar", params={"ator": ator} if ator else None)


async def remover_credenciais(ator: str | None = None) -> None:
    await _req("DELETE", "/interno/credenciais", params={"ator": ator} if ator else None)


async def eventos(limite: int = 30) -> list[dict[str, Any]]:
    return await _req("GET", "/interno/credenciais/eventos", params={"limite": limite}) or []


# ── envio (o motor de notificações, quando existir) ─────────────────────────


async def enviar_template(
    *, telefone: str, template: str, parametros: list[str], origem: str | None = None
) -> dict[str, Any]:
    return await _req(
        "POST",
        "/interno/templates",
        json={
            "telefone": telefone,
            "template": template,
            "parametros": parametros,
            "origem": origem,
        },
    )
