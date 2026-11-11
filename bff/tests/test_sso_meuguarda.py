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


def _entrar(db, token, volta="https://meuguarda.gestao.solar/painel?x=1", produto="meuguarda"):
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return sessao.entrar_no_produto(produto, sessao.EntrarIn(volta=volta), cred, db).url


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
        # quem o gerente não liberou fica fora do meuGuarda; a plataforma sempre entra
        assert c["meuguarda"] is (portao == "painel")
        # a do meuGuarda não vale no meuWatt (nem a deles aqui)
        with pytest.raises(Exception):
            jwt.decode(frag, publica, algorithms=["RS256"], audience="meuwatt")


def test_o_eu_dos_portoes_diz_se_a_pessoa_entra_no_meuguarda(db):
    from app.api.v1 import auth, empresa, tecnico

    gerente = _conta(db, "gerente.tres", Perfil.GESTOR_EMPRESA)
    assert empresa.eu(db, gerente).meuguarda is False
    gerente.meuguarda_liberado = True
    assert empresa.eu(db, gerente).meuguarda is True
    tec = _conta(db, "tecnico.tres", Perfil.TECNICO)
    assert tecnico.eu(db, tec).meuguarda is False
    dono = _conta(db, "dono.tres", Perfil.CLIENTE)
    dono.meuguarda_liberado = True
    assert auth.eu(db, dono).meuguarda is True


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



def test_o_termovision_entra_pelo_gestao_solar_igual_ao_meuguarda(db, publica):
    """Pedido do dono (11/11/2026): "login do termovision pelo GESTÃO SOLAR igual tem no meuguarda"."""
    from app.models.user import VinculoProduto

    tecnico = _conta(db, "tecnico.tv", Perfil.TECNICO)
    db.add(VinculoProduto(gs_user_id=tecnico.id, produto="meuplano", usuario_remoto_id="88"))
    db.commit()
    url = _entrar(db, security.criar_token_tecnico(tecnico.id)[0], "https://termovision.gestao.solar/entrar.html",
                  "termovision")
    volta, _, frag = url.partition("#assercao=")
    assert volta == "https://termovision.gestao.solar/entrar.html"
    c = jwt.decode(frag, publica, algorithms=["RS256"], audience="termovision", issuer="gestao-solar")
    # o id da pessoa no meuPlano: é como o TermoVision reconhecia quem já entrava; e o acesso que o gerente liberou
    assert (c["apelido"], c["portao"], c["meuplano_id"], c["termovision"]) == ("tecnico.tv", "tecnico", 88, False)
    tecnico.termovision_liberado = True
    db.commit()
    c = jwt.get_unverified_claims(_entrar(db, security.criar_token_tecnico(tecnico.id)[0],
                                          "https://app.termovision.tech/", "termovision").partition("#assercao=")[2])
    assert c["termovision"] is True and "meuguarda" not in c
    # a asserção de um produto não vale no outro; a volta de um não serve ao outro
    with pytest.raises(Exception):
        jwt.decode(frag, publica, algorithms=["RS256"], audience="meuguarda")
    for produto, ruim in (("termovision", "https://meuguarda.gestao.solar/"), ("meuguarda", "https://termovision.gestao.solar/")):
        with pytest.raises(HTTPException) as e:
            _entrar(db, security.criar_token_tecnico(tecnico.id)[0], ruim, produto)
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:                # produto que não existe
        _entrar(db, security.criar_token_tecnico(tecnico.id)[0], "https://termovision.gestao.solar/", "outro")
    assert e.value.status_code == 404


def test_a_rota_de_cada_produto_nao_engole_as_rotas_fixas_da_sessao():
    from starlette.routing import Match

    from app.main import app

    def primeira(caminho):
        escopo = {"type": "http", "path": caminho, "method": "POST"}
        return next(r for r in app.routes if r.matches(escopo)[0] == Match.FULL).endpoint.__name__

    assert [primeira(f"/api/sessao/{x}") for x in ("trocar", "senha", "empresa", "meuguarda", "termovision")] == \
        ["trocar", "trocar_a_propria_senha", "trocar_de_empresa", "entrar_no_produto", "entrar_no_produto"]


def test_o_apelido_e_a_senha_do_gs_valem_direto_na_tela_do_termovision(db, publica):
    """O TermoVision pediu (11/11/2026): a tela de entrar dele confere o apelido e a senha do GS, servidor a servidor,
    e recebe a MESMA asserção do redirecionamento."""
    from app.api.v1 import auth
    from app.core.security import gerar_hash_senha

    gerente = _conta(db, "gerente.tv", Perfil.GESTOR_EMPRESA)
    gerente.senha_hash, gerente.termovision_liberado = gerar_hash_senha("senha-forte-1"), True
    db.commit()
    r = auth.assercao_para_produto("termovision", auth.AssercaoIn(apelido="gerente.tv", senha="senha-forte-1"), db)
    c = jwt.decode(r.assertion, publica, algorithms=["RS256"], audience="termovision", issuer="gestao-solar")
    assert (c["apelido"], c["portao"], c["termovision"], c["empresa_id"]) == ("gerente.tv", "empresa", True,
                                                                               gerente.empresa_id)
    with pytest.raises(HTTPException) as e:
        auth.assercao_para_produto("termovision", auth.AssercaoIn(apelido="gerente.tv", senha="errada"), db)
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:                # produto que não existe: antes de olhar a senha
        auth.assercao_para_produto("outro", auth.AssercaoIn(apelido="gerente.tv", senha="errada"), db)
    assert e.value.status_code == 404
    db.get(Empresa, gerente.empresa_id).ativa = False      # empresa desligada não entra, como nos portões
    db.commit()
    with pytest.raises(HTTPException) as e:
        auth.assercao_para_produto("termovision", auth.AssercaoIn(apelido="gerente.tv", senha="senha-forte-1"), db)
    assert e.value.status_code == 403


def test_os_botoes_dos_portoes_so_mostram_o_que_o_gerente_liberou(db):
    tecnico = _conta(db, "tecnico.botoes", Perfil.TECNICO)
    tecnico.meuguarda_liberado = True
    db.commit()
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=security.criar_token_tecnico(tecnico.id)[0])
    assert [(p.produto, p.url) for p in sessao.produtos_da_sessao(cred, db)] == [
        ("meuguarda", "https://meuguarda.gestao.solar/")]
    tecnico.termovision_liberado = True
    db.commit()
    assert [p.url for p in sessao.produtos_da_sessao(cred, db)][-1] == "https://termovision.gestao.solar/entrar.html"


def test_a_entrada_unica_aceita_qualquer_conta_com_a_senha_do_gs(db, publica):
    """gestao.solar/entrar/<produto> sem sessão: equipe, dono de usina ou plataforma, com o apelido e a senha do GS."""
    from app.core.security import gerar_hash_senha

    contas = [(_conta(db, "dono.unico", Perfil.CLIENTE), "cliente"), (_conta(db, "tecnico.unico", Perfil.TECNICO), "tecnico"),
              (_conta(db, "adm.unico", Perfil.ADMINISTRADOR, empresa=False), "painel")]
    for conta, _ in contas:
        conta.senha_hash = gerar_hash_senha("senha-forte-1")
    db.commit()
    for conta, portao in contas:
        url = sessao.entrar_no_produto_com_senha("termovision", sessao.EntrarComSenhaIn(
            apelido=conta.apelido, senha="senha-forte-1", volta="https://termovision.gestao.solar/entrar.html"), db).url
        c = jwt.decode(url.partition("#assercao=")[2], publica, algorithms=["RS256"], audience="termovision")
        assert (c["apelido"], c["portao"]) == (conta.apelido, portao)
    with pytest.raises(HTTPException) as e:
        sessao.entrar_no_produto_com_senha("termovision", sessao.EntrarComSenhaIn(
            apelido="dono.unico", senha="errada", volta="https://termovision.gestao.solar/"), db)
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:               # a volta é conferida ANTES da senha
        sessao.entrar_no_produto_com_senha("termovision", sessao.EntrarComSenhaIn(
            apelido="dono.unico", senha="senha-forte-1", volta="https://evil.com/"), db)
    assert e.value.status_code == 400
