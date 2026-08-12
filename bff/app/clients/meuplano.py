"""Cliente do backend do meuPlano.

Mesma divisão do cliente do meuWatt: a credencial do usuário só autentica no login; todo o
resto usa a credencial de serviço.

Duas coisas do meuPlano que este cliente respeita e não tenta contornar:

- **A conformidade do cronograma não se conta por OS.** O upstream compara o que o ativo
  deve receber com o histórico do próprio ativo, e já devolve a cor de cada célula. Aqui a
  cor é repassada, nunca recalculada.
- **O assistente é assíncrono.** `POST /assistant/chat` cria um run e responde na hora; a
  resposta chega por polling em `GET /assistant/runs/{id}`. Não existe versão síncrona.
"""

from typing import Any

import httpx

from app.core.config import get_settings


class MeuPlanoError(RuntimeError):
    pass


class MeuPlanoClient:
    """A credencial de serviço vem do que o gestor gravou no painel, não do ambiente."""

    def __init__(
        self,
        base_url: str | None = None,
        usuario: str | None = None,
        senha: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.meuplano_api_url).rstrip("/")
        self._usuario = usuario
        self._senha = senha
        self._timeout = timeout
        self._service_token: str | None = None

    # ------------------------------------------------------------------ auth

    async def autenticar(self, email: str, senha: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/v1/meuacesso/auth/login",
                json={"email": email, "senha": senha},
            )
        if r.status_code in (401, 403):
            return None
        r.raise_for_status()
        return r.json()

    async def _token_servico(self) -> str:
        if self._service_token:
            return self._service_token
        if not self._usuario or not self._senha:
            raise MeuPlanoError(
                "A ponte com o meuPlano não tem credencial de serviço. "
                "Configure em Painel → Conexões."
            )
        dados = await self.autenticar(self._usuario, self._senha)
        if not dados:
            raise MeuPlanoError("credencial de serviço do meuPlano recusada")
        self._service_token = dados["access_token"]
        return self._service_token

    async def _req(
        self, metodo: str, path: str, token: str | None = None, **kwargs: Any
    ) -> httpx.Response:
        jwt = token or await self._token_servico()
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.request(
                metodo, f"{self.base_url}{path}", headers={"Authorization": f"Bearer {jwt}"}, **kwargs
            )
        if r.status_code == 401 and token is None:
            self._service_token = None
        r.raise_for_status()
        return r

    async def _get(self, path: str, token: str | None = None, **params: Any) -> Any:
        r = await self._req(
            "GET", path, token=token, params={k: v for k, v in params.items() if v is not None}
        )
        return r.json()

    # --------------------------------------------------------------- leitura

    async def sessao(self, token: str) -> dict[str, Any]:
        """Permissões e organizações do usuário — é daqui que sai o escopo de usinas dele
        e o `nivel_acesso` que decide o que o assistente pode revelar."""
        return await self._get("/api/v1/meuacesso/auth/me/session", token=token)

    async def usinas(self, token: str | None = None) -> list[dict[str, Any]]:
        """As usinas visíveis. Com `token` do usuário, devolve o escopo DELE — é assim que
        o teste da ponte descobre o que a conta de serviço enxerga.

        O meuPlano devolve ora uma lista, ora um envelope paginado; normalizado aqui para
        o resto do BFF não precisar saber disso.
        """
        dados = await self._get("/api/v1/meuacesso/usinas", token=token)
        if isinstance(dados, dict):
            return dados.get("items") or dados.get("results") or []
        return dados or []

    async def cronograma(self, usina_id: int, container_id: int | None = None) -> dict[str, Any]:
        return await self._get(
            f"/api/v1/maintenance/usinas/{usina_id}/cronograma", container_id=container_id
        )

    async def ordens_servico(
        self, usina_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._get(
            "/api/v1/meuacesso/service-orders", plant_id=usina_id, status=status
        )

    async def ordem_servico(self, so_id: int) -> dict[str, Any]:
        return await self._get(f"/api/v1/meuacesso/service-orders/{so_id}")

    async def notificacoes(self, token: str, grupo: str | None = None) -> list[dict[str, Any]]:
        return await self._get("/api/v1/meuacesso/me/notifications", token=token, group=grupo)

    async def nao_lidas(self, token: str) -> dict[str, Any]:
        return await self._get("/api/v1/meuacesso/me/notifications/unread-count", token=token)

    # ------------------------------------------------------------------- PDF

    async def gerar_pdf_os(self, so_id: int) -> int:
        """Gera (ou reaproveita) o PDF da OS e devolve o id na cesta.

        O upstream versiona por fingerprint: se nada mudou desde a última geração, ele
        devolve a versão existente em vez de gerar de novo.
        """
        r = await self._req("POST", f"/api/v1/meuacesso/service-orders/{so_id}/pdf")
        return r.json()["id"]

    async def baixar_pdf_cesta(self, item_id: int) -> bytes:
        r = await self._req("GET", f"/api/v1/meuacesso/pdf-basket/{item_id}/download")
        return r.content

    async def pdf_cronograma(self, usina_id: int) -> bytes:
        r = await self._req("GET", f"/api/v1/maintenance/usinas/{usina_id}/cronograma/pdf")
        return r.content

    # ------------------------------------------------------------- assistente

    async def assistente_chat(self, token: str, mensagem: str, usina_id: int | None) -> str:
        r = await self._req(
            "POST",
            "/api/v1/meuacesso/assistant/chat",
            token=token,
            json={"message": mensagem, "usina_id": usina_id},
        )
        return r.json()["run_id"]

    async def assistente_run(self, token: str, run_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/meuacesso/assistant/runs/{run_id}", token=token)
