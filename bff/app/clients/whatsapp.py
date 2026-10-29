"""Cliente do gateway de WhatsApp.

O BFF não conhece o token da Meta, nem a Graph, nem o formato do webhook: ele fala com o
gateway pela porta interna, com uma chave em cabeçalho. É o que permite trocar o número, o
app ou o provedor sem tocar no painel nem no motor de notificações.

O gateway é um serviço nosso, e não um upstream de terceiro — por isso os erros dele viram
frases diretas para a tela do gestor, em vez de "erro 502". "Não configurado" (503) é o
estado mais comum enquanto ninguém preencheu a tela, e dizer isso é metade do trabalho.
"""

import asyncio
from typing import Any

import httpx

from app.core.config import get_settings

TIMEOUT_S = 25.0
CABECALHO_CHAVE = "X-Chave-Interna"


class GatewayIndisponivel(RuntimeError):
    """O gateway não está configurado aqui, ou não respondeu. A frase vai para a tela.

    `status` é o HTTP que o gateway respondeu, quando respondeu — é o que deixa a rota
    devolver um 404 como 404, sem casar frase.
    """

    def __init__(self, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


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


#: Esperas antes de tentar de novo quando a conexão NEM ABRIU (DNS, porta recusada). Em
#: 24/10/2026 o DNS do endereço do gateway falhou uma vez ("Name or service not known") e a
#: resposta do bot se perdeu. Como nada saiu, repetir não duplica mensagem.
ESPERAS_S = (1.0, 3.0)


async def _req(metodo: str, caminho: str, **kw: Any) -> Any:
    url = f"{_base()}{caminho}"
    cabecalhos = {CABECALHO_CHAVE: get_settings().whatsapp_chave_interna}
    for tentativa in range(len(ESPERAS_S) + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
                r = await cliente.request(metodo, url, headers=cabecalhos, **kw)
            break
        except httpx.ConnectError as exc:
            if tentativa == len(ESPERAS_S):
                raise GatewayIndisponivel(
                    f"Não foi possível falar com o gateway de WhatsApp: {exc}"
                ) from None
            await asyncio.sleep(ESPERAS_S[tentativa])
        except httpx.RequestError as exc:
            # Saiu e não voltou (tempo esgotado no meio): pode ter chegado — não repete.
            raise GatewayIndisponivel(
                f"Não foi possível falar com o gateway de WhatsApp: {exc}"
            ) from None

    if r.status_code == 401:
        raise GatewayIndisponivel(
            "O gateway recusou a chave interna. Confira WHATSAPP_CHAVE_INTERNA nos dois "
            "serviços: ela precisa ser a mesma."
        )
    if r.status_code >= 400:
        detalhe = ""
        try:
            corpo = r.json()
            detalhe = corpo.get("detail") if isinstance(corpo, dict) else ""
        except ValueError:
            detalhe = (r.text or "")[:200]
        raise GatewayIndisponivel(
            detalhe or f"O gateway respondeu {r.status_code}.", status=r.status_code
        )

    if not r.content:
        return None
    return r.json()


# ── credenciais (a tela de administração do WhatsApp) ───────────────────────


def url_do_webhook() -> str:
    """O endereço que vai no cadastro do webhook, no painel da Meta.

    Mora aqui porque é o cliente quem sabe onde o gateway está. A tela precisa dele para
    copiar: errar esse campo não dá erro nenhum, só silêncio — a Meta entrega em outro lugar
    e as mensagens dos clientes somem.

    É o endereço PÚBLICO (`WHATSAPP_GATEWAY_URL_PUBLICA`): a API fala com o gateway pela rede
    interna do Docker, que a Meta não alcança.
    """
    publica = get_settings().whatsapp_gateway_url_publica.rstrip("/")
    return f"{publica or _base()}/webhook"


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


# ── o WhatsApp Business de cada técnico ─────────────────────────────────────
#
# `gs_user_id` sai SEMPRE da sessão de quem chama a rota do BFF — o gateway confia nele
# porque só o BFF passa pela porta interna. Ver `api/v1/tecnico.py`.


async def configuracao_das_contas() -> dict[str, Any]:
    return await _req("GET", "/interno/contas/configuracao")


async def contas_de(gs_user_id: int) -> list[dict[str, Any]]:
    return await _req("GET", "/interno/contas", params={"gs_user_id": gs_user_id}) or []


async def conectar_conta(dados: dict[str, Any]) -> dict[str, Any]:
    return await _req("POST", "/interno/contas", json=dados)


async def desconectar_conta(phone_number_id: str, gs_user_id: int, ator: str | None) -> None:
    params: dict[str, Any] = {"gs_user_id": gs_user_id}
    if ator:
        params["ator"] = ator
    await _req("DELETE", f"/interno/contas/{phone_number_id}", params=params)


# ── o que a conta tem ───────────────────────────────────────────────────────


async def numeros() -> list[dict[str, Any]]:
    """Os números da conta na Meta. A tela lista para ninguém precisar decorar ids."""
    return await _req("GET", "/interno/numeros") or []


async def templates() -> list[dict[str, Any]]:
    """Os modelos de mensagem da conta, aprovados ou não."""
    return await _req("GET", "/interno/templates") or []


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


# ── assistente (resposta dentro da janela de 24 h) ───────────────────────────


async def enviar_conteudo(
    *, telefone: str, tipo: str, texto: str | None = None, arquivo: bytes | None = None,
    filename: str | None = None, mime: str | None = None, origem: str = "assistente",
    botoes: list[dict[str, str]] | None = None, guardar: str | None = None,
    formulario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`tipo`: text | document | image | botoes | formulario (`{token, titulo, opcoes, marcados, aviso}`). Arquivo vai em base64 para o gateway subir na
    Meta; `botoes` (até 3, `{id, titulo}`) vão com o `texto` numa mensagem interativa. `guardar`: o que
    o gateway guarda no lugar do `texto` (a resposta sem as senhas; a Meta recebe a inteira)."""
    import base64
    return await _req("POST", "/interno/conteudo", json={
        "telefone": telefone, "tipo": tipo, "texto": texto, "filename": filename, "mime": mime,
        "arquivo_b64": base64.b64encode(arquivo).decode() if arquivo else None, "origem": origem,
        **({"botoes": botoes} if botoes else {}), **({"guardar": guardar} if guardar else {}),
        **({"formulario": formulario} if formulario else {}),
    })


async def saude() -> dict[str, Any]:
    """Se o canal está OUVINDO: entregas paradas, mensagens sem aviso ao BFF, últimas datas."""
    return await _req("GET", "/interno/saude")


async def ocultar_texto(mensagem_id: int, texto: str | None = None) -> None:
    """Troca no gateway o texto de uma mensagem recebida pelo `texto` sem a senha de atuação
    (sem `texto`, apaga a mensagem inteira)."""
    await _req("POST", f"/interno/mensagens/{mensagem_id}/ocultar", json={"texto": texto})


async def mascarar(telefone: str, valores: list[str]) -> None:
    """Esconde os VALORES (as senhas que o bot só soube depois) nas mensagens das últimas 24 h do número."""
    await _req("POST", "/interno/mensagens/mascarar", json={"telefone": telefone, "valores": valores})


async def baixar_midia(mensagem_id: int) -> tuple[bytes, str | None]:
    """O arquivo de uma mensagem recebida (a nota de voz), que o gateway baixa da Meta na hora."""
    try:
        async with httpx.AsyncClient(timeout=60) as cliente:
            r = await cliente.get(f"{_base()}/interno/mensagens/{int(mensagem_id)}/midia",
                                  headers={CABECALHO_CHAVE: get_settings().whatsapp_chave_interna})
    except httpx.RequestError as exc:
        raise GatewayIndisponivel(f"Não foi possível falar com o gateway de WhatsApp: {exc}") from None
    if r.status_code >= 400:
        raise GatewayIndisponivel(f"O gateway não entregou o arquivo ({r.status_code}).", status=r.status_code)
    return r.content, r.headers.get("content-type")


async def digitando(wamid: str) -> None:
    await _req("POST", "/interno/digitando", json={"wamid": wamid})
