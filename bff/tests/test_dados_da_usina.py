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
    gerente_b = User(apelido="gerente.b", nome="Gerente B", perfil=Perfil.GESTOR_EMPRESA, empresa_id=b.id)
    atendimento = User(apelido="atend", nome="Atendimento", perfil=Perfil.ATENDIMENTO)
    db.add_all([gerente_b, atendimento])
    db.commit()
    for u in (gerente_b, atendimento):
        db.add(VinculoProduto(gs_user_id=u.id, produto="meuplano", usuario_remoto_id=str(200 + u.id)))
        db.add(AcessoGS(gs_user_id=u.id, login=u.apelido, acao="passe", sistema="meuplano", ok=True, ip="200.1.1.1",
                        em=datetime.now(UTC) - timedelta(days=1)))
    db.commit()
    return dict(a=a, b=b, ib=ib, de_b=de_b, gerente=gerente, dono=dono, gerente_b=gerente_b, atendimento=atendimento)


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
    assert (bady.tv_codigo, bady.empresa_id, bady.uf, bady.ativo) == ("dv96wz32", c["a"].id, "SP", False)
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
    pend = rotas_empresa.usinas_a_confirmar(False, db, c["gerente"])
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
                     ).status_code == 403                                            # o meuGuarda usa as do GS
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


def test_o_numero_no_nome_separa_usinas(db, c):
    for nome in ("Monte Sião 6", "Stuqui - UFV 1 - Loja", "Mairinque"):
        db.add(PlantLink(nome=nome, empresa_id=c["a"].id))
    db.commit()
    acha = lambda nome: [p["nome"] for p in dados_da_usina.parecidas(db, c["a"].id, nome)]
    assert acha("Monte Sião 7") == []                                    # outro número: outra usina
    assert acha("Monte Sião 6") == ["Monte Sião 6"]
    assert acha("UFV Stuqui") == ["Stuqui - UFV 1 - Loja"]               # sem número de um lado: o gerente decide
    assert acha("Stuqui - UFV 4 - Elias") == []
    assert acha("Mairinque 205") == ["Mairinque"]
    db.add_all([PlantLink(nome="Bady Bassit 2", empresa_id=c["a"].id), PlantLink(nome="Porto Ferreira", empresa_id=c["a"].id)])
    db.commit()
    assert acha("Bady 2 (Solarorto)") == ["Bady Bassit 2"]              # a mesma palavra e o mesmo número
    assert acha("Bady 1") == []
    assert acha("Porto Feliz") == []                                     # uma palavra igual sem número não basta
    assert acha("ibitinga") == ["UFV Ibitinga"]


def test_o_pedido_nao_vaza_nem_se_perde_entre_empresas(http, c, db):
    url = "/api/v1/interno/usinas"
    r = http.post(url, headers=_h(c["gerente"]), json={"nome": "Ibitinga Sul", "referencia": "555"})
    assert r.status_code == 202 and r.json()["parecidas"][0]["nome"] == "UFV Ibitinga"
    r = http.post(url, headers=_h(c["gerente_b"]), json={"nome": "Outra", "referencia": "555"})
    assert r.status_code == 409 and "Ibitinga" not in r.text                         # nada do pedido da outra empresa
    # descartado pela empresa A ("não é nossa"), o pedido dela não bloqueia a B (antes: 409 "já está no GS")
    pid = rotas_empresa.usinas_a_confirmar(False, db, c["gerente"])[0]["id"]
    rotas_empresa.decidir_usina_a_confirmar(pid, rotas_empresa.DecisaoIn(decisao="descartar"), db, c["gerente"])
    r = http.post(url, headers=_h(c["gerente_b"]), json={"nome": "Outra", "referencia": "555"})
    assert r.status_code in (201, 202) and "Ibitinga" not in r.text, r.text
    # e o descartado da A continua na lista dela (pode voltar a confirmar), sem nada da B
    assert [p["id"] for p in rotas_empresa.usinas_a_confirmar(True, db, c["gerente"])] == [pid]
    assert http.patch(f"/api/v1/interno/usinas/{c['ib'].id}", headers=_h(c["atendimento"]),
                      json={"cidade": "X"}).status_code == 403                       # o atendimento não muda usina


def test_corrida_e_pedido_decidido_que_perdeu_o_vinculo(http, c, db, monkeypatch):
    from app.api.v1 import interno_sistemas
    url = "/api/v1/interno/usinas"
    # a corrida: o mesmo registro entra pelo outro pedido no meio do caminho -> responde o que ficou, sem 500
    original = dados_da_usina.criar

    def criar_em_corrida(db_, **k):                                       # o outro pedido gravou antes deste
        db_.add(PlantLink(nome="Corrida", empresa_id=c["a"].id, mp_usina_id=4242))
        db_.commit()
        return original(db_, **k)
    monkeypatch.setattr(dados_da_usina, "criar", criar_em_corrida)
    r = http.post(url, headers=_h(c["gerente"]), json={"nome": "Nova 4242", "referencia": "4242"})
    monkeypatch.setattr(dados_da_usina, "criar", original)
    assert r.status_code == 200 and r.json()["situacao"] == "ligada", r.text      # responde o que ficou, sem 500
    assert db.query(PlantLink).filter_by(mp_usina_id=4242).count() == 1
    # decidido "é a mesma", depois desligado do outro lado: registrar de novo reabre, sem 500
    r = http.post(url, headers=_h(c["gerente"], sistema="termovision"), json={"nome": "Ibitinga", "referencia": "OF1"})
    pid = rotas_empresa.usinas_a_confirmar(False, db, c["gerente"])[0]["id"]
    rotas_empresa.decidir_usina_a_confirmar(pid, rotas_empresa.DecisaoIn(decisao="mesma", gs=c["ib"].id), db, c["gerente"])
    assert http.delete(f"/api/v1/interno/usinas/{c['ib'].id}/mapa?termovision=OF1",
                       headers=_h(c["gerente"], sistema="termovision")).status_code == 200
    r = http.post(url, headers=_h(c["gerente"], sistema="termovision"), json={"nome": "Ibitinga", "referencia": "OF1"})
    assert r.status_code == 202 and r.json()["situacao"] == "a_confirmar"
    # dois cliques na decisão: o segundo é 409, e não cria outra usina
    pid = rotas_empresa.usinas_a_confirmar(False, db, c["gerente"])[0]["id"]
    rotas_empresa.decidir_usina_a_confirmar(pid, rotas_empresa.DecisaoIn(decisao="outra"), db, c["gerente"])
    with pytest.raises(HTTPException) as e:
        rotas_empresa.decidir_usina_a_confirmar(pid, rotas_empresa.DecisaoIn(decisao="outra"), db, c["gerente"])
    assert e.value.status_code == 409
    assert db.query(PlantLink).filter_by(tv_codigo="OF1").count() == 1


def test_descartar_sempre_e_voltar_atras(http, c, db):
    url = "/api/v1/interno/usinas"
    http.post(url, headers=_h(c["gerente"]), json={"nome": "Ibitinga B", "referencia": "777"})
    pid = rotas_empresa.usinas_a_confirmar(False, db, c["gerente"])[0]["id"]
    # trazida pelo catálogo enquanto esperava: o pedido sai sozinho da lista
    db.add(PlantLink(nome="Trazida", empresa_id=c["a"].id, mp_usina_id=777))
    db.commit()
    assert rotas_empresa.usinas_a_confirmar(False, db, c["gerente"]) == []
    db.query(UsinaAConfirmar).filter_by(id=pid).update({"decisao": None})
    db.commit()
    rotas_empresa.decidir_usina_a_confirmar(pid, rotas_empresa.DecisaoIn(decisao="descartar"), db, c["gerente"])
    with pytest.raises(HTTPException) as e:                                          # decidido não se decide de novo
        rotas_empresa.decidir_usina_a_confirmar(pid, rotas_empresa.DecisaoIn(decisao="descartar"), db, c["gerente"])
    assert e.value.status_code == 409
    assert [p["id"] for p in rotas_empresa.usinas_a_confirmar(True, db, c["gerente"])] == [pid]
    rotas_empresa.decidir_usina_a_confirmar(pid, rotas_empresa.DecisaoIn(decisao="reabrir"), db, c["gerente"])
    assert db.get(UsinaAConfirmar, pid).decisao is None


def test_o_catalogo_marca_a_releitura_e_nao_desfaz_o_nome(db, c, monkeypatch):
    import asyncio
    monkeypatch.setattr(rotas_empresa, "_o_seu_token_enxerga", lambda *a, **k: asyncio.sleep(0))
    ib = c["ib"]
    ib.atualizado_em = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    antes = ib.atualizado_em
    # outro sistema renomeou; a tela velha só desliga (sem o nome): o nome fica
    ib.nome = "Ibitinga (Deva)"
    db.commit()
    asyncio.run(rotas_empresa.salvar_usina(rotas_empresa.UsinaIn(plant_link_id=ib.id, mp_usina_id=37, no_app=False),
                                           db, c["gerente"]))
    db.refresh(ib)
    assert (ib.nome, ib.ativo) == ("Ibitinga (Deva)", False)
    assert ib.atualizado_em > antes                                              # a releitura vê a mudança
    out = rotas_empresa.dados_da_usina_da_empresa(ib.id, db, c["gerente"])
    assert ("No aplicativo", "ligada", "desligada") in [(h.rotulo, h.antes, h.depois) for h in out.historico]
    # a usina só do TermoVision não entra no aplicativo
    so_tv = PlantLink(nome="Só mapa", empresa_id=c["a"].id, tv_codigo="tv1", ativo=False)
    db.add(so_tv)
    db.commit()
    with pytest.raises(HTTPException) as e:
        asyncio.run(rotas_empresa.salvar_usina(rotas_empresa.UsinaIn(plant_link_id=so_tv.id, no_app=True), db,
                                               c["gerente"]))
    assert e.value.status_code == 400 and "TermoVision" in e.value.detail
    asyncio.run(rotas_empresa.salvar_usina(rotas_empresa.UsinaIn(plant_link_id=so_tv.id, nome="Só o mapa", no_app=False),
                                           db, c["gerente"]))
    db.refresh(so_tv)
    assert so_tv.nome == "Só o mapa" and rotas_empresa._origem(so_tv) == "termovision"
    # outro sistema ligou a usina ao meuPlano depois que a tela abriu; a tela velha liga no app SEM os identificadores:
    # a ligação fica (antes: gravava o que a tela tinha, nada, e desfazia a ligação)
    so_tv.mp_usina_id = 999
    db.commit()
    asyncio.run(rotas_empresa.salvar_usina(rotas_empresa.UsinaIn(plant_link_id=so_tv.id, no_app=True), db,
                                           c["gerente"]))
    db.refresh(so_tv)
    assert (so_tv.mp_usina_id, so_tv.tv_codigo, so_tv.ativo) == (999, "tv1", True)
    # e o que VEM no pedido muda (desfazer o casamento é mandar o campo vazio)
    asyncio.run(rotas_empresa.salvar_usina(rotas_empresa.UsinaIn(plant_link_id=so_tv.id, mp_usina_id=None,
                                                                 no_app=False), db, c["gerente"]))
    db.refresh(so_tv)
    assert so_tv.mp_usina_id is None
