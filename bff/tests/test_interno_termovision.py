"""O TermoVision e as usinas do GS (Plano Casa GS, 24/11/2026), pela porta HTTP de verdade: a chave do TermoVision não
basta (a pessoa tem de ter entrado no TermoVision pelo GS há pouco, ser da O&M e da empresa do passe, ativa), as
referências de cada sistema, o vínculo do mapa ("Enviar ao GS") sem corrida nem vazamento do nome de outra empresa, e
a página de entrar que confere a volta ao abrir."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import interno_termovision as rota
from app.api.v1.sessao import conferir_volta
from app.core.config import get_settings
from app.core.db import get_db
from app.main import app
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa, MembroDaEmpresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User

CHAVE = "chave-do-tv-de-teste"


@pytest.fixture
def db():
    """O banco em memória com UMA conexão para todas as threads: as rotas daqui gravam e releem na mesma requisição,
    e a thread do TestClient cairia num banco vazio depois do commit."""
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
    monkeypatch.setattr(get_settings(), "termovision_chave_interna", CHAVE)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cenario(db):
    a, b, c = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M"), Empresa(nome="Desligada O&M", ativa=False)
    db.add_all([a, b, c])
    db.commit()
    ib = PlantLink(nome="Ibitinga", empresa_id=a.id, mw_plant_slug="ibitinga", mp_usina_id=7, cidade="Ibitinga", uf="SP")
    of = PlantLink(nome="Ouro Fino", empresa_id=a.id, mw_plant_slug="ouro-fino")
    de_b = PlantLink(nome="Usina Secreta B", empresa_id=b.id)
    de_c = PlantLink(nome="Usina da Desligada", empresa_id=c.id)
    gerente = User(apelido="gerente.a", nome="G", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id,
                   termovision_liberado=True)
    dono = User(apelido="dono.a", nome="D", perfil=Perfil.CLIENTE, empresa_id=a.id, termovision_liberado=True)
    adm = User(apelido="adm.p", nome="P", perfil=Perfil.ADMINISTRADOR)
    sem_tv = User(apelido="tec.sem.tv", nome="T", perfil=Perfil.TECNICO, empresa_id=a.id)
    sumido = User(apelido="tec.sumido", nome="S", perfil=Perfil.TECNICO, empresa_id=a.id, termovision_liberado=True)
    gerente_b = User(apelido="gerente.b", nome="GB", perfil=Perfil.GESTOR_EMPRESA, empresa_id=b.id,
                     termovision_liberado=True)
    db.add_all([ib, of, de_b, de_c, gerente, dono, adm, sem_tv, sumido, gerente_b])
    db.commit()
    db.add(MembroDaEmpresa(empresa_id=c.id, user_id=gerente.id))              # também é da empresa desligada
    agora = datetime.now(UTC)
    so_bot = User(apelido="tec.so.bot", nome="B", perfil=Perfil.TECNICO, empresa_id=a.id, termovision_liberado=True)
    db.add(so_bot)
    db.commit()
    for u in (gerente, dono, adm, sem_tv, gerente_b):                         # entraram no TermoVision pelo GS há pouco
        db.add(AcessoGS(gs_user_id=u.id, login=u.apelido, acao="passe", sistema="termovision", ok=True,
                        ip="200.1.1.1", em=agora - timedelta(minutes=5)))
    db.add(AcessoGS(gs_user_id=sumido.id, login="tec.sumido", acao="passe", sistema="termovision", ok=True,
                    ip="200.1.1.1", em=agora - timedelta(hours=13)))          # há mais de 12 h
    db.add(AcessoGS(gs_user_id=so_bot.id, login="tec.so.bot", acao="passe", sistema="termovision", ok=True,
                    motivo="pelo bot ou pelo conector do Claude", em=agora))   # o bot entrou por ela: sem IP
    db.commit()
    return dict(a=a, b=b, c=c, ib=ib, of=of, de_b=de_b, de_c=de_c, gerente=gerente, dono=dono, adm=adm, sem_tv=sem_tv,
                sumido=sumido, gerente_b=gerente_b, so_bot=so_bot)


def _h(pessoa, chave=CHAVE, empresa=None, sistema="termovision"):
    h = {"X-Sistema": sistema, "X-Chave-Interna": chave, "X-Usuario-GS": str(pessoa.id)}
    if empresa is not None:
        h["X-Empresa-GS"] = str(empresa)
    return h


def test_a_porta_exige_a_chave_do_termovision(http, cenario, monkeypatch):
    g = cenario["gerente"]
    for h in (_h(g, chave="errada"), _h(g, chave="é".encode()), _h(g, sistema="meuguarda"), {"X-Usuario-GS": str(g.id)}):
        for metodo, url in (("get", "/api/v1/interno/usinas"),
                            ("post", f"/api/v1/interno/usinas/{cenario['ib'].id}/mapa"),
                            ("delete", f"/api/v1/interno/usinas/{cenario['ib'].id}/mapa?termovision=x")):
            r = getattr(http, metodo)(url, headers=h, **({"json": {"termovision": "x"}} if metodo == "post" else {}))
            assert r.status_code == 401, (metodo, h, r.text)
    monkeypatch.setattr(get_settings(), "termovision_chave_interna", "")
    assert http.get("/api/v1/interno/usinas", headers=_h(g)).status_code == 503       # porta sem chave: fechada


def test_so_a_om_que_entrou_pelo_gs_ha_pouco_e_so_a_empresa_ativa_do_passe(http, cenario):
    c = cenario
    r = http.get("/api/v1/interno/usinas", headers=_h(c["gerente"]))
    assert r.status_code == 200 and [u["nome"] for u in r.json()] == ["Ibitinga", "Ouro Fino"]
    ib = next(u for u in r.json() if u["nome"] == "Ibitinga")
    assert ib == {"gs": c["ib"].id, "nome": "Ibitinga", "empresa": "Splendor O&M", "meuwatt": {"slug": "ibitinga"},
                  "meuplano": {"id": 7}, "termovision": None, "cidade": "Ibitinga", "uf": "SP", "endereco": None,
                  "latitude": None, "longitude": None}
    for quem, esperado in (("dono", 403), ("adm", 403), ("sem_tv", 404), ("sumido", 403), ("so_bot", 403)):
        assert http.get("/api/v1/interno/usinas", headers=_h(c[quem])).status_code == esperado, quem
    assert http.get("/api/v1/interno/usinas", headers=_h(c["gerente"], empresa=c["c"].id)).status_code == 404
    assert http.get("/api/v1/interno/usinas", headers=_h(c["gerente"], empresa=c["b"].id)).status_code == 404
    assert http.get("/api/v1/interno/usinas", headers={**_h(c["gerente"]), "X-Usuario-GS": "²".encode()}).status_code == 404
    assert http.get("/api/v1/interno/usinas?ids=abc", headers=_h(c["gerente"])).json() == []
    so = http.get(f"/api/v1/interno/usinas?ids={c['of'].id},²,{c['de_b'].id}", headers=_h(c["gerente"])).json()
    assert [u["nome"] for u in so] == ["Ouro Fino"]


def test_ligar_e_desligar_o_mapa(http, cenario):
    c = cenario
    url = f"/api/v1/interno/usinas/{c['ib'].id}/mapa"
    corpo = {"termovision": " zy6x0nhp ", "voo": "251126", "camadas": ["orto"]}
    r = http.post(url, headers=_h(c["gerente"]), json=corpo)
    assert r.status_code == 200 and r.json()["termovision"] == {"codigo": "zy6x0nhp"}
    assert http.post(url, headers=_h(c["gerente"]), json=corpo).status_code == 200                  # idempotente
    assert http.post(url, headers=_h(c["gerente"]), json={"termovision": "outro"}).status_code == 409
    for ruim in ("   ", "a b", "x" * 41, "../x"):
        assert http.post(url, headers=_h(c["gerente"]), json={"termovision": ruim}).status_code == 422, ruim
    # o mesmo mapa em outra usina da empresa: 409 com o nome dela
    r = http.post(f"/api/v1/interno/usinas/{c['of'].id}/mapa", headers=_h(c["gerente"]),
                  json={"termovision": "zy6x0nhp"})
    assert r.status_code == 409 and "Ibitinga" in r.json()["detail"]
    # a usina de outra empresa: não existe para ela
    assert http.post(f"/api/v1/interno/usinas/{c['de_b'].id}/mapa", headers=_h(c["gerente"]),
                     json={"termovision": "x1"}).status_code == 404
    assert http.delete(url + "?termovision=outro", headers=_h(c["gerente"])).status_code == 409
    r = http.delete(url + "?termovision=zy6x0nhp", headers=_h(c["gerente"]))
    assert r.status_code == 200 and r.json()["termovision"] is None
    assert http.delete(url + "?termovision=zy6x0nhp", headers=_h(c["gerente"])).status_code == 200  # repetir: ok


def test_o_mapa_de_outra_empresa_nao_diz_o_nome_dela(http, cenario, db):
    c = cenario
    c["de_b"].tv_codigo = "mapa-de-b"
    db.commit()
    r = http.post(f"/api/v1/interno/usinas/{c['ib'].id}/mapa", headers=_h(c["gerente"]),
                  json={"termovision": "mapa-de-b"})
    assert r.status_code == 409 and "Secreta" not in r.json()["detail"]


def test_dois_pedidos_ao_mesmo_tempo_um_grava_o_outro_e_409(db, cenario):
    """A corrida, sem o "já ligado" de antes: o código entrou em outra usina, ou esta ganhou outro mapa, no meio."""
    c = cenario
    visiveis = [c["ib"], c["of"]]
    c["of"].tv_codigo = "disputado"
    db.commit()
    with pytest.raises(HTTPException) as e:                                   # o índice único fala, e vira 409
        rota._ligar(db, c["ib"], "disputado", visiveis)
    assert e.value.status_code == 409 and "Ouro Fino" in e.value.detail
    from sqlalchemy import update
    db.execute(update(PlantLink).where(PlantLink.id == c["ib"].id).values(tv_codigo="ganhou-antes"))
    db.commit()
    c["ib"].tv_codigo = None                                                  # o objeto ainda acha que está livre
    with pytest.raises(HTTPException) as e:
        rota._ligar(db, c["ib"], "chegou-depois", visiveis)
    assert e.value.status_code == 409 and "ganhou-antes" in e.value.detail


def test_a_pagina_de_entrar_confere_a_volta_ao_abrir():
    conferir_volta("meuplano", "https://app.meuplano.solar/login?next=/frota")
    for ruim in ("https://evil.example.com/x", "https://meuplano.meuwatt.com.br/", "http://app.meuplano.solar/"):
        with pytest.raises(HTTPException) as e:
            conferir_volta("meuplano", ruim)
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        conferir_volta("outro", "https://app.meuplano.solar/")
    assert e.value.status_code == 404


def test_a_volta_pela_porta_http(http):
    assert http.get("/api/sessao/termovision/volta", params={"volta": "https://app.termovision.tech/x"}).status_code == 204
    assert http.get("/api/sessao/termovision/volta", params={"volta": "https://evil.example.com/"}).status_code == 400


def test_a_migracao_tem_uma_cabeca_so():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    raiz = Path(__file__).resolve().parents[1]
    cfg = Config(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1


def test_a_usina_desativada_no_gs_solta_o_mapa(http, cenario, db):
    """Desligar a usina no GS não prende o mapa dos dois lados: o desligar vale para ela e o conflito diz o nome."""
    c = cenario
    url = f"/api/v1/interno/usinas/{c['ib'].id}/mapa"
    assert http.post(url, headers=_h(c["gerente"]), json={"termovision": "mapa-ib"}).status_code == 200
    c["ib"].ativo = False
    db.commit()
    assert [u["nome"] for u in http.get("/api/v1/interno/usinas", headers=_h(c["gerente"])).json()] == ["Ouro Fino"]
    r = http.post(f"/api/v1/interno/usinas/{c['of'].id}/mapa", headers=_h(c["gerente"]),
                  json={"termovision": "mapa-ib"})
    assert r.status_code == 409 and "Ibitinga" in r.json()["detail"]        # da empresa: o nome vai
    assert http.post(url, headers=_h(c["gerente"]), json={"termovision": "mapa-ib"}).status_code == 404   # ligar não
    r = http.delete(url + "?termovision=mapa-ib", headers=_h(c["gerente"]))
    assert r.status_code == 200 and r.json()["termovision"] is None         # desligar sim
