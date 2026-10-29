"""As duas portas: a da Meta (assinatura) e a do BFF (chave).

O que estes testes protegem é o que separa este serviço de um relé aberto: sem assinatura
válida, qualquer um forjaria mensagem chegando do cliente; sem a chave interna, qualquer um
mandaria mensagem em nome da empresa.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from gateway.api import interno, webhook
from gateway.core.db import get_db
from gateway.core.seguranca import (
    CABECALHO_ASSINATURA,
    CABECALHO_CHAVE_INTERNA,
    assinatura_da_meta,
)
from gateway.models.mensagem import Mensagem, WebhookEvento
from tests.conftest import APP_SECRET, VERIFY_TOKEN

CHAVE = "chave-interna-de-teste"


@pytest.fixture
def cliente(db):
    app = FastAPI()
    app.include_router(webhook.router)
    app.include_router(interno.router)
    app.dependency_overrides[get_db] = lambda: db
    # O processamento em segundo plano roda com sessão própria (SessionLocal), que nos
    # testes aponta para outro banco em memória. Aqui interessa a PORTA, não o
    # processamento — ele tem testes próprios em test_recebimento.py.
    return TestClient(app)


def _corpo() -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": "5516999998888", "id": "wamid.R1",
                                     "timestamp": "1789000000", "type": "text",
                                     "text": {"body": "oi"}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    ).encode()


# ── porta da Meta ───────────────────────────────────────────────────────────


def test_verificacao_devolve_o_desafio_em_texto_puro(cliente, credencial):
    r = cliente.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "1234567890"},
    )
    assert r.status_code == 200
    assert r.text == "1234567890"
    assert r.headers["content-type"].startswith("text/plain")


def test_verificacao_com_token_errado_e_recusada(cliente, credencial):
    r = cliente.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "outro", "hub.challenge": "1"},
    )
    assert r.status_code == 403


def test_sem_credencial_a_porta_da_meta_diz_que_falta_configurar(cliente, db):
    r = cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x"})
    assert r.status_code == 503
    assert "tela de administração" in r.json()["detail"]

    r = cliente.post("/webhook", content=_corpo())
    assert r.status_code == 503


def test_entrega_assinada_e_aceita_e_gravada(cliente, credencial, db):
    corpo = _corpo()
    r = cliente.post(
        "/webhook",
        content=corpo,
        headers={CABECALHO_ASSINATURA: assinatura_da_meta(APP_SECRET, corpo)},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    # Gravado ANTES de responder: é o que impede perder a mensagem num deploy.
    assert db.query(WebhookEvento).count() == 1


def test_entrega_e_encaminhada_crua_com_a_assinatura_da_meta(cliente, credencial, monkeypatch):
    """Quem recebe a cópia confere o HMAC com o segredo do app: só funciona com os MESMOS
    bytes e o MESMO cabeçalho que a Meta mandou."""
    from gateway.core.config import get_settings

    recebidos = []

    class _Falso:
        def __init__(self, **_): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_): ...
        async def post(self, url, content, headers):
            recebidos.append((url, content, headers[CABECALHO_ASSINATURA]))

    monkeypatch.setattr(webhook.httpx, "AsyncClient", _Falso)
    monkeypatch.setattr(get_settings(), "encaminhar_urls", "https://a/w, https://b/w")
    corpo = _corpo()
    assinatura = assinatura_da_meta(APP_SECRET, corpo)
    r = cliente.post("/webhook", content=corpo, headers={CABECALHO_ASSINATURA: assinatura})
    assert r.status_code == 200
    assert recebidos == [("https://a/w", corpo, assinatura), ("https://b/w", corpo, assinatura)]


def test_entrega_sem_assinatura_ou_com_assinatura_errada_e_recusada(cliente, credencial, db):
    corpo = _corpo()
    assert cliente.post("/webhook", content=corpo).status_code == 401
    r = cliente.post("/webhook", content=corpo,
                     headers={CABECALHO_ASSINATURA: "sha256=errada"})
    assert r.status_code == 401
    assert db.query(WebhookEvento).count() == 0


def test_corpo_alterado_depois_de_assinado_e_recusado(cliente, credencial):
    """A assinatura cobre os BYTES: mexer numa vírgula invalida, que é o ponto."""
    assinatura = assinatura_da_meta(APP_SECRET, _corpo())
    r = cliente.post("/webhook", content=b'{"entry":[]}',
                     headers={CABECALHO_ASSINATURA: assinatura})
    assert r.status_code == 401


# ── porta do BFF ────────────────────────────────────────────────────────────


def test_porta_interna_exige_a_chave(cliente, credencial):
    assert cliente.get("/interno/credenciais").status_code == 401
    assert cliente.get(
        "/interno/credenciais", headers={CABECALHO_CHAVE_INTERNA: "errada"}
    ).status_code == 401

    r = cliente.get("/interno/credenciais", headers={CABECALHO_CHAVE_INTERNA: CHAVE})
    assert r.status_code == 200
    assert r.json()["envio_pronto"] is True


def test_estado_nao_devolve_segredo_nenhum(cliente, credencial):
    dados = cliente.get("/interno/credenciais", headers={CABECALHO_CHAVE_INTERNA: CHAVE}).json()
    inteiro = json.dumps(dados)
    assert "EAAG1testeTokenDaMeta" not in inteiro
    assert APP_SECRET not in inteiro and VERIFY_TOKEN not in inteiro


def test_envio_sem_credencial_responde_503(cliente, db):
    r = cliente.post(
        "/interno/templates",
        json={"telefone": "+5516999998888", "template": "gs_parada", "parametros": []},
        headers={CABECALHO_CHAVE_INTERNA: CHAVE},
    )
    assert r.status_code == 503


def test_envio_com_recusa_da_meta_responde_200_com_o_motivo(cliente, credencial, monkeypatch, db):
    """Recusa é resultado do envio, não falha da requisição — a tela precisa da frase."""
    from gateway.meta import graph

    async def _graph(**_k):
        return graph.Resposta(ok=False, erro_codigo="131047", erro_detalhe="fora da janela")

    monkeypatch.setattr(graph, "enviar_template", _graph)

    r = cliente.post(
        "/interno/templates",
        json={"telefone": "+5516999998888", "template": "gs_parada", "parametros": ["x"]},
        headers={CABECALHO_CHAVE_INTERNA: CHAVE},
    )
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["ok"] is False and corpo["erro"] == "fora da janela"
    assert db.get(Mensagem, corpo["id"]).status == "falhou"


def test_mensagem_inexistente_responde_404(cliente, credencial):
    r = cliente.get("/interno/mensagens/9999", headers={CABECALHO_CHAVE_INTERNA: CHAVE})
    assert r.status_code == 404


def test_resposta_em_texto_e_documento_sai_pela_graph_e_fica_registrada(cliente, credencial, monkeypatch, db):
    """A RESPOSTA do assistente: texto vai direto; documento sobe na Meta e vai pelo id."""
    import base64

    from gateway.meta import graph

    enviados = []

    async def _subir(**k):
        assert k["raw"] == b"%PDF-1" and k["filename"] == "a.pdf"
        return "MEDIA1", None

    async def _enviar(**k):
        enviados.append((k["tipo"], k["conteudo"]))
        return graph.Resposta(ok=True, wamid=f"wamid.{len(enviados)}")

    monkeypatch.setattr(graph, "subir_midia", _subir)
    monkeypatch.setattr(graph, "enviar_conteudo", _enviar)
    h = {CABECALHO_CHAVE_INTERNA: CHAVE}
    r1 = cliente.post("/interno/conteudo", headers=h,
                      json={"telefone": "+5516999998888", "tipo": "text", "texto": "oi"})
    r2 = cliente.post("/interno/conteudo", headers=h,
                      json={"telefone": "+5516999998888", "tipo": "document", "texto": "Relatório",
                            "arquivo_b64": base64.b64encode(b"%PDF-1").decode(), "filename": "a.pdf"})
    assert r1.json()["ok"] and r2.json()["ok"]
    assert enviados == [("text", {"body": "oi", "preview_url": False}),
                        ("document", {"id": "MEDIA1", "filename": "a.pdf", "caption": "Relatório"})]
    assert db.get(Mensagem, r2.json()["id"]).status == "enviada"
    assert cliente.post("/interno/conteudo", json={"telefone": "+55", "tipo": "text", "texto": "x"}).status_code == 401


def test_a_saude_do_canal_conta_o_que_esta_parado(cliente, db):
    """O que teria mostrado o bot surdo de 10/2026: entregas paradas e o erro delas."""
    from gateway.models.mensagem import WebhookEvento

    from datetime import UTC, datetime, timedelta

    from gateway.models.mensagem import Mensagem

    agora = datetime.now(UTC)
    recebida, entregue = agora - timedelta(minutes=30), agora - timedelta(minutes=20)
    db.add_all([
        Mensagem(direcao="entrada", wa_id="5517", telefone="+5517", tipo="text", texto="oi", ocorrida_em=recebida,
                 status="recebida", notificada_bff_em=agora),
        Mensagem(direcao="saida", wa_id="5517", telefone="+5517", tipo="text", texto="olá",
                 ocorrida_em=agora - timedelta(minutes=25), status="entregue", status_em=entregue),
        WebhookEvento(corpo={}, erro="StringDataRightTruncation", tentativas=1, recebido_em=agora - timedelta(minutes=10)),
        # A que acabou de chegar ainda está sendo processada, e a de dois dias atrás já desistiu:
        # nenhuma das duas diz que o canal está surdo AGORA.
        WebhookEvento(corpo={}, recebido_em=agora),
        WebhookEvento(corpo={}, erro="antigo", tentativas=10, recebido_em=agora - timedelta(days=2)),
    ])
    db.commit()
    sem_chave = cliente.get("/interno/saude")
    assert sem_chave.status_code == 401
    r = cliente.get("/interno/saude", headers={"X-Chave-Interna": "chave-interna-de-teste"})
    assert r.status_code == 200
    d = r.json()
    assert d["eventos_parados"] == 1 and d["eventos_com_erro"] == 1 and "Truncation" in d["ultimo_erro"]
    # As datas, cada uma da sua coluna (a consulta é uma só, com sete partes).
    assert d["mensagens_sem_aviso"] == 0
    assert datetime.fromisoformat(d["ultima_recebida_em"]).replace(tzinfo=UTC) == recebida
    assert datetime.fromisoformat(d["ultima_entregue_em"]).replace(tzinfo=UTC) == entregue


def test_a_senha_digitada_sai_da_mensagem_e_da_entrega_crua(cliente, db):
    """O bot pede a senha de atuação no WhatsApp: guardada aqui, ela ficaria em claro."""
    from datetime import UTC, datetime

    from gateway.models.mensagem import Mensagem, WebhookEvento

    corpo = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "wamid.SENHA", "type": "text", "text": {"body": "482913"}},
        {"id": "wamid.OUTRA", "type": "text", "text": {"body": "bom dia"}},
    ]}}]}]}
    ev = WebhookEvento(corpo=corpo, processado_em=datetime.now(UTC))
    m = Mensagem(wamid="wamid.SENHA", direcao="entrada", wa_id="5517997377626", tipo="text", texto="482913",
                 ocorrida_em=datetime.now(UTC))
    db.add_all([ev, m])
    db.commit()

    assert cliente.post(f"/interno/mensagens/{m.id}/ocultar").status_code == 401
    r = cliente.post(f"/interno/mensagens/{m.id}/ocultar", headers={"X-Chave-Interna": "chave-interna-de-teste"})
    assert r.status_code == 204
    db.expire_all()
    assert db.get(Mensagem, m.id).texto == "[senha de atuação]"
    msgs = db.get(WebhookEvento, ev.id).corpo["entry"][0]["changes"][0]["value"]["messages"]
    assert [x["text"]["body"] for x in msgs] == ["[senha de atuação]", "bom dia"]
    assert "482913" not in str(db.get(WebhookEvento, ev.id).corpo)

    # Numa frase, fica o texto sem a senha — a frase continua legível.
    m2 = Mensagem(wamid="wamid.FRASE", direcao="entrada", wa_id="5517997377626", tipo="text",
                  texto="pode ligar, senha 482913", ocorrida_em=datetime.now(UTC))
    db.add(m2)
    db.commit()
    r = cliente.post(f"/interno/mensagens/{m2.id}/ocultar", headers={"X-Chave-Interna": "chave-interna-de-teste"},
                     json={"texto": "pode ligar, senha [senha oculta]"})
    assert r.status_code == 204
    db.expire_all()
    assert db.get(Mensagem, m2.id).texto == "pode ligar, senha [senha oculta]"


# ── avaliação 11: o bot é avisado NA HORA, uma vez só; o áudio é baixado sob pedido ───────


def _bff_falso(monkeypatch, demora=0.0):
    """O BFF de mentira: guarda o corpo de cada aviso."""
    import asyncio

    from gateway.core.config import get_settings
    from gateway.services import notificacao_bff

    avisos = []

    class _Cliente:
        def __init__(self, **_): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_): ...
        async def post(self, url, json, headers):
            await asyncio.sleep(demora)
            avisos.append(json)

            class _R:
                def raise_for_status(self): ...
            return _R()

    monkeypatch.setattr(notificacao_bff.httpx, "AsyncClient", _Cliente)
    monkeypatch.setattr(get_settings(), "bff_url", "http://bff")
    monkeypatch.setattr(get_settings(), "whatsapp_chave_interna", CHAVE)
    return avisos


def test_a_mensagem_chega_ao_bot_na_hora_sem_esperar_a_varredura(cliente, credencial, db, monkeypatch):
    """Só a varredura de 60 s avisava o BFF: a pessoa esperava até um minuto, e a senha
    mandada antes do resumo chegava ao bot depois dele (avaliação 11)."""
    avisos = _bff_falso(monkeypatch)
    monkeypatch.setattr(webhook, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    corpo = _corpo()
    r = cliente.post("/webhook", content=corpo, headers={CABECALHO_ASSINATURA: assinatura_da_meta(APP_SECRET, corpo)})
    assert r.status_code == 200
    assert [a["texto"] for a in avisos] == ["oi"]
    assert db.query(Mensagem).one().notificada_bff_em is not None


async def test_aviso_imediato_e_varredura_juntos_avisam_uma_vez_so(db, monkeypatch):
    """O webhook e a varredura podem rodar ao mesmo tempo: sem a trava, os dois pegariam a
    mesma mensagem, e o bot responderia em dobro."""
    import asyncio
    from datetime import UTC, datetime

    from sqlalchemy.orm import sessionmaker

    from gateway.services import notificacao_bff

    avisos = _bff_falso(monkeypatch, demora=0.05)
    db.add_all([Mensagem(wamid=f"wamid.{i}", direcao="entrada", wa_id="5516", telefone="+5516", tipo="text",
                         texto=f"m{i}", ocorrida_em=datetime.now(UTC), status="recebida") for i in range(3)])
    db.commit()
    outra = sessionmaker(bind=db.get_bind())()
    await asyncio.gather(notificacao_bff.avisar_pendentes(db), notificacao_bff.avisar_pendentes(outra))
    assert sorted(a["texto"] for a in avisos) == ["m0", "m1", "m2"]


def test_o_audio_e_baixado_da_meta_so_quando_o_bot_pede(cliente, credencial, db, monkeypatch):
    from datetime import UTC, datetime

    from gateway.meta import graph

    pedidos = []

    async def _baixar(*, token, media_id):
        pedidos.append(media_id)
        return b"OGG", "audio/ogg", None

    monkeypatch.setattr(graph, "baixar_midia", _baixar)
    com = Mensagem(wamid="wamid.A", direcao="entrada", wa_id="5516", telefone="+5516", tipo="audio",
                   midia={"id": "m-1", "mime": "audio/ogg"}, ocorrida_em=datetime.now(UTC), status="recebida")
    sem = Mensagem(wamid="wamid.T", direcao="entrada", wa_id="5516", telefone="+5516", tipo="text", texto="oi",
                   ocorrida_em=datetime.now(UTC), status="recebida")
    db.add_all([com, sem])
    db.commit()
    h = {CABECALHO_CHAVE_INTERNA: CHAVE}
    assert cliente.get(f"/interno/mensagens/{com.id}/midia").status_code == 401
    r = cliente.get(f"/interno/mensagens/{com.id}/midia", headers=h)
    assert r.status_code == 200 and r.content == b"OGG" and r.headers["content-type"].startswith("audio/ogg")
    assert cliente.get(f"/interno/mensagens/{sem.id}/midia", headers=h).status_code == 404
    assert pedidos == ["m-1"]


def test_resposta_com_botoes_sai_como_interativa_da_meta(cliente, credencial, monkeypatch, db):
    """Dono (24/10/2026): "Ao invés de digitar sim tem como enviar botão, sim e não?" O toque volta
    como mensagem `interactive` com o título do botão — e o bot o lê como texto."""
    from gateway.meta import graph

    enviados = []

    async def _graph(**k):
        enviados.append(k)
        return graph.Resposta(ok=True, wamid="wamid.B1")

    monkeypatch.setattr(graph, "enviar_conteudo", _graph)
    h = {CABECALHO_CHAVE_INTERNA: CHAVE}
    r = cliente.post("/interno/conteudo", headers=h, json={
        "telefone": "+5517997377626", "tipo": "botoes", "texto": "Criar a OS em Ibitinga?",
        "botoes": [{"id": "sim", "titulo": "Sim"}, {"id": "nao", "titulo": "Não"}]})
    assert r.status_code == 200 and r.json()["ok"]
    assert enviados[0]["tipo"] == "interactive"
    assert enviados[0]["conteudo"] == {"type": "button", "body": {"text": "Criar a OS em Ibitinga?"}, "action": {
        "buttons": [{"type": "reply", "reply": {"id": "sim", "title": "Sim"}},
                    {"type": "reply", "reply": {"id": "nao", "title": "Não"}}]}}
    linha = db.query(Mensagem).filter_by(wamid="wamid.B1").one()
    assert (linha.tipo, linha.texto) == ("interactive", "Criar a OS em Ibitinga?")
    # Mais de 3 botões, título longo ou texto acima de 1024: recusado antes de gastar a Meta.
    for ruim in ({"botoes": [{"id": str(i), "titulo": "x"} for i in range(4)], "texto": "a"},
                 {"botoes": [{"id": "s", "titulo": "Sim, pode criar a OS agora"}], "texto": "a"},
                 {"botoes": [{"id": "s", "titulo": "Sim"}], "texto": "a" * 1025}):
        assert cliente.post("/interno/conteudo", headers=h,
                            json={"telefone": "+5517997377626", "tipo": "botoes", **ruim}).status_code in (400, 422)
    assert len(enviados) == 1



def test_formulario_de_marcar_sai_como_flow_da_meta(cliente, credencial, monkeypatch, db):
    """Dono (29/10/2026): "não tem como ele enviar a lista e eu clico só nas que quero?" — as opções vão no formulário
    publicado (`gs_escolha_multipla`), com as já marcadas pré-marcadas; o que volta é o índice."""
    from gateway.meta import graph

    enviados, pedidos = [], []

    async def _graph(**k):
        enviados.append(k)
        return graph.Resposta(ok=True, wamid="wamid.F1")

    async def _id(**k):
        pedidos.append(k["nome"])
        return "1487572283291378", None

    monkeypatch.setattr(graph, "enviar_conteudo", _graph)
    monkeypatch.setattr(graph, "id_do_flow", _id)
    h = {CABECALHO_CHAVE_INTERNA: CHAVE}
    r = cliente.post("/interno/conteudo", headers=h, json={
        "telefone": "+5517997377626", "tipo": "formulario", "texto": "Marque os centros de custo",
        "formulario": {"token": "tok-123456", "titulo": "Centros de custo do #1736", "aviso": "Nenhum = todos.",
                       "opcoes": ["Roçagem", "Lavagem", "Receitas de Serviços Eventuais (Avulsos)"],
                       "marcados": ["Lavagem", "Não existe"]}})
    assert r.status_code == 200 and r.json()["ok"] and pedidos == ["gs_escolha_multipla"]
    c = enviados[0]["conteudo"]
    assert enviados[0]["tipo"] == "interactive" and c["type"] == "flow"
    p = c["action"]["parameters"]
    assert (p["flow_id"], p["flow_token"], p["flow_action"]) == ("1487572283291378", "tok-123456", "navigate")
    assert p["flow_action_payload"] == {"screen": "ESCOLHA", "data": {
        "titulo": "Centros de custo do #1736", "aviso": "Nenhum = todos.",
        "opcoes": [{"id": "0", "title": "Roçagem"}, {"id": "1", "title": "Lavagem"},
                   {"id": "2", "title": "Receitas de Serviços Eventuais"}], "marcados": ["1"]}}
    assert db.query(Mensagem).filter_by(wamid="wamid.F1").one().texto == "Marque os centros de custo"

    async def _sem(**k):
        return None, "O formulário «gs_escolha_multipla» não está publicado na conta do WhatsApp."

    monkeypatch.setattr(graph, "id_do_flow", _sem)            # sem o formulário na conta: ok falso, nada sai
    r = cliente.post("/interno/conteudo", headers=h, json={
        "telefone": "+5517997377626", "tipo": "formulario", "texto": "x",
        "formulario": {"token": "tok-123456", "titulo": "t", "opcoes": ["a"]}})
    assert r.status_code == 200 and not r.json()["ok"] and "não está publicado" in r.json()["erro"]
    assert len(enviados) == 1

def test_o_toque_no_botao_chega_ao_bot_com_o_id_do_resumo(cliente, credencial, db, monkeypatch):
    """O título ("Sim") não diz de QUAL resumo era o botão; o id diz — e vai guardado, para a
    varredura também repassá-lo (avaliação 13: o Sim de um resumo antigo confirmava o de agora)."""
    avisos = _bff_falso(monkeypatch)
    monkeypatch.setattr(webhook, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    corpo = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "5516999998888", "id": "wamid.B9", "timestamp": "1789000000", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": "sim:a1b2c3d4", "title": "Sim"}}}]}}]}]}).encode()
    r = cliente.post("/webhook", content=corpo, headers={CABECALHO_ASSINATURA: assinatura_da_meta(APP_SECRET, corpo)})
    assert r.status_code == 200
    assert [(a["texto"], a["botao"]) for a in avisos] == [("Sim", "sim:a1b2c3d4")]
    assert db.query(Mensagem).filter_by(wamid="wamid.B9").one().botao == "sim:a1b2c3d4"


# ── avaliação 26: a senha que o bot revela ou que a pessoa manda gravar não fica guardada aqui ─────────────────


def test_a_resposta_vai_inteira_a_meta_e_fica_guardada_sem_a_senha(cliente, credencial, monkeypatch, db):
    from gateway.meta import graph

    enviados = []

    async def _enviar(**k):
        enviados.append(k["conteudo"]["body"])
        return graph.Resposta(ok=True, wamid="wamid.S")

    monkeypatch.setattr(graph, "enviar_conteudo", _enviar)
    r = cliente.post("/interno/conteudo", headers={CABECALHO_CHAVE_INTERNA: CHAVE},
                     json={"telefone": "+5516999998888", "tipo": "text", "texto": "SL1: admin / Huawei@123",
                           "guardar": "SL1: admin / ••••"})
    assert enviados == ["SL1: admin / Huawei@123"]
    assert db.get(Mensagem, r.json()["id"]).texto == "SL1: admin / ••••"


def test_os_valores_somem_das_mensagens_recentes_do_numero(cliente, db):
    from datetime import UTC, datetime, timedelta

    from gateway.models.mensagem import WebhookEvento

    agora = datetime.now(UTC)
    corpo = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "wamid.G", "type": "text", "text": {"body": "grava aí: SL2, usuário admin, changeme"}}]}}]}]}
    db.add_all([
        WebhookEvento(corpo=corpo, processado_em=agora, recebido_em=agora),
        Mensagem(wamid="wamid.G", direcao="entrada", wa_id="5517997377626", telefone="+5517997377626", tipo="text",
                 texto="grava aí: SL2, usuário admin, changeme", ocorrida_em=agora),
        Mensagem(direcao="saida", wa_id="5517997377626", telefone="+5517997377626", tipo="text",
                 texto="Gravar changeme no SL2?", ocorrida_em=agora),
        Mensagem(direcao="saida", wa_id="5517997377626", telefone="+5517997377626", tipo="text",
                 texto="changemeX não é o valor", ocorrida_em=agora),                  # só o valor INTEIRO
        Mensagem(direcao="saida", wa_id="5517997377626", telefone="+5517997377626", tipo="text",
                 texto="ab de abril", ocorrida_em=agora),                              # curto demais para ser senha
        Mensagem(direcao="saida", wa_id="5511900000000", telefone="+5511900000000", tipo="text",
                 texto="changeme de outro número", ocorrida_em=agora),
        Mensagem(direcao="saida", wa_id="5517997377626", telefone="+5517997377626", tipo="text",
                 texto="changeme de três dias atrás", ocorrida_em=agora - timedelta(days=3)),
    ])
    db.commit()
    h = {"X-Chave-Interna": "chave-interna-de-teste"}
    assert cliente.post("/interno/mensagens/mascarar", json={"telefone": "+5517997377626", "valores": ["x"]}
                        ).status_code == 401
    r = cliente.post("/interno/mensagens/mascarar", headers=h,
                     json={"telefone": "+55 17 99737-7626", "valores": ["changeme", "ab"]})
    assert r.json() == {"alteradas": 2}
    db.expire_all()
    textos = {m.texto for m in db.scalars(select(Mensagem))}
    assert textos == {"grava aí: SL2, usuário admin, ••••", "Gravar •••• no SL2?", "changemeX não é o valor", "ab de abril",
                      "changeme de outro número", "changeme de três dias atrás"}
    assert "changeme" not in str(db.scalars(select(WebhookEvento)).one().corpo)


def test_a_mensagem_que_saiu_tambem_perde_a_senha(cliente, db):
    """A limpeza das mensagens antigas (avaliação 27: o número do cadeado de 22/10 seguia aqui) passa também pelas que
    o bot MANDOU."""
    from datetime import UTC, datetime

    m = Mensagem(direcao="saida", wa_id="5517997377626", telefone="+5517997377626", tipo="text",
                 texto="Senha do cadeado: 3262", ocorrida_em=datetime.now(UTC))
    db.add(m)
    db.commit()
    h = {"X-Chave-Interna": "chave-interna-de-teste"}
    assert cliente.post(f"/interno/mensagens/{m.id}/ocultar", headers=h,
                        json={"texto": "Senha do cadeado: ••••"}).status_code == 204
    db.expire_all()
    assert db.get(Mensagem, m.id).texto == "Senha do cadeado: ••••"
    assert cliente.post("/interno/mensagens/999999/ocultar", headers=h).status_code == 404
