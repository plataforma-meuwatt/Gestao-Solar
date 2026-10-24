"""A tela de administração do WhatsApp e a porta por onde o gateway avisa.

O BFF não fala com a Meta: ele repassa ao gateway. O que estes testes protegem é justamente
o que sobra do lado de cá, e cada item é uma falha silenciosa:

* **quem abre a tela.** Quem configura o WhatsApp manda mensagem em nome da empresa para
  qualquer cliente — é régua de administrador, como Conexões;
* **gateway ausente não é erro 500.** Enquanto o serviço não existir no ambiente, a tela
  precisa dizer isso com todas as letras, senão o gestor fica olhando uma tela quebrada sem
  saber que falta uma variável;
* **a porta interna falha fechada.** Sem a chave configurada, ninguém entra — nem por
  omissão, nem com chave vazia.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import criar_token_painel
from app.main import app

GW = "https://gateway.test"
CHAVE = "chave-interna-de-teste"


@pytest.fixture
def cliente_http(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def configurado(monkeypatch):
    """O ambiente com o gateway no lugar. `get_settings` é cacheado — o ajuste é no objeto."""
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_gateway_url", GW)
    monkeypatch.setattr(s, "whatsapp_chave_interna", CHAVE)
    return s


@pytest.fixture
def sem_gateway(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_gateway_url", "")
    monkeypatch.setattr(s, "whatsapp_chave_interna", "")
    return s


def _sessao(usuario) -> dict[str, str]:
    token, _ = criar_token_painel(usuario.id)
    return {"Authorization": f"Bearer {token}"}


ESTADO = {
    "configurada": True,
    "envio_pronto": True,
    "webhook_pronto": True,
    "phone_number_id": "1352387357947608",
    "waba_id": "1050499467726264",
    "app_id": "1088684893680434",
    "numero_exibicao": "+55 16 99999-8888",
    "token_prefixo": "EAAG1te",
    "estado": "ok",
    "detalhe": "Conectado como Gestão Solar · +55 16 99999-8888.",
    "cifragem_disponivel": True,
}


# ── a tela ──────────────────────────────────────────────────────────────────


@respx.mock
def test_administrador_ve_o_estado_sem_receber_segredo(cliente_http, administrador, configurado):
    respx.get(f"{GW}/interno/credenciais").respond(200, json=ESTADO)

    r = cliente_http.get("/api/painel/whatsapp", headers=_sessao(administrador))

    assert r.status_code == 200
    assert r.json()["phone_number_id"] == "1352387357947608"
    # O prefixo basta para reconhecer o token; o valor inteiro não volta de lugar nenhum.
    assert "token" not in r.json() and r.json()["token_prefixo"] == "EAAG1te"


@respx.mock
def test_a_chave_interna_vai_no_cabecalho_e_nao_na_url(cliente_http, administrador, configurado):
    """Segredo em query string acaba no log de acesso de todo intermediário do caminho."""
    rota = respx.get(f"{GW}/interno/credenciais").respond(200, json=ESTADO)

    cliente_http.get("/api/painel/whatsapp", headers=_sessao(administrador))

    pedido = rota.calls.last.request
    assert pedido.headers["X-Chave-Interna"] == CHAVE
    assert CHAVE not in str(pedido.url)


def test_atendimento_nao_abre_a_tela(cliente_http, atendente, configurado):
    """Quem configura o WhatsApp manda mensagem em nome da empresa. É régua de administrador."""
    r = cliente_http.get("/api/painel/whatsapp", headers=_sessao(atendente))
    assert r.status_code == 403


def test_sem_sessao_ninguem_entra(cliente_http, configurado):
    assert cliente_http.get("/api/painel/whatsapp").status_code == 401


def test_sem_gateway_no_ambiente_a_tela_diz_o_que_falta(cliente_http, administrador, sem_gateway):
    """503 com a frase, nunca 500: falta configuração, e o gestor precisa saber qual."""
    r = cliente_http.get("/api/painel/whatsapp", headers=_sessao(administrador))

    assert r.status_code == 503
    assert "WHATSAPP_GATEWAY_URL" in r.json()["detail"]


@respx.mock
def test_gateway_fora_do_ar_vira_frase_e_nao_tela_quebrada(cliente_http, administrador, configurado):
    respx.get(f"{GW}/interno/credenciais").mock(side_effect=httpx.ConnectError("sem rota"))

    r = cliente_http.get("/api/painel/whatsapp", headers=_sessao(administrador))

    assert r.status_code == 503
    assert "gateway" in r.json()["detail"].lower()


@respx.mock
def test_gravar_repassa_o_ator_e_devolve_a_recusa_da_meta(cliente_http, administrador, configurado):
    """Recusa da Meta é resultado, não erro da requisição: 200 com `ok: false` e o motivo.

    A tela precisa da frase inteira — "Error validating access token" não conta a ninguém
    que o token do painel do app expira em 24 horas.
    """
    rota = respx.put(f"{GW}/interno/credenciais").respond(
        200, json={"ok": False, "detalhe": "A Meta recusou o token."}
    )

    r = cliente_http.put(
        "/api/painel/whatsapp",
        headers=_sessao(administrador),
        json={"phone_number_id": "1352387357947608", "token": "EAAG1novo"},
    )

    assert r.status_code == 200
    assert r.json() == {"ok": False, "detalhe": "A Meta recusou o token."}
    # Quem gravou vai junto: o histórico do gateway mostra o autor da mudança.
    assert rota.calls.last.request.read().decode().find(administrador.identificacao) > 0


@respx.mock
def test_remover_responde_sem_corpo(cliente_http, administrador, configurado):
    respx.delete(f"{GW}/interno/credenciais").respond(204)

    r = cliente_http.delete("/api/painel/whatsapp", headers=_sessao(administrador))

    assert r.status_code == 204


# ── a porta por onde o gateway avisa ────────────────────────────────────────


AVISO = {
    "id": 7,
    "wamid": "wamid.R1",
    "wa_id": "5516999998888",
    "telefone": "+5516999998888",
    "tipo": "text",
    "texto": "oi",
}


def test_sem_chave_configurada_a_porta_interna_recusa_tudo(cliente_http, sem_gateway):
    """Falha fechada: uma porta que aceita por omissão é pior do que não existir."""
    r = cliente_http.post("/api/v1/interno/whatsapp/evento", json=AVISO)
    assert r.status_code == 503


def test_chave_errada_e_recusada(cliente_http, configurado):
    r = cliente_http.post(
        "/api/v1/interno/whatsapp/evento", json=AVISO, headers={"X-Chave-Interna": "outra"}
    )
    assert r.status_code == 401
    # Sem cabeçalho nenhum também não passa — o `or ""` não pode virar uma porta aberta.
    assert cliente_http.post("/api/v1/interno/whatsapp/evento", json=AVISO).status_code == 401


def test_com_a_chave_certa_o_aviso_e_aceito(cliente_http, configurado, monkeypatch):
    """202, e não 200: o gateway pode parar de reenviar; responder é do bot, em segundo plano."""
    from app.services import assistente

    entregues = []

    async def _atender(evento):
        entregues.append(evento["telefone"])

    monkeypatch.setattr(assistente, "atender", _atender)
    r = cliente_http.post(
        "/api/v1/interno/whatsapp/evento", json=AVISO, headers={"X-Chave-Interna": CHAVE}
    )
    assert r.status_code == 202
    assert r.json() == {"ok": True}
    assert entregues == ["+5516999998888"]


@respx.mock
async def test_dns_que_falha_uma_vez_nao_perde_a_resposta_do_bot(configurado, monkeypatch):
    """24/10/2026: o DNS do endereço do gateway falhou uma vez e a resposta do bot se perdeu.
    A conexão nem abriu — nada saiu —, então tentar de novo não duplica mensagem."""
    from app.clients import whatsapp

    async def _sem_espera(_s):
        return None

    monkeypatch.setattr(whatsapp.asyncio, "sleep", _sem_espera)
    rota = respx.post(f"{GW}/interno/conteudo").mock(
        side_effect=[httpx.ConnectError("[Errno -2] Name or service not known"), httpx.Response(200, json={"ok": True})]
    )
    assert (await whatsapp.enviar_conteudo(telefone="+5517997377626", tipo="text", texto="oi"))["ok"]
    assert rota.call_count == 2


@respx.mock
async def test_tempo_esgotado_no_meio_nao_repete(configurado):
    """Saiu e não voltou: pode ter chegado — repetir mandaria duas vezes."""
    from app.clients import whatsapp

    rota = respx.post(f"{GW}/interno/conteudo").mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(whatsapp.GatewayIndisponivel):
        await whatsapp.enviar_conteudo(telefone="+5517997377626", tipo="text", texto="oi")
    assert rota.call_count == 1


@respx.mock
def test_a_saude_do_canal_diz_quando_o_bot_esta_surdo(cliente_http, administrador, configurado):
    """O bot de 10/2026: configuração toda verde e 40 mensagens presas no gateway."""
    rota = respx.get(f"{GW}/interno/saude")
    rota.mock(return_value=httpx.Response(200, json={
        "eventos_parados": 3, "eventos_com_erro": 3, "mensagens_sem_aviso": 0,
        "ultimo_erro": "StringDataRightTruncation: value too long",
    }))
    d = cliente_http.get("/api/painel/whatsapp/saude", headers=_sessao(administrador)).json()
    assert d["ouvindo"] is False and "3 entrega" in d["resumo"] and "StringDataRightTruncation" in d["resumo"]

    rota.mock(return_value=httpx.Response(200, json={"eventos_parados": 0, "eventos_com_erro": 0, "mensagens_sem_aviso": 0}))
    assert cliente_http.get("/api/painel/whatsapp/saude", headers=_sessao(administrador)).json()["ouvindo"] is True

    rota.mock(side_effect=httpx.ConnectError("sem rota"))
    d = cliente_http.get("/api/painel/whatsapp/saude", headers=_sessao(administrador)).json()
    assert d["ouvindo"] is False and "não respondeu" in d["resumo"]
    assert cliente_http.get("/api/painel/whatsapp/saude").status_code == 401
