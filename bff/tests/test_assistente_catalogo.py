"""O catálogo do conector do Claude dentro do bot (`assistente_catalogo`): o dono, 17/11/2026, "e se eu fizer o bot usar o
mcp do claude, ele vai ficar muito mais poderoso né?" — "faça tudo". Duas ferramentas (procurar e consultar) em vez das
cem: as do bot seguem na frente, e o catálogo responde o resto, com o token da própria pessoa e só leitura."""

import base64
import json
import types

import pytest

from app.api.v1 import mcp
from app.clients import whatsapp
from app.services import assistente_catalogo as cat
from app.services import assistente_geracao as ger

CATALOGO = [
    {"name": "monitoramento_strings_sem_corrente", "description": "[Monitoramento] Strings sem corrente: as entradas que "
     "não geraram no dia.", "inputSchema": {"type": "object", "properties": {"slug": {"type": "string"},
                                                                              "date": {"type": "string"}},
                                            "required": ["slug"]}},
    {"name": "monitoramento_temperatura_trafos", "description": "[Monitoramento] Temperatura dos transformadores.",
     "inputSchema": {"type": "object", "properties": {"slug": {"type": "string"}}}},
    {"name": "manutencao_listar_os", "description": "[Manutenção] Ordens de serviço.", "inputSchema": {}},
    {"name": "meuguarda_foto", "description": "[meuGuarda] A foto de agora de uma câmera.", "inputSchema": {}},
]

# a forma de `GET /plants/{slug}/charts/intraday/temperature` (Pirapozinho, 17/11/2026), com um buraco no SKID-02
TEMPERATURA = {"plant": "Pirapozinho", "date": "2026-11-17", "sensors": [
    {"id": f"relay-pirapozinho-{n}", "name": f"TEMP-SKID-0{n}",
     "points": [{"time": f"{h:02d}:{m:02d}", "temp_s1": 50.0 + n + h, "temp_s2": 51.0 + n, "temp_s3": None if h == 9 else 52.0,
                 "temp_ambient": 29.5}
                for h in range(6, 12) for m in (0, 5) if not (n == 2 and h == 8)]}
    for n in (1, 2, 3)]}


@pytest.fixture
def conector(monkeypatch):
    chamadas, listas, enviados = [], [], []

    async def ferramentas(db, usuario):
        listas.append(usuario.id)
        return CATALOGO

    async def chamar(db, usuario, nome, args):
        chamadas.append((nome, args))
        if nome == "meuguarda_foto":
            return {"content": [{"type": "text", "text": "Térmica 02 · UFV Pereiras"},
                                {"type": "image", "data": base64.b64encode(b"\xff\xd8jpeg").decode(),
                                 "mimeType": "image/jpeg"}], "isError": False}
        if nome == "monitoramento_grande":
            return {"content": [{"type": "text", "text": "início" + "x" * 50_000 + "AGORA"}], "isError": False}
        if nome == "fora":
            return {"content": [{"type": "text", "text": "Monitoramento: não respondeu agora."}], "isError": True}
        if nome == "monitoramento_temperatura_trafos":
            return {"content": [{"type": "text", "text": json.dumps(TEMPERATURA)}], "isError": False}
        return {"content": [{"type": "text", "text": '{"strings": 3}'}], "isError": False}

    async def envia(**kw):
        enviados.append(kw)
        return {"ok": True}

    monkeypatch.setattr(mcp, "_ferramentas", ferramentas)
    monkeypatch.setattr(mcp, "_chamar", chamar)
    monkeypatch.setattr(whatsapp, "enviar_conteudo", envia)
    return types.SimpleNamespace(chamadas=chamadas, listas=listas, enviados=enviados)


def _ctx():
    return ger.Contexto(db=None, user=types.SimpleNamespace(id=7), telefone="+5517999990000")


async def test_procura_pelo_assunto_e_guarda_o_catalogo(conector):
    ctx = _ctx()
    r = await cat.procurar_consulta(ctx, {"assunto": "quais strings estão sem corrente em Ibitinga"})
    assert r["consultas"][0]["nome"] == "monitoramento_strings_sem_corrente"
    assert r["consultas"][0]["parametros"] == {"slug": "string", "date": "string"} and r["consultas"][0]["obrigatorios"] == ["slug"]
    # o formato que evita o 422: faixa, padrão, data
    assert cat._param({"type": "integer", "minimum": 7, "maximum": 90, "default": 30}) == "integer · 7–90 · padrão 30"
    assert cat._param({"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
                       "description": "Data YYYY-MM-DD (default: hoje)"}) == \
        "string · AAAA-MM-DD — Data YYYY-MM-DD (default: hoje)"
    r = await cat.procurar_consulta(ctx, {"assunto": "temperatura dos trafos"})
    assert r["consultas"][0]["nome"] == "monitoramento_temperatura_trafos"
    assert conector.listas == [7]                                    # o catálogo foi montado uma vez só (10 min)
    assert "erro" in await cat.procurar_consulta(ctx, {"assunto": "xyzw"})


async def test_consulta_roda_com_o_conector_e_devolve_o_texto(conector):
    r = await cat.consultar(_ctx(), {"nome": "monitoramento_strings_sem_corrente", "argumentos": {"slug": "ibitinga"}})
    assert r == {"consulta": "monitoramento_strings_sem_corrente", "dados": '{"strings":3}'}
    # do monitoramento, o dado inteiro (o texto do conector para nos 120 mil caracteres)
    assert conector.chamadas[-1] == ("monitoramento_strings_sem_corrente", {"slug": "ibitinga", "_completo": True})
    assert (await cat.consultar(_ctx(), {"nome": "fora"}))["erro"].startswith("Monitoramento: não respondeu")


async def test_a_foto_vai_ao_chat_e_nao_a_ia(conector):
    ctx = _ctx()
    r = await cat.consultar(ctx, {"nome": "meuguarda_foto", "argumentos": {"camera": "térmica 2"}})
    assert r["imagens_enviadas_no_chat"] == 1 and "jpeg" not in r["resultado"]
    assert conector.enviados[-1]["tipo"] == "image" and conector.enviados[-1]["arquivo"] == b"\xff\xd8jpeg"


async def test_resposta_grande_e_cortada(conector):
    r = await cat.consultar(_ctx(), {"nome": "monitoramento_grande"})
    t = r["resultado"]                                   # o começo e o fim ficam: o "agora" de uma série é o fim
    assert len(t) < 11_200 and t.startswith("início") and t.endswith("AGORA") and "cortado no meio" in t


async def test_serie_longa_vem_resumida_para_a_ia(conector):
    """A série do dia (as sondas dos três trafos) chega à IA como os equipamentos, os campos e o mínimo, máximo e último
    de cada série, mais o JSON encurtado: nunca os 14 mil caracteres cortados no meio de um número."""
    r = await cat.consultar(_ctx(), {"nome": "monitoramento_temperatura_trafos", "argumentos": {"slug": "pirapozinho"}})
    s = r["series_no_tempo"]
    assert s["equipamentos"] == ["TEMP-SKID-01", "TEMP-SKID-02", "TEMP-SKID-03"]
    assert "temp_s1 (°C)" in s["campos"] and s["series"] == 12
    s1 = next(x for x in s["analise"] if x["serie"] == "TEMP-SKID-02 · sonda 1")
    assert s1["leituras"] == 10 and s1["minimo"] == [58.0, "06:00"] and s1["maximo"] == [63.0, "11:00"]
    assert len(r["dados"]) <= 5_100


def test_so_quem_tem_algum_servico_no_bot_recebe_o_catalogo(monkeypatch):
    monkeypatch.setattr(mcp, "servicos", lambda u: ["monitoramento"])
    assert cat.permitidas(object()) == ["procurar_consulta", "consultar", "grafico_de_series"]
    monkeypatch.setattr(mcp, "servicos", lambda u: [])
    assert cat.permitidas(object()) == []
