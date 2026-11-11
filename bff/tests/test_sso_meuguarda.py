""""Entrar com o Gestão Solar" no meuGuarda (pedido do dono, 11/11/2026: "eu clico, o Gestão Solar autentica e boa").

A página `/entrar/meuguarda?volta=` dos três portões chama `POST /api/sessao/meuguarda` com a sessão daquele portão e
manda o navegador à `volta` com a asserção no fragmento. A `volta` só pode ser do meuGuarda (senão, redirecionamento
aberto), e a sessão passa pela guarda do próprio portão.
"""
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from app.api.v1 import sessao
from app.core import security
from app.core.config import get_settings
from app.models.empresa import Empresa
from app.models.user import Perfil, User


@pytest.fixture
def publica(monkeypatch):
    par = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(get_settings(), "gs_sso_private_key", par.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    return par.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def _conta(db, apelido, perfil, empresa=True):
    emp = None
    if empresa:
        emp = db.query(Empresa).filter_by(nome="Splendor").one_or_none() or Empresa(nome="Splendor")
        db.add(emp)
        db.commit()
    u = User(apelido=apelido, nome=apelido.title(), perfil=perfil, empresa_id=emp and emp.id)
    db.add(u)
    db.commit()
    return u


def _entrar(db, token, volta="https://meuguarda.gestao.solar/painel?x=1"):
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return sessao.entrar_no_meuguarda(sessao.MeuGuardaIn(volta=volta), cred, db).url


def test_cada_portao_leva_o_apelido_o_perfil_o_portao_e_a_empresa(db, publica):
    casos = [(_conta(db, "dono.um", Perfil.CLIENTE), security.criar_token, "cliente"),
             (_conta(db, "gerente.um", Perfil.GESTOR_EMPRESA), security.criar_token_empresa, "empresa"),
             (_conta(db, "tecnico.um", Perfil.TECNICO), security.criar_token_tecnico, "tecnico"),
             (_conta(db, "renan.gestao", Perfil.ADMINISTRADOR, empresa=False), security.criar_token_painel, "painel")]
    for conta, emitir, portao in casos:
        url = _entrar(db, emitir(conta.id)[0])
        volta, _, frag = url.partition("#assercao=")
        assert volta == "https://meuguarda.gestao.solar/painel?x=1"
        c = jwt.decode(frag, publica, algorithms=["RS256"], audience="meuguarda", issuer="gestao-solar")
        assert (c["sub"], c["apelido"], c["perfil"], c["portao"], c["empresa_id"]) == (
            str(conta.id), conta.apelido, conta.perfil.value, portao, conta.empresa_id)
        assert c["exp"] - c["iat"] == 120 and c["jti"]
        # a do meuGuarda não vale no meuWatt (nem a deles aqui)
        with pytest.raises(Exception):
            jwt.decode(frag, publica, algorithms=["RS256"], audience="meuwatt")


def test_a_volta_so_vai_para_o_meuguarda(db, publica):
    token = security.criar_token(_conta(db, "dono.dois", Perfil.CLIENTE).id)[0]
    assert _entrar(db, token, "https://meuguarda.177.153.20.214.sslip.io").startswith(
        "https://meuguarda.177.153.20.214.sslip.io/#assercao=")
    for ruim in ("https://evil.com/", "http://meuguarda.gestao.solar/", "https://meuguarda.gestao.solar.evil.com/",
                 "https://evil@meuguarda.gestao.solar/", "https://meuguarda.gestao.solar:8443/",
                 "//meuguarda.gestao.solar/", "javascript:alert(1)", "https://meuguarda.gestao.solar\\@evil.com/", ""):
        with pytest.raises(HTTPException) as e:
            _entrar(db, token, ruim)
        assert e.value.status_code == 400, ruim


def test_a_guarda_do_portao_vale(db, publica):
    # o técnico com um token de EMPRESA (escopo que não é o dele) é recusado como no próprio portão
    tecnico = _conta(db, "tecnico.dois", Perfil.TECNICO)
    with pytest.raises(HTTPException) as e:
        _entrar(db, security.criar_token_empresa(tecnico.id)[0])
    assert e.value.status_code == 403
    # empresa desligada: nada de asserção
    gerente = _conta(db, "gerente.dois", Perfil.GESTOR_EMPRESA)
    db.get(Empresa, gerente.empresa_id).ativa = False
    db.commit()
    with pytest.raises(HTTPException):
        _entrar(db, security.criar_token_empresa(gerente.id)[0])
    with pytest.raises(HTTPException) as e:
        _entrar(db, "nao-e-token")
    assert e.value.status_code == 401
