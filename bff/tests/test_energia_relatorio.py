"""O fechamento do mês — `GET /api/v1/energia/usinas/{id}/relatorio-mes`.

Esta aba nasceu de uma frase do dono ("a aba RELATÓRIO também, ela tem informações boas")
e de uma restrição do mesmo dono ("sem a opção de gerar PDF"). Os dois lados dessa frase
são defeitos guardados aqui.

O que cada teste guarda:

- **`potencial_kwh` não pode ser uma segunda conta.** Ele é `medido + perdida`, e as duas
  parcelas têm de vir do MESMO `/painel` do mesmo mês. Se alguém trocar a fonte da perda
  pela do `useReportParadas` do meuWatt — que existe, é tentadora e é *mais* precisa — o
  portal passa a publicar dois números para a mesma perda (medido na Pirapozinho: 30,98
  contra 29,90 MWh) e a única pergunta que esta aba responde perde o lastro.
- **A fábrica de PDF não pode atravessar.** Um teste varre o JSON inteiro atrás de
  `branding`, `capa`, `qr` e `pdf` — a capa, a contracapa com QR code e o
  `report-branding` são maquinário de impressão, e o dono os recusou por escrito.
- **A ausência não vira zero**, nas quatro portas em que ela é mais tentadora aqui: mês
  sem curadoria da timeline, mês sem considerações, paradas que o upstream não entregou e
  parada sem duração calculada.
- **A PII da equipe não atravessa.** A `AlertDetail` do meuWatt carrega número de série,
  `inverter_id`, nº da ordem de serviço e as notas do operador. O recorte é do cliente
  (`CAMPOS_DA_PARADA`) e há um teste que o confere no JSON de saída.
- **Todo percentual sai com o denominador.** `horas_paradas` sem `horas_possiveis` e sem
  `inversores_considerados` é o absoluto que se lê para o lado alarmante.

Os payloads são os que `generation/range`, `/alerts`, `/observations` e
`/paradas-timeline` devolvem de fato (shapes conferidos em `mw-api/src/*/schemas.py`).
"""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import energia, plants
from app.clients.meuwatt import MeuWattClient
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

#: Meio de agosto — o mês da referência fica EM CURSO, que é onde mora o recorte do
#: denominador em "agora" (contar o dia de hoje inteiro faria a fração parada encolher).
HOJE = date(2026, 8, 14)
AGORA = datetime(2026, 8, 14, 12, 0, 0)

#: UTC-3 sem horário de verão — o fuso das usinas, igual ao `BRT` de `core.datas`. Os
#: carimbos do meuWatt chegam em UTC; escrevê-los aqui já com o fuso é o que faz o teste
#: exercitar a conversão em vez de contorná-la.
BRT_FIXO = timezone(timedelta(hours=-3))


def _aplicacao(db) -> FastAPI:
    aplicacao = FastAPI()
    aplicacao.include_router(energia.router)
    aplicacao.dependency_overrides[get_db] = lambda: db
    return aplicacao


@pytest.fixture
def dono(db):
    u = User(
        apelido="renan.marquezini",
        email="renan@exemplo.com.br",
        nome="Renan",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


# ── os payloads do upstream ──────────────────────────────────────────────────


def _janelas_solares(ate: int) -> list[dict]:
    """`daily_solar_windows` — 06:00 às 18:00 BRT, 720 min por dia."""
    return [
        {
            "date": f"2026-08-{d:02d}",
            "sunrise_utc": f"2026-08-{d:02d}T09:00:00+00:00",
            "sunset_utc": f"2026-08-{d:02d}T21:00:00+00:00",
            "duration_min": 720.0,
        }
        for d in range(1, ate + 1)
    ]


def _range(
    *,
    energia_kwh: float = 9800.0,
    perdida_kwh: float = 140.0,
    janelas: list[dict] | None = None,
    transformadores: list[dict] | None = None,
    **extra,
) -> dict:
    """O `RangeGenerationReport` como o mw-api o monta, no essencial que esta aba lê."""
    base = {
        "plant": "Porto Ferreira",
        "start_date": "2026-08-01",
        "end_date": "2026-08-14",
        "days_in_range": 14,
        "days_with_data": 14,
        "total_generation_kwh": energia_kwh,
        "total_capacity_kwp": 1000.0,
        "performance_ratio": 0.8123,
        "availability_real_pct": 98.2,
        "availability_contratual_pct": 99.1,
        "pending_classification_count": 0,
        "summary": {"total_lost_kwh": perdida_kwh, "total_lost_externa_kwh": 30.0},
        "inverters": [
            {"id": 1, "sn": "SN2312090045", "capacity_kwp": 500.0, "transformer_id": 11},
            {"id": 2, "sn": "SN2312090046", "capacity_kwp": 500.0, "transformer_id": 12},
        ],
        "transformers": transformadores
        if transformadores is not None
        else [
            {"id": 11, "name": "UC Norte", "inverter_count": 1, "total_yield_kwh": 5000.0},
            {"id": 12, "name": "UC Sul", "inverter_count": 1, "total_yield_kwh": 4800.0},
        ],
        "daily_summaries": [
            {"date": f"2026-08-{d:02d}", "generation_kwh": 700.0} for d in range(1, 15)
        ],
        "monthly_summaries": [
            {"month": "2026-08", "generation_kwh": energia_kwh, "lost_kwh": perdida_kwh}
        ],
        "daily_solar_windows": janelas if janelas is not None else _janelas_solares(14),
        "chart_data": {
            "daily_generation": {},
            "daily_irradiation": [],
            "daily_temperature": [],
            "daily_pr": [],
            "daily_pr_flags": [],
        },
    }
    base.update(extra)
    return base


def _pvsyst(kwh_por_dia: float = 700.0) -> dict:
    return {
        "rows": [
            {
                "date": f"2026-08-{d:02d}",
                "e_array": kwh_por_dia,
                "e_grid": kwh_por_dia,
                "globinc": 5.2,
                "pr": 0.8,
            }
            for d in range(1, 32)
        ],
        "years": [2026],
        "count": 31,
    }


def _alerta(
    id_: int,
    *,
    dia: int = 5,
    hora: int = 9,
    kind: str = "stop",
    duracao_min: float | None = 120.0,
    perda_kwh: float = 60.0,
    motivo: str | None = "Falta de energia da concessionária",
    origem: str | None = "Externa",
    externa: bool = True,
    grupo: str | None = None,
    uc: str | None = "UC Norte",
    fatias: list[dict] | None = None,
    resolvido: bool = True,
    **extra,
) -> dict:
    """Um `AlertDetail` — COM as entranhas que o cliente não pode ver, para o recorte do
    `MeuWattClient` ser exercitado de verdade e não presumido."""
    inicio = datetime(2026, 8, dia, hora, tzinfo=BRT_FIXO)
    alerta = {
        "id": id_,
        "inverter_id": 900 + id_,
        "sn": "SN2312090045",
        "model": "SUN2000-100KTL",
        "transformer_name": uc,
        "kind": kind,
        "status": 1,
        "notification": None,
        "message": None,
        "started_at": inicio.isoformat(),
        "resolved_at": (inicio + timedelta(hours=2)).isoformat() if resolvido else None,
        "is_active": not resolvido,
        "duration_minutes": duracao_min,
        "estimated_loss_kwh": perda_kwh,
        "daily_losses": fatias,
        "is_monitoring_issue": False,
        "motivo": motivo,
        "origem": origem,
        "causa": None,
        "causa_raiz": "Religador da distribuidora",
        "ordem_servico": "OS-4471",
        "observacoes": "cliente avisou por telefone; não repetir no relatório",
        "is_external_cause": externa,
        "classified_by_name": "Diogo",
        "acknowledgement_note": "vi e liguei para a CPFL",
        "manual_group_id": grupo,
    }
    alerta.update(extra)
    return alerta


def _observacao(
    *,
    secao: str = "dash:gerais",
    corpo: str = "Mês marcado por duas quedas da concessionária; usina normalizada.",
    autor: str = "Diogo",
    atualizado: str = "2026-09-02T14:30:00+00:00",
) -> dict:
    return {
        "id": 71,
        "plant_id": 3,
        "user_id": 8,
        "user_name": autor,
        "section": secao,
        "period": "MENSAL",
        "date_from": "2026-08-01",
        "date_key": None,
        "body": corpo,
        "created_at": "2026-09-01T10:00:00+00:00",
        "updated_at": atualizado,
    }


def _timeline(*, exibir: bool = True, marcos: list[dict] | None = None) -> dict:
    return {
        "plant_id": 3,
        "year": 2026,
        "month": 8,
        "show_in_report": exibir,
        "milestones": marcos
        if marcos is not None
        else [
            {
                "id": "m1",
                "at": "2026-08-05T12:00:00+00:00",
                "tone": "parada",
                "chip": "Queda",
                "title": "Falta de energia na rede",
                "sub": "Toda a usina fora por 2 h",
                "group": "g1",
            },
            {
                "id": "m2",
                "at": "2026-08-05T14:00:00+00:00",
                "tone": "normalizado",
                "chip": "Normalizado",
                "title": "Rede restabelecida",
                "sub": "",
                "group": "g1",
            },
        ],
        "created_by_name": "Diogo",
        "updated_by_name": "Diogo",
        "created_at": "2026-09-01T10:00:00+00:00",
        "updated_at": "2026-09-02T10:00:00+00:00",
    }


def _devolver(resposta):
    if isinstance(resposta, BaseException):
        raise resposta
    return resposta


class ClienteFalso:
    """O meuWatt sem rede. Qualquer resposta pode ser uma exceção a lançar.

    As paradas passam pelo recorte REAL do `MeuWattClient` (`CAMPOS_DA_PARADA`) em vez de
    entrarem cruas: é o recorte que impede o número de série e as notas do operador de
    chegarem ao portal, e um duplo falso que o pulasse deixaria o buraco invisível.
    """

    def __init__(
        self,
        relatorio=None,
        pvsyst=None,
        alertas=None,
        observacoes=None,
        timeline=None,
        fronteira=None,
    ):
        self.relatorio = relatorio if relatorio is not None else _range()
        self.pvsyst_resposta = pvsyst if pvsyst is not None else _pvsyst()
        self.alertas_resposta = alertas if alertas is not None else []
        self.observacoes_resposta = observacoes if observacoes is not None else []
        self.timeline_resposta = timeline if timeline is not None else _timeline(exibir=False)
        self.fronteira_resposta = fronteira if fronteira is not None else {}
        self.chamadas: list[tuple] = []

    async def geracao_periodo(self, slug, inicio, fim):
        self.chamadas.append(("range", inicio, fim))
        return _devolver(self.relatorio)

    async def pvsyst(self, slug, inicio, fim):
        self.chamadas.append(("pvsyst", inicio, fim))
        return _devolver(self.pvsyst_resposta)

    async def pvsyst_manual(self, slug, ano):
        return {"year": ano, "rows": []}

    async def ssu_totais_mensais(self, slug, ano):
        return _devolver(self.fronteira_resposta)

    async def faturas_concessionaria(self, slug, ano=None):
        return []

    async def alertas_todos(self, slug, status="all", limit=500):
        self.chamadas.append(("alertas", status))
        return _devolver(self.alertas_resposta)

    # O recorte de PII é do cliente de verdade — o falso só empresta as respostas. A
    # lista de campos vem junto: emprestar o método sem ela deixaria o teste de vazamento
    # passar por AttributeError, que é o pior jeito de um teste de segurança "passar".
    CAMPOS_DA_PARADA = MeuWattClient.CAMPOS_DA_PARADA
    paradas_classificadas = MeuWattClient.paradas_classificadas

    async def observacoes(self, slug, periodo, de):
        self.chamadas.append(("observacoes", periodo, de))
        return _devolver(self.observacoes_resposta)

    async def timeline_de_paradas(self, slug, ano, mes):
        self.chamadas.append(("timeline", ano, mes))
        return _devolver(self.timeline_resposta)


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    """Usina do dono ligada ao meuWatt, hoje congelado em 14/08/2026, cliente trocável."""
    minha, _ = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=minha.id))
    db.commit()

    caixa = {"cliente": ClienteFalso()}

    async def _cliente(_db):
        return caixa["cliente"]

    monkeypatch.setattr(energia.integracoes, "cliente_meuwatt", _cliente)
    monkeypatch.setattr(energia, "hoje_na_usina", lambda: HOJE)
    monkeypatch.setattr(energia, "agora_na_usina", lambda: AGORA)
    # `_referencia_pedida` mora em `plants` e recusa data futura pelo relógio DELE.
    monkeypatch.setattr(plants, "hoje_na_usina", lambda: HOJE)

    http = TestClient(_aplicacao(db))
    token, _ = criar_token(dono.id)
    http.headers["Authorization"] = f"Bearer {token}"
    yield http, caixa, minha


def _fechamento(http, usina, referencia="2026-08-14") -> dict:
    r = http.get(
        f"/api/v1/energia/usinas/{usina.id}/relatorio-mes?referencia={referencia}"
    )
    assert r.status_code == 200, r.text
    return r.json()


def _painel(http, usina, referencia="2026-08-14") -> dict:
    r = http.get(
        f"/api/v1/energia/usinas/{usina.id}/painel?recorte=mes&referencia={referencia}"
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── o par que separa clima de parada ─────────────────────────────────────────


def test_o_potencial_e_o_medido_mais_a_perda_do_proprio_painel(cenario):
    """⛔ O defeito guardado: `potencial_kwh` virar uma SEGUNDA conta da perda.

    O meuWatt tem duas leituras da mesma energia perdida — `summary.total_lost_kwh` (que
    sustenta a disponibilidade que este portal já publica) e a do `useReportParadas` (que
    recorta ao período e é suppression-aware). Elas divergem: 30,98 contra 29,90 MWh na
    Pirapozinho. Se o potencial daqui usar a segunda, o portal passa a dizer duas coisas
    sobre a mesma perda — e o cartão que existe para separar "faltou sol" de "a usina
    parou" deixa de ter lastro.

    A igualdade é conferida contra o `/painel` do MESMO mês, no mesmo turno, com o mesmo
    cliente: é a única prova de que a fonte é a mesma, e não só parecida.
    """
    http, _, usina = cenario

    c = _fechamento(http, usina)
    p = _painel(http, usina)

    assert c["medido_inversores_kwh"] == p["medido_inversores_kwh"]
    assert c["perdida_kwh"] == p["perdida_kwh"], "a perda é a MESMA do painel, não outra"
    assert c["potencial_kwh"] == round(
        p["medido_inversores_kwh"] + p["perdida_kwh"], 2
    ) == 9940.0
    assert c["perda_origem"] == "monitoramento"


def test_o_potencial_compara_com_o_projeto_proporcional_e_nao_com_o_do_mes_inteiro(cenario):
    """O denominador é o projeto ATÉ o dia medido, não a meta do mês fechado.

    31 dias de PVsyst a 700 kWh = 21.700 kWh de meta do mês; até o dia 14, 9.800. Comparar
    o potencial de meio de mês com a meta do mês inteiro devolveria −54 % para uma usina
    que está exatamente no plano — o mesmo defeito de janela que produziu "36 % numa tela
    e 101,7 % na outra".
    """
    http, _, usina = cenario

    c = _fechamento(http, usina)

    assert c["projeto_proporcional_kwh"] == 9800.0
    # medido 9.800 = projeto proporcional → 0 %; potencial 9.940 → +1,43 %.
    assert c["medido_vs_projeto_pct"] == 0.0
    assert c["potencial_vs_projeto_pct"] == 1.43
    assert c["potencial_vs_projeto_pct"] > c["medido_vs_projeto_pct"], (
        "é exatamente essa diferença que diz 'o mês foi de paradas, não de falta de sol'"
    )


def test_a_base_da_perda_sai_declarada_e_muda_com_o_medidor_de_fronteira(cenario):
    """`perda_pct` sobre a fronteira e sobre o inversor dão números DIFERENTES.

    O meuWatt escreve "X % da geração perdida no mês · base fronteira" justamente porque a
    conta muda de base. Publicar o percentual sem dizer de qual medição ele saiu é a
    receita de duas telas discordando sobre a mesma pergunta.
    """
    http, caixa, usina = cenario

    sem_medidor = _fechamento(http, usina)
    assert sem_medidor["perda_base"] == "inversor"
    # 140 ÷ (9.800 + 140) = 1,41 %
    assert sem_medidor["perda_pct"] == 1.41

    # 9,7 MWh na fronteira: uma perda de ~1 % até o ponto de entrega (plausível), então a
    # fronteira NÃO é parcial e passa a ser a base.
    caixa["cliente"].fronteira_resposta = {8: 9.7}
    com_medidor = _fechamento(http, usina)
    assert com_medidor["perda_base"] == "fronteira"
    assert com_medidor["perda_pct"] == 1.42
    assert com_medidor["perda_pct"] != sem_medidor["perda_pct"], (
        "as duas bases respondem à mesma pergunta com números diferentes — daí o rótulo"
    )


# ── as horas, com o denominador ──────────────────────────────────────────────


def test_as_horas_paradas_nunca_saem_sem_o_denominador(cenario):
    """⛔ O defeito guardado: publicar `141h paradas` sem dizer de quantas.

    Um absoluto sem denominador em documento contratual é sempre lido para o lado mais
    alarmante. A régua é a do próprio meuWatt: horas de sol DECORRIDAS × nº de inversores
    — e o mês em curso pára em "agora", senão o dia de hoje entra inteiro e a fração
    parada encolhe sozinha.

    Aritmética: 13 dias inteiros de 720 min + o dia 14 das 06:00 às 12:00 (360 min) =
    9.720 min; × 2 inversores ÷ 60 = 324 h.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [_alerta(1, duracao_min=120.0)]

    c = _fechamento(http, usina)

    assert c["horas_paradas"] == 2.0
    assert c["horas_possiveis"] == 324.0
    assert c["inversores_considerados"] == 2, "o denominador diz de quantos aparelhos fala"


def test_o_dia_de_hoje_entra_so_ate_agora_no_denominador(cenario):
    """Contar o dia em curso inteiro infla o possível e faz a parada parecer menor.

    Com "agora" às 18:00 (o sol já se pôs), o dia 14 entra completo: 14 × 720 × 2 ÷ 60 =
    336 h — 12 h a mais que às 12:00. A diferença é exatamente a meia janela solar de hoje
    vezes os dois inversores.
    """
    http, _, usina = cenario

    ao_meio_dia = _fechamento(http, usina)["horas_possiveis"]

    energia.agora_na_usina = lambda: datetime(2026, 8, 14, 18, 0, 0)
    ao_anoitecer = _fechamento(http, usina)["horas_possiveis"]

    assert ao_meio_dia == 324.0
    assert ao_anoitecer == 336.0


def test_parada_sem_duracao_calculada_deixa_as_horas_em_travessao(cenario):
    """⛔ Regra 0. `duration_minutes` vem nulo quando o monitoramento não tem janela solar
    para calcular. Somar só as paradas que têm duração faria a conta parecer MENOR do que
    foi — a mesma régua de `api/v1/paradas.py` (`_soma_se_todas`).

    O total sai em travessão e a resposta diz por quê (`eventos_sem_duracao`), em vez de
    publicar um número curto que ninguém consegue auditar.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [
        _alerta(1, duracao_min=120.0),
        _alerta(2, dia=6, duracao_min=None),
    ]

    c = _fechamento(http, usina)

    assert c["horas_paradas"] is None
    assert c["eventos_sem_duracao"] == 1
    assert c["horas_possiveis"] == 324.0, "o denominador não depende das paradas"


# ── o porquê: causas e eventos ───────────────────────────────────────────────


def test_as_causas_agrupam_por_motivo_e_a_soma_nao_excede_a_perda(cenario):
    """O ranking de causas é o que dá lastro à disponibilidade contratual.

    Sem ele o portal publica `99,1 % contratual` sem nenhuma justificativa ao lado — e a
    contratual é justamente a que desconta a causa externa. A soma das causas não pode
    ultrapassar a perda do monitoramento: ultrapassar significaria contar duas vezes a
    mesma energia (a parada que atravessa a virada do mês, tipicamente).
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [
        _alerta(1, dia=5, perda_kwh=60.0),
        _alerta(2, dia=6, perda_kwh=50.0),
        _alerta(
            3, dia=7, perda_kwh=20.0, motivo="Falha de comunicação",
            origem="Interna", externa=False,
        ),
    ]

    c = _fechamento(http, usina)

    assert c["paradas_origem"] == "alertas" and c["causas_origem"] == "alertas"
    assert [(x["categoria"], x["eventos"], x["energia_kwh"]) for x in c["causas"]] == [
        ("Falta de energia da concessionária", 2, 110.0),
        ("Falha de comunicação", 1, 20.0),
    ]
    assert c["causas"][0]["externa"] is True and c["causas"][1]["externa"] is False
    assert c["causas_total_kwh"] == 130.0
    assert c["causas_total_kwh"] <= c["perdida_kwh"] == 140.0


def test_parada_sem_classificacao_aparece_como_tal_e_nao_e_diluida(cenario):
    """Energia sem explicação tem de continuar visível.

    Distribuir a parada não classificada entre as causas conhecidas — ou omiti-la — faria
    o ranking parecer completo quando não é, e esconderia justamente o trabalho que falta
    à equipe. `causa` nula é ausência; a categoria diz o nome dela.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [
        _alerta(1, dia=5, perda_kwh=60.0),
        _alerta(2, dia=6, perda_kwh=25.0, motivo=None, origem=None, externa=False),
    ]

    c = _fechamento(http, usina)

    naoclassificada = [x for x in c["causas"] if x["categoria"] == "Não classificada"]
    assert len(naoclassificada) == 1
    assert naoclassificada[0]["classificada"] is False
    assert naoclassificada[0]["energia_kwh"] == 25.0
    assert [e for e in c["eventos"] if e["causa"] is None][0]["classificada"] is False


def test_a_parada_que_atravessa_o_mes_entra_so_com_o_pedaco_daqui(cenario):
    """`daily_losses` são as fatias por dia BRT do motor de perdas do meuWatt.

    Sem usá-las, uma parada iniciada em 31/07 e resolvida em 02/08 despejaria a perda
    INTEIRA num dos dois meses — e a soma das causas passaria da perda do monitoramento,
    que é o invariante do teste anterior. Aqui só os 40 kWh de agosto entram; os 90 de
    julho ficam em julho.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [
        _alerta(
            1,
            dia=1,
            perda_kwh=130.0,
            fatias=[
                {"d": "2026-07-31", "kwh": 90.0},
                {"d": "2026-08-01", "kwh": 40.0},
            ],
        )
    ]

    c = _fechamento(http, usina)

    assert c["eventos"][0]["energia_kwh"] == 40.0
    assert c["causas_total_kwh"] == 40.0


def test_so_o_agrupamento_persistido_do_meuwatt_junta_linhas(cenario):
    """⛔ O defeito guardado: inventar um segundo detector de paradas.

    O agrupamento por escopo (usina / skid / inversor) do meuWatt mora no front dele e nos
    endpoints `/shadow-breakdowns`, que respondem 403 ao nosso token de serviço. Replicá-lo
    aqui criaria um segundo detector, que divergiria do primeiro na primeira mudança de
    regra — e o cliente veria duas contagens de paradas para o mesmo mês.

    O único agrupamento que atravessa é o `manual_group_id`: a equipe juntou as linhas à
    mão, e isso está PERSISTIDO no banco do meuWatt. Duas linhas com o mesmo grupo viram um
    evento de 2 inversores; a terceira, sem grupo, continua sozinha.
    """
    http, caixa, usina = cenario
    # Duas paradas do MESMO dia com grupo (a equipe as juntou) e duas do mesmo dia SEM
    # grupo. Só o primeiro par vira uma linha: qualquer regra inventada aqui — "mesmo dia",
    # "mesmo motivo", "mesma UC" — juntaria o segundo par também, e é isso que se guarda.
    caixa["cliente"].alertas_resposta = [
        _alerta(1, dia=5, grupo="g-77", perda_kwh=60.0, uc="UC Norte"),
        _alerta(2, dia=5, grupo="g-77", perda_kwh=40.0, uc="UC Sul"),
        _alerta(3, dia=9, hora=8, perda_kwh=20.0, uc="UC Norte"),
        _alerta(4, dia=9, hora=14, perda_kwh=10.0, uc="UC Norte"),
    ]

    c = _fechamento(http, usina)

    assert len(c["eventos"]) == 3, "só o par que a EQUIPE agrupou vira uma linha"
    juntas, sozinha, outra = c["eventos"]
    assert juntas["inversores_afetados"] == 2 and juntas["energia_kwh"] == 100.0
    assert juntas["horas"] == 4.0, "2 h de cada inversor — a régua soma por aparelho"
    assert sozinha["inversores_afetados"] == 1 and outra["inversores_afetados"] == 1
    assert (sozinha["inicio"], outra["inicio"]) == ("2026-08-09", "2026-08-09")
    # A limitação é DECLARADA na resposta, não deduzida pela tela: se um dia alguém
    # replicar o detector aqui, esta frase tem de mudar junto.
    assert "uma linha por parada" in c["eventos_agrupamento"].lower()


def test_degradacao_conta_a_energia_mas_nao_as_horas_paradas(cenario):
    """Degradação é o inversor PRODUZINDO abaixo dos pares — não é parada.

    Somar as horas dela às horas paradas diria que a usina esteve fora quando ela estava
    gerando, e é isso que o cliente lê no cartão de horas. A energia perdida, essa sim,
    conta: ela foi perdida do mesmo jeito.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [
        _alerta(1, dia=5, duracao_min=120.0, perda_kwh=60.0),
        _alerta(2, dia=6, kind="degradation", duracao_min=300.0, perda_kwh=15.0,
                motivo=None, origem=None, externa=False),
    ]

    c = _fechamento(http, usina)

    degradacao = [e for e in c["eventos"] if e["tipo"] == "degradacao"][0]
    assert degradacao["horas"] == 0.0 and degradacao["energia_kwh"] == 15.0
    assert c["horas_paradas"] == 2.0, "as 5 h de degradação não são horas paradas"
    assert [x["categoria"] for x in c["causas"] if x["eventos"] == 1 and x["horas"] == 0.0]


def test_parada_de_outro_mes_nao_entra_pelo_dia_de_inicio(cenario):
    """O recorte é o dia BRT de `started_at` — o mesmo critério de `api/v1/paradas.py`.

    A fonte de alertas não filtra por período (ela lista a usina inteira), então o corte é
    nosso. Duas telas do mesmo portal cortando por réguas diferentes fariam a mesma parada
    aparecer num mês e sumir do outro.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [
        _alerta(1, dia=5),
        {**_alerta(2), "started_at": "2026-07-20T12:00:00-03:00"},
        {**_alerta(3), "started_at": "2026-09-02T12:00:00-03:00"},
    ]

    c = _fechamento(http, usina)

    assert len(c["eventos"]) == 1 and c["eventos"][0]["inicio"] == "2026-08-05"


# ── regra 0: a ausência não vira zero ────────────────────────────────────────


def test_mes_sem_timeline_curada_responde_200_e_a_secao_nao_existe(cenario):
    """⛔ Regra 0. Mês que ninguém curou é ESTADO NORMAL, não erro nem seção vazia.

    O upstream devolve `show_in_report=false` com `milestones=[]`, e a decisão de produto
    do meuWatt atravessa: uma espinha de timeline desenhada em branco é pior que seção
    nenhuma. Nem 404, nem `exibir=true` com lista vazia.
    """
    http, caixa, usina = cenario
    caixa["cliente"].timeline_resposta = {
        "plant_id": 3, "year": 2026, "month": 8,
        "show_in_report": False, "milestones": [],
    }

    c = _fechamento(http, usina)

    assert c["timeline"] == {"exibir": False, "marcos": []}
    assert c["aviso"] is None, "mês sem curadoria não é dado faltando"


def test_a_timeline_curada_atravessa_na_ordem_do_autor(cenario):
    """A ordem do array é conteúdo AUTORAL: o editor do meuWatt reordena por setas e o
    servidor de lá não re-ordena por data. Reordenar aqui reescreveria a narrativa de quem
    esteve na usina."""
    http, caixa, usina = cenario
    caixa["cliente"].timeline_resposta = _timeline()

    c = _fechamento(http, usina)

    assert c["timeline"]["exibir"] is True
    assert [m["id"] for m in c["timeline"]["marcos"]] == ["m1", "m2"]
    assert c["timeline"]["marcos"][0]["tom"] == "parada"
    # Carimbo UTC do meuWatt convertido ao fuso da usina: 12:00Z = 09:00 na usina.
    assert c["timeline"]["marcos"][0]["em"].startswith("2026-08-05T09:00")
    assert c["timeline"]["marcos"][0]["grupo"] == "g1"


def test_mes_sem_consideracoes_devolve_nulo_e_nao_erro(cenario):
    """⛔ Regra 0. A caixa `dash:gerais` vazia é ausência — a seção some da tela.

    Devolver texto vazio faria a tela desenhar um bloco de fechamento em branco, que o
    cliente lê como "a equipe não teve nada a dizer" em vez de "ainda não escreveram".
    """
    http, caixa, usina = cenario
    caixa["cliente"].observacoes_resposta = []

    c = _fechamento(http, usina)

    assert c["consideracoes"] is None
    assert c["aviso"] is None


def test_as_consideracoes_trazem_o_autor_e_a_data_da_ultima_edicao(cenario):
    """A caixa é um DOCUMENTO do mês, não uma conversa: vale a mais recente, com quem
    escreveu e quando — é o que o meuWatt imprime ("Última edição por Fulano em dd/mm")."""
    http, caixa, usina = cenario
    caixa["cliente"].observacoes_resposta = [
        _observacao(corpo="rascunho antigo", atualizado="2026-09-01T10:00:00+00:00"),
        _observacao(atualizado="2026-09-02T14:30:00+00:00"),
        # Seção de operação — nunca é o fechamento do cliente.
        _observacao(secao="dash:paradas", corpo="conferir com o técnico do skid 2"),
    ]

    c = _fechamento(http, usina)

    assert c["consideracoes"]["texto"].startswith("Mês marcado por duas quedas")
    assert c["consideracoes"]["autor"] == "Diogo"
    assert c["consideracoes"]["em"].startswith("2026-09-02T11:30")
    assert "skid 2" not in json.dumps(c, ensure_ascii=False), (
        "as caixas de operação são conversa interna e não atravessam"
    )


def test_paradas_que_nao_vieram_nao_viram_zero_paradas(cenario):
    """⛔ Regra 0, a porta mais perigosa desta aba. Fonte fora do ar tem de dizer "não
    sei", não "não parou" — a segunda leitura absolve a manutenção de graça.

    A resposta continua 200 (a aba abre, com o resto), `paradas_origem` fica nulo e o
    aviso nomeia o que faltou. Contar `eventos: []` como "nenhuma parada" seria publicar
    um mês limpo por causa de um 500 alheio.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = RuntimeError("breakdowns/range respondeu 500")

    c = _fechamento(http, usina)

    assert c["paradas_origem"] is None and c["causas_origem"] is None
    assert c["eventos"] == [] and c["causas"] == []
    assert c["causas_total_kwh"] is None and c["causas_conferem"] is None
    assert c["horas_paradas"] is None
    assert "paradas classificadas" in c["aviso"]
    # O que NÃO depende das paradas continua de pé — a aba não some inteira.
    assert c["potencial_kwh"] == 9940.0


def test_usina_sem_medicao_no_mes_nao_publica_potencial_zero(cenario):
    """Mês sem medição não tem potencial: `0 kWh` se leria como "a usina não gerou nada",
    e a usina pode simplesmente não estar monitorada ainda naquele mês."""
    http, caixa, usina = cenario
    caixa["cliente"].relatorio = _range(days_with_data=0)

    c = _fechamento(http, usina)

    assert c["medido_inversores_kwh"] is None
    assert c["perdida_kwh"] is None
    assert c["potencial_kwh"] is None and c["potencial_vs_projeto_pct"] is None
    assert c["perda_pct"] is None and c["perda_base"] is None
    assert c["perda_origem"] is None


def test_a_divergencia_entre_as_duas_leituras_da_perda_sai_declarada(cenario):
    """Quando dois números respondem à mesma pergunta e não podem ser o mesmo, a tela diz
    de que janela cada um saiu — em vez de reescalar um pelo outro.

    Reescalar produziria um kWh que ninguém mediu (a casa proíbe número inventado) e
    apagaria a única pista de que a classificação das paradas está incompleta.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [_alerta(1, perda_kwh=60.0)]

    c = _fechamento(http, usina)

    assert c["perdida_kwh"] == 140.0 and c["causas_total_kwh"] == 60.0
    assert c["causas_conferem"] is False, "60 contra 140 não bate — e a resposta admite"
    assert c["perda_origem"] == "monitoramento" and c["causas_origem"] == "alertas"


# ── o que NÃO pode atravessar ────────────────────────────────────────────────


def test_nada_da_fabrica_de_pdf_atravessa(cenario):
    """⛔ O dono, por escrito: "quero os dashs do meuWatt SEM a opção de gerar PDF, mas com
    todas as informações".

    A capa (`report-branding`: logo, foto de capa, nome do cliente), a contracapa com QR
    code, o cabeçalho corrente e os ganchos de impressão são maquinário de folha A4 — não
    têm contraparte no painel e não devem ganhar uma. A tela Relatórios já entrega o
    documento fechado; republicá-lo aqui seria a terceira cópia do mesmo conteúdo, e a que
    envelhece.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [_alerta(1)]
    caixa["cliente"].observacoes_resposta = [_observacao()]
    caixa["cliente"].timeline_resposta = _timeline()

    cru = json.dumps(_fechamento(http, usina), ensure_ascii=False).lower()

    for proibido in ("branding", "capa", "qr", "pdf", "cover", "print"):
        assert proibido not in cru, f"maquinário de impressão vazou: {proibido!r}"


def test_o_recorte_das_paradas_acontece_no_cliente(cenario):
    """⛔ O recorte de PII mora no `MeuWattClient`, e não em quem chama — pelo mesmo motivo
    das faturas: *a PII não pode depender de cada chamador lembrar de descartá-la*.

    Este teste bate no cliente DIRETAMENTE porque o teste seguinte, que confere a resposta
    da rota, **passa mesmo sem o recorte**: o `RelatorioMesOut` já escolhe campo a campo, e
    a segunda cerca esconderia a queda da primeira. É defesa em profundidade — e quem tem
    duas cercas precisa de dois testes, senão só uma delas está de pé de verdade.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [_alerta(1)]

    import asyncio

    recortadas = asyncio.run(caixa["cliente"].paradas_classificadas("porto-ferreira"))

    assert set(recortadas[0]) == set(MeuWattClient.CAMPOS_DA_PARADA)
    for entranha in (
        "sn",
        "inverter_id",
        "model",
        "ordem_servico",
        "observacoes",
        "causa_raiz",
        "classified_by_name",
        "acknowledgement_note",
    ):
        assert entranha not in recortadas[0], f"o cliente deixou passar {entranha!r}"
    # E o que dá LASTRO ao número contratual continua vindo.
    assert recortadas[0]["motivo"] and recortadas[0]["is_external_cause"] is True


def test_a_ficha_de_trabalho_da_equipe_nao_chega_ao_dono(cenario):
    """⛔ A segunda cerca: nem o número de série, nem o `inverter_id`, nem a nota do
    operador ("cliente avisou por telefone; não repetir no relatório") podem aparecer na
    resposta da rota — mesmo que um dia alguém afrouxe o recorte do cliente.

    A `AlertDetail` do meuWatt é o registro de trabalho da EQUIPE. O dono da usina precisa
    do motivo e da classificação; o resto é conversa interna.
    """
    http, caixa, usina = cenario
    caixa["cliente"].alertas_resposta = [_alerta(1), _alerta(2, dia=9, grupo="g-1")]

    cru = json.dumps(_fechamento(http, usina), ensure_ascii=False)

    for entranha in (
        "SN2312090045",       # número de série do inversor
        "901",                # inverter_id
        "OS-4471",            # ordem de serviço interna
        "Religador",          # causa raiz — análise de equipe
        "não repetir",        # nota do operador
        "vi e liguei",        # acknowledgement_note
        "SUN2000",            # modelo do inversor
    ):
        assert entranha not in cru, f"entranha da equipe vazou: {entranha!r}"
    # E o que É do dono continua saindo.
    assert "UC Norte" in cru and "Falta de energia da concessionária" in cru


# ── contrato da rota ─────────────────────────────────────────────────────────


def test_a_aba_e_travada_no_mes_e_le_as_tres_fontes_novas(cenario):
    """Sem `recorte`: o fechamento narrativo de um ano não existe — considerações, timeline
    e classificação de parada são todas escritas mês a mês. E o `range` para em HOJE (no
    futuro ele fabrica dias vazios), enquanto o PVsyst vai até o fim do mês."""
    http, caixa, usina = cenario

    c = _fechamento(http, usina)

    chamadas = dict((x[0], x[1:]) for x in caixa["cliente"].chamadas)
    assert chamadas["range"] == (date(2026, 8, 1), HOJE)
    assert chamadas["pvsyst"] == (date(2026, 8, 1), date(2026, 8, 31))
    assert chamadas["observacoes"] == ("MENSAL", date(2026, 8, 1))
    assert chamadas["timeline"] == (2026, 8)
    assert chamadas["alertas"] == ("all",)
    assert c["rotulo"] == "Agosto / 2026"
    assert (c["inicio"], c["fim"]) == ("2026-08-01", "2026-08-31")
    assert c["em_curso"] is True and c["dia_de_corte"] == 14
    assert "recorte" not in c


def test_sem_ponte_com_o_monitoramento_a_aba_abre_vazia_e_diz_o_motivo(cenario):
    """Nunca 5xx por causa do upstream: a aba abre com os campos nulos e o aviso. Um 500
    aqui derrubaria a página inteira do cliente por causa de uma credencial fora do ar."""
    http, _, usina = cenario

    async def _sem_ponte(_db):
        raise RuntimeError("credencial de serviço do meuWatt recusada")

    energia.integracoes.cliente_meuwatt = _sem_ponte
    c = _fechamento(http, usina)

    assert c["potencial_kwh"] is None and c["causas"] == []
    assert c["timeline"] == {"exibir": False, "marcos": []}
    assert c["consideracoes"] is None
    assert "Monitoramento indisponível" in c["aviso"]
    assert c["regra"]["potencial"].startswith("Energia potencial =")


def test_usina_fora_do_escopo_do_usuario_e_404(cenario):
    """O escopo é o mesmo do painel: a aba nova não pode ser a porta larga."""
    http, _, _ = cenario

    r = http.get("/api/v1/energia/usinas/2/relatorio-mes?referencia=2026-08-14")

    assert r.status_code == 404
