"""Login único pelo GS (Plano Casa GS, 24/11/2026): o login ou o e-mail, o registro de cada acesso e o passe v2 dos
quatro sistemas."""
import pytest
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import func, select

from app.api.v1.auth import LoginIn, login
from app.core.security import gerar_hash_senha
from app.models.acesso import AcessoGS
from app.models.user import Perfil, User, VinculoProduto
from app.services import acessos


def _conta(db, apelido, email, senha, perfil=Perfil.CLIENTE, ativo=True):
    u = User(apelido=apelido, email=email, nome=apelido, perfil=perfil, ativo=ativo,
             senha_hash=gerar_hash_senha(senha))
    db.add(u)
    db.commit()
    return u


def test_entra_pelo_login_ou_pelo_email_e_a_senha_escolhe_entre_duas_contas(db):
    gestora = _conta(db, "ana.gestora", "ana@x.com", "senha-gestora")
    dona = _conta(db, "ana.dona", "Ana@X.com", "senha-dona")
    assert acessos.autenticar(db, "ANA.GESTORA ", "senha-gestora")[0] is gestora
    assert acessos.autenticar(db, "ana@x.com", "senha-gestora")[0] is gestora
    assert acessos.autenticar(db, "ANA@x.com", "senha-dona")[0] is dona         # o e-mail sem caixa
    assert acessos.autenticar(db, "ana@x.com", "errada") == (None, "senha errada")
    dona.senha_hash = gestora.senha_hash                                         # a mesma senha nas duas
    db.commit()
    u, motivo = acessos.autenticar(db, "ana@x.com", "senha-gestora")
    assert u is None and motivo == acessos.AMBIGUO and "entre pelo login" in acessos.frase(motivo)
    assert acessos.frase("senha errada") == acessos.RECUSA                      # só o caso provado tem frase própria
    _conta(db, "desligado", "d@x.com", "senha-1234", ativo=False)
    assert acessos.autenticar(db, "desligado", "senha-1234") == (None, "conta desligada")
    assert acessos.autenticar(db, "d@x.com", "senha-1234") == (None, "conta desligada")
    assert acessos.autenticar(db, "ninguem", "x") == (None, "login de conta nenhuma")


def test_cada_entrada_e_cada_recusa_ficam_registradas(db):
    u = _conta(db, "dono.um", "dono@x.com", "senha-1234")
    with pytest.raises(HTTPException) as e:
        login(LoginIn(apelido="dono.um", senha="chute"), db=db)
    assert e.value.detail == "Login ou senha inválidos"
    login(LoginIn(apelido="dono@x.com", senha="senha-1234"), db=db)
    linhas = list(db.scalars(select(AcessoGS).order_by(AcessoGS.id)))
    assert [(x.acao, x.ok, x.gs_user_id, x.motivo) for x in linhas] == [
        ("recusado", False, u.id, "senha errada"), ("entrou", True, u.id, "aplicativo ou portal")]
    assert linhas[1].login == "dono@x.com"                                       # o que foi digitado; nunca a senha
    assert all("senha-1234" not in (x.login + x.motivo) for x in linhas)


def test_o_passe_v2_leva_login_perfil_e_as_usinas_com_o_numero_de_cada_sistema(db, usinas, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode()
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "gs_sso_private_key", pem)
    from app.api.v1 import mapa
    from app.api.v1.sessao import _passe

    u = _conta(db, "dono.dois", "d2@x.com", "senha-1234")
    monkeypatch.setattr(mapa, "usinas_do_mapa", lambda db_, user: usinas)
    ler = lambda t: jwt.get_unverified_claims(t)                                  # noqa: E731
    mw = ler(_passe(db, u, "meuwatt", "cliente", None))
    assert (mw["aud"], mw["v"], mw["apelido"], mw["perfil"]) == ("meuwatt", 2, "dono.dois", "cliente")
    assert [x["id"] for x in mw["usinas"]] == ["porto-ferreira", "ribeirao-bonito"]
    assert [x["id"] for x in ler(_passe(db, u, "meuplano", "cliente", None))["usinas"]] == [1, 2]
    tv = ler(_passe(db, u, "termovision", "cliente", None))
    assert tv["aud"] == "termovision" and "termovision" in tv and [x["id"] for x in tv["usinas"]] == [
        x.id for x in usinas]


def test_a_lista_de_sistemas_da_sessao_tem_os_quatro_quando_liberados(db):
    from app.models.user import User as U
    u = _conta(db, "gerente.x", "g@x.com", "senha-1234", perfil=Perfil.CLIENTE)
    db.add(VinculoProduto(gs_user_id=u.id, produto="meuplano", usuario_remoto_id="7"))
    db.commit()
    db.refresh(u)
    assert u.entra_no_meuplano and not u.entra_no_meuwatt
    assert isinstance(db.get(U, u.id), U)


def test_senha_digitada_no_campo_do_login_nao_fica_no_registro_e_o_limite_barra(db):
    for t in (acessos._erros, acessos._por_ip, acessos._avisados):
        t.clear()
    _conta(db, "dono.tres", "d3@x.com", "senha-1234")
    with pytest.raises(HTTPException):
        login(LoginIn(apelido="MinhaSenha!9", senha="x"), db=db)                 # a senha no campo errado
    linha = db.scalars(select(AcessoGS).order_by(AcessoGS.id.desc())).first()
    import hashlib
    assert linha.login.startswith("? ") and "minhasenha" not in linha.login and linha.gs_user_id is None
    assert hashlib.sha256(b"minhasenha!9").hexdigest()[:12] not in linha.login     # nem reversível por lista
    for _ in range(10):
        with pytest.raises(HTTPException) as e:
            login(LoginIn(apelido="dono.tres", senha="chute"), db=db)
        assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:                                       # depois de 10: barrado, mesmo certa
        login(LoginIn(apelido="dono.tres", senha="senha-1234"), db=db)
    assert e.value.status_code == 429 and e.value.detail == acessos.BARRADO
    barrados = [x for x in db.scalars(select(AcessoGS)) if x.motivo.startswith("bloqueado")]
    login_ok = pytest.raises(HTTPException)
    with login_ok:
        login(LoginIn(apelido="dono.tres", senha="senha-1234"), db=db)
    assert len(barrados) == 1 and len([x for x in db.scalars(select(AcessoGS)) if x.motivo.startswith("bloqueado")]) == 1
    from types import SimpleNamespace
    outro_lugar = SimpleNamespace(headers={"x-forwarded-for": "200.1.1.1"}, client=None)
    assert login(LoginIn(apelido="dono.tres", senha="senha-1234"), db=db, request=outro_lugar).token  # não trancou
    for t in (acessos._erros, acessos._por_ip, acessos._avisados):
        t.clear()


def test_usinas_do_passe_so_da_empresa_da_sessao_e_a_plataforma_ve_todas(db, usinas, monkeypatch):
    from app.api.v1 import mapa
    from app.services import login_externo

    usinas[0].empresa_id, usinas[1].empresa_id = 1, 2
    g = _conta(db, "gerente.duas", "g2@x.com", "senha-1234", perfil=Perfil.GESTOR_EMPRESA)
    monkeypatch.setattr(mapa, "usinas_do_mapa", lambda db_, user: usinas)
    assert [x["id"] for x in login_externo.extras_v2(db, g, "meuwatt", 1)["usinas"]] == ["porto-ferreira"]
    adm = _conta(db, "adm.x", "a@x.com", "senha-1234", perfil=Perfil.ADMINISTRADOR)
    e = login_externo.extras_v2(db, adm, "meuwatt")
    assert e["todas_as_usinas"] is True and "usinas" not in e
    monkeypatch.setattr(login_externo, "TETO_USINAS", 10)                         # grande demais: diz que ficou fora
    e = login_externo.extras_v2(db, g, "meuwatt", 1)
    assert e.get("usinas_fora") is True and "usinas" not in e
    assert login_externo.extras_v2(db, g, "meuwatt", 1, teto=False)["usinas"]      # a renovação: a lista inteira


def test_entrada_unica_dos_quatro_e_sem_endereco_morto():
    from app.api.v1.sessao import VOLTAS, _volta
    assert sorted(VOLTAS) == ["helper", "meuguarda", "meuplano", "meuwatt", "termovision"]
    assert _volta("meuplano", "https://app.meuplano.solar/os/1") == "https://app.meuplano.solar/os/1"
    for ruim in ("https://meuplano.meuwatt.com.br/", "http://app.meuplano.solar/", "https://app.meuwatt.com.br.x.io/"):
        with pytest.raises(HTTPException):
            _volta("meuplano" if "meuplano" in ruim else "meuwatt", ruim)


def _de(ip, usuario_ip=None, sistema=None, chave=None):
    from types import SimpleNamespace
    h = {"x-forwarded-for": ip}
    if usuario_ip:
        h["x-usuario-ip"] = usuario_ip
    if sistema:
        h["x-sistema"], h["x-chave-interna"] = sistema, chave or ""
    return SimpleNamespace(headers=h, client=None)


def _limpar_limites():
    for t in (acessos._erros, acessos._por_ip, acessos._avisados):
        t.clear()


def test_ip_de_fora_e_barrado_em_todas_as_portas_e_a_conta_real_sempre_entra_no_registro(db):
    from app.api.v1.auth import AssercaoIn, assercao_para_produto
    _limpar_limites()
    real = _conta(db, "dono.quatro", "d4@x.com", "senha-1234")
    fora = _de("200.9.9.9")
    for i in range(30):
        with pytest.raises(HTTPException):
            login(LoginIn(apelido=f"lixo{i}", senha="x"), db=db, request=fora)
    for porta in (lambda: login(LoginIn(apelido="dono.quatro", senha="senha-1234"), db=db, request=fora),
                  lambda: assercao_para_produto("meuplano", AssercaoIn(apelido="dono.quatro", senha="senha-1234"),
                                                db=db, request=fora)):
        with pytest.raises(HTTPException) as e:                             # barrado também na rota dos servidores
            porta()
        assert e.value.status_code == 429
    linhas = list(db.scalars(select(AcessoGS)))
    assert sum(1 for x in linhas if x.login.startswith("? ")) == 30
    assert sum(1 for x in linhas if x.motivo.startswith("bloqueado: 30")) == 1
    _limpar_limites()


def test_repasse_pelo_servidor_so_e_confiado_com_a_chave_do_sistema(db, monkeypatch):
    from app.core.config import get_settings
    _limpar_limites()
    monkeypatch.setattr(get_settings(), "meuguarda_chave_interna", "chave-do-meuguarda-de-teste")
    monkeypatch.setattr(get_settings(), "teto_ip_casa_sem_chave", 40)
    real = _conta(db, "dono.cinco", "d5@x.com", "senha-1234")
    sem_chave = _de("177.153.20.214")                                         # o endereço da KingHost, sem chave
    for i in range(39):                                                      # 39 erros de estranhos: ainda passa
        with pytest.raises(HTTPException) as e:
            login(LoginIn(apelido=f"lixo{i}", senha="x"), db=db, request=sem_chave)
        assert e.value.status_code == 401
    assert login(LoginIn(apelido="dono.cinco", senha="senha-1234"), db=db, request=sem_chave).token
    with pytest.raises(HTTPException):
        login(LoginIn(apelido="lixo-final", senha="x"), db=db, request=sem_chave)
    with pytest.raises(HTTPException) as e:                                   # passou do teto da casa: barra
        login(LoginIn(apelido="dono.cinco", senha="senha-1234"), db=db, request=sem_chave)
    assert e.value.status_code == 429
    _limpar_limites()
    chave = "chave-do-meuguarda-de-teste"
    pessoa = _de("10.0.1.23", usuario_ip="200.7.7.7", sistema="meuguarda", chave=chave)
    assert acessos._ip(pessoa) == "200.7.7.7"                                 # com a chave, o IP da pessoa vale
    assert acessos._ip(_de("10.0.1.23", usuario_ip="200.7.7.7", sistema="meuguarda", chave="errada")) == "10.0.1.23"
    assert acessos._ip(_de("10.0.1.23", usuario_ip="200.7.7.7")) == "10.0.1.23"   # sem chave: ignorado
    for i in range(30):
        with pytest.raises(HTTPException):
            login(LoginIn(apelido=f"lixo{i}", senha="x"), db=db, request=pessoa)
    with pytest.raises(HTTPException) as e:                                    # o limite vale para o IP da pessoa
        login(LoginIn(apelido="dono.cinco", senha="senha-1234"), db=db, request=pessoa)
    assert e.value.status_code == 429
    outra_pessoa = _de("10.0.1.23", usuario_ip="200.8.8.8", sistema="meuguarda", chave=chave)
    assert login(LoginIn(apelido="dono.cinco", senha="senha-1234"), db=db, request=outra_pessoa).token
    linhas = [x for x in db.scalars(select(AcessoGS)) if x.ip == "200.7.7.7"]
    assert linhas and all(x.ip == "200.7.7.7" for x in linhas)                 # o registro com o IP da pessoa
    assert acessos._ip(_de("1.2.3.4, 200.1.1.1")) == "200.1.1.1"               # o último é o do proxy
    _limpar_limites()


def test_troca_de_papel_so_registra_a_senha_errada(db):
    from app.api.v1 import sessao as rotas
    from app.models.pessoa import Pessoa
    _limpar_limites()
    p = Pessoa(nome="Ana")
    db.add(p)
    db.commit()
    dona = _conta(db, "ana.d", "a1@x.com", "senha-1234")
    adm = _conta(db, "ana.adm", "a2@x.com", "senha-adm-1", perfil=Perfil.ADMINISTRADOR)
    dona.pessoa_id = adm.pessoa_id = p.id
    db.commit()
    antes = db.scalar(select(func.count()).select_from(AcessoGS))
    for alvo in ("nao.existe1", "nao.existe2"):
        with pytest.raises(HTTPException) as e:
            rotas.trocar(rotas.TrocaIn(apelido=alvo, senha=None), db=db, usuario=dona, request=_de("1.2.3.4"))
        assert e.value.status_code == 404
    assert db.scalar(select(func.count()).select_from(AcessoGS)) == antes        # sondar conta não suja o registro
    with pytest.raises(HTTPException) as e:
        rotas.trocar(rotas.TrocaIn(apelido="ana.adm", senha="errada"), db=db, usuario=dona, request=_de("1.2.3.4"))
    assert e.value.status_code == 401
    assert db.scalar(select(func.count()).select_from(AcessoGS)) == antes + 1
    _limpar_limites()


def test_transicao_chave_com_acento_e_ip_inventado(db, monkeypatch):
    from app.core.config import get_settings
    _limpar_limites()
    chave = "chave-do-meuguarda-de-teste"
    monkeypatch.setattr(get_settings(), "meuguarda_chave_interna", chave)
    real = _conta(db, "dono.seis", "d6@x.com", "senha-1234")
    casa = _de("10.0.1.23")                                                   # sem chave, na transição (teto 0)
    for i in range(60):
        with pytest.raises(HTTPException) as e:
            login(LoginIn(apelido=f"lixo{i}", senha="x"), db=db, request=casa)
        assert e.value.status_code == 401                                     # nunca 429 por IP: ninguém é trancado
    assert login(LoginIn(apelido="dono.seis", senha="senha-1234"), db=db, request=casa).token
    acento = _de("10.0.1.23", usuario_ip="200.1.1.1", sistema="meuguarda", chave="é")
    assert acessos.repasse(acento) is None                                    # não derruba: chave inválida
    antes = db.scalar(select(func.count()).select_from(AcessoGS))
    assert login(LoginIn(apelido="dono.seis", senha="senha-1234"), db=db, request=acento).token
    assert db.scalar(select(func.count()).select_from(AcessoGS)) == antes + 1      # e o registro entrou
    sem_ip = _de("10.0.1.23", sistema="meuguarda", chave=chave)
    with pytest.raises(HTTPException) as e:                                    # com chave e sem o IP: recusado
        login(LoginIn(apelido="dono.seis", senha="senha-1234"), db=db, request=sem_ip)
    assert e.value.status_code == 400
    _limpar_limites()
    de_casa = _de("10.0.1.23", usuario_ip="200.0.0.77", sistema="meuguarda", chave=chave)
    assert login(LoginIn(apelido="dono.seis", senha="senha-1234"), db=db, request=de_casa).token   # o lugar de sempre
    for i in range(30):                                                       # IP inventado a cada tentativa
        with pytest.raises(HTTPException) as e:
            login(LoginIn(apelido="dono.seis", senha="chute"), db=db,
                  request=_de("10.0.1.23", usuario_ip=f"200.0.0.{i + 1}", sistema="meuguarda", chave=chave))
        assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:                                    # o total do login pelo sistema: teto
        login(LoginIn(apelido="dono.seis", senha="senha-1234"), db=db,
              request=_de("10.0.1.23", usuario_ip="200.0.0.99", sistema="meuguarda", chave=chave))
    assert e.value.status_code == 429 and "gestao.solar" in e.value.detail
    assert login(LoginIn(apelido="dono.seis", senha="senha-1234"), db=db, request=de_casa).token   # de casa: entra
    _limpar_limites()
