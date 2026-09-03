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
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.meuplano_api_url).rstrip("/")
        self._usuario = usuario
        self._senha = senha
        # Token pessoal (`mp_pat_…`) gerado no meuPlano e colado no painel — ver o gêmeo
        # em clients/meuwatt.py.
        self._token_fixo = token
        self._timeout = timeout
        self._service_token: str | None = None

    # ------------------------------------------------------------------ auth

    async def quem_sou_eu(self, token: str | None = None) -> dict[str, Any]:
        """De quem é a credencial em uso — o que permite à tela dizer "token de Fulano".

        `/auth/me/profile` e não `/auth/me`: o segundo devolve papel, permissões e id,
        mas **não o nome** da pessoa. Um e-mail de serviço não diz a ninguém de quem é a
        conta; o nome, sim — e a tela de Conexões existe justamente para que o gestor
        repare que colou o token da pessoa errada.
        """
        return await self._get("/api/v1/meuacesso/auth/me/profile", token=token)

    async def autenticar(self, email: str, senha: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as c:
            r = await c.post(
                f"{self.base_url}/api/v1/meuacesso/auth/login",
                json={"email": email, "senha": senha},
            )
        if r.status_code in (401, 403):
            return None
        r.raise_for_status()
        return r.json()

    async def _token_servico(self) -> str:
        if self._token_fixo:
            return self._token_fixo
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
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as c:
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

    async def procurar_usuario_por_email(self, email: str) -> dict[str, Any] | None:
        """Busca exata. Este sistema tem o endpoint de lookup; o meuWatt não."""
        try:
            return await self._get("/api/v1/meuacesso/admin/users/lookup", email=email)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def usinas_do_usuario(self, user_id: str | int) -> list[int]:
        """Os ids das usinas que aquele usuário enxerga.

        Lista vazia aqui significa "sem restrição explícita" — o usuário cai na regra da
        organização dele. O painel trata isso como "nenhuma sugestão", não como "nenhuma
        usina": quem decide é o gestor.
        """
        dados = await self._get(f"/api/v1/meuacesso/admin/users/{user_id}/usinas")
        return [int(i) for i in (dados or [])]

    async def contratos(self, usina_id: int | None = None) -> list[dict[str, Any]]:
        """Os contratos de O&M de uma usina — os containers do **pipeline**.

        A fonte é `/pipelines/global/contrato/containers`, e não a lista do financeiro:
        são duas tabelas diferentes (`PipelineContainer` e `FinContainer`) com numerações
        próprias. O cronograma valida o `container_id` contra a primeira, então um id
        colhido da segunda responde "Contrato (container) não encontrado" — um 404 que
        parece problema de permissão e é só a tabela errada.
        """
        dados = await self._get(
            "/api/v1/meuacesso/pipelines/global/contrato/containers", usina_id=usina_id
        )
        return dados if isinstance(dados, list) else (dados.get("items") or [])

    async def cronograma(self, usina_id: int, container_id: int | None = None) -> dict[str, Any]:
        """O cronograma de manutenção da usina, dentro de um contrato.

        `container_id` é **obrigatório** no upstream — sem ele a resposta é 422. Este
        cliente o tratava como opcional, e o resultado era a tela de manutenção falhando
        com um erro de validação em vez de mostrar o cronograma.

        Quando não vem informado, é descoberto: uma usina normalmente tem um contrato só,
        e é esse o cronograma que o dono dela quer ver. Com mais de um, vale o primeiro —
        escolher qual contrato mostrar é decisão de produto que ainda não foi tomada, e
        chutar em silêncio seria pior do que a tela pedir para escolher no dia em que isso
        aparecer.
        """
        if container_id is None:
            contratos = await self.contratos(usina_id)
            if not contratos:
                raise MeuPlanoError(
                    f"A usina {usina_id} não tem contrato de manutenção no meuPlano, "
                    "e o cronograma é sempre dentro de um contrato."
                )
            container_id = contratos[0]["id"]

        return await self._get(
            f"/api/v1/maintenance/usinas/{usina_id}/cronograma", container_id=container_id
        )

    async def ordens_servico(
        self, usina_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        dados = await self._get(
            "/api/v1/meuacesso/service-orders", plant_id=usina_id, status=status
        )
        # Ora lista, ora envelope paginado — normalizado aqui, como nas usinas.
        if isinstance(dados, dict):
            return dados.get("items") or dados.get("results") or []
        return dados or []

    async def ordem_servico(self, so_id: int) -> dict[str, Any]:
        return await self._get(f"/api/v1/meuacesso/service-orders/{so_id}")

    async def tarefas_da_ordem(self, so_id: int) -> list[dict[str, Any]]:
        """As tarefas de uma OS — o que de fato foi (ou será) executado nela.

        A OS por si só devolve `task_count`/`task_realized_count`: dois números, sem o
        que são. Quem é dono da usina quer a lista — "Termografia no Skid 02",
        "Reaperto de conexões" — e o estado de cada uma; é por isso que a tela de
        detalhe precisa desta chamada além da OS.

        `/tasks` aceita `os_id` e é a MESMA rota que a Programação do meuPlano usa, com
        o mesmo `_enrich`: vem `plan_type_label` (a seção), `equipment_path` (qual dos
        cinco trafos) e `verdict_status` (o parecer do ensaio). Reaproveitar a rota
        oficial em vez de somar campos da OS é o que mantém as duas leituras iguais.
        """
        dados = await self._get("/api/v1/meuacesso/tasks", os_id=so_id)
        if isinstance(dados, dict):
            return dados.get("items") or dados.get("results") or []
        return dados or []

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
