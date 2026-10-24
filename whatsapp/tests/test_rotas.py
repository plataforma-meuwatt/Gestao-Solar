"""As duas portas: a da Meta (assinatura) e a do BFF (chave).

O que estes testes protegem é o que separa este serviço de um relé aberto: sem assinatura
válida, qualquer um forjaria mensagem chegando do cliente; sem a chave interna, qualquer um
mandaria mensagem em nome da empresa.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
