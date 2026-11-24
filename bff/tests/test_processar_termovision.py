"""'Processar <usina>' pelo WhatsApp (TermoVision, 23/11/2026): o pedido vira ação com o Sim, o Sim pede ao TermoVision
como a pessoa e guarda o token, e o aviso só vale para o token daqui e só fala quando a etapa muda."""
import asyncio
from types import SimpleNamespace

import httpx
import respx

from app.models.processamento_tv import ProcessamentoTV  # noqa: F401 (a tabela entra no create_all da suíte)
from app.models.user import Perfil
from app.services import assistente_helper as helper
from app.services import assistente_termovision as tv

B = "https://app.termovision.tech"
OPC = {"usina": None, "usinas_com_o_nome": 0, "no_envio": {"arquivos": 522, "usina_nova": True},
       "empresas": [{"id": "splendor_om", "nome": "Splendor O&M"}], "dona_sugerida": "splendor_om",
       "processando": False}


class _Db:
    def __init__(self): self.novos = []
    def add(self, x): self.novos.append(x)
    def commit(self): pass


def _ctx(monkeypatch):
    monkeypatch.setattr(tv, "assercao", lambda db, user, liberado=None: "jwt")
    user = SimpleNamespace(id=24, perfil=Perfil.GESTOR_EMPRESA, termovision_liberado=True, senha_atuacao_hash=None,
                           apelido="x", bot_ativo=set())
    return SimpleNamespace(db=_Db(), user=user, proposta=None, pedido="Processar ibitinga", mw=None, usinas={})


@respx.mock
def test_pede_com_o_sim_e_guarda_o_token(monkeypatch):
    ctx = _ctx(monkeypatch)
    respx.post(f"{B}/api/conta/gs").respond(200)
    respx.get(f"{B}/api/processar/opcoes").respond(200, json=OPC)
    pedido = respx.post(f"{B}/api/processar").respond(201, json={
        "token": "tvp_abc", "status_url": f"{B}/p/tvp_abc", "usina": {"nome": "Ibitinga", "criada": True}})
    r = asyncio.run(tv.processar_usina(ctx, {"usina": "ibitinga"}))
    assert "erro" not in r and ctx.proposta.confirmacao == "sim" and not pedido.called
    assert "usina NOVA, de Splendor O&M" in ctx.proposta.resumo
    texto = asyncio.run(ctx.proposta.executar(ctx.db, ctx.user, "5517999"))
    assert pedido.called and f"{B}/p/tvp_abc" in texto
    assert ctx.db.novos[0].token == "tvp_abc" and ctx.db.novos[0].telefone == "5517999"
    helper.PENDENTES.clear()


@respx.mock
def test_pasta_que_nao_existe_nao_propoe(monkeypatch):
    ctx = _ctx(monkeypatch)
    respx.post(f"{B}/api/conta/gs").respond(200)
    respx.get(f"{B}/api/processar/opcoes").respond(200, json={**OPC, "no_envio": {"arquivos": 0}})
    r = asyncio.run(tv.processar_usina(ctx, {"usina": "xyz"}))
    assert "drive de envio" in r["erro"] and ctx.proposta is None


@respx.mock
def test_sem_conta_no_termovision_repassa_o_porque(monkeypatch):
    ctx = _ctx(monkeypatch)
    respx.post(f"{B}/api/conta/gs").respond(401, json={"detail": "Sem conta no TermoVision."})
    r = asyncio.run(tv.processar_usina(ctx, {"usina": "ibitinga"}))
    assert "Sem conta no TermoVision." in r["erro"]


def test_a_mensagem_so_muda_com_a_etapa():
    etapas = [{"titulo": "Organizar", "estado": "concluido"}, {"titulo": "Ortomosaico RGB", "estado": "rodando",
                                                              "texto": "na fila dos PCs"}]
    a = tv.mensagem({"usina": "Ibitinga", "estado": "rodando", "etapas": etapas})
    b = tv.mensagem({"usina": "Ibitinga", "estado": "rodando", "etapas": etapas, "progresso": 40})
    assert a == b and a[1] == "🛠️ Ibitinga: Ortomosaico RGB, etapa 2 de 2 (na fila dos PCs)"
    fim = tv.mensagem({"usina": "Ibitinga", "estado": "concluido", "link_final": "/v/tvv_1"})
    assert fim[1].endswith(f"{B}/v/tvv_1")


def test_aviso_so_do_token_daqui_e_so_quando_a_etapa_muda(db, monkeypatch):
    import contextlib

    import pytest
    from fastapi import BackgroundTasks, HTTPException

    from app.api.v1 import termovision_aviso as rota

    monkeypatch.setattr(rota, "SessionLocal", lambda: contextlib.nullcontext(db))
    enviadas = []

    async def enviar(**k):
        enviadas.append(k["texto"])
    monkeypatch.setattr(rota.whatsapp, "enviar_conteudo", enviar)
    with pytest.raises(HTTPException):
        rota.aviso(rota.Aviso(token="tvp_de_ninguem"), BackgroundTasks())
    db.add(ProcessamentoTV(token="tvp_meu", gs_user_id=1, telefone="1", usina="Ibitinga"))
    db.commit()
    assert rota.aviso(rota.Aviso(token="tvp_meu"), BackgroundTasks()) == {"ok": True}
    corpo = {"usina": "Ibitinga", "estado": "rodando", "etapas": [{"titulo": "Organizar", "estado": "rodando"}]}
    with respx.mock:
        respx.get(f"{B}/api/processar/tvp_meu").respond(200, json=corpo)
        asyncio.run(rota._repassar("tvp_meu"))
        asyncio.run(rota._repassar("tvp_meu"))
    assert enviadas == ["🛠️ Ibitinga: Organizar, etapa 1 de 1"]   # relido lá, e uma vez só por etapa


@respx.mock
def test_provisionar_liga_e_desliga_e_a_plataforma_nunca(monkeypatch):
    ctx = _ctx(monkeypatch)
    rota = respx.post(f"{B}/api/conta/gs/provisionar").respond(200, json={"acao": "bloqueada"})
    assert asyncio.run(tv.provisionar(ctx.db, ctx.user, False)) is None and rota.called
    adm = SimpleNamespace(**{**vars(ctx.user), "perfil": Perfil.ADMINISTRADOR})
    rota.reset()
    assert asyncio.run(tv.provisionar(ctx.db, adm, True)) is None and not rota.called


@respx.mock
def test_ja_processando_manda_o_link_que_esta_rodando(monkeypatch):
    ctx = _ctx(monkeypatch)
    respx.post(f"{B}/api/conta/gs").respond(200)
    respx.get(f"{B}/api/processar/opcoes").respond(200, json={
        **OPC, "usina": {"nome": "Ibitinga"}, "usinas_com_o_nome": 1, "processando": True, "status_url": f"{B}/p/tvp_x"})
    r = asyncio.run(tv.processar_usina(ctx, {"usina": "ibitinga"}))
    assert f"{B}/p/tvp_x" in r["erro"] and ctx.proposta is None


class _Mw:
    async def mapa(self, slug):
        return {"objetos": [
            {"id": 7, "tipo": "string", "nome": "U1-3S22", "slot_id": 45, "string_number": 22,
             "geometria": {"type": "Polygon", "coordinates": [[[-46, -22], [-46, -22.1], [-46.1, -22]]]}},
            {"id": 8, "tipo": "mesa", "geometria": {"type": "Point", "coordinates": [-46, -22]}}]}

    async def strings_por_vaga(self, slug):
        return {"inverters": [{"slot_id": 45, "label": "Inv 13"}]}


@respx.mock
def test_processar_leva_as_strings_do_meuwatt_inteiras(monkeypatch):
    ctx = _ctx(monkeypatch)
    ctx.mw, ctx.usinas = _Mw(), {"ufv-ouro-fino": {"nome": "Ouro Fino", "slug": "ufv-ouro-fino"}}
    respx.post(f"{B}/api/conta/gs").respond(200)
    respx.get(f"{B}/api/processar/opcoes").respond(200, json={**OPC, "usina": {"nome": "Ouro Fino", "codigo": "of1"},
                                                              "usinas_com_o_nome": 1})
    respx.post(f"{B}/api/processar").respond(201, json={
        "token": "tvp_of", "status_url": f"{B}/p/tvp_of", "usina": {"nome": "Ouro Fino", "codigo": "of1"}})
    rota = respx.post(f"{B}/api/usinas/of1/strings/meuwatt").respond(200, json={"criadas": 1, "atualizadas": 0,
                                                                                "removidas": 0, "avisos": []})
    asyncio.run(tv.processar_usina(ctx, {"usina": "ouro fino"}))
    assert any("Leva as 1 strings" in d for d in ctx.proposta.detalhes)
    texto = asyncio.run(ctx.proposta.executar(ctx.db, ctx.user, "1"))
    import json
    enviado = json.loads(rota.calls[0].request.content)
    assert enviado["slug"] == "ufv-ouro-fino" and enviado["strings"] == [
        {"id_meuwatt": 7, "nome": "U1-3S22", "geometria": {"type": "Polygon", "coordinates": [[[-46, -22], [-46, -22.1],
         [-46.1, -22]]]}, "slot_id": 45, "inversor": "Inv 13", "entrada": 22}]
    assert "1 novas" in texto
    helper.PENDENTES.clear()


@respx.mock
def test_usina_pronta_manda_o_link_e_so_refaz_quando_pedem(monkeypatch):
    ctx = _ctx(monkeypatch)
    respx.post(f"{B}/api/conta/gs").respond(200)
    respx.get(f"{B}/api/processar/opcoes").respond(200, json={
        **OPC, "usina": {"nome": "Ibitinga", "codigo": "zy"}, "usinas_com_o_nome": 1, "no_envio": {"arquivos": 0},
        "ultimo": {"estado": "concluido", "link_final": "/v/tvv_1", "status_url": f"{B}/p/tvp_1"}})
    r = asyncio.run(tv.processar_usina(ctx, {"usina": "ibitinga"}))
    assert r["link"] == f"{B}/v/tvv_1" and ctx.proposta is None
    pedido = respx.post(f"{B}/api/processar").respond(201, json={"token": "t", "status_url": "u", "usina": {}})
    asyncio.run(tv.processar_usina(ctx, {"usina": "ibitinga", "refazer": True}))
    assert ctx.proposta.resumo.startswith("REFAZER Ibitinga")
    asyncio.run(ctx.proposta.executar(ctx.db, ctx.user, "1"))
    import json
    assert json.loads(pedido.calls[0].request.content)["refazer"] is True
    helper.PENDENTES.clear()


TV_TOOLS = [{"name": "usina_estado", "annotations": {"readOnlyHint": True}},
            {"name": "mesas_motor", "annotations": {"readOnlyHint": False}, "_meta": {"confirmar": True, "pesado": True},
             "description": "motor"},
            {"name": "usina_link_publico", "annotations": {"readOnlyHint": False}, "_meta": {"confirmar": False}}]


def _mcp_falso(monkeypatch, chamadas):
    async def mcp(self, payload):
        chamadas.append(payload)
        if payload["method"] == "tools/list":
            return {"result": {"tools": TV_TOOLS}}
        return {"result": {"content": [{"type": "text", "text": "ok " + payload["params"]["name"]}]}}
    monkeypatch.setattr(tv.ClienteMcp, "mcp", mcp)


def test_comando_com_confirmar_espera_o_sim_e_sem_confirmar_roda(monkeypatch):
    ctx, chamadas = _ctx(monkeypatch), []
    _mcp_falso(monkeypatch, chamadas)
    r = asyncio.run(tv.comando_termovision(ctx, {"nome": "mesas_motor", "argumentos": {"usina": "Ibitinga",
                                                                                      "profundidade": 1}}))
    assert "erro" not in r and "roda horas" in ctx.proposta.resumo and len(chamadas) == 1  # só a lista
    assert asyncio.run(ctx.proposta.executar(ctx.db, ctx.user, "1")) == "✅ ok mesas_motor"
    helper.PENDENTES.clear()
    ctx.proposta = None
    r = asyncio.run(tv.comando_termovision(ctx, {"nome": "usina_link_publico", "argumentos": {"usina": "x"}}))
    assert r == {"resultado": "ok usina_link_publico"} and ctx.proposta is None
    lista = asyncio.run(tv.comando_termovision(ctx, {}))["comandos"]
    assert [c["nome"] for c in lista] == ["mesas_motor", "usina_link_publico"]      # a leitura não é comando


def test_o_conector_so_le_o_termovision(monkeypatch):
    from app.api.v1 import mcp
    chamadas = []
    _mcp_falso(monkeypatch, chamadas)
    monkeypatch.setattr(mcp, "servicos", lambda u: ["termovision"])
    nomes = [t["name"] for t in asyncio.run(mcp._ferramentas(None, SimpleNamespace(id=1)))]
    assert nomes == ["termovision_usina_estado"]
    r = asyncio.run(mcp._chamar(None, SimpleNamespace(id=1), "termovision_mesas_motor", {}))
    assert r["isError"] and not any(c["method"] == "tools/call" for c in chamadas)
    r = asyncio.run(mcp._chamar(None, SimpleNamespace(id=1), "termovision_usina_estado", {"usina": "x"}))
    assert r["content"][0]["text"] == "ok usina_estado"
