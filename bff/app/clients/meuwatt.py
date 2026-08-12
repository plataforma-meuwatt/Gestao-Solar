"""Cliente da mw-api (meuWatt).

Duas formas de falar com ela, e a diferença importa:

- `autenticar()` usa a credencial do PRÓPRIO usuário, uma única vez, no login. Serve para
  provar quem ele é e para descobrir a que usinas ele tem direito enquanto ainda temos o
  token dele em mãos.
- Todo o resto usa a CREDENCIAL DE SERVIÇO. O JWT do usuário expira em 24 h e guardar a
  senha dele para renovar seria inaceitável — então o BFF entra com conta própria e filtra
  pelo escopo que capturou no login.

A mw-api não tem versionamento de path: os routers são montados na raiz (`/plants`,
`/auth`, `/reports`). Uma mudança de shape lá quebra aqui em silêncio — por isso os
métodos devolvem `dict` cru e a tradução para o formato do app fica nos serviços, num
lugar só.
"""

from datetime import date
from typing import Any

import httpx

from app.core.config import get_settings


class MeuWattError(RuntimeError):
    pass


class MeuWattClient:
    """A credencial de serviço vem de fora (do que o gestor gravou no painel), não do
    ambiente — é o que permite configurar e testar a ponte sem redeploy."""

    def __init__(
        self,
        base_url: str | None = None,
        usuario: str | None = None,
        senha: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.meuwatt_api_url).rstrip("/")
        self._usuario = usuario
        self._senha = senha
        self._timeout = timeout
        self._service_token: str | None = None

    # ------------------------------------------------------------------ auth

    async def autenticar(self, email: str, senha: str) -> dict[str, Any] | None:
        """Valida a credencial do usuário. Devolve o payload do login ou None se recusada.

        Só 401 vira None (credencial errada). Qualquer outro erro sobe — um 500 do
        upstream não pode ser confundido com "senha inválida", senão o usuário vê
        "credencial incorreta" quando o problema é o servidor.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(f"{self.base_url}/auth/login", json={"email": email, "password": senha})
        if r.status_code == 401:
            return None
        r.raise_for_status()
        return r.json()

    async def _token_servico(self) -> str:
        if self._service_token:
            return self._service_token
        if not self._usuario or not self._senha:
            raise MeuWattError(
                "A ponte com o meuWatt não tem credencial de serviço. "
                "Configure em Painel → Conexões."
            )
        dados = await self.autenticar(self._usuario, self._senha)
        if not dados:
            raise MeuWattError("credencial de serviço do meuWatt recusada")
        self._service_token = dados["access_token"]
        return self._service_token

    async def _get(self, path: str, token: str | None = None, **params: Any) -> Any:
        jwt = token or await self._token_servico()
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {jwt}"},
                params={k: v for k, v in params.items() if v is not None},
            )
        # 401 com token de serviço = token expirou; limpa e deixa a próxima chamada renovar.
        if r.status_code == 401 and token is None:
            self._service_token = None
        r.raise_for_status()
        return r.json()

    # --------------------------------------------------------------- leitura

    async def usinas(self, token: str | None = None) -> list[dict[str, Any]]:
        """Com `token` do usuário, devolve o escopo DELE — é assim que o login descobre a
        que usinas ele tem direito."""
        return await self._get("/plants", token=token)

    async def usina(self, slug: str) -> dict[str, Any]:
        return await self._get(f"/plants/{slug}")

    async def monitoramento_atual(self, slug: str) -> dict[str, Any]:
        return await self._get(f"/plants/{slug}/monitoring/current")

    async def geracao_diaria(self, slug: str, dia: date) -> dict[str, Any]:
        return await self._get(f"/plants/{slug}/generation/daily", date=dia.isoformat())

    async def geracao_periodo(self, slug: str, inicio: date, fim: date) -> dict[str, Any]:
        """O upstream limita o intervalo a 366 dias — a tela Anual encosta nesse teto."""
        return await self._get(
            f"/plants/{slug}/generation/range", start=inicio.isoformat(), end=fim.isoformat()
        )

    async def alertas(self, slug: str, status: str = "active") -> list[dict[str, Any]]:
        return await self._get(f"/plants/{slug}/alerts", status=status)

    async def paradas(self, slug: str, inicio: date, fim: date) -> list[dict[str, Any]]:
        return await self._get(
            f"/plants/{slug}/breakdowns/range", start=inicio.isoformat(), end=fim.isoformat()
        )

    async def slots(self, slug: str) -> list[dict[str, Any]]:
        """Inversor é endereçado por SLOT (posição física permanente), não por serial — o
        serial muda quando o equipamento é trocado, o slot não."""
        return await self._get(f"/plants/{slug}/slots")

    async def slot(self, slug: str, slot_id: int) -> dict[str, Any]:
        return await self._get(f"/plants/{slug}/slots/{slot_id}")

    async def faturas_concessionaria(self, slug: str) -> list[dict[str, Any]]:
        """UC no meuWatt é o TRANSFORMADOR — cada fatura pertence a um transformer.id."""
        return await self._get(f"/plants/{slug}/utility-bills")

    async def portal_relatorios(self, token: str) -> dict[str, Any]:
        """Portal do Cliente: relatórios publicados. Exige o token do usuário (é gated a
        `plant_owner`), não a credencial de serviço."""
        return await self._get("/reports/portal", token=token)

    async def arquivo_relatorio(self, report_id: int, kind: str) -> bytes:
        jwt = await self._token_servico()
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(
                f"{self.base_url}/reports/{report_id}/files/{kind}",
                headers={"Authorization": f"Bearer {jwt}"},
            )
        r.raise_for_status()
        return r.content
