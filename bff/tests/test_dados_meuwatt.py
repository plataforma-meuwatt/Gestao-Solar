"""O que o BFF publica quando o meuWatt responde — com o payload que ele de fato responde.

Este arquivo existe porque a auditoria apontou algo que era verdade: os testes de `_tom`
construíam a `UsinaOut` **à mão**, já com o valor que se queria afirmar. Isso testa a régua
de cor e não testa **a decisão de publicar ou anular o número**, que é onde os defeitos
estavam. Um teste que monta `disponibilidade_pct=None` e depois verifica que é `None` é
uma tautologia.

Aqui os payloads são os que `build_monitoring_snapshot` e `build_daily_report` produzem,
inclusive nos dois estados em que o upstream fabrica número sem lastro:

- **amanhecer**: linhas sintetizadas com `daily_yield_kwh = 0.0` e sem expectativa, que o
  cálculo transforma em disponibilidade **0.0** com peso cheio;
- **usina muda**: linhas com `is_communicating: False`, puladas do denominador, que fazem
  o campo sair **100.0**.

Nos dois casos o número não tem base, e o certo é não publicá-lo.
"""

import asyncio
from datetime import date

from app.api.v1.plants import UsinaOut, _dados_meuwatt, _tom
from app.models.plant import PlantLink


class ClienteFalso:
    """Responde o que o mw-api responderia, sem rede."""

    def __init__(self, agora: dict, diario: dict):
        self._agora = agora
        self._diario = diario

    async def monitoramento_atual(self, slug: str) -> dict:
        return self._agora

    async def geracao_diaria(self, slug: str, dia: date) -> dict:
        return self._diario


def _link() -> PlantLink:
    return PlantLink(id=1, nome="Usina Teste", mw_plant_slug="usina-teste", kwp=None)


def _colher(agora: dict, diario: dict) -> dict:
    return asyncio.run(_dados_meuwatt(ClienteFalso(agora, diario), _link(), date(2026, 8, 14)))


def _como_usina(dados: dict) -> UsinaOut:
    u = UsinaOut(
        id=1,
        nome="Usina Teste",
        tom="",
        situacao="",
        tem_meuwatt=True,
        tem_meuplano=False,
        potencia_kw=dados.get("potencia_kw"),
        disponibilidade_pct=dados.get("disponibilidade_pct"),
        sem_comunicacao=bool(dados.get("sem_comunicacao")),
        inversores_mudos=dados.get("inversores_mudos"),
        inversores_parados=dados.get("inversores_parados"),
        inversores_alerta=dados.get("inversores_alerta"),
        fora_da_janela_solar=bool(dados.get("fora_da_janela_solar")),
    )
    u.tom, u.situacao = _tom(u)
    return u


# ── amanhecer: o relatório do dia ainda não chegou ──────────────────────────

AMANHECER_AGORA = {
    "in_solar_window": True,
    "inverters": [
        {"id": "slot-1", "status": "normal", "active_power": 4_000.0, "capacity_kwp": 600.0,
         "timestamp": "2026-08-14T09:10:00Z", "down": False},
        {"id": "slot-2", "status": "normal", "active_power": 4_100.0, "capacity_kwp": 600.0,
         "timestamp": "2026-08-14T09:10:00Z", "down": False},
    ],
}
#: Como `build_daily_report` sintetiza os slots que ainda não reportaram: rendimento zero,
#: sem expectativa, e `plant_availability_pct` já calculado em 0.0 com peso cheio.
AMANHECER_DIARIO = {
    "total_generation_kwh": 0.0,
    "total_capacity_kwp": 1200.0,
    "plant_availability_pct": 0.0,
    "inverters": [
        {"sn": "A1", "daily_yield_kwh": 0.0, "expected_yield_kwh": None,
         "is_communicating": True, "diagnosis": "NO_REPORT"},
        {"sn": "A2", "daily_yield_kwh": 0.0, "expected_yield_kwh": None,
         "is_communicating": True, "diagnosis": "NO_REPORT"},
    ],
}


def test_ao_amanhecer_a_disponibilidade_nao_e_publicada():
    """O zero fabricado não sai do BFF.

    Reproduzido pela auditoria executando o código: usina intacta, gerando 8,1 kW, saía
    com `disponibilidade_pct = 0.0` — que virava faixa "com problema" com o NOME da usina
    na tela mais visível do aplicativo, todo amanhecer.
    """
    dados = _colher(AMANHECER_AGORA, AMANHECER_DIARIO)

    assert dados["disponibilidade_pct"] is None, "0.0 sem expectativa é número sem lastro"


def test_usina_intacta_ao_amanhecer_nao_ganha_faixa():
    """O circuito inteiro: payload real → `_dados_meuwatt` → `_tom`."""
    u = _como_usina(_colher(AMANHECER_AGORA, AMANHECER_DIARIO))

    assert u.tom == "ok", f"usina saudável marcada como {u.tom!r}: {u.situacao!r}"
    assert u.potencia_kw == 8.1, "a potência real continua sendo publicada"


# ── usina muda: ninguém comunicando ─────────────────────────────────────────

MUDA_AGORA = {
    "in_solar_window": True,
    "inverters": [
        {"id": "slot-1", "status": "communication_error", "active_power": 300_000.0,
         "capacity_kwp": 600.0, "timestamp": "2026-08-14T12:00:00Z"},
        {"id": "slot-2", "status": "communication_error", "active_power": 290_000.0,
         "capacity_kwp": 600.0, "timestamp": "2026-08-14T12:00:00Z"},
    ],
}
#: Linhas puladas do denominador ⇒ `avail_weight_total == 0` ⇒ o upstream devolve 100.0.
MUDA_DIARIO = {
    "total_generation_kwh": 0.0,
    "total_capacity_kwp": 1200.0,
    "plant_availability_pct": 100.0,
    "inverters": [
        {"sn": "A1", "daily_yield_kwh": 0.0, "expected_yield_kwh": 0.0,
         "is_communicating": False, "diagnosis": "NO_COMMUNICATION"},
        {"sn": "A2", "daily_yield_kwh": 0.0, "expected_yield_kwh": 0.0,
         "is_communicating": False, "diagnosis": "NO_COMMUNICATION"},
    ],
}


def test_usina_muda_nao_publica_cem_por_cento():
    """O outro número sem lastro. "Energia hoje 0,0 kWh · disponibilidade 100%" é uma
    contradição apresentada com a maior tranquilidade possível."""
    dados = _colher(MUDA_AGORA, MUDA_DIARIO)

    assert dados["disponibilidade_pct"] is None
    assert dados["sem_comunicacao"] is True


def test_usina_muda_nao_publica_a_potencia_velha():
    """O mw-api mantém o `active_power` da última leitura ao marcar
    `communication_error`. Somá-lo publicaria a potência do meio-dia às três da tarde."""
    dados = _colher(MUDA_AGORA, MUDA_DIARIO)

    assert dados["potencia_kw"] is None

    u = _como_usina(dados)
    assert u.tom == "semDados"
    assert u.situacao == "Sem comunicação"


# ── dia normal: tudo com lastro ─────────────────────────────────────────────


def test_dia_normal_publica_tudo():
    """A correção não pode ter emudecido o caso bom: com expectativa medida e inversores
    comunicando, o número sai."""
    agora = {
        "in_solar_window": True,
        "inverters": [
            {"id": "slot-1", "status": "normal", "active_power": 500_000.0,
             "capacity_kwp": 600.0, "timestamp": "2026-08-14T13:00:00Z", "down": False},
        ],
    }
    diario = {
        "total_generation_kwh": 3_200.0,
        "total_capacity_kwp": 600.0,
        "plant_availability_pct": 97.4,
        "inverters": [
            {"sn": "A1", "daily_yield_kwh": 3_200.0, "expected_yield_kwh": 3_280.0,
             "is_communicating": True},
        ],
    }

    dados = _colher(agora, diario)

    assert dados["disponibilidade_pct"] == 97.4
    assert dados["potencia_kw"] == 500.0
    assert dados["energia_hoje_kwh"] == 3_200.0
    assert _como_usina(dados).tom == "ok"


def test_zero_de_geracao_com_expectativa_e_zero_honesto():
    """Dia fechado, com expectativa medida e usina comunicando: zero é informação, e tem
    de sobreviver. A correção anula o zero SEM lastro, não todo zero."""
    agora = {
        "in_solar_window": True,
        "inverters": [
            {"id": "slot-1", "status": "normal", "active_power": 0.0,
             "capacity_kwp": 600.0, "timestamp": "2026-08-14T13:00:00Z", "down": False},
        ],
    }
    diario = {
        "total_generation_kwh": 0.0,
        "total_capacity_kwp": 600.0,
        "plant_availability_pct": 0.0,
        "inverters": [
            {"sn": "A1", "daily_yield_kwh": 0.0, "expected_yield_kwh": 2_800.0,
             "is_communicating": True},
        ],
    }

    dados = _colher(agora, diario)

    assert dados["energia_hoje_kwh"] == 0.0, "zero medido é zero"
    assert dados["disponibilidade_pct"] == 0.0, "com expectativa real, o zero tem lastro"
