"""A porta do bot do mw-modbus-helper — contrato em `docs/bot.md` do helper (2.25.0).

O helper não conversa: recebe pedidos de um CHAMADOR (o Gestão Solar) e faz o que a web
faz, como a pessoa logada — a identidade é o token do meuWatt DELA. Leitura volta na hora;
escrita volta como PROPOSTA (nada é executado) e só roda em `confirmar`, pela mesma pessoa e
o mesmo chamador, uma vez. Quem pede a confirmação à pessoa é o chamador (`assistente`).

O endereço chega ao Gestão Solar por um túnel SSH reverso que sai do srvclaude até a
KingHost (`http://10.0.1.1:18080`, só dentro da rede `coolify`), com um filtro que só deixa
passar `POST /api/bot/ferramentas|chamar|confirmar`.
"""

from __future__ import annotations

from typing import Any

import httpx


class HelperBot:
    def __init__(self, base_url: str, chamador: str, chave: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._cabecalhos = {
            "X-MW-Bot-Chamador": chamador,
            "X-MW-Bot-Chave": chave,
            "Authorization": f"Bearer {token}",
        }

    async def _post(self, caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
        """Devolve o JSON do helper, inclusive nos erros (`{"ok": false, "reason", "error"}`):
        a frase do helper é a que diz o que fazer (`sem_login`, `ocupada_por_outro`…)."""
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.base_url}/api/bot/{caminho}", headers=self._cabecalhos, json=corpo)
        try:
            dados = r.json()
        except ValueError:
            return {"ok": False, "reason": "resposta_invalida", "error": f"HTTP {r.status_code}"}
        return dados if isinstance(dados, dict) else {"ok": False, "reason": "resposta_invalida"}

    async def ferramentas(self) -> dict[str, Any]:
        return await self._post("ferramentas", {})

    async def chamar(self, rota: str, corpo: dict[str, Any], origem: str, metodo: str = "POST") -> dict[str, Any]:
        return await self._post("chamar", {"rota": rota, "metodo": metodo, "corpo": corpo, "origem": origem})

    async def confirmar(self, proposta: str, confirmado_por: str, origem: str) -> dict[str, Any]:
        return await self._post(
            "confirmar", {"proposta": proposta, "confirmado_por": confirmado_por, "origem": origem}
        )
