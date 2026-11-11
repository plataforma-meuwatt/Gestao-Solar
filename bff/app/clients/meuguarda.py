"""A API do meuGuarda (CFTV das usinas, da família Gestão Solar) — especificação em `/root/DEVV/CFTV/docs/bot-gs.md`.

Sem chave e sem token de produto: o bot manda a SESSÃO do GS da própria pessoa (`Authorization` + `X-Portao`: empresa,
tecnico ou cliente). O meuGuarda a confere no `/eu` do portão daqui (cache de 2 min) e aplica as permissões e as usinas
que a pessoa tem LÁ; a recusa (403/404/422) volta com a frase dele em `detail`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

import httpx


class MeuGuarda:
    def __init__(self, base_url: str, sessao: str, portao: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._cabecalhos = {"Authorization": f"Bearer {sessao}", "X-Portao": portao}

    async def _req(self, metodo: str, caminho: str, corpo: dict | None = None, espera_s: float = 20) -> httpx.Response:
        async with httpx.AsyncClient(timeout=espera_s) as c:
            r = await c.request(metodo, f"{self.base_url}{caminho}", headers=self._cabecalhos, json=corpo)
        return r.raise_for_status()

    async def eu(self) -> dict[str, Any]:
        return (await self._req("GET", "/api/eu")).json()

    async def usinas(self) -> list[dict[str, Any]]:
        return (await self._req("GET", "/api/usinas")).json()

    async def cameras(self, usina_id: int) -> list[dict[str, Any]]:
        return (await self._req("GET", f"/api/usinas/{usina_id}/cameras")).json()

    async def alarmes(self) -> list[dict[str, Any]]:
        """Os ABERTOS, das usinas que a pessoa vê."""
        return (await self._req("GET", "/api/alarmes")).json()

    async def link(self, camera_id: int, canal: int = 1) -> dict[str, Any]:
        """`{url, expira_em, camera}`: abre a câmera ao vivo sem login, por 15 min (cada abertura vai ao log de lá)."""
        return (await self._req("POST", f"/api/cameras/{camera_id}/link", {"canal": canal})).json()

    async def foto(self, camera_id: int, canal: int = 1) -> tuple[bytes, str]:
        """A foto de agora (o PC da usina tira, ~6 s): `(jpeg, fonte)`. Lá espera 25 s antes do 504."""
        r = await self._req("POST", f"/api/cameras/{camera_id}/foto-agora", {"canal": canal}, espera_s=40)
        return r.content, unquote(r.headers.get("x-fonte", ""))

    async def deteccao(self, usina_id: int, ligada: bool, camera_ids: list[int], minutos: int | None,
                       motivo: str | None) -> dict[str, Any]:
        """Liga ou desliga o alarme das câmeras. `minutos: None` = até o horário de religar da usina."""
        return (await self._req("POST", f"/api/usinas/{usina_id}/deteccao", {
            "ligada": ligada, "camera_ids": camera_ids, "minutos": minutos, "motivo": motivo})).json()

    async def contar(self, filtro: dict[str, Any]) -> dict[str, Any]:
        """Quantos eventos o recorte pega: `{total, por_camera[{nome, n}], por_tipo[{tipo, n}]}`."""
        return (await self._req("POST", "/api/alarmes/contar", filtro)).json()

    async def classificar_lote(self, filtro: dict[str, Any], classificacao: str, motivo: str) -> dict[str, Any]:
        """Classifica o recorte de uma vez (os abertos fecham com o motivo): `{classificados, cameras}`."""
        return (await self._req("POST", "/api/alarmes/classificar-lote",
                                {**filtro, "classificacao": classificacao, "motivo": motivo}, espera_s=60)).json()


async def no_ar(base_url: str) -> bool:
    """A prova de vida, sem sessão (`/api/saude`): o alto da tela Rotas."""
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            return (await c.get(f"{base_url.rstrip('/')}/api/saude")).status_code == 200
    except httpx.HTTPError:
        return False
