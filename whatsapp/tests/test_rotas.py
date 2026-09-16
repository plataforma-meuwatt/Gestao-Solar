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
