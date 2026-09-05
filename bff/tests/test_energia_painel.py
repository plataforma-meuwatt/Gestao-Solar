"""O Painel de geração — `GET /api/v1/energia/usinas/{id}/painel`.

O que se protege aqui é o contrário do que um teste de dashboard costuma proteger. Não é
"o número saiu certo": é que a **ausência não vira zero** em nenhum dos quatro lugares
onde ela é mais tentadora — o dia cuja PR o monitoramento descartou, o dia futuro do mês
em curso, a usina sem medidor de fronteira e a usina sem estação solarimétrica. Cada um
desses, publicado como zero, seria lido pelo cliente como "gerou nada", "PR de 0%" ou
"perdemos 100% até a fronteira".

E protege a promessa que justifica este módulo existir: o recorte acontece no servidor.
Há um teste que varre o JSON inteiro atrás de número de série de inversor, id de
transformador e do nome interno do descarte de PR — nenhum dos três pode atravessar.

Os payloads são os que `generation/range`, `/pvsyst`, `/pvsyst/manual/{ano}`,
`ssu-readers/monthly-totals` e `utility-bills` devolvem de fato.
"""

import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import energia, plants
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

#: Meio de agosto: o mês da referência fica EM CURSO, que é onde moram o dia futuro, o
#: projeto proporcional e a tendência de fechamento.
HOJE = date(2026, 8, 14)


def _aplicacao(db) -> FastAPI:
    """Só o router sob teste, com o banco do teste — a mesma postura de `test_desempenho`:
    um router alheio quebrado no meio de uma edição não pode derrubar os testes de
    energia."""
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


def _dia(d: int, gerado: float = 700.0, perdida: float = 10.0, externa: float = 0.0) -> dict:
    return {
        "date": f"2026-08-{d:02d}",
        "generation_kwh": gerado,
        "lost_kwh": perdida,
        "lost_kwh_externa": externa,
    }


def _range(
    *,
    dias_com_dado: int = 14,
    energia_kwh: float = 9800.0,
    diarios: list[dict] | None = None,
    irradiacao: list[dict] | None = None,
    temperatura: list[dict] | None = None,
    pr_diario: list[dict] | None = None,
    pr_flags: list[dict] | None = None,
    inversores: list[dict] | None = None,
    timeline: list[dict] | None = None,
    mensais: list[dict] | None = None,
    **extra,
) -> dict:
    """O `RangeGenerationReport` como o mw-api o monta — com as entranhas que NÃO podem
    atravessar a ponte (serial, id de transformador, nome do descarte de PR)."""
    base = {
        "plant": "Porto Ferreira",
        "start_date": "2026-08-01",
        "end_date": "2026-08-14",
        "days_in_range": 14,
        "days_with_data": dias_com_dado,
        "total_generation_kwh": energia_kwh,
        "total_capacity_kwp": 1000.0,
        "productivity": 9.8,
        "performance_ratio": 0.8123,
        "irradiation": {"hpoa": 70.0, "hghi": 62.0},
        "availability_real_pct": 98.2,
        "availability_contratual_pct": 99.1,
        "pending_classification_count": 3,
        "summary": {"total_lost_kwh": 140.0, "total_lost_externa_kwh": 30.0},
        "inverters": inversores
        if inversores is not None
        else [
            {
                "id": 1,
                "sn": "SN2312090045",
                "slot_label": "INV-01",
                "capacity_kwp": 500.0,
                "total_yield_kwh": 5000.0,
                "transformer_id": 11,
                "transformer_name": "UC Norte",
                "installed_at": None,
                "deleted_at": None,
            },
            {
                "id": 2,
                "sn": "SN2312090046",
                "slot_label": None,
                "capacity_kwp": 500.0,
                "total_yield_kwh": 4800.0,
                "transformer_id": 12,
                "transformer_name": "UC Sul",
                "installed_at": None,
                "deleted_at": None,
            },
        ],
        "transformers": [
            {"id": 11, "name": "UC Norte", "inverter_count": 1, "total_yield_kwh": 5000.0},
            {"id": 12, "name": "UC Sul", "inverter_count": 1, "total_yield_kwh": 4800.0},
        ],
        "daily_summaries": diarios if diarios is not None else [_dia(d) for d in range(1, 15)],
        "monthly_summaries": mensais
        if mensais is not None
        else [
            {
                "month": "2026-08",
                "generation_kwh": energia_kwh,
                "lost_kwh": 140.0,
                "lost_externa_kwh": 30.0,
                "availability_real_pct": 98.2,
                "availability_contratual_pct": 99.1,
            }
        ],
        "alert_timeline": timeline if timeline is not None else [],
        "daily_solar_windows": [],
        "chart_data": {
            "daily_generation": {"SN2312090045": [{"t": "2026-08-01", "y": 350.0}]},
            "sn_transformer": {"SN2312090045": "UC Norte"},
            "daily_irradiation": irradiacao
            if irradiacao is not None
            else [{"t": f"2026-08-{d:02d}", "hpoa": 5.0, "hghi": 4.4} for d in range(1, 15)],
            "daily_temperature": temperatura
            if temperatura is not None
            else [
                {
                    "t": f"2026-08-{d:02d}",
                    "t_amb": 24.0,
                    "t_amb_max": 31.0,
                    "t_mod": 38.0,
                    "t_mod_max": 52.0,
                }
                for d in range(1, 15)
            ],
            "daily_pr": pr_diario
            if pr_diario is not None
            else [{"t": f"2026-08-{d:02d}", "pr": 0.81} for d in range(1, 15)],
            "daily_pr_flags": pr_flags if pr_flags is not None else [],
        },
    }
    base.update(extra)
    return base


def _pvsyst(kwh_por_dia: float = 700.0, ate: int = 31) -> dict:
    return {
        "rows": [
            {
                "date": f"2026-08-{d:02d}",
                "e_array": kwh_por_dia,
                "e_grid": kwh_por_dia,
                "globinc": 5.2,
                "indisponibilidade": None,
                "pr": 0.8,
            }
            for d in range(1, ate + 1)
        ],
        "years": [2026],
        "count": ate,
    }


def _manual(**campos) -> dict:
    """A linha de agosto da página Projeto. Sem POA/GHI não há correção pela meteo."""
    linha = {"month": 8, "e_array": 21000.0, "e_grid": 20500.0}
    linha.update(campos)
    return {"year": 2026, "rows": [linha]}


class ClienteFalso:
    """O meuWatt sem rede. Qualquer resposta pode ser uma exceção a lançar.

    `por_mes` responde às leituras de UM mês com um relatório próprio — é como o upstream
    de verdade se comporta, e o motivo de o painel do ano conferir mês a mês: o cabeçalho
    do `range` de agosto e o `monthly_summaries` do `range` do ano DISCORDAM (medido em
    Porto Ferreira: 99,89 % contra 99,99 %).
    """

    def __init__(
        self,
        relatorio=None,
        pvsyst=None,
        manual=None,
        fronteira=None,
        faturas=None,
        por_mes=None,
    ):
        self.relatorio = relatorio if relatorio is not None else _range()
        self.pvsyst_resposta = pvsyst if pvsyst is not None else _pvsyst()
        self.manual_resposta = manual if manual is not None else {"year": 2026, "rows": []}
        self.fronteira_resposta = fronteira if fronteira is not None else {}
        self.faturas_resposta = faturas if faturas is not None else []
        self.por_mes = por_mes or {}
        self.chamadas: list[tuple] = []

    async def geracao_periodo(self, slug, inicio, fim):
        self.chamadas.append(("range", inicio, fim))
        de_um_mes_so = inicio.day == 1 and (inicio.year, inicio.month) == (fim.year, fim.month)
        if de_um_mes_so and inicio.month in self.por_mes:
            return _devolver(self.por_mes[inicio.month])
        return _devolver(self.relatorio)

    async def pvsyst(self, slug, inicio, fim):
        self.chamadas.append(("pvsyst", inicio, fim))
        return _devolver(self.pvsyst_resposta)

    async def pvsyst_manual(self, slug, ano):
        self.chamadas.append(("manual", ano))
        return _devolver(self.manual_resposta)

    async def ssu_totais_mensais(self, slug, ano):
        self.chamadas.append(("ssu", ano))
        return _devolver(self.fronteira_resposta)

    async def faturas_concessionaria(self, slug, ano=None):
        self.chamadas.append(("faturas", ano))
        return _devolver(self.faturas_resposta)


def _devolver(resposta):
    if isinstance(resposta, BaseException):
        raise resposta
    return resposta


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
    # `_referencia_pedida` mora em `plants` e recusa data futura pelo relógio DELE — sem
    # este congelamento o teste passaria a depender do dia em que roda.
    monkeypatch.setattr(plants, "hoje_na_usina", lambda: HOJE)

    http = TestClient(_aplicacao(db))
    token, _ = criar_token(dono.id)
    http.headers["Authorization"] = f"Bearer {token}"
    yield http, caixa, minha


def _painel(http, usina, **params) -> dict:
    consulta = "&".join(f"{k}={v}" for k, v in params.items())
    r = http.get(f"/api/v1/energia/usinas/{usina.id}/painel?{consulta}")
    assert r.status_code == 200, r.text
    return r.json()


# ── o caminho feliz ──────────────────────────────────────────────────────────


def test_o_mes_traz_geracao_performance_e_o_periodo(cenario):
    http, _, usina = cenario

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["recorte"] == "mes"
    assert c["rotulo"] == "Agosto / 2026"
    assert (c["inicio"], c["fim"]) == ("2026-08-01", "2026-08-31")
    assert c["em_curso"] is True and c["dia_de_corte"] == 14
    assert c["medido_inversores_kwh"] == 9800.0
    assert c["capacidade_kwp"] == 1000.0
    assert c["produtividade_kwh_kwp"] == 9.8
    assert c["pr_pct"] == 81.2, "PR chega como razão 0–1 e sai em %"
    assert c["disponibilidade_real_pct"] == 98.2
    assert c["disponibilidade_contratual_pct"] == 99.1
    assert c["paradas_pendentes"] == 3
    assert c["perdida_kwh"] == 140.0 and c["perdida_externa_kwh"] == 30.0
    assert c["aviso"] is None
    assert c["regra"]["disponibilidade"].startswith("Disponibilidade =")


def test_o_range_para_em_hoje_e_o_projeto_vai_ate_o_fim_do_mes(cenario):
    """Duas janelas diferentes de propósito: o `range` fabrica dias vazios no futuro (e um
    zero fabricado se lê como "não gerou"), mas a referência de projeto do dia 30 existe
    mesmo antes de o dia 30 acontecer — é dela que sai o total do mês."""
    http, caixa, usina = cenario

    _painel(http, usina, recorte="mes", referencia="2026-08-14")

    chamadas = dict((c[0], c[1:]) for c in caixa["cliente"].chamadas)
    assert chamadas["range"] == (date(2026, 8, 1), HOJE)
    assert chamadas["pvsyst"] == (date(2026, 8, 1), date(2026, 8, 31))


def test_o_projeto_proporcional_e_a_tendencia_saem_do_mes_em_curso(cenario):
    """31 dias de PVsyst a 700 kWh = 21.700 kWh de projeto; até o dia 14, 9.800."""
    http, _, usina = cenario

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["projeto_kwh"] == 21700.0
    assert c["projeto_proporcional_kwh"] == 9800.0
    assert c["desvios"]["medido_vs_projeto_pct"] == 0.0, "compara com o proporcional"
    assert c["totais"]["tendencia_kwh"] == 21700.0


# ── regra 0: a ausência não vira zero ────────────────────────────────────────


def test_dia_com_pr_descartada_sai_sem_pr_e_com_a_bandeira(cenario):
    """O monitoramento tem um teto de plausibilidade: quando a PR do dia o estoura, ela é
    DESCARTADA. Publicá-la diria ao cliente que a usina teve 109% de PR — fisicamente
    impossível — ou 0%, que é o valor fabricado que costuma vir no lugar.

    O payload abaixo traz o dia descartado com PR POSITIVA na série, que é o caso que a
    filtragem por "maior que zero" não pega: quem manda a bandeira é quem decide, e a
    bandeira ganha do valor.
    """
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            pr_diario=[{"t": "2026-08-05", "pr": 1.09}, {"t": "2026-08-06", "pr": 0.79}],
            pr_flags=[{"t": "2026-08-05", "flag": "implausivel_alta", "pr_raw": 1.09}],
        )
    )

    dias = {d["dia"]: d for d in _painel(http, usina, recorte="mes", referencia="2026-08-14")["dias"]}

    assert dias[5]["pr_pct"] is None and dias[5]["pr_descartado"] is True
    assert dias[6]["pr_pct"] == 79.0 and dias[6]["pr_descartado"] is False


def test_dia_futuro_do_mes_em_curso_vem_marcado_e_sem_medicao(cenario):
    http, _, usina = cenario

    dias = {d["dia"]: d for d in _painel(http, usina, recorte="mes", referencia="2026-08-14")["dias"]}

    assert len(dias) == 31, "o mês inteiro aparece; o futuro é marcado, não omitido"
    assert dias[14]["futuro"] is False and dias[14]["medido_kwh"] == 700.0
    assert dias[20]["futuro"] is True and dias[20]["medido_kwh"] is None
    assert dias[20]["projeto_kwh"] == 700.0, "a referência de projeto do dia futuro existe"


def test_usina_sem_medidor_de_fronteira_nao_ganha_fronteira_nem_perda(cenario):
    """O atalho `medido × 0,987` foi removido do próprio meuWatt por ser um número
    inventado vestido de medição. Ele não volta por aqui."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(fronteira={})

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["medido_fronteira_kwh"] is None
    assert c["perda_inv_fronteira_pct"] is None
    assert c["conciliacao"]["fronteira_mwh"] is None
    assert c["conciliacao"]["situacao"] is None


def test_com_medidor_a_fronteira_e_a_perda_ate_ela_aparecem(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(fronteira={8: 9.653})

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["medido_fronteira_kwh"] == 9653.0
    assert c["perda_inv_fronteira_pct"] == 1.5
    assert c["conciliacao"]["fronteira_mwh"] == 9.653


def test_usina_sem_estacao_nao_tem_meteo_nem_pr(cenario):
    """Sem irradiação medida não há PR — e o upstream devolve `0.0` nesse caso, por
    construção. Zero de PR não é uma medição, é a ausência dela."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            irradiacao=[], temperatura=[], pr_diario=[], performance_ratio=0.0
        )
    )

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["meteo"]["tem_estacao"] is False
    assert c["meteo"]["tem_sensor_temperatura"] is False
    assert c["meteo"]["hpoa"] is None and c["meteo"]["ghi"] is None
    assert c["meteo"]["razao"] is None
    assert c["pr_pct"] is None
    assert all(d["pr_pct"] is None for d in c["dias"])


def test_mes_sem_fatura_e_estado_e_nao_erro(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(fronteira={8: 9.653}, faturas=[])

    conciliacao = _painel(http, usina, recorte="mes", referencia="2026-08-14")["conciliacao"]

    assert conciliacao["faturado_mwh"] is None
    assert conciliacao["diferenca_mwh"] is None and conciliacao["situacao"] is None
    assert conciliacao["fronteira_mwh"] == 9.653, "o que foi medido continua valendo"


def test_a_conciliacao_classifica_pela_tolerancia_declarada(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        fronteira={8: 9.653},
        faturas=[{"transformer_id": 11, "year": 2026, "month": 8, "billed_mwh": 9.6}],
    )

    conciliacao = _painel(http, usina, recorte="mes", referencia="2026-08-14")["conciliacao"]

    assert conciliacao["faturado_mwh"] == 9.6
    assert conciliacao["diferenca_mwh"] == 0.053
    assert conciliacao["diferenca_pct"] == 0.55
    assert conciliacao["situacao"] == "Conciliado"
    assert conciliacao["tolerancia_pct"] == 1.0


# ── a fronteira que não cobre a usina inteira ────────────────────────────────


def test_fronteira_que_nao_cobre_a_usina_nao_vira_perda(cenario):
    """Medido em Porto Ferreira, agosto de 2026: 846 MWh na fronteira contra 1.065 MWh nos
    inversores. Isso não é perda de 20,5 % — perda entre o inversor e o ponto de entrega é
    de transformação e de linha, e a referência do próprio projeto é 1,50 %. É o medidor
    cobrindo menos que a usina, e publicar a diferença como perda seria repetir, com
    número de verdade, o `medido × 0,987` que o meuWatt removeu."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(fronteira={8: 7.8})  # 7,8 MWh contra 9,8 medidos

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["fronteira_parcial"] is True
    assert c["perda_inv_fronteira_pct"] is None
    assert c["medido_fronteira_kwh"] == 7800.0, "o que o medidor mediu continua valendo"


def test_fronteira_parcial_nao_acusa_a_distribuidora_de_divergencia(cenario):
    """Classificar cobertura incompleta do medidor como "divergência relevante" mandaria o
    cliente cobrar da distribuidora um erro que é do aparelho dele."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        fronteira={8: 7.8},
        faturas=[{"transformer_id": 11, "year": 2026, "month": 8, "billed_mwh": 9.6}],
    )

    conciliacao = _painel(http, usina, recorte="mes", referencia="2026-08-14")["conciliacao"]

    assert conciliacao["situacao"] is None
    assert conciliacao["diferenca_mwh"] is None and conciliacao["diferenca_pct"] is None
    assert conciliacao["fronteira_mwh"] == 7.8 and conciliacao["faturado_mwh"] == 9.6


def test_fronteira_dentro_da_faixa_de_perda_nao_e_parcial(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(fronteira={8: 9.653})

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["fronteira_parcial"] is False and c["perda_inv_fronteira_pct"] == 1.5


# ── a temperatura sentinela ──────────────────────────────────────────────────


def test_sentinela_do_rele_de_temperatura_nao_vira_media(cenario):
    """A série real de Porto Ferreira em agosto de 2026: sete leituras, seis em `0.0` e
    uma em `-100.0`. Somadas, publicavam **−14,3 °C** como temperatura ambiente do mês.
    −100 °C não existe em lugar nenhum do planeta; é o relé dizendo "não medi"."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            temperatura=[
                {"t": "2026-08-02", "t_amb": 21.0, "t_amb_max": 30.0,
                 "t_mod": 35.5, "t_mod_max": 48.9},
                {"t": "2026-08-03", "t_amb": -100.0, "t_amb_max": -100.0,
                 "t_mod": -100.0, "t_mod_max": -100.0},
                {"t": "2026-08-06", "t_amb": 23.0, "t_amb_max": 32.0,
                 "t_mod": 36.1, "t_mod_max": 49.8},
            ]
        )
    )

    meteo = _painel(http, usina, recorte="mes", referencia="2026-08-14")["meteo"]

    assert meteo["t_amb_media"] == 22.0, "média das DUAS leituras de verdade"
    assert meteo["t_mod_media"] == 35.8
    assert meteo["t_mod_max"] == 49.8
    dia_do_sentinela = next(
        p for p in meteo["pontos"] if p["chave"] == "2026-08-03"
    )
    assert dia_do_sentinela["t_amb"] is None and dia_do_sentinela["t_mod"] is None


def test_serie_toda_zero_e_rele_mudo_nao_vira_medicao(cenario):
    """O OUTRO sentinela do mesmo relé. Filtrar só o −100 deixava o zero passar, e a tela do
    cliente publicava "TEMPERATURA AMBIENTE 0,0 °C, máxima 0,0 °C" num agosto do interior
    paulista. Medido no upstream em 2026: das 13 leituras de `t_amb`, doze são `0.0` e uma é
    `-100.0` — nenhuma na faixa plausível. Sensor que mede, oscila."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            temperatura=[
                {"t": "2026-08-02", "t_amb": 0.0, "t_amb_max": 0.0,
                 "t_mod": None, "t_mod_max": None},
                {"t": "2026-08-03", "t_amb": 0.0, "t_amb_max": 0.0,
                 "t_mod": None, "t_mod_max": None},
                {"t": "2026-08-04", "t_amb": -100.0, "t_amb_max": -100.0,
                 "t_mod": None, "t_mod_max": None},
            ]
        )
    )

    meteo = _painel(http, usina, recorte="mes", referencia="2026-08-14")["meteo"]

    assert meteo["t_amb_media"] is None, "sensor mudo não publica média"
    assert meteo["t_amb_max"] is None
    assert meteo["tem_sensor_temperatura"] is False
    assert all(p["t_amb"] is None for p in meteo["pontos"])


def test_rele_de_ambiente_mudo_nao_derruba_o_do_modulo(cenario):
    """O caso real de Porto Ferreira: o de ambiente só devolve o valor de fábrica enquanto o
    do módulo mede 33,8 °C. Some o campo mudo, não a meteorologia inteira."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            temperatura=[
                {"t": "2026-08-02", "t_amb": 0.0, "t_amb_max": 0.0,
                 "t_mod": 33.0, "t_mod_max": 45.0},
                {"t": "2026-08-03", "t_amb": 0.0, "t_amb_max": 0.0,
                 "t_mod": 34.6, "t_mod_max": 47.0},
            ]
        )
    )

    meteo = _painel(http, usina, recorte="mes", referencia="2026-08-14")["meteo"]

    assert meteo["t_amb_media"] is None
    assert meteo["t_mod_media"] == 33.8
    assert meteo["t_mod_max"] == 47.0
    assert meteo["tem_sensor_temperatura"] is True


def test_zero_em_serie_que_varia_atravessa_como_veio(cenario):
    """A régua é POR SÉRIE de propósito. Zero grau existe — serra no inverno —, e descartá-lo
    ponto a ponto jogaria fora medição de verdade. Uma leitura diferente na série e os zeros
    voltam a valer: corrigir medição plausível seria inventar dado."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            temperatura=[
                {"t": "2026-08-02", "t_amb": 0.0, "t_amb_max": 4.0,
                 "t_mod": None, "t_mod_max": None},
                {"t": "2026-08-03", "t_amb": 12.0, "t_amb_max": 18.0,
                 "t_mod": None, "t_mod_max": None},
            ]
        )
    )

    meteo = _painel(http, usina, recorte="mes", referencia="2026-08-14")["meteo"]

    assert meteo["t_amb_media"] == 6.0, "a média das duas, com o zero dentro"
    assert meteo["tem_sensor_temperatura"] is True
    dia_frio = next(p for p in meteo["pontos"] if p["chave"] == "2026-08-02")
    assert dia_frio["t_amb"] == 0.0


# ── a irradiação medida contra a do projeto ──────────────────────────────────


def test_desvio_de_poa_vem_do_pvsyst_diario_na_janela_do_medido(cenario):
    """A comparação que separa "o sol não veio" de "a usina não rendeu" — e que faltava.

    A fonte preferida é o PVsyst DIÁRIO, somado só até o último dia medido: 14 dias × 5,2 =
    72,8 kWh/m² de projeto contra 70,0 medidos (−3,85 %). Comparar com o mês inteiro (31 ×
    5,2 = 161,2) devolveria "−57 % de sol" no dia 14 de todo mês, todo mês.
    """
    http, _, usina = cenario

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["meteo"]["hpoa_projeto"] == pytest.approx(72.8, abs=0.01)
    assert c["desvios"]["hpoa_vs_projeto_pct"] == pytest.approx(-3.85, abs=0.01)
    # GHI de projeto só existe digitado na página de projeto; sem ele, nada sai.
    assert c["meteo"]["ghi_projeto"] is None
    assert c["desvios"]["ghi_vs_projeto_pct"] is None


def test_ghi_de_projeto_digitado_completa_a_comparacao(cenario):
    """O GHI de projeto não tem série diária — vem do valor mensal da página de projeto,
    rateado pela janela do medido: 60 × 14/31 = 27,10 kWh/m² contra os 61,6 medidos
    (14 dias × 4,4). O desvio grande é o do cenário, não da conta."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(manual=_manual(ghi=60.0))

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["meteo"]["ghi_projeto"] == pytest.approx(27.10, abs=0.01), "mês em curso: rateado"
    assert c["desvios"]["ghi_vs_projeto_pct"] == pytest.approx(127.31, abs=0.05)


def test_sem_projeto_de_irradiacao_o_desvio_nao_sai(cenario):
    """Sem PVsyst diário e sem POA/GHI digitados não há com o que comparar — e inventar uma
    referência seria pior do que não ter o número. A linha some da tela, não vira travessão."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(pvsyst={"rows": [], "years": [], "count": 0})

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["meteo"]["hpoa_projeto"] is None and c["meteo"]["ghi_projeto"] is None
    assert c["desvios"]["hpoa_vs_projeto_pct"] is None
    assert c["desvios"]["ghi_vs_projeto_pct"] is None


def test_no_mes_em_curso_a_irradiacao_digitada_e_prorateada(cenario):
    """Sem série diária, o valor MENSAL digitado entra rateado pelo mesmo dia de corte do
    projeto de energia: 65 × 14/31 = 29,35 kWh/m². Sem o rateio, meio mês de sol medido
    apanharia de um mês inteiro de projeto."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        pvsyst={"rows": [], "years": [], "count": 0}, manual=_manual(poa=65.0)
    )

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["em_curso"] is True and c["dia_de_corte"] == 14
    assert c["meteo"]["hpoa_projeto"] == pytest.approx(29.35, abs=0.01)
    assert c["desvios"]["hpoa_vs_projeto_pct"] > 0, "agosto teve mais sol do que o projeto supôs"


# ── o previsto pela meteorologia ─────────────────────────────────────────────


def test_previsto_de_origem_manual_sai_com_a_procedencia_escrita(cenario):
    """O meuWatt esconde este card quando a correção é a manual. Aqui ele aparece com a
    origem escrita: esconder do cliente um número que existe é pior do que mostrá-lo
    dizendo de onde veio. EARRAY 21.000 × (70 HPOA medidos ÷ 65 POA de projeto)."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(manual=_manual(poa=65.0, ghi=60.0))

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["previsto_origem"] == "manual_corrigido"
    assert c["previsto_kwh"] == pytest.approx(21000.0 * (70.0 / 65.0), rel=1e-6)
    assert c["projeto_kwh"] == 21000.0, "o EARRAY digitado é a fonte canônica do projeto"


def test_sem_meteo_de_projeto_o_previsto_e_o_pvsyst_diario(cenario):
    http, _, usina = cenario

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["previsto_origem"] == "pvsyst_diario"
    assert c["previsto_kwh"] == 9800.0, "na mesma janela do medido, não o mês inteiro"


def test_sem_projeto_nenhum_o_previsto_e_nulo(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(pvsyst={"rows": []}, manual={"year": 2026, "rows": []})

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["previsto_kwh"] is None and c["previsto_origem"] is None
    assert c["projeto_kwh"] is None
    assert c["desvios"]["medido_vs_projeto_pct"] is None


# ── o recorte ANO ────────────────────────────────────────────────────────────


def _range_do_ano() -> dict:
    """Junho e julho fechados, agosto em curso — a forma real de uma usina cuja série
    começa no meio do ano."""
    return _range(
        start_date="2026-01-01",
        end_date="2026-08-14",
        total_generation_kwh=30000.0,
        mensais=[
            {
                "month": "2026-06",
                "generation_kwh": 12000.0,
                "lost_kwh": 200.0,
                "lost_externa_kwh": 50.0,
                "availability_real_pct": 96.91,
                "availability_contratual_pct": 97.53,
            },
            {
                "month": "2026-07",
                "generation_kwh": 11000.0,
                "lost_kwh": 180.0,
                "lost_externa_kwh": 0.0,
                "availability_real_pct": 98.4,
                "availability_contratual_pct": 98.4,
            },
            {
                "month": "2026-08",
                "generation_kwh": 7000.0,
                "lost_kwh": 90.0,
                "lost_externa_kwh": 10.0,
                "availability_real_pct": 99.0,
                "availability_contratual_pct": 99.0,
            },
        ],
    )


def _mes_conferido(chave: str, disponibilidade: float, contratual: float) -> dict:
    """O `range` de UM mês, como o upstream o devolve — cabeçalho próprio, que é o que
    `/plants/{id}/desempenho` publica."""
    return _range(
        start_date=f"{chave}-01",
        availability_real_pct=disponibilidade,
        availability_contratual_pct=contratual,
    )


def test_a_disponibilidade_do_mes_no_ano_e_a_mesma_que_o_cliente_ve_no_mes(cenario):
    """O número de teor contratual não pode mudar conforme a aba.

    O `monthly_summaries` do `range` do ANO e o cabeçalho do `range` daquele MÊS discordam
    — medido em Porto Ferreira, agosto de 2026: 99,99 % contra 99,89 %. É o cabeçalho que
    o recorte `mes` mostra e que `/plants/{id}/desempenho` publica desde sempre; logo é ele
    que a linha do ano tem de repetir, senão o cliente lê dois números para o mesmo mês.
    """
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range_do_ano(),
        por_mes={
            6: _mes_conferido("2026-06", 96.91, 96.91),
            7: _mes_conferido("2026-07", 97.2, 99.74),
            8: _mes_conferido("2026-08", 99.89, 99.89),
        },
    )

    c = _painel(http, usina, recorte="ano", referencia="2026-08-14")
    meses = {m["mes"]: m for m in c["meses"]}

    assert meses["2026-08"]["disponibilidade_real_pct"] == 99.89, "o rollup dizia 99,0"
    assert meses["2026-07"]["disponibilidade_contratual_pct"] == 99.74
    assert meses["2026-06"]["disponibilidade_real_pct"] == 96.91
    assert meses["2026-01"]["disponibilidade_real_pct"] is None, "mês sem medição é ausência"
    assert meses["2026-06"]["medido_kwh"] == 12000.0


def test_o_acumulado_do_ano_usa_uma_janela_so(cenario):
    """`medido_inversores_kwh` do ano soma só os meses FECHADOS; a fronteira e a fatura
    acompanham. Somar a fronteira do ano inteiro poria dois acumulados de janelas
    diferentes na mesma faixa de cartões — e inventaria uma perda (aqui, negativa) do
    tamanho do mês em curso."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range_do_ano(),
        fronteira={6: 11.8, 7: 10.85, 8: 6.9},  # agosto está em curso
        faturas=[
            {"transformer_id": 11, "year": 2026, "month": mes, "billed_mwh": mwh}
            for mes, mwh in ((6, 11.75), (7, 10.8), (8, 6.85))
        ],
    )

    c = _painel(http, usina, recorte="ano", referencia="2026-08-14")

    assert c["medido_inversores_kwh"] == 23000.0, "junho + julho"
    assert c["medido_fronteira_kwh"] == 22650.0, "a mesma janela do medido"
    assert c["perda_inv_fronteira_pct"] == 1.52, "22,65 MWh de fronteira contra 23 MWh"
    assert c["fronteira_parcial"] is False
    assert c["conciliacao"]["fronteira_mwh"] == 22.65
    assert c["conciliacao"]["faturado_mwh"] == 22.55, "agosto ainda não tem fatura fechada"
    assert c["conciliacao"]["situacao"] == "Conciliado"


def test_o_ano_cheio_e_conferido_sem_travar_na_fila(cenario):
    """Doze meses medidos passam pelo portão de quatro em quatro — e chegam inteiros."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            start_date="2026-01-01",
            end_date="2026-08-14",
            mensais=[
                {"month": f"2026-{m:02d}", "generation_kwh": 1000.0 * m, "lost_kwh": 10.0,
                 "lost_externa_kwh": 0.0, "availability_real_pct": 90.0,
                 "availability_contratual_pct": 90.0}
                for m in range(1, 13)
            ],
        ),
        por_mes={m: _mes_conferido(f"2026-{m:02d}", 90.0 + m / 10, 95.0) for m in range(1, 13)},
    )

    meses = {
        m["mes"]: m
        for m in _painel(http, usina, recorte="ano", referencia="2026-08-14")["meses"]
    }

    # Agosto é o mês em curso e setembro em diante ainda não começou: sem leitura a fazer.
    for numero in range(1, 9):
        chave = f"2026-{numero:02d}"
        assert meses[chave]["disponibilidade_real_pct"] == 90.0 + numero / 10, chave
    assert meses["2026-09"]["disponibilidade_real_pct"] == 90.0, "futuro cai no rollup"


def test_so_os_meses_medidos_sao_conferidos(cenario):
    """Doze leituras por causa de uma tela seria pressão gratuita — e os meses anteriores
    ao início da série não têm o que conferir."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=_range_do_ano())

    _painel(http, usina, recorte="ano", referencia="2026-08-14")

    mensais = [
        c for c in caixa["cliente"].chamadas
        if c[0] == "range" and c[1].day == 1 and c[1].month == c[2].month
    ]
    assert sorted(c[1].month for c in mensais) == [6, 7, 8]


def test_mes_que_nao_responde_cai_no_rollup_em_vez_de_sumir(cenario):
    """A conferência é uma melhoria, não uma dependência: uma leitura que falha devolve a
    linha ao rollup, e a tabela do ano continua inteira."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range_do_ano(),
        por_mes={
            6: RuntimeError("o monitoramento não respondeu"),
            8: _mes_conferido("2026-08", 99.89, 99.89),
        },
    )

    meses = {
        m["mes"]: m
        for m in _painel(http, usina, recorte="ano", referencia="2026-08-14")["meses"]
    }

    assert meses["2026-06"]["disponibilidade_real_pct"] == 96.91, "veio do rollup"
    assert meses["2026-08"]["disponibilidade_real_pct"] == 99.89, "veio da conferência"


def test_o_acumulado_do_ano_soma_so_os_meses_fechados(cenario):
    """Somar o mês em curso compararia meio mês medido com o projeto inteiro dele e
    rebaixaria o ano sem que nada tivesse acontecido."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=_range_do_ano())

    c = _painel(http, usina, recorte="ano", referencia="2026-08-14")

    assert c["medido_inversores_kwh"] == 23000.0, "junho + julho; agosto está em curso"
    assert c["perdida_kwh"] == 380.0 and c["perdida_externa_kwh"] == 50.0
    assert c["totais"]["tendencia_kwh"] is None, "prever o passado não é previsão"


def test_o_ano_diz_quais_meses_tem_medicao_para_o_seletor_pular_os_vazios(cenario):
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=_range_do_ano())

    c = _painel(http, usina, recorte="ano", referencia="2026-08-14")

    assert c["meses_disponiveis"] == ["2026-06", "2026-07", "2026-08"]


def test_no_mes_a_lista_de_meses_e_nula_e_nao_vazia(cenario):
    """`[]` diria "nenhum mês tem dado" e apagaria o seletor. Nulo diz "não consultado
    neste recorte" — a informação chega de graça no recorte `ano`, e é de lá que a tela a
    lê, exatamente como o próprio meuWatt faz."""
    http, _, usina = cenario

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["meses_disponiveis"] is None


def _estados_por_dia(faixas: list[dict]) -> dict[str, str]:
    """Expande as faixas de volta em dia → estado.

    A resposta vem em FAIXAS (trechos contínuos no mesmo estado) porque dia a dia um ano de
    vinte inversores pesava 246 KB. O teste, porém, pergunta pelo dia: "o dia 5 está em falha
    de comunicação?". Expandir aqui mantém a asserção legível sem devolver o formato caro.
    """
    from datetime import date as _date, timedelta as _td

    saida: dict[str, str] = {}
    for faixa in faixas:
        dia = _date.fromisoformat(faixa["de"])
        fim = _date.fromisoformat(faixa["ate"])
        while dia <= fim:
            saida[dia.isoformat()] = faixa["estado"]
            dia += _td(days=1)
    return saida


def test_a_linha_do_tempo_por_inversor_vem_com_o_aviso_das_duas_reguas(cenario):
    """Publicar tempo de pé ao lado de disponibilidade energética sem dizer que são
    réguas diferentes entrega dois percentuais contraditórios num documento contratual."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            start_date="2026-01-01",
            timeline=[
                {
                    "sn": "SN2312090046",
                    "notification": "communication_error",
                    "started_at": "2026-08-05T09:00:00Z",
                    "resolved_at": "2026-08-05T20:00:00Z",
                    "duration_minutes": 660.0,
                    "estimated_loss_kwh": 300.0,
                    "day": "2026-08-05",
                    "day_loss_pct": 12.0,
                    "inverter_id": 2,
                    "status": 1,
                    "is_active": False,
                }
            ],
        )
    )

    tecnica = _painel(http, usina, recorte="ano", referencia="2026-08-14")["disponibilidade_tecnica"]

    assert "TÉCNICA" in tecnica["aviso"] and "energética" in tecnica["aviso"]
    assert (tecnica["primeiro_dia"], tecnica["ultimo_dia"]) == ("2026-01-01", "2026-08-14")
    nomes = [i["nome"] for i in tecnica["inversores"]]
    assert nomes == ["INV-01", "Inversor 2"], "etiqueta do slot, e a posição na falta dela"

    parado = next(i for i in tecnica["inversores"] if i["nome"] == "Inversor 2")
    estados = _estados_por_dia(parado["faixas"])
    assert estados["2026-08-05"] == "falha_comunicacao"
    assert estados["2026-08-06"] == "operando"
    assert estados["2026-01-10"] == "sem_dado", "dia sem medição não é dia verde"
    assert parado["disponibilidade_pct"] == pytest.approx(92.9, abs=0.1)


def test_a_linha_do_tempo_vem_em_faixas_e_nenhum_dia_se_perde(cenario):
    """Dia a dia, um ano de vinte inversores pesava 246 KB — mais do que o payload cru que
    este módulo existe para recortar, e com cinco mil repetições de "sem dado". Em faixas
    a mesma informação cabe em poucos quilobytes; o que não pode é sumir um dia."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=_range(start_date="2026-01-01"))

    tecnica = _painel(http, usina, recorte="ano", referencia="2026-08-14")["disponibilidade_tecnica"]

    for inversor in tecnica["inversores"]:
        assert sum(f["dias"] for f in inversor["faixas"]) == 226, "1/jan a 14/ago"
        assert len(inversor["faixas"]) <= 4, "sem incidente, o período inteiro são poucas faixas"
        for faixa in inversor["faixas"]:
            assert faixa["de"] <= faixa["ate"]


# ── o recorte não pode vazar as entranhas do meuWatt ─────────────────────────


def test_o_corpo_nao_carrega_serial_id_de_transformador_nem_bandeira_interna(cenario):
    """A promessa que justifica este módulo existir. `chart_data.daily_generation` é
    indexado por número de série, `transformers[].id` é chave do inventário de outro
    sistema e `implausivel_alta` é vocabulário interno — nenhum dos três diz nada ao dono
    da usina, e todos prenderiam a tela a um formato que não é nosso."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(
            start_date="2026-01-01",
            pr_flags=[{"t": "2026-08-05", "flag": "implausivel_alta", "pr_raw": 1.09}],
            timeline=[
                {
                    "sn": "SN2312090045",
                    "notification": "power_zero",
                    "started_at": "2026-08-05T09:00:00Z",
                    "resolved_at": None,
                    "duration_minutes": 660.0,
                    "estimated_loss_kwh": 300.0,
                    "day": "2026-08-05",
                    "day_loss_pct": 12.0,
                    "inverter_id": 1,
                    "status": 1,
                    "is_active": True,
                }
            ],
        )
    )

    for recorte in ("mes", "ano"):
        corpo = json.dumps(_painel(http, usina, recorte=recorte, referencia="2026-08-14"))
        assert "SN2312090045" not in corpo and "SN2312090046" not in corpo
        assert "transformer_id" not in corpo and "sn_transformer" not in corpo
        assert "daily_pr_flags" not in corpo and "implausivel_alta" not in corpo


# ── degradação: nada derruba a resposta ──────────────────────────────────────


def test_monitoramento_fora_do_ar_devolve_200_com_aviso_e_campos_nulos(cenario):
    """Uma tela de erro manda o cliente corporativo culpar a própria internet; uma tela de
    zeros diz que a usina não gerou. A terceira saída é dizer o que faltou."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(relatorio=RuntimeError("500 do upstream"))

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["medido_inversores_kwh"] is None
    assert c["pr_pct"] is None and c["disponibilidade_real_pct"] is None
    assert c["dias"] == [] and c["meses"] == []
    assert "500 do upstream" in c["aviso"]
    assert c["rotulo"] == "Agosto / 2026", "o período pedido continua identificado"


@pytest.mark.parametrize(
    ("campo", "trecho"),
    [
        ("pvsyst_resposta", "meta diária do projeto"),
        ("manual_resposta", "meta mensal do projeto"),
        ("fronteira_resposta", "medição na fronteira"),
        ("faturas_resposta", "faturas da distribuidora"),
    ],
)
def test_fonte_acessoria_fora_do_ar_tira_o_bloco_dela_e_escreve_o_aviso(
    cenario, campo, trecho
):
    http, caixa, usina = cenario
    cliente = ClienteFalso()
    setattr(cliente, campo, RuntimeError("indisponível"))
    caixa["cliente"] = cliente

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["medido_inversores_kwh"] == 9800.0, "o medido não depende do acessório"
    assert trecho in c["aviso"]


def test_periodo_sem_medicao_avisa_em_vez_de_publicar_zeros(cenario):
    """`days_with_data == 0` faz o upstream devolver `0.0` em todos os totais. Repassá-los
    diria que a usina não gerou nada, quando ninguém mediu."""
    http, caixa, usina = cenario
    caixa["cliente"] = ClienteFalso(
        relatorio=_range(dias_com_dado=0, energia_kwh=0.0, diarios=[], pr_diario=[])
    )

    c = _painel(http, usina, recorte="mes", referencia="2026-08-14")

    assert c["medido_inversores_kwh"] is None
    assert c["pr_pct"] is None
    assert c["disponibilidade_real_pct"] is None
    assert "não tem medição neste período" in c["aviso"]


# ── portaria ─────────────────────────────────────────────────────────────────


def test_usina_de_outro_cliente_nao_abre(cenario):
    http, _, _ = cenario
    outra = 999

    r = http.get(f"/api/v1/energia/usinas/{outra}/painel?recorte=mes")

    assert r.status_code == 404, "404 e não 403: 'proibido' confirmaria que ela existe"


def test_recorte_desconhecido_e_recusado(cenario):
    http, _, usina = cenario

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/painel?recorte=semana")

    assert r.status_code == 400


def test_referencia_futura_e_recusada(cenario):
    http, _, usina = cenario

    r = http.get(f"/api/v1/energia/usinas/{usina.id}/painel?referencia=2027-01-01")

    assert r.status_code == 400
