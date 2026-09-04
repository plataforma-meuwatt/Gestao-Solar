"""Medido × esperado do projeto — `GET /plants/{id}/desempenho`.

O que se protege aqui é a REGRA 0 do produto na sua forma mais tentadora: quando falta a
meta, o percentual não vira 0% (que se lê "gerou nada") e quando falta a medição a energia
não vira 0 kWh. E a régua de cor sai do servidor, com os limiares escritos num lugar só.

Os payloads são os que `generation/range` e `/pvsyst` devolvem de fato — inclusive o
`0.0` fabricado quando `days_with_data == 0`, que é onde o zero falso nasce.
"""

from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import plants
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


def _range(dias_com_dado: int = 14, energia: float = 9500.0, **extra) -> dict:
    """O headline do `range` como o mw-api o monta."""
    base = {
        "total_generation_kwh": energia,
        "days_with_data": dias_com_dado,
        "performance_ratio": 0.8123,
        "availability_real_pct": 98.2,
        "availability_contratual_pct": 99.1,
        "summary": {"total_lost_kwh": 120.5},
        "monthly_summaries": [
            {
                "month": "2026-08",
                "generation_kwh": energia,
                "lost_kwh": 120.5,
                "availability_real_pct": 98.2,
                "availability_contratual_pct": 99.1,
            }
        ],
    }
    base.update(extra)
    return base


def _pvsyst_diario(kwh_por_dia: float = 700.0, ate: int = 14, extras: list | None = None) -> dict:
    linhas = [
        {"date": f"2026-08-{d:02d}", "globinc": 5.0, "e_array": kwh_por_dia, "e_grid": kwh_por_dia}
        for d in range(1, ate + 1)
    ]
    return {"rows": linhas + (extras or []), "years": [2026], "count": len(linhas)}


class ClienteFalso:
    """O meuWatt sem rede. Cada método pode ser trocado por uma exceção a lançar."""

    def __init__(self, relatorio=None, pvsyst=None, manual=None):
        self.relatorio = relatorio if relatorio is not None else _range()
        self.pvsyst_resposta = pvsyst if pvsyst is not None else {"rows": [], "years": [], "count": 0}
        self.manual_resposta = manual if manual is not None else {"year": 2026, "rows": []}
        self.chamadas: list[tuple] = []

    async def geracao_periodo(self, slug, inicio, fim):
        self.chamadas.append(("range", inicio, fim))
        if isinstance(self.relatorio, BaseException):
            raise self.relatorio
        return self.relatorio

    async def pvsyst(self, slug, inicio, fim):
        self.chamadas.append(("pvsyst", inicio, fim))
        if isinstance(self.pvsyst_resposta, BaseException):
            raise self.pvsyst_resposta
        return self.pvsyst_resposta

    async def pvsyst_manual(self, slug, ano):
        self.chamadas.append(("manual", ano))
        if isinstance(self.manual_resposta, BaseException):
            raise self.manual_resposta
        return self.manual_resposta


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    """Usina do dono ligada ao meuWatt, hoje congelado em 14/08/2026, cliente trocável."""
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


# ── o caminho feliz ──────────────────────────────────────────────────────────


def test_range_e_pvsyst_dao_energia_esperado_pct_pr_e_situacao(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(pvsyst=_pvsyst_diario())

    r = http.get(f"/api/v1/plants/{usina.id}/desempenho?recorte=mes&referencia=2026-08-14")

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["inicio"] == "2026-08-01" and corpo["fim"] == "2026-08-14"
    assert corpo["energia_kwh"] == 9500.0
    assert corpo["esperado_projeto_kwh"] == 9800.0
    assert corpo["pct_do_projeto"] == 96.9
    assert corpo["pr_pct"] == 81.2, "PR chega como razão 0–1 e sai em %"
    assert corpo["disponibilidade_real_pct"] == 98.2
    assert corpo["disponibilidade_contratual_pct"] == 99.1
    assert corpo["perdas_paradas_kwh"] == 120.5
    assert (corpo["tom"], corpo["situacao"]) == ("ok", "Dentro do esperado")
    assert corpo["meses"] == [], "no recorte mês não há série mensal"
    assert corpo["aviso"] is None


def test_a_meta_do_mes_corrente_para_em_hoje(cenario):
    """A tabela tem os 31 dias de agosto; medido só até o 14. Somar o mês inteiro diria
    'abaixo do esperado' para uma usina em dia."""
    http, caixa, usina = cenario
    futuro = [{"date": f"2026-08-{d:02d}", "globinc": 5.0, "e_array": 700.0, "e_grid": 700.0}
              for d in range(15, 32)]
    caixa["cliente"] = ClienteFalso(pvsyst=_pvsyst_diario(extras=futuro))

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14").json()

    assert corpo["esperado_projeto_kwh"] == 9800.0
    assert corpo["tom"] == "ok"
    # E o range também foi pedido só até hoje, não até o fim do mês.
    assert caixa["cliente"].chamadas[0] == ("range", date(2026, 8, 1), HOJE)


@pytest.mark.parametrize(
    ("energia", "tom", "situacao"),
    [
        (9310.0, "ok", "Dentro do esperado"),      # 95,0 %
        (9300.0, "alerta", "Abaixo do esperado"),  # 94,9 %
        (8330.0, "alerta", "Abaixo do esperado"),  # 85,0 %
        (8320.0, "parado", "Bem abaixo do esperado"),  # 84,9 %
    ],
)
def test_a_regua_do_projeto_tem_tres_faixas(cenario, energia, tom, situacao):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=_range(energia=energia), pvsyst=_pvsyst_diario())

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14").json()

    assert (corpo["tom"], corpo["situacao"]) == (tom, situacao)


def test_todo_tom_existe_nos_tokens():
    """Os nomes são as chaves de `tons` do cliente — um nome fora da lista vira `undefined`."""
    tons = {"parado", "alerta", "multiplos", "tempoRuim", "ok", "semDados"}
    for energia, esperado, indisponivel in [
        (None, None, False), (1.0, None, False), (1.0, None, True),
        (100.0, 100.0, False), (90.0, 100.0, False), (10.0, 100.0, False),
    ]:
        _, tom, _ = plants._situacao_do_projeto(energia, esperado, indisponivel)
        assert tom in tons


# ── sem meta, sem medição, sem ponte ────────────────────────────────────────


def test_sem_pvsyst_o_esperado_e_nulo_e_nenhum_campo_vira_zero(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso()  # pvsyst e manual vazios

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14").json()

    assert corpo["energia_kwh"] == 9500.0
    assert corpo["esperado_projeto_kwh"] is None
    assert corpo["pct_do_projeto"] is None
    assert (corpo["tom"], corpo["situacao"]) == ("semDados", "Sem meta de projeto cadastrada")
    assert 0 not in (corpo["esperado_projeto_kwh"], corpo["pct_do_projeto"])
    # A ausência da diária fez o BFF tentar a mensal do ano — e só do ano que faltava.
    assert ("manual", 2026) in caixa["cliente"].chamadas


def test_a_meta_mensal_digitada_e_a_segunda_fonte_proporcional_ao_mes(cenario):
    """Só a aba Projeto do meuWatt tem número: 31.000 kWh em agosto, 14 dias medidos →
    a meta comparável é 14/31 dela. Não é estimativa nova, é a mesma meta na fração vivida."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        manual={"year": 2026, "rows": [{"month": 8, "e_array": 0, "e_grid": 31000.0}]}
    )

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14").json()

    assert corpo["esperado_projeto_kwh"] == 14000.0
    assert corpo["pct_do_projeto"] == 67.9
    assert (corpo["tom"], corpo["situacao"]) == ("parado", "Bem abaixo do esperado")


def test_meta_fora_do_ar_nao_vira_sem_meta_cadastrada(cenario):
    """'Ninguém cadastrou' e 'o monitoramento caiu' pedem ações diferentes."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(pvsyst=_erro_http(500), manual=_erro_http(500))

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14").json()

    assert corpo["energia_kwh"] == 9500.0, "o medido continua vindo"
    assert corpo["esperado_projeto_kwh"] is None
    assert corpo["situacao"] == "Meta do projeto indisponível agora"
    assert "indisponível" in corpo["aviso"]


def test_sem_dias_com_dado_a_energia_e_nula_e_nao_o_zero_fabricado(cenario):
    """`days_with_data == 0` faz o mw-api devolver 0.0 em tudo — por construção."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(dias_com_dado=0, energia=0.0, performance_ratio=0.0),
        pvsyst=_pvsyst_diario(),
    )

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14").json()

    assert corpo["energia_kwh"] is None
    assert corpo["pr_pct"] is None
    assert corpo["perdas_paradas_kwh"] is None
    assert corpo["pct_do_projeto"] is None
    assert (corpo["tom"], corpo["situacao"]) == ("semDados", "Sem dados de geração no período")
    assert "não devolveu geração" in corpo["aviso"]


def test_pr_zero_do_upstream_nao_e_pr(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=_range(performance_ratio=0.0))

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14").json()

    assert corpo["pr_pct"] is None
    assert corpo["energia_kwh"] == 9500.0


def test_range_fora_do_ar_e_502_com_o_produto_certo(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=_erro_http(500))

    r = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14")

    assert r.status_code == 502
    assert "meuPlano" not in r.json()["detail"]


def test_range_demorando_e_504(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=httpx.ReadTimeout("demorou"))

    r = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-14")

    assert r.status_code == 504
    assert "meuWatt" in r.json()["detail"]


# ── entrada e escopo ─────────────────────────────────────────────────────────


def test_referencia_futura_e_400(cenario):
    http, _caixa, usina = cenario
    r = http.get(f"/api/v1/plants/{usina.id}/desempenho?referencia=2026-08-15")
    assert r.status_code == 400


def test_recorte_desconhecido_e_400(cenario):
    http, _caixa, usina = cenario
    r = http.get(f"/api/v1/plants/{usina.id}/desempenho?recorte=semana")
    assert r.status_code == 400


def test_usina_de_outro_cliente_e_404(cenario, usinas):
    http, _caixa, _minha = cenario
    _, alheia = usinas
    assert http.get(f"/api/v1/plants/{alheia.id}/desempenho").status_code == 404


def test_usina_sem_monitoramento_e_404(cenario, db):
    http, _caixa, usina = cenario
    usina.mw_plant_slug = None
    db.commit()
    r = http.get(f"/api/v1/plants/{usina.id}/desempenho")
    assert r.status_code == 404
    assert "monitoramento" in r.json()["detail"]


def test_sem_token_e_401(cenario):
    http, _caixa, usina = cenario
    del http.headers["Authorization"]
    assert http.get(f"/api/v1/plants/{usina.id}/desempenho").status_code in (401, 403)


# ── recorte ano ──────────────────────────────────────────────────────────────


def test_no_ano_cada_mes_ate_hoje_vem_com_o_esperado_ao_lado(cenario):
    """Jan..ago (hoje é 14/08): o mês sem `monthly_summaries` fica NULO, não zero; o
    esperado acompanha cada mês que tem meta."""
    http, caixa, usina = cenario
    relatorio = _range(
        dias_com_dado=200, energia=60000.0,
        monthly_summaries=[
            {"month": "2026-01", "generation_kwh": 8000.0, "lost_kwh": 0.0,
             "availability_contratual_pct": 100.0},
            {"month": "2026-03", "generation_kwh": 7000.0, "lost_kwh": 50.0,
             "availability_contratual_pct": 99.0},
        ],
    )
    pvsyst = {
        "rows": [
            {"date": "2026-01-10", "globinc": 5, "e_array": 8100, "e_grid": 8100.0},
            {"date": "2026-03-10", "globinc": 5, "e_array": 7500, "e_grid": 7500.0},
            {"date": "2026-08-10", "globinc": 5, "e_array": 700, "e_grid": 700.0},
        ],
        "years": [2026], "count": 3,
    }
    caixa["cliente"] = ClienteFalso(relatorio=relatorio, pvsyst=pvsyst)

    corpo = http.get(f"/api/v1/plants/{usina.id}/desempenho?recorte=ano&referencia=2026-08-14").json()

    assert corpo["inicio"] == "2026-01-01" and corpo["fim"] == "2026-08-14"
    assert [m["mes"] for m in corpo["meses"]] == [f"2026-{m:02d}" for m in range(1, 9)]
    por_mes = {m["mes"]: m for m in corpo["meses"]}
    assert por_mes["2026-01"]["energia_kwh"] == 8000.0
    assert por_mes["2026-01"]["esperado_projeto_kwh"] == 8100.0
    assert por_mes["2026-01"]["disponibilidade_contratual_pct"] == 100.0
    assert por_mes["2026-03"]["perdas_kwh"] == 50.0
    assert por_mes["2026-02"]["energia_kwh"] is None
    assert por_mes["2026-02"]["esperado_projeto_kwh"] is None
    assert por_mes["2026-08"]["energia_kwh"] is None
    assert por_mes["2026-08"]["esperado_projeto_kwh"] == 700.0
    assert corpo["esperado_projeto_kwh"] == 16300.0
