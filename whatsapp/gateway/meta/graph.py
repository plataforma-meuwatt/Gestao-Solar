"""Falar com a Graph API — o único lugar do sistema que toca o token da Meta.

As credenciais chegam como PARÂMETRO, não de `settings`: elas vivem cifradas no banco e são
cadastradas pela tela (`services/credenciais.py`). Ler configuração aqui dentro faria este
módulo depender do banco e, pior, esconderia de quem chama que existe um estado que pode
não estar configurado.

**Só template, por enquanto.** Mensagem iniciada pela empresa exige modelo aprovado; texto
livre só vale dentro da janela de 24 h depois de o cliente escrever, que é a frente
seguinte. Deixar a função pronta convidaria a usá-la fora da janela, e a recusa só
apareceria na hora do envio real.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from gateway.core.config import get_settings
from gateway.core.telefone import para_envio

TIMEOUT_S = 20.0


@dataclass
class Resposta:
    ok: bool
    wamid: str | None = None
    erro_codigo: str | None = None
    erro_detalhe: str | None = None


def _corpo_do_template(
    telefone: str, template: str, idioma: str, parametros: list[str]
) -> dict[str, Any]:
    componentes = []
    if parametros:
        componentes.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in parametros],
            }
        )
    return {
        "messaging_product": "whatsapp",
        "to": para_envio(telefone),
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": idioma},
            **({"components": componentes} if componentes else {}),
        },
    }


def _ler_erro(dados: Any) -> tuple[str | None, str | None]:
    if not isinstance(dados, dict):
        return None, None
    erro = dados.get("error")
    if not isinstance(erro, dict):
        return None, None
    codigo = erro.get("code")
    detalhe = erro.get("error_user_msg") or erro.get("message")
    return (str(codigo) if codigo is not None else None), detalhe


async def enviar_template(
    *,
    token: str,
    phone_number_id: str,
    telefone: str,
    template: str,
    parametros: list[str],
    idioma: str = "pt_BR",
) -> Resposta:
    """Manda um template aprovado. Nunca levanta por recusa da Meta — devolve o motivo.

    Recusa é resultado, não erro de programa: o número pode ter bloqueado a empresa, o
    template pode ter sido pausado por qualidade. Quem chamou grava isso na linha da
    mensagem; um 500 aqui viraria "erro interno" numa tela que precisava dizer "o cliente
    bloqueou o seu número".
    """
    s = get_settings()
    url = f"{s.graph_url}/{phone_number_id}/messages"
    corpo = _corpo_do_template(telefone, template, idioma, parametros)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
            r = await cliente.post(url, json=corpo, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        # Rede fora não é recusa: quem chamou grava `falhou` com o motivo e pode reenviar.
        return Resposta(ok=False, erro_codigo="rede", erro_detalhe=str(e))

    try:
        dados = r.json()
    except ValueError:
        dados = {}

    if r.status_code >= 400:
        codigo, detalhe = _ler_erro(dados)
        return Resposta(
            ok=False,
            erro_codigo=codigo or str(r.status_code),
            erro_detalhe=detalhe or (r.text or "")[:300],
        )

    mensagens = dados.get("messages") if isinstance(dados, dict) else None
    wamid = None
    if isinstance(mensagens, list) and mensagens and isinstance(mensagens[0], dict):
        wamid = mensagens[0].get("id")

    if not wamid:
        # 200 sem id é resposta que não dá para rastrear: melhor tratar como falha do que
        # gravar uma mensagem que nenhum aviso de status vai alcançar.
        return Resposta(ok=False, erro_codigo="sem_wamid", erro_detalhe=str(dados)[:300])

    return Resposta(ok=True, wamid=str(wamid))
