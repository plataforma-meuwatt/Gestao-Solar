"""As strings dos inversores no bot (o Renan, 25/11/2026: "o inversor 13 possui uma string a menos … a resposta da
diferença de geração entre inversores seria a mesma, porém, ele ia dizer que falta uma string, e considerando se
tivesse uma string a mais esse inversor iria gerar X e portanto estaria ok"). Os números são os do meuWatt de 25/11:
o Inv 13 de Pirapozinho com a 6S27 e a 6S28 zeradas desde 27/10 ou antes, 41 kWh de perda no dia."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import assistente_geracao as ger
from app.services import assistente_helper as h


def _string(n, status="ok", marca=None, zero_desde=None, perda=None):
    return {"number": n, "tag": f"6S{n}", "registered": True, "kwp": 18.2, "status": status, "mark": marca,
            "zero_since": zero_desde, "zero_since_before_window": bool(zero_desde), "loss_kwh_day": perda}


def _inv13(marca=None):
    return {"serial_number": "SN13", "slot_id": 127, "label": "Inv 13", "transformer_name": "TR-01", "loss_kwh_day": 41.0,
            "strings": [_string(n) for n in range(2, 20)]
            + [_string(27, "zero", marca, "2026-10-27", 20.5), _string(28, "zero", None, "2026-10-27", 20.5)]}


def test_um_dia_soma_a_perda_que_o_meuwatt_conta():
    dia = date(2026, 11, 25)
    r = ger._strings_na_comparacao(_inv13(), 369.31, 364.0, 1.127, dia, dia)
    assert r["energia_se_as_strings_gerassem_kwh"] == 410.3 and r["perda_das_strings_kwh"] == 41.0
    assert r["desvio_da_mediana_se_as_strings_gerassem_pct"] == 0.0
    assert r["strings_com_problema"] == ["6S27 zerada desde 27/10/2026 ou antes", "6S28 zerada desde 27/10/2026 ou antes"]
    assert "perda_ja_sabida_kwh" not in r
    marcado = ger._strings_na_comparacao(_inv13({"ignored": True, "note": "falta uma string"}), 369.31, 364.0, 1.127,
                                         dia, dia)
    assert marcado["perda_ja_sabida_kwh"] == 20.5
    assert marcado["strings_com_problema"][0] == "6S27 zerada desde 27/10/2026 ou antes (a equipe marcou «já sei»: falta uma string)"


def test_varios_dias_so_estima_com_as_strings_paradas_o_periodo_todo():
    r = ger._strings_na_comparacao(_inv13(), 3600.0, 364.0, 11.0, date(2026, 11, 1), date(2026, 11, 10))
    assert r["energia_se_as_strings_gerassem_kwh"] == 4000.0 and "18 de 20" in r["como"]   # 20/18 da energia
    antes = ger._strings_na_comparacao(_inv13(), 3600.0, 364.0, 11.0, date(2026, 10, 1), date(2026, 11, 10))
    assert "energia_se_as_strings_gerassem_kwh" not in antes and antes["strings_com_problema"]   # parou no meio


def test_inversor_sem_string_com_problema_nao_ganha_campo():
    ok = {**_inv13(), "strings": [_string(n) for n in range(2, 22)], "loss_kwh_day": 0}
    assert ger._strings_na_comparacao(ok, 410.0, 364.0, 1.127, date(2026, 11, 25), date(2026, 11, 25)) == {}


async def test_geracao_diz_as_strings_e_quando_nao_leu(monkeypatch):
    async def _range(ctx, u, ini, fim, c):
        return {"inverters": [{"slot_label": "Inv 13", "sn": "SN13", "total_yield_kwh": 369.31, "capacity_kwp": 364.0},
                              {"slot_label": "Inv 22", "sn": "SN22", "total_yield_kwh": 414.6, "capacity_kwp": 364.0}]}

    async def _strings(ctx, slug, dia):
        return {"SN13": _inv13()}

    monkeypatch.setattr(ger, "_range", _range)
    monkeypatch.setattr(ger, "_strings_por_inversor", _strings)
    ctx = ger.Contexto(db=None, user=SimpleNamespace(id=1), telefone="", mw=SimpleNamespace(),
                       usinas={"pirapozinho": {"id": 1, "nome": "Pirapozinho", "slug": "pirapozinho", "estacao": False}})
    r = await ger.geracao(ctx, {"usina": "pirapozinho", "inicio": "2026-11-20", "fim": "2026-11-20"})
    inv13 = next(i for i in r["inversores_do_melhor_ao_pior"] if i["inversor"] == "Inv 13")
    assert inv13["energia_se_as_strings_gerassem_kwh"] == 410.3 and r["nota_strings"]
    assert "strings_com_problema" not in r["inversores_do_melhor_ao_pior"][0]       # o Inv 22, sem string parada

    async def _sem(ctx, slug, dia):
        return "sem as strings do meuWatt agora"
    monkeypatch.setattr(ger, "_strings_por_inversor", _sem)
    r = await ger.geracao(ctx, {"usina": "pirapozinho", "inicio": "2026-11-20", "fim": "2026-11-20"})
    assert r["strings"] == "sem as strings do meuWatt agora"                         # dito, nunca esquecido calado


class _MW:
    def __init__(self, pode=True, marca=None):
        self.pode, self.marca, self.pedidos, self.problemas = pode, marca, [], []

    async def gemeo_pendencias(self, plant_id):
        return [{"titulo": t, "status": "aberta"} for t in self.problemas]

    async def gemeo_problema_criar(self, plant_id, titulo, problema, origem):
        self.problemas.append(titulo)
        return {"id": len(self.problemas), "titulo": titulo, "status": "aberta"}

    async def strings_por_vaga(self, slug):
        return {"can_mark": self.pode, "inverters": [_inv13(self.marca),
                {"serial_number": "SN12", "slot_id": 171, "label": "Inv 12", "strings": [_string(2)]}]}

    async def marcar_leitura(self, *args, **kw):
        self.pedidos.append((*args, kw.get("equipamento")))


def _ctx(uid, mw):
    user = SimpleNamespace(id=uid, senha_atuacao_hash=None, bot_ativo=["bot_meuwatt"], apelido="renan.marquezini")
    return ger.Contexto(db=None, user=user, telefone="+5517997377626", mw=mw,
                        usinas={"pirapozinho": {"id": 9376, "nome": "Pirapozinho", "slug": "pirapozinho"}})


@pytest.fixture
def grava(monkeypatch):
    g = _MW()
    monkeypatch.setattr("app.services.vinculos.cliente_meuwatt", lambda db, uid, so_proprio=False: g)
    return g


async def test_uma_string_a_menos_com_duas_zeradas_pergunta_quais(grava):
    with pytest.raises(ger.Recusa, match="mede 2") as e:
        await ger.marcar_strings(_ctx(9301, _MW()), {"usina": "pirapozinho", "inversor": "inversor 13", "quantas": 1,
                                                     "observacao": "o inversor 13 possui uma string a menos"})
    assert "6S27 zerada" in str(e.value) and "6S28 zerada" in str(e.value) and "defeito para ver em campo" in str(e.value)
    assert 9301 not in h.PENDENTES and grava.pedidos == []


async def test_marca_a_string_dita_na_vaga_do_inversor(grava):
    ctx = _ctx(9302, _MW())
    r = await ger.marcar_strings(ctx, {"usina": "pirapozinho", "inversor": "13", "strings": ["6S27"],
                                       "observacao": "o inversor 13 possui uma string a menos"})
    assert r["proposta_pendente"] == "Marcar «já sei» no meuWatt: Inv 13 · 6S27 (Pirapozinho)"
    p = h.PENDENTES.pop(9302)
    fim = await p.executar(None, ctx.user, ctx.telefone)
    assert grava.pedidos == [("pirapozinho", 127, "string_27", True, "o inversor 13 possui uma string a menos", None,
                              "inverter")]
    assert fim.startswith("✅ Inv 13 · 6S27 (Pirapozinho): marcado «já sei»")
    assert grava.problemas == ["Inv 13 · 6S27: o inversor 13 possui uma string a menos"]          # e na lista do Gêmeos
    assert fim.endswith("✅ Registrado como problema conhecido (Pirapozinho): Inv 13 · 6S27: o inversor 13 possui uma "
                        "string a menos.")


async def test_sem_strings_marca_as_duas_zeradas_e_mantem_a_nota_da_tela(grava):
    grava.marca = {"ignored": False, "note": "fusível queimado", "expires_at": None}
    ctx = _ctx(9303, _MW())
    r = await ger.marcar_strings(ctx, {"usina": "pirapozinho", "inversor": "Inv 13"})
    assert r["proposta_pendente"] == "Marcar «já sei» no meuWatt: Inv 13 · 6S27 e 6S28 (Pirapozinho)"
    await h.PENDENTES.pop(9303).executar(None, ctx.user, ctx.telefone)
    assert [x[2] for x in grava.pedidos] == ["string_27", "string_28"]
    assert grava.pedidos[0][4] == "fusível queimado" and grava.pedidos[1][4] is None   # cada string fica com a dela


async def test_recusas_antes_do_sim(grava):
    with pytest.raises(ger.Recusa, match="não marca leituras"):
        await ger.marcar_strings(_ctx(9304, _MW(pode=False)), {"usina": "pirapozinho", "inversor": "13"})
    with pytest.raises(ger.Recusa, match="não está ligada"):
        await ger.marcar_strings(_ctx(9305, _MW()), {"usina": "pirapozinho", "inversor": "13", "strings": ["6S25"]})
    with pytest.raises(ger.Recusa, match="não mede string zerada"):
        await ger.marcar_strings(_ctx(9306, _MW()), {"usina": "pirapozinho", "inversor": "12"})
    with pytest.raises(ger.Recusa, match="Não achei o inversor"):
        await ger.marcar_strings(_ctx(9307, _MW()), {"usina": "pirapozinho", "inversor": "Inv 99"})
    with pytest.raises(ger.Recusa, match="mede 2"):                               # "1" como texto também vale
        await ger.marcar_strings(_ctx(9308, _MW()), {"usina": "pirapozinho", "inversor": "INV-013", "quantas": "1"})
    assert grava.pedidos == [] and not {9304, 9305, 9306, 9307, 9308} & set(h.PENDENTES)


async def test_string_a_menos_nao_pega_a_fraca(grava):
    """Sem dizer quais, só as ZERADAS: a fraca só entra dita pelo nome (avaliador, 25/11)."""
    class Fraca(_MW):
        async def strings_por_vaga(self, slug):
            return {"can_mark": True, "inverters": [{"serial_number": "SN12", "slot_id": 171, "label": "Inv 12",
                                                     "strings": [_string(2), _string(25, "weak")]}]}
    with pytest.raises(ger.Recusa, match="não mede string zerada") as e:
        await ger.marcar_strings(_ctx(9309, Fraca()), {"usina": "pirapozinho", "inversor": "12", "quantas": 1})
    assert "6S25 fraca" in str(e.value) and 9309 not in h.PENDENTES
    ctx = _ctx(9310, Fraca())
    r = await ger.marcar_strings(ctx, {"usina": "pirapozinho", "inversor": "12", "strings": ["6S25"]})
    assert r["proposta_pendente"] == "Marcar «já sei» no meuWatt: Inv 12 · 6S25 (Pirapozinho)"
    h.PENDENTES.pop(9310)


def test_inversor_sem_dado_nunca_vira_nenhuma_string():
    sem = {"serial_number": "SN4", "label": "Inv 4", "no_data": True, "strings": [_string(n) for n in range(2, 22)]}
    r = ger._strings_na_comparacao(sem, 0.0, 364.0, 1.12, date(2026, 11, 25), date(2026, 11, 25))
    assert r == {"strings_sem_dado": ger.SEM_DADO_DAS_STRINGS}


async def test_leituras_mostra_o_inversor_sem_dado(monkeypatch):
    async def _strings(ctx, slug, dia):
        return {"SN4": {"label": "Inv 4", "transformer_name": "TR-01", "no_data": True, "strings": []},
                "SN13": _inv13()}

    class MW:
        async def leituras(self, slug):
            return {"relays": []}

        async def monitoramento_atual(self, slug):
            from datetime import UTC, datetime, timedelta
            return {"data_at": (datetime.now(UTC) - timedelta(minutes=77)).isoformat()}
    monkeypatch.setattr(ger, "_strings_por_inversor", _strings)
    ctx = ger.Contexto(db=None, user=SimpleNamespace(id=1), telefone="", mw=MW(),
                       usinas={"p": {"id": 1, "nome": "Pirapozinho", "slug": "p"}})
    r = await ger.leituras_usina(ctx, {"usina": "p"})
    assert r["strings"][0] == {"inversor": "Inv 4", "skid": "TR-01", "strings": [ger.SEM_DADO_DAS_STRINGS]}
    assert r["strings"][1]["inversor"] == "Inv 13" and "o dia ainda não fechou" in r["strings_do_dia"]
    assert ", das " in r["strings_do_dia"] and "há 77 min" in r["aviso"]          # a hora do dado, e velho


def test_dado_velho_do_meuwatt_nao_e_agora():
    from datetime import UTC, datetime, timedelta
    agora = datetime.now(UTC)
    assert ger.dado_velho((agora - timedelta(minutes=5)).isoformat()) is None
    velho = ger.dado_velho((agora - timedelta(minutes=46)).isoformat())
    assert "há 46 min" in velho and "não diga 'agora'" in velho
    assert "não disse de quando" in ger.dado_velho(None)


async def test_geracao_com_dado_velho_nao_afirma_sem_falha(monkeypatch):
    from datetime import UTC, datetime, timedelta

    async def _range(ctx, u, ini, fim, c):
        return {"inverters": [{"slot_label": "Inv 13", "sn": "SN13", "total_yield_kwh": 369.31, "capacity_kwp": 364.0,
                               "is_faulty": False}]}

    async def _strings(ctx, slug, dia):
        return {}

    class MW:
        async def monitoramento_atual(self, slug):
            return {"energy_today_kwh": 4047.8, "inverters": [{"active_power": 568200}], "faulty_inverters": [],
                    "data_at": (datetime.now(UTC) - timedelta(minutes=46)).isoformat()}
    monkeypatch.setattr(ger, "_range", _range)
    monkeypatch.setattr(ger, "_strings_por_inversor", _strings)
    ctx = ger.Contexto(db=None, user=SimpleNamespace(id=1), telefone="", mw=MW(),
                       usinas={"p": {"id": 1, "nome": "Pirapozinho", "slug": "p", "estacao": False}})
    r = await ger.geracao(ctx, {"usina": "p"})
    assert r["agora"]["inversores_com_falha"] is None and r["agora"]["potencia_agora_kw"] is None
    assert "há 46 min" in r["agora"]["aviso"] and r["inversores_do_melhor_ao_pior"][0]["com_falha"] is None


def test_so_com_as_ja_sabidas_a_parte_que_falta_por_projeto():
    """O Renan marca «já sei» só na string que falta por projeto: o bot diz o que o inversor geraria só com ela; a
    perda que sobra (a outra zerada) é defeito (avaliador 2, 25/11)."""
    dia = date(2026, 11, 25)
    r = ger._strings_na_comparacao(_inv13({"ignored": True, "note": "falta uma string"}), 369.31, 364.0, 1.127, dia, dia)
    assert r["energia_se_as_strings_gerassem_kwh"] == 410.3 and r["energia_com_as_ja_sabidas_kwh"] == 389.8
    assert r["desvio_da_mediana_com_as_ja_sabidas_pct"] == -5.0
    duas = _inv13()
    for x in duas["strings"][-2:]:
        x["mark"] = {"ignored": True}
    assert "energia_com_as_ja_sabidas_kwh" not in ger._strings_na_comparacao(duas, 369.31, 364.0, 1.127, dia, dia)
    varios = ger._strings_na_comparacao(_inv13({"ignored": True}), 3600.0, 364.0, 11.0, date(2026, 11, 1), date(2026, 11, 10))
    assert varios["energia_com_as_ja_sabidas_kwh"] == 3800.0                     # 19 de 18 strings, pela potência


async def test_a_etiqueta_propria_vale_antes_do_numero(grava):
    class Etiqueta(_MW):
        async def strings_por_vaga(self, slug):
            inv = _inv13()
            inv["strings"][-1]["tag"] = "U1-3S22"                                # a string 28 com etiqueta da planta
            return {"can_mark": True, "inverters": [inv]}
    ctx = _ctx(9311, Etiqueta())
    r = await ger.marcar_strings(ctx, {"usina": "pirapozinho", "inversor": "13", "strings": ["u1-3s22"]})
    assert r["proposta_pendente"] == "Marcar «já sei» no meuWatt: Inv 13 · U1-3S22 (Pirapozinho)"
    await h.PENDENTES.pop(9311).executar(None, ctx.user, ctx.telefone)
    assert grava.pedidos[-1][2] == "string_28"                                   # nunca a string_22



async def test_problemas_conhecidos_le_o_gemeo_e_os_ja_sei(monkeypatch):
    """O Renan, 25/11: "pendências é um termo do meuPlano … para o meuWatt quero outro nome" (problemas conhecidos), e o
    bot os lê das duas fontes: a lista do Gêmeos e os «já sei» da tela Leituras."""
    import httpx

    async def _strings(ctx, slug, dia):
        return {"SN13": _inv13({"ignored": True, "note": "falta uma string"})}

    class MW:
        negar = False

        async def gemeo_pendencias(self, pid):
            if self.negar:
                raise httpx.HTTPStatusError("x", request=httpx.Request("GET", "http://a"), response=httpx.Response(403))
            return [{"titulo": "Recuo a mais dos trackers", "status": "aberta", "problema": "fileiras a 6,5 m",
                     "servicos": [{"tipo": "ajuste_trackers", "resultado": "parcial"}]}]

        async def leituras(self, slug):
            return {"relays": [{"name": "Relé Skid 3", "readings": [
                {"key": "voltage_a", "label": "Tensão fase A", "mark": {"ignored": True, "note": "TP com defeito"}},
                {"key": "current_a", "label": "Corrente fase A", "mark": None}]}]}

    monkeypatch.setattr(ger, "_strings_por_inversor", _strings)
    mw = MW()
    ctx = ger.Contexto(db=None, user=SimpleNamespace(id=1), telefone="", mw=mw,
                       usinas={"p": {"id": 7, "nome": "Pirapozinho", "slug": "p"}})
    r = await ger.problemas_conhecidos(ctx, {"usina": "p"})
    assert r["lista_do_gemeo"][0]["titulo"] == "Recuo a mais dos trackers"
    assert r["lista_do_gemeo"][0]["servicos"][0] == {"servico": "ajuste dos trackers", "o_que_foi_feito": None,
                                                     "os_meuplano": None, "feito_em": None, "deu_resultado": "em parte",
                                                     "anotacao": None}
    assert r["ja_sei_nas_leituras"] == ["Relé Skid 3 · Tensão fase A: já sei (TP com defeito)",
                                        "Inv 13 · 6S27 zerada desde 27/10/2026 ou antes (a equipe marcou «já sei»: falta "
                                        "uma string)"]
    mw.negar = True                                                   # sem acesso ao Gêmeos: diz, e os «já sei» ficam
    r = await ger.problemas_conhecidos(ctx, {"usina": "p"})
    assert "equipe da plataforma" in r["lista_do_gemeo"] and len(r["ja_sei_nas_leituras"]) == 2
    assert await ger.conhecidos_abertos(ctx, {"id": 7}) is None
    mw.negar = False
    assert await ger.conhecidos_abertos(ctx, {"id": 7}) == ["Recuo a mais dos trackers: fileiras a 6,5 m"]


async def test_registrar_problema_conhecido_com_o_sim_sem_duplicar(grava):
    ctx = _ctx(9312, _MW())
    ctx.user.apelido = "renan.marquezini"
    r = await ger.registrar_problema_conhecido(ctx, {"usina": "pirapozinho", "titulo": "Trafo 2 esquenta mais",
                                                     "problema": "10 °C acima do TR-01 na mesma carga"})
    assert r["proposta_pendente"] == "Registrar como problema conhecido no meuWatt (Pirapozinho): Trafo 2 esquenta mais"
    p = h.PENDENTES.pop(9312)
    assert (await p.executar(None, ctx.user, ctx.telefone)).startswith("✅ Registrado como problema conhecido")
    assert grava.problemas == ["Trafo 2 esquenta mais"]
    ctx = _ctx(9313, _MW())
    ctx.user.apelido = "renan.marquezini"
    await ger.registrar_problema_conhecido(ctx, {"usina": "pirapozinho", "titulo": "trafo 2 esquenta mais"})
    assert "já estava" in await h.PENDENTES.pop(9313).executar(None, ctx.user, ctx.telefone)
    assert grava.problemas == ["Trafo 2 esquenta mais"]                         # o mesmo título aberto não duplica
    with pytest.raises(ger.Recusa, match="título"):
        await ger.registrar_problema_conhecido(_ctx(9314, _MW()), {"usina": "pirapozinho", "titulo": " "})


async def test_registrar_de_quem_so_acompanha_diz_a_recusa():
    import httpx

    class Nega:
        async def gemeo_pendencias(self, pid):
            return []

        async def gemeo_problema_criar(self, *a):
            raise httpx.HTTPStatusError("x", request=httpx.Request("POST", "http://a"), response=httpx.Response(403))
    assert "só quem opera a usina" in await ger._registrar(Nega(), 7, "Pirapozinho", "x", "", "bot")
