"""O índice de dispositivos pela porta da máquina (`PUT`/`GET /api/v1/interno/maquina/usinas/{gs}/dispositivos`), pela
porta HTTP de verdade: só a chave do sistema, sem pessoa; o meuWatt manda a lista inteira da usina ligada a ele e cada
posição ganha um número do GS; a mesma lista de novo não muda nada; o que não veio fica ausente (nunca é apagado) e
volta com o mesmo número; a referência de outra usina recusa o pedido inteiro; e os outros sistemas ainda não entram."""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_db
from app.main import app
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa
from app.models.plant import DeviceLink, PlantLink
from app.services import acessos, dispositivos

CHAVES = {"meuguarda": "chave-mg", "meuwatt": "chave-mw", "meuplano": "chave-mp", "termovision": "chave-tv"}
LISTA = [{"ref": "trafo:41", "tipo": "transformador", "nome": "TR-01", "pai": None},
         {"ref": "inv:99", "tipo": "inversor", "nome": "INV12", "pai": "trafo:41"}]


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
    monkeypatch.setattr(acessos, "_ultimos", {})           # o agrupamento do registro é da memória do processo
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
    ib = PlantLink(nome="Ibitinga", empresa_id=a.id, mw_plant_slug="ibitinga", mp_usina_id=7, tv_codigo="dv96wz32")
    of = PlantLink(nome="Ouro Fino", empresa_id=a.id, mw_plant_slug="ouro-fino")
    so_mp = PlantLink(nome="Só no meuPlano", empresa_id=a.id, mp_usina_id=9)
    db.add_all([ib, of, so_mp])
    db.commit()
    return dict(ib=ib, of=of, so_mp=so_mp)


def _h(sistema="meuwatt", chave=None):
    return {"X-Sistema": sistema, "X-Chave-Interna": chave or CHAVES[sistema]}


def _url(usina) -> str:
    return f"/api/v1/interno/maquina/usinas/{usina.id if isinstance(usina, PlantLink) else usina}/dispositivos"


def _por(resposta: dict) -> dict:
    return {d["meuwatt"]["ref"]: d for d in resposta["dispositivos"]}


def _marcas(db) -> dict:
    db.expire_all()
    return {x.mw_ref: x.atualizado_em for x in db.query(DeviceLink)}


def test_a_lista_nasce_e_de_novo_nao_muda_nada(http, c, db):
    r = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (2, 0, 0)
    tr, inv = _por(corpo)["trafo:41"], _por(corpo)["inv:99"]
    assert tr == {"gd": tr["gd"], "codigo": f"GD-{tr['gd']:06d}", "tipo": "transformador", "nome": "TR-01",
                  "pai": None, "ativo": True, "meuwatt": {"ref": "trafo:41"}}
    assert (inv["pai"], inv["tipo"], inv["nome"], inv["codigo"]) == (tr["gd"], "inversor", "INV12", f"GD-{inv['gd']:06d}")
    antes = _marcas(db)
    # o pai pode vir DEPOIS do filho na lista, e a mesma lista de novo não muda nada (nem o "atualizado em")
    r = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA[::-1]})
    assert r.status_code == 200 and r.json() == {**corpo, "criados": 0}
    assert _marcas(db) == antes and db.query(DeviceLink).count() == 2
    # a leitura devolve a mesma lista, sem os contadores
    r = http.get(_url(c["ib"]), headers=_h())
    assert r.status_code == 200 and r.json() == {"dispositivos": corpo["dispositivos"]}
    assert http.get(_url(c["of"]), headers=_h()).json() == {"dispositivos": []}       # a outra usina dele: vazia


def test_o_nome_e_o_pai_mudam_so_onde_mudou(http, c, db):
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA})
    antes = _marcas(db)
    nova = [LISTA[0], {**LISTA[1], "nome": "  INV 12  "}, {"ref": "trafo:42", "tipo": "transformador", "nome": "TR-02"}]
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": nova}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (1, 1, 0)
    assert _por(corpo)["inv:99"]["nome"] == "INV 12"
    depois = _marcas(db)
    assert depois["trafo:41"] == antes["trafo:41"] and depois["inv:99"] != antes["inv:99"]
    # o inversor muda de transformador: só ele muda, e o número dele no GS é o mesmo
    gd = _por(corpo)["inv:99"]["gd"]
    nova[1] = {**nova[1], "nome": "INV 12", "pai": "trafo:42"}
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": nova}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 1, 0)
    assert _por(corpo)["inv:99"]["pai"] == _por(corpo)["trafo:42"]["gd"] and _por(corpo)["inv:99"]["gd"] == gd
    assert _marcas(db)["trafo:42"] == depois["trafo:42"]


def test_o_que_nao_veio_fica_ausente_e_volta_com_o_mesmo_numero(http, c, db):
    primeira = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA}).json()
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA[:1]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 0, 1)
    assert [(d["meuwatt"]["ref"], d["ativo"]) for d in corpo["dispositivos"]] == [("trafo:41", True), ("inv:99", False)]
    inv = db.query(DeviceLink).filter_by(mw_ref="inv:99").one()
    desde = inv.ausente_desde
    assert desde is not None and inv.ativo is False
    # ausente de novo: nada muda (a data é a da primeira vez), e a leitura traz o ausente
    antes = _marcas(db)
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA[:1]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 0, 0)
    db.refresh(inv)
    assert inv.ausente_desde == desde and _marcas(db) == antes
    assert [d["ativo"] for d in http.get(_url(c["ib"]), headers=_h()).json()["dispositivos"]] == [True, False]
    # voltou: o mesmo número, ativo, sem a data
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 1, 0)
    assert corpo["dispositivos"] == primeira["dispositivos"]
    db.refresh(inv)
    assert inv.ativo is True and inv.ausente_desde is None
    # a lista vazia põe todos como ausentes, e nenhum é apagado
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": []}).json()
    assert corpo["ausentes"] == 2 and db.query(DeviceLink).count() == 2


def test_a_referencia_de_outra_usina_recusa_o_pedido_inteiro(http, c, db):
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA})
    antes = _marcas(db)
    nova = [{"ref": "trafo:50", "tipo": "transformador", "nome": "TR-50", "pai": None},
            {"ref": "inv:99", "tipo": "inversor", "nome": "INV12", "pai": "trafo:50"}]
    r = http.put(_url(c["of"]), headers=_h(), json={"dispositivos": nova})
    assert r.status_code == 409 and "inv:99" in r.json()["detail"] and "trafo:50" not in r.json()["detail"], r.text
    assert _marcas(db) == antes                            # nem o trafo:50 nasceu, nem o inv:99 mudou
    assert db.query(DeviceLink).filter_by(plant_link_id=c["of"].id).count() == 0
    # o ausente continua sendo da usina dele: não muda de usina por ter saído da lista
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA[:1]})
    assert http.put(_url(c["of"]), headers=_h(), json={"dispositivos": nova}).status_code == 409


def test_so_a_usina_ligada_ao_sistema_que_chama(http, c, db):
    corpo = {"dispositivos": LISTA}
    for usina in (c["so_mp"], 9999):                       # a que não é do meuWatt e a que não existe: a mesma frase
        for r in (http.put(_url(usina), headers=_h(), json=corpo), http.get(_url(usina), headers=_h())):
            assert r.status_code == 404 and r.json()["detail"] == "Pessoa ou usina não encontrada.", r.text
    for r in (http.put(_url(c["ib"]), headers=_h("meuguarda"), json=corpo), http.get(_url(c["ib"]), headers=_h("meuguarda"))):
        assert r.status_code == 403 and "não tem usina ligada" in r.json()["detail"]
    for quem in ("meuplano", "termovision"):               # ligados à usina, mas ainda não mandam dispositivos
        for r in (http.put(_url(c["ib"]), headers=_h(quem), json=corpo), http.get(_url(c["ib"]), headers=_h(quem))):
            assert r.status_code == 403 and "ainda não" in r.json()["detail"], r.text
    for h in (_h(chave="errada"), {}, {"X-Sistema": "meuwatt"}):
        r = http.put(_url(c["ib"]), headers=h, json=corpo)
        assert r.status_code == 401 and r.json()["detail"] == "Chave inválida."
    assert db.query(DeviceLink).count() == 0 and db.query(AcessoGS).count() == 0


def test_a_lista_que_nao_serve_e_422_e_nada_e_gravado(http, c, db):
    tr, inv = LISTA
    ruins = [
        ([{**tr, "ref": "str:41:2"}], "não serve"),                                  # grafia de fase futura
        ([{**tr, "ref": "trafo:abc"}], "não serve"),
        ([{**tr, "ref": "TRAFO:41"}], "não serve"),
        ([{**tr, "tipo": "inversor"}], "é de transformador"),                       # o tipo não bate com a referência
        ([{**tr, "tipo": "string"}], "é de transformador"),
        ([tr, tr], "mais de uma vez"),
        ([inv], "mesma lista"),                                                     # o pai não veio
        ([{**tr, "pai": "trafo:41"}], "mesma lista"),                               # pai de si mesmo
    ]
    for lista, frase in ruins:
        r = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": lista})
        assert r.status_code == 422 and frase in r.json()["detail"], (lista, r.text)
    for corpo in ({"dispositivos": [{**tr, "nome": "  "}]}, {"dispositivos": [{**tr, "outro": 1}]}, {}, {"dispositivos": None},
                  {"dispositivos": [tr], "usina": {"nome": "X"}}):                    # o corpo fora do formato
        assert http.put(_url(c["ib"]), headers=_h(), json=corpo).status_code == 422, corpo
    muitos = [{"ref": f"inv:{i}", "tipo": "inversor", "nome": f"INV{i}"} for i in range(dispositivos.TETO + 1)]
    assert http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": muitos}).status_code == 422
    assert db.query(DeviceLink).count() == 0


def test_a_escrita_da_maquina_so_toca_os_dispositivos_dela_e_entra_no_registro(http, c, db):
    ib = c["ib"]
    marca = ib.atualizado_em
    de_outro = DeviceLink(plant_link_id=ib.id, tipo="inversor", nome="Nó do meuPlano", mp_node_id=501,
                          atualizado_em=datetime(2026, 1, 1, tzinfo=UTC))
    db.add(de_outro)
    db.commit()
    for _ in range(2):
        assert http.put(_url(ib), headers={**_h(), "User-Agent": "python-httpx/0.27"},
                        json={"dispositivos": LISTA}).status_code == 200
    assert http.put(_url(ib), headers=_h(), json={"dispositivos": []}).json()["ausentes"] == 2
    assert http.get(_url(ib), headers=_h()).status_code == 200
    db.refresh(de_outro)
    db.refresh(ib)
    # o dispositivo que só o meuPlano conhece não some, não fica ausente e não vai ao meuWatt; a usina não muda
    assert (de_outro.ativo, de_outro.ausente_desde, de_outro.mw_ref) == (True, None, None)
    assert de_outro.id not in {d["gd"] for d in http.get(_url(ib), headers=_h()).json()["dispositivos"]}
    assert (ib.atualizado_em, ib.nome, ib.mw_plant_slug) == (marca, "Ibitinga", "ibitinga")
    linhas = db.query(AcessoGS).order_by(AcessoGS.id).all()
    assert [(a.acao, a.sistema, a.gs_user_id, a.login, a.ok) for a in linhas] == [
        ("gravacao", "meuwatt", None, "", True), ("leitura", "meuwatt", None, "", True)]   # uma por sistema, usina e hora
    assert linhas[0].motivo == (f"meuWatt gravou pela porta da máquina (só a chave, sem pessoa): os dispositivos da "
                                f"usina GS-{ib.id:04d}")
    assert [x["quem"] for x in acessos.listar(db)] == ["Servidor do meuWatt (sem pessoa)"] * 2


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
