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
        self.perms = {local.PERMISSAO}
        self.gravadas, self.recusa = [], None

    async def permissoes(self):
        return self.perms

    async def usinas(self):
        return self.usinas_

    async def marcar_coordenada(self, uid, lat, lng, substituir):
        if self.recusa:
            raise _erro(*self.recusa)
        self.gravadas.append((uid, lat, lng, substituir))
        return {"ok": True, "ja_tinha": substituir, "mensagem": "Coordenada da usina marcada."}


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
