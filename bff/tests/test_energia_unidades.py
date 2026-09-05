"""Comparativo entre unidades consumidoras — `GET /api/v1/energia/usinas/{id}/unidades`.

A UC do meuWatt é o TRANSFORMADOR. Aqui ela chega ao cliente identificada por **nome** e
por um **índice estável da resposta**: o `transformer_id` é chave interna do produto de
origem e não atravessa — há um teste que varre o JSON atrás dele e atrás dos seriais.

O resto é regra 0 na coluna que mais tenta: UC sem PR pareado sai `null` e não 0% (0%
se lê "a usina não está performando"), e mês sem fatura sai `null` com situação nula —
fatura ainda não emitida é estado, não erro.
"""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import energia
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess
from tests.test_energia_dia import ClienteFalso, _inversor

HOJE = date(2026, 8, 14)


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


def _serie(dias: dict[str, float]) -> list[dict]:
    return [{"t": d, "y": v} for d, v in sorted(dias.items())]


def _transformador(tid: int, nome: str, kwh: float, **extra) -> dict:
    base = {
        "id": tid,
        "name": nome,
        "inverter_count": 2,
        "total_yield_kwh": kwh,
        "total_capacity_kwp": 200.0,
        "productivity": round(kwh / 200.0, 2),
        "performance_ratio": 0.81,
        "availability_real_pct": 98.2,
        "availability_contratual_pct": 99.1,
        "total_expected_kwh": kwh * 1.02,
        "total_lost_kwh": kwh * 0.02,
        "total_lost_externa_kwh": 0.0,
        "daily_generation": _serie(
            {"2026-08-01": kwh * 0.5, "2026-08-02": kwh * 0.5}
        ),
    }
    base.update(extra)
    return base


def _range(**extra) -> dict:
    """Duas UCs de tamanhos diferentes — para o share e os rankings terem ordem."""
    base = {
        "plant": "Porto Ferreira",
        "start_date": "2026-08-01",
        "end_date": "2026-08-14",
        "days_in_range": 14,
        "days_with_data": 14,
        "total_generation_kwh": 100_000.0,
        "total_capacity_kwp": 400.0,
        "productivity": 250.0,
        "performance_ratio": 0.812,
        "irradiation": {"hpoa": 70.0, "hghi": 65.0},
        "has_fault_data": True,
        "availability_real_pct": 98.2,
        "availability_contratual_pct": 99.1,
        "inverters": [
            _inversor("SN-A1", 1, "SKID 01", 30_000.0, total_yield_kwh=30_000.0),
            _inversor("SN-A2", 1, "SKID 01", 30_000.0, total_yield_kwh=30_000.0),
            _inversor("SN-B1", 2, "SKID 02", 20_000.0, total_yield_kwh=20_000.0),
            _inversor("SN-B2", 2, "SKID 02", 20_000.0, total_yield_kwh=20_000.0),
        ],
        "transformers": [
            _transformador(1, "SKID 01", 60_000.0, performance_ratio=0.83),
            _transformador(2, "SKID 02", 40_000.0, performance_ratio=0.78),
        ],
        "availability": [],
        "summary": {"total_lost_kwh": 2000.0},
        "monthly_summaries": [],
        "daily_summaries": [],
        "alert_timeline": [],
        "chart_data": {},
    }
    base.update(extra)
    return base


def _fatura(tid: int, mes: int, mwh: float | None, ano: int = 2026) -> dict:
    return {
        "id": tid * 100 + mes,
        "transformer_id": tid,
        "year": ano,
        "month": mes,
        "billed_mwh": mwh,
        "installation_number": "123456",
        "tariff": "Verde",
        "titular": None,
        "pdf_filename": None,
        "pdf_mime_type": None,
        "pdf_size_bytes": None,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=minha.id))
    db.commit()

    caixa = {"cliente": ClienteFalso(range_=_range())}

    async def _cliente(_db):
        return caixa["cliente"]

    monkeypatch.setattr(energia.integracoes, "cliente_meuwatt", _cliente)
    monkeypatch.setattr(energia, "hoje_na_usina", lambda: HOJE)

    http = TestClient(_aplicacao(db))
    token, _ = criar_token(dono.id)
    http.headers["Authorization"] = f"Bearer {token}"
    yield http, caixa, minha


def _pedir(http, usina, consulta: str = "recorte=mes&referencia=2026-08-14") -> dict:
    r = http.get(f"/api/v1/energia/usinas/{usina.id}/unidades?{consulta}")
    assert r.status_code == 200, r.text
    return r.json()


# ── o caminho feliz ──────────────────────────────────────────────────────────


def test_os_numeros_do_periodo_e_o_maior_contribuinte(cenario):
    http, _, usina = cenario

    c = _pedir(http, usina)

    assert c["recorte"] == "mes"
    assert (c["inicio"], c["fim"]) == ("2026-08-01", "2026-08-14")
    assert c["ucs_ativas"] == 2
    assert c["capacidade_total_kwp"] == 400.0
    assert c["energia_periodo_kwh"] == 100_000.0
    assert c["maior"] == {"nome": "SKID 01", "share_pct": 60.0}
    assert c["pr_referencia_pct"] == 80.0
    assert c["aviso"] is None


def test_a_tabela_por_uc_traz_geracao_share_capacidade_e_desempenho(cenario):
    http, _, usina = cenario

    ucs = _pedir(http, usina)["ucs"]

    assert [u["indice"] for u in ucs] == [0, 1]
    primeira = ucs[0]
    assert primeira["nome"] == "SKID 01"
    assert primeira["geracao_kwh"] == 60_000.0
    assert primeira["share_pct"] == 60.0
    assert primeira["capacidade_kwp"] == 200.0
    assert primeira["inversores"] == 2
    assert primeira["produtividade"] == 300.0
    assert primeira["pr_pct"] == 83.0, "PR chega como razão 0–1 e sai em %"
    assert primeira["disponibilidade_real_pct"] == 98.2
    assert primeira["disponibilidade_contratual_pct"] == 99.1
    assert sum(u["share_pct"] for u in ucs) == 100.0


def test_o_periodo_para_em_hoje_e_nao_no_fim_do_mes(cenario):
    """O `range` fabrica dias vazios no futuro, e eles entrariam na série diária por UC
    como buracos que não existem."""
    http, caixa, usina = cenario

    _pedir(http, usina)

    assert ("range", date(2026, 8, 1), HOJE) in caixa["cliente"].chamadas


def test_os_tres_rankings_saem_prontos_do_servidor(cenario):
    http, _, usina = cenario

    c = _pedir(http, usina)

    assert c["ranking_geracao"] == [0, 1]
    assert c["ranking_pr"] == [0, 1]
    assert c["ranking_produtividade"] == [0, 1]


def test_a_serie_diaria_por_uc_vem_alinhada_nos_mesmos_dias(cenario):
    http, _, usina = cenario

    c = _pedir(http, usina)

    assert c["serie_dias"] == ["2026-08-01", "2026-08-02"]
    assert [s["nome"] for s in c["serie"]] == ["SKID 01", "SKID 02"]
    assert c["serie"][0]["valores"] == [30_000.0, 30_000.0]
    for s in c["serie"]:
        assert len(s["valores"]) == len(c["serie_dias"])


def test_dia_sem_leitura_da_uc_vira_lacuna_na_serie(cenario):
    http, caixa, usina = cenario
    relatorio = _range()
    relatorio["transformers"][1]["daily_generation"] = _serie({"2026-08-01": 40_000.0})
    caixa["cliente"] = ClienteFalso(range_=relatorio)

    c = _pedir(http, usina)

    assert c["serie_dias"] == ["2026-08-01", "2026-08-02"]
    assert c["serie"][1]["valores"] == [40_000.0, None]


# ── uma UC só ────────────────────────────────────────────────────────────────


def test_usina_de_uma_uc_devolve_uma_linha_com_share_de_cem_por_cento(cenario):
    http, caixa, usina = cenario
    relatorio = _range(
        total_generation_kwh=60_000.0,
        transformers=[_transformador(1, "SKID ÚNICO", 60_000.0)],
        inverters=[
            _inversor("SN-A1", 1, "SKID ÚNICO", 30_000.0, total_yield_kwh=30_000.0),
            _inversor("SN-A2", 1, "SKID ÚNICO", 30_000.0, total_yield_kwh=30_000.0),
        ],
    )
    caixa["cliente"] = ClienteFalso(range_=relatorio)

    c = _pedir(http, usina)

    assert c["ucs_ativas"] == 1
    assert len(c["ucs"]) == 1
    assert c["ucs"][0]["share_pct"] == 100.0
    assert c["maior"] == {"nome": "SKID ÚNICO", "share_pct": 100.0}


# ── regra 0 ──────────────────────────────────────────────────────────────────


def test_uc_sem_pr_sai_nula_e_fica_de_fora_do_ranking_de_pr(cenario):
    """0% se lê 'a usina não está performando'. Ausente é ausente."""
    http, caixa, usina = cenario
    relatorio = _range()
    relatorio["transformers"][1]["performance_ratio"] = None
    caixa["cliente"] = ClienteFalso(range_=relatorio)

    c = _pedir(http, usina)

    assert c["ucs"][1]["pr_pct"] is None
    assert c["ranking_pr"] == [0], "quem não tem o número não entra no ranking"
    assert c["ranking_geracao"] == [0, 1], "e continua na tabela e nos outros rankings"


def test_uc_sem_disponibilidade_sai_nula(cenario):
    http, caixa, usina = cenario
    relatorio = _range()
    relatorio["transformers"][0]["availability_real_pct"] = None
    relatorio["transformers"][0]["availability_contratual_pct"] = None
    caixa["cliente"] = ClienteFalso(range_=relatorio)

    c = _pedir(http, usina)

    assert c["ucs"][0]["disponibilidade_real_pct"] is None
    assert c["ucs"][0]["disponibilidade_contratual_pct"] is None


def test_inversor_sem_transformador_aparece_em_sem_uc(cenario):
    http, caixa, usina = cenario
    relatorio = _range(total_generation_kwh=110_000.0)
    relatorio["inverters"].append(
        _inversor("SN-ORFAO", None, None, 10_000.0, total_yield_kwh=10_000.0)
    )
    caixa["cliente"] = ClienteFalso(range_=relatorio)

    c = _pedir(http, usina)

    assert [u["nome"] for u in c["ucs"]] == ["SKID 01", "SKID 02", "Sem UC"]
    orfa = c["ucs"][2]
    assert orfa["geracao_kwh"] == 10_000.0
    assert orfa["capacidade_kwp"] == 100.0
    assert abs(sum(u["geracao_kwh"] for u in c["ucs"]) - c["energia_periodo_kwh"]) < 0.01


def test_uc_sem_energia_pronta_soma_pelos_inversores_dela(cenario):
    """Mesma régua do recorte do dia, e de propósito: a soma pelos membros mora dentro do
    agrupamento por UC, que serve aos dois — duas contas para o mesmo número divergiriam
    com o tempo. Aqui ela também sustenta o share, que sai da participação de cada UC."""
    http, caixa, usina = cenario
    relatorio = _range()
    relatorio["transformers"][0].pop("total_yield_kwh")
    caixa["cliente"] = ClienteFalso(range_=relatorio)

    c = _pedir(http, usina)

    assert c["ucs"][0]["geracao_kwh"] == 60_000.0, "30.000 + 30.000 da SKID 01"
    assert c["ucs"][0]["share_pct"] == 60.0
    assert c["energia_periodo_kwh"] == 100_000.0


# ── a conta de energia ───────────────────────────────────────────────────────


def test_a_fatura_do_periodo_entra_por_uc(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        range_=_range(),
        faturas=[_fatura(1, 8, 58.4), _fatura(2, 8, 39.1), _fatura(1, 7, 61.0)],
    )

    c = _pedir(http, usina)

    assert c["ucs"][0]["faturado_mwh"] == 58.4
    assert c["ucs"][1]["faturado_mwh"] == 39.1, "julho ficou de fora do mês de agosto"
    assert c["faturas_situacao"] == "Emitida"


def test_mes_sem_fatura_sai_nulo_e_com_situacao_nula(cenario):
    """Fatura ainda não emitida é estado, não erro — e nunca 0 MWh."""
    http, _, usina = cenario

    c = _pedir(http, usina)

    assert [u["faturado_mwh"] for u in c["ucs"]] == [None, None]
    assert c["faturas_situacao"] is None
    assert c["aviso"] is None


def test_fatura_de_parte_das_ucs_e_declarada_como_parcial(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(range_=_range(), faturas=[_fatura(1, 8, 58.4)])

    c = _pedir(http, usina)

    assert c["ucs"][0]["faturado_mwh"] == 58.4
    assert c["ucs"][1]["faturado_mwh"] is None
    assert c["faturas_situacao"] == "Parcial"


def test_conta_de_energia_fora_do_ar_nao_derruba_o_comparativo(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(range_=_range(), faturas=RuntimeError("500"))

    c = _pedir(http, usina)

    assert c["ucs_ativas"] == 2
    assert [u["faturado_mwh"] for u in c["ucs"]] == [None, None]
    assert c["faturas_situacao"] is None


# ── a barreira ───────────────────────────────────────────────────────────────


def test_o_corpo_nao_carrega_serial_nem_id_de_transformador(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(range_=_range(), faturas=[_fatura(1, 8, 58.4)])

    corpo = http.get(
        f"/api/v1/energia/usinas/{usina.id}/unidades?recorte=mes&referencia=2026-08-14"
    ).text

    for serial in ("SN-A1", "SN-A2", "SN-B1", "SN-B2"):
        assert serial not in corpo
    for chave in ("transformer_id", "serial_number", "\"sn\"", "installation_number"):
        assert chave not in corpo


# ── degradação e escopo ──────────────────────────────────────────────────────


def test_recorte_ano_pede_o_ano_inteiro_ate_hoje(cenario):
    http, caixa, usina = cenario

    c = _pedir(http, usina, "recorte=ano&referencia=2026-08-14")

    assert (c["inicio"], c["fim"]) == ("2026-01-01", "2026-08-14")
    assert ("range", date(2026, 1, 1), HOJE) in caixa["cliente"].chamadas


def test_a_conta_de_energia_e_pedida_pelo_ano_do_periodo(cenario):
    """Mês e ano cabem sempre num ano civil. Sem o ano no pedido o upstream devolve o
    histórico inteiro de faturas para o BFF recortar um ano dele."""
    http, caixa, usina = cenario

    _pedir(http, usina)

    assert ("faturas", 2026) in caixa["cliente"].chamadas


def test_recorte_invalido_e_recusado(cenario):
    http, _, usina = cenario

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/unidades?recorte=semana")

    assert r.status_code == 400


def test_monitoramento_fora_do_ar_vira_aviso_e_nao_zeros(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(range_=RuntimeError("502"))

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/unidades?referencia=2026-08-14")

    assert r.status_code == 200
    c = r.json()
    assert c["ucs"] == [] and c["energia_periodo_kwh"] is None
    assert c["ucs_ativas"] == 0
    assert "Monitoramento indisponível" in c["aviso"]


def test_usina_sem_uc_cadastrada_diz_isso_em_vez_de_tela_em_branco(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(range_=_range(transformers=[], inverters=[]))

    c = _pedir(http, usina)

    assert c["ucs"] == []
    assert "não devolveu unidades consumidoras" in c["aviso"]


def test_usina_fora_do_escopo_devolve_404(cenario):
    http, _, _ = cenario

    assert http.get("/api/v1/energia/usinas/999/unidades").status_code == 404
