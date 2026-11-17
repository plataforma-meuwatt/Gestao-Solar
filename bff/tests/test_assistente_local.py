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
from app.services import assistente_formulario as formulario
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
        self.marcados, self.lista, self.perguntas, self.falha_perto, self.avaliacoes = [], [], 0, None, []
        self.resposta_marcar = {"id": 7, "ja_tinha": False}

    async def permissoes(self):
        return self.perms

    async def eu(self):
        return {"user_id": 77, "permissions": sorted(self.perms)}

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
        import copy
        return copy.deepcopy(self.perto)                # como lá: cada busca devolve uma lista nova

    async def marcar_lugar(self, lugar, motivo, recomendado, **avaliacao):
        if self.recusa:
            raise _erro(*self.recusa)
        self.marcados.append((lugar, motivo, recomendado))
        self.avaliacoes.append(avaliacao)
        # como lá: devolve a marcação como ficou gravada (o teste pode dizer o que já estava)
        return {"nome": lugar["nome"], "lat": lugar["lat"], "lng": lugar["lng"], "recomendado": recomendado,
                "motivo": motivo, **avaliacao, **self.resposta_marcar}

    async def lugares_marcados(self):
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
            nome, args = "avaliar_lugar", {"lugar": lugar[1] if lugar else "1", "recomenda": False,
                                           "comentario": m[1] or ""}
        elif m := re.search(r"salve(?:.*?, (.*))?", txt):
            lugar = re.search(r"«(.+?)»", txt)
            nome, args = "avaliar_lugar", {"lugar": lugar[1] if lugar else "1", "recomenda": True,
                                           "comentario": m[1] or ""}
        elif "avalie" in txt:
            lugar = re.search(r"«(.+?)»", txt)
            nome, args = "avaliar_lugar", {"lugar": lugar[1] if lugar else "1"}
        elif "quais lugares" in txt:
            nome, args = "lugares_da_equipe", {}
        else:
            return {"content": "?"}
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": nome, "arguments": json.dumps(args)}}]}

    monkeypatch.setattr(assistente, "_llm", _llm)
    formulario._ABERTOS.clear()
    formulario._AVALIACOES.clear()
    return cenario


def _ctx(db, p):
    return SimpleNamespace(telefone=p.telefone, db=db, user=p, proposta=None, pedido="", avaliacao=None)


async def test_a_localizacao_sugere_o_posto_e_o_formulario_avalia_nao_recomendado(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1, nome=None, endereco=None))
    sugestao = estrada.bot.enviados[-1]
    assert "1. Auto Posto Capim Fino, Posto de combustível, Av. Eng. Ivanil Franchiscini, Ibitinga, a 21 m" in sugestao
    assert "usinas_perto" not in sugestao and "21.74" not in sugestao      # a IA não vê número de coordenada
    await assistente.atender(_texto(p, 2, "sim, esse lugar não é recomendado porque o diesel é batizado"))
    # uma porta só (a avaliação independente de 17/11): o formulário, sem o Sim junto, com o que ela disse
    assert p.id not in h.PENDENTES and estrada.bot.tipos[-1] == ("formulario", [])
    aberto = formulario._ABERTOS[p.telefone]["avaliacao"]
    assert (aberto["nome"], aberto["recomenda"], aberto["motivo"]) == ("Auto Posto Capim Fino", "nao",
                                                                       "o diesel é batizado")
    assert estrada.mp.marcados == [] and estrada.mp.perguntas == 1        # nada antes de enviar; procurado UMA vez
    await assistente.atender(_resposta_do_formulario(p, 3, recomenda="nao", estrelas="1", preco="6,29",
                                                     motivo="o diesel é batizado"))
    lugar, motivo, recomendado = estrada.mp.marcados[0]
    # os números são os do lugar que o meuPlano achou, não os da IA nem os de quem mandou
    assert (lugar["lat"], lugar["lng"], lugar["place_id"], motivo, recomendado) == (
        -21.746376, -48.820501, "G1", "o diesel é batizado", False)
    assert estrada.mp.avaliacoes[-1] == {"estrelas": 1, "preco_medio": 6.29, "notas": None}
    assert estrada.bot.enviados[-1] == ("✅ Auto Posto Capim Fino está na lista de lugares não recomendados da equipe.\n"
                                        "⚠️ não recomendo · ★ 1 · R$ 6,29 · «o diesel é batizado»")


async def test_o_lugar_ja_marcado_aparece_e_o_de_fora_do_mapa_se_escolhe_pelo_nome(db, estrada):
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
    assert ("Borracharia do Zé, a 33 m — ⚠️ NÃO RECOMENDADO pela equipe: cobrou dobrado (Diogo, 01/11/2026)"
            in estrada.bot.enviados[-1])                                    # fora da lista do mapa
    await assistente.atender(_texto(p, 2, "a «borracharia do zé» não é recomendado porque fecha cedo"))
    aberto = formulario._ABERTOS[p.telefone]["avaliacao"]
    assert (aberto["nome"], aberto["lugar"]["lat"], aberto["motivo"]) == ("Borracharia do Zé", LAT + 0.0003,
                                                                          "fecha cedo")


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
    assert ("O mapa não trouxe estabelecimento com nome aqui; o endereço é Rod. SP-304, km 120, Ibitinga"
            in estrada.bot.enviados[-1])
    await assistente.atender(_texto(p, 2, "é o «3»: não é recomendado porque fecha cedo"))
    assert "Não há o número 3 na lista" in estrada.bot.enviados[-1] and p.telefone not in formulario._ABERTOS
    await assistente.atender(_texto(p, 3, "«essa lanchonete» não é recomendado porque fecha cedo"))
    assert "não diz qual lugar é" in estrada.bot.enviados[-1] and p.telefone not in formulario._ABERTOS
    await assistente.atender(_texto(p, 4, "o «Restaurante Graal»: não é recomendado porque fecha cedo"))
    lugar = formulario._ABERTOS[p.telefone]["avaliacao"]["lugar"]
    assert (lugar["nome"], lugar["lat"], lugar["lng"], lugar["fonte"]) == ("Restaurante Graal", LAT, LNG, "manual")
    assert lugar["endereco"] == "Rod. SP-304, km 120, Ibitinga"


async def test_com_a_lista_cheia_o_nome_que_nao_casa_pergunta_e_so_vira_lugar_novo_confirmado(db, estrada):
    """A avaliação independente (17/11): "essa lanchonete", "o 2" e "a lanchonete de São Roque" viravam um lugar NOVO
    com essas palavras, ou a repartição pública pela palavra da cidade."""
    p = _pessoa(db)
    local.guardar(p.telefone, _local(p, 1))
    ctx = _ctx(db, p)
    for termo in ("essa lanchonete", "a lanchonete de ibitinga", "Restaurante Graal", "o 5"):
        r = await local.avaliar_lugar(ctx, {"lugar": termo, "recomenda": True})
        assert r["opcoes"] == ["Auto Posto Capim Fino", "Padaria Capim Fino"] and ctx.avaliacao is None, (termo, r)
    await local.avaliar_lugar(ctx, {"lugar": "o segundo", "recomenda": True})
    assert ctx.avaliacao["nome"] == "Padaria Capim Fino"
    r = await local.avaliar_lugar(ctx, {"lugar": "1"})                    # um lugar por vez no mesmo turno
    assert "Um lugar por vez" in r["erro"] and ctx.avaliacao["nome"] == "Padaria Capim Fino"
    ctx = _ctx(db, p)
    await local.avaliar_lugar(ctx, {"lugar": "Restaurante Graal", "recomenda": True, "fora_da_lista": True})
    assert (ctx.avaliacao["nome"], ctx.avaliacao["lugar"]["fonte"]) == ("Restaurante Graal", "manual")


async def test_sem_motivo_vai_so_o_formulario_e_sem_a_frota_nada(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "não é recomendado"))
    # sem o motivo não há o Sim: o formulário pergunta (o motivo é obrigatório lá no "Não recomendo")
    assert p.id not in h.PENDENTES and estrada.bot.tipos[-1] == ("formulario", [])
    assert formulario._ABERTOS[p.telefone]["avaliacao"]["recomenda"] == "nao"
    estrada.mp.perms = {local.PERMISSAO}
    formulario._ABERTOS.clear()
    await assistente.atender(_texto(p, 3, "não é recomendado porque é caro"))
    assert "não usa a frota" in estrada.bot.enviados[-1] and p.telefone not in formulario._ABERTOS
    assert estrada.mp.marcados == []


async def test_a_usina_perto_vem_na_sugestao(db, estrada):
    p = _pessoa(db)
    estrada.mp.usinas_[0].update(latitude=LAT + 0.003, longitude=LNG)      # a Ibitinga a ~330 m de quem mandou
    local.guardar(p.telefone, _local(p, 1))
    r = await local.lugar_da_localizacao(SimpleNamespace(telefone=p.telefone, db=db, user=p), {})
    assert r["usinas_perto"] == ["UFV Ibitinga (a 334 m)"] and len(r["lugares"]) == 2


async def test_a_lista_de_lugares_da_equipe(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_texto(p, 1, "quais lugares a equipe não recomenda?"))
    assert "A lista está vazia" in estrada.bot.enviados[-1]
    estrada.mp.lista = [{"id": 7, "nome": "Auto Posto Capim Fino", "endereco": "Ibitinga", "motivo": "diesel batizado",
                         "por": "Renan", "em": "2026-11-12T12:00:00Z"}]
    await assistente.atender(_texto(p, 2, "quais lugares a equipe não recomenda?"))
    assert ("Auto Posto Capim Fino (Ibitinga) — ⚠️ NÃO RECOMENDADO pela equipe: diesel batizado (Renan, 12/11/2026)"
            in estrada.bot.enviados[-1])
    assert {"lugar_da_localizacao", "avaliar_lugar", "lugares_da_equipe"} <= set(assistente.permitidas(p))


async def test_a_lista_grande_nao_e_cortada_calada_e_a_busca_acha(db, estrada, monkeypatch):
    p = _pessoa(db)
    monkeypatch.setattr(local, "TETO_LISTA", 120)
    estrada.mp.lista = [{"id": i, "nome": f"Posto {i}", "endereco": "Tietê" if i == 5 else "Ibitinga",
                         "motivo": "diesel batizado", "por": "Renan", "em": "2026-11-12T12:00:00Z"} for i in range(1, 9)]
    ctx = SimpleNamespace(telefone=p.telefone, db=db, user=p)
    r = await local.lugares_da_equipe(ctx, {})
    assert r["total"] == 8 and len(r["lugares"]) < 8 and f"Mais {8 - len(r['lugares'])} lugares" in r["faltam"]
    r = await local.lugares_da_equipe(ctx, {"busca": "tiete"})
    assert r["lugares"] == ["Posto 5 (Tietê) — ⚠️ NÃO RECOMENDADO pela equipe: diesel batizado (Renan, 12/11/2026)"]
    assert "faltam" not in r


async def test_a_lista_tem_a_media_de_todos_quem_nao_recomenda_e_separa_lugares_de_mesmo_nome(db, estrada):
    """A avaliação independente (17/11): "quais recomendam" fazia a média só de quem recomendou e escondia o ★1 de
    quem não recomenda; e dois "Posto Graal" de estradas diferentes viravam um só."""
    p = _pessoa(db)
    sr = "R. Pedro Conti, 45 - Centro, São Roque"
    estrada.mp.lista = [
        {"id": 1, "nome": "Browdog - Hamburguer Defumado", "endereco": sr, "place_id": "GB", "recomendado": True,
         "estrelas": 5, "preco_medio": 40.0, "motivo": "maravilhosa", "por": "Renan", "em": "2026-11-16T23:19:00Z"},
        {"id": 2, "nome": "Browdog - Hamburguer Defumado", "endereco": sr, "place_id": "GB", "recomendado": False,
         "estrelas": 1, "preco_medio": 30.0, "motivo": "intoxicação", "por": "Kewyn", "em": "2026-11-17T12:00:00Z"},
        {"id": 3, "nome": "Posto Graal", "recomendado": True, "estrelas": 5, "motivo": "", "por": "Renan",
         "em": "2026-11-10T12:00:00Z", "lat": -23.20, "lng": -46.90},
        {"id": 4, "nome": "Posto Graal", "recomendado": False, "estrelas": 1, "motivo": "diesel batizado", "por": "Diogo",
         "em": "2026-11-11T12:00:00Z", "lat": -23.45, "lng": -47.30}]
    ctx = SimpleNamespace(telefone=p.telefone, db=db, user=p)
    r = await local.lugares_da_equipe(ctx, {})
    assert r["total"] == 3 and [x.split(" — ")[0] for x in r["lugares"][1:]] == ["Posto Graal", "Posto Graal"]
    r = await local.lugares_da_equipe(ctx, {"quais": "recomendados"})
    assert r["total"] == 2
    assert r["lugares"][0] == (
        "Browdog - Hamburguer Defumado (R. Pedro Conti, 45 - Centro, São Roque) — média da equipe: ★ 3,0 (2 avaliações) "
        "· preço médio R$ 35,00 — 👍 RECOMENDADO pela equipe: ★ 5 · maravilhosa (Renan, 16/11/2026) — ⚠️ NÃO "
        "RECOMENDADO pela equipe: ★ 1 · intoxicação (Kewyn, 17/11/2026)")


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


async def test_o_numero_vale_contra_a_lista_mostrada(db, estrada):
    p = _pessoa(db)
    estrada.mp.perto["incompleto"] = True
    await assistente.atender(_local(p, 1))                               # mostrou a lista parcial
    estrada.mp.perto["lugares"] = estrada.mp.perto["lugares"][::-1]     # a busca completa traria outra ordem
    await assistente.atender(_texto(p, 2, "não é recomendado porque a comida é ruim"))
    assert formulario._ABERTOS[p.telefone]["avaliacao"]["nome"] == "Auto Posto Capim Fino"
    assert estrada.mp.perguntas == 1


async def test_depois_de_avaliar_o_numero_segue_o_da_lista_mostrada_e_a_marcacao_aparece(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "não é recomendado porque a comida é ruim"))
    estrada.mp.resposta_marcar = {"id": 11, "por": "Kewyn", "em": "2026-11-12T13:00:00Z", "ja_tinha": False}
    await assistente.atender(_resposta_do_formulario(p, 3, recomenda="nao", estrelas="2", motivo="a comida é ruim"))
    estrada.mp.perto["lugares"] = estrada.mp.perto["lugares"][::-1]     # uma busca nova traria outra ordem
    await assistente.atender(_texto(p, 4, "o «2»: não é recomendado porque a fila é enorme"))
    assert formulario._ABERTOS[p.telefone]["avaliacao"]["nome"] == "Padaria Capim Fino" and estrada.mp.perguntas == 1
    r = await local.lugar_da_localizacao(SimpleNamespace(telefone=p.telefone, db=db, user=p), {})
    assert "NÃO RECOMENDADO pela equipe: ★ 2 · a comida é ruim (Kewyn, 12/11/2026)" in r["lugares"][0]


# 16/11/2026, o dono mandou a localização de uma lanchonete em São Roque e pediu "Salve essa lanchonete como maravilhosaz
# browdog": o mapa não trouxe nada (o meuPlano estava sem a chave do Google) e o bot só sabia o NÃO recomendado.
async def test_salvar_o_lugar_abre_o_formulario_ja_com_recomendo(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "salve a «padaria», que é ótima"))
    assert "é ambíguo" not in estrada.bot.enviados[-1] and p.id not in h.PENDENTES
    aberto = formulario._ABERTOS[p.telefone]["avaliacao"]
    assert (aberto["nome"], aberto["recomenda"], aberto["comentario"]) == ("Padaria Capim Fino", "sim", "que é ótima")
    await assistente.atender(_resposta_do_formulario(p, 3, recomenda="sim", estrelas="4", comentario="que é ótima"))
    assert estrada.mp.marcados[-1][1:] == ("que é ótima", True)
    assert estrada.mp.avaliacoes[-1] == {"estrelas": 4, "preco_medio": None, "notas": None}
    assert estrada.bot.enviados[-1] == ("✅ Padaria Capim Fino está na lista de lugares recomendados da equipe.\n"
                                        "👍 recomendo · ★ 4 · «que é ótima»")


async def test_mudar_de_ideia_troca_a_marcacao_e_o_lugar_bom_aparece_na_localizacao(db, estrada):
    p = _pessoa(db)
    estrada.mp.perto["lugares"][1]["nao_recomendado_ids"] = [7]
    estrada.mp.perto["nao_recomendados_perto"] = [
        {"id": 7, "nome": "Padaria Capim Fino", "motivo": "maravilhosa", "recomendado": True, "estrelas": 5,
         "por": "Renan", "em": "2026-11-16T23:19:00Z", "distancia_m": 33, "lat": -21.7464146, "lng": -48.8206163}]
    local.guardar(p.telefone, _local(p, 1))
    r = await local.lugar_da_localizacao(_ctx(db, p), {})
    assert r["lugares"][1].endswith("— média da equipe: ★ 5,0 (1 avaliação) — 👍 RECOMENDADO pela equipe: ★ 5 · "
                                    "maravilhosa (Renan, 16/11/2026)")
    await assistente.atender(_texto(p, 2, "a «padaria» não é recomendado porque fechou"))
    estrada.mp.resposta_marcar = {"id": 7, "ja_tinha": True, "motivo_anterior": "pão bom", "recomendado_anterior": True}
    await assistente.atender(_resposta_do_formulario(p, 3, recomenda="nao", estrelas="2", motivo="fechou"))
    assert estrada.bot.enviados[-1] == ("✅ Padaria Capim Fino: a sua marcação mudou de recomendado para não "
                                        "recomendado.\n⚠️ não recomendo · ★ 2 · «fechou»")


def test_o_lugar_e_escolhido_por_uma_palavra_do_nome_nunca_pelo_tipo_nem_pelo_endereco():
    sr = "R. Pedro Conti, 45 - Centro, São Roque"
    lugares = [{"nome": "PAV são roque, Ponto SP", "endereco": "Rua Marechal Deodoro da Fonseca, 193 - Centro, São Roque"},
               {"nome": "Browdog - Hamburguer Defumado", "endereco": sr},
               {"nome": "Buzzy Gang Tattoo Shop", "endereco": sr}, {"nome": "Lanchonete do Zé"},
               {"nome": "Auto Posto Ipiranga"}]
    assert local._escolher_lugar(lugares, "maravilhosaz browdog")[0]["nome"] == "Browdog - Hamburguer Defumado"
    assert local._escolher_lugar(lugares, "a lanchonete de são roque")[0] is None   # a cidade não escolhe a repartição
    assert local._escolher_lugar(lugares, "essa lanchonete")[0] is None              # o tipo não escolhe…
    assert local._escolher_lugar(lugares, "o posto bom")[0] is None
    assert local._escolher_lugar(lugares, "Lanchonete do Zé")[0]["nome"] == "Lanchonete do Zé"   # …o nome inteiro sim
    assert local._escolher_lugar(lugares, "o 2")[0]["nome"] == local._escolher_lugar(lugares, "o segundo")[0]["nome"] \
        == "Browdog - Hamburguer Defumado"
    assert local._escolher_lugar(lugares, "Restaurante Graal") == (None, [])
    assert local._so_tipo("essa lanchonete aqui") and not local._so_tipo("Bar do Zé")
    barbearia = [{"nome": "JF Barbearia", "tipo": "Barbearia"}, {"nome": "PAV são roque, Ponto SP",
                                                                "tipo": "Repartição pública"},
                 {"nome": "Browdog - Hamburguer Defumado", "tipo": "Hamburgueria"}]
    assert local._escolher_lugar(barbearia, "bar") == local._escolher_lugar(barbearia, "o ponto") == (None, [])
    # só o tipo vale pelo TIPO que o mapa dá, se um só da lista é dele
    assert local._escolher_lugar(barbearia, "a hamburgueria")[0]["nome"] == "Browdog - Hamburguer Defumado"
    assert local._escolher_lugar(barbearia, "essa lanchonete") == (None, [])


# 17/11/2026, o dono: "falta abrir o menu com opções para avaliação, com média de preço, as estrelas, notas etc"
def _resposta_do_formulario(p, n, **campos):
    """A resposta como a Meta a manda: o campo com o nome do lado que o formulário DESENHOU (sem opinião dita,
    `opiniao`/`motivo2`/`comentario2`; sem estrelas, `estrelas2`) e o lugar assinado que ele levou."""
    aberto = formulario._ABERTOS[p.telefone]
    av = aberto["avaliacao"]
    o, e = bool(av.get("recomenda")), bool(av.get("estrelas"))
    nomes = {**({} if o else {"recomenda": "opiniao", "motivo": "motivo2", "comentario": "comentario2"}),
             **({} if e else {"estrelas": "estrelas2"})}
    vazio = {k: "" for k in ("preco", "atendimento", "limpeza", "comida")}
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "interactive", "texto": None,
            "midia": {"formulario": {**vazio, **{nomes.get(k, k): v for k, v in campos.items()},
                                     "flow_token": aberto["token"],
                                     "ref": formulario._ref(p.telefone, av["lugar"], o=o, e=e)}}}


async def test_avaliar_abre_o_formulario_sem_marcar_e_enviar_grava_estrelas_preco_e_notas(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "avalie a «padaria»"))
    assert p.id not in h.PENDENTES and estrada.bot.tipos[-1] == ("formulario", [])
    aberto = formulario._ABERTOS[p.telefone]["avaliacao"]
    # sem opinião dita, nada vem marcado (o 1º formulário vinha com "Recomendo": ★1 e "comida fria" gravavam recomendado)
    assert (aberto["nome"], aberto["recomenda"], aberto["lugar"]["place_id"]) == ("Padaria Capim Fino", "", "G2")
    await assistente.atender(_resposta_do_formulario(p, 3, recomenda="sim", estrelas="5", preco="35,50", limpeza="4",
                                                     comida="5", comentario="maravilhosa"))
    lugar, motivo, recomendado = estrada.mp.marcados[-1]
    assert (lugar["place_id"], motivo, recomendado) == ("G2", "maravilhosa", True)
    assert estrada.mp.avaliacoes[-1] == {"estrelas": 5, "preco_medio": 35.5, "notas": {"limpeza": 4, "comida": 5}}
    assert estrada.bot.enviados[-1] == ("✅ Padaria Capim Fino está na lista de lugares recomendados da equipe.\n"
                                        "👍 recomendo · ★ 5 · R$ 35,50 · limpeza 4, comida 5 · «maravilhosa»")
    assert len(estrada.bot.llm) == 2                         # a resposta do formulário não passou pela IA
    # o mesmo formulário de novo não vale (uma vez só)
    await assistente.atender({"id": 4, "telefone": p.telefone, "wa_id": "1", "tipo": "interactive", "texto": None,
                              "midia": {"formulario": {"flow_token": "velho", "recomenda": "sim", "estrelas": "1"}}})
    assert estrada.bot.enviados[-1] == formulario.VENCIDO and len(estrada.mp.marcados) == 1


async def test_reavaliar_traz_a_de_antes_e_sem_formulario_o_sim_de_reserva_nao_apaga_nada(db, estrada, monkeypatch):
    """A avaliação independente (17/11): o Sim mandava a marcação sem a avaliação e as estrelas viravam nulas; e o
    formulário de reavaliar começava do zero."""
    p = _pessoa(db)
    estrada.mp.perto["lugares"][1]["nao_recomendado_ids"] = [8]
    estrada.mp.perto["nao_recomendados_perto"] = [
        {"id": 8, "nome": "Padaria Capim Fino", "motivo": "pão quentinho", "recomendado": True, "estrelas": 5,
         "preco_medio": 12.0, "notas": {"comida": 5}, "por": "Kewyn", "por_id": 77, "em": "2026-11-16T12:00:00Z",
         "distancia_m": 33, "lat": -21.7464146, "lng": -48.8206163}]
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "avalie a «padaria»"))
    aberto = formulario._ABERTOS[p.telefone]["avaliacao"]
    assert (aberto["recomenda"], aberto["comentario"], aberto["motivo"], aberto["estrelas"], aberto["preco"],
            aberto["notas"]) == ("sim", "pão quentinho", "", 5, "12,00", {"comida": "5"})

    async def _nao_abre(telefone, avaliacao):
        return False

    monkeypatch.setattr(formulario, "mandar_avaliacao", _nao_abre)
    formulario._ABERTOS.clear()
    await assistente.atender(_texto(p, 3, "avalie a «padaria»"))       # sem opinião dita agora: nada a propor
    assert estrada.bot.enviados[-1] == local.SEM_FORMULARIO and p.id not in h.PENDENTES
    await assistente.atender(_texto(p, 4, "salve a «padaria», que é ótima"))
    assert h.PENDENTES[p.id].resumo == "Marcar como RECOMENDADO: Padaria Capim Fino"
    assert estrada.bot.enviados[-1].startswith(local.SEM_FORMULARIO_COM_SIM) and estrada.bot.tipos[-1][0] == "botoes"
    estrada.mp.resposta_marcar = {"id": 8, "ja_tinha": True, "recomendado_anterior": True,
                                  "motivo_anterior": "pão quentinho", "estrelas": 5, "preco_medio": 12.0,
                                  "notas": {"comida": 5}}
    await _sim(p, 5)
    assert estrada.mp.avaliacoes[-1] == {}                     # sem estrelas, preço e notas: lá ficam as de antes
    assert estrada.bot.enviados[-1] == ("✅ Padaria Capim Fino: a sua avaliação foi atualizada.\n"
                                        "👍 recomendo · ★ 5 · R$ 12,00 · comida 5 · «que é ótima»")


async def test_o_formulario_que_nao_gravou_volta_preenchido_e_sem_a_parte_do_meuplano_nada(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "avalie a «padaria»"))
    estrada.mp.recusa = (400, "Falta o nome do lugar ou o motivo")
    await assistente.atender(_resposta_do_formulario(p, 3, recomenda="sim", estrelas="4", preco="20", comentario="bom"))
    assert estrada.bot.enviados[-2].startswith("❌ O meuPlano recusou: Falta o nome do lugar ou o motivo. Nada foi "
                                               "gravado. O formulário vai de novo")
    assert estrada.bot.tipos[-1] == ("formulario", [])
    aberto = formulario._ABERTOS[p.telefone]["avaliacao"]
    assert (aberto["recomenda"], aberto["preco"], aberto["comentario"]) == ("sim", "20,00", "bom")
    sem = SimpleNamespace(telefone=p.telefone, db=db, user=SimpleNamespace(id=p.id, bot_ativo={"bot_meuwatt"}))
    assert (await local.pelo_formulario(sem, {"lugar": aberto["lugar"], "nome": aberto["nome"], "recomendado": True}))\
        .startswith("❌ A parte do meuPlano no seu bot está desligada")


def test_a_media_da_equipe_e_o_preco_como_se_digita():
    marcas = [{"recomendado": True, "estrelas": 5, "preco_medio": 30.0, "motivo": "maravilhosa", "por": "Renan",
               "em": "2026-11-16T23:19:00Z"},
              {"recomendado": True, "estrelas": 4, "preco_medio": 35.0, "notas": {"comida": 4}, "por": "Kewyn",
               "em": "2026-11-17T15:00:00Z"},
              {"recomendado": False, "motivo": "fila", "por": "Diogo", "em": "2026-11-12T12:00:00Z"}]
    assert local._avaliacoes(marcas) == (
        " — média da equipe: ★ 4,5 (2 avaliações) · preço médio R$ 32,50 · comida 4,0 — 👍 RECOMENDADO pela equipe: "
        "★ 5 · maravilhosa (Renan, 16/11/2026); ★ 4 (Kewyn, 17/11/2026) — ⚠️ NÃO RECOMENDADO pela equipe: fila "
        "(Diogo, 12/11/2026)")
    # com UM separador ele é o decimal: o litro na bomba é 6,299, e o teclado numérico às vezes só tem o ponto
    assert [formulario._numero(t) for t in ("35", "35,50", "R$ 1.234,50", "35.5", "6.299", "abc", "-3")] == [
        35.0, 35.5, 1234.5, 35.5, 6.299, None, None]
    assert (formulario.reais(6.299), formulario.reais(32.5), local._preco_br(1234.5)) == ("R$ 6,299", "R$ 32,50",
                                                                                          "1234,50")



async def test_mudar_de_ideia_nao_leva_o_comentario_bom_para_o_motivo(db, estrada):
    """A reavaliação independente (17/11): quem recomendava ("maravilhosa", ★5) e agora diz "não recomendo mais" abria
    o formulário com o Motivo obrigatório já escrito "maravilhosa" — e gravava ★1 · maravilhosa como não recomendado."""
    p = _pessoa(db)
    estrada.mp.perto["lugares"][1]["nao_recomendado_ids"] = [8]
    estrada.mp.perto["nao_recomendados_perto"] = [
        {"id": 8, "nome": "Padaria Capim Fino", "motivo": "maravilhosa", "recomendado": True, "estrelas": 5,
         "preco_medio": 12.0, "notas": {"comida": 5}, "por": "Kewyn", "por_id": 77, "em": "2026-11-16T12:00:00Z",
         "distancia_m": 33, "lat": -21.7464146, "lng": -48.8206163}]
    local.guardar(p.telefone, _local(p, 1))
    ctx = _ctx(db, p)
    await local.avaliar_lugar(ctx, {"lugar": "padaria", "recomenda": False})
    av = ctx.avaliacao
    assert (av["recomenda"], av["motivo"], av["comentario"], av["estrelas"], av["notas"], av["preco"]) == (
        "nao", "", "", None, {}, "12,00")                     # o preço é fato: fica; a opinião de antes, não
    # a mesma opinião de antes: o comentário volta, e o Sim de reserva o leva (senão ele o apagaria)
    ctx = _ctx(db, p)
    await local.avaliar_lugar(ctx, {"lugar": "padaria", "recomenda": True})
    assert (ctx.avaliacao["comentario"], ctx.avaliacao["dito"]["motivo"]) == ("maravilhosa", "maravilhosa")


async def test_sem_formulario_vai_o_sim_com_o_que_ela_disse(db, estrada):
    """A reavaliação independente (17/11): com o formulário chegando e não abrindo (WhatsApp antigo, Web), não havia
    caminho por texto."""
    p = _pessoa(db)
    local.guardar(p.telefone, _local(p, 1))
    ctx = _ctx(db, p)
    r = await local.avaliar_lugar(ctx, {"lugar": "2", "recomenda": True, "estrelas": 5, "preco": 35,
                                        "sem_formulario": True})
    assert "proposta_pendente" in r and ctx.avaliacao is None          # o formulário não vai junto
    pend = h.PENDENTES[p.id]
    assert pend.resumo == "Marcar como RECOMENDADO: Padaria Capim Fino"
    assert "★ 5" in pend.detalhes and "Preço médio: R$ 35,00" in pend.detalhes
    h.PENDENTES.pop(p.id)
    ctx = _ctx(db, p)
    r = await local.avaliar_lugar(ctx, {"lugar": "2", "estrelas": 5, "sem_formulario": True})
    assert "falta ela dizer se recomenda" in r["erro"] and p.id not in h.PENDENTES


async def test_a_localizacao_junta_as_marcacoes_do_mesmo_lugar_numa_linha(db, estrada):
    """A reavaliação independente (17/11): a Borracharia com três avaliações saía em três linhas, cada uma com a sua
    "média da equipe"."""
    p = _pessoa(db)
    perto = {"nome": "Borracharia do Zé", "lat": LAT + 0.0003, "lng": LNG}
    estrada.mp.perto["nao_recomendados_perto"] = [
        {**perto, "id": 9, "recomendado": False, "estrelas": 1, "motivo": "cobrou dobrado", "por": "Diogo",
         "em": "2026-11-01T13:00:00Z", "distancia_m": 33},
        {**perto, "id": 10, "recomendado": True, "estrelas": 5, "motivo": "", "por": "Kewyn",
         "em": "2026-11-02T13:00:00Z", "distancia_m": 34},
        {**perto, "id": 11, "recomendado": True, "estrelas": 4, "motivo": "", "por": "Michel",
         "em": "2026-11-03T13:00:00Z", "distancia_m": 35}]
    local.guardar(p.telefone, _local(p, 1))
    r = await local.lugar_da_localizacao(_ctx(db, p), {})
    assert r["marcados_aqui"] == [
        "Borracharia do Zé, a 33 m — média da equipe: ★ 3,3 (3 avaliações) — 👍 RECOMENDADO pela equipe: ★ 5 (Kewyn, "
        "02/11/2026); ★ 4 (Michel, 03/11/2026) — ⚠️ NÃO RECOMENDADO pela equipe: ★ 1 · cobrou dobrado (Diogo, "
        "01/11/2026)"]


async def test_o_formulario_de_avaliacao_vale_horas_e_nao_so_meia_hora(db, estrada):
    """A reavaliação independente (17/11): quem pedia para salvar e voltava a dirigir perdia o formulário em 30 min."""
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "avalie a «padaria»"))
    formulario._ABERTOS[p.telefone]["em"] -= 3 * 3600                  # preenchido três horas depois
    await assistente.atender(_resposta_do_formulario(p, 3, recomenda="sim", estrelas="5"))
    assert estrada.bot.enviados[-1].startswith("✅ Padaria Capim Fino está na lista de lugares recomendados")



# A 3ª avaliação independente (17/11): o formulário prometia 12 h, mas a memória daqui caía com um deploy ou com outro
# formulário depois; e o Sim, numa mudança de opinião, levava as estrelas da opinião de antes.
async def test_a_avaliacao_grava_pelo_lugar_assinado_mesmo_sem_a_memoria(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "avalie a «padaria»"))
    lugar = formulario._ABERTOS[p.telefone]["avaliacao"]["lugar"]
    ref = formulario._ref(p.telefone, lugar)
    formulario._ABERTOS.clear()                                  # um deploy: a memória foi embora
    resposta = {"id": 3, "telefone": p.telefone, "wa_id": "1", "tipo": "interactive", "texto": None,
                "midia": {"formulario": {"flow_token": "do-processo-velho", "opiniao": "sim", "estrelas2": "4",
                                         "comentario2": "bom", "ref": ref}}}
    await assistente.atender(resposta)
    assert estrada.mp.marcados[-1][0]["place_id"] == "G2" and estrada.mp.marcados[-1][1:] == ("bom", True)
    assert estrada.bot.enviados[-1].startswith("✅ Padaria Capim Fino está na lista de lugares recomendados")
    # o lugar assinado de OUTRO número não vale; o de mais de 12 h ensina a refazer de longe
    outro = formulario._ref("+5511999990000", lugar)
    await assistente.atender({**resposta, "id": 4, "midia": {"formulario": {"flow_token": "x", "ref": outro,
                                                                            "opiniao": "sim", "estrelas2": "1"}}})
    assert estrada.bot.enviados[-1] == formulario.VENCIDA_AVALIACAO and len(estrada.mp.marcados) == 1
    corpo, _ = ref.rsplit(".", 1)
    import base64
    d = json.loads(base64.urlsafe_b64decode(corpo.encode()))
    velho = base64.urlsafe_b64encode(json.dumps({**d, "em": d["em"] - 13 * 3600}).encode()).decode()
    await assistente.atender({**resposta, "id": 5, "midia": {"formulario": {
        "flow_token": "x", "ref": f"{velho}.{formulario._assinatura(velho.encode())}", "opiniao": "sim",
        "estrelas2": "1"}}})
    assert estrada.bot.enviados[-1] == formulario.VENCIDA_AVALIACAO and len(estrada.mp.marcados) == 1


async def test_outro_formulario_depois_nao_derruba_a_avaliacao(db, estrada):
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "avalie a «padaria»"))
    lugar = formulario._ABERTOS[p.telefone]["avaliacao"]["lugar"]
    token_da_avaliacao = formulario._ABERTOS[p.telefone]["token"]
    await formulario.mandar(p.telefone, {"titulo": "Centros de custo", "opcoes": ["A", "B"], "responda": "Ficam"})
    await assistente.atender({"id": 3, "telefone": p.telefone, "wa_id": "1", "tipo": "interactive", "texto": None,
                              "midia": {"formulario": {"flow_token": token_da_avaliacao, "opiniao": "nao",
                                                       "estrelas2": "2", "motivo2": "fila enorme",
                                                       "ref": formulario._ref(p.telefone, lugar)}}})
    assert estrada.mp.marcados[-1][1:] == ("fila enorme", False)


async def test_o_sim_numa_mudanca_de_opiniao_limpa_as_estrelas_de_antes(db, estrada):
    p = _pessoa(db)
    estrada.mp.perto["lugares"][1]["nao_recomendado_ids"] = [8]
    estrada.mp.perto["nao_recomendados_perto"] = [
        {"id": 8, "nome": "Padaria Capim Fino", "motivo": "maravilhosa", "recomendado": True, "estrelas": 5,
         "preco_medio": 12.0, "notas": {"comida": 5}, "por": "Kewyn", "por_id": 77, "em": "2026-11-16T12:00:00Z",
         "distancia_m": 33, "lat": -21.7464146, "lng": -48.8206163}]
    local.guardar(p.telefone, _local(p, 1))
    ctx = _ctx(db, p)
    r = await local.avaliar_lugar(ctx, {"lugar": "padaria", "recomenda": False, "comentario": "comida estragada",
                                        "sem_formulario": True})
    assert "proposta_pendente" in r
    assert "As estrelas e as notas de antes saem (a opinião mudou)" in h.PENDENTES[p.id].detalhes
    await _sim(p, 2)
    assert estrada.mp.avaliacoes[-1] == {"estrelas": None, "notas": None}
    assert estrada.mp.marcados[-1][1:] == ("comida estragada", False)
    # sem repetir a opinião, com algo novo dito ("não abriu, 4 estrelas"): vale a de antes
    h.PENDENTES.pop(p.id, None)
    ctx = _ctx(db, p)
    r = await local.avaliar_lugar(ctx, {"lugar": "padaria", "estrelas": 4, "sem_formulario": True})
    assert h.PENDENTES[p.id].resumo == "Marcar como RECOMENDADO: Padaria Capim Fino" and "★ 4" in h.PENDENTES[p.id].detalhes


def test_a_media_do_preco_tem_duas_casas_menos_a_do_litro():
    marcas = [{"recomendado": True, "estrelas": 4, "preco_medio": v} for v in (30.0, 35.0, 41.0)]
    assert "preço médio R$ 35,33" in local._avaliacoes(marcas)
    assert "preço médio R$ 6,245" in local._avaliacoes([{"recomendado": False, "motivo": "x", "preco_medio": v}
                                                        for v in (6.299, 6.19)])



async def test_vale_o_campo_desenhado_nunca_o_escondido_e_a_avaliacao_longe_nao_entra_aqui(db, estrada):
    """A 4ª avaliação independente (17/11): os campos de dois nomes não podem depender do que a Meta devolve no campo
    escondido; e a avaliação feita de outro lugar (o formulário vale 12 h) não vira marcação "aqui"."""
    p = _pessoa(db)
    await assistente.atender(_local(p, 1))
    await assistente.atender(_texto(p, 2, "avalie a «padaria»"))        # sem opinião: o formulário desenha `opiniao`
    resposta = _resposta_do_formulario(p, 4, recomenda="nao", motivo="fila enorme", estrelas="2")
    resposta["midia"]["formulario"].update(recomenda="sim", comentario="lixo do escondido", estrelas="5")
    # foi para outro lugar (40 km dali) e mandou a localização de lá; só então enviou o formulário da padaria
    await assistente.atender(_local(p, 3, lat=-21.40, lng=-48.82, nome=None, endereco=None))
    await assistente.atender(resposta)
    assert estrada.mp.marcados[-1][1:] == ("fila enorme", False) and estrada.mp.avaliacoes[-1]["estrelas"] == 2
    assert all(m.get("nome") != "Padaria Capim Fino" for m in local.recebida(p.telefone)["marcados"])
