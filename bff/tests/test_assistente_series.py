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
         "temp_sensors": [{"name": "TEMP-SKID-01", "temp_s1": 52.1, "temp_s2": 56.4, "temp_max_s1": 148.2,
                           "temp_max_s2": 99.0, "setpoints": {"fan_c": 90.0, "alarm_c": 130.0, "trip_c": 140.0}}]}
INTRADAY_32_MUDO = {**INTRADAY, "points": [
    {**p, "inverters": [{**i, "power_kw": 0.0} if i["serial_number"] == "S32" else i for i in p["inverters"]]}
    for p in INTRADAY["points"]]}

RESPOSTAS = {"monitoramento_curva_5min": INTRADAY, "monitoramento_curva_horaria": HORARIA,
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
    # no teto, o máximo é o trecho (a hora de um ponto dentro do teto não diz nada)
    assert r["maximo"] == [250, "no teto de 12:00 a 12:30"] and i["maximo"] == [250, "no teto de 12:00 a 12:30"]
    # geração: quando começou e parou (não a última leitura), a média só com sol e a energia do dia
    assert i["comecou"] == "06:00" and i["parou"] == "17:30" and i["ultima_leitura"] == [71.4, "17:30"]
    assert "media" not in i and i["media_com_sol"] > 100 and i["energia_kwh"] > 1000
    c = a["comparacoes"][0]
    assert c["andam_juntas"] == 1.0 and c["como_andam"] == "sobem e descem juntas" and "frase" not in c
    assert c["energia_kwh_nos_mesmos_horarios"][0] == c["energia_kwh_nos_mesmos_horarios"][1]
    # a comparação já escrita: quem tem menos é o sujeito e a base é o outro (10% = 1 − 0,9)
    i11, _ = ser.series_de(ser.observacoes(INTRADAY, DIA), _mapa(), ["potência"], ["Inv 11"])
    f = ser.analise(inv + i11)["comparacoes"][0]["frase"]
    assert f.startswith("Inv 11 (TR-01) · potência gerou ") and "10,0% menos que Inv 12 (TR-01) · potência" in f
    # o relé × a soma dos inversores: a diferença é a perda no trafo e nos cabos
    soma, _ = ser.series_de(ser.observacoes(INTRADAY, DIA), _mapa(), ["potência"], ["Inv 11", "Inv 12"], somar=True)
    assert "perda no trafo" in ser.analise(rele + soma)["comparacoes"][0]["o_que_e_a_diferenca"]
    dia, _ = ser.series_de(ser.observacoes(GRANDEZAS, DIA), _mapa(), ["energia"], [])
    assert ser.e_diario(dia) and ser.analise(dia)["series"][0]["soma_mwh"] == round((14000 * 17 + 153) / 1000, 1)
    # o patamar: o teto do skid, ou a sonda que parou num valor
    teto = ser.Serie("skid", "kW", [(ser.instante(h, DIA), 1000.0 if "10:00" <= h <= "12:30" else 300.0 + 20 * k)
                                    for k, h in enumerate(HORAS)])
    assert ser.analise([teto])["series"][0]["no_teto"] == {"valor": 1000, "de": "10:00", "ate": "12:30",
                                                           "minutos": 150}
    nuvem = ser.Serie("skid", "kW", [(t, 188.0 if t.strftime("%H:%M") == "11:00" else v) for t, v in teto.pontos])
    assert ser.analise([nuvem])["series"][0]["no_teto"]["quedas"] == [["11:00", 188]]
    # corrente de string não tem teto (o limite é da potência do inversor)
    assert "no_teto" not in ser.analise([ser.dataclasses.replace(teto, unidade="A")])["series"][0]
    # a sonda que travou num valor alto (99,8 °C) aparece; a madrugada parada, não
    sonda = ser.Serie("sonda 1", "°C", [(ser.instante(h, DIA), 99.8 if "10:00" <= h <= "12:00" else
                                         (56.0 if h < "08:00" else 60.0 + k)) for k, h in enumerate(HORAS)])
    a = ser.analise([sonda])["series"][0]
    assert a["leitura_parada"] == {"valor": 99.8, "de": "10:00", "ate": "12:00", "minutos": 120}
    assert a["maximo"].startswith("não medido")             # o pico da sonda travada é desconhecido
    # uma leitura solta no meio não corta o trecho; a isolação (uma medida por partida) nunca é "sonda travada"
    solta = ser.Serie("sonda 1", "°C", [(t, 102.6 if t.strftime("%H:%M") == "11:00" else v) for t, v in sonda.pontos])
    assert ser.analise([solta])["series"][0]["leitura_parada"]["ate"] == "12:00"
    assert "leitura_parada" not in ser.analise([ser.dataclasses.replace(sonda, unidade="MΩ")])["series"][0]
    # o ruído do relé antes do sol e depois que a usina para não é começo nem fim
    rele = ser.Serie("relé", "kW", [(ser.instante(h, DIA), {"06:00": 9.9, "06:30": 0.0}.get(h, 500.0 if h < "17:00"
                                                                                            else 5.0)) for h in HORAS])
    assert (ser.analise([rele])["series"][0]["comecou"], ser.analise([rele])["series"][0]["parou"]) == \
        ("07:00", "16:30")
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
    aviso = r["avisos"][0]
    assert "PV1 do Inv 11 (TR-01) não tem string ligada" in aviso and "PV2–4, 6, 10" in aviso
    # a única mais próxima entra no lugar, com o nome dizendo isso; o título diz o que foi desenhado
    assert "no gráfico foi a mais próxima, a PV2 (1S02)" in aviso and r["grafico"] == "Inv 11 (TR-01): string 2 (1S02) · 17/11/2026"
    assert [x["serie"] for x in r["analise"]["series"]] == [
        "Inv 11 (TR-01) · string 2 (1S02), no lugar da PV1 (sem string)"]
    # empate (a PV5: a 4 e a 6): não escolhe, pergunta
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "correntes_strings_dia", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["pv5"], "so": ["Inv 11"]}]})
    assert r["erro"] == "Nada para desenhar." and "as mais próximas são a PV4 (1S04) e a PV6 (1S06)" in r["avisos"][0]
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "correntes_strings_dia", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["pv2"], "so": ["Inv 11"]}]})
    assert r["analise"]["series"][0]["serie"] == "Inv 11 (TR-01) · string 2 (1S02)"
    # com outra série que existe, desenha ela e diz da entrada vazia (não barra o gráfico)
    r = await ser.grafico_de_series(_ctx(), {"series": [
        {"consulta": "correntes_strings_dia", "argumentos": {"slug": "pirapozinho", "date": "2026-11-17"},
         "campos": ["pv1"], "so": ["Inv 11"]},
        {"consulta": "correntes_strings_dia", "argumentos": {"slug": "pirapozinho", "date": "2026-11-17"},
         "campos": ["pv10"], "so": ["Inv 32"]}]})
    assert [x["serie"] for x in r["analise"]["series"]] == [
        "Inv 11 (TR-01) · string 2 (1S02), no lugar da PV1 (sem string)", "Inv 32 (TR-03) · string 10 (3S10)"]
    assert "PV1 do Inv 11 (TR-01) não tem string ligada" in r["avisos"][0] and r["enviado_no_chat"]


async def test_limite_numa_linha_so_e_hora_a_hora(conector):
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "isolacao_inversores", "argumentos": {
        "slug": "pirapozinho"}, "campos": ["isolação"]}]})
    nomes = [x["serie"] for x in r["analise"]["series"]]
    assert nomes == ["Inv 13 (TR-01) · isolação", "limite (0,05 MΩ)"]
    assert r["analise"]["series"][0]["abaixo_do_minimo"] == [] and "não liga" in r["sobre_a_isolacao"]
    # abaixo do mínimo: os trechos por manhã (17/11/2026: "45 vezes" eram três manhãs)
    pts = [(datetime(2026, 11, d, 6, m, tzinfo=BRT), 0.03) for d in (3, 15) for m in range(20, 60, 10)] + \
          [(datetime(2026, 11, 4, 10, 0, tzinfo=BRT), 0.6)]
    s = ser.Serie("Inv 14 · isolação", "MΩ", sorted(pts))
    lim = ser.Serie("limite", "MΩ", [pts[0]], estilo="limite")
    assert ser.analise([s, ser.dataclasses.replace(lim, pontos=[(pts[0][0], 0.05)])])["series"][0][
        "abaixo_do_minimo"] == [{"dia": "03/11", "de": "06:20", "ate": "06:50"},
                                {"dia": "15/11", "de": "06:20", "ate": "06:50"}]
    # a curva hora a hora: a hora vem em número (antes as 24 horas viravam um ponto só)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "curva_horaria", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["generated"], "so": ["Inv 12"]}]})
    assert r["analise"]["series"][0]["ultima_leitura"][1] == "23:00" and r["analise"]["series"][0]["maximo"][1] == "12:00"


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
    assert s1["folga_ate_o_alarme"] == round(130 - (51 + 17), 1)
    assert s1["maxima_guardada_no_rele"] == "148,2 °C, acima do desligamento (140 °C); o relé não diz quando foi"
    assert "maxima_guardada_no_rele" not in a["TEMP-SKID-01 · sonda 2"]       # 99 °C: abaixo do alarme, não diz
    assert "limites_do_rele" not in a["TEMP-SKID-01 · ambiente"]
    assert {"alarme do relé de temperatura (130 °C)", "desligamento do relé de temperatura (140 °C)"} <= set(a)


async def test_barra_do_dia_sem_parte_dos_inversores(conector):
    """O pico de 17/11 de Porto Ferreira sem o SKID-02 mudo entrava como o pior dia e na média (17/11/2026)."""
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "serie_grandezas", "argumentos": {
        "plants": "pirapozinho", "grandezas": "energia_dia", "start": "2026-11-01", "end": "2026-11-17"},
        "campos": ["energia"]}], "tipo": "barras"})
    e = r["analise"]["series"][0]
    assert e["dias_incompletos"] == ["17/11"] and e["maximo"] == [14016, "16/11"] and e["soma_mwh"] == 238.2
    assert "17/11" in str(r["comunicacao"]) and conector.enviados


async def test_inversor_que_gera_menos_e_as_strings_dele_sem_corrente(conector, monkeypatch):
    """O Inv 13 de Pirapozinho 5% abaixo dos outros: a causa eram a 6S27 e a 6S28 zeradas (17/11/2026)."""
    sem_contador = {**INTRADAY, "points": [{**p, "inverters": [{**i, "daily_gen_kwh": None} for i in p["inverters"]]}
                                           for p in INTRADAY["points"]]}
    zeradas = {**STRINGS, "points": [{**p, "inverters": [
        {**i, "strings": [0.0 if i["serial_number"] == "S11" and k in (5, 9) else v for k, v in enumerate(i["strings"])]}
        for i in p["inverters"]]} for p in STRINGS["points"]]}
    monkeypatch.setitem(RESPOSTAS, "monitoramento_curva_5min", sem_contador)
    monkeypatch.setitem(RESPOSTAS, "monitoramento_correntes_strings_dia", zeradas)
    r = await ser.grafico_de_series(_ctx(), {"series": [{"consulta": "curva_5min", "argumentos": {
        "slug": "pirapozinho", "date": "2026-11-17"}, "campos": ["potência"], "so": ["Inv 11", "Inv 12", "Inv 13"]}]})
    a = {x["serie"]: x for x in r["analise"]["series"]}
    assert a["Inv 11 (TR-01) · potência"]["strings_sem_corrente"] == ["1S06", "1S10"]
    assert "strings_sem_corrente" not in a["Inv 12 (TR-01) · potência"]
