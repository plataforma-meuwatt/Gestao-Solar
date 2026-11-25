"""A porta dos sistemas da família (Plano Casa GS, 24/11/2026), pela porta HTTP de verdade: cada sistema com a SUA
chave, a pessoa ativa e com aquele sistema liberado, a empresa ativa; a renovação (`usinas-da-pessoa`) no formato do
passe v2; as usinas de cada um (plataforma todas, O&M a empresa, dono as dele) com o código do GS; e o passe do
TermoVision para o mapa embutido, só para quem entrou no sistema que pede pelo GS nas últimas 12 h."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import get_settings
from app.core.db import get_db
from app.main import app
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess, VinculoProduto

CHAVES = {"meuguarda": "chave-mg", "meuwatt": "chave-mw", "meuplano": "chave-mp", "termovision": "chave-tv"}


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
    for s, c in CHAVES.items():
        monkeypatch.setattr(get_settings(), f"{s}_chave_interna", c)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cenario(db):
    a, b, off = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M"), Empresa(nome="Desligada", ativa=False)
    db.add_all([a, b, off])
    db.commit()
    ib = PlantLink(nome="Ibitinga", empresa_id=a.id, mw_plant_slug="ibitinga", mp_usina_id=7, latitude=-21.7,
                   longitude=-48.8, kwp=1250.0)
    of = PlantLink(nome="Ouro Fino", empresa_id=a.id, mw_plant_slug="ouro-fino")
    desligada = PlantLink(nome="Desligada no GS", empresa_id=a.id, ativo=False)
    de_b = PlantLink(nome="Usina Secreta B", empresa_id=b.id, mp_usina_id=9)
    gerente = User(apelido="gerente.a", nome="G", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id, email="g@x.com",
                   meuguarda_liberado=True, termovision_liberado=True)
    dono = User(apelido="dono.a", nome="D", perfil=Perfil.CLIENTE, empresa_id=a.id, meuguarda_liberado=True)
    adm = User(apelido="adm.p", nome="P", perfil=Perfil.ADMINISTRADOR)
    sem_mg = User(apelido="tec.sem.mg", nome="T", perfil=Perfil.TECNICO, empresa_id=a.id)
    inativo = User(apelido="tec.inativo", nome="I", perfil=Perfil.TECNICO, empresa_id=a.id, meuguarda_liberado=True,
                   ativo=False)
    da_off = User(apelido="ger.off", nome="O", perfil=Perfil.GESTOR_EMPRESA, empresa_id=off.id, meuguarda_liberado=True)
    db.add_all([ib, of, desligada, de_b, gerente, dono, adm, sem_mg, inativo, da_off])
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=of.id))
    db.add(VinculoProduto(gs_user_id=gerente.id, produto=Produto.MEUWATT.value, usuario_remoto_id="8"))
    for u in (gerente, dono, adm, sem_mg, inativo, da_off):   # entraram pelo GS há pouco (a transição sem a sessão)
        db.add(AcessoGS(gs_user_id=u.id, login=u.apelido, acao="entrou", sistema="gs", ok=True, ip="200.1.1.1",
                        em=datetime.now(UTC) - timedelta(days=2)))
    db.commit()
    return dict(a=a, b=b, ib=ib, of=of, de_b=de_b, desligada=desligada, gerente=gerente, dono=dono, adm=adm,
                sem_mg=sem_mg, inativo=inativo, da_off=da_off)


def _h(pessoa, sistema="meuguarda", chave=None, empresa=None, ip=None):
    h = {"X-Sistema": sistema, "X-Chave-Interna": chave or CHAVES[sistema], "X-Usuario-GS": str(pessoa.id)}
    if empresa is not None:
        h["X-Empresa-GS"] = str(empresa)
    if ip is not None:
        h["X-Usuario-IP"] = ip
    return h


def test_cada_sistema_com_a_sua_chave(http, cenario, monkeypatch):
    g = cenario["gerente"]
    for h in (_h(g, chave="errada"), _h(g, sistema="meuguarda", chave=CHAVES["meuwatt"]), {"X-Usuario-GS": str(g.id)},
              {**_h(g), "X-Sistema": "outro"}):
        for url in ("/api/v1/interno/usinas-da-pessoa", "/api/v1/interno/usinas", f"/api/v1/interno/usinas/{cenario['ib'].id}"):
            assert http.get(url, headers=h).status_code == 401, (h, url)
    assert http.post("/api/v1/interno/passe/termovision", headers=_h(g, sistema="meuwatt", chave="x")).status_code == 401
    monkeypatch.setattr(get_settings(), "meuguarda_chave_interna", "")
    r = http.get("/api/v1/interno/usinas", headers=_h(g, chave="qualquer"))
    assert r.status_code == 401 and "CHAVE" not in r.json()["detail"]   # porta sem chave: fechada, sem dizer qual


def test_a_renovacao_diz_quem_e_e_as_usinas_como_no_passe(http, cenario):
    c = cenario
    r = http.get("/api/v1/interno/usinas-da-pessoa", headers=_h(c["gerente"]))
    assert r.status_code == 200
    j = r.json()
    assert (j["gs"], j["apelido"], j["perfil"], j["empresa_id"]) == (c["gerente"].id, "gerente.a", "gestor_empresa", c["a"].id)
    # meuGuarda: o nº do GS; a O&M leva também a da empresa fora do aplicativo (a régua da porta, `visiveis`)
    assert j["usinas"] == [{"gs": n, "id": n} for n in (c["desligada"].id, c["ib"].id, c["of"].id)]
    assert not j["todas_as_usinas"] and not j["usinas_fora"]
    assert set(j["sistemas"]) == {"meuwatt", "meuguarda", "termovision"}
    mw = http.get("/api/v1/interno/usinas-da-pessoa", headers=_h(c["gerente"], sistema="meuwatt")).json()
    assert mw["usinas"] == [{"gs": c["ib"].id, "id": "ibitinga"}, {"gs": c["of"].id, "id": "ouro-fino"}]  # o slug de lá
    # (a desligada não tem slug no meuWatt: não vai na lista de lá)
    assert http.get("/api/v1/interno/usinas-da-pessoa", headers=_h(c["adm"])).json()["todas_as_usinas"] is True
    assert http.get("/api/v1/interno/usinas-da-pessoa", headers=_h(c["dono"])).json()["usinas"] == [
        {"gs": c["of"].id, "id": c["of"].id}]
    # a sessão de lá acaba: desligada, sem o sistema liberado, empresa desativada ou de outra empresa
    for h in (_h(c["inativo"]), _h(c["sem_mg"]), _h(c["da_off"]), _h(c["gerente"], empresa=c["b"].id),
              _h(c["dono"], sistema="meuplano"), {**_h(c["gerente"]), "X-Usuario-GS": "abc"}):
        r = http.get("/api/v1/interno/usinas-da-pessoa", headers=h)
        assert r.status_code == 404 and r.json()["detail"] == "Pessoa ou usina não encontrada.", h


def test_as_usinas_de_cada_um_com_o_codigo_do_gs(http, cenario):
    c = cenario
    r = http.get("/api/v1/interno/usinas", headers=_h(c["gerente"]))
    assert [(u["nome"], u["ativo"]) for u in r.json()] == [("Desligada no GS", False), ("Ibitinga", True),
                                                          ("Ouro Fino", True)]       # da empresa; `ativo` diz
    assert r.headers["X-GS-Lido-Em"]
    ib = r.json()[1]
    assert (ib["codigo"], ib["latitude"], ib["longitude"], ib["kwp"], ib["meuplano"]) == (
        f"GS-{c['ib'].id:04d}", -21.7, -48.8, 1250.0, {"id": 7})
    assert [u["nome"] for u in http.get("/api/v1/interno/usinas", headers=_h(c["adm"])).json()] == [
        "Desligada no GS", "Ibitinga", "Ouro Fino", "Usina Secreta B"]               # a plataforma: todas
    assert [u["nome"] for u in http.get("/api/v1/interno/usinas", headers=_h(c["dono"])).json()] == ["Ouro Fino"]
    assert [u["nome"] for u in http.get(f"/api/v1/interno/usinas?ids={c['of'].id},{c['de_b'].id}",
                                        headers=_h(c["gerente"])).json()] == ["Ouro Fino"]
    assert http.get(f"/api/v1/interno/usinas/{c['ib'].id}", headers=_h(c["gerente"])).json()["nome"] == "Ibitinga"
    for gs, quem in ((c["de_b"].id, "gerente"), (c["ib"].id, "dono"), (999, "adm")):     # fora do alcance: 404
        assert http.get(f"/api/v1/interno/usinas/{gs}", headers=_h(c[quem])).status_code == 404
    # o TermoVision segue com a régua dele: o dono não liga mapa, e só quem entrou lá pelo GS há pouco
    assert http.get("/api/v1/interno/usinas", headers=_h(c["gerente"], sistema="termovision")).status_code == 403


def test_o_passe_do_termovision_so_para_quem_entrou_pelo_gs_ha_pouco(http, cenario, db):
    c, g = cenario, cenario["gerente"]
    url = "/api/v1/interno/passe/termovision"
    assert http.post(url, headers=_h(g, sistema="meuwatt", ip="200.1.1.1")).status_code == 403   # sem entrada recente
    db.add(AcessoGS(gs_user_id=g.id, login=g.apelido, acao="passe", sistema="meuwatt", ok=True, ip="",
                    em=datetime.now(UTC)))                                           # o bot por ela (sem IP): não conta
    db.add(AcessoGS(gs_user_id=g.id, login=g.apelido, acao="passe", sistema="meuwatt", ok=True, ip="200.1.1.1",
                    em=datetime.now(UTC) - timedelta(hours=13)))                    # há mais de 12 h: não conta
    db.commit()
    r = http.post(url, headers=_h(g, sistema="meuwatt", ip="200.1.1.1"))
    assert r.status_code == 403 and "meuWatt" in r.json()["detail"]
    db.add(AcessoGS(gs_user_id=g.id, login=g.apelido, acao="passe", sistema="meuwatt", ok=True, ip="200.1.1.1",
                    em=datetime.now(UTC) - timedelta(minutes=3)))
    db.commit()
    assert http.post(url, headers=_h(g, sistema="meuwatt")).status_code == 400                  # sem o IP da pessoa
    r = http.post(url, headers=_h(g, sistema="meuwatt", ip="200.9.9.9"))
    assert r.status_code == 200, r.text
    dados = jwt.get_unverified_claims(r.json()["assertion"])
    assert (dados["aud"], dados["sub"], dados["termovision"], dados["empresa_id"], dados["portao"]) == (
        "termovision", str(g.id), True, c["a"].id, "empresa")
    assert dados["usinas"] == [{"gs": n, "id": n} for n in (c["desligada"].id, c["ib"].id, c["of"].id)]
    linha = db.query(AcessoGS).filter(AcessoGS.sistema == "termovision").one()
    assert (linha.acao, linha.motivo, linha.ip, linha.gs_user_id) == ("passe", "mapa embutido no meuWatt", "200.9.9.9", g.id)
    # o meuPlano não abre por esta pessoa (sem a ligação de lá), o dono sem o TermoVision, e o TermoVision não pede a si
    assert http.post(url, headers=_h(g, sistema="meuplano", ip="200.1.1.1")).status_code == 404
    assert http.post(url, headers=_h(c["dono"], ip="200.1.1.1")).status_code == 404
    assert http.post(url, headers=_h(g, sistema="termovision", ip="200.1.1.1")).status_code == 403


def test_os_objetos_do_mapa_para_o_importar_do_termovision(http, cenario, db, monkeypatch):
    import httpx

    from app.services import vinculos
    c, g = cenario, cenario["gerente"]
    db.add(AcessoGS(gs_user_id=g.id, login=g.apelido, acao="passe", sistema="termovision", ok=True, ip="200.1.1.1",
                    em=datetime.now(UTC)))
    db.commit()
    estado = {"mapa": {"objetos": [
        {"id": 41, "tipo": "string", "nome": "U1-3S22", "geometria": {"type": "Polygon", "coordinates": []},
         "origem": "asbuilt:of1-r03:U1-3S22", "slot_id": 5, "string_number": 22, "transformer_id": 3,
         "atualizado_em": "2026-11-18T20:00:00+00:00"},
        {"id": 42, "tipo": "camera", "nome": "Câmera 01", "geometria": {"type": "Point", "coordinates": [-46.5, -22.2]},
         "origem": "meuplano:node:345"}]}}

    class MW:
        async def mapa(self, slug):
            assert slug == "ibitinga"
            if isinstance(estado["mapa"], Exception):
                raise estado["mapa"]
            return estado["mapa"]

        async def slots(self, slug):
            return [{"id": 5, "label": "Inv 13", "position": 13}]

    class MP:
        async def mapa_da_usina(self, mp_id):
            assert mp_id == 7
            return {"objetos": [{"id": 42, "node_id": 345}], "aviso": None}

    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda db, uid, **k: MW())
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db, uid, **k: MP())
    url = f"/api/v1/interno/usinas/{c['ib'].id}/mapa/objetos"
    r = http.get(url, headers=_h(g, sistema="termovision"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["usina"] == {"gs": c["ib"].id, "codigo": f"GS-{c['ib'].id:04d}", "nome": "Ibitinga",
                          "meuwatt": {"slug": "ibitinga"}}
    assert j["lido_em"].endswith("-03:00") and j["avisos"] == []
    s, cam = j["objetos"]
    assert s == {"id": "41", "tipo": "string", "nome": "U1-3S22", "geometria": {"type": "Polygon", "coordinates": []},
                 "origem": "asbuilt:of1-r03:U1-3S22",
                 "refs": {"meuwatt": {"id": 41, "slug": "ibitinga", "slot_id": 5, "inversor": "Inv 13", "entrada": 22,
                                      "transformer_id": 3}, "meuplano": None},
                 "atualizado_em": "2026-11-18T20:00:00+00:00"}
    assert cam["refs"]["meuplano"] == {"node": 345} and cam["refs"]["meuwatt"]["inversor"] is None
    # sem o meuWatt é erro, nunca uma lista vazia; a usina sem o meuWatt diz por quê; a de fora e o dono não leem
    estado["mapa"] = httpx.ConnectError("fora")
    r = http.get(url, headers=_h(g, sistema="termovision"))
    assert r.status_code == 502 and "não respondeu" in r.json()["detail"]
    sem_mw = PlantLink(nome="Só no meuPlano", empresa_id=c["a"].id, mp_usina_id=8)
    db.add(sem_mw)
    db.commit()
    r = http.get(f"/api/v1/interno/usinas/{sem_mw.id}/mapa/objetos", headers=_h(g, sistema="termovision"))
    assert r.status_code == 200 and r.json()["objetos"] == [] and "não está ligada ao meuWatt" in r.json()["avisos"][0]
    assert http.get(f"/api/v1/interno/usinas/{c['de_b'].id}/mapa/objetos",
                    headers=_h(g, sistema="termovision")).status_code == 404
    c["dono"].termovision_liberado = True
    db.commit()
    assert http.get(url, headers=_h(c["dono"], sistema="termovision")).status_code == 403   # o dono não importa


def test_o_mapa_embutido_le_pela_sessao_do_passe_tambem_o_dono(http, cenario, db, monkeypatch):
    """Fase 1 do mapa novo ("libere", o Renan em 25/11/2026): com a sessão do passe do TermoVision, lê quem vê a usina
    na lista do GS — o dono, as dele; a O&M, as da empresa. Sem a sessão, a régua do Importar (o dono leva 403)."""
    from app.core.security import criar_token_sistema
    from app.services import vinculos
    c, dono, g = cenario, cenario["dono"], cenario["gerente"]
    dono.termovision_liberado = True
    db.commit()
    lidos = []

    class MW:
        async def mapa(self, slug):
            lidos.append(slug)
            return {"objetos": [{"id": 7, "tipo": "string", "nome": "U1-1S01", "geometria": None}]}

        async def slots(self, slug):
            return []

    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda db, uid, **k: MW())
    url = f"/api/v1/interno/usinas/{c['of'].id}/mapa/objetos"
    sessao = {"X-Sessao-GS": criar_token_sistema(dono.id, "termovision")}
    r = http.get(url, headers={**_h(dono, sistema="termovision"), **sessao})
    assert r.status_code == 200 and [o["nome"] for o in r.json()["objetos"]] == ["U1-1S01"] and lidos == ["ouro-fino"]
    assert http.get(url, headers=_h(dono, sistema="termovision")).status_code == 403          # sem a sessão: Importar
    assert http.get(f"/api/v1/interno/usinas/{c['ib'].id}/mapa/objetos",                     # não é dele
                    headers={**_h(dono, sistema="termovision"), **sessao}).status_code == 404
    assert http.get(url, headers={**_h(dono, sistema="termovision"),                          # sessão de outro sistema
                                  "X-Sessao-GS": criar_token_sistema(dono.id, "meuwatt")}).status_code == 404
    r = http.get(f"/api/v1/interno/usinas/{c['ib'].id}/mapa/objetos",
                 headers={**_h(g, sistema="termovision", empresa=c["a"].id),
                          "X-Sessao-GS": criar_token_sistema(g.id, "termovision")})
    assert r.status_code == 200 and lidos[-1] == "ibitinga"                                     # a O&M, a da empresa
    leitura = db.query(AcessoGS).filter(AcessoGS.gs_user_id == dono.id, AcessoGS.acao == "leitura",
                                        AcessoGS.motivo.contains(f"GS-{c['of'].id:04d}")).one()
    assert leitura.sistema == "termovision" and "sem a sessão" not in leitura.motivo


def test_a_chave_sozinha_nao_fala_por_ninguem(http, cenario, db):
    """Sem a sessão do passe (`X-Sessao-GS`), só quem entrou pelo GS nos últimos 60 dias; com ela, só a sessão DELA
    neste sistema, e encerrar as sessões no GS a encerra aqui também."""
    from app.core.security import criar_token_sistema
    from app.models.acesso import AcessoGS as A
    from app.services import sessoes
    c, g, adm = cenario, cenario["gerente"], cenario["adm"]
    db.query(A).filter(A.gs_user_id == adm.id).update({"em": datetime.now(UTC) - timedelta(days=61)})
    db.commit()
    assert http.get("/api/v1/interno/usinas", headers=_h(adm)).status_code == 404          # sumido há 61 dias
    sessao_adm = criar_token_sistema(adm.id, "meuguarda")
    assert http.get("/api/v1/interno/usinas", headers={**_h(adm), "X-Sessao-GS": sessao_adm}).status_code == 200
    # a renovação devolve um `sessao_gs` novo, da MESMA sessão, com 60 dias a contar de agora (o meuPlano, 24/11)
    from jose import jwt as _jwt

    from app.core.config import get_settings as _gs
    r = http.get("/api/v1/interno/usinas-da-pessoa", headers={**_h(adm), "X-Sessao-GS": sessao_adm})
    nova = r.json()["sessao_gs"]
    velho, novo = (_jwt.decode(t, _gs().gs_jwt_secret, algorithms=["HS256"]) for t in (sessao_adm, nova))
    assert novo["sid"] == velho["sid"] and novo["exp"] >= velho["exp"] and novo["escopo"] == "sistema:meuguarda"
    assert http.get("/api/v1/interno/usinas", headers={**_h(adm), "X-Sessao-GS": nova}).status_code == 200
    assert http.get("/api/v1/interno/usinas-da-pessoa", headers=_h(g)).json()["sessao_gs"] is None   # transição: nada
    for errada in (criar_token_sistema(adm.id, "meuwatt"), criar_token_sistema(g.id, "meuguarda"), "lixo"):
        assert http.get("/api/v1/interno/usinas", headers={**_h(adm), "X-Sessao-GS": errada}).status_code == 404
    sessoes.encerrar_todas(db, adm, por=None, motivo="teste")
    db.commit()
    for t in (sessao_adm, nova):                                                 # a renovada cai junto
        assert http.get("/api/v1/interno/usinas", headers={**_h(adm), "X-Sessao-GS": t}).status_code == 404
    # e a TRANSIÇÃO (sem `X-Sessao-GS`, o caminho de hoje): a entrada de antes do "encerrar todas" não fala mais
    assert http.get("/api/v1/interno/usinas", headers=_h(g)).status_code == 200
    import time as _t
    _t.sleep(1.1)                                          # a marca é em segundos
    sessoes.encerrar_todas(db, g, por=None, motivo="teste")
    db.commit()
    assert http.get("/api/v1/interno/usinas", headers=_h(g)).status_code == 404
    leituras = [a for a in db.query(A).filter(A.acao == "leitura", A.gs_user_id == adm.id) if "renovação" not in a.motivo]
    assert len(leituras) == 1 and "as usinas" in leituras[0].motivo                         # uma por hora


def test_os_itens_do_mapa_para_o_termovision_por_mover_e_tirar(http, cenario, db, monkeypatch):
    """Fase 2 do mapa novo (o Renan, 25/11/2026: "arrastar os inversores e transformadores para a planta" e "marcar a
    subestação e a posição dos relés"): a lista de tudo o que existe na usina, e pôr, mover e tirar com o "antes" (o
    meuWatt confere e devolve 409; a mesma geometria de novo é 200 sem mudar). Ler é de quem vê; editar, da O&M."""
    import httpx

    from app.core.security import criar_token_sistema
    from app.services import vinculos
    c, g, dono = cenario, cenario["gerente"], cenario["dono"]
    dono.termovision_liberado = True
    db.commit()
    ponto, area = {"type": "Point", "coordinates": [-48.8, -21.7]}, \
        {"type": "Polygon", "coordinates": [[[-48.8, -21.7], [-48.79, -21.7], [-48.79, -21.69], [-48.8, -21.7]]]}

    def erro(codigo, corpo):
        return httpx.HTTPStatusError("x", request=httpx.Request("PATCH", "http://mw"),
                                     response=httpx.Response(codigo, json=corpo))

    class MW:
        def __init__(self):
            self.proximo, self.objetos = 100, [
                {"id": 41, "tipo": "string", "nome": "U1-3S22", "geometria": area, "slot_id": None},
                {"id": 42, "tipo": "transformador", "nome": "TR-01", "geometria": ponto, "transformer_id": 3,
                 "atualizado_em": "2026-11-25T18:00:00+00:00", "atualizado_por": {"id": 8, "nome": "Renan"}},
                {"id": 43, "tipo": "camera", "nome": "Câmera 01", "geometria": ponto}]

        async def mapa_equipamentos(self, slug):
            return {"transformadores": [{"id": 3, "nome": "TR-01", "kva": 1250}],
                    "vagas": [{"slot_id": 5, "rotulo": "Inv 13", "posicao": 13, "transformer_id": 3,
                               "inversor": {"sn": "SN13", "modelo": "SUN2000"}, "strings": [1, 2]}],
                    "reles": [{"relay_id": 9, "nome": "URP6000 TR-01", "transformer_id": 3},
                              {"relay_id": 10, "nome": "URP Geral", "transformer_id": None}]}

        async def mapa(self, slug):
            return {"objetos": [dict(o) for o in self.objetos]}

        def _o(self, oid):
            o = next((x for x in self.objetos if x["id"] == oid), None)
            if o is None:
                raise erro(404, {"detail": "não existe"})
            return o

        async def mapa_criar(self, slug, objeto):
            if any(x.get("origem") == objeto.get("origem") for x in self.objetos):
                raise erro(409, {"detail": "origem repetida"})
            self.proximo += 1
            self.objetos.append({**objeto, "id": self.proximo})

        async def mapa_alterar(self, slug, oid, campos):
            o = self._o(oid)
            if o["geometria"] == campos["geometria"]:
                return
            if campos.get("antes") is not None and o["geometria"] != campos["antes"]:
                raise erro(409, {"detail": "mexeram", "objeto": o})
            o["geometria"] = campos["geometria"]

        async def mapa_apagar(self, slug, oid, antes=None):
            o = self._o(oid)
            if antes is not None and o["geometria"] != antes:
                raise erro(409, {"detail": "mexeram", "objeto": o})
            self.objetos.remove(o)

    mw = MW()
    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda db, uid, **k: mw)
    url = f"/api/v1/interno/usinas/{c['ib'].id}/mapa/itens"
    h = {**_h(g, sistema="termovision", empresa=c["a"].id), "X-Sessao-GS": criar_token_sistema(g.id, "termovision")}
    j = http.get(url, headers=h).json()
    assert j["pode_editar"] is True and j["lido_em"].endswith("-03:00")
    por = {i["ref"]: i for i in j["itens"]}
    assert set(por) == {"trafo:3", "inv:5", "str:5:1", "str:5:2", "rele:9", "rele:10", "obj:41"}   # a câmera não é item
    assert por["trafo:3"] == {"ref": "trafo:3", "tipo": "transformador", "nome": "TR-01", "pai": None,
                              "detalhe": "1.250 kVA", "geometria": ponto, "meuwatt": {"objeto": 42, "transformer_id": 3},
                              "alterado_por": "Renan", "alterado_em": "2026-11-25T18:00:00+00:00"}
    assert (por["inv:5"]["pai"], por["inv:5"]["detalhe"], por["inv:5"]["geometria"]) == ("trafo:3", "SUN2000 · SN13", None)
    assert por["str:5:2"]["pai"] == "inv:5" and por["str:5:2"]["meuwatt"] == {"objeto": None, "slot_id": 5, "string_number": 2}
    assert (por["rele:9"]["pai"], por["rele:10"]["pai"], por["rele:10"]["detalhe"]) == ("trafo:3", None, "Geral")
    assert por["obj:41"]["tipo"] == "string" and por["obj:41"]["geometria"] == area             # o as-built solto

    # pôr o inversor no mapa, e o mesmo pedido de novo não cria outro
    for _ in range(2):
        r = http.put(f"{url}/inv:5", headers=h, json={"geometria": ponto, "antes": None})
        assert r.status_code == 200 and r.json()["item"]["geometria"] == ponto
    criados = [o for o in mw.objetos if o.get("origem") == "gs-item:inv:5"]
    assert len(criados) == 1 and criados[0]["slot_id"] == 5 and criados[0]["tipo"] == "inversor"
    # mover com o "antes" certo; com o "antes" velho, 409 com o item como está
    longe = {"type": "Point", "coordinates": [-48.7, -21.6]}
    assert http.put(f"{url}/trafo:3", headers=h, json={"geometria": longe, "antes": ponto}).json()["item"]["geometria"] == longe
    r = http.put(f"{url}/trafo:3", headers=h, json={"geometria": ponto, "antes": ponto})
    assert r.status_code == 409 and r.json()["item"]["geometria"] == longe
    r = http.put(f"{url}/trafo:3", headers=h, json={"geometria": ponto, "antes": None})   # a tela o viu fora do mapa
    assert r.status_code == 409
    # a forma de cada tipo, o ref que não existe e a subestação nova (idempotente pelo ref)
    assert http.put(f"{url}/str:5:1", headers=h, json={"geometria": ponto}).status_code == 400
    assert http.put(f"{url}/inv:999", headers=h, json={"geometria": ponto}).status_code == 404
    assert http.put(f"{url}/novo:abc", headers=h, json={"geometria": area}).status_code == 400       # sem tipo e nome
    for _ in range(2):
        r = http.put(f"{url}/novo:abc", headers=h, json={"geometria": area, "tipo": "subestacao", "nome": "Subestação"})
        assert r.status_code == 200 and r.json()["item"]["ref"] == "novo:abc"
    assert len([o for o in mw.objetos if o.get("origem") == "gs-item:novo:abc"]) == 1
    # tirar: com o "antes" velho, 409; certo, sai (a subestação some da lista); de novo, 200
    assert http.request("DELETE", f"{url}/inv:5", headers=h, json={"antes": longe}).status_code == 409
    r = http.request("DELETE", f"{url}/inv:5", headers=h, json={"antes": ponto})
    assert r.status_code == 200 and r.json()["item"]["geometria"] is None                  # volta à lista sem posição
    r = http.put(f"{url}/inv:5", headers=h, json={"geometria": longe, "antes": ponto})     # a tela o via no mapa
    assert r.status_code == 409 and r.json()["item"]["geometria"] is None
    for _ in range(2):
        r = http.request("DELETE", f"{url}/novo:abc", headers=h, json={"antes": area})
        assert r.status_code == 200 and r.json()["item"] is None
    # o dono lê (a usina dele) e não edita
    hd = {**_h(dono, sistema="termovision"), "X-Sessao-GS": criar_token_sistema(dono.id, "termovision")}
    url_dono = f"/api/v1/interno/usinas/{c['of'].id}/mapa/itens"
    assert http.get(url_dono, headers=hd).json()["pode_editar"] is False
    assert http.put(f"{url_dono}/inv:5", headers=hd, json={"geometria": ponto}).status_code == 403
    assert http.get(url, headers=hd).status_code == 404                                    # Ibitinga não é dele
