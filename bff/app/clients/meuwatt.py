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
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.meuwatt_api_url).rstrip("/")
        self._usuario = usuario
        self._senha = senha
        # Token pessoal (`mw_pat_…`) que alguém gerou no meuWatt e colou no painel. Quando
        # existe, dispensa o login: não há senha guardada nem sessão a renovar, e o acesso
        # é revogável do outro lado sem passar por aqui.
        self._token_fixo = token
        self._timeout = timeout
        self._service_token: str | None = None

    # ------------------------------------------------------------------ auth

    async def quem_sou_eu(self, token: str | None = None) -> dict[str, Any]:
        """De quem é a credencial em uso. É o que faz a tela de Conexões dizer "token de
        Fulano" em vez de só "conectado" — sem isso, ninguém percebe que colou o token da
        pessoa errada, e o escopo de usinas vem calado junto."""
        return await self._get("/auth/me", token=token)

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
        if self._token_fixo:
            return self._token_fixo
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

    async def usuarios(self, apenas_ativos: bool = True) -> list[dict[str, Any]]:
        """Todos os usuários. Não há busca por e-mail nesta API — quem precisa filtrar,
        filtra do lado de cá."""
        return await self._get("/admin/users", only_active=apenas_ativos)

    async def plantas_do_usuario(self, user_id: str | int) -> list[str]:
        """Os slugs das plantas que aquele usuário enxerga.

        Reconstituído a partir de `user_plants`, que é a concessão direta. Não cobre quem
        vê plantas por ser funcionário de uma empresa de O&M — a API não expõe esse
        agregado, e para o dono de usina (nosso caso) a concessão direta é o que vale.
        """
        associacoes = await self._get("/admin/user-plants")
        plant_ids = {
            a.get("plant_id") for a in associacoes if str(a.get("user_id")) == str(user_id)
        }
        if not plant_ids:
            return []

        # A associação traz plant_id; o resto do sistema trabalha com slug.
        return [p["slug"] for p in await self.usinas() if p.get("id") in plant_ids]

    async def monitoramento_atual(self, slug: str) -> dict[str, Any]:
        return await self._get(f"/plants/{slug}/monitoring/current")

    async def geracao_diaria(self, slug: str, dia: date) -> dict[str, Any]:
        return await self._get(f"/plants/{slug}/generation/daily", date=dia.isoformat())

    async def geracao_periodo(self, slug: str, inicio: date, fim: date) -> dict[str, Any]:
        """O upstream limita o intervalo a 366 dias — a tela Anual encosta nesse teto."""
        return await self._get(
            f"/plants/{slug}/generation/range", start=inicio.isoformat(), end=fim.isoformat()
        )

    async def intraday(self, slug: str, dia: date | None = None) -> dict[str, Any]:
        """Curva do dia em buckets de 5 min: `points[].{time, inverters[]}`.

        Cada ponto traz a lista de inversores QUE MEDIRAM naquele bucket — quem não
        mediu simplesmente não aparece, e é assim que a lacuna chega até a tela em vez
        de virar zero.
        """
        params = {"date": dia.isoformat()} if dia else {}
        return await self._get(f"/plants/{slug}/charts/intraday", **params)

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

    async def portal_relatorios(self, token: str | None = None) -> dict[str, Any]:
        """Portal do Cliente: relatórios publicados.

        A rota é fechada a `plant_owner` **ou** administrador. Com o token de serviço — que
        costuma ser de administrador — ela devolve as usinas **todas**, porque é também a
        pré-visualização que o gestor usa. Quem chama daqui é obrigado a filtrar pelo
        escopo do cliente antes de mostrar qualquer coisa; ver `api/v1/documents.py`.
        """
        return await self._get("/reports/portal", token=token)

    #: As duas peças de um fechamento. É lista fechada porque `kind` entra na URL do
    #: upstream, e a chamada usa o token de serviço — que costuma ser de administrador.
    #: Com texto livre, `../../../admin/users` normaliza para outra rota da mw-api e o
    #: cliente recebe os bytes. A validação existe aqui **além** da rota que chama, para
    #: que um chamador futuro não reabra o buraco por descuido.
    PECAS = ("geracao", "paradas")

    async def arquivo_relatorio(self, report_id: int, kind: str) -> bytes:
        if kind not in self.PECAS:
            raise MeuWattError(f"peça de relatório desconhecida: {kind!r}")

        jwt = await self._token_servico()
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(
                f"{self.base_url}/reports/{int(report_id)}/files/{kind}",
                headers={"Authorization": f"Bearer {jwt}"},
            )
        r.raise_for_status()
        return r.content
