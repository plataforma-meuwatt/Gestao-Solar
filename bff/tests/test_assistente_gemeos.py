"""Gêmeo digital no bot (dono, 06/11/2026: "faça o bot saber tudo dos gêmeos, qualquer pergunta que eu fizer ele
responde"). O gêmeo mora no módulo de análise do meuWatt; o bot lê com o token da pessoa e resume para a IA."""

import json

import httpx
import pytest

from app.services import assistente_geracao as ger


def _erro(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://analise.meuwatt.test/gemeos/9371")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(status, request=req))


MES = {
    "estacao": "ws-ufv-ibitinga-1", "ficha": {"modelo_modulo": "um diodo do PVsyst (x.PAN)", "modelo_inversor": "curva do .OND (y.ond)",
                                         "geometria": "Tracker ±55°, GCR 20%", "geometria_pdf": {"gcr": 0.2, "fileiras_m": 6.5, "largura_m": 1.3},
                                         "geometria_real": {"gcr": 0.367, "max_angle": 57.0, "fileiras_m": 6.5, "largura_m": 2.384, "fonte": "campo"},
                                         "geometria_controlador": {"gcr": 0.436, "max_angle": 57.0, "fileiras_m": 5.5, "largura_m": 2.4, "fonte": "controladores"}},
    "resumo": {"real_mwh": 169.5, "previsto_mwh": 196.5, "pvsyst_mwh": 249.2, "regua_mwh": 244.5, "desvio_previsto_pct": -13.7,
               "efeito_regua_mwh": -4.7, "efeito_clima_mwh": -50.4, "efeito_geometria_mwh": -2.6, "efeito_limitacao_mwh": 2.4,
               "efeito_trackers_mwh": -1.6, "poa_trackers": 185.7, "efeito_plano_mwh": -8.7,
               "efeito_paradas_mwh": -0.06, "efeito_conversao_mwh": -16.7, "efeito_usina_mwh": -27.0, "parte_clima_pct": 63,
               "incerteza_regua_pct": -1.87, "incerteza_regua_mwh": 4.7, "poa_real": 176.2, "poa_tempo": 189.6, "poa_pvsyst": 233.9,
               "ghi_real": 155.8, "ghi_pvsyst": 173.6, "t_amb_media": 24.3, "t_amb_pvsyst": 23.9, "pr_real": 0.746,
               "pr_pvsyst": 0.826, "corte_mwh": 19.4, "dias_travados": 0, "paradas": {"n": 2, "minutos": 51},
               "inmet": {"codigo": "A737", "nome": "IBITINGA", "km": 11.1, "dias": 1},
               "tratamentos": [{"dia": "2026-10-25", "sol": None, "sol_kwh_m2": None, "energia": None, "energia_kwh": None,
                                "descartar": True, "motivo": "coleta parada", "aviso": None}],
               "dias_na_conta": 30, "dias_do_mes": 31,
               "fonte_sol": {"margem_pct": 3.2, "dentro_da_margem": False, "margens": {"estacao": 3.0, "inmet": 10.0, "open-meteo": 20.0},
                             "fontes": [{"tipo": "estacao", "dias": 30, "margem_pct": 3.0},
                                        {"tipo": "inmet", "codigo": "A737", "cidade": "Ibitinga", "km": 11.1, "dias": 1, "margem_pct": 10.0}]}},
    "hora_a_hora": {"leitura": {"tipo": "sol_direto", "titulo": "A perda cresce com o sol direto…", "inversor": None},
                    "perfil": [{"hora": 9, "pct": -8.0, "pct_fora_limite": -10.5}, {"hora": 5, "pct": None, "pct_fora_limite": None}],
                    "rendimento": [{"dia": "2026-10-22", "pct": -1.7, "chuva_mm": 6.6, "minutos": 385, "inversores": {}},
                                   {"dia": "2026-10-23", "pct": None, "chuva_mm": 0.0, "minutos": 0, "inversores": {}}]},
    "dias": [{"dia": "2026-10-01", "previsto_kwh": 2580, "real_kwh": 2260, "desvio_pct": -12.4, "poa": 2.1, "corte_kwh": 10, "paradas_n": 0,
              "poa_fonte": "estacao"},
             {"dia": "2026-10-02", "previsto_kwh": 0, "real_kwh": 0, "desvio_pct": None, "poa": 0.0, "corte_kwh": 0, "paradas_n": 0,
              "poa_fonte": "inmet", "inmet_estacao": "A737"}],
    "inversores": [{"sn": "ES1", "rotulo": "Inv 1", "real_kwh": 42659, "previsto_kwh": 49601, "desvio_pct": -14.0,
                    "paradas_n": 2, "paradas_kwh": 27.8}],
    "limites": {"projeto_kw": 1000.0, "usina_configurado_kw": 1027.0, "usina_teto_medido_kw": None, "dias": [
        {"dia": "2026-10-30", "inversores": {"ES1": {"limite_kw": 252.5, "comando_kw": 252.5, "fonte": "leitura"}}},
        {"dia": "2026-10-31", "inversores": {"ES1": {"limite_kw": 252.5, "comando_kw": None, "fonte": "modelo"}}}]},
    "paradas": [{"inversor": "Inv 1", "ini": "2026-10-08T16:39:00-03:00", "minutos": 7, "perda_kwh": 27.7},
                {"inversor": "Inv 1", "ini": "2026-10-13T16:45:00-03:00", "minutos": 3, "perda_kwh": 0.1}],
}


class _GemeoFalso:
    def __init__(self, erro: int | None = None):
        self.erro = erro
        self.pedidos: list = []

    async def gemeo_mes(self, plant_id, mes):
        self.pedidos.append((plant_id, mes))
        if self.erro:
            raise _erro(self.erro)
        return MES

    async def gemeos(self):
        return [{"plant_id": 9371, "nome": "Ibitinga"}, {"plant_id": 9378, "nome": "Porto Ferreira"}]

    async def gemeo_pendencias(self, plant_id):
        self.pedidos.append(("pendencias", plant_id))
        return [{"id": 1, "titulo": "Recuo a mais nos trackers", "status": "aberta", "problema": "controlador com 5,50 m",
                 "origem": "Gêmeo · out/2026: −1,6 MWh", "criada_em": "2026-11-07T20:00:00+00:00",
                 "servicos": [{"tipo": "ajuste_trackers", "descricao": "650 cm nos 8 controladores", "os_meuplano": "1901",
                               "feito_em": "2026-11-10", "resultado": "deu_bom", "anotacao": "ângulo das 06:30 subiu"},
                              {"tipo": "lavagem", "descricao": "", "os_meuplano": None, "feito_em": None, "resultado": None, "anotacao": ""}]}]

    async def gemeo_dia(self, plant_id, dia):
        return {"kwac": 1027.0, "horas": [
            {"hora": 10, "previsto_kwh": 900.0, "real_kwh": 800.0, "desvio_pct": -11.1, "poa_wh": 700, "poa_tempo_wh": 760,
             "t_amb": 30.1, "t_cel_max": 52.0, "corte_kwh": 0.0, "paradas_kwh": 0.0},
            {"hora": 11, "previsto_kwh": 1000.0, "real_kwh": None, "desvio_pct": None, "poa_wh": 800, "poa_tempo_wh": 820,
             "t_amb": 31.0, "t_cel_max": 55.0, "corte_kwh": 20.0, "paradas_kwh": 0.0}]}


def _ctx(mw):
    return ger.Contexto(db=None, user=None, telefone="+5517997377626", mw=mw, usinas={
        "ibitinga": {"id": 9371, "nome": "Ibitinga", "slug": "ibitinga"},
        "pirapozinho": {"id": 9376, "nome": "Pirapozinho", "slug": "pirapozinho"}})


async def test_o_mes_no_gemeo_resumido_para_a_ia():
    mw = _GemeoFalso()
    r = await ger.gemeo(_ctx(mw), {"usina": "ibiti", "mes": "2026-10"})
    assert mw.pedidos == [(9371, "2026-10")]                           # o id numérico do meuWatt, não o slug
    assert r["placar_mwh"] == {"real": 169.5, "previsto_pelo_gemeo": 196.5, "pvsyst": 249.2, "gemeo_no_ano_tipico_regua": 244.5}
    assert r["cascata_mwh"]["conversao"] == -16.7 and r["parte_clima_pct"] == 63
    assert r["cascata_mwh"]["geometria"] == -2.6 and r["geometria"]["construida"]["gcr"] == 0.367
    assert r["cascata_mwh"]["recuo_a_mais"] == -1.6 and r["geometria"]["controlador"]["fileiras_m"] == 5.5   # o controlador com 5,50 m
    assert r["sol_kwh_m2"]["no_plano_com_o_recuo_do_controlador"] == 185.7
    assert r["hora_a_hora"]["leitura"]["tipo"] == "sol_direto"
    assert r["hora_a_hora"]["por_hora_fora_do_limite_pct"] == {9: -10.5}           # hora sem dado não vira zero
    assert [x["dia"] for x in r["hora_a_hora"]["rendimento_por_dia_pct"]] == ["22"]
    assert [x["dia"] for x in r["dias"]] == ["01"]                                  # dia sem nada fica de fora
    assert r["limites"]["por_inversor"] == [{"inversor": "Inv 1", "limite_kw": 252.5, "comando_lido_kw": 252.5, "fonte": "leitura"}]
    assert r["paradas"]["maiores"][0] == {"inversor": "Inv 1", "inicio": "10-08 16:39", "minutos": 7, "perda_kwh": 27.7}
    assert "Números só daqui" in r["como_explicar"]
    # de onde veio o sol e a margem de erro do mês: o que o módulo decidiu (o mesmo do relatório)
    f = r["fonte_do_sol"]
    assert f["fontes"] == [{"fonte": "estação solarimétrica da usina", "dias": 30, "margem_pct": 3.0},
                           {"fonte": "estação do INMET em Ibitinga (A737, a 11.1 km da usina)", "dias": 1, "margem_pct": 10.0}]
    assert f["margem_de_erro_do_mes_pct"] == 3.2 and f["dentro_da_margem"] is False and "INMET ±10.0%" in f["como_ler"]
    t = r["dias_tratados"]
    assert t["dias"] == [{"dia": "2026-10-25", "o_que": ["fora da conta"], "motivo": "coleta parada", "aviso": None}]
    assert (t["dias_na_conta"], t["dias_do_mes"]) == (30, 31)
    assert len(json.dumps(r, ensure_ascii=False)) < ger_teto()


def ger_teto() -> int:
    from app.services import assistente
    return assistente.TETO_RESULTADO


async def test_quem_nao_e_da_plataforma_e_usina_sem_gemeo():
    with pytest.raises(ger.Recusa, match="só da equipe da plataforma"):
        await ger.gemeo(_ctx(_GemeoFalso(erro=403)), {"usina": "ibitinga", "mes": "2026-10"})
    with pytest.raises(ger.Recusa, match=r"Pirapozinho não tem gêmeo digital \(têm: Ibitinga, Porto Ferreira\)"):
        await ger.gemeo(_ctx(_GemeoFalso(erro=404)), {"usina": "pirapozinho", "mes": "2026-10"})
    with pytest.raises(ger.Recusa, match="ainda não começou"):
        await ger.gemeo(_ctx(_GemeoFalso()), {"usina": "ibitinga", "mes": "2099-01"})
    with pytest.raises(httpx.HTTPStatusError):                       # 500 sobe: o laço do bot diz o erro, não inventa
        await ger.gemeo(_ctx(_GemeoFalso(erro=500)), {"usina": "ibitinga", "mes": "2026-10"})


async def test_o_dia_hora_a_hora():
    r = await ger.gemeo_dia(_ctx(_GemeoFalso()), {"usina": "ibitinga", "dia": "2026-10-17"})
    assert r["dia"] == "2026-10-17" and r["potencia_maxima_kw"] == 1027.0
    assert r["total"] == {"previsto_kwh": 1900, "real_kwh": 800, "desvio_pct": -57.9}
    assert r["horas"][1]["real_kwh"] is None                         # hora sem leitura fica nula, não zero


async def test_pendencias_do_gemeo_para_a_ia():
    """A caixa de conteúdo: o problema, os serviços com a OS do meuPlano e o "deu bom / não deu bom" anotado."""
    mw = _GemeoFalso()
    r = await ger.gemeo_pendencias(_ctx(mw), {"usina": "ibiti"})
    assert mw.pedidos == [("pendencias", 9371)]
    p = r["pendencias"][0]
    assert (p["titulo"], p["situacao"], p["criada_em"]) == ("Recuo a mais nos trackers", "aberta", "2026-11-07")
    assert p["servicos"][0] == {"servico": "ajuste dos trackers", "o_que_foi_feito": "650 cm nos 8 controladores", "os_meuplano": "1901",
                                "feito_em": "2026-11-10", "deu_resultado": "deu bom", "anotacao": "ângulo das 06:30 subiu"}
    assert p["servicos"][1]["deu_resultado"] == "não anotado" and p["servicos"][1]["o_que_foi_feito"] is None
