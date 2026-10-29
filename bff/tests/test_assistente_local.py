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
