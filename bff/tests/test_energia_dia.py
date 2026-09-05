"""A operação do dia — `GET /api/v1/energia/usinas/{id}/dia`.

O que se protege aqui é a promessa de que a agregação por unidade consumidora acontece no
servidor: o navegador do cliente recebe a soma por UC e uma faísca de 15 em 15 minutos, e
nunca a série por inversor. Por consequência, **nem número de série nem id de
transformador podem aparecer no corpo** — há um teste que varre o JSON inteiro atrás
deles.

O resto é regra 0 na sua forma mais tentadora: bucket sem leitura não vira zero, dia sem
incidente é uma lista vazia (e não um erro), e a soma das UCs tem de fechar com a geração
da usina — inclusive quando um inversor não tem transformador cadastrado.

Os payloads são os que `generation/daily` e `charts/intraday` devolvem de fato.
"""

import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import energia
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

HOJE = date(2026, 8, 14)
DIA = "2026-08-14"


def _aplicacao(db) -> FastAPI:
    """Só o router sob teste, com o banco do teste — a mesma postura de
    `test_desempenho`: um router alheio quebrado no meio de uma edição não pode derrubar
    os testes de energia."""
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


def _inversor(sn: str, tid: int | None, tnome: str | None, kwh: float, **extra) -> dict:
    base = {
        "id": abs(hash(sn)) % 10_000,
        "sn": sn,
        "slot_label": None,
        "model": "SUN2000",
        "capacity_kwp": 100.0,
        "daily_yield_kwh": kwh,
        "is_faulty": False,
        "is_removed": False,
        "installed_at": None,
        "deleted_at": None,
        "transformer_id": tid,
        "transformer_name": tnome,
    }
    base.update(extra)
    return base


def _diario(**extra) -> dict:
    """Duas UCs, dois inversores cada. Energia da usina = soma das UCs."""
    base = {
        "plant": "Porto Ferreira",
        "date": DIA,
        "total_generation_kwh": 4000.0,
        "total_capacity_kwp": 400.0,
        "productivity": 10.0,
        "performance_ratio": 0.812,
        "pr_flag": None,
        "pr_raw": None,
        "irradiation": {"hpoa": 5.4, "hghi": 5.0},
        "has_fault_data": True,
        "inverters": [
            _inversor("SN-A1", 1, "SKID 01", 1100.0, slot_label="INV 1"),
            _inversor("SN-A2", 1, "SKID 01", 900.0),
            _inversor("SN-B1", 2, "SKID 02", 1200.0),
            _inversor("SN-B2", 2, "SKID 02", 800.0),
        ],
        "transformers": [
            {
                "id": 1,
                "name": "SKID 01",
                "inverter_count": 2,
                "total_yield_kwh": 2000.0,
                "total_capacity_kwp": 200.0,
            },
            {
                "id": 2,
                "name": "SKID 02",
                "inverter_count": 2,
                "total_yield_kwh": 2000.0,
                "total_capacity_kwp": 200.0,
            },
        ],
        "alert_timeline": [],
        "availability": [],
        "plant_availability_pct": 100.0,
        "availability_real_pct": 98.2,
        "availability_contratual_pct": 99.1,
        "pending_classification_count": 0,
        "uptime": [],
        "plant_uptime_pct": 100.0,
        "solar_window": None,
        "summary": {"total_lost_kwh": 60.0},
    }
    base.update(extra)
    return base


def _intraday(pontos: list[dict] | None = None) -> dict:
    if pontos is None:
        pontos = [
            {
                "time": "09:00",
                "ghi": 500.0,
                "poa": 540.0,
                "inverters": [
                    {"serial_number": "SN-A1", "power_kw": 60.0},
                    {"serial_number": "SN-A2", "power_kw": 50.0},
                    {"serial_number": "SN-B1", "power_kw": 70.0},
                    {"serial_number": "SN-B2", "power_kw": 40.0},
                ],
            },
            {
                "time": "09:05",
                "ghi": 520.0,
                "poa": 560.0,
                "inverters": [
                    {"serial_number": "SN-A1", "power_kw": 80.0},
                    {"serial_number": "SN-A2", "power_kw": 70.0},
                    {"serial_number": "SN-B1", "power_kw": 90.0},
                    {"serial_number": "SN-B2", "power_kw": 60.0},
                ],
            },
            {
                "time": "09:20",
                "ghi": 600.0,
                "poa": 640.0,
                "inverters": [
                    {"serial_number": "SN-A1", "power_kw": 90.0},
                    {"serial_number": "SN-A2", "power_kw": 85.0},
                    {"serial_number": "SN-B1", "power_kw": 95.0},
                    {"serial_number": "SN-B2", "power_kw": 80.0},
                ],
            },
        ]
    return {
        "plant": "Porto Ferreira",
        "date": DIA,
        "total_capacity_kwp": 400.0,
        "points": pontos,
    }


class ClienteFalso:
    """O meuWatt sem rede. Qualquer resposta pode ser uma exceção a lançar."""

    def __init__(self, diario=None, intraday=None, range_=None, faturas=None):
        self.diario_resposta = diario if diario is not None else _diario()
        self.intraday_resposta = intraday if intraday is not None else _intraday()
        self.range_resposta = range_ if range_ is not None else {}
        self.faturas_resposta = faturas if faturas is not None else []
        self.chamadas: list[tuple] = []

    async def geracao_diaria(self, slug, dia):
        self.chamadas.append(("daily", dia))
        if isinstance(self.diario_resposta, BaseException):
            raise self.diario_resposta
        return self.diario_resposta

    async def intraday(self, slug, dia=None):
        self.chamadas.append(("intraday", dia))
        if isinstance(self.intraday_resposta, BaseException):
            raise self.intraday_resposta
        return self.intraday_resposta

    async def geracao_periodo(self, slug, inicio, fim):
        self.chamadas.append(("range", inicio, fim))
        if isinstance(self.range_resposta, BaseException):
            raise self.range_resposta
        return self.range_resposta

    async def faturas_concessionaria(self, slug):
        self.chamadas.append(("faturas",))
        if isinstance(self.faturas_resposta, BaseException):
            raise self.faturas_resposta
        return self.faturas_resposta


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=minha.id))
    db.commit()

    caixa = {"cliente": ClienteFalso()}

    async def _cliente(_db):
        return caixa["cliente"]

    monkeypatch.setattr(energia.integracoes, "cliente_meuwatt", _cliente)
    monkeypatch.setattr(energia, "hoje_na_usina", lambda: HOJE)

    http = TestClient(_aplicacao(db))
    token, _ = criar_token(dono.id)
    http.headers["Authorization"] = f"Bearer {token}"
    yield http, caixa, minha


# ── o caminho feliz ──────────────────────────────────────────────────────────


def test_os_numeros_do_dia_saem_prontos(cenario):
    http, _, usina = cenario

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}")

    assert r.status_code == 200, r.text
    c = r.json()
    assert c["dia"] == DIA
    assert c["gerado_kwh"] == 4000.0
    assert c["pico_kw"] == 350.0 and c["pico_hora"] == "09:20"
    assert c["potencia_agora_kw"] == 350.0
    assert c["inversores_gerando"] == 4
    assert c["inversores_total"] == 4
    assert c["disponibilidade_pct"] == 98.2
    assert c["pr_pct"] == 81.2, "PR chega como razão 0–1 e sai em %"
    assert c["pr_descartado"] is False
    assert c["tem_estacao"] is True
    assert c["hpoa_agora"] == 640.0
    assert c["hpoa_acumulada"] == 5.4 and c["ghi_acumulada"] == 5.0
    assert [p["hora"] for p in c["curva"]] == ["09:00", "09:05", "09:20"]
    assert c["aviso"] is None


def test_a_soma_das_ucs_bate_com_a_geracao_da_usina(cenario):
    http, _, usina = cenario

    c = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()

    soma = sum(u["energia_kwh"] for u in c["ucs"])
    assert abs(soma - c["gerado_kwh"]) < 0.01
    assert [u["nome"] for u in c["ucs"]] == ["SKID 01", "SKID 02"]
    assert [u["indice"] for u in c["ucs"]] == [0, 1]


def test_cada_uc_traz_potencia_agora_pct_da_capacidade_e_status(cenario):
    http, _, usina = cenario

    ucs = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()["ucs"]

    skid1 = ucs[0]
    assert skid1["kwp"] == 200.0 and skid1["inversores"] == 2
    assert skid1["potencia_agora_kw"] == 175.0, "90 + 85 no último bucket com leitura"
    assert skid1["pct_capacidade"] == 87.5
    assert (skid1["ok"], skid1["total"]) == (2, 2)


def test_uc_com_inversor_em_falha_conta_o_status_certo(cenario):
    http, caixa, usina = cenario
    diario = _diario()
    diario["inverters"][1]["is_faulty"] = True
    diario["inverters"][1]["daily_yield_kwh"] = 0.0
    caixa["cliente"] = ClienteFalso(diario=diario)

    ucs = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()["ucs"]

    assert (ucs[0]["ok"], ucs[0]["total"]) == (1, 2)
    assert (ucs[1]["ok"], ucs[1]["total"]) == (2, 2)


# ── a faísca: 15 minutos, alinhada, e com lacuna de verdade ──────────────────


def test_a_faisca_vem_reamostrada_em_quinze_minutos_e_alinhada_entre_as_ucs(cenario):
    http, _, usina = cenario

    c = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()

    assert c["faisca_horas"] == ["09:00", "09:15"], "três buckets de 5 min viram 2 fatias"
    # SKID 01: (60+50) e (80+70) na primeira fatia → média 130; (90+85) na segunda.
    assert c["ucs"][0]["faisca"] == [130.0, 175.0]
    assert c["ucs"][1]["faisca"] == [130.0, 175.0]
    for uc in c["ucs"]:
        assert len(uc["faisca"]) == len(c["faisca_horas"])


def test_fatia_sem_leitura_da_uc_vira_lacuna_e_nao_zero(cenario):
    """Um vale desenhado no lugar da lacuna diria 'parou' para quem só olha a linha."""
    http, caixa, usina = cenario
    pontos = _intraday()["points"]
    # Na fatia das 09:15 só a SKID 02 publica.
    pontos[2]["inverters"] = [{"serial_number": "SN-B1", "power_kw": 95.0}]
    caixa["cliente"] = ClienteFalso(intraday=_intraday(pontos))

    c = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()

    assert c["ucs"][0]["faisca"] == [130.0, None]
    assert c["ucs"][1]["faisca"] == [130.0, 95.0]


# ── o inversor sem transformador ─────────────────────────────────────────────


def test_inversor_sem_transformador_aparece_em_sem_uc(cenario):
    """Descartá-lo faria a soma das UCs não fechar com a geração da usina — que é
    justamente a conferência que o dono faz de olho."""
    http, caixa, usina = cenario
    diario = _diario(total_generation_kwh=4500.0)
    diario["inverters"].append(_inversor("SN-ORFAO", None, None, 500.0))
    caixa["cliente"] = ClienteFalso(diario=diario)

    c = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()

    nomes = [u["nome"] for u in c["ucs"]]
    assert nomes == ["SKID 01", "SKID 02", "Sem UC"]
    orfa = c["ucs"][2]
    assert orfa["energia_kwh"] == 500.0
    assert orfa["kwp"] == 100.0 and orfa["total"] == 1
    assert abs(sum(u["energia_kwh"] for u in c["ucs"]) - c["gerado_kwh"]) < 0.01


# ── eventos ──────────────────────────────────────────────────────────────────


def test_dia_sem_incidente_devolve_lista_vazia_e_nao_erro(cenario):
    http, _, usina = cenario

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}")

    assert r.status_code == 200
    assert r.json()["eventos"] == []
    assert r.json()["aviso"] is None


def test_evento_traz_hora_rotulo_duracao_e_se_ainda_esta_em_curso(cenario):
    http, caixa, usina = cenario
    diario = _diario(
        alert_timeline=[
            {
                "id": 7,
                "inverter_id": 12,
                "sn": "SN-A1",
                "slot_label": None,
                "status": 768,
                "notification": "Potência zero",
                "message": None,
                "started_at": "2026-08-14T09:32:00-03:00",
                "resolved_at": "2026-08-14T11:04:00-03:00",
                "is_active": False,
                "duration_minutes": 92.0,
                "estimated_loss_kwh": 45.0,
            },
            {
                "id": 8,
                "inverter_id": 15,
                "sn": "SN-B2",
                "slot_label": None,
                "status": 768,
                "notification": None,
                "message": "Falha de comunicação",
                "started_at": "2026-08-14T08:10:00-03:00",
                "resolved_at": None,
                "is_active": True,
                "duration_minutes": 400.0,
                "estimated_loss_kwh": 90.0,
            },
        ]
    )
    caixa["cliente"] = ClienteFalso(diario=diario)

    eventos = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()["eventos"]

    assert [e["hora"] for e in eventos] == ["08:10", "09:32"], "ordenado pela hora"
    aberto, fechado = eventos
    assert aberto["evento"] == "Falha de comunicação"
    assert aberto["em_curso"] is True and aberto["resolvido_em"] is None
    assert fechado["evento"] == "Potência zero"
    assert fechado["em_curso"] is False and fechado["resolvido_em"] == "11:04"
    assert fechado["duracao_min"] == 92.0
    # A etiqueta do slot quando existe; a posição na lista quando não.
    assert fechado["inversor"] == "INV 1"
    assert aberto["inversor"] == "Inversor 4"


# ── a barreira: nada de entranhas do meuWatt no corpo ────────────────────────


def test_o_corpo_nao_carrega_serial_nem_id_de_transformador(cenario):
    """O recorte existe para isto: a estrutura interna do produto de origem não
    atravessa até o navegador do cliente."""
    http, caixa, usina = cenario
    diario = _diario(
        alert_timeline=[
            {
                "id": 7,
                "inverter_id": 12,
                "sn": "SN-A1",
                "status": 768,
                "notification": "Potência zero",
                "message": None,
                "started_at": "2026-08-14T09:32:00-03:00",
                "resolved_at": None,
                "is_active": True,
                "duration_minutes": 92.0,
                "estimated_loss_kwh": 45.0,
            }
        ]
    )
    caixa["cliente"] = ClienteFalso(diario=diario)

    corpo = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").text

    for serial in ("SN-A1", "SN-A2", "SN-B1", "SN-B2"):
        assert serial not in corpo
    for chave in ("serial_number", "transformer_id", "inverter_id", "\"sn\""):
        assert chave not in corpo


# ── regra 0 e degradação ─────────────────────────────────────────────────────


def test_pr_descartada_pelo_meuwatt_sai_nula_com_a_bandeira(cenario):
    """Nunca 0%: o `performance_ratio` que vem junto do flag é zero fabricado."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        diario=_diario(pr_flag="implausivel_alta", pr_raw=2.4, performance_ratio=0.0)
    )

    c = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()

    assert c["pr_pct"] is None
    assert c["pr_descartado"] is True


def test_usina_sem_estacao_nao_publica_irradiacao_nem_pr(cenario):
    """O upstream preenche `poa` com 0 quando não há sensor — desenhar isso daria uma
    linha rasteira com cara de medição."""
    http, caixa, usina = cenario
    pontos = _intraday()["points"]
    for p in pontos:
        p["poa"] = 0
        p["ghi"] = 0
    caixa["cliente"] = ClienteFalso(
        diario=_diario(irradiation={"hpoa": 0.0, "hghi": 0.0}), intraday=_intraday(pontos)
    )

    c = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()

    assert c["tem_estacao"] is False
    assert c["hpoa_agora"] is None
    assert c["hpoa_acumulada"] is None and c["ghi_acumulada"] is None
    assert c["pr_pct"] is None and c["pr_descartado"] is False
    assert all(p["poa"] is None for p in c["curva"])


def test_bucket_sem_leitura_nao_vira_ponto(cenario):
    http, caixa, usina = cenario
    pontos = _intraday()["points"]
    pontos.insert(0, {"time": "03:00", "ghi": 0, "poa": 0, "inverters": []})
    caixa["cliente"] = ClienteFalso(intraday=_intraday(pontos))

    c = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}").json()

    assert "03:00" not in [p["hora"] for p in c["curva"]]


def test_curva_fora_do_ar_nao_derruba_os_numeros_do_dia(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(intraday=RuntimeError("timeout"))

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}")

    assert r.status_code == 200
    c = r.json()
    assert c["gerado_kwh"] == 4000.0
    assert c["curva"] == [] and c["potencia_agora_kw"] is None
    assert c["ucs"][0]["energia_kwh"] == 2000.0
    assert c["ucs"][0]["potencia_agora_kw"] is None
    assert c["ucs"][0]["pct_capacidade"] is None
    assert "curva do dia não veio" in c["aviso"]


def test_monitoramento_fora_do_ar_vira_aviso_e_nao_zeros(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(diario=RuntimeError("502"))

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}")

    assert r.status_code == 200
    c = r.json()
    assert c["gerado_kwh"] is None and c["ucs"] == [] and c["curva"] == []
    assert "Monitoramento indisponível" in c["aviso"]


# ── escopo e peso ────────────────────────────────────────────────────────────


def test_usina_fora_do_escopo_devolve_404(cenario):
    http, _, _ = cenario

    assert http.get("/api/v1/energia/usinas/999/dia").status_code == 404


def test_data_futura_e_recusada(cenario):
    http, _, usina = cenario

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data=2027-01-01")

    assert r.status_code == 400


def test_o_corpo_do_dia_cabe_em_duzentos_kb_com_vinte_inversores(cenario):
    """Um dia inteiro de uma usina de 20 inversores: 288 buckets de 5 min. Se a série por
    inversor vazasse para a resposta, este teste seria o primeiro a cair."""
    http, caixa, usina = cenario

    inversores = []
    transformadores = []
    for uc in range(1, 6):
        transformadores.append(
            {
                "id": uc,
                "name": f"SKID {uc:02d}",
                "inverter_count": 4,
                "total_yield_kwh": 2000.0,
                "total_capacity_kwp": 400.0,
            }
        )
        for n in range(1, 5):
            inversores.append(
                _inversor(f"SN-{uc}-{n}", uc, f"SKID {uc:02d}", 500.0)
            )

    pontos = []
    for minuto in range(0, 24 * 60, 5):
        pontos.append(
            {
                "time": f"{minuto // 60:02d}:{minuto % 60:02d}",
                "ghi": 500.0,
                "poa": 540.0,
                "inverters": [
                    {"serial_number": i["sn"], "power_kw": 55.5} for i in inversores
                ],
            }
        )

    caixa["cliente"] = ClienteFalso(
        diario=_diario(
            total_generation_kwh=10000.0,
            inverters=inversores,
            transformers=transformadores,
        ),
        intraday=_intraday(pontos),
    )

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/dia?data={DIA}")

    assert r.status_code == 200
    assert len(r.content) < 200 * 1024, f"{len(r.content)} bytes"
    c = json.loads(r.content)
    assert len(c["ucs"]) == 5
    assert len(c["faisca_horas"]) == 96, "24 h em fatias de 15 min"
    assert all(len(u["faisca"]) == 96 for u in c["ucs"])
