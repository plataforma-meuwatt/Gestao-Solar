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


def _params_do_periodo(de: str, ate: str, container_id: int | None) -> dict[str, Any]:
    """Query do relatório de manutenção. `container_id` ausente NÃO vai como "None" na URL:
    o meuPlano o lê como texto e responderia 422 em vez de escolher o contrato sozinho."""
    return {k: v for k, v in {"de": de, "ate": ate, "container_id": container_id}.items()
            if v is not None}


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
        self, metodo: str, path: str, token: str | None = None,
        timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        """`timeout` sobrescreve o padrão do cliente para as chamadas que legitimamente
        demoram — gerar o PDF de uma ficha grande no meuPlano leva alguns segundos na
        primeira vez, e cortar isso no timeout padrão daria erro num caminho que funciona."""
        jwt = token or await self._token_servico()
        async with httpx.AsyncClient(timeout=timeout or self._timeout, follow_redirects=True) as c:
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

    # ------------------------------------------ visão do cliente: cronograma
    #
    # Por que não as rotas internas: `GET /maintenance/usinas/{id}/cronograma` CRIA o
    # rascunho v1 quando ele não existe e devolve DRAFT como se fosse o combinado, e
    # `/cronograma/pdf` renderiza a última versão, rascunho inclusive. Foi assim que o
    # dono de usina podia ver X de negociação como contrato. O router `visao-cliente`
    # só serve a versão CONSOLIDADA.

    async def vc_contratos(self, usina_id: int) -> list[dict[str, Any]]:
        """Os contratos de O&M da usina, cada um dizendo se tem cronograma consolidado
        (`versao_consolidada`, nulo enquanto só há rascunho).

        Substitui o `contratos()[0]` cego que o cronograma usava: o portal mostra a lista
        para o cliente escolher, e o BFF escolhe por padrão o que tem a versão consolidada
        mais recente — nunca o primeiro que apareceu. `contratos()` (rota interna do
        funil) continua existindo para o painel; o portal não a chama.
        """
        dados = await self._get(
            f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/contratos"
        )
        if isinstance(dados, dict):
            return dados.get("items") or dados.get("results") or []
        return dados or []

    async def vc_cronograma(self, usina_id: int, container_id: int) -> dict[str, Any]:
        """O cronograma CONSOLIDADO do contrato — a mesma matriz do `_cronograma_out`
        interno, com `cell_status` vindo do ATIVO.

        `container_id` é obrigatório aqui como no upstream: cronograma existe sempre
        dentro de um contrato. Quem não sabe qual, pergunta em `vc_contratos` primeiro.
        Contrato só com rascunho responde **404** — e o chamador decide o que dizer ao
        cliente; este cliente não inventa matriz vazia no lugar.
        """
        return await self._get(
            f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/cronograma",
            container_id=container_id,
        )

    async def vc_cronograma_pdf(self, usina_id: int, container_id: int) -> bytes:
        """O PDF do cronograma consolidado. Renderiza a cada chamada — timeout folgado."""
        r = await self._req(
            "GET",
            f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/cronograma/pdf/view",
            params={"container_id": container_id},
            timeout=120.0,
        )
        return r.content

    async def cronograma(self, usina_id: int, container_id: int) -> dict[str, Any]:
        """Mantido pelo nome; hoje é `vc_cronograma`.

        O ramo que descobria o contrato sozinho (`contratos()[0]`) saiu: escolher qual
        contrato mostrar é decisão de quem chama, com a lista de `vc_contratos` na mão.
        """
        return await self.vc_cronograma(usina_id, container_id)

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

    async def tarefa(self, task_id: int) -> dict[str, Any]:
        """Uma tarefa, com o mesmo enriquecimento da lista (`plan_type_label`,
        `equipment_path`, `verdict_status`)."""
        return await self._get(f"/api/v1/meuacesso/tasks/{task_id}")

    async def foto_da_tarefa(self, task_id: int, foto_id: int,
                             variante: str = "original") -> tuple[bytes, str]:
        """Os bytes de UMA foto da ficha, com o tipo que o meuPlano declarou.

        Timeout curto de propósito: é uma imagem já pronta no armazenamento, não um documento
        que nasce na hora. Se demorar mais que isso, é falha — e a tela deve dizer, não ficar
        esperando com o usuário olhando um quadrado cinza.
        """
        r = await self._req("GET", f"/api/v1/meuacesso/tasks/{task_id}/fotos/{foto_id}",
                            params={"variante": variante}, timeout=30.0)
        return r.content, r.headers.get("content-type", "image/jpeg")

    async def tarefas_do_item_no_mes(self, plan_item_id: int, mes: str) -> list[dict[str, Any]]:
        """As tarefas de UMA atividade do plano NAQUELE mês — o que está atrás do X.

        A mesma rota `/tasks` da lista da OS, com os filtros que o próprio Cronograma do
        meuPlano usa (`usina_type_plan_item_id` + `contract_month`). Reaproveitar a rota
        oficial é o que mantém as duas leituras iguais.
        """
        dados = await self._get("/api/v1/meuacesso/tasks",
                                usina_type_plan_item_id=plan_item_id, contract_month=mes)
        if isinstance(dados, dict):
            return dados.get("items") or dados.get("results") or []
        return dados or []

    async def ficha_da_tarefa(self, task_id: int) -> dict[str, Any]:
        """As RESPOSTAS da tarefa em JSON — medições, checklist, parecer, por equipamento.

        É a mesma fonte do PDF do lado de lá (`ficha_leitura` lê o que o gerador do laudo lê),
        então tela e documento não divergem. Uma ficha grande leva alguns segundos.
        """
        r = await self._req("GET", f"/api/v1/meuacesso/tasks/{task_id}/ficha", timeout=120.0)
        return r.json()

    async def pdf_da_tarefa(self, task_id: int) -> bytes:
        """O PDF de UMA tarefa — a ficha respondida pelo técnico.

        Diferente do PDF da OS (que passa pela cesta), o do ensaio tem rota direta que já
        devolve a versão vigente e só regera quando algo mudou. Uma ficha grande leva alguns
        segundos na primeira vez, por isso o cliente precisa de um timeout folgado."""
        r = await self._req("GET", f"/api/v1/meuacesso/tasks/{task_id}/pdf/view",
                            timeout=180.0)
        return r.content

    async def baixar_pdf_cesta(self, item_id: int) -> bytes:
        r = await self._req("GET", f"/api/v1/meuacesso/pdf-basket/{item_id}/download")
        return r.content

    async def pdf_cronograma(self, usina_id: int, container_id: int) -> bytes:
        """Mantido pelo nome; hoje é `vc_cronograma_pdf`.

        Antes batia em `/maintenance/usinas/{id}/cronograma/pdf` SEM `container_id` — que
        lá é `Query(...)` obrigatório. O upstream respondia 422, este lado achatava em 502
        "Não deu para gerar o cronograma em PDF", e o botão de PDF nunca funcionou.
        """
        return await self.vc_cronograma_pdf(usina_id, container_id)

    # ------------------------------------ relatório de manutenção (visão do cliente)

    async def vc_relatorio(
        self, usina_id: int, de: str, ate: str, container_id: int | None = None
    ) -> dict[str, Any]:
        """O relatório de manutenção do período — agregado do próprio ativo, no meuPlano.

        `de`/`ate` são competências (`YYYY-MM`). Sem `container_id`, o meuPlano escolhe o
        contrato com cronograma consolidado mais recente. Agrega cronograma, OSs, pareceres,
        problemas, dispensas e pendências numa ida só; numa usina grande isso leva segundos,
        daí o prazo folgado.
        """
        r = await self._req(
            "GET",
            f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/relatorio-manutencao",
            params=_params_do_periodo(de, ate, container_id),
            timeout=120.0,
        )
        return r.json()

    async def vc_relatorio_pdf(
        self, usina_id: int, de: str, ate: str, container_id: int | None = None
    ) -> bytes:
        """O mesmo relatório, renderizado em PDF pelo meuPlano — do MESMO JSON, então tela e
        documento não divergem. `/pdf/view` e não `/pdf`: é a rota autenticada (a terminação
        `/pdf` cai na dispensa pública do audit de permissões de lá)."""
        r = await self._req(
            "GET",
            f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/relatorio-manutencao/pdf/view",
            params=_params_do_periodo(de, ate, container_id),
            timeout=180.0,
        )
        return r.content

    # ------------------------------------- pendências (visão do cliente)
    #
    # A rota INTERNA do funil (`/pipelines/global/pendencia/containers`) devolve TUDO a quem
    # manda na usina — e a conta de serviço desta ponte é da Splendor, que manda. O router
    # `visao-cliente` do meuPlano aplica o corte do cliente (`shareable`, documentos
    # publicados) sempre, independente de quem pergunta. É só ele que este cliente chama.

    async def vc_pendencias(self, usina_id: int) -> list[dict[str, Any]]:
        """As pendências COMPARTILHÁVEIS de uma usina, já recortadas pelo meuPlano.

        O BFF re-filtra `shareable` de qualquer jeito (`api/v1/pendencias.py`): a régua do
        que o cliente vê tem de valer mesmo que a rota de lá mude.
        """
        dados = await self._get(f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/pendencias")
        if isinstance(dados, dict):
            return dados.get("items") or dados.get("results") or []
        return dados or []

    async def vc_pendencia(self, cid: int) -> dict[str, Any]:
        """O detalhe leve: o container, o parecer, os documentos PUBLICADOS e as OSs
        vinculadas — numa chamada. Sem feed nem checklist, por desenho de lá."""
        return await self._get(f"/api/v1/meuacesso/visao-cliente/pendencias/{cid}")

    async def vc_documento(self, cid: int, did: int) -> tuple[bytes, str]:
        """Os bytes de UM documento da pendência, com o tipo declarado.

        O meuPlano responde com um redirect para a URL assinada do armazenamento; o cliente
        segue o redirect (e o httpx tira o `Authorization` ao trocar de host, que é o
        certo — a URL assinada já é a credencial). Quem chama precisa ter conferido ANTES
        que o `did` está entre os publicados: a rota de lá é aberta por id.
        """
        r = await self._req(
            "GET", f"/api/v1/meuacesso/pipelines/containers/{cid}/documents/{did}/download",
            timeout=60.0,
        )
        return r.content, r.headers.get("content-type", "application/octet-stream")

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
