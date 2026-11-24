"""Os dados básicos da usina moram no GS (Plano Casa GS, R10): editar por qualquer sistema da família com histórico
(quem, de onde, antes e depois), a usina criada em outro sistema que nasce no GS ou fica "a confirmar" quando parece
uma que existe, a decisão do gerente no oem-gs e a releitura só do que mudou."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import empresa as rotas_empresa
from app.api.v1.interno_sistemas import DadosIn
from app.core.config import get_settings
from app.core.db import get_db
from app.main import app
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa
from app.models.plant import HistoricoDaUsina, PlantLink, UsinaAConfirmar
from app.models.user import Perfil, User, VinculoProduto
from app.services import dados_da_usina

CHAVES = {"meuplano": "chave-mp", "termovision": "chave-tv", "meuguarda": "chave-mg"}


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
    for s, c in CHAVES.items():
        monkeypatch.setattr(get_settings(), f"{s}_chave_interna", c)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def c(db):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    ib = PlantLink(nome="UFV Ibitinga", empresa_id=a.id, mp_usina_id=37, latitude=-21.75, longitude=-48.83,
                   cidade="Ibitinga", uf="SP")
    de_b = PlantLink(nome="Da Outra", empresa_id=b.id, mp_usina_id=99)
    gerente = User(apelido="gerente.a", nome="Gerente A", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id,
                   termovision_liberado=True)
    dono = User(apelido="dono.a", nome="Dono", perfil=Perfil.CLIENTE, empresa_id=a.id)
    db.add_all([ib, de_b, gerente, dono])
    db.commit()
    for u in (gerente, dono):
        db.add(VinculoProduto(gs_user_id=u.id, produto="meuplano", usuario_remoto_id=str(100 + u.id)))
        db.add(AcessoGS(gs_user_id=u.id, login=u.apelido, acao="passe", sistema="meuplano", ok=True, ip="200.1.1.1",
                        em=datetime.now(UTC) - timedelta(days=2)))
    db.add(AcessoGS(gs_user_id=gerente.id, login="gerente.a", acao="passe", sistema="termovision", ok=True,
                    ip="200.1.1.1", em=datetime.now(UTC)))
    db.commit()
    return dict(a=a, b=b, ib=ib, de_b=de_b, gerente=gerente, dono=dono)


def _h(pessoa, sistema="meuplano", empresa=None):
    h = {"X-Sistema": sistema, "X-Chave-Interna": CHAVES[sistema], "X-Usuario-GS": str(pessoa.id)}
    if empresa is not None:
        h["X-Empresa-GS"] = str(empresa)
    return h


def _hist(db, link):
    return [(h.campo, h.antes, h.depois, h.sistema) for h in
            db.query(HistoricoDaUsina).filter_by(plant_link_id=link.id).order_by(HistoricoDaUsina.id)]


def test_editar_pelo_sistema_grava_so_o_que_mudou_com_historico(http, c, db):
    url = f"/api/v1/interno/usinas/{c['ib'].id}"
    r = http.patch(url, headers=_h(c["gerente"]), json={"endereco": "Estrada Vicinal, km 4", "cidade": "Ibitinga",
                                                        "latitude": -21.751, "longitude": -48.832})
    assert r.status_code == 200, r.text
    assert r.json()["alterados"] == ["endereco", "latitude", "longitude"]           # a cidade já era essa
    assert _hist(db, c["ib"]) == [("endereco", None, "Estrada Vicinal, km 4", "meuplano"),
                                  ("latitude", "-21.75", "-21.751", "meuplano"),
                                  ("longitude", "-48.83", "-48.832", "meuplano")]
    assert db.query(HistoricoDaUsina).first().por_id == c["gerente"].id
    for corpo, frase in (({"latitude": 1.0}, "juntas"), ({"latitude": 91, "longitude": 0}, "entre -90"),
                         ({"uf": "São Paulo"}, "duas letras"), ({"nome": "  "}, "nome")):
        r = http.patch(url, headers=_h(c["gerente"]), json=corpo)
        assert r.status_code == 400 and frase in r.json()["detail"], (corpo, r.text)
    assert http.patch(url, headers=_h(c["gerente"]), json={"outro": 1}).status_code == 422    # campo que não existe
    assert http.patch(url, headers=_h(c["dono"]), json={"cidade": "X"}).status_code == 403     # o dono não muda
    assert http.patch(f"/api/v1/interno/usinas/{c['de_b'].id}", headers=_h(c["gerente"]),
                      json={"cidade": "X"}).status_code == 404                                  # a de outra empresa
    db.query(AcessoGS).filter_by(sistema="meuplano").update({"em": datetime.now(UTC) - timedelta(days=31)})
    db.commit()
    r = http.patch(url, headers=_h(c["gerente"]), json={"cidade": "Outra"})
    assert r.status_code == 403 and "entre nele pelo Gestão Solar" in r.json()["detail"]
    assert http.patch(url, headers=_h(c["gerente"], sistema="meuguarda"), json={}).status_code == 404  # sem o meuGuarda


def test_reler_so_as_que_mudaram(http, c, db):
    marco = datetime.now(UTC)
    c["ib"].atualizado_em = marco - timedelta(hours=1)
    db.commit()
    url = "/api/v1/interno/usinas?alteradas_desde="
    assert http.get(url + marco.isoformat().replace("+00:00", "Z"), headers=_h(c["gerente"])).json() == []
    http.patch(f"/api/v1/interno/usinas/{c['ib'].id}", headers=_h(c["gerente"]), json={"endereco": "Rua 1"})
    assert [u["nome"] for u in http.get(url + marco.isoformat().replace("+00:00", "Z"),
                                        headers=_h(c["gerente"])).json()] == ["UFV Ibitinga"]


def test_usina_nova_de_outro_sistema_nasce_ou_espera_o_gerente(http, c, db):
    url = "/api/v1/interno/usinas"
    # nenhuma parecida: nasce no GS, já ligada ao sistema de onde veio
    r = http.post(url, headers=_h(c["gerente"], sistema="termovision"), json={"nome": "Bady 1", "referencia": "dv96wz32",
                  "latitude": -22.5, "longitude": -47.1, "cidade": "Bady Bassitt", "uf": "sp"})
    assert r.status_code == 201, r.text
    bady = db.get(PlantLink, r.json()["usina"]["gs"])
    assert (bady.tv_codigo, bady.empresa_id, bady.uf, bady.ativo) == ("dv96wz32", c["a"].id, "SP", True)
    assert _hist(db, bady) == [("criada", None, "Mapa no TermoVision: dv96wz32", "termovision")]
    r = http.post(url, headers=_h(c["gerente"], sistema="termovision"), json={"nome": "Bady 1", "referencia": "dv96wz32"})
    assert r.status_code == 200 and r.json()["situacao"] == "ligada"                 # pedir de novo é idempotente
    # parecida pelo nome (sem acento, sem "UFV"): espera o gerente
    r = http.post(url, headers=_h(c["gerente"], sistema="termovision"), json={"nome": "Ibitinga", "referencia": "zy6x0nhp"})
    assert r.status_code == 202 and r.json()["situacao"] == "a_confirmar"
    assert r.json()["parecidas"][0]["gs"] == c["ib"].id
    assert http.post(url, headers=_h(c["gerente"], sistema="termovision"),
                     json={"nome": "Ibitinga", "referencia": "zy6x0nhp"}).status_code == 202
    # parecida pela distância (a 300 m), com outro nome
    r = http.post(url, headers=_h(c["gerente"]), json={"nome": "Usina do Zé", "referencia": "777",
                                                       "latitude": -21.752, "longitude": -48.830})
    assert r.status_code == 202 and r.json()["parecidas"][0]["distancia_km"] < 1.5
    # o gerente decide no oem-gs
    pend = rotas_empresa.usinas_a_confirmar(db, c["gerente"])
    assert [(p["sistema"], p["referencia"]) for p in pend] == [("TermoVision", "zy6x0nhp"), ("meuPlano", "777")]
    assert pend[0]["parecidas"][0]["codigo"] == f"GS-{c['ib'].id:04d}"
    feito = rotas_empresa.decidir_usina_a_confirmar(pend[0]["id"], rotas_empresa.DecisaoIn(decisao="mesma", gs=c["ib"].id),
                                                    db, c["gerente"])
    assert feito["decisao"] == "mesma" and db.get(PlantLink, c["ib"].id).tv_codigo == "zy6x0nhp"
    with pytest.raises(HTTPException) as e:                                          # o meuPlano 777 não é a Ibitinga
        rotas_empresa.decidir_usina_a_confirmar(pend[1]["id"], rotas_empresa.DecisaoIn(decisao="mesma", gs=c["ib"].id),
                                                db, c["gerente"])
    assert e.value.status_code == 409                                                # ela já tem o meuPlano 37
    rotas_empresa.decidir_usina_a_confirmar(pend[1]["id"], rotas_empresa.DecisaoIn(decisao="descartar"), db, c["gerente"])
    assert http.post(url, headers=_h(c["gerente"], sistema="termovision"),
                     json={"nome": "Ibitinga", "referencia": "zy6x0nhp"}).json()["situacao"] == "ligada"
    assert http.post(url, headers=_h(c["gerente"]), json={"nome": "Usina do Zé", "referencia": "777"}).json()[
        "situacao"] == "descartada"
    assert http.post(url, headers=_h(c["gerente"]), json={"nome": "Da Outra", "referencia": "99"}).status_code == 409
    assert http.post(url, headers=_h(c["gerente"], sistema="meuguarda"), json={"nome": "X", "referencia": "1"}
                     ).status_code in (403, 404)                                     # o meuGuarda usa as do GS
    assert http.post(url, headers=_h(c["gerente"]), json={"nome": "Y", "referencia": "abc"}).status_code == 400


def test_a_tela_dados_e_a_troca_de_nome_no_catalogo(db, c, monkeypatch):
    g, ib = c["gerente"], c["ib"]
    out = rotas_empresa.alterar_dados_da_usina(ib.id, DadosIn(endereco="Rod. SP-321", cidade="Araraquara"), db, g)
    assert (out.codigo, out.endereco, out.cidade) == (f"GS-{ib.id:04d}", "Rod. SP-321", "Araraquara")
    assert [(h.rotulo, h.depois, h.por, h.sistema) for h in out.historico] == [
        ("Cidade", "Araraquara", "Gerente A", "Gestão Solar"), ("Endereço", "Rod. SP-321", "Gerente A", "Gestão Solar")]
    with pytest.raises(HTTPException) as e:
        rotas_empresa.dados_da_usina_da_empresa(c["de_b"].id, db, g)
    assert e.value.status_code == 404
    # renomear pelo catálogo não desfaz a cidade editada aqui, e entra no histórico
    import asyncio
    monkeypatch.setattr(rotas_empresa, "_o_seu_token_enxerga", lambda *a, **k: asyncio.sleep(0))
    body = rotas_empresa.UsinaIn(plant_link_id=ib.id, mp_usina_id=37, nome="Ibitinga (Deva)", cidade="Ibitinga",
                                 uf="SP", kwp=1250.0, no_app=True)
    asyncio.run(rotas_empresa.salvar_usina(body, db, g))
    db.refresh(ib)
    assert (ib.nome, ib.cidade, ib.kwp) == ("Ibitinga (Deva)", "Araraquara", 1250.0)    # a potência era nula: vem
    assert ("nome", "UFV Ibitinga", "Ibitinga (Deva)", "gs") in _hist(db, ib)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
