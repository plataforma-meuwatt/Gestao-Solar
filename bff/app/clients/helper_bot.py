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
        self._cabecalhos = {"X-MW-Bot-Chamador": chamador, "X-MW-Bot-Chave": chave}
        if token:
            # Sem token (a prova de vida do `ferramentas`), o cabeçalho não vai: "Bearer " vazio é
            # cabeçalho inválido, e o httpx recusava a requisição inteira (500 na tela, 24/10/2026).
            self._cabecalhos["Authorization"] = f"Bearer {token}"

    async def _post(self, caminho: str, corpo: dict[str, Any], espera_s: float = 120) -> dict[str, Any]:
        """Devolve o JSON do helper, inclusive nos erros (`{"ok": false, "reason", "error"}`):
        a frase do helper é a que diz o que fazer (`sem_login`, `ocupada_por_outro`…).

        Sem conexão = nada chegou lá. Tempo esgotado depois de enviar = PODE ter chegado
        (`incerto`): numa confirmação, dizer "falhou" convidaria a mandar de novo."""
        try:
            async with httpx.AsyncClient(timeout=espera_s) as c:
                r = await c.post(f"{self.base_url}/api/bot/{caminho}", headers=self._cabecalhos, json=corpo)
        except httpx.ConnectError:
            return {"ok": False, "reason": "helper_fora", "error": "O helper não respondeu (túnel ou serviço fora do ar)."}
        except httpx.TimeoutException:
            return {"ok": False, "incerto": True, "reason": "sem_resposta",
                    "error": f"O helper não respondeu em {int(espera_s)} s."}
        except httpx.HTTPError as exc:                   # protocolo, rede no meio: nunca um 500 na tela
            return {"ok": False, "incerto": True, "reason": "erro_de_rede", "error": f"Falha ao falar com o helper: {exc}"}
        try:
            dados = r.json()
        except ValueError:
            return {"ok": False, "reason": "resposta_invalida", "error": f"HTTP {r.status_code}"}
        return dados if isinstance(dados, dict) else {"ok": False, "reason": "resposta_invalida"}

    async def ferramentas(self, espera_s: float = 120) -> dict[str, Any]:
        """O catálogo — e a prova de vida: só pede a chave do chamador, não o token de ninguém."""
        return await self._post("ferramentas", {}, espera_s=espera_s)

    async def chamar(self, rota: str, corpo: dict[str, Any], origem: str, metodo: str = "POST") -> dict[str, Any]:
        return await self._post("chamar", {"rota": rota, "metodo": metodo, "corpo": corpo, "origem": origem})

    async def confirmar(self, proposta: str, confirmado_por: str, origem: str) -> dict[str, Any]:
        """O ajuste em massa (2.26.0) espera o lote inteiro até ~150 s, e o filtro do túnel corta
        em 200 s: espera 190 s."""
        return await self._post(
            "confirmar", {"proposta": proposta, "confirmado_por": confirmado_por, "origem": origem},
            espera_s=190,
        )
