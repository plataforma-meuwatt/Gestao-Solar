"""A porta da máquina (`GET /api/v1/interno/maquina/usinas`), pela porta HTTP de verdade: só a chave do sistema, sem
pessoa; cada sistema lê as usinas do índice ligadas a ELE, com a referência dele e mais nenhuma, sem a empresa e sem a
proprietária; a desligada no aplicativo vem; `alteradas_desde` relê só o que mudou e diz o vínculo que saiu; o meuGuarda
não tem o que ler; e a leitura entra no Registro de acessos uma vez por sistema e hora."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_db
from app.main import app
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa, Proprietaria
from app.models.plant import PlantLink
from app.services import acessos, dados_da_usina

CHAVES = {"meuguarda": "chave-mg", "meuwatt": "chave-mw", "meuplano": "chave-mp", "termovision": "chave-tv"}
URL = "/api/v1/interno/maquina/usinas"
#: o que a porta da máquina entrega de cada usina, além da referência do sistema que chama
BASICOS = {"gs", "codigo", "nome", "cidade", "uf", "kwp", "endereco", "latitude", "longitude", "ativo", "atualizado_em"}


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
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    dona = Proprietaria(nome="Dona Segredo S.A.", empresa_id=a.id)
    db.add(dona)
    db.commit()
    ib = PlantLink(nome="Ibitinga", empresa_id=a.id, mw_plant_slug="ibitinga", mp_usina_id=7, tv_codigo="dv96wz32",
                   cidade="Ibitinga", uf="SP", kwp=1250.0, endereco="Estrada Vicinal, km 4", latitude=-21.7,
                   longitude=-48.8, proprietaria_id=dona.id)
    of = PlantLink(nome="Ouro Fino", empresa_id=b.id, mw_plant_slug="ouro-fino")      # de outra empresa: a máquina lê
    parada = PlantLink(nome="Parada no GS", empresa_id=a.id, mw_plant_slug="parada", ativo=False)
    so_mp = PlantLink(nome="Só no meuPlano", empresa_id=a.id, mp_usina_id=9)
    solta = PlantLink(nome="Sem sistema nenhum", empresa_id=a.id)
    db.add_all([ib, of, parada, so_mp, solta])
    db.commit()
    return dict(a=a, b=b, ib=ib, of=of, parada=parada, so_mp=so_mp, solta=solta)


def _h(sistema="meuwatt", chave=None):
    return {"X-Sistema": sistema, "X-Chave-Interna": chave or CHAVES[sistema]}


def _z(quando: datetime) -> str:
    return quando.isoformat().replace("+00:00", "Z")


def test_sem_a_chave_certa_a_porta_da_maquina_nao_abre(http, c, monkeypatch):
    for h in (_h(chave="errada"), _h(sistema="meuwatt", chave=CHAVES["meuplano"]), {}, {"X-Sistema": "meuwatt"},
              {"X-Chave-Interna": CHAVES["meuwatt"]}, {**_h(), "X-Sistema": "outro"}):
        r = http.get(URL, headers=h)
        assert r.status_code == 401 and r.json()["detail"] == "Chave inválida.", h
    monkeypatch.setattr(get_settings(), "meuwatt_chave_interna", "")
    r = http.get(URL, headers=_h(chave="qualquer"))
    assert r.status_code == 401 and "CHAVE" not in r.json()["detail"]      # porta sem chave: fechada, sem dizer qual
    assert http.get(URL, headers=_h(chave="")).status_code == 401          # a chave vazia não casa com a não configurada


def test_so_a_chave_le_as_usinas_ligadas_ao_sistema_que_chama(http, c):
    r = http.get(URL, headers=_h())                                        # nenhum cabeçalho de pessoa
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"usinas", "desligadas"} and j["desligadas"] == []
    assert [(u["nome"], u["meuwatt"]) for u in j["usinas"]] == [
        ("Ibitinga", {"slug": "ibitinga"}), ("Ouro Fino", {"slug": "ouro-fino"}), ("Parada no GS", {"slug": "parada"})]
    ib = j["usinas"][0]
    assert {k: ib[k] for k in BASICOS - {"atualizado_em"}} == {
        "gs": c["ib"].id, "codigo": f"GS-{c['ib'].id:04d}", "nome": "Ibitinga", "cidade": "Ibitinga", "uf": "SP",
        "kwp": 1250.0, "endereco": "Estrada Vicinal, km 4", "latitude": -21.7, "longitude": -48.8, "ativo": True}
    assert ib["atualizado_em"]
    # o campo vazio vem nulo (a usina sem cidade), e a desligada no aplicativo vem, com `ativo` falso
    assert j["usinas"][1]["cidade"] is None and j["usinas"][2]["ativo"] is False
    # cada sistema com a referência DELE
    mp = http.get(URL, headers=_h("meuplano")).json()["usinas"]
    assert [(u["nome"], u["meuplano"]) for u in mp] == [("Ibitinga", {"id": 7}), ("Só no meuPlano", {"id": 9})]
    tv = http.get(URL, headers=_h("termovision")).json()["usinas"]
    assert [(u["nome"], u["termovision"]) for u in tv] == [("Ibitinga", {"codigo": "dv96wz32"})]


def test_a_chave_nao_aprende_o_que_e_dos_outros_sistemas_nem_de_quem_e_a_usina(http, c):
    for quem in ("meuwatt", "meuplano", "termovision"):
        r = http.get(URL, headers=_h(quem))
        for u in r.json()["usinas"]:
            assert set(u) == BASICOS | {quem}, (quem, u)                   # nem como nulo: o campo não existe
        for segredo in ("empresa", "proprietaria", "Splendor", "Outra O&M", "Dona Segredo", "micro"):
            assert segredo not in r.text, (quem, segredo)
    mw = http.get(URL, headers=_h()).text
    assert "dv96wz32" not in mw and "meuplano" not in mw and "termovision" not in mw
    assert "ibitinga" not in http.get(URL, headers=_h("termovision")).text.replace("Ibitinga", "")


def test_a_pessoa_no_cabecalho_nao_muda_o_que_a_maquina_le(http, c):
    limpo = http.get(URL, headers=_h()).json()
    com = http.get(URL, headers={**_h(), "X-Usuario-GS": "999", "X-Empresa-GS": str(c["b"].id), "X-Sessao-GS": "x"})
    assert com.status_code == 200 and com.json() == limpo                 # nem 404 da pessoa, nem recorte da empresa


def test_o_meuguarda_nao_tem_usina_ligada_a_ele(http, c, db):
    r = http.get(URL, headers=_h("meuguarda"))
    assert r.status_code == 403 and "não tem usina ligada a ele" in r.json()["detail"]
    assert db.query(AcessoGS).count() == 0                                 # não leu: não há o que registrar


def test_reler_so_as_que_mudaram_com_o_relogio_do_gs(http, c, db):
    marco = datetime.now(UTC)
    for u in (c["ib"], c["of"], c["parada"]):
        u.atualizado_em = marco - timedelta(hours=1)
    db.commit()
    r = http.get(URL, headers=_h())
    lido = datetime.fromisoformat(r.headers["X-GS-Lido-Em"])
    assert lido.tzinfo is not None and abs(lido - marco) < timedelta(seconds=5) and len(r.json()["usinas"]) == 3
    r = http.get(f"{URL}?alteradas_desde={_z(marco)}", headers=_h())
    assert r.status_code == 200 and r.json() == {"usinas": [], "desligadas": []} and r.headers["X-GS-Lido-Em"]
    # o dado básico mudou (como o PATCH da porta e as telas do GS gravam), e a usina saiu do aplicativo
    dados_da_usina.alterar(db, c["ib"], {"endereco": "Rua 1"}, por=None, sistema="gs")
    c["parada"].nome, c["parada"].atualizado_em = "Parada de vez", datetime.now(UTC)
    db.commit()
    j = http.get(f"{URL}?alteradas_desde={_z(marco)}", headers=_h()).json()
    assert [(u["nome"], u["endereco"], u["ativo"]) for u in j["usinas"]] == [("Ibitinga", "Rua 1", True),
                                                                            ("Parada de vez", None, False)]
    # sem fuso, é de Brasília (UTC-3): a hora de lá, daqui a uma hora, ainda não chegou
    brasilia = (marco - timedelta(hours=3)).replace(tzinfo=None)
    assert len(http.get(f"{URL}?alteradas_desde={(brasilia - timedelta(minutes=1)).isoformat()}",
                        headers=_h()).json()["usinas"]) == 2
    assert http.get(f"{URL}?alteradas_desde={(brasilia + timedelta(hours=1)).isoformat()}",
                    headers=_h()).json()["usinas"] == []
    assert http.get(f"{URL}?alteradas_desde=ontem", headers=_h()).status_code == 422


def _religar(db, link, campo, novo):
    """Como o oem-gs › Usinas e o TermoVision gravam a troca de vínculo: o campo, a linha do histórico e o relógio."""
    antes = getattr(link, campo)
    setattr(link, campo, novo)
    dados_da_usina.historico(db, link, campo, antes, novo, por=None, sistema="gs")
    link.atualizado_em = datetime.now(UTC)
    db.commit()


def test_o_vinculo_que_saiu_vem_nas_desligadas(http, c, db):
    marco = datetime.now(UTC) - timedelta(minutes=1)
    for u in (c["ib"], c["of"], c["parada"], c["so_mp"]):
        u.atualizado_em = marco - timedelta(hours=1)
    db.commit()
    _religar(db, c["of"], "mw_plant_slug", None)                           # desligada do meuWatt
    _religar(db, c["parada"], "mw_plant_slug", "parada-2")                 # trocou de usina no meuWatt
    _religar(db, c["ib"], "mp_usina_id", None)                             # saiu do meuPlano, segue no meuWatt
    j = http.get(f"{URL}?alteradas_desde={_z(marco)}", headers=_h()).json()
    # (a Ibitinga volta porque a linha dela mudou; o meuWatt não fica sabendo o quê: o meuPlano não aparece)
    assert [(u["nome"], u["meuwatt"]) for u in j["usinas"]] == [("Ibitinga", {"slug": "ibitinga"}),
                                                                ("Parada no GS", {"slug": "parada-2"})]
    assert all("meuplano" not in u for u in j["usinas"])
    assert [(d["gs"], d["codigo"], d["meuwatt"]) for d in j["desligadas"]] == [
        (c["of"].id, f"GS-{c['of'].id:04d}", {"slug": "ouro-fino"}), (c["parada"].id, f"GS-{c['parada'].id:04d}",
                                                                      {"slug": "parada"})]
    for d in j["desligadas"]:                                              # só o número, o código, a referência e quando
        assert set(d) == {"gs", "codigo", "meuwatt", "desligada_em"}
    # o meuPlano fica sabendo do dele, com o número de lá
    mp = http.get(f"{URL}?alteradas_desde={_z(marco)}", headers=_h("meuplano")).json()
    assert mp["usinas"] == [] and [(d["gs"], d["meuplano"]) for d in mp["desligadas"]] == [(c["ib"].id, {"id": 7})]
    # ligada de novo à mesma usina: não está desligada, volta em `usinas`
    _religar(db, c["of"], "mw_plant_slug", "ouro-fino")
    j = http.get(f"{URL}?alteradas_desde={_z(marco)}", headers=_h()).json()
    assert [u["nome"] for u in j["usinas"]] == ["Ibitinga", "Ouro Fino", "Parada no GS"]
    assert [d["meuwatt"] for d in j["desligadas"]] == [{"slug": "parada"}]
    # o que saiu ANTES do marco não volta, e a leitura inteira não traz desligadas
    depois = _z(datetime.now(UTC) + timedelta(minutes=1))
    assert http.get(f"{URL}?alteradas_desde={depois}", headers=_h()).json() == {"usinas": [], "desligadas": []}
    assert http.get(URL, headers=_h()).json()["desligadas"] == []


def test_a_leitura_entra_no_registro_uma_vez_por_sistema_e_hora(http, c, db):
    for _ in range(3):                                                     # a rotina relê de poucos em poucos minutos
        assert http.get(URL, headers={**_h(), "User-Agent": "python-httpx/0.27"}).status_code == 200
    assert http.get(URL, headers=_h("meuplano")).status_code == 200
    assert http.get(URL, headers=_h(chave="errada")).status_code == 401
    linhas = db.query(AcessoGS).order_by(AcessoGS.id).all()
    assert [(a.acao, a.sistema, a.gs_user_id, a.login, a.ok) for a in linhas] == [
        ("leitura", "meuwatt", None, "", True), ("leitura", "meuplano", None, "", True)]
    assert linhas[0].motivo == "meuWatt leu pela porta da máquina (só a chave, sem pessoa): as usinas ligadas a ele"
    # a tela Registro de acessos diz de quem é a linha (não "Login em branco"); a empresa não a vê (não é de conta dela)
    visto = acessos.listar(db)
    assert [x["quem"] for x in visto] == ["Servidor do meuPlano (sem pessoa)", "Servidor do meuWatt (sem pessoa)"]
    assert visto[1]["aparelho"] == "servidor de outro sistema" and visto[1]["usuario_id"] is None
    from app.models.user import User
    assert acessos.listar(db, contas=User.empresa_id == c["a"].id, empresa_vista=c["a"].id) == []
