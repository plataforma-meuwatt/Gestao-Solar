"""A série longa — `GET /plants/{id}/historico?meses=`.

Três coisas aqui quebram em silêncio: um mês sem leitura virando barra de zero, o
`ano_anterior` sendo lido de um mês que não foi buscado, e a fatia de um ano civil passando
dos 366 dias que o upstream aceita. Os payloads seguem o `monthly_summaries` real.
"""

from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import plants
from app.api.v1.plants import _deslocar_mes, _fatias_por_ano, _meses_entre
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

HOJE = date(2026, 8, 14)


def _aplicacao(db) -> FastAPI:
    """Só o router sob teste, com o banco do teste. Não passa por `app.main` de propósito:
    a rota é a mesma que ele monta, e um router alheio quebrado no meio de uma edição
    não pode derrubar os testes de energia."""
    aplicacao = FastAPI()
    aplicacao.include_router(plants.router)
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


def _erro_http(status: int) -> httpx.HTTPStatusError:
    pedido = httpx.Request("GET", "https://api.meuwatt.test/plants/x/generation/range")
    resposta = httpx.Response(status, json={"detail": "Erro interno."}, request=pedido)
    return httpx.HTTPStatusError(str(status), request=pedido, response=resposta)


def _kwh_de(mes: str) -> float:
    """Um valor reconhecível por mês: `2025-03` → 2503.0."""
    return float(f"{mes[2:4]}{mes[5:7]}")


class ClienteFalso:
    """Um `range` por fatia, com `monthly_summaries` de todos os meses da fatia — menos os
    listados em `sem_dado`. Uma fatia cujo início está em `falha_em` lança."""

    def __init__(self, sem_dado=(), falha_em=(), pvsyst=None):
        self.sem_dado = set(sem_dado)
        self.falha_em = set(falha_em)
        self.pvsyst_resposta = pvsyst if pvsyst is not None else {"rows": [], "years": [], "count": 0}
        self.fatias: list[tuple[date, date]] = []

    async def geracao_periodo(self, slug, inicio, fim):
        self.fatias.append((inicio, fim))
        if inicio in self.falha_em:
            raise _erro_http(500)
        meses = _meses_entre(f"{inicio.year:04d}-{inicio.month:02d}", f"{fim.year:04d}-{fim.month:02d}")
        return {
            "total_generation_kwh": 1.0,
            "days_with_data": (fim - inicio).days + 1,
            "monthly_summaries": [
                {"month": m, "generation_kwh": _kwh_de(m), "lost_kwh": 1.5}
                for m in meses if m not in self.sem_dado
            ],
        }

    async def pvsyst(self, slug, inicio, fim):
        return self.pvsyst_resposta

    async def pvsyst_manual(self, slug, ano):
        return {"year": ano, "rows": []}


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=minha.id))
    db.commit()

    caixa = {"cliente": ClienteFalso()}

    async def _cliente(_db):
        return caixa["cliente"]

    monkeypatch.setattr(plants.integracoes, "cliente_meuwatt", _cliente)
    monkeypatch.setattr(plants, "hoje_na_usina", lambda: HOJE)

    http = TestClient(_aplicacao(db))
    token, _ = criar_token(dono.id)
    http.headers["Authorization"] = f"Bearer {token}"
    yield http, caixa, minha


# ── a aritmética que sustenta a rota ────────────────────────────────────────


def test_deslocar_mes_atravessa_o_ano():
    assert _deslocar_mes("2026-03", -12) == "2025-03"
    assert _deslocar_mes("2026-01", -1) == "2025-12"
    assert _deslocar_mes("2025-12", 1) == "2026-01"
    assert _deslocar_mes("2026-08", -23) == "2024-09"


def test_fatias_nunca_passam_de_um_ano_civil():
    """2024 é bissexto: a fatia inteira tem exatamente 366 dias — o teto do upstream."""
    fatias = _fatias_por_ano(date(2023, 9, 1), date(2026, 8, 14))

    assert fatias == [
        (date(2023, 9, 1), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 8, 14)),
    ]
    assert all((b - a).days + 1 <= 366 for a, b in fatias)


# ── a rota ───────────────────────────────────────────────────────────────────


def test_24_meses_com_dois_sem_leitura_ficam_nulos_e_o_ano_anterior_vem_quando_existe(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(sem_dado={"2025-03", "2026-02"})

    r = http.get(f"/api/v1/plants/{usina.id}/historico?meses=24")

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["inicio"] == "2024-09-01" and corpo["fim"] == "2026-08-14"
    meses = corpo["meses"]
    assert [m["mes"] for m in meses][0] == "2024-09"
    assert [m["mes"] for m in meses][-1] == "2026-08"
    assert len(meses) == 24

    por_mes = {m["mes"]: m for m in meses}
    # Sem leitura é NULO — não é barra de zero.
    assert por_mes["2025-03"]["energia_kwh"] is None
    assert por_mes["2026-02"]["energia_kwh"] is None
    assert por_mes["2025-03"]["perdas_kwh"] is None
    # Quem tem leitura, tem.
    assert por_mes["2025-04"]["energia_kwh"] == 2504.0
    assert por_mes["2025-04"]["perdas_kwh"] == 1.5
    # Ano anterior: preenchido quando o mês −12 existe…
    assert por_mes["2026-04"]["ano_anterior_kwh"] == 2504.0
    assert por_mes["2024-09"]["ano_anterior_kwh"] == 2309.0, "o 1º mês da série olha um ano atrás"
    # …e nulo quando o mês −12 não teve dado.
    assert por_mes["2026-03"]["ano_anterior_kwh"] is None
    assert por_mes["2026-02"]["ano_anterior_kwh"] == 2502.0, "mês sem leitura ainda tem o ano anterior"
    assert corpo["aviso"] is None


def test_le_um_ano_a_mais_para_tras_em_fatias_de_ano_civil(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso()

    http.get(f"/api/v1/plants/{usina.id}/historico?meses=24")

    assert caixa["cliente"].fatias == [
        (date(2023, 9, 1), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), HOJE),
    ]


def test_o_esperado_do_projeto_acompanha_cada_mes(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        pvsyst={
            "rows": [
                {"date": "2026-07-01", "globinc": 5, "e_array": 100, "e_grid": 100.0},
                {"date": "2026-07-02", "globinc": 5, "e_array": 150, "e_grid": 150.0},
            ],
            "years": [2026], "count": 2,
        }
    )

    corpo = http.get(f"/api/v1/plants/{usina.id}/historico?meses=3").json()

    por_mes = {m["mes"]: m for m in corpo["meses"]}
    assert list(por_mes) == ["2026-06", "2026-07", "2026-08"]
    assert por_mes["2026-07"]["esperado_projeto_kwh"] == 250.0
    assert por_mes["2026-06"]["esperado_projeto_kwh"] is None
    assert por_mes["2026-08"]["esperado_projeto_kwh"] is None


def test_uma_fatia_falhando_anula_os_meses_dela_e_avisa(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(falha_em={date(2025, 1, 1)})

    r = http.get(f"/api/v1/plants/{usina.id}/historico?meses=24")

    assert r.status_code == 200
    corpo = r.json()
    por_mes = {m["mes"]: m for m in corpo["meses"]}
    assert por_mes["2025-06"]["energia_kwh"] is None
    assert por_mes["2026-06"]["ano_anterior_kwh"] is None
    assert por_mes["2026-06"]["energia_kwh"] == 2606.0
    assert "2025-01 a 2025-12" in corpo["aviso"]


def test_todas_as_fatias_falhando_e_502(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        falha_em={date(2025, 8, 1), date(2026, 1, 1)}
    )

    r = http.get(f"/api/v1/plants/{usina.id}/historico?meses=1")

    assert r.status_code == 502
    # A frase leva o `detail` do upstream, e nunca acusa o produto errado.
    assert "Erro interno" in r.json()["detail"]
    assert "meuPlano" not in r.json()["detail"]


@pytest.mark.parametrize("meses", [0, 37, -1])
def test_fora_do_teto_e_400(cenario, meses):
    http, _caixa, usina = cenario
    assert http.get(f"/api/v1/plants/{usina.id}/historico?meses={meses}").status_code == 400


def test_usina_alheia_e_404(cenario, usinas):
    http, _caixa, _minha = cenario
    _, alheia = usinas
    assert http.get(f"/api/v1/plants/{alheia.id}/historico").status_code == 404


def test_usina_sem_monitoramento_e_404(cenario, db):
    http, _caixa, usina = cenario
    usina.mw_plant_slug = None
    db.commit()
    assert http.get(f"/api/v1/plants/{usina.id}/historico").status_code == 404


def test_sem_token_e_401(cenario):
    http, _caixa, usina = cenario
    del http.headers["Authorization"]
    assert http.get(f"/api/v1/plants/{usina.id}/historico").status_code in (401, 403)
