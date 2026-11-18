"""O motor de séries do bot (`assistente_series`): o dono, 17/11/2026, "Gere um gráfico da potência do relé com a
potência dos inversores de Pirapozinho do skid 1", "Plote o gráfico da string 1 do inversor 1 do skid 1 com a string 10
do inversor 2 do skid 3", "gráfico da resistência de isolação, temperatura do trafo com potência do inversor 2 e 3 …
gráfico de barra com potências diárias, energias … Análises". As formas abaixo são as das consultas do meuWatt em
Pirapozinho (17/11/2026), encolhidas."""

import types
from datetime import date, datetime

import pytest

from app.api.v1 import mcp
from app.core.datas import BRT
from app.clients import whatsapp
from app.services import assistente_catalogo as cat
from app.services import assistente_geracao as ger
from app.services import assistente_series as ser

DIA = date(2026, 11, 17)
HORAS = [f"{h:02d}:{m:02d}" for h in range(6, 18) for m in (0, 30)]
SERIAIS = {"S12": 1.0, "S11": 0.9, "S13": 0.95, "S32": 0.8}

# GET /plants/{slug}/charts/intraday — por instante: cada ponto traz os inversores pelo número de série
INTRADAY = {"plant": "Pirapozinho", "date": "2026-11-17", "total_capacity_kwp": 3640.0, "points": [
    {"time": h, "ghi": 500, "poa": 600, "inverters": [
        {"serial_number": sn, "power_kw": round(250 * f * (1 - abs(12 - int(h[:2])) / 7), 1), "daily_gen_kwh": 1.0,
         "temperature": None} for sn, f in SERIAIS.items()]} for h in HORAS]}
# GET /plants/{slug}/charts/intraday/strings — a corrente de cada string numa lista (pv1…)
STRINGS = {"plant": "Pirapozinho", "date": "2026-11-17", "points": [
    {"time": h, "inverters": [{"serial_number": sn, "strings": [round(8 * f - k * 0.1, 2) for k in range(12)],
                               "mppts": []} for sn, f in SERIAIS.items()]} for h in HORAS]}
# GET /plants/{slug}/charts/intraday/relay — por equipamento: cada relé com os seus pontos
RELES = {"plant": "Pirapozinho", "date": "2026-11-17", "relays": [
    {"id": f"relay-{n}", "name": nome, "points": [
        {"time": h, "voltage_a": 7833.8, "current_a": 10.0, "active_power_a": 80.0, "active_power_b": None,
         "total_active_power": round(1000 * (1 - abs(12 - int(h[:2])) / 7), 1) * (1 if n == 17 else 0.25)}
        for h in HORAS]} for n, nome in ((17, "Relé Geral"), (18, "Relé Skid 1"), (19, "7SR10 Skid 3"))]}
# GET /plants/{slug}/charts/intraday/temperature — as sondas de cada trafo
TEMPERATURA = {"plant": "Pirapozinho", "date": "2026-11-17", "sensors": [
    {"id": f"relay-pirapozinho-{n}", "name": f"TEMP-SKID-0{n}", "points": [
        {"time": h, "temp_s1": 50.0 + n + int(h[:2]), "temp_s2": 51.0, "temp_ambient": 29.5} for h in HORAS]}
    for n in (1, 2, 3)]}
# GET /plants/{slug}/inverters/diagnostics/insulation — lista de leituras (a vaga pelo slot_id)
ISOLACAO = {"start": "2026-10-19T00:27:14", "end": "2026-11-18T00:27:14", "items": [
    {"timestamp": f"2026-11-{d:02d}T08:36:53+00:00", "slot_id": 127, "kind": "partida",
     "insulation_mohm": 0.40 + d / 100, "threshold_mohm": 0.05, "device_status": 512, "fault_code": 0}
    for d in range(1, 18)]}
# GET /grandezas/series (diário) — em colunas: as datas numa lista, os valores em outra
GRANDEZAS = {"family": "diario", "step": "1d", "timestamps": [f"2026-11-{d:02d}" for d in range(1, 18)], "series": [
    {"plant": "pirapozinho", "unidade": None, "label": None, "grandeza": g, "values": [v + d for d in range(1, 18)]}
    for g, v in (("energia_dia", 14000.0), ("pr_dia", 80.0))]}
# o cadastro: GET /plants/{slug}/slots (as vagas) e o catálogo das grandezas (os nomes dos skids)
SLOTS = [{"id": i, "transformer_id": tr, "position": pos, "label": rot, "current_assignment": {"serial_number": sn}}
         for i, tr, pos, rot, sn in ((171, 50, 1, "Inv 12", "S12"), (125, 50, 2, "Inv 11", "S11"),
                                     (127, 50, 4, "Inv 13", "S13"), (134, 52, 2, "Inv 32", "S32"))]
CATALOGO_GRANDEZAS = {"plants": [{"slug": "pirapozinho", "skids": [
    {"id": 50, "name": "TR-01"}, {"id": 51, "name": "TR-02"}, {"id": 52, "name": "TR-03"}]}]}

# GET /plants/{slug}/charts/hourly — a hora em número
HORARIA = {"plant": "Pirapozinho", "date": "2026-11-17", "hours": [
    {"hour": h, "total_generation_kwh": max(0.0, 900 - 60 * abs(12 - h)), "inverters": [
        {"serial_number": "S12", "generated": max(0.0, 230 - 15 * abs(12 - h)), "status": 1}]} for h in range(24)]}
# GET /plants/{slug}/readings/strings — as strings LIGADAS de cada inversor (a PV1 não tem string)
LIGADAS = {"date": "2026-11-17", "inverters": [
    {"serial_number": sn, "label": rot, "strings": [{"number": n, "tag": f"{rot[-2]}S{n:02d}", "registered": True}
                                                   for n in (2, 3, 4, 6, 10)]}
    for sn, rot in (("S11", "Inv 11"), ("S12", "Inv 12"), ("S13", "Inv 13"), ("S32", "Inv 32"))]}
# GET /plants/{slug}/monitoring/current — o Inv 32 sem comunicação desde as 06:00 de hoje (09:00 UTC)
AGORA = {"inverters": [{"name": "Inv 32", "serial_number": "S32", "down": True, "down_cause": "communication_failure",
                        "down_since": "2026-11-17T09:00:00Z"},
                       {"name": "Inv 12", "serial_number": "S12", "down": False}],
         "relays": [{"name": "7SR10 Skid 3", "transformer_name": "TR-03"},
                    {"name": "EP4 Temp Skid 3", "transformer_name": "TR-03", "is_temperature_relay": True}],
         "temp_sensors": [{"name": "TEMP-SKID-01", "transformer_name": "TR-01", "temp_s1": 52.1, "temp_s2": 56.4,
                           "temp_max_s1": 148.2, "temp_max_s2": 99.0,
                           "setpoints": {"fan_c": 90.0, "alarm_c": 130.0, "trip_c": 140.0}},
                          {"name": "TEMP-SKID-03", "transformer_name": "TR-03", "temp_s1": 50.0,
                           "setpoints": {"fan_c": 90.0, "alarm_c": 130.0, "trip_c": 140.0}}]}
INTRADAY_32_MUDO = {**INTRADAY, "points": [
    {**p, "inverters": [{**i, "power_kw": 0.0} if i["serial_number"] == "S32" else i for i in p["inverters"]]}
    for p in INTRADAY["points"]]}

DETALHE = {"slug": "pirapozinho", "transformers": [{"id": 50, "name": "TR-01", "power_kva": 1000.0},
                                                   {"id": 52, "name": "TR-03", "power_kva": 500.0}]}
RESPOSTAS = {"monitoramento_curva_5min": INTRADAY, "monitoramento_curva_horaria": HORARIA,
             "monitoramento_detalhe_usina": DETALHE,
             "monitoramento_leituras_strings": LIGADAS, "monitoramento_monitoramento_usina": AGORA, "monitoramento_correntes_strings_dia": STRINGS,
             "monitoramento_reles_dia": RELES, "monitoramento_temperatura_trafos": TEMPERATURA,
             "monitoramento_isolacao_inversores": ISOLACAO, "monitoramento_serie_grandezas": GRANDEZAS,
             "monitoramento_inversores": {"itens": SLOTS}, "monitoramento_grandezas_catalogo": CATALOGO_GRANDEZAS}


@pytest.fixture
def conector(monkeypatch):
    chamadas, enviados = [], []

    async def ferramentas(db, usuario):
        return [{"name": n, "description": "" if n in ("monitoramento_inversores", "monitoramento_grandezas_catalogo")
                 else "[Monitoramento] Série de 5 em 5 min num dia (date).", "inputSchema": {}} for n in RESPOSTAS]

    async def chamar(db, usuario, nome, args):
        chamadas.append((nome, args))
        if nome not in RESPOSTAS:
            return {"content": [{"type": "text", "text": "Ferramenta desconhecida"}], "isError": True}
        return {"content": [{"type": "text", "text": "Resultado inteiro em structuredContent."}],
                "structuredContent": RESPOSTAS[nome], "isError": False}

    async def envia(**kw):
        enviados.append(kw)
        return {"ok": True}

    monkeypatch.setattr(mcp, "_ferramentas", ferramentas)
    monkeypatch.setattr(mcp, "_chamar", chamar)
    monkeypatch.setattr(whatsapp, "enviar_conteudo", envia)
    return types.SimpleNamespace(chamadas=chamadas, enviados=enviados)


def _ctx():
    return ger.Contexto(db=None, user=types.SimpleNamespace(id=7), telefone="+5517999990000")


def _mapa():
    return ser.apelidos_do_meuwatt({"itens": SLOTS}, CATALOGO_GRANDEZAS, "pirapozinho")


def _rotulos(payload, campos=(), so=(), **kw):
    series, problema = ser.series_de(ser.observacoes(payload, DIA), _mapa(), list(campos), list(so), **kw)
    return sorted(s.rotulo for s in series), problema


def test_o_leitor_entende_as_formas_das_consultas():
    assert len(ser.observacoes(INTRADAY, DIA)[((("serial_number", "S12"),), "power_kw")]) == len(HORAS)
    assert ser.observacoes(STRINGS, DIA)[((("serial_number", "S32"),), "pv10")][0][1] == 5.5
    rele = ser.observacoes(RELES, DIA)[((("name", "Relé Skid 1"), ("id", "relay-18")), "total_active_power")]
    assert rele[12][0].hour == 12 and rele[12][1] == 250.0
    iso = ser.observacoes(ISOLACAO, DIA)[((("slot_id", "127"),), "insulation_mohm")]
    assert iso[0][0].hour == 5 and iso[0][0].day == 1                 # 08:36 UTC = 05:36 em Brasília
    col = ser.observacoes(GRANDEZAS, DIA)[((("plant", "pirapozinho"),), "energia_dia")]
    assert col[0] == (ser.instante("2026-11-01", DIA), 14001.0) and len(col) == 17
    assert ((("name", "Relé Geral"), ("id", "relay-17")), "active_power_b") not in ser.observacoes(RELES, DIA)


def test_os_equipamentos_pelo_nome_que_a_pessoa_usa():
    assert _rotulos(INTRADAY, ["potência"], ["Skid 1"])[0] == [
        "Inv 11 (TR-01) · potência", "Inv 12 (TR-01) · potência", "Inv 13 (TR-01) · potência"]
    # "inversor 1 do skid 1" é o Inv 11: o rótulo já diz o skid e o inversor (a POSIÇÃO 1 do TR-01 é o Inv 12)
    assert _rotulos(STRINGS, ["string 10"], ["inversor 2 do skid 3"])[0] == ["Inv 32 (TR-03) · string 10"]
    assert _rotulos(STRINGS, ["pv1"], ["inversor 1 do skid 1"])[0] == ["Inv 11 (TR-01) · string 1"]
    assert _rotulos(STRINGS, ["pv1"], ["skid 1 posição 1"])[0] == ["Inv 12 (TR-01) · string 1"]
    assert _rotulos(INTRADAY, ["potencia"], ["Inv 12", "Inv 13"])[0] == [
        "Inv 12 (TR-01) · potência", "Inv 13 (TR-01) · potência"]
    assert _rotulos(TEMPERATURA, ["sonda 1"], ["trafo 2"])[0] == ["TEMP-SKID-02 · sonda 1"]
    # "potência" do relé é a total; as fases, só pedidas
    assert _rotulos(RELES, ["potência"], ["relé do skid 1"])[0] == ["Relé Skid 1 · potência ativa"]
    assert _rotulos(RELES, ["potência fase a"], ["relé do skid 1"])[0] == ["Relé Skid 1 · active_power_a"]
    assert _rotulos(ISOLACAO, ["isolação"])[0] == ["Inv 13 (TR-01) · isolação", "Inv 13 (TR-01) · threshold_mohm"]
    assert _rotulos(GRANDEZAS, ["energia"])[0] == ["pirapozinho · energia_dia"]
    # com o catálogo trazendo os nomes: a usina e a grandeza pelo nome, e a unidade dele
    nomes = {**CATALOGO_GRANDEZAS, "plants": [{**CATALOGO_GRANDEZAS["plants"][0], "name": "Pirapozinho"}],
             "grandezas": [{"key": "energia_dia", "label": "Energia gerada", "unit": "kWh"}]}
    s, _p = ser.series_de(ser.observacoes(GRANDEZAS, DIA), ser.apelidos_do_meuwatt({"itens": SLOTS}, nomes,
                                                                                    "pirapozinho"), ["energia"], [])
    assert [(x.rotulo, x.unidade) for x in s] == [("Pirapozinho · Energia gerada", "kWh")]
    ser._GRANDEZAS.clear()
    nada, problema = _rotulos(INTRADAY, ["potência"], ["Inv 99"])
    assert nada == [] and "Inv 32 (TR-03)" in problema["equipamentos"]
    nada, problema = _rotulos(RELES, ["frequência"])
    assert nada == [] and "total_active_power (kW)" in problema["campos"]
    soma, _p = ser.series_de(ser.observacoes(INTRADAY, DIA), _mapa(), ["potência"], ["Skid 1"], somar=True,
                             rotulo="Inversores do Skid 1")
    assert [s.rotulo for s in soma] == ["Inversores do Skid 1"] and soma[0].pontos[12][1] == 250 + 225 + 237.5


def test_a_analise_traz_a_hora_do_maximo_e_a_correlacao():
    rele, _ = ser.series_de(ser.observacoes(RELES, DIA), _mapa(), ["potência"], ["Relé Skid 1"])
    inv, _ = ser.series_de(ser.observacoes(INTRADAY, DIA), _mapa(), ["potência"], ["Inv 12"])
    a = ser.analise(rele + inv)
    r, i = a["series"]
    # no teto, o máximo é o trecho (a hora de um ponto dentro do teto não diz nada); o relé mede: sem teto, e
    # "registrou potência" no lugar de começou/parou
    assert i["maximo"] == [250, "no teto por 30 min: 12:00–12:30"] and r["maximo"] == [250, "12:00"]
    assert "no_teto" not in r and r["registrou_potencia"] == ["06:00", "17:30"] and "comecou" not in r
    # geração: quando começou e parou e a energia (a última leitura só no dia de hoje; sem a média com sol)
    assert i["comecou"] == "06:00" and i["parou"] == "17:30" and "ultima_leitura" not in i
    assert "media" not in i and "media_com_sol" not in i and i["energia_kwh"] > 1000
    # relé × inversor no mesmo gráfico: as energias pela curva (a mesma conta dos dois)
    assert i["energia_fonte"].startswith("pela curva")
    c = a["comparacoes"][0]
    assert c["andam_juntas"] == 1.0 and c["como_andam"] == "sobem e descem juntas" and "frase" not in c
    assert c["energia_kwh_nos_mesmos_horarios"][0] == c["energia_kwh_nos_mesmos_horarios"][1]
    # a comparação já escrita: quem tem menos é o sujeito e a base é o outro (10% = 1 − 0,9)
    i11, _ = ser.series_de(ser.observacoes(INTRADAY, DIA), _mapa(), ["potência"], ["Inv 11"])
    f = ser.analise(inv + i11)["comparacoes"][0]["frase"]
    assert f.startswith("Inv 11 (TR-01) · potência somou ") and "10,0% menos que Inv 12 (TR-01) · potência" in f
    # o relé × a soma dos inversores: no trecho de potência alta (o do dia mistura instantes diferentes; avaliação de
    # 17/11/2026: "perda no trafo" com o relé medindo 0,6% a MAIS no teto)
    ts = [datetime(2026, 11, 17, 10, 0, tzinfo=BRT) + ser.timedelta(minutes=5 * k) for k in range(37)]
    r5 = ser.Serie("Relé Skid 1 · potência ativa total", "kW", [(t, 1006.0) for t in ts], "Relé Skid 1",
                   campo="total_active_power")
    s5 = ser.Serie("Inversores do Skid 1", "kW", [(t, 1000.0) for t in ts], "Inv 11, Inv 12", componentes=("S11", "S12"))
    assert ser.analise([r5, s5])["comparacoes"][0]["no_trecho_alto"] == (
        "com a potência alta (entre 10:00 e 13:00), Relé Skid 1 · potência ativa total mediu 0,6% a mais que "
        "Inversores do Skid 1")
    # as maiores quedas do dia (nuvem), também fora do teto
    nuvem5 = ser.Serie("Inv 12", "kW", [(t, 100.0 if t.minute == 45 and t.hour == 10 else 250.0) for t in ts])
    assert ser.analise([nuvem5])["series"][0]["maiores_quedas"] == ["caiu de 250 kW (10:40) para 100 kW (10:45)"]
    # o que cai e não volta (a tarde descendo, o inversor que desarmou) não é a queda de uma nuvem
    tarde = ser.Serie("Inv 12", "kW", [(t, 250.0 if k < 20 else 100.0) for k, t in enumerate(ts)])
    assert "maiores_quedas" not in ser.analise([tarde])["series"][0]
    # a temperatura que pula 8,6 °C em 5 min (o ambiente às 23:50) é leitura suspeita
    pulo = ser.Serie("ambiente", "°C", [(t, 25.7 if k == 20 else 34.0) for k, t in enumerate(ts)])
    assert ser.analise([pulo])["series"][0]["leitura_suspeita"][0] == "às 11:40 pulou de 34,0 para 25,7 °C"
    dia, _ = ser.series_de(ser.observacoes(GRANDEZAS, DIA), _mapa(), ["energia"], [])
    assert ser.e_diario(dia) and ser.analise(dia)["series"][0]["soma_mwh"] == round((14000 * 17 + 153) / 1000, 1)
    # o patamar: o teto do skid, ou a sonda que parou num valor
    teto = ser.Serie("skid", "kW", [(ser.instante(h, DIA), 1000.0 if "10:00" <= h <= "12:30" else 300.0 + 20 * k)
                                    for k, h in enumerate(HORAS)])
    assert ser.analise([teto])["series"][0]["no_teto"] == {"valor": 1000, "trechos": [["10:00", "12:30"]],
                                                           "minutos": 150, "de_quem": "da usina"}
    # todos os trechos no teto (o Inv 13 voltou a 250 kW das 12:05 às 12:20 e só o 1º era dito)
    volta = ser.Serie("Inv 13", "kW", [(ser.instante(h, DIA), 250.0 if h in ("10:00", "10:30", "11:00", "13:00",
                                                                          "13:30") else 150.0) for h in HORAS])
    assert ser.analise([volta])["series"][0]["no_teto"]["trechos"] == [["10:00", "11:00"], ["13:00", "13:30"]]
    nuvem = ser.Serie("skid", "kW", [(t, 188.0 if t.strftime("%H:%M") == "11:00" else v) for t, v in teto.pontos])
    assert ser.analise([nuvem])["series"][0]["no_teto"]["quedas"] == [["11:00", 188]]
    # corrente de string não tem teto (o limite é da potência do inversor)
    assert "no_teto" not in ser.analise([ser.dataclasses.replace(teto, unidade="A")])["series"][0]
    # a sonda que travou num valor alto (99,8 °C) aparece; a madrugada parada, não
    sonda = ser.Serie("sonda 1", "°C", [(ser.instante(h, DIA), 99.8 if "10:00" <= h <= "12:00" else
                                         (56.0 if h < "08:00" else 60.0 + k)) for k, h in enumerate(HORAS)])
    a = ser.analise([sonda])["series"][0]
    assert a["leitura_parada"] == {"valor": 99.8, "de": "10:00", "ate": "12:00", "minutos": 120}
    # uma leitura solta no meio não corta o trecho; a isolação (uma medida por partida) nunca é "sonda travada"
    solta = ser.Serie("sonda 1", "°C", [(t, 102.6 if t.strftime("%H:%M") == "11:00" else v) for t, v in sonda.pontos])
    assert ser.analise([solta])["series"][0]["leitura_parada"]["exceto"] == [["11:00", 102.6]]   # dita, não escondida
    assert "leitura_parada" not in ser.analise([ser.dataclasses.replace(sonda, unidade="MΩ")])["series"][0]
    # o ruído do relé antes do sol e depois que a usina para não é começo nem fim
    rele = ser.Serie("relé", "kW", [(ser.instante(h, DIA), {"06:00": 9.9, "06:30": 0.0}.get(h, 500.0 if h < "17:00"
                                                                                            else 5.0)) for h in HORAS],
                     campo="total_active_power")
    assert ser.analise([rele])["series"][0]["registrou_potencia"] == ["07:00", "16:30"]
    assert ser.arred(530.85) == 531 and ser.arred(14.02) == 14.0 and ser.arred(0.0523) == 0.052


def test_o_desenho_sai_em_linha_barras_e_dois_eixos():
    temp, _ = ser.series_de(ser.observacoes(TEMPERATURA, DIA), _mapa(), ["sonda 1"], ["TR-02"])
    pot, _ = ser.series_de(ser.observacoes(INTRADAY, DIA), _mapa(), ["potência"], ["Inv 12", "Inv 11"])
    assert ser.desenhar(temp + pot, "Trafo 2 × inversores")[:4] == b"\x89PNG"
    dia, _ = ser.series_de(ser.observacoes(GRANDEZAS, DIA), _mapa(), ["energia", "pr"], [])
    assert {s.unidade for s in dia} == {"kWh", "%"}
    assert ser.desenhar(dia, "Energia e PR por dia")[:4] == b"\x89PNG"


async def test_um_grafico_com_series_de_consultas_diferentes(conector):
    """O pedido de 17/11 21:19: a potência do relé com a dos inversores do skid 1 — duas consultas, um gráfico."""
    ctx = _ctx()
    r = await ser.grafico_de_series(ctx, {"series": [
        {"consulta": "reles_dia", "argumentos": {"slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["potência"],
         "so": ["Relé Skid 1"]},
        {"consulta": "monitoramento_curva_5min", "argumentos": {"slug": "pirapozinho", "date": "2026-11-17"},
         "campos": ["potência"], "so": ["Skid 1"], "somar": True, "rotulo": "Inversores do Skid 1"}]})
    assert r["enviado_no_chat"] is True and len(conector.enviados) == 1
    assert conector.enviados[0]["arquivo"][:4] == b"\x89PNG"
    assert [s["serie"] for s in r["analise"]["series"]] == ["Relé Skid 1 · potência ativa", "Inversores do Skid 1"]
    assert r["analise"]["comparacoes"][0]["andam_juntas"] > 0.99 and "problemas" not in r
    assert r["grafico"].endswith("17/11/2026") and "_" not in r["nota"][:0]       # o título leva a data
    assert all(a.get("_completo") for n, a in conector.chamadas)    # o dado inteiro de cada consulta
    # três unidades não cabem num gráfico (dois eixos no máximo): diz e não manda nada
    r = await ser.grafico_de_series(ctx, {"series": [
        {"consulta": "temperatura_trafos", "argumentos": {"slug": "pirapozinho"}, "campos": ["sonda 1"]},
        {"consulta": "curva_5min", "argumentos": {"slug": "pirapozinho"}, "campos": ["potência"], "so": ["Inv 12"]},
        {"consulta": "isolacao_inversores", "argumentos": {"slug": "pirapozinho"}, "campos": ["isolação"]}]})
    assert "Unidades demais" in r["erro"] and len(conector.enviados) == 1
    # o que não casa volta com o que existe, para a IA acertar; e nada sai pela metade (17/11/2026: o gráfico só com o
    # relé, "os inversores ficaram de fora")
    r = await ser.grafico_de_series(ctx, {"series": [
        {"consulta": "reles_dia", "argumentos": {"slug": "pirapozinho"}, "campos": ["potência"], "so": ["Relé Skid 1"]},
        {"consulta": "curva_5min", "argumentos": {"slug": "pirapozinho"}, "campos": ["potência"], "so": ["Inv 99"]}]})
    assert r["erro"].startswith("Nada desenhado ainda") and r["ja_deram"] == ["Relé Skid 1 · potência ativa"]
    assert "Inv 12 (TR-01)" in r["problemas"][0]["equipamentos"] and len(conector.enviados) == 1
    r = await ser.grafico_de_series(ctx, {"series": [{"consulta": "geracao_do_dia", "campos": ["potência"]}]})
    assert r["problemas"][0]["sugestoes"][0].startswith("monitoramento_")


async def test_consultar_le_a_serie_com_os_nomes_do_cadastro(conector):
    r = await cat.consultar(_ctx(), {"nome": "monitoramento_correntes_strings_dia",
                                     "argumentos": {"slug": "pirapozinho", "date": "2026-11-17"}})
    s = r["series_no_tempo"]
    assert s["equipamentos"] == ["Inv 11 (TR-01)", "Inv 12 (TR-01)", "Inv 13 (TR-01)", "Inv 32 (TR-03)"]
    assert "pv10 (A)" in s["campos"] and s["series"] == 48 and "analise" not in s     # 48 séries: só a lista
    assert len(r["dados"]) <= 5_100


async def test_sem_comunicacao_zero_nao_e_leitura(conector, monkeypatch):
    """O SKID-02 de Porto Ferreira (17/11/2026): os inversores sem comunicação apareciam como 0 kW o dia todo."""
    monkeypatch.setitem(RESPOSTAS, "monitoramento_curva_5min", INTRADAY_32_MUDO)
    ctx = _ctx()
    r = await ser.grafico_de_series(ctx, {"series": [{"consulta": "curva_5min", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["potência"], "so": ["Inv 32"]}]})
    pb = r["problemas"][0]
    assert r["erro"].startswith("Nada desenhado") and "sem comunicação desde 17/11 06:00" in pb["erro"]
    assert "O TR-03 inteiro (Inv 32) está sem comunicação" in pb["erro"] and "reles_dia" not in pb["erro"]
    # o relé que mede o skid inteiro, com o que ele mediu no dia (a prova de que o skid gerou)
    assert "7SR10 Skid 3" in pb["como_seguir"] and "EP4" not in pb["como_seguir"]
    assert pb["o_rele_do_skid_mediu"][0].startswith("o relé 7SR10 Skid 3 mediu ") and "pico de 250 kW" in \
        pb["o_rele_do_skid_mediu"][0]
    assert conector.enviados == []
    # junto com outro que gera: o mudo some (não vira linha em zero) e o aviso vai à IA
    r = await ser.grafico_de_series(ctx, {"series": [{"consulta": "curva_5min", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["potência"], "so": ["Inv 12", "Inv 32"]}]})
    assert [x["serie"] for x in r["analise"]["series"]] == ["Inv 12 (TR-01) · potência"]
    assert "Inv 32 sem comunicação desde 17/11 06:00" in r["comunicacao"][0]


async def test_entrada_sem_string_nao_e_string_zerada(conector):
    """A PV1 não tem string em Pirapozinho: o gráfico dizia "zerada o dia todo" e sugeria fusível (17/11/2026)."""
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "correntes_strings_dia", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["string 1"], "so": ["inversor 1 do skid 1"]}]})
    erro = r["problemas"][0]["erro"]
    assert erro == ("A entrada PV1 do Inv 11 (TR-01) está vazia, sem string ligada (não é string zerada; é do "
                    "projeto: a PV1 é vazia nos 4 inversores). As ligadas são PV2–4, 6, 10. Opções: PV2 (1S02), a "
                    "mais próxima e a 1ª ligada.")
    # pergunta antes de desenhar (a pessoa pode chamar de "string 1" a 1ª string ligada): nada vai ao chat
    assert r["problemas"][0]["pergunte"]
    assert r["como_seguir"].startswith("Não desenhe ainda: pergunte") and conector.enviados == []
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "correntes_strings_dia", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["pv5"], "so": ["Inv 11"]}]})
    assert "Opções: PV4 (1S04), a mais próxima; PV6 (1S06), a mais próxima; PV10 (1S10), a 5ª ligada." in \
        r["problemas"][0]["erro"]
    # o número da string só no rótulo (campos ["corrente"]): a mesma pergunta, não todas as strings do inversor
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "correntes_strings_dia", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["corrente"], "so": ["Inv 11"],
        "rotulo": "Corrente da string 5 (PV5) do Inv 11"}]})
    assert "A entrada PV5 do Inv 11 (TR-01) está vazia" in r["problemas"][0]["erro"]
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "correntes_strings_dia", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["pv2"], "so": ["Inv 11"]}]})
    assert r["analise"]["series"][0]["serie"] == "Inv 11 (TR-01) · string 2 (1S02)"
    # com outra série que existe: também não desenha pela metade (o gráfico ia sem a série prometida no título)
    antes = len(conector.enviados)
    r = await ser.grafico_de_series(_ctx(), {"series": [
        {"consulta": "correntes_strings_dia", "argumentos": {"slug": "pirapozinho", "date": "2026-11-17"},
         "campos": ["pv1"], "so": ["Inv 11"]},
        {"consulta": "correntes_strings_dia", "argumentos": {"slug": "pirapozinho", "date": "2026-11-17"},
         "campos": ["pv10"], "so": ["Inv 32"]}]})
    assert r["ja_deram"] == ["Inv 32 (TR-03) · string 10 (3S10)"] and len(conector.enviados) == antes


async def test_limite_numa_linha_so_e_hora_a_hora(conector):
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "isolacao_inversores", "argumentos": {
        "slug": "pirapozinho"}, "campos": ["isolação"]}]})
    nomes = [x["serie"] for x in r["analise"]["series"]]
    assert nomes == ["Inv 13 (TR-01) · isolação", "limite (0,05 MΩ)"]
    i13 = r["analise"]["series"][0]
    assert i13["abaixo_do_minimo"] == [] and "naquele_dia" in r["sobre_a_isolacao"] and "media" not in i13
    assert i13["media_da_1a_leitura_do_dia"] == 0.49 and r["a_menor_isolacao"].startswith("0,41 MΩ no Inv 13 (TR-01)")
    # abaixo do mínimo: os trechos por manhã (17/11/2026: "45 vezes" eram três manhãs)
    pts = [(datetime(2026, 11, d, 6, m, tzinfo=BRT), 0.03) for d in (3, 15) for m in range(20, 60, 10)] + \
          [(datetime(2026, 11, 4, 10, 0, tzinfo=BRT), 0.6)]
    s = ser.Serie("Inv 14 · isolação", "MΩ", sorted(pts))
    lim = ser.Serie("limite", "MΩ", [pts[0]], estilo="limite")
    assert ser.analise([s, ser.dataclasses.replace(lim, pontos=[(pts[0][0], 0.05)])])["series"][0][
        "abaixo_do_minimo"] == [{"dia": "03/11", "de": "06:20", "ate": "06:50"},
                                {"dia": "15/11", "de": "06:20", "ate": "06:50"}]
    # a média justa é a da 1ª leitura de cada dia (nos dias ruins o inversor repete a medida a cada 10 min)
    assert ser.analise([s])["series"][0]["media_da_1a_leitura_do_dia"] == round((0.03 + 0.6 + 0.03) / 3, 3)
    # quem chegou perto sem passar (o Inv 23 a 0,052 MΩ, 4% acima)
    perto = ser.Serie("Inv 23 · isolação", "MΩ", [(pts[0][0], 0.052), (pts[-1][0], 0.4)])
    assert ser.analise([perto, ser.dataclasses.replace(lim, pontos=[(pts[0][0], 0.05)])])["series"][0][
        "perto_do_minimo"] == "0,052 MΩ em 03/11 06:20, 4% acima do mínimo"
    # a curva hora a hora: a hora vem em número (antes as 24 horas viravam um ponto só)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "curva_horaria", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["generated"], "so": ["Inv 12"]}]})
    assert r["analise"]["series"][0]["minimo"][1] == "00:00" and r["analise"]["series"][0]["maximo"][1] == "12:00"


def test_titulo_com_a_data_do_brasil():
    s = [ser.Serie("x", "°C", [(ser.instante("10:00", DIA), 1.0), (ser.instante("11:00", DIA), 2.0)])]
    assert ser.titulo_com_data("Temperatura do TR-02 (hoje)", s) == "Temperatura do TR-02 · 17/11/2026"
    assert ser.titulo_com_data("Trafo 1 e Inv 12, hoje", s) == "Trafo 1 e Inv 12 · 17/11/2026"
    assert ser.titulo_com_data("Energia 2026-11-01 a 2026-11-17", s) == "Energia 01/11/2026 a 17/11/2026"


async def test_o_nome_que_o_bot_mostra_e_quem_nem_aparece_por_estar_sem_comunicacao(conector, monkeypatch):
    # "Inv 12 (TR-01)", o nome da legenda, também chama o equipamento (17/11/2026: voltava "nenhum equipamento")
    assert _rotulos(INTRADAY, ["potência"], ["Inv 12 (TR-01)"])[0] == ["Inv 12 (TR-01) · potência"]
    # a consulta de strings nem traz o inversor sem dado: o aviso é "sem comunicação", não "não existe"
    sem_32 = {**STRINGS, "points": [{**p, "inverters": [i for i in p["inverters"] if i["serial_number"] != "S32"]}
                                    for p in STRINGS["points"]]}
    monkeypatch.setitem(RESPOSTAS, "monitoramento_correntes_strings_dia", sem_32)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "correntes_strings_dia", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["pv10"], "so": ["Inv 32"]}]})
    assert "Inv 32 sem comunicação desde 17/11 06:00" in r["problemas"][0]["erro"]


async def test_a_busca_poe_o_monitoramento_na_frente_da_manutencao(monkeypatch):
    lista = [{"name": "manutencao_consultar_materiais_equipamentos", "description": "[Manutenção] Lista os materiais "
              "e acessórios dos equipamentos (inversor, transformador, potência nominal) do escopo da usina, "
              "por nome, tipo e potência do equipamento inversor.", "inputSchema": {}},
             {"name": "monitoramento_curva_5min", "description": "[Monitoramento] Potência e irradiação de 5 em 5 min "
              "num dia (date).", "inputSchema": {}},
             {"name": "monitoramento_serie_grandezas", "description": "[Monitoramento] Série no tempo de qualquer "
              "grandeza.", "inputSchema": {}}]

    async def ferramentas(db, usuario):
        return lista

    async def chamar(db, usuario, nome, args):
        return {"content": [], "structuredContent": {"grandezas": [
            {"key": "potencia_pico_dia", "label": "Potência de pico", "unit": "kW"}]}, "isError": False}

    monkeypatch.setattr(mcp, "_ferramentas", ferramentas)
    monkeypatch.setattr(mcp, "_chamar", chamar)
    r = await cat.procurar_consulta(_ctx(), {"assunto": "potência dos inversores por equipamento no dia"})
    assert r["consultas"][0]["nome"] == "monitoramento_curva_5min"
    r = await cat.procurar_consulta(_ctx(), {"assunto": "potência de pico de cada dia"})
    assert r["consultas"][0]["nome"] == "monitoramento_serie_grandezas"
    assert "Potência de pico (potencia_pico_dia, kW)" in r["consultas"][0]["descricao"]


def test_o_dia_em_andamento_fica_fora_das_contas(monkeypatch):
    """Às 00:05, "energia de cada dia neste mês" punha hoje (0 kWh) como o pior dia."""
    monkeypatch.setattr(ser.ger, "hoje", lambda: date(2026, 11, 17))
    monkeypatch.setattr(ser, "agora_brt", lambda: datetime(2026, 11, 17, 9, 0, tzinfo=BRT))
    s = ser.Serie("energia", "kWh", [(datetime(2026, 11, d, tzinfo=BRT), 0.0 if d == 17 else 1000.0 + d)
                                     for d in range(1, 18)])
    a = ser.analise([s])["series"][0]
    assert a["minimo"] == [1001, "01/11"] and a["dia_em_andamento"].startswith("17/11: o dia ainda não acabou")
    monkeypatch.setattr(ser, "agora_brt", lambda: datetime(2026, 11, 17, 20, 0, tzinfo=BRT))
    assert ser.analise([s])["series"][0]["minimo"] == [0, "17/11"]          # depois das 19h, o dia já fechou


def test_data_sozinha_num_campo_de_data_e_hora_vale_o_dia_inteiro():
    """A isolação com "end": "2026-11-17" cortava em 17/11 00:00 UTC e deixava hoje de fora (17/11/2026)."""
    esq = {"start": {"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
           "end": {"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
           "date": {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}}
    assert ser.datas_inteiras({"start": "2026-10-19", "end": "2026-11-17", "date": "2026-11-17", "slug": "x"}, esq) == {
        "start": "2026-10-19T00:00:00-03:00", "end": "2026-11-18T00:00:00-03:00", "date": "2026-11-17", "slug": "x"}


async def test_trafo_com_os_limites_do_rele_de_temperatura(conector):
    """A sonda 2 do TR-01 a 3,3 °C do alarme e o bot não disse (avaliação de 17/11/2026)."""
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "temperatura_trafos", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "so": ["TEMP-SKID-01"]}]})
    a = {x["serie"]: x for x in r["analise"]["series"]}
    s1 = a["TEMP-SKID-01 · sonda 1"]
    assert s1["limites_do_rele"] == {"ventilacao": 90.0, "alarme": 130.0, "desligamento": 140.0}
    # as linhas no VALOR do relé (avaliação de 17/11/2026: saíram na 1ª leitura da sonda, 55,1 °C)
    assert [a[f"{k} do relé de temperatura ({v} °C)"]["limite"] for k, v in (
        ("ventilação", 90), ("alarme", 130), ("desligamento", 140))] == [90, 130, 140]
    # os outros trafos no mesmo dia: a sonda mais quente e o teto do skid pelo relé
    # a carga é a soma dos inversores do skid (o relé pode estar mudo: o do Skid 2 de Pirapozinho parou às 08:40), em %
    # da potência do trafo (o TR-03 é de 500 kVA: 500 kW é 100%, não "50% da carga")
    assert r["trafos_no_dia"] == [
        "TEMP-SKID-01 (TR-01) (o do gráfico): a sonda 1 chegou a 68,0 °C às 17:00; os inversores do skid ficaram no "
        "teto de 712 kW por 30 min (12:00–12:30) (71% dos 1.000 kVA do trafo)",
        "TEMP-SKID-02: a sonda 1 chegou a 69,0 °C às 17:00",
        "TEMP-SKID-03 (TR-03): a sonda 1 chegou a 70,0 °C às 17:00; os inversores do skid ficaram no teto de 200 kW "
        "por 30 min (12:00–12:30) (40% dos 500 kVA do trafo) (Inv 32 sem comunicação desde 17/11 06:00: o que gerou "
        "depois disso não está na soma)"]
    # sem gráfico (consultar): a temperatura máxima vem com os limites do relé
    c = await cat.consultar(_ctx(), {"nome": "monitoramento_temperatura_trafos", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}})
    lida = {x["serie"]: x for x in c["series_no_tempo"]["analise"]}
    assert lida["TEMP-SKID-01 · sonda 1"]["folga_ate_o_alarme"] == 62.0
    assert s1["folga_ate_o_alarme"] == round(130 - (51 + 17), 1)
    assert s1["maxima_guardada_no_rele"] == "148,2 °C, acima do desligamento (140 °C); o relé não diz quando foi"
    assert "maxima_guardada_no_rele" not in a["TEMP-SKID-01 · sonda 2"]       # 99 °C: abaixo do alarme, não diz
    assert "limites_do_rele" not in a["TEMP-SKID-01 · ambiente do skid"]


async def test_barra_do_dia_sem_parte_dos_inversores(conector):
    """O pico de 17/11 de Porto Ferreira sem o SKID-02 mudo entrava como o pior dia e na média (17/11/2026)."""
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "serie_grandezas", "argumentos": {
        "plants": "pirapozinho", "grandezas": "energia_dia", "start": "2026-11-01", "end": "2026-11-17"},
        "campos": ["energia"]}], "tipo": "barras"})
    e = r["analise"]["series"][0]
    assert e["dias_incompletos"] == ["17/11"] and e["maximo"] == [14016, "16/11"] and e["soma_mwh"] == 238.2
    assert "17/11" in str(r["comunicacao"]) and conector.enviados


async def test_inversor_que_gera_menos_e_as_strings_dele_com_problema(conector, monkeypatch):
    """O Inv 13 de Pirapozinho 5% abaixo dos outros: a causa eram a 6S27 e a 6S28 zeradas desde 19/10, 174,5 kWh por
    dia (17/11/2026). A regra é a da tela Leituras do meuWatt (readings/strings): nada calculado no bot."""
    sem_contador = {**INTRADAY, "points": [{**p, "inverters": [{**i, "daily_gen_kwh": None} for i in p["inverters"]]}
                                           for p in INTRADAY["points"]]}
    ligadas = {**LIGADAS, "inverters": [
        {**i, **({"loss_kwh_day": 174.5} if i["serial_number"] == "S11" else {}), "strings": [
            {**x, "status": "zero", "zero_since": "2026-10-19", "zero_since_before_window": x["number"] == 6}
            if i["serial_number"] == "S11" and x["number"] in (6, 10) else {**x, "status": "ok"} for x in i["strings"]]}
        for i in LIGADAS["inverters"]]}
    monkeypatch.setitem(RESPOSTAS, "monitoramento_curva_5min", sem_contador)
    monkeypatch.setitem(RESPOSTAS, "monitoramento_leituras_strings", ligadas)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "curva_5min", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["potência"], "so": ["Inv 11", "Inv 12", "Inv 13"]}]})
    a = {x["serie"]: x for x in r["analise"]["series"]}
    z = a["Inv 11 (TR-01) · potência"]["strings_com_problema"]
    assert z["strings"] == ["1S06 zerada desde 19/10/2026 ou antes", "1S10 zerada desde 19/10/2026"]
    # uma perda só: a medida no dia contra os outros do gráfico (a estimativa da tela não conta o teto do inversor)
    assert "perda_kwh_dia" not in z and z["perda_no_dia"] == ("126 kWh (7,7%) a menos que a mediana dos outros 2 "
                                                              "inversores do gráfico (1.645 kWh)")
    assert "strings_com_problema" not in a["Inv 12 (TR-01) · potência"]


async def test_isolacao_abaixo_do_minimo_e_o_que_aconteceu_no_dia(conector, monkeypatch):
    """O fim do trecho abaixo do mínimo é a hora em que a sonda para de ler (10h), não a hora em que o inversor ligou:
    o Inv 14 não gerou nada em 03/11 (avaliação de 17/11/2026)."""
    baixa = {**ISOLACAO, "items": [{**ISOLACAO["items"][0], "timestamp": f"2026-11-03T{h}:00+00:00",
                                    "insulation_mohm": 0.03} for h in ("09:20", "09:30", "09:40")]
             + ISOLACAO["items"][3:]}
    parado = {**INTRADAY, "points": [{**p, "inverters": [{**i, "power_kw": 0.0} if i["serial_number"] == "S13" else i
                                                         for i in p["inverters"]]} for p in INTRADAY["points"]]}
    monkeypatch.setitem(RESPOSTAS, "monitoramento_isolacao_inversores", baixa)
    monkeypatch.setitem(RESPOSTAS, "monitoramento_curva_5min", parado)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "isolacao_inversores", "argumentos": {
        "slug": "pirapozinho"}, "campos": ["isolação"]}]})
    jan = r["analise"]["series"][0]["abaixo_do_minimo"]
    assert jan[0]["dia"] == "03/11" and jan[0]["naquele_dia"] == (
        "não ligou o dia todo (0 kWh); cada um dos outros gerou ~1,0 kWh e ligou por volta das 06:00 (perdeu ~1,0 kWh)")


async def test_barras_de_pico_com_a_linha_do_teto(conector, monkeypatch):
    """Porto Ferreira bate 5.005 kW em vários dias: é o teto da usina, com uma linha de referência no gráfico."""
    picos = {**GRANDEZAS, "series": [{"plant": "pirapozinho", "unidade": None, "label": None,
                                      "grandeza": "potencia_pico_dia", "values": [3000.0 + (2005 if d in (3, 13) else d)
                                                                                for d in range(1, 18)]}]}
    monkeypatch.setitem(RESPOSTAS, "monitoramento_serie_grandezas", picos)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "serie_grandezas", "argumentos": {
        "plants": "pirapozinho", "grandezas": "potencia_pico_dia", "start": "2026-11-01", "end": "2026-11-17"},
        "campos": ["potencia_pico_dia"]}], "tipo": "barras"})
    a = {x["serie"]: x for x in r["analise"]["series"]}
    assert a["teto da usina (5.005 kW)"]["limite"] == 5005
    assert a["pirapozinho · potencia_pico_dia"]["dias_no_teto"]["dias"] == [["03/11", 5005], ["13/11", 5005]]


async def test_a_energia_do_skid_pelos_contadores(conector, monkeypatch):
    """A potência do skid pela série de grandezas: a energia é a soma dos contadores dos inversores dele, a mesma conta
    de cada inversor (17/11/2026: o Skid 1 com 6.605 kWh num gráfico e 6.585 kWh no outro)."""
    skid = {"family": "intradiario", "timestamps": [f"2026-11-17T{h}:00" for h in HORAS], "series": [
        {"plant": "pirapozinho", "unidade": 50, "label": None, "grandeza": "potencia_ativa", "values": [500.0] * len(HORAS)}]}
    monkeypatch.setitem(RESPOSTAS, "monitoramento_serie_grandezas", skid)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "serie_grandezas", "argumentos": {
        "plants": "pirapozinho", "grandezas": "potencia_ativa", "start": "2026-11-17", "end": "2026-11-17",
        "escopo": "skid"}, "campos": ["potencia_ativa"]}]})
    e = r["analise"]["series"][0]
    assert e["serie"].startswith("TR-01") and e["energia_kwh"] == 3.0          # S11 + S12 + S13: 1 kWh cada
    assert e["energia_fonte"].startswith("a soma dos contadores")


def test_temperatura_do_trafo_e_potencia_o_atraso_e_a_base_sem_carga():
    """O trafo esquenta e esfria DEPOIS da carga (o TR-01 a 114 °C às 14:00 com 702 kW) e fica quente à noite sem
    carga: "sobem e descem juntas" não era verdade (avaliação de 17/11/2026)."""
    ts = [datetime(2026, 11, 17, 4, 0, tzinfo=BRT) + ser.timedelta(minutes=5 * k) for k in range(240)]   # 04:00–23:55

    def carga(t):
        h = t.hour + t.minute / 60
        return max(0.0, 1000.0 * (1 - abs(h - 12) / 6)) if 6 <= h <= 18 else 0.0
    pot = ser.Serie("Skid 1", "kW", [(t, carga(t)) for t in ts], "TR-01")
    # a temperatura = a carga de 1 h antes (60 min de atraso) + a base de 56 °C
    temp = ser.Serie("TEMP-SKID-01 · sonda 2", "°C", [(t, 56.0 + carga(t - ser.timedelta(hours=1)) / 15) for t in ts],
                     "TEMP-SKID-01", campo="temp_s2")
    par = ser.analise([pot, temp])["comparacoes"][0]
    assert par["como_andam"].startswith("TEMP-SKID-01 · sonda 2 segue a potência com uns 60 min de atraso")
    assert par["sem_carga"] == "com a potência em zero, TEMP-SKID-01 · sonda 2 ficou em torno de 56,0 °C"


def test_sensor_que_pula_a_noite_toda_e_instavel():
    ts = [datetime(2026, 11, 17, 0, 0, tzinfo=BRT) + ser.timedelta(minutes=10 * k) for k in range(12)]
    amb = ser.Serie("TEMP-SKID-02 · ambiente do skid", "°C", [(t, 29.5 if k % 2 else 35.0) for k, t in enumerate(ts)],
                    campo="temp_ambient")
    a = ser.analise([amb])["series"][0]
    assert a["sensor_instavel"].startswith("pulou 11 vezes (3 °C ou mais em até 10 min) entre 00:10 e 01:50")
    # a sonda do trafo respondendo à carga (5,5 °C em 10 min, a nuvem) não é salto: só o ar tem o corte de 3 °C
    sobe = ser.Serie("sonda 2", "°C", [(t, 100.0 + (5.5 if k % 2 else 0)) for k, t in enumerate(ts)], campo="temp_s2")
    assert "sensor_instavel" not in ser.analise([sobe])["series"][0] and \
        "leitura_suspeita" not in ser.analise([sobe])["series"][0]


async def test_os_trafos_na_mesma_carga_e_a_conclusao(conector, monkeypatch):
    """Na mesma carga (100% do trafo), o TR-01 de Pirapozinho ficou 20 °C mais quente que o TR-02: a análise tem de
    tirar a conclusão — verificar a ventilação e as sondas (avaliação de 17/11/2026)."""
    quente = {**TEMPERATURA, "sensors": [{**x, "points": [{**p, "temp_s1": p["temp_s1"] + (25 if x["name"] ==
                                                                                       "TEMP-SKID-01" else 0)}
                                                         for p in x["points"]]} for x in TEMPERATURA["sensors"]]}
    monkeypatch.setitem(RESPOSTAS, "monitoramento_temperatura_trafos", quente)
    # o mesmo tamanho (700 kVA) e a mesma carga: vale, e com o trafo do gráfico sendo o mais frio também
    monkeypatch.setitem(RESPOSTAS, "monitoramento_detalhe_usina", {"transformers": [
        {"name": "TR-01", "power_kva": 700.0}, {"name": "TR-03", "power_kva": 700.0}]})
    monkeypatch.setitem(RESPOSTAS, "monitoramento_curva_5min", {**INTRADAY, "points": [
        {**p, "inverters": [{**i, "power_kw": i["power_kw"] * 3.5} if i["serial_number"] == "S32" else i
                            for i in p["inverters"]]} for p in INTRADAY["points"]]})
    for sensor in ("TEMP-SKID-01", "TEMP-SKID-03"):
        ser._GERACAO.clear()
        r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "temperatura_trafos", "argumentos": {
            "slug": "pirapozinho", "date": "2026-11-17"}, "so": [sensor]}]})
        assert r["trafos_no_dia"][-1] == ("conclusão: com a mesma carga (102% de 700 kVA), o TR-01 ficou 23 °C mais "
                                          "quente que o TR-03: vale verificar a ventilação e as sondas do TR-01")
    # tamanhos diferentes (o de 500 kVA esquenta diferente): sem conclusão
    monkeypatch.setitem(RESPOSTAS, "monitoramento_detalhe_usina", {"transformers": [
        {"name": "TR-01", "power_kva": 700.0}, {"name": "TR-03", "power_kva": 500.0}]})
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "temperatura_trafos", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "so": ["TEMP-SKID-01"]}]})
    assert not any(x.startswith("conclusão") for x in r["trafos_no_dia"])


async def test_titulo_de_um_skid_com_inversores_de_outro_nao_sai(conector):
    """"Skid 1" no título e os inversores da usina toda no gráfico: o pedido esqueceu o `so` (17/11/2026)."""
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "curva_5min", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["potência"]}],
        "titulo": "Pirapozinho: potência dos inversores do Skid 1"})
    assert r["erro"].startswith("Nada desenhado ainda: o título fala do skid/trafo 1") and "Inv 32 (TR-03)" in r["erro"]
    assert conector.enviados == []
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "curva_5min", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["potência"], "so": ["Skid 1"]}],
        "titulo": "Pirapozinho: potência dos inversores do Skid 1"})
    assert r["enviado_no_chat"]
