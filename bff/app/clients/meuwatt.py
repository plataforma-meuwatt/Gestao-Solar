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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel

from app.clients.http import sessao
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
        c = sessao(self.base_url, self._timeout)
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

    async def _get(
        self, path: str, token: str | None = None, timeout: float | None = None, **params: Any
    ) -> Any:
        """`timeout` sobrepõe o teto do cliente, e existe para quem TEM plano B: esperar
        trinta segundos por uma fonte que tem substituta é o que faz a tela demorar."""
        jwt = token or await self._token_servico()
        c = sessao(self.base_url, self._timeout)
        r = await c.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {jwt}"},
            params={k: v for k, v in params.items() if v is not None},
            timeout=timeout or self._timeout,
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

    async def pvsyst(self, slug: str, inicio: date, fim: date) -> dict[str, Any]:
        """A meta de projeto DIÁRIA (`pvsyst_previewed_energy`): `rows[].{date, e_grid}`.

        É o "esperado" contra o qual o portal compara a energia medida. Nunca é estimado
        deste lado: se a tabela não tem linha para o período, a resposta vem vazia e o
        portal diz "sem meta cadastrada" — não inventa um número.
        """
        return await self._get(
            f"/plants/{slug}/pvsyst", start=inicio.isoformat(), end=fim.isoformat()
        )

    async def pvsyst_manual(self, slug: str, ano: int) -> dict[str, Any]:
        """A meta de projeto MENSAL digitada na aba Projeto do meuWatt
        (`pvsyst_manual_monthly`): `rows[].{month, e_grid}` só dos meses salvos.

        É a fonte que o próprio mw-fe usa no relatório (`ReportView` → `getManualYear`),
        e a segunda opção deste lado quando a tabela diária não cobre o período — muitas
        usinas têm só a simulação anual em PDF, transcrita mês a mês.
        """
        return await self._get(f"/plants/{slug}/pvsyst/manual/{int(ano)}")

    async def intraday(self, slug: str, dia: date | None = None) -> dict[str, Any]:
        """Curva do dia em buckets de 5 min: `points[].{time, inverters[]}`.

        Cada ponto traz a lista de inversores QUE MEDIRAM naquele bucket — quem não
        mediu simplesmente não aparece, e é assim que a lacuna chega até a tela em vez
        de virar zero.
        """
        params = {"date": dia.isoformat()} if dia else {}
        return await self._get(f"/plants/{slug}/charts/intraday", **params)

    async def intraday_strings(self, slug: str, dia: date | None = None) -> dict[str, Any]:
        """Corrente por string (PV1..PV32) e MPPT, em buckets de 5 min.

        Mesma estrutura da curva de potência — `points[].inverters[]` —, mas cada
        inversor traz `strings` e `mppts` em vez de potência.
        """
        params = {"date": dia.isoformat()} if dia else {}
        return await self._get(f"/plants/{slug}/charts/intraday/strings", **params)

    async def intraday_rele(self, slug: str, dia: date | None = None) -> dict[str, Any]:
        """Tensão, corrente e potência por fase de cada relé de proteção, em 5 min."""
        params = {"date": dia.isoformat()} if dia else {}
        return await self._get(f"/plants/{slug}/charts/intraday/relay", **params)

    async def intraday_temperatura(self, slug: str, dia: date | None = None) -> dict[str, Any]:
        """Temperatura de cada sensor (S1/S2/S3 + ambiente), em buckets de 5 min."""
        params = {"date": dia.isoformat()} if dia else {}
        return await self._get(f"/plants/{slug}/charts/intraday/temperature", **params)

    async def eventos_de_trip(
        self, slug: str, relay_id: int, limite: int = 50
    ) -> dict[str, Any]:
        """Histórico de flags de um relé de proteção, mais recente primeiro.

        `relay_id` é o id NUMÉRICO do relé no meuWatt — o `monitoring/current` publica
        `relay-{id}`, e o prefixo precisa sair antes de chegar aqui.
        """
        return await self._get(f"/plants/{slug}/relays/{relay_id}/trip-events", limit=limite)

    async def alertas(
        self, slug: str, status: str = "active", limit: int = 500, offset: int = 0
    ) -> dict[str, Any]:
        """Uma PÁGINA de alertas: `AlertListResponse{plant, total, alerts[]}`.

        O upstream pagina (`limit` ≤ 500, `offset`) e, sem dizer nada, corta em 100 quando
        ninguém pede — foi assim que o histórico de uma usina com 130 paradas chegava com
        30 a menos. Quem quer tudo usa `alertas_todos`.
        """
        return await self._get(
            f"/plants/{slug}/alerts", status=status, limit=limit, offset=offset
        )

    async def alertas_todos(
        self, slug: str, status: str = "all", limit: int = 500
    ) -> list[dict[str, Any]]:
        """Todos os alertas da usina, página a página, até a última vir incompleta.

        É a fonte ALTERNATIVA de paradas enquanto `breakdowns/range` responde 500 (ver
        `api/v1/paradas.py`): o mesmo evento aparece nos dois lugares, só que aqui sem
        filtro de período — o corte por data fica com quem chama. O teto de páginas é
        proteção contra um upstream que devolvesse sempre uma página cheia; 20 páginas
        são dez mil eventos, mais do que qualquer usina acumulou.
        """
        todos: list[dict[str, Any]] = []
        offset = 0
        for _ in range(20):
            pagina = await self.alertas(slug, status=status, limit=limit, offset=offset)
            itens = pagina.get("alerts") if isinstance(pagina, dict) else pagina
            if not isinstance(itens, list):
                break
            todos.extend(i for i in itens if isinstance(i, dict))
            if len(itens) < limit:
                break
            offset += limit
        return todos

    async def paradas(
        self, slug: str, inicio: date, fim: date, timeout: float | None = None
    ) -> dict[str, Any]:
        """`BreakdownRangeResponse{plant, start, end, total, total_loss_kwh,
        total_off_time_minutes, breakdowns[]}` — as paradas cujo INÍCIO cai no período.

        Responde 500 em produção (ver `api/v1/paradas.py`, que tem a fonte reserva) — e
        demora entre 16 e 23 s para dizê-lo, medido nas 7 usinas do escopo de homologação.
        Daí o `timeout`: quem chama passa um teto curto, porque o plano B responde em 2 s.
        """
        return await self._get(
            f"/plants/{slug}/breakdowns/range",
            timeout=timeout,
            start=inicio.isoformat(),
            end=fim.isoformat(),
        )

    async def slots(self, slug: str) -> list[dict[str, Any]]:
        """Inversor é endereçado por SLOT (posição física permanente), não por serial — o
        serial muda quando o equipamento é trocado, o slot não."""
        return await self._get(f"/plants/{slug}/slots")

    async def slot(self, slug: str, slot_id: int) -> dict[str, Any]:
        return await self._get(f"/plants/{slug}/slots/{slot_id}")

    async def ssu_totais_mensais(self, slug: str, ano: int) -> dict[int, float]:
        """A FRONTEIRA do ano, mês a mês, em MWh: `{mês (1-12): MWh}`.

        É outra MEDIÇÃO, não outra conta. Os inversores medem o que geraram; o medidor
        SSU mede o que atravessou o ponto de entrega. A diferença entre os dois é a
        perda até a fronteira, e é este número — não o dos inversores — que se concilia
        com a conta da distribuidora.

        Mês sem leitura fica **fora do mapa**, nunca zero, e usina sem medidor devolve
        `{}`: o portal diz "sem medição na fronteira" em vez de publicar uma queda que
        nunca houve. O atalho antigo — medido × 0,987 — foi removido do próprio meuWatt
        por ser um número inventado vestido de medição; não volta por aqui.
        """
        corpo = await self._get(f"/plants/{slug}/ssu-readers/monthly-totals", year=int(ano))
        bruto = corpo.get("by_month") if isinstance(corpo, dict) else None
        if not isinstance(bruto, dict):
            return {}

        totais: dict[int, float] = {}
        for mes, mwh in bruto.items():
            # As chaves chegam como texto (é JSON) e o mês é índice, não rótulo: quem
            # consome compara com `data.month`, que é int.
            try:
                totais[int(mes)] = float(mwh)
            except (TypeError, ValueError):
                continue
        return totais

    #: O que pode sair de uma fatura. A listagem do upstream traz também `titular`,
    #: `installation_number` e `tariff` — dado contratual do cliente, que o portal não
    #: usa e não tem por que atravessar a ponte. Os irmãos `/{id}/pdf` e
    #: `/{id}/password` (a senha do PDF é CPF/CNPJ parcial do titular) não têm método
    #: aqui de propósito: o que não existe no cliente não vaza por descuido de rota nova.
    CAMPOS_DA_FATURA = ("transformer_id", "year", "month", "billed_mwh")

    async def faturas_concessionaria(
        self, slug: str, ano: int | None = None
    ) -> list[dict[str, Any]]:
        """O MWh faturado pela distribuidora, por UC e por mês.

        UC no meuWatt é o TRANSFORMADOR — cada fatura pertence a um transformer.id.
        Sem `ano` o upstream devolve o histórico inteiro; a conciliação do painel é
        sempre de um ano, então quem chama passa o ano em vez de arrastar anos de
        fatura para recortar um deles.

        A resposta vem em envelope (`{"bills": [...]}`) e sai daqui como lista, já
        recortada aos campos de `CAMPOS_DA_FATURA`. Recortar no cliente é a exceção
        declarada à regra do módulo (traduzir é dos serviços): a PII não pode depender
        de cada chamador lembrar de descartá-la.
        """
        corpo = await self._get(
            f"/plants/{slug}/utility-bills", year=int(ano) if ano is not None else None
        )
        brutas = corpo.get("bills") if isinstance(corpo, dict) else corpo
        if not isinstance(brutas, list):
            return []
        return [
            {campo: f.get(campo) for campo in self.CAMPOS_DA_FATURA}
            for f in brutas
            if isinstance(f, dict)
        ]

    #: O que pode sair de uma parada CLASSIFICADA. A `AlertDetail` do upstream é o
    #: registro de trabalho da equipe: ela carrega o número de série do inversor, o
    #: `inverter_id`, o número da ordem de serviço, as notas do operador
    #: (`observacoes`, `acknowledgement_note`, `suppression_note`), quem classificou e
    #: quem editou a perda. Nada disso é do dono da usina — e o recorte fica AQUI, e não
    #: em quem chama, pelo mesmo motivo de `CAMPOS_DA_FATURA`: a PII não pode depender
    #: de cada chamador lembrar de descartá-la.
    #:
    #: `motivo`/`origem`/`causa` são a classificação que dá LASTRO à disponibilidade
    #: contratual — sem elas o portal publica um número de teor contratual sem nenhuma
    #: justificativa ao lado. `is_external_cause` é o que separa "foi a manutenção" de
    #: "estava fora do alcance dela". `daily_losses` são as fatias por dia BRT do motor
    #: (Σ = a perda da parada), e é o que permite recortar ao mês uma parada que
    #: atravessa a virada sem estimar nada.
    CAMPOS_DA_PARADA = (
        "id",
        "kind",
        "started_at",
        "resolved_at",
        "is_active",
        "duration_minutes",
        "estimated_loss_kwh",
        "daily_losses",
        "motivo",
        "origem",
        "causa",
        "is_external_cause",
        "manual_group_id",
        "transformer_name",
    )

    async def paradas_classificadas(self, slug: str) -> list[dict[str, Any]]:
        """As paradas da usina com a CLASSIFICAÇÃO do operador, recortadas.

        Vem de `alerts?status=all` (paginado por `alertas_todos`) e não de
        `breakdowns/range`: a linha do `range` não traz `motivo` nem
        `is_external_cause` — que são justamente o motivo desta leitura existir. Sem
        filtro de período, como a fonte; o corte por data fica com quem chama, pela
        mesma régua de `api/v1/paradas.py` (o dia BRT de `started_at`).
        """
        return [
            {campo: a.get(campo) for campo in self.CAMPOS_DA_PARADA}
            for a in await self.alertas_todos(slug, status="all")
            if isinstance(a, dict)
        ]

    async def observacoes(
        self, slug: str, periodo: str, de: date
    ) -> list[dict[str, Any]]:
        """As observações que a equipe escreveu para aquele período do relatório.

        `periodo` é o vocabulário do upstream (`DIÁRIO | SEMANAL | MENSAL | ANUAL`) e
        `de` é o primeiro dia da janela — a chave (usina, seção, período, início) é o
        que separa a caixa de abril da de maio.

        **Só leitura.** Escrever é trabalho de operação e não tem por que atravessar
        para o portal do cliente: o que não existe no cliente não vaza por descuido de
        rota nova (mesma postura de `/{id}/pdf` das faturas).
        """
        corpo = await self._get(
            f"/plants/{slug}/observations", period=periodo, date_from=de.isoformat()
        )
        itens = corpo.get("observations") if isinstance(corpo, dict) else corpo
        if not isinstance(itens, list):
            return []
        return [i for i in itens if isinstance(i, dict)]

    async def timeline_de_paradas(self, slug: str, ano: int, mes: int) -> dict[str, Any]:
        """A timeline CURADA das paradas do mês — a história contada por quem esteve lá.

        O upstream devolve `show_in_report=False` e `milestones=[]` para o mês que
        ninguém curou, e é assim que ele chega aqui: **mês sem curadoria é estado
        normal, não erro** — a seção simplesmente não existe naquele mês.
        """
        return await self._get(
            f"/plants/{slug}/paradas-timeline", year=int(ano), month=int(mes)
        )

    async def portal_relatorios(self, token: str | None = None) -> dict[str, Any]:
        """Portal do Cliente: relatórios publicados.

        A rota é fechada a `plant_owner` **ou** administrador. Com o token de serviço — que
        costuma ser de administrador — ela devolve as usinas **todas**, porque é também a
        pré-visualização que o gestor usa. Quem chama daqui é obrigado a filtrar pelo
        escopo do cliente antes de mostrar qualquer coisa; ver `api/v1/documents.py`.
        """
        return await self._get("/reports/portal", token=token)

    #: As peças de um fechamento. É lista fechada porque `kind` entra na URL do
    #: upstream, e a chamada usa o token de serviço — que costuma ser de administrador.
    #: Com texto livre, `../../../admin/users` normaliza para outra rota da mw-api e o
    #: cliente recebe os bytes. A validação existe aqui **além** da rota que chama, para
    #: que um chamador futuro não reabra o buraco por descuido.
    #:
    #: `resumo` é o Resumo Executivo, o terceiro documento do fechamento. Ele entrou de
    #: propósito, acrescentando um valor à lista — nunca afrouxando o tipo —, porque a
    #: mw-api já o publica (`_FILE_KINDS = {geracao, paradas, resumo}`) e o download daqui
    #: o recusava. É a peça mais RARA das três: o deck só é gerado quando o mês teve uma
    #: análise de IA concluída, então fechamento sem ela é estado normal, não defeito.
    PECAS = ("geracao", "paradas", "resumo")

    async def arquivo_relatorio(self, report_id: int, kind: str) -> bytes:
        if kind not in self.PECAS:
            raise MeuWattError(f"peça de relatório desconhecida: {kind!r}")

        jwt = await self._token_servico()
        c = sessao(self.base_url, self._timeout)
        r = await c.get(
            f"{self.base_url}/reports/{int(report_id)}/files/{kind}",
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.content

    # ------------------------------------------------- exportação de dados brutos

    async def export_options(self, slug: str) -> dict[str, Any]:
        """O que ESTA usina pode oferecer na tela "Baixar dados".

        `RawExportOptions{plant, skids[], estacao, fronteira, sistema, retencao, limites}`
        — os inversores por skid, quais colunas a estação realmente coleta, os leitores da
        fronteira, se há PR, desde quando existe cada acervo e os tetos de dias por passo.

        É o que permite a tela dizer *"esta usina não tem estação solarimétrica"* em vez de
        oferecer o bloco e devolver um 400 depois de meio minuto de espera. Barata: 1,2 s a
        2,1 s medidos em Porto Ferreira (a maior do escopo, 20 inversores, 05/09/2026),
        contra os 35,6 s da geração do arquivo — daí o teto de 20 s aqui, curto o bastante
        para a tela não ficar pendurada numa fonte que já provou responder rápido.

        E ela **não** entra no balde de 10/minuto: o `@limiter.limit` da mw-api está só no
        POST — provado, com três `options` seguidas depois do balde esgotado respondendo
        200. A tela pode reabrir à vontade.
        """
        return await self._get(f"/plants/{slug}/exports/raw/options", timeout=20.0)

    @asynccontextmanager
    async def export_raw(
        self, slug: str, pedido: BaseModel
    ) -> AsyncIterator[httpx.Response]:
        """O `.xlsx` da seleção, ABERTO e ainda não lido.

        Contexto assíncrono, e não `-> bytes`, pelo mesmo motivo de
        `MeuPlanoClient.vc_fichas_pacote`: ler a resposta inteira de uma vez guardaria o
        arquivo na memória deste processo e de novo na do corpo que o portal devolve. O teto do
        servidor é o orçamento de células (2.000.000), que a ~2,78 bytes/célula medidos dá
        ≈ 5,3 MiB por arquivo — não é o monstro que se temia, mas o risco no Railway nunca
        foi um arquivo: é N clientes × 5 MiB ao mesmo tempo. Quem chama repassa os pedaços.

        **O fluxo aqui não adianta o primeiro byte, e é honesto dizê-lo.** A mw-api gera o
        XLSX inteiro antes de responder (`to_thread(write_xlsx)` → `FileResponse` de um
        temporário, com `Content-Length` e sem `chunked`): medido no pior caso que ela
        aceita (5 min × 31 d, todos os blocos de Porto Ferreira), o CABEÇALHO chega aos
        35,6 s, e o corpo — 2.511.408 B (2,40 MiB) em 212 pedaços — transfere em 1,4 s
        depois dele. Fluxo aqui serve para não SEGURAR os bytes, não para o cliente vê-los
        mais cedo.

        ⚠ O pedido que se temia — 366 dias em passo de 1 h com todos os blocos — **não
        existe**: a retenção dos snapshots é de 183 dias e a mw-api o recusa em 2,2 s com
        `fora_da_retencao`. O maior pedido de 1 h que sobrevive é o de 183 dias (18,7 s de
        cabeçalho, 0,66 MiB). O pior caso VERDADEIRO é o de 31 d × 5 min acima.

        Daí o prazo de LEITURA de 120 s, explícito. O cliente é construído sem `timeout` em
        `integracoes.cliente_meuwatt` e cai nos 30 s da assinatura — que REPROVAM o pior
        pedido permitido: pelo caminho normal esta exportação estouraria `ReadTimeout`
        antes de o servidor terminar. E as medições do MESMO pedido (35,6 s, 34,3 s,
        27,2 s) mostram que a margem contra 30 s não é só apertada, é instável — na última
        ela já não existe. O precedente já estava no arquivo (`arquivo_relatorio` passa
        60 s explícito); 120 s é a folga para usina maior ou Timescale fria. **Conectar
        continua curto (5 s)**: destino fora do ar tem de falhar depressa, não em dois
        minutos.

        O `pedido` é um modelo Pydantic já validado — nunca um `dict` repassado cru. O
        `{slug}` é interpolado numa URL chamada com a credencial de serviço, e é a mesma
        forma que já custou caro em `documents.py` (`../../../admin/users` normalizava e
        devolvia os bytes): quem chama resolve o slug a partir de `PlantLink`, e o corpo
        atravessa tipado porque o BFF não pode ser o lugar por onde entra o que ninguém
        olhou. `exclude_none=True` porque **bloco ausente não entra no arquivo** — mandar
        `"estacao": null` é dizer a mesma coisa, mas depender do upstream tratar nulo como
        ausente é apostar numa gentileza que o contrato não promete.
        """
        jwt = await self._token_servico()
        c = sessao(self.base_url, self._timeout)
        async with c.stream(
            "POST",
            f"{self.base_url}/plants/{slug}/exports/raw",
            headers={"Authorization": f"Bearer {jwt}"},
            json=pedido.model_dump(mode="json", exclude_none=True),
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
        ) as r:
            if r.status_code >= 400:
                # O corpo do erro é JSON curto — 400 traz `{"detail": {motivo, message}}`
                # e o 429 do limite traz `{"error": ...}`. Lê-se inteiro para que a razão
                # chegue a quem traduz; só o caminho FELIZ é que não pode ser materializado.
                await r.aread()
                if r.status_code == 401:
                    self._service_token = None
                r.raise_for_status()
            yield r
