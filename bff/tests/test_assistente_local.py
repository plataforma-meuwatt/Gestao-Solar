"""Localização do WhatsApp gravada como coordenada da usina no meuPlano. Pedido do Renan (29/10/2026): "enviar uma
localização para o bot e ele pedir qual usina é; ele vê se tem coordenada; se não tiver, pede se quer gravar; se tiver,
pede se quer substituir"."""

import json
import re
from types import SimpleNamespace

import httpx
import pytest

from app.services import assistente
from app.services import assistente_geracao as ger
from app.services import assistente_helper as h
from app.services import assistente_local as local
from app.services import vinculos
from tests.test_assistente_whatsapp import _conta, bot_local  # noqa: F401 (bot_local é fixture)

LAT, LNG = -21.7654321, -48.8123456


def _erro(codigo, detalhe=""):
    req = httpx.Request("POST", "http://meuplano")
    return httpx.HTTPStatusError(str(codigo), request=req, response=httpx.Response(codigo, json={"detail": detalhe},
                                                                                   request=req))


class _MeuPlano:
    def __init__(self):
        self.usinas_ = [
            {"id": 501, "name": "UFV Ibitinga", "city": "Ibitinga", "latitude": None, "longitude": None, "coordinates": None},
            {"id": 502, "name": "UFV TIETE", "city": "Tietê", "latitude": -23.10, "longitude": -47.70, "coordinates": "x"},
            {"id": 503, "name": "UFV Leme", "latitude": None, "longitude": None, "coordinates": "-22,18 -47,39"},
            {"id": 2045, "name": "Mairinque", "city": "Mairinque", "latitude": None, "longitude": None},
            {"id": 2046, "name": "Mairinque", "city": "Mairinque", "is_commissioning": True, "latitude": None,
             "longitude": None},
        ]
        self.perms = {local.PERMISSAO, local.PERMISSAO_FROTA}
        self.gravadas, self.recusa = [], None
        self.perto = {"fonte": "google", "endereco": None, "nao_recomendados_perto": [], "lugares": [
            {"nome": "Auto Posto Capim Fino", "tipo": "Posto de combustível", "endereco": "Av. Eng. Ivanil Franchiscini, "
             "Ibitinga", "lat": -21.746376, "lng": -48.820501, "place_id": "G1", "fonte": "google", "distancia_m": 21,
             "nao_recomendado_ids": []},
            {"nome": "Padaria Capim Fino", "tipo": "Padaria", "endereco": "Av. Wilson Pinheiro, Ibitinga",
             "lat": -21.7464146, "lng": -48.8206163, "place_id": "G2", "fonte": "google", "distancia_m": 33,
             "nao_recomendado_ids": []}]}
        self.marcados, self.lista, self.perguntas, self.falha_perto = [], [], 0, None
        self.resposta_marcar = {"id": 7, "ja_tinha": False}

    async def permissoes(self):
        return self.perms

    async def usinas(self):
        return self.usinas_

    async def marcar_coordenada(self, uid, lat, lng, substituir):
        if self.recusa:
            raise _erro(*self.recusa)
        self.gravadas.append((uid, lat, lng, substituir))
        return {"ok": True, "ja_tinha": substituir, "mensagem": "Coordenada da usina marcada."}

    async def lugares_perto(self, lat, lng):
        import asyncio
        self.perguntas += 1
        await asyncio.sleep(0)                          # cede a vez, como a rede: as ferramentas de uma rodada se cruzam
        if self.falha_perto:
            raise _erro(*self.falha_perto)
        return self.perto

    async def marcar_lugar_nao_recomendado(self, lugar, motivo):
        if self.recusa:
            raise _erro(*self.recusa)
        self.marcados.append((lugar, motivo))
        return self.resposta_marcar

    async def lugares_nao_recomendados(self):
        return self.lista


@pytest.fixture
def cenario(db, bot_local, monkeypatch):
    """A IA de mentira: com "usina X" (ou "é X") na mensagem chama `gravar_coordenada`; sem, pergunta qual é."""
    mp = _MeuPlano()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)
    chamadas = []

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        ultima = msgs[-1]
        if ultima["role"] == "tool":
            r = json.loads(ultima["content"])
            return {"content": r.get("erro", "") + " " + "; ".join(r.get("opcoes", [])) if "erro" in r else "Certo."}
        bot_local.llm.append(ultima["content"])
        if m := re.search(r"(?:usina|é)\s+(\w+)", ultima["content"], re.I):
            chamadas.append(m[1])
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "gravar_coordenada", "arguments": json.dumps({"usina": m[1]})}}]}
        return {"content": "De qual usina é essa localização?"}

    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    local._RECEBIDAS.clear()
    return SimpleNamespace(mp=mp, bot=bot_local, chamadas=chamadas)


def _pessoa(db):
    return _conta(db, "kewyn", "+5517997367733")


def _local(p, n, **midia):
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "location", "texto": None,
            "midia": {"lat": LAT, "lng": LNG, "nome": "UFV Ibitinga", "endereco": "Rod. SP-304", **midia}}


def _texto(p, n, texto):
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "text", "texto": texto}


async def _sim(p, n):
    h.mostrada(p.id)
    await assistente.atender(_texto(p, n, "Sim"))


async def test_sem_coordenada_pergunta_a_usina_e_grava_com_o_sim(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    # a IA lê que chegou uma localização, sem os números, e pergunta a usina
    assert cenario.bot.llm == ["[📍 localização recebida, ainda não gravada: UFV Ibitinga, Rod. SP-304]"]
    assert "21.765" not in cenario.bot.llm[0] and cenario.bot.enviados == ["De qual usina é essa localização?"]
    await assistente.atender(_texto(p, 2, "é ibitinga"))
    pend = h.PENDENTES[p.id]
    assert pend.resumo == "Gravar a coordenada da usina UFV Ibitinga" and pend.confirmacao == "sim"
    assert pend.detalhes[0] == "Local: -21.765432, -48.812346 (UFV Ibitinga, Rod. SP-304)"
    assert cenario.mp.gravadas == []                                         # nada antes do Sim
    await _sim(p, 3)
    assert cenario.mp.gravadas == [(501, LAT, LNG, False)]                  # os números da Meta, não os da IA
    assert cenario.bot.enviados[-1] == "✅ Coordenada da usina UFV Ibitinga gravada no meuPlano: -21.765432, -48.812346."
    assert local.recebida(p.telefone) is None                               # gravada não volta numa próxima vez


async def test_com_coordenada_propoe_substituir_e_diz_a_distancia(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "usina tiete"))
    pend = h.PENDENTES[p.id]
    assert pend.resumo == "SUBSTITUIR a coordenada da usina UFV TIETE"
    assert pend.detalhes[0].startswith("Gravada hoje: -23.100000, -47.700000 (a ") and " km da nova)" in pend.detalhes[0]
    await _sim(p, 3)
    assert cenario.mp.gravadas == [(502, LAT, LNG, True)]
    assert "substituída" in cenario.bot.enviados[-1]


async def test_coordenada_antiga_so_em_texto_tambem_e_substituir(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "usina leme"))
    assert h.PENDENTES[p.id].resumo == "SUBSTITUIR a coordenada da usina UFV Leme"
    assert h.PENDENTES[p.id].detalhes[0] == "Gravada hoje: -22,18 -47,39"
    await _sim(p, 3)
    assert cenario.mp.gravadas == [(503, LAT, LNG, True)]


async def test_usina_ambigua_volta_com_as_opcoes_e_o_id_escolhe(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "usina mairinque"))
    assert p.id not in h.PENDENTES
    assert "Mairinque (id 2045, Mairinque)" in cenario.bot.enviados[-1]
    assert "Mairinque (id 2046, esporádica, Mairinque)" in cenario.bot.enviados[-1]
    await assistente.atender(_texto(p, 3, "é 2046"))
    assert h.PENDENTES[p.id].resumo == "Gravar a coordenada da usina Mairinque"
    await _sim(p, 4)
    assert cenario.mp.gravadas[0][0] == 2046


async def test_sem_a_permissao_do_meuplano_avisa_antes_do_sim(db, cenario):
    p = _pessoa(db)
    cenario.mp.perms = set()
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "é ibitinga"))
    assert p.id not in h.PENDENTES and "não marca coordenada" in cenario.bot.enviados[-1]


async def test_a_recusa_do_meuplano_no_sim_chega_inteira_e_a_localizacao_fica(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "é ibitinga"))
    cenario.mp.recusa = (409, "Esta usina já tem uma coordenada, a 2.3 km daqui.")   # alguém gravou enquanto esperava
    await _sim(p, 3)
    assert cenario.bot.enviados[-1].startswith("⚠️ Enquanto você confirmava, gravaram outra coordenada")
    assert local.recebida(p.telefone) is not None                           # dá para mandar substituir em seguida


async def test_sem_localizacao_guardada_e_sem_a_parte_do_meuplano(db, cenario):
    p = _pessoa(db)
    r = await local.gravar_coordenada(SimpleNamespace(telefone=p.telefone, db=db, user=p), {"usina": "ibitinga"})
    assert "Não há localização recebida" in r["erro"]
    local.guardar(p.telefone, _local(p, 1))
    r = await local.gravar_coordenada(SimpleNamespace(telefone=p.telefone, db=db, user=p), {"usina": " "})
    assert "Falta a usina" in r["erro"] and cenario.mp.gravadas == []
    p.bot_meuplano = False
    db.commit()
    assert "gravar_coordenada" not in assistente.permitidas(p)


def test_evento_de_localizacao_torto_nao_conta():
    assert local.e_local({"tipo": "location", "midia": {"lat": -21.0, "lng": -48.0}})
    assert not local.e_local({"tipo": "location", "midia": None})
    assert not local.e_local({"tipo": "location", "midia": {"lat": "-21", "lng": -48.0}})
    assert not local.e_local({"tipo": "image", "midia": {"lat": -21.0, "lng": -48.0}})


# 06/11/2026, dono: "eu quero que o bot entenda links Google Maps. Toda vez que eu pedir uma loc ele deve me enviar
# formato Google Maps e formato Waze" (o bot respondia que não abria o link do Maps).
CURTO = "https://maps.app.goo.gl/E2JmZzNgcWZ7beit9?g_st=awb"
LONGO = ("https://www.google.com/maps/place/-23.053564,-47.725915/data=!4m6!3m5!1s0!7e2!8m2!3d-23.0535642"
         "!4d-47.7259153!18m1!1e1?utm_source=mstt_1&entry=gps")       # o destino real do link do dono


@pytest.fixture
def google(monkeypatch):
    """O Google de mentira: o link curto redireciona para o longo (o que o dono mandou, conferido em 06/11)."""
    pedidos = []

    def _responde(req):
        pedidos.append(str(req.url))
        if req.url.host == "maps.app.goo.gl":
            destino = LONGO if "E2Jm" in str(req.url) else "https://www.google.com/maps?q=Rua+Sem+Numero&ftid=1"
            return httpx.Response(302, headers={"location": destino})
        if req.url.host == "evil.example":
            return httpx.Response(200)
        return httpx.Response(200, text="<html></html>")

    real = httpx.AsyncClient

    class _Cliente(real):
        def __init__(self, *a, **k):
            super().__init__(*a, transport=httpx.MockTransport(_responde), **k)

    monkeypatch.setattr(local.httpx, "AsyncClient", _Cliente)
    return pedidos


async def test_o_link_do_google_maps_vira_a_localizacao_e_grava_com_o_sim(db, cenario, google):
    p = _pessoa(db)
    await assistente.atender(_texto(p, 1, CURTO))
    # a IA lê que a localização chegou pelo link, sem que ela tenha de abrir o link ou escrever número
    assert cenario.bot.llm == [CURTO + " [📍 localização recebida pelo link do Google Maps, ainda não gravada]"]
    assert cenario.bot.enviados == ["De qual usina é essa localização?"]
    await assistente.atender(_texto(p, 2, "usina tiete"))
    assert h.PENDENTES[p.id].detalhes[1] == "Nova: -23.053564, -47.725915"
    await _sim(p, 3)
    assert cenario.mp.gravadas == [(502, -23.0535642, -47.7259153, True)]     # o PINO do link, não a câmera do mapa


async def test_link_sem_ponto_ou_fora_do_google_nao_vira_localizacao(db, google):
    texto = await local.do_link("+5517999990000", "https://maps.app.goo.gl/outro")
    assert texto.endswith("[🔗 link do Google Maps sem um ponto que eu consiga ler: peça a localização pelo 📎 → Localização]")
    assert local.recebida("+5517999990000") is None
    assert await local.do_link("+5517999990000", "veja https://evil.example/maps?q=-23.1,-47.7") \
        == "veja https://evil.example/maps?q=-23.1,-47.7"                   # não é do Google: nem é lido
    assert not any("evil" in u for u in google)
    assert local._ponto_da_url("https://www.google.com/maps/@-23.05,-47.72,15z") is None   # a câmera não é ponto
    assert local._ponto_da_url("https://www.google.com/maps/search/?api=1&query=-21.7%2C-48.7") == (-21.7, -48.7)
    assert local.so_link(CURTO) and not local.so_link("grava " + CURTO)


async def test_o_pedido_da_localizacao_sai_em_google_maps_e_waze_pelo_sistema(db, cenario, monkeypatch):
    p = _pessoa(db)

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            r = json.loads(msgs[-1]["content"])
            return {"content": r.get("erro") or "Segue a localização da Tietê."}
        usina = msgs[-1]["content"].split()[-1]
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "local_da_usina", "arguments": json.dumps({"usina": usina})}}]}

    monkeypatch.setattr(assistente, "_llm", _llm)
    await assistente.atender(_texto(p, 1, "Me manda a localização de tiete"))
    assert cenario.bot.enviados[-1] == ("Segue a localização da Tietê.\n\n📍 *UFV TIETE*\n"
                                        "Google Maps: https://maps.google.com/?q=-23.100000,-47.700000\n"
                                        "Waze: https://waze.com/ul?ll=-23.100000,-47.700000&navigate=yes")
    await assistente.atender(_texto(p, 2, "e a de ibitinga"))
    assert "não tem coordenada gravada no meuPlano" in cenario.bot.enviados[-1] and "Waze" not in cenario.bot.enviados[-1]
    assert "local_da_usina" in assistente.permitidas(p)


async def test_as_coordenadas_escritas_viram_a_localizacao_e_gravam_com_o_sim(db, cenario):
    """11/11/2026, o dono: "eu mandei coordenada, ele deveria entender e gravar" (o bot dizia que texto não valia)."""
    p = _pessoa(db)
    await assistente.atender(_texto(p, 1, "-23,0535642, -47,7259153\n\nsalve a coordenada da usina tiete"))
    assert "[📍 localização recebida pelas coordenadas escritas, ainda não gravada]" in cenario.bot.llm[0]
    assert h.PENDENTES[p.id].detalhes[1] == "Nova: -23.053564, -47.725915"
    await _sim(p, 2)
    assert cenario.mp.gravadas == [(502, -23.0535642, -47.7259153, True)]     # o ponto lido pelo sistema


def test_o_que_nao_e_coordenada_nao_vira_localizacao():
    assert local._coordenadas("22°16'48.8\"S 51°31'31.7\"W")[0] == pytest.approx((-22.280222, -51.525472))
    for texto in ("PR de 82,51 e 81,34", "gerou 1234,5678 kWh", "OS 1638, 1640", "veja https://x.com/?q=-23.1234,-47.7234",
                  "-95.12345, 10.12345"):
        assert local._coordenadas(texto) is None, texto
    assert local.so_link("-22.2802, -51.5254") and not local.so_link("grava -22.2802, -51.5254")


# 12/11/2026, o dono: "parei em um posto agora … pela localização eu quero que o bot sugira o local … aí eu falo sim. Aí
# ele vai falar, o que você quer? Aí eu falo, esse lugar não é recomendado, por isso. Aí fica lá tipo na lista negra".
@pytest.fixture
def estrada(cenario, monkeypatch):
    """A IA de mentira da estrada: localização → `lugar_da_localizacao`; "não é recomendado porque X" → marca o 1º da lista
    (ou o lugar que vier entre aspas); "quais lugares" → a lista. Ela responde com o que a ferramenta devolveu."""
    async def _llm(msgs, ferramentas=None):
        ultima = msgs[-1]
        if ultima["role"] == "tool":
            r = json.loads(ultima["content"])
            return {"content": r.get("erro") or json.dumps(r, ensure_ascii=False)}
        cenario.bot.llm.append(ultima["content"])
        txt = ultima["content"]
        if txt.startswith("[📍"):
            nome, args = "lugar_da_localizacao", {}
        elif m := re.search(r"não é recomendado(?: porque (.*))?", txt):
            lugar = re.search(r"«(.+?)»", txt)
            nome, args = "marcar_lugar_nao_recomendado", {"lugar": lugar[1] if lugar else "1", "motivo": m[1] or ""}
        elif "quais lugares" in txt:
            nome, args = "lugares_nao_recomendados", {}
        else:
            return {"content": "?"}
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": nome, "arguments": json.dumps(args)}}]}

    monkeypatch.setattr(assistente, "_llm", _llm)
    return cenario


async def test_a_localizacao_sugere_o_posto_e_marca_nao_recomendado_com_o_sim(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1, nome=None, endereco=None))
    sugestao = estrada.bot.enviados[-1]
    assert "1. Auto Posto Capim Fino, Posto de combustível, Av. Eng. Ivanil Franchiscini, Ibitinga, a 21 m" in sugestao
    assert "usinas_perto" not in sugestao and "21.74" not in sugestao      # a IA não vê número de coordenada
    await assistente.atender(_texto(p, 2, "sim, esse lugar não é recomendado porque o diesel é batizado"))
    pend = h.PENDENTES[p.id]
    assert pend.resumo == "Marcar como NÃO RECOMENDADO: Auto Posto Capim Fino" and pend.confirmacao == "sim"
    assert "Motivo: o diesel é batizado" in pend.detalhes and estrada.mp.marcados == []          # nada antes do Sim
    assert estrada.mp.perguntas == 1                                       # o lugar foi procurado UMA vez
    await _sim(p, 3)
    lugar, motivo = estrada.mp.marcados[0]
    # os números são os do lugar que o meuPlano achou, não os da IA nem os de quem mandou
    assert (lugar["lat"], lugar["lng"], lugar["place_id"], motivo) == (-21.746376, -48.820501, "G1", "o diesel é batizado")
    assert estrada.bot.enviados[-1] == "✅ Auto Posto Capim Fino está na lista de lugares não recomendados da equipe."


async def test_o_lugar_ja_marcado_avisa_e_o_resumo_mostra_o_que_ja_esta_na_lista(db, estrada):
    p = _pessoa(db)
    estrada.mp.perto["lugares"][0]["nao_recomendado_ids"] = [7]
    estrada.mp.perto["nao_recomendados_perto"] = [
        # 22h30 de 10/11 em Brasília: o meuPlano manda em UTC, e a data não pode virar o dia seguinte
        {"id": 7, "nome": "Auto Posto Capim Fino", "motivo": "fila de uma hora", "por": "Michel",
         "em": "2026-11-11T01:30:00Z", "distancia_m": 21, "lat": -21.746376, "lng": -48.820501},
        {"id": 9, "nome": "Borracharia do Zé", "motivo": "cobrou dobrado", "por": "Diogo", "em": "2026-11-01T13:00:00Z",
         "distancia_m": 33, "lat": LAT + 0.0003, "lng": LNG}]      # perto de quem mandou: o lugar dito pelo nome
    await assistente.atender(_local(p, 1))
    assert ("Auto Posto Capim Fino, Posto de combustível, Av. Eng. Ivanil Franchiscini, Ibitinga, a 21 m — ⚠️ NÃO "
            "RECOMENDADO pela equipe: fila de uma hora (Michel, 10/11/2026)") in estrada.bot.enviados[-1]
    assert "Borracharia do Zé: cobrou dobrado (Diogo, 01/11/2026), a 33 m" in estrada.bot.enviados[-1]  # fora da lista do mapa
    await assistente.atender(_texto(p, 2, "não é recomendado porque o banheiro está fechado"))
    pend = h.PENDENTES[p.id]
    assert "Já na lista: fila de uma hora (Michel, 10/11/2026)" in pend.detalhes
    assert "Motivo: o banheiro está fechado" in pend.detalhes
    # o lugar dito pelo nome (fora da lista do mapa) também mostra o que já está marcado nele
    h.PENDENTES.pop(p.id)
    await assistente.atender(_texto(p, 3, "a «borracharia do zé» não é recomendado porque fecha cedo"))
    assert "Já na lista: cobrou dobrado (Diogo, 01/11/2026)" in h.PENDENTES[p.id].detalhes
    estrada.mp.resposta_marcar = {"id": 9, "ja_tinha": True, "motivo_anterior": "cobrou o dobro"}
    await _sim(p, 4)
    assert estrada.bot.enviados[-1] == ("✅ borracharia do zé já estava na sua lista de lugares não recomendados: o seu "
                                        "motivo de antes («cobrou o dobro») foi trocado por este.")


async def test_sem_a_frota_ou_com_o_mapa_fora_a_usina_segue_e_ninguem_diz_que_nao_ha_lugar(db, estrada):
    p = _pessoa(db)
    estrada.mp.usinas_[0].update(latitude=LAT + 0.003, longitude=LNG)
    estrada.mp.falha_perto = (403, "sem permissão")
    local.guardar(p.telefone, _local(p, 1))
    ctx = SimpleNamespace(telefone=p.telefone, db=db, user=p)
    r = await local.lugar_da_localizacao(ctx, {})
    assert r["usinas_perto"] == ["UFV Ibitinga (a 334 m)"] and "não usa a frota" in r["sem_mapa"]
    assert "sem_lugar" not in r
    estrada.mp.falha_perto = None
    estrada.mp.perto.update(lugares=[], fonte="erro")
    r = await local.lugar_da_localizacao(ctx, {})                         # o que falhou é perguntado de novo
    assert "o mapa (Google/OpenStreetMap) não respondeu agora" in r["sem_mapa"] and "sem_lugar" not in r
    assert estrada.mp.perguntas == 2


async def test_lugar_fora_da_lista_vai_com_o_nome_dito_no_ponto_mandado(db, estrada):
    p = _pessoa(db)
    estrada.mp.perto.update(lugares=[], endereco="Rod. SP-304, km 120, Ibitinga")
    await assistente.atender(_local(p, 1, nome=None, endereco=None))
    assert "O mapa não trouxe estabelecimento com nome aqui; o endereço é Rod. SP-304, km 120, Ibitinga" in estrada.bot.enviados[-1]
    await assistente.atender(_texto(p, 2, "é o «3»: não é recomendado porque fecha cedo"))
    assert "não está na lista" in estrada.bot.enviados[-1] and p.id not in h.PENDENTES   # número inventado não vira lugar
    await assistente.atender(_texto(p, 3, "o «Restaurante Graal»: não é recomendado porque fecha cedo"))
    await _sim(p, 4)
    lugar, _ = estrada.mp.marcados[0]
    assert (lugar["nome"], lugar["lat"], lugar["lng"], lugar["fonte"]) == ("Restaurante Graal", LAT, LNG, "manual")
    assert lugar["endereco"] == "Rod. SP-304, km 120, Ibitinga"


async def test_sem_motivo_ou_sem_a_frota_nada_e_proposto(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "não é recomendado"))
    assert "Falta o motivo" in estrada.bot.enviados[-1] and p.id not in h.PENDENTES
    estrada.mp.perms = {local.PERMISSAO}
    await assistente.atender(_texto(p, 3, "não é recomendado porque é caro"))
    assert "não usa a frota" in estrada.bot.enviados[-1] and p.id not in h.PENDENTES and estrada.mp.marcados == []


async def test_a_usina_perto_vem_na_sugestao(db, estrada):
    p = _pessoa(db)
    estrada.mp.usinas_[0].update(latitude=LAT + 0.003, longitude=LNG)      # a Ibitinga a ~330 m de quem mandou
    local.guardar(p.telefone, _local(p, 1))
    r = await local.lugar_da_localizacao(SimpleNamespace(telefone=p.telefone, db=db, user=p), {})
    assert r["usinas_perto"] == ["UFV Ibitinga (a 334 m)"] and len(r["lugares"]) == 2


async def test_a_lista_de_lugares_nao_recomendados(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_texto(p, 1, "quais lugares a equipe não recomenda?"))
    assert "A lista está vazia" in estrada.bot.enviados[-1]
    estrada.mp.lista = [{"id": 7, "nome": "Auto Posto Capim Fino", "endereco": "Ibitinga", "motivo": "diesel batizado",
                         "por": "Renan", "em": "2026-11-12T12:00:00Z"}]
    await assistente.atender(_texto(p, 2, "quais lugares a equipe não recomenda?"))
    assert "Auto Posto Capim Fino: diesel batizado (Renan, 12/11/2026)" in estrada.bot.enviados[-1]
    assert {"lugar_da_localizacao", "marcar_lugar_nao_recomendado", "lugares_nao_recomendados"} <= set(
        assistente.permitidas(p))


async def test_a_lista_grande_nao_e_cortada_calada_e_a_busca_acha(db, estrada, monkeypatch):
    p = _pessoa(db)
    monkeypatch.setattr(local, "TETO_LISTA", 120)
    estrada.mp.lista = [{"id": i, "nome": f"Posto {i}", "endereco": "Tietê" if i == 5 else "Ibitinga",
                         "motivo": "diesel batizado", "por": "Renan", "em": "2026-11-12T12:00:00Z"} for i in range(1, 9)]
    ctx = SimpleNamespace(telefone=p.telefone, db=db, user=p)
    r = await local.lugares_nao_recomendados(ctx, {})
    assert r["total"] == 8 and len(r["lugares"]) < 8 and f"Mais {8 - len(r['lugares'])} lugares" in r["faltam"]
    r = await local.lugares_nao_recomendados(ctx, {"busca": "tiete"})
    assert r["lugares"] == ["Posto 5: diesel batizado (Renan, 12/11/2026)"] and "faltam" not in r


async def test_mapa_em_parte_avisa_e_pergunta_de_novo(db, estrada):
    p = _pessoa(db)
    estrada.mp.perto["incompleto"] = True
    local.guardar(p.telefone, _local(p, 1))
    ctx = SimpleNamespace(telefone=p.telefone, db=db, user=p)
    assert "respondeu só em parte" in (await local.lugar_da_localizacao(ctx, {}))["aviso"]
    estrada.mp.perto["incompleto"] = False
    assert "aviso" not in await local.lugar_da_localizacao(ctx, {}) and estrada.mp.perguntas == 2


async def test_duas_ferramentas_juntas_nao_leem_a_lista_pela_metade(db, estrada):
    """A rodada roda as ferramentas juntas: com a resposta parcial guardada, a que refaz a busca não pode deixar a outra
    ver a lista vazia (ela marcaria o lugar "manual", na coordenada de quem mandou)."""
    import asyncio
    p = _pessoa(db)
    estrada.mp.perto["incompleto"] = True
    local.guardar(p.telefone, _local(p, 1))
    ctx = SimpleNamespace(telefone=p.telefone, db=db, user=p, proposta=None, pedido="")
    await local.lugar_da_localizacao(ctx, {})

    async def marcar_ve():
        return len((await local._lugares(ctx, local.recebida(p.telefone), refazer_parcial=False))["lugares"])

    lugar, visto = await asyncio.gather(local.lugar_da_localizacao(ctx, {}), marcar_ve())
    assert visto == 2 and len(lugar["lugares"]) == 2


async def test_o_numero_vale_contra_a_lista_mostrada_e_o_aviso_so_quando_nao_leu(db, estrada):
    p = _pessoa(db)
    estrada.mp.perto["incompleto"] = True
    await assistente.atender(_local(p, 1))                               # mostrou a lista parcial
    estrada.mp.perto["lugares"] = estrada.mp.perto["lugares"][::-1]     # a busca completa traria outra ordem
    await assistente.atender(_texto(p, 2, "não é recomendado porque a comida é ruim"))
    pend = h.PENDENTES[p.id]
    assert pend.resumo == "Marcar como NÃO RECOMENDADO: Auto Posto Capim Fino" and estrada.mp.perguntas == 1
    assert not any(d.startswith("Não deu para ver a lista") for d in pend.detalhes)   # a lista foi lida


async def test_depois_de_marcar_o_numero_segue_o_da_lista_mostrada_e_a_marcacao_aparece(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "não é recomendado porque a comida é ruim"))
    estrada.mp.resposta_marcar = {"id": 11, "nome": "Auto Posto Capim Fino", "lat": -21.746376, "lng": -48.820501,
                                  "motivo": "a comida é ruim", "por": "Kewyn", "em": "2026-11-12T13:00:00Z",
                                  "ja_tinha": False}
    await _sim(p, 3)
    estrada.mp.perto["lugares"] = estrada.mp.perto["lugares"][::-1]     # uma busca nova traria outra ordem
    await assistente.atender(_texto(p, 4, "o «2»: não é recomendado porque a fila é enorme"))
    assert h.PENDENTES[p.id].resumo == "Marcar como NÃO RECOMENDADO: Padaria Capim Fino" and estrada.mp.perguntas == 1
    r = await local.lugar_da_localizacao(SimpleNamespace(telefone=p.telefone, db=db, user=p), {})
    assert "NÃO RECOMENDADO pela equipe: a comida é ruim (Kewyn, 12/11/2026)" in r["lugares"][0]
