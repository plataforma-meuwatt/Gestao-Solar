"""O conector do Claude, um só (`api/v1/mcp.py`): login com a conta do Gestão Solar e o repasse aos conectores do
meuWatt e do meuPlano com o token PRÓPRIO da pessoa — o que se lê é o que o bot responde a ela."""

import hashlib
import re
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.api.v1 import mcp
from app.clients.meuplano import MeuPlanoClient
from app.clients.meuwatt import MeuWattClient
from app.core.cripto import cifrar
from app.core.security import gerar_hash_senha
from app.models.mcp import TokenMcp
from app.models.user import Perfil, User, VinculoProduto

CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PAT_MW = "mw_pat_" + "a" * 38
PAT_MP = "mp_pat_" + "b" * 38


@pytest.fixture
def db():
    """O banco em memória numa conexão SÓ: as rotas síncronas rodam noutra thread, e o SQLite em memória de outra
    conexão nasce vazio."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield sessao
    finally:
        sessao.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _memoria_limpa():
    for d in (mcp._pedidos, mcp._codigos, mcp._falhas):
        d.clear()
    yield


@pytest.fixture
def http(db):
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app, follow_redirects=False)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def fernando(db):
    u = User(apelido="fernando.labes", email="f@eldorado.local", nome="Fernando", perfil=Perfil.CLIENTE,
             senha_hash=gerar_hash_senha("sol-1234"), bot_meuwatt=True, bot_meuplano=True)
    db.add(u)
    db.flush()
    db.add_all([VinculoProduto(gs_user_id=u.id, produto="meuwatt", usuario_remoto_id="15", token_cifrado=cifrar(PAT_MW)),
                VinculoProduto(gs_user_id=u.id, produto="meuplano", usuario_remoto_id="1735",
                               token_cifrado=cifrar(PAT_MP))])
    db.commit()
    return u


@pytest.fixture
def produtos(monkeypatch):
    """Os conectores do meuWatt e do meuPlano de mentira: anotam com que token e o que foi pedido."""
    pedidos = []
    estado = {"mp_fora": False}

    def responde(produto, token, msg):
        pedidos.append((produto, token, msg["method"], msg.get("params")))
        if produto == "meuplano" and estado["mp_fora"]:
            raise httpx.ConnectError("fora")
        metodo = msg["method"]
        if metodo == "initialize":
            frase = "Use o meuWatt." if produto == "meuwatt" else "Abra o meuPlano antes."
            return {"jsonrpc": "2.0", "id": 1, "result": {"instructions": frase}}
        if metodo == "tools/list":
            nome = "geracao" if produto == "meuwatt" else "listar_os"
            return {"jsonrpc": "2.0", "id": 1, "result": {"tools": [
                {"name": nome, "description": "Lê.", "inputSchema": {"type": "object", "properties": {}}}]}}
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": f"{produto}:ok"}],
                                                      "isError": False}}

    async def mw(self, msg):
        return responde("meuwatt", self._token_fixo, msg)

    async def mp(self, msg):
        return responde("meuplano", self._token_fixo, msg)

    monkeypatch.setattr(MeuWattClient, "mcp", mw)
    monkeypatch.setattr(MeuPlanoClient, "mcp", mp)
    return pedidos, estado


def _pkce():
    v = secrets.token_urlsafe(32)
    return v, urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def _abre(http, desafio, redirect=CALLBACK):
    r = http.get("/oauth/authorize", params={"response_type": "code", "redirect_uri": redirect,
                                             "code_challenge": desafio, "code_challenge_method": "S256",
                                             "state": "st1"})
    m = re.search(r'name="pedido" value="([^"]+)"', r.text)
    return r, m.group(1) if m else None


def _codigo(http, apelido="fernando.labes", senha="sol-1234"):
    verif, desafio = _pkce()
    _r, pedido = _abre(http, desafio)
    r = http.post("/oauth/authorize", data={"pedido": pedido, "apelido": apelido, "senha": senha, "acao": "autorizar"})
    q = parse_qs(urlparse(r.headers.get("location", "")).query)
    return r, verif, (q.get("code") or [None])[0], q


def _token(http, **kw):
    _r, verif, codigo, _q = _codigo(http, **kw)
    r = http.post("/oauth/token", data={"grant_type": "authorization_code", "code": codigo, "code_verifier": verif,
                                        "redirect_uri": CALLBACK})
    return r.json()["access_token"]


def _dos_sistemas(http, token):
    """As ferramentas dos outros sistemas (as da casa, `gs_…`, têm o teste delas no fim)."""
    return [t["name"] for t in _rpc(http, token, "tools/list").json()["result"]["tools"] if not t["name"].startswith("gs_")]


def _rpc(http, token, metodo, params=None):
    r = http.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "method": metodo, "params": params or {}},
                  headers={"Authorization": f"Bearer {token}"})
    return r


def test_descoberta_aponta_para_esta_api(http):
    r = http.get("/.well-known/oauth-protected-resource").json()
    assert r["resource"].endswith("/mcp") and r["authorization_servers"]
    a = http.get("/.well-known/oauth-authorization-server").json()
    assert a["code_challenge_methods_supported"] == ["S256"] and a["token_endpoint"].endswith("/oauth/token")


def test_destino_de_fora_nao_recebe_nada(http):
    _v, desafio = _pkce()
    r, pedido = _abre(http, desafio, redirect="https://ladrao.example/cb")
    assert r.status_code == 400 and pedido is None and "location" not in r.headers


def test_login_certo_manda_o_codigo_so_ao_claude(http, db, fernando):
    r, _v, codigo, q = _codigo(http)
    assert r.status_code == 303 and r.headers["location"].startswith(CALLBACK + "?") and codigo and q["state"] == ["st1"]


def test_senha_errada_nao_da_codigo_e_cinco_travam_o_apelido(http, db, fernando):
    _v, desafio = _pkce()
    _r, pedido = _abre(http, desafio)
    for _ in range(5):
        r = http.post("/oauth/authorize", data={"pedido": pedido, "apelido": "fernando.labes", "senha": "x",
                                                "acao": "autorizar"})
        assert r.status_code == 401 and "inválidos" in r.text and "location" not in r.headers
    r = http.post("/oauth/authorize", data={"pedido": pedido, "apelido": "fernando.labes", "senha": "sol-1234",
                                            "acao": "autorizar"})
    assert r.status_code == 429 and "location" not in r.headers


def test_cancelar_devolve_negado(http, db, fernando):
    _v, desafio = _pkce()
    _r, pedido = _abre(http, desafio)
    r = http.post("/oauth/authorize", data={"pedido": pedido, "acao": "cancelar"})
    assert r.status_code == 303 and "error=access_denied" in r.headers["location"]


def test_conta_sem_sistema_liberado_nao_conecta(http, db):
    db.add(User(apelido="semnada", nome="S", perfil=Perfil.CLIENTE, senha_hash=gerar_hash_senha("abc-12345")))
    db.commit()
    r, _v, codigo, _q = _codigo(http, apelido="semnada", senha="abc-12345")
    assert r.status_code == 403 and codigo is None and "liberados" in r.text


def test_codigo_vale_uma_vez_e_so_com_o_verificador(http, db, fernando):
    _r, verif, codigo, _q = _codigo(http)
    errado = http.post("/oauth/token", data={"grant_type": "authorization_code", "code": codigo, "code_verifier": "x"})
    assert errado.status_code == 400 and errado.json()["error"] == "invalid_grant"
    de_novo = http.post("/oauth/token", data={"grant_type": "authorization_code", "code": codigo, "code_verifier": verif})
    assert de_novo.status_code == 400  # o código saiu na 1ª tentativa
    token = _token(http)
    assert token.startswith("gs_mcp_")
    linhas = db.query(TokenMcp).all()
    assert len(linhas) == 1 and linhas[0].token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_le_os_dois_sistemas_com_o_token_dela(http, db, fernando, produtos):
    pedidos, _e = produtos
    token = _token(http)
    ini = _rpc(http, token, "initialize").json()["result"]
    assert ini["serverInfo"]["name"] == "Gestão Solar" and "Use o monitoramento." in ini["instructions"] \
        and "Abra a manutenção antes." in ini["instructions"]  # o cliente lê o serviço, nunca o produto
    nomes = _dos_sistemas(http, token)
    assert nomes == ["monitoramento_geracao", "manutencao_listar_os"]
    res = _rpc(http, token, "tools/call", {"name": "manutencao_listar_os", "arguments": {"usina": 3}}).json()["result"]
    assert res["content"][0]["text"] == "meuplano:ok"
    assert pedidos[-1] == ("meuplano", PAT_MP, "tools/call", {"name": "listar_os", "arguments": {"usina": 3}})
    assert {(p, t) for p, t, _m, _q in pedidos} == {("meuwatt", PAT_MW), ("meuplano", PAT_MP)}


def test_so_o_que_o_gerente_liberou(http, db, fernando, produtos):
    token = _token(http)
    fernando.bot_meuplano = False
    db.commit()
    nomes = _dos_sistemas(http, token)
    assert nomes == ["monitoramento_geracao"]
    res = _rpc(http, token, "tools/call", {"name": "manutencao_listar_os"}).json()["result"]
    assert res["isError"] and "liberado" in res["content"][0]["text"]


def test_sistema_fora_vira_ferramenta_que_avisa(http, db, fernando, produtos):
    _p, estado = produtos
    token = _token(http)
    estado["mp_fora"] = True
    ferramentas = [t for t in _rpc(http, token, "tools/list").json()["result"]["tools"] if not t["name"].startswith("gs_")]
    assert [t["name"] for t in ferramentas] == ["monitoramento_geracao", "manutencao_indisponivel"]
    assert "não respondeu" in ferramentas[1]["description"]
    res = _rpc(http, token, "tools/call", {"name": "manutencao_indisponivel"}).json()["result"]
    assert res["isError"] and "não respondeu" in res["content"][0]["text"]


def test_sem_token_valido_nao_entra(http, db, fernando, produtos):
    r = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
    assert _rpc(http, "gs_mcp_inventado", "tools/list").status_code == 401
    token = _token(http)
    assert _rpc(http, token, "tools/list").status_code == 200
    fernando.ativo = False
    db.commit()
    assert _rpc(http, token, "tools/list").status_code == 401
    fernando.ativo = True
    db.query(TokenMcp).update({"revogado_em": TokenMcp.criado_em})
    db.commit()
    assert _rpc(http, token, "tools/list").status_code == 401


def test_o_nome_do_produto_vira_o_do_servico():
    assert mcp._sem_marca("O meuPlano não abre; veja no meuWatt.") == "A manutenção não abre; veja no monitoramento."
    assert mcp._sem_marca("as OS do meuPlano, pelo meuPlano e ao meuPlano") == \
        "as OS da manutenção, pela manutenção e à manutenção"


# ── as câmeras (meuGuarda): as leituras do bot, com a sessão do GS da pessoa ─────────────────────
class _MeuGuarda:
    def __init__(self):
        self.contagens = []

    async def usinas(self):
        return [{"id": 1, "nome": "UFV Pereiras", "com_sinal": True, "cameras": 2, "cameras_online": 2,
                 "alarmes_abertos": 1}]

    async def cameras(self, usina_id):
        return [{"id": 7, "nome": "Perímetro 03", "tipo": "camera", "canais": 1, "online": True,
                 "deteccao_desligada_ate": None, "alarmes_abertos": 1, "ultimo_evento": None},
                {"id": 8, "nome": "Térmica 02", "tipo": "camera", "canais": 2, "online": True,
                 "deteccao_desligada_ate": None, "alarmes_abertos": 0, "ultimo_evento": None}]

    async def alarmes(self):
        return [{"usina": "UFV Pereiras", "camera": "Perímetro 03", "tipo": "pessoa", "prioridade": 1,
                 "aberto_em": "2026-11-17T20:21:01+00:00"}]

    async def contar(self, filtro):
        self.contagens.append(filtro)
        return {"total": 3, "por_camera": [{"nome": "Perímetro 03", "n": 3}], "por_tipo": [{"tipo": "pessoa", "n": 3}]}

    async def foto(self, camera_id, canal=1):
        return b"\xff\xd8jpeg", "isapi"


@pytest.fixture
def cameras(monkeypatch, db, fernando):
    from app.services import assistente_meuguarda

    falso = _MeuGuarda()
    monkeypatch.setattr(assistente_meuguarda, "cliente", lambda user: falso)
    fernando.meuguarda_liberado = True
    db.commit()
    return falso


def test_as_cameras_entram_com_o_acesso_ao_meuguarda(http, db, fernando, produtos, cameras):
    token = _token(http)
    nomes = _dos_sistemas(http, token)
    assert nomes[-3:] == ["meuguarda_cameras", "meuguarda_eventos", "meuguarda_foto"]
    assert not any("ver" in n or "alarme_" in n or "classificar" in n for n in nomes)  # sem o ao vivo e sem ação
    estado = _rpc(http, token, "tools/call", {"name": "meuguarda_cameras"}).json()["result"]
    assert not estado["isError"] and "Perímetro 03" in estado["content"][0]["text"]
    ev = _rpc(http, token, "tools/call", {"name": "meuguarda_eventos", "arguments": {
        "cameras": ["perímetro 3"], "de": "2026-11-16", "ate": "2026-11-17"}}).json()["result"]
    assert '"total": 3' in ev["content"][0]["text"] and cameras.contagens[-1]["camera_ids"] == [7]
    assert cameras.contagens[-1]["de"].startswith("2026-11-16T00:00:00-03:00")
    foto = _rpc(http, token, "tools/call", {"name": "meuguarda_foto", "arguments": {"camera": "térmica 2"}}).json()["result"]
    assert foto["content"][1] == {"type": "image", "data": "/9hqcGVn", "mimeType": "image/jpeg"}
    assert foto["content"][0]["text"].startswith("Térmica 02 · UFV Pereiras")


def test_sem_o_acesso_ao_meuguarda_as_cameras_nao_abrem(http, db, fernando, produtos, cameras):
    token = _token(http)
    fernando.meuguarda_liberado = False
    db.commit()
    nomes = _dos_sistemas(http, token)
    assert not any(n.startswith("meuguarda_") for n in nomes)
    res = _rpc(http, token, "tools/call", {"name": "meuguarda_foto", "arguments": {"camera": "térmica 2"}}).json()["result"]
    assert res["isError"] and "câmeras" in res["content"][0]["text"]



def test_as_regras_e_a_memoria_da_propria_pessoa_so_leitura(http, db, fernando, produtos):
    """Plano Assistente GS, Fase 2: o conector lê "minhas regras" e "minha memória" (criar e mexer segue no bot)."""
    import json
    from datetime import datetime

    from app.services import automacoes as auto
    from app.services import memoria

    outra = User(apelido="vizinha", nome="Vizinha", email="v@x.com", senha_hash="x", perfil=Perfil.CLIENTE)
    db.add(outra)
    db.commit()
    auto.criar(db, fernando, nome="Resumo da geração às 19:00", gatilho={"tipo": "horario", "hora": "19:00"},
               acao={"tipo": "resumo_geracao"}, escopo={"todas": True}, agora=datetime.now(auto.BRT))
    auto.criar(db, outra, nome="Regra da vizinha", gatilho={"tipo": "horario", "hora": "07:00"},
               acao={"tipo": "resumo_geracao"}, escopo={"todas": True}, agora=datetime.now(auto.BRT))
    memoria.gravar(db, fernando, "vocabulario", "PF é Porto Ferreira")
    memoria.gravar(db, outra, "anotacao", "coisa da vizinha")
    db.commit()

    token = _token(http)
    nomes = [t["name"] for t in _rpc(http, token, "tools/list").json()["result"]["tools"]]
    assert nomes[-2:] == ["gs_minhas_regras", "gs_minha_memoria"]
    regras = json.loads(_rpc(http, token, "tools/call", {"name": "gs_minhas_regras"}).json()["result"]["content"][0]["text"])
    assert [r["nome"] for r in regras["regras"]] == ["Resumo da geração às 19:00"]        # só as dela
    mem = json.loads(_rpc(http, token, "tools/call", {"name": "gs_minha_memoria"}).json()["result"]["content"][0]["text"])
    assert mem["itens"] == [{"n": 1, "tipo": "vocabulário", "texto": "PF é Porto Ferreira"}]
    assert "gs_minhas_regras" in _rpc(http, token, "initialize").json()["result"]["instructions"]
    assert _rpc(http, token, "tools/call", {"name": "gs_apagar_tudo"}).json()["result"]["isError"]

