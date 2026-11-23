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
    return SimpleNamespace(db=_Db(), user=user, proposta=None, pedido="Processar ibitinga")


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
