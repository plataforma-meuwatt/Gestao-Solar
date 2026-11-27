"""O índice de dispositivos pela porta da máquina (`PUT`/`GET /api/v1/interno/maquina/usinas/{gs}/dispositivos`), pela
porta HTTP de verdade: só a chave do sistema, sem pessoa; o meuWatt manda a lista inteira da usina ligada a ele e cada
posição ganha um número do GS; a mesma lista de novo não muda nada; o que não veio fica ausente (nunca é apagado) e
volta com o mesmo número; a referência de outra usina recusa o pedido inteiro; e os outros sistemas ainda não mandam
lista. O meuPlano liga os nós dele aos dispositivos que já existem (`PUT …/dispositivos/nos`): só o que veio muda, um nó
é uma posição só, a troca cabe num pedido, o nó nulo desliga e a referência desconhecida volta em `sem_dispositivo`."""
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
    # ligados à usina, mas não mandam a lista (o meuPlano lê e liga nós; o TermoVision ainda não entra)
    for r in (http.put(_url(c["ib"]), headers=_h("meuplano"), json=corpo),
              http.put(_url(c["ib"]), headers=_h("termovision"), json=corpo),
              http.get(_url(c["ib"]), headers=_h("termovision"))):
        assert r.status_code == 403 and "ainda não" in r.json()["detail"], r.text
    for h in (_h(chave="errada"), {}, {"X-Sistema": "meuwatt"}):
        r = http.put(_url(c["ib"]), headers=h, json=corpo)
        assert r.status_code == 401 and r.json()["detail"] == "Chave inválida."
    assert db.query(DeviceLink).count() == 0 and db.query(AcessoGS).count() == 0


def test_a_lista_que_nao_serve_e_422_e_nada_e_gravado(http, c, db):
    tr, inv = LISTA
    ruins = [
        ([{**tr, "ref": "sb:41"}], "não serve"), ([{**tr, "ref": "medidor:41"}], "não serve"),   # prefixo que não há
        ([{"ref": "gw:1", "tipo": "rele", "nome": "ABS", "pai": None}], "é de gateway"),
        ([{"ref": "rele:1", "tipo": "gateway", "nome": "ABS", "pai": None}], "é de rele"),
        ([tr, {"ref": "gw:1", "tipo": "gateway", "nome": "ABS", "pai": "trafo:41"}], "não tem pai"),
        ([{"ref": "gw:1", "tipo": "gateway", "nome": "ABS"}, {"ref": "gw:2", "tipo": "gateway", "nome": "ABS 2", "pai": "gw:1"}],
         "não tem pai"),
        ([{"ref": "gw:1:2", "tipo": "gateway", "nome": "ABS", "pai": None}], "não serve"),
        ([{**tr, "ref": "rele:41"}], "é de rele"),                                  # o relé que veio como trafo
        ([{"ref": "ssu:1", "tipo": "rele", "nome": "Fronteira", "pai": None}], "é de medidor_ssu"),
        ([{"ref": "est:1", "tipo": "estacao_solar", "nome": "Estação", "pai": None}], "é de estacao"),
        ([tr, inv, {"ref": "rele:5", "tipo": "rele", "nome": "Relé", "pai": "inv:99"}], "tem de ser um transformador"),
        ([tr, inv, {"ref": "est:5", "tipo": "estacao", "nome": "Estação", "pai": "inv:99"}], "tem de ser um transformador"),
        ([tr, {"ref": "rele:5", "tipo": "rele", "nome": "Relé", "pai": "trafo:42"}], "mesma lista"),    # o trafo não veio
        ([tr, {"ref": "ssu:5", "tipo": "medidor_ssu", "nome": "Fronteira", "pai": "trafo:41"}], "não tem pai"),
        ([{"ref": "rele:5", "tipo": "rele", "nome": "Geral", "pai": None},
          {"ref": "rele:6", "tipo": "rele", "nome": "Relé", "pai": "rele:5"}], "tem de ser um transformador"),
        ([{**tr, "ref": "str:41"}], "não serve"), ([{**tr, "ref": "str:41:2:3"}], "não serve"),
        ([{**tr, "ref": "str:41:2"}], "é de string"),                               # a string que veio como trafo
        ([tr, inv, {"ref": "str:99:7", "tipo": "inversor", "nome": "String 7", "pai": "inv:99"}], "é de string"),
        ([tr, inv, {"ref": "str:99:7", "tipo": "string", "nome": "String 7", "pai": None}], "inversor dela (inv:99)"),
        ([tr, inv, {"ref": "str:99:7", "tipo": "string", "nome": "String 7", "pai": "trafo:41"}], "inversor dela (inv:99)"),
        ([tr, inv, {"ref": "str:98:7", "tipo": "string", "nome": "String 7", "pai": "inv:99"}], "inversor dela (inv:98)"),
        ([tr, {"ref": "str:99:7", "tipo": "string", "nome": "String 7", "pai": "inv:99"}], "mesma lista"),   # sem o inversor
        ([tr, inv, {"ref": "str:99:7", "tipo": "string", "nome": "String 7", "pai": "inv:99"},
          {"ref": "str:99:7", "tipo": "string", "nome": "String 7 de novo", "pai": "inv:99"}], "mais de uma vez"),
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


def test_as_strings_entram_como_posicao_debaixo_do_inversor_delas(http, c, db):
    """A string é a entrada CC do inversor (`str:<vaga>:<n>`; o número tem buracos), com o inversor dela por pai."""
    strings = [{"ref": f"str:99:{n}", "tipo": "string", "nome": f"String {n}", "pai": "inv:99"} for n in (1, 2, 7, 18)]
    r = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": [*strings[::-1], *LISTA]})   # em qualquer ordem
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (6, 0, 0)
    por = _por(corpo)
    s7 = por["str:99:7"]
    assert s7 == {"gd": s7["gd"], "codigo": f"GD-{s7['gd']:06d}", "tipo": "string", "nome": "String 7",
                  "pai": por["inv:99"]["gd"], "ativo": True, "meuwatt": {"ref": "str:99:7"}}
    antes = _marcas(db)
    assert http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": [*LISTA, *strings]}).json() == {**corpo, "criados": 0}
    assert _marcas(db) == antes
    # a string que saiu da entrada fica ausente (nunca é apagada) e volta com o mesmo número; a renomeada muda só ela
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": [
        *LISTA, strings[0], {**strings[1], "nome": "String 2 (leste)"}, strings[3]]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 1, 1)
    assert (_por(corpo)["str:99:7"]["ativo"], _por(corpo)["str:99:7"]["gd"]) == (False, s7["gd"])
    assert _por(corpo)["str:99:2"]["nome"] == "String 2 (leste)"
    # a mesma entrada em outra usina recusa o pedido inteiro, como qualquer dispositivo
    r = http.put(_url(c["of"]), headers=_h(), json={"dispositivos": [
        {"ref": "inv:99", "tipo": "inversor", "nome": "INV12", "pai": None}, strings[0]]})
    assert r.status_code == 409 and "str:99:1" in r.json()["detail"]
    # o meuPlano lê as strings na lista dele, sem nó enquanto a rotina de lá não as liga
    do_mp = http.get(_url(c["ib"]), headers=_h("meuplano")).json()["dispositivos"]
    assert [d for d in do_mp if d["tipo"] == "string"][0]["meuplano"] is None and len(do_mp) == 6


def test_a_lista_de_uma_usina_grande_cabe_num_pedido(http, c, db):
    """A maior usina manda uns 400 de uma vez (os transformadores, os inversores e as strings): um pedido só."""
    lista = [{"ref": "trafo:1", "tipo": "transformador", "nome": "TR-01", "pai": None}]
    for i in range(20):
        lista.append({"ref": f"inv:{100 + i}", "tipo": "inversor", "nome": f"INV{i:02d}", "pai": "trafo:1"})
        lista += [{"ref": f"str:{100 + i}:{n}", "tipo": "string", "nome": f"String {n}", "pai": f"inv:{100 + i}"}
                  for n in range(1, 21)]
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": lista}).json()
    assert (corpo["criados"], len(corpo["dispositivos"])) == (421, 421)
    antes = _marcas(db)
    corpo = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": lista}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 0, 0) and _marcas(db) == antes
    assert max(len(x.mw_ref) for x in db.query(DeviceLink)) <= 60 and len("str:123456:99") <= 60


# --------------------------------------------------------------------------- o meuPlano liga os nós dele
TRES = [*LISTA, {"ref": "inv:100", "tipo": "inversor", "nome": "INV13", "pai": "trafo:41"}]


def _nos(usina) -> str:
    return _url(usina) + "/nos"


def _ligar(http, usina, *pares):
    return http.put(_nos(usina), headers=_h("meuplano"), json={"nos": [{"ref": r, "node_id": n} for r, n in pares]})


def _nos_de(resposta: dict) -> dict:
    return {d["meuwatt"]["ref"]: (d["meuplano"] or {}).get("node_id") for d in resposta["dispositivos"] if d["meuwatt"]}


def test_o_meuplano_liga_os_nos_e_de_novo_nao_muda_nada(http, c, db):
    do_mw = http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": TRES}).json()
    gd = {ref: d["gd"] for ref, d in _por(do_mw).items()}
    r = _ligar(http, c["ib"], ("inv:99", 555), ("trafo:41", 500), ("inv:777", 900))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["ligados"], corpo["desligados"], corpo["sem_dispositivo"]) == (2, 0, ["inv:777"])   # não é erro
    # TODOS os dispositivos da usina, com a referência do meuWatt e o nó (nulo no que ainda não tem)
    assert corpo["dispositivos"] == [
        {"gd": gd["trafo:41"], "codigo": f"GD-{gd['trafo:41']:06d}", "tipo": "transformador", "nome": "TR-01",
         "pai": None, "ativo": True, "meuwatt": {"ref": "trafo:41"}, "meuplano": {"node_id": 500}},
        {"gd": gd["inv:99"], "codigo": f"GD-{gd['inv:99']:06d}", "tipo": "inversor", "nome": "INV12",
         "pai": gd["trafo:41"], "ativo": True, "meuwatt": {"ref": "inv:99"}, "meuplano": {"node_id": 555}},
        {"gd": gd["inv:100"], "codigo": f"GD-{gd['inv:100']:06d}", "tipo": "inversor", "nome": "INV13",
         "pai": gd["trafo:41"], "ativo": True, "meuwatt": {"ref": "inv:100"}, "meuplano": None}]
    assert db.query(DeviceLink).filter(DeviceLink.mp_node_id == 900).count() == 0
    antes = _marcas(db)
    r = _ligar(http, c["ib"], ("trafo:41", 500), ("inv:99", 555), ("inv:777", 900))
    assert r.json() == {**corpo, "ligados": 0} and _marcas(db) == antes                # o mesmo de novo: nada muda
    # a leitura do meuPlano traz a mesma lista; a do meuWatt segue igual à de antes (sem o nó)
    assert http.get(_url(c["ib"]), headers=_h("meuplano")).json() == {"dispositivos": corpo["dispositivos"]}
    assert http.get(_url(c["ib"]), headers=_h()).json() == {"dispositivos": do_mw["dispositivos"]}
    assert http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": TRES}).json() == {**do_mw, "criados": 0}
    assert _nos_de(http.get(_url(c["ib"]), headers=_h("meuplano")).json())["inv:99"] == 555   # a lista não mexe no nó


def test_so_o_que_veio_muda_e_o_no_nulo_desliga(http, c, db):
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": TRES})
    _ligar(http, c["ib"], ("inv:99", 555), ("trafo:41", 500))
    antes = _marcas(db)
    # o que não veio fica como está (não vir não é desligar); o que veio com outro nó muda, e só ele
    corpo = _ligar(http, c["ib"], ("inv:99", 556)).json()
    assert (corpo["ligados"], corpo["desligados"]) == (1, 0)
    assert _nos_de(corpo) == {"trafo:41": 500, "inv:99": 556, "inv:100": None}
    depois = _marcas(db)
    assert depois["trafo:41"] == antes["trafo:41"] and depois["inv:99"] != antes["inv:99"]
    assert _ligar(http, c["ib"]).json()["dispositivos"] == corpo["dispositivos"]            # a lista vazia: nada
    # o nó nulo desliga; de novo, e no que nunca teve nó, não muda nada
    corpo = _ligar(http, c["ib"], ("inv:99", None), ("inv:100", None)).json()
    assert (corpo["ligados"], corpo["desligados"]) == (0, 1)
    assert _nos_de(corpo) == {"trafo:41": 500, "inv:99": None, "inv:100": None}
    antes = _marcas(db)
    corpo = _ligar(http, c["ib"], ("inv:99", None)).json()
    assert (corpo["ligados"], corpo["desligados"]) == (0, 0) and _marcas(db) == antes
    # o dispositivo AUSENTE na lista do meuWatt guarda o nó (a posição existe) e o ausente também pode ser ligado
    _ligar(http, c["ib"], ("inv:99", 555))
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA[:1]})
    corpo = _ligar(http, c["ib"], ("inv:100", 600)).json()
    assert _nos_de(corpo) == {"trafo:41": 500, "inv:99": 555, "inv:100": 600}
    assert [d["ativo"] for d in corpo["dispositivos"]] == [True, False, False]


def test_um_no_e_uma_posicao_so_e_a_troca_cabe_num_pedido(http, c, db):
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": TRES})
    http.put(_url(c["of"]), headers=_h(), json={"dispositivos": [
        {"ref": "inv:300", "tipo": "inversor", "nome": "INV01", "pai": None}]})
    c["of"].mp_usina_id = 8
    db.commit()
    assert _ligar(http, c["ib"], ("inv:99", 555), ("inv:100", 556)).status_code == 200
    gd99 = db.query(DeviceLink).filter_by(mw_ref="inv:99").one().id
    antes = _marcas(db)
    # o nó que está em outro dispositivo, que o pedido não tira de lá: recusa o pedido inteiro, com o nó e o código
    for usina, pares in ((c["ib"], [("trafo:41", 500), ("inv:100", 555)]), (c["of"], [("inv:300", 555)])):
        r = _ligar(http, usina, *pares)
        assert r.status_code == 409 and "nó 555" in r.json()["detail"] and f"GD-{gd99:06d}" in r.json()["detail"], r.text
    assert _marcas(db) == antes and db.query(DeviceLink).filter_by(mw_ref="trafo:41").one().mp_node_id is None
    # a troca: os dois no mesmo pedido
    corpo = _ligar(http, c["ib"], ("inv:99", 556), ("inv:100", 555)).json()
    assert (corpo["ligados"], corpo["desligados"]) == (2, 0)
    assert _nos_de(corpo) == {"trafo:41": None, "inv:99": 556, "inv:100": 555}
    # o nó passa de um para o outro quando o mesmo pedido desliga o primeiro
    corpo = _ligar(http, c["ib"], ("inv:99", None), ("trafo:41", 556)).json()
    assert (corpo["ligados"], corpo["desligados"]) == (1, 1)
    assert _nos_de(corpo) == {"trafo:41": 556, "inv:99": None, "inv:100": 555}
    # e o nó solto aqui pode ir para a outra usina
    assert _ligar(http, c["of"], ("inv:300", 700)).json()["ligados"] == 1


def test_os_pares_que_nao_servem_sao_422_e_nada_e_gravado(http, c, db):
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": TRES})
    for pares, frase in (([("inv:99", 555), ("inv:99", 556)], "mais de uma vez"),         # a mesma referência
                         ([("inv:99", 555), ("inv:100", 555)], "nó 555 veio mais de uma vez"),
                         ([("inversor:99", 555)], "não serve"),                           # a grafia do meuPlano
                         ([("str:99", 555)], "não serve"), ([("sb:9", 555)], "não serve"),
                         ([("str:99:1", 555), ("str:99:1", 556)], "mais de uma vez"),
                         ([("str:99:1", 555), ("inv:99", 555)], "nó 555 veio mais de uma vez"),
                         ([("INV:99", 555)], "não serve")):
        r = _ligar(http, c["ib"], *pares)
        assert r.status_code == 422 and frase in r.json()["detail"], (pares, r.text)
    assert _ligar(http, c["ib"], ("inv:99", None), ("inv:100", None)).status_code == 200    # dois nulos não são repetição
    for corpo in ({"nos": [{"ref": "inv:99"}]}, {"nos": [{"ref": "inv:99", "node_id": 0}]}, {},
                  {"nos": [{"ref": "inv:99", "node_id": "abc"}]}, {"nos": [{"ref": "inv:99", "node_id": 1, "tipo": "x"}]},
                  {"nos": [{"ref": f"inv:{i}", "node_id": i + 1} for i in range(dispositivos.TETO + 1)]}):
        assert http.put(_nos(c["ib"]), headers=_h("meuplano"), json=corpo).status_code == 422, str(corpo)[:80]
    assert db.query(DeviceLink).filter(DeviceLink.mp_node_id.isnot(None)).count() == 0


def test_so_o_meuplano_liga_nos_e_so_na_usina_ligada_a_ele(http, c, db):
    http.put(_url(c["ib"]), headers=_h(), json={"dispositivos": LISTA})
    registros = db.query(AcessoGS).count()
    corpo = {"nos": [{"ref": "inv:99", "node_id": 555}]}
    for usina in (c["of"], 9999):                          # a que não é do meuPlano e a que não existe: a mesma frase
        for r in (http.put(_nos(usina), headers=_h("meuplano"), json=corpo), http.get(_url(usina), headers=_h("meuplano"))):
            assert r.status_code == 404 and r.json()["detail"] == "Pessoa ou usina não encontrada.", r.text
    for quem in ("meuwatt", "termovision"):
        r = http.put(_nos(c["ib"]), headers=_h(quem), json=corpo)
        assert r.status_code == 403 and "é o meuPlano" in r.json()["detail"], r.text
    r = http.put(_nos(c["ib"]), headers=_h("meuguarda"), json=corpo)
    assert r.status_code == 403 and "não tem usina ligada" in r.json()["detail"]
    for h in (_h("meuplano", chave="errada"), {}, {"X-Sistema": "meuplano"}):
        r = http.put(_nos(c["ib"]), headers=h, json=corpo)
        assert r.status_code == 401 and r.json()["detail"] == "Chave inválida."
    assert db.query(DeviceLink).filter(DeviceLink.mp_node_id.isnot(None)).count() == 0
    assert db.query(AcessoGS).count() == registros
    # a usina só do meuPlano, sem dispositivo nenhum: a lista vazia, e tudo volta em `sem_dispositivo`
    r = http.put(_nos(c["so_mp"]), headers=_h("meuplano"), json=corpo)
    assert r.status_code == 200 and r.json() == {"dispositivos": [], "ligados": 0, "desligados": 0,
                                                 "sem_dispositivo": ["inv:99"]}


def test_ligar_nos_so_grava_o_no_e_entra_no_registro(http, c, db):
    ib = c["ib"]
    http.put(_url(ib), headers=_h(), json={"dispositivos": LISTA})
    marca = ib.atualizado_em
    inv = db.query(DeviceLink).filter_by(mw_ref="inv:99").one()
    antes = (inv.tipo, inv.nome, inv.pai_id, inv.mw_ref, inv.tv_ref, inv.ativo, inv.ausente_desde)
    for _ in range(2):
        assert _ligar(http, ib, ("inv:99", 555)).status_code == 200
    db.refresh(inv)
    db.refresh(ib)
    assert (inv.tipo, inv.nome, inv.pai_id, inv.mw_ref, inv.tv_ref, inv.ativo, inv.ausente_desde) == antes
    assert inv.mp_node_id == 555 and (ib.atualizado_em, ib.mp_usina_id) == (marca, 7)       # a usina não muda
    linhas = db.query(AcessoGS).filter_by(sistema="meuplano").all()
    assert [(a.acao, a.gs_user_id, a.login, a.ok) for a in linhas] == [("gravacao", None, "", True)]
    assert linhas[0].motivo == (f"meuPlano gravou pela porta da máquina (só a chave, sem pessoa): os nós dele nos "
                                f"dispositivos da usina GS-{ib.id:04d}")


def test_o_meuplano_liga_os_nos_das_strings_pela_mesma_rota(http, c, db):
    """As strings são ligadas pela rotina do meuPlano, num pedido só delas, com as regras de qualquer dispositivo."""
    ib = c["ib"]
    lista = [*LISTA, {"ref": "inv:100", "tipo": "inversor", "nome": "INV13", "pai": "trafo:41"}]
    for vaga in (99, 100):
        lista += [{"ref": f"str:{vaga}:{n}", "tipo": "string", "nome": f"String {n}", "pai": f"inv:{vaga}"}
                  for n in range(1, 201)]
    assert http.put(_url(ib), headers=_h(), json={"dispositivos": lista}).json()["criados"] == 403
    pares = [(f"str:{vaga}:{n}", vaga * 1000 + n) for vaga in (99, 100) for n in range(1, 201)]
    r = _ligar(http, ib, *pares, ("str:99:900", 5), ("str:777:1", 6))               # 400 pares de uma vez
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["ligados"], corpo["desligados"], corpo["sem_dispositivo"]) == (400, 0, ["str:99:900", "str:777:1"])
    assert (_nos_de(corpo)["str:99:7"], _nos_de(corpo)["str:100:200"], _nos_de(corpo)["inv:99"]) == (99007, 100200, None)
    antes = _marcas(db)
    assert _ligar(http, ib, *pares).json()["ligados"] == 0 and _marcas(db) == antes   # de novo: nada muda
    # não vir não é desligar; o nó nulo desliga; a troca cabe num pedido
    corpo = _ligar(http, ib, ("str:99:1", None), ("str:99:2", 99003), ("str:99:3", 99002)).json()
    assert (corpo["ligados"], corpo["desligados"]) == (2, 1)
    assert [_nos_de(corpo)[r_] for r_ in ("str:99:1", "str:99:2", "str:99:3", "str:99:4")] == [None, 99003, 99002, 99004]
    # um nó é uma posição só, seja de string ou de inversor: recusa o pedido inteiro, com o nó e o código
    gd = db.query(DeviceLink).filter_by(mw_ref="str:99:4").one().id
    for par in (("str:99:1", 99004), ("inv:99", 99004)):
        r = _ligar(http, ib, par, ("str:99:5", 77))
        assert r.status_code == 409 and "nó 99004" in r.json()["detail"] and f"GD-{gd:06d}" in r.json()["detail"], r.text
    assert db.query(DeviceLink).filter_by(mw_ref="str:99:5").one().mp_node_id == 99005
    # a string que sai da lista do meuWatt fica ausente e guarda o nó; o histórico da usina não ganha linha por string
    http.put(_url(ib), headers=_h(), json={"dispositivos": LISTA})
    assert db.query(DeviceLink).filter_by(mw_ref="str:100:9").one().mp_node_id == 100009
    from app.models.plant import HistoricoDaUsina
    assert db.query(HistoricoDaUsina).count() == 0
    linhas = db.query(AcessoGS).filter_by(sistema="meuplano", acao="gravacao").all()
    assert len(linhas) == 1 and "os nós dele nos dispositivos" in linhas[0].motivo   # uma linha por usina e hora


# --------------------------------------------------------------------------- relés, estações e medidores da fronteira
OUTROS = [{"ref": "rele:5", "tipo": "rele", "nome": "Relé do TR-01", "pai": "trafo:41"},
          {"ref": "rele:6", "tipo": "rele", "nome": "Relé geral", "pai": None},
          {"ref": "est:3", "tipo": "estacao", "nome": "Estação 1", "pai": "trafo:41"},
          {"ref": "est:4", "tipo": "estacao", "nome": "Estação da usina"},
          {"ref": "ssu:9", "tipo": "medidor_ssu", "nome": "Fronteira", "pai": None}]


def test_reles_estacoes_e_medidores_entram_como_qualquer_dispositivo(http, c, db):
    ib = c["ib"]
    # a lista de HOJE (sem os tipos novos) segue igual: nada fica ausente por eles não virem
    hoje = http.put(_url(ib), headers=_h(), json={"dispositivos": LISTA}).json()
    assert (hoje["criados"], hoje["alterados"], hoje["ausentes"]) == (2, 0, 0)
    corpo = http.put(_url(ib), headers=_h(), json={"dispositivos": [*OUTROS, *LISTA]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (5, 0, 0)
    por = _por(corpo)
    assert por["trafo:41"] == _por(hoje)["trafo:41"] and por["inv:99"] == _por(hoje)["inv:99"]
    tr = por["trafo:41"]["gd"]
    assert [(r, por[r]["tipo"], por[r]["pai"]) for r in ("rele:5", "rele:6", "est:3", "est:4", "ssu:9")] == [
        ("rele:5", "rele", tr), ("rele:6", "rele", None), ("est:3", "estacao", tr), ("est:4", "estacao", None),
        ("ssu:9", "medidor_ssu", None)]
    assert por["ssu:9"] == {"gd": por["ssu:9"]["gd"], "codigo": f"GD-{por['ssu:9']['gd']:06d}", "tipo": "medidor_ssu",
                            "nome": "Fronteira", "pai": None, "ativo": True, "meuwatt": {"ref": "ssu:9"}}
    antes = _marcas(db)
    assert http.put(_url(ib), headers=_h(), json={"dispositivos": [*LISTA, *OUTROS]}).json() == {**corpo, "criados": 0}
    assert _marcas(db) == antes
    # a leitura dos dois sistemas os traz com o tipo
    assert http.get(_url(ib), headers=_h()).json() == {"dispositivos": corpo["dispositivos"]}
    do_mp = {d["meuwatt"]["ref"]: d for d in http.get(_url(ib), headers=_h("meuplano")).json()["dispositivos"]}
    assert (do_mp["rele:6"]["tipo"], do_mp["est:3"]["tipo"], do_mp["ssu:9"]["tipo"], do_mp["ssu:9"]["meuplano"]) == (
        "rele", "estacao", "medidor_ssu", None)
    # o que não veio fica ausente (nunca é apagado) e volta com o mesmo número; o relé muda de transformador
    corpo = http.put(_url(ib), headers=_h(), json={"dispositivos": [
        *LISTA, {**OUTROS[0], "pai": None}, OUTROS[1], OUTROS[3]]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 1, 2)
    assert [(_por(corpo)[r]["ativo"], _por(corpo)[r]["gd"]) for r in ("est:3", "ssu:9")] == [
        (False, por["est:3"]["gd"]), (False, por["ssu:9"]["gd"])]
    assert _por(corpo)["rele:5"]["pai"] is None and db.query(DeviceLink).count() == 7
    corpo = http.put(_url(ib), headers=_h(), json={"dispositivos": [*LISTA, *OUTROS]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 3, 0)
    assert _por(corpo)["ssu:9"] == por["ssu:9"]
    # a mesma referência em outra usina recusa o pedido inteiro
    r = http.put(_url(c["of"]), headers=_h(), json={"dispositivos": [OUTROS[4]]})
    assert r.status_code == 409 and "ssu:9" in r.json()["detail"]
    # e a lista de hoje, de novo, põe os tipos novos como ausentes como poria qualquer um que não veio
    corpo = http.put(_url(ib), headers=_h(), json={"dispositivos": LISTA}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 0, 5)


def test_o_meuplano_liga_o_no_do_rele_da_estacao_e_do_medidor(http, c, db):
    ib = c["ib"]
    http.put(_url(ib), headers=_h(), json={"dispositivos": [*LISTA, *OUTROS]})
    corpo = _ligar(http, ib, ("rele:5", 801), ("est:3", 802), ("ssu:9", 803), ("rele:77", 804)).json()
    assert (corpo["ligados"], corpo["desligados"], corpo["sem_dispositivo"]) == (3, 0, ["rele:77"])
    assert [_nos_de(corpo)[r] for r in ("rele:5", "est:3", "ssu:9", "rele:6")] == [801, 802, 803, None]
    # um nó é uma posição só; não vir não é desligar; o nó nulo desliga
    r = _ligar(http, ib, ("rele:6", 803))
    assert r.status_code == 409 and "nó 803" in r.json()["detail"]
    corpo = _ligar(http, ib, ("ssu:9", None)).json()
    assert (corpo["ligados"], corpo["desligados"]) == (0, 1)
    assert [_nos_de(corpo)[r] for r in ("rele:5", "est:3", "ssu:9")] == [801, 802, None]
    # o ausente na lista do meuWatt guarda o nó
    http.put(_url(ib), headers=_h(), json={"dispositivos": LISTA})
    assert db.query(DeviceLink).filter_by(mw_ref="rele:5").one().mp_node_id == 801


def test_o_gateway_entra_como_dispositivo_da_usina(http, c, db):
    ib = c["ib"]
    gws = [{"ref": "gw:7", "tipo": "gateway", "nome": "ABS Skid 1", "pai": None},
           {"ref": "gw:8", "tipo": "gateway", "nome": "ABS Skid 2"}]
    # a lista de antes (sem gateway) segue igual, e nada fica ausente por ele não vir
    antes_dele = http.put(_url(ib), headers=_h(), json={"dispositivos": [*LISTA, *OUTROS]}).json()
    assert (antes_dele["criados"], antes_dele["ausentes"]) == (7, 0)
    corpo = http.put(_url(ib), headers=_h(), json={"dispositivos": [*gws, *LISTA, *OUTROS]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (2, 0, 0)
    por = _por(corpo)
    assert por["gw:7"] == {"gd": por["gw:7"]["gd"], "codigo": f"GD-{por['gw:7']['gd']:06d}", "tipo": "gateway",
                           "nome": "ABS Skid 1", "pai": None, "ativo": True, "meuwatt": {"ref": "gw:7"}}
    assert {r: d for r, d in por.items() if not r.startswith("gw:")} == _por(antes_dele)
    marcas = _marcas(db)
    assert http.put(_url(ib), headers=_h(), json={"dispositivos": [*LISTA, *OUTROS, *gws]}).json() == {**corpo, "criados": 0}
    assert _marcas(db) == marcas
    # as duas leituras o trazem; o que não veio fica ausente e volta com o mesmo número; de outra usina, 409
    assert http.get(_url(ib), headers=_h()).json() == {"dispositivos": corpo["dispositivos"]}
    do_mp = {d["meuwatt"]["ref"]: d for d in http.get(_url(ib), headers=_h("meuplano")).json()["dispositivos"]}
    assert (do_mp["gw:8"]["tipo"], do_mp["gw:8"]["meuplano"]) == ("gateway", None)
    corpo = http.put(_url(ib), headers=_h(), json={"dispositivos": [*LISTA, *OUTROS, gws[0]]}).json()
    assert (corpo["criados"], corpo["alterados"], corpo["ausentes"]) == (0, 0, 1)
    assert (_por(corpo)["gw:8"]["ativo"], _por(corpo)["gw:8"]["gd"]) == (False, por["gw:8"]["gd"])
    assert http.put(_url(ib), headers=_h(), json={"dispositivos": [*LISTA, *OUTROS, *gws]}).json()["alterados"] == 1
    r = http.put(_url(c["of"]), headers=_h(), json={"dispositivos": [gws[0]]})
    assert r.status_code == 409 and "gw:7" in r.json()["detail"]
    # o meuPlano liga o nó dele, com as regras de sempre
    corpo = _ligar(http, ib, ("gw:7", 901), ("gw:99", 902)).json()
    assert (corpo["ligados"], corpo["sem_dispositivo"], _nos_de(corpo)["gw:7"], _nos_de(corpo)["gw:8"]) == (
        1, ["gw:99"], 901, None)
    r = _ligar(http, ib, ("gw:8", 901))
    assert r.status_code == 409 and "nó 901" in r.json()["detail"]
    assert _ligar(http, ib, ("gw:7", None)).json()["desligados"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
