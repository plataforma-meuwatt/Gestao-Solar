"""R4 e R12 (Plano Casa GS, 24/11/2026): cada sessão tem número e se encerra (uma, ou todas de uma vez, inclusive as que
nunca foram usadas); a verificação em duas etapas vale para o gerente e a plataforma em todas as portas de senha (painel,
portal e aplicativo, a entrada do gestao.solar, a troca de papel para a plataforma e o conector do Claude), com o
cadastro do autenticador no primeiro login; a tela de senha de outro sistema manda ao botão do GS."""
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import criar_token, criar_token_empresa, gerar_hash_senha
from app.main import app
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa
from app.models.sessao import SessaoGS
from app.models.user import Perfil, User
from app.services import duas_etapas

SENHA = "senha-boa-123"


@pytest.fixture
def db():
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


@pytest.fixture
def http(db, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    par = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(get_settings(), "gs_sso_private_key", par.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    monkeypatch.setattr(get_settings(), "gs_2fa_desligada", False)
    from app.services import acessos
    for t in (acessos._erros, acessos._por_ip, acessos._avisados):
        t.clear()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def c(db):
    a = Empresa(nome="Splendor O&M")
    db.add(a)
    db.commit()
    h = gerar_hash_senha(SENHA)
    gerente = User(apelido="gerente", nome="Gerente", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id, senha_hash=h,
                   termovision_liberado=True)
    dono = User(apelido="dono", nome="Dono", perfil=Perfil.CLIENTE, empresa_id=a.id, senha_hash=h)
    adm = User(apelido="adm", nome="Adm", perfil=Perfil.ADMINISTRADOR, senha_hash=h)
    db.add_all([gerente, dono, adm])
    db.commit()
    return dict(a=a, gerente=gerente, dono=dono, adm=adm)


def _codigo(segredo: str, passos: int = 0) -> str:
    return duas_etapas._codigo(segredo.replace(" ", ""), int(time.time()) // 30 + passos)


def _ativar(db, *contas) -> list[str]:
    """O autenticador cadastrado (a conta que exige o código e não cadastrou não tem sessão que valha)."""
    segredos = []
    for u in contas:
        duas_etapas.comecar_cadastro(u)
        u.totp_ativo_em = datetime.now(UTC)
        segredos.append(duas_etapas.cripto.decifrar(u.totp_segredo_cifrado))
    db.commit()
    return segredos


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_a_sessao_tem_numero_e_se_encerra(http, c, db):
    _ativar(db, c["gerente"], c["adm"])
    token, _ = criar_token_empresa(c["gerente"].id)
    r = http.get("/api/empresa/eu", headers={**_bearer(token), "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130"})
    assert r.status_code == 200
    s = db.query(SessaoGS).one()
    assert (s.gs_user_id, s.escopo) == (c["gerente"].id, "empresa") and s.aparelho
    # o adm lista e encerra: a próxima requisição desta sessão cai
    adm_token, _ = __import__("app.core.security", fromlist=["x"]).criar_token_painel(c["adm"].id)
    lista = http.get(f"/api/painel/acessos/sessoes?pessoa={c['gerente'].id}", headers=_bearer(adm_token)).json()
    assert [x["onde"] for x in lista] == ["oem-gs"]
    assert http.post(f"/api/painel/acessos/sessoes/{s.id}/encerrar?pessoa={c['gerente'].id}",
                     headers=_bearer(adm_token)).status_code == 204
    r = http.get("/api/empresa/eu", headers=_bearer(token))
    assert r.status_code == 401 and "encerrada" in r.json()["detail"]
    assert "sessão encerrada" in db.query(AcessoGS).filter_by(acao="acesso").one().motivo
    # "encerrar todas": derruba também a nunca usada e a de antes das sessões (sem número); a nova vale
    nunca_usada, _ = criar_token(c["dono"].id)
    from jose import jwt
    antiga = jwt.encode({"sub": str(c["dono"].id), "exp": datetime.now(UTC) + timedelta(days=1)},
                        get_settings().gs_jwt_secret, algorithm="HS256")
    assert http.get("/api/v1/auth/eu", headers=_bearer(antiga)).status_code == 200
    time.sleep(1.1)                                          # o `iat` é em segundos
    assert http.post(f"/api/painel/acessos/pessoas/{c['dono'].id}/encerrar-sessoes",
                     headers=_bearer(adm_token)).status_code == 200
    for t in (nunca_usada, antiga):
        assert http.get("/api/v1/auth/eu", headers=_bearer(t)).status_code == 401
    nova, _ = criar_token(c["dono"].id)
    assert http.get("/api/v1/auth/eu", headers=_bearer(nova)).status_code == 200
    # sair encerra a sessão no servidor
    assert http.post("/api/sessao/sair", headers=_bearer(nova)).status_code == 204
    assert http.get("/api/v1/auth/eu", headers=_bearer(nova)).status_code == 401


def test_duas_etapas_no_painel_do_cadastro_ao_codigo(http, c, db):
    r = http.post("/api/painel/entrar", json={"apelido": "gerente", "senha": SENHA})
    assert r.status_code == 200 and not r.json()["token"]
    d = r.json()["duas_etapas"]
    assert d["cadastrar"] and d["qr"].startswith("data:image/svg+xml") and d["otpauth"].startswith("otpauth://totp/")
    assert http.post("/api/painel/entrar/codigo", json={"desafio": d["desafio"], "codigo": "000000"}).status_code == 401
    r = http.post("/api/painel/entrar/codigo", json={"desafio": d["desafio"], "codigo": _codigo(d["segredo"])})
    assert r.status_code == 200 and r.json()["token"] and r.json()["escopo"] == "empresa"
    db.refresh(c["gerente"])
    assert duas_etapas.situacao(c["gerente"]) == "ativa"
    assert "ativada" in " ".join(a.motivo for a in db.query(AcessoGS).filter_by(acao="acesso"))
    # o mesmo código não vale duas vezes; o próximo login já não cadastra
    r = http.post("/api/painel/entrar", json={"apelido": "gerente", "senha": SENHA})
    d2 = r.json()["duas_etapas"]
    assert d2["cadastrar"] is False and d2["qr"] is None
    assert http.post("/api/painel/entrar/codigo", json={"desafio": d2["desafio"], "codigo": _codigo(d["segredo"])}
                     ).status_code == 401
    assert http.post("/api/painel/entrar/codigo",
                     json={"desafio": d2["desafio"], "codigo": _codigo(d["segredo"], 1)}).status_code == 200
    # o desafio de um destino não vale no outro, e não é sessão de portão nenhum
    assert http.post("/api/v1/auth/login/codigo", json={"desafio": d2["desafio"], "codigo": "123456"}).status_code == 401
    assert http.get("/api/empresa/eu", headers=_bearer(d2["desafio"])).status_code in (401, 403)


def test_duas_etapas_nas_outras_portas(http, c, db, monkeypatch):
    g = c["gerente"]
    duas_etapas.comecar_cadastro(g)
    segredo = duas_etapas.cripto.decifrar(g.totp_segredo_cifrado)
    g.totp_ativo_em = datetime.now(UTC)
    db.commit()
    # o dono entra direto; o gerente no portal pede o código
    assert http.post("/api/v1/auth/login", json={"apelido": "dono", "senha": SENHA}).json()["token"]
    r = http.post("/api/v1/auth/login", json={"apelido": "gerente", "senha": SENHA})
    assert not r.json()["token"] and r.json()["duas_etapas"]["cadastrar"] is False
    r = http.post("/api/v1/auth/login/codigo", json={"desafio": r.json()["duas_etapas"]["desafio"],
                                                     "codigo": _codigo(segredo)})
    assert r.json()["token"] and r.json()["usuario"]["apelido"] == "gerente"
    # a entrada única do gestao.solar
    volta = "https://termovision.gestao.solar/entrar.html"
    r = http.post("/api/sessao/termovision/com-senha", json={"apelido": "gerente", "senha": SENHA, "volta": volta})
    assert not r.json()["url"]
    r = http.post("/api/sessao/termovision/com-senha/codigo", json={
        "desafio": r.json()["duas_etapas"]["desafio"], "codigo": _codigo(segredo, 1), "volta": volta})
    assert r.status_code == 200 and r.json()["url"].startswith(volta + "#assercao=") and r.json()["entrada"]
    # a tela de senha do próprio sistema manda ao botão do GS
    r = http.post("/api/v1/auth/produtos/termovision/assercao", json={"apelido": "gerente", "senha": SENHA})
    assert r.status_code == 403 and "Entrar com o Gestão Solar" in r.json()["detail"]
    # a saída de emergência
    monkeypatch.setattr(get_settings(), "gs_2fa_desligada", True)
    assert http.post("/api/painel/entrar", json={"apelido": "gerente", "senha": SENHA}).json()["token"]


def test_subir_para_a_plataforma_pede_o_codigo_e_refazer(http, c, db):
    from app.models.pessoa import Pessoa
    adm, g = c["adm"], c["gerente"]
    p = Pessoa(nome="Renan")
    db.add(p)
    db.commit()
    adm.pessoa_id = g.pessoa_id = p.id
    db.commit()
    _ativar(db, g)
    token, _ = criar_token_empresa(g.id)
    r = http.post("/api/sessao/trocar", headers=_bearer(token), json={"apelido": "adm", "senha": SENHA})
    assert r.status_code == 403 and "cadastrou" in r.json()["detail"]
    duas_etapas.comecar_cadastro(adm)
    segredo = duas_etapas.cripto.decifrar(adm.totp_segredo_cifrado)
    adm.totp_ativo_em = datetime.now(UTC)
    db.commit()
    assert http.post("/api/sessao/trocar", headers=_bearer(token), json={"apelido": "adm", "senha": SENHA,
                                                                       "codigo": "111111"}).status_code == 401
    r = http.post("/api/sessao/trocar", headers=_bearer(token), json={"apelido": "adm", "senha": SENHA,
                                                                    "codigo": _codigo(segredo)})
    assert r.status_code == 200 and r.json()["escopo"] == "painel"
    # o gerente refaz a verificação de alguém da empresa: no próximo login cadastra de novo, e as sessões acabam
    tec = User(apelido="tec", nome="Tec", perfil=Perfil.TECNICO, empresa_id=c["a"].id, senha_hash=g.senha_hash)
    db.add(tec)
    db.commit()
    duas_etapas.comecar_cadastro(tec)
    tec.totp_ativo_em = datetime.now(UTC)
    db.commit()
    assert http.post(f"/api/empresa/usuarios/{tec.id}/refazer-duas-etapas", headers=_bearer(token)).status_code == 204
    db.refresh(tec)
    assert tec.totp_segredo_cifrado is None and tec.sessoes_desde is not None
    assert http.post(f"/api/empresa/usuarios/{adm.id}/refazer-duas-etapas", headers=_bearer(token)).status_code == 404


def test_o_conector_do_claude_pede_o_codigo(http, c, db):
    from app.api.v1 import mcp
    g = c["gerente"]
    g.bot_meuwatt = True
    duas_etapas.comecar_cadastro(g)
    segredo = duas_etapas.cripto.decifrar(g.totp_segredo_cifrado)
    g.totp_ativo_em = datetime.now(UTC)
    db.commit()
    mcp._pedidos["p1"] = {"desafio": "x" * 43, "redirect": "https://claude.ai/api/mcp/auth_callback", "state": "s",
                          "exp": time.time() + 60}
    r = http.post("/oauth/authorize", data={"pedido": "p1", "apelido": "gerente", "senha": SENHA, "acao": "autorizar"},
                  follow_redirects=False)
    assert r.status_code == 401 and "código do autenticador" in r.text
    r = http.post("/oauth/authorize", data={"pedido": "p1", "apelido": "gerente", "senha": SENHA, "acao": "autorizar",
                                            "codigo": _codigo(segredo)}, follow_redirects=False)
    assert r.status_code in (303, 403), r.text                # 403 se a conta não tem serviço: passou do código
    assert "código do autenticador" not in r.text


if __name__ == "__main__":
    pytest.main([__file__, "-q"])


# ------------------------------------------- a avaliação independente de 24/11/2026: um teste por achado


def test_o_desafio_e_a_sessao_de_sistema_nao_abrem_as_rotas_de_sessao(http, c, db):
    """O desafio da duas etapas (sai só com a senha) trocava a senha e lia os papéis sem o código; o `sessao_gs` de um
    sistema (vai em todo passe) também."""
    from app.core.security import criar_token_sistema
    g = c["gerente"]
    _ativar(db, g)
    for token in (duas_etapas.desafio(g, "painel"), criar_token_sistema(g.id, "meuplano")):
        assert http.post("/api/sessao/senha", headers=_bearer(token),
                         json={"senha_atual": SENHA, "senha_nova": "outra-senha-99"}).status_code == 401
        assert http.get("/api/sessao/papeis", headers=_bearer(token)).status_code == 401
        assert http.post("/api/sessao/trocar", headers=_bearer(token), json={"apelido": "dono"}).status_code == 401
    db.refresh(g)
    from app.core.security import conferir_senha
    assert conferir_senha(SENHA, g.senha_hash)                                   # a senha não mudou
    sessao, _ = criar_token_empresa(g.id)                                        # a sessão de verdade, sim
    assert http.get("/api/sessao/papeis", headers=_bearer(sessao)).status_code == 200


def test_trocar_para_a_conta_que_exige_o_codigo_pede_o_codigo(http, c, db):
    """Da sessão do dono (sem duas etapas) para o gerente da mesma pessoa: antes, sem nada."""
    from app.models.pessoa import Pessoa
    p = Pessoa(nome="Renan")
    db.add(p)
    db.commit()
    c["dono"].pessoa_id = c["gerente"].pessoa_id = p.id
    db.commit()
    dono, _ = criar_token(c["dono"].id)
    papeis = {x["apelido"]: x for x in http.get("/api/sessao/papeis", headers=_bearer(dono)).json()}
    assert (papeis["gerente"]["exige_senha"], papeis["gerente"]["exige_codigo"]) == (False, True)
    r = http.post("/api/sessao/trocar", headers=_bearer(dono), json={"apelido": "gerente"})
    assert r.status_code == 403 and "cadastrou" in r.json()["detail"]           # sem o autenticador, não troca
    (segredo,) = _ativar(db, c["gerente"])
    assert http.post("/api/sessao/trocar", headers=_bearer(dono), json={"apelido": "gerente"}).status_code == 401
    r = http.post("/api/sessao/trocar", headers=_bearer(dono), json={"apelido": "gerente", "codigo": _codigo(segredo)})
    assert r.status_code == 200 and r.json()["escopo"] == "empresa"


def test_sem_o_autenticador_cadastrado_nenhuma_sessao_vale(http, c, db):
    """A conta que exige o código e não cadastrou tem só sessões de antes da exigência: nem valem, nem se renovam (a
    renovação do app e a da entrada do gestao.solar pulavam o código para sempre)."""
    from app.core.security import criar_token_entrada
    g = c["gerente"]
    empresa, _ = criar_token_empresa(g.id)
    app_, _ = criar_token(g.id)
    entrada, _ = criar_token_entrada(g.id)
    r = http.get("/api/empresa/eu", headers=_bearer(empresa))
    assert r.status_code == 401 and "cadastrar o autenticador" in r.json()["detail"]
    assert http.post("/api/v1/auth/renovar", headers=_bearer(app_)).status_code == 401
    assert http.post("/api/sessao/termovision", headers=_bearer(entrada),
                     json={"volta": "https://termovision.gestao.solar/"}).status_code == 401
    _ativar(db, g)
    assert http.get("/api/empresa/eu", headers=_bearer(empresa)).status_code == 200


def test_o_codigo_tem_limite_por_conta_de_qualquer_lugar(http, c, db):
    g = c["gerente"]
    (segredo,) = _ativar(db, g)
    for i in range(duas_etapas.ERROS_POR_CONTA):                                 # cada erro de um IP diferente
        desafio = duas_etapas.desafio(g, "painel")
        r = http.post("/api/painel/entrar/codigo", headers={"X-Forwarded-For": f"203.0.113.{i}"},
                      json={"desafio": desafio, "codigo": "000000"})
        assert r.status_code == 401
    r = http.post("/api/painel/entrar/codigo", headers={"X-Forwarded-For": "198.51.100.7"},
                  json={"desafio": duas_etapas.desafio(g, "painel"), "codigo": _codigo(segredo)})
    assert r.status_code == 429                                                  # nem o certo, até a janela passar
    assert db.query(AcessoGS).filter_by(acao="bloqueado", gs_user_id=g.id).count() == 1


def test_o_conector_do_claude_cai_com_encerrar_todas(http, c, db):
    from app.api.v1 import mcp
    from app.models.mcp import TokenMcp
    from app.services import sessoes
    d = c["dono"]
    db.add(TokenMcp(user_id=d.id, token_hash=mcp._hash("gs_mcp_teste"), criado_em=datetime.now(UTC) - timedelta(days=1),
                    expira_em=datetime.now(UTC) + timedelta(days=89)))
    db.commit()

    class Pedido:
        headers = {"Authorization": "Bearer gs_mcp_teste"}
        base_url = "https://api.gestao.solar/"
        url = "https://api.gestao.solar/mcp"
    assert mcp._quem(db, Pedido()) .__class__ is User
    sessoes.encerrar_todas(db, d, por=None, motivo="a senha foi roubada")
    db.commit()
    assert mcp._quem(db, Pedido()).__class__ is not User                        # a ligação do Claude caiu junto
    # e a do gerente que exige o código e não cadastrou o autenticador (ligada só com a senha, antes da exigência)
    g = c["gerente"]
    db.add(TokenMcp(user_id=g.id, token_hash=mcp._hash("gs_mcp_ger"), expira_em=datetime.now(UTC) + timedelta(days=89)))
    db.commit()
    Pedido.headers = {"Authorization": "Bearer gs_mcp_ger"}
    assert mcp._quem(db, Pedido()).__class__ is not User
    _ativar(db, g)
    assert mcp._quem(db, Pedido()).__class__ is User
