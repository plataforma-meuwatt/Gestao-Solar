"""O MAPA ÚNICO da usina (gestao.solar/mapa/<usina>; o dono, 18/11/2026: "todos usam o mesmo … o meuGuarda só consome
o mapa"; escolheu a O&M editando e o dono da usina só vendo).

O que não pode acontecer: o dono ou a O&M abrir a usina de outra empresa pelo id; o dono marcar no mapa; a escrita sair
com outro token que não o PESSOAL de quem marca; o meuPlano fora virar um mapa vazio que parece certo."""
import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1 import mapa as rotas
from app.core.security import criar_token, criar_token_empresa, criar_token_tecnico, gerar_hash_senha
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess, VinculoProduto
from app.services import vinculos


class _MeuPlano:
    def __init__(self, token):
        self.token, self.marcados, self.falha = token, [], None

    async def mapa_da_usina(self, usina_id):
        if self.falha:
            raise self.falha
        return {"usina": {"id": usina_id}, "vinculado": True, "orto": None, "aviso": None, "slug": "pereiras",
                "objetos": [{"id": 1, "tipo": "outro", "nome": "Câmera 01", "node_id": 71, "geometria": {
                    "type": "Point", "coordinates": [-47.99, -23.2]}}]}

    async def equipamento_pelo_nome(self, usina_id, nome):
        return {"achados": [{"node_id": 71, "nome": "Câmera 01"}], "parecidos": []}

    async def marcar_no_mapa(self, usina_id, node_id, lat, lng, novo_nome=None, apelido=None):
        if self.falha:
            raise self.falha
        self.marcados.append((usina_id, node_id, lat, lng))
        return {"ok": True, "avisos": []}


class _MeuWatt:
    """O mapa do monitoramento simulado: o objeto 1 é ponto de equipamento da manutenção, o 2 veio do voo, o 3 é desenho."""

    def __init__(self, token):
        self.token, self.criados, self.alterados, self.apagados = token, [], [], []
        self.estado, self.ignora_forma = None, False
        self.objetos = [{"id": 1, "tipo": "outro", "origem": "meuplano:node:71"},
                        {"id": 2, "tipo": "mesa", "origem": "termovision:mesa:1"},
                        {"id": 3, "tipo": "string", "nome": "S12", "origem": None, "slot_id": 7, "string_number": 12,
                         "geometria": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}}]

    async def mapa(self, slug):
        return {"objetos": self.objetos}

    async def mapa_estado(self, slug):
        if self.estado is None:
            req = httpx.Request("GET", "http://mw")
            raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(404, request=req))
        return self.estado

    async def strings_por_vaga(self, slug):
        return {"inverters": [{"slot_id": 7, "label": "Inv 03", "transformer_name": "TR-01",
                               "strings": [{"number": 12}, {"number": 13}]},
                              {"slot_id": None, "label": "sem vaga", "strings": [{"number": 1}]}]}

    async def slots(self, slug):
        return [{"id": 7, "transformer_id": 3, "label": "Inv 03", "ip_address": "10.0.0.9"}]

    async def mapa_criar(self, slug, objeto):
        self.criados.append((slug, objeto))
        return {"criados": 1}

    async def mapa_alterar(self, slug, objeto_id, campos):
        self.alterados.append((slug, objeto_id, campos))
        o = next(x for x in self.objetos if x["id"] == objeto_id)          # grava (o próximo GET vê)
        o.update({k: v for k, v in campos.items() if not (k == "geometria" and self.ignora_forma)})
        return dict(o)

    async def mapa_apagar(self, slug, objeto_id):
        self.apagados.append((slug, objeto_id))


def _recusa(codigo, frase):
    req = httpx.Request("POST", "http://meuplano")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(codigo, json={"detail": frase}, request=req))


@pytest.fixture
def cenario(db, monkeypatch):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    pereiras = PlantLink(nome="UFV Pereiras", empresa_id=a.id, mp_usina_id=4, mw_plant_slug="pereiras")
    tiete = PlantLink(nome="UFV Tietê", empresa_id=a.id, mp_usina_id=5)
    vizinha = PlantLink(nome="Usina da B", empresa_id=b.id, mp_usina_id=9)
    db.add_all([pereiras, tiete, vizinha])
    db.commit()

    def conta(apelido, perfil, token_mp=False, token_mw=False):
        u = User(apelido=apelido, nome=apelido.title(), perfil=perfil, empresa_id=a.id,
                 senha_hash=gerar_hash_senha("senha-1234"))
        db.add(u)
        db.commit()
        if token_mp:
            db.add(VinculoProduto(gs_user_id=u.id, produto="meuplano", usuario_remoto_id="9", token_cifrado="x"))
        if token_mw:
            db.add(VinculoProduto(gs_user_id=u.id, produto="meuwatt", usuario_remoto_id="9", token_cifrado="x"))
        db.commit()
        return u
    gerente = conta("gerente.a", Perfil.GESTOR_EMPRESA, token_mp=True, token_mw=True)
    so_mp = conta("gerente.b", Perfil.GESTOR_EMPRESA, token_mp=True)
    tecnico = conta("tecnico.a", Perfil.TECNICO)
    dono = conta("dono.a", Perfil.CLIENTE)
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=pereiras.id))
    db.commit()
    clientes = {}

    def cliente_meuplano(db_, uid, so_proprio=False):
        clientes.setdefault((uid, so_proprio), _MeuPlano(f"token-de-{uid}"))
        return clientes[(uid, so_proprio)]
    monkeypatch.setattr(vinculos, "cliente_meuplano", cliente_meuplano)
    mw = {}

    def cliente_meuwatt(db_, uid, so_proprio=False):
        mw.setdefault((uid, so_proprio), _MeuWatt(f"token-mw-de-{uid}"))
        return mw[(uid, so_proprio)]
    monkeypatch.setattr(vinculos, "cliente_meuwatt", cliente_meuwatt)
    return dict(gerente=gerente, so_mp=so_mp, tecnico=tecnico, dono=dono, pereiras=pereiras, tiete=tiete,
                vizinha=vizinha, clientes=clientes, mw=mw)


def _cred(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_as_tres_sessoes_abrem_e_nenhuma_outra(db, cenario):
    c = cenario
    assert rotas.quem_abre(_cred(criar_token(c["dono"].id)[0]), db).id == c["dono"].id
    assert rotas.quem_abre(_cred(criar_token_empresa(c["gerente"].id)[0]), db).id == c["gerente"].id
    assert rotas.quem_abre(_cred(criar_token_tecnico(c["tecnico"].id)[0]), db).id == c["tecnico"].id
    for ruim in (None, _cred("lixo")):
        with pytest.raises(HTTPException) as e:
            rotas.quem_abre(ruim, db)
        assert e.value.status_code == 401


async def test_cada_um_ve_as_suas_e_a_usina_de_fora_e_404(db, cenario):
    c = cenario
    assert {u.id for u in rotas.listar(db, c["gerente"])} == {c["pereiras"].id, c["tiete"].id}
    assert {u.id for u in rotas.listar(db, c["tecnico"])} == {c["pereiras"].id, c["tiete"].id}
    assert {u.id for u in rotas.listar(db, c["dono"])} == {c["pereiras"].id}
    for quem, usina in ((c["dono"], c["tiete"]), (c["gerente"], c["vizinha"])):
        with pytest.raises(HTTPException) as e:
            await rotas.mapa_da_usina(usina.id, db, quem)
        assert e.value.status_code == 404 and "não encontrada" in e.value.detail


async def test_o_mapa_vem_do_meuplano_e_so_a_om_com_token_edita(db, cenario):
    c = cenario
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["dono"])
    assert r["mapa"]["objetos"][0]["node_id"] == 71 and r["pode_editar"] is False and "O&M" in r["por_que_nao_edita"]
    assert (c["dono"].id, False) in c["clientes"]           # o token da pessoa (senão o da empresa): a régua do portal
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert r["pode_editar"] is True and r["por_que_nao_edita"] is None
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["tecnico"])
    assert r["pode_editar"] is False and "token do sistema de manutenção" in r["por_que_nao_edita"]
    # o meuPlano fora vira aviso, não mapa vazio
    c["clientes"][(c["gerente"].id, False)].falha = httpx.ConnectError("x")
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert r["mapa"] is None and "não respondeu" in r["aviso"]


async def test_marcar_e_da_om_com_o_token_pessoal(db, cenario):
    c = cenario
    with pytest.raises(HTTPException) as e:
        await rotas.marcar(c["pereiras"].id, rotas.PontoIn(node_id=71, lat=-23.2, lng=-47.99), db, c["dono"])
    assert e.value.status_code == 403
    r = await rotas.marcar(c["pereiras"].id, rotas.PontoIn(node_id=71, lat=-23.2, lng=-47.99), db, c["gerente"])
    assert r["ok"] and c["clientes"][(c["gerente"].id, True)].marcados == [(4, 71, -23.2, -47.99)]
    # a recusa do meuPlano (a permissão de lá, o desenhado como área) chega com a frase de lá
    c["clientes"][(c["gerente"].id, True)].falha = _recusa(409, "'Inversor 03' já está desenhado como área no mapa")
    with pytest.raises(HTTPException) as e:
        await rotas.marcar(c["pereiras"].id, rotas.PontoIn(node_id=51, lat=-23.2, lng=-47.99), db, c["gerente"])
    assert e.value.status_code == 409 and "desenhado como área" in e.value.detail
    achados = await rotas.equipamentos(c["pereiras"].id, "câmera 1", db, c["gerente"])
    assert achados["achados"][0]["node_id"] == 71


async def test_o_meuguarda_le_as_posicoes_com_a_chave_e_o_recorte_da_pessoa(db, cenario, monkeypatch):
    """A porta interna do meuGuarda: sem a chave configurada recusa tudo; com a chave errada, 401; a pessoa sem o
    meuGuarda ou a usina fora das dela, 404; o mapa fora do ar é 502 (nunca uma lista vazia que parece certa); e só
    saem as câmeras ligadas ao meuGuarda, com a posição."""
    from app.api.v1 import interno_meuguarda as interno
    from app.core.config import get_settings
    c = cenario
    with pytest.raises(HTTPException) as e:
        interno._porta("qualquer")
    assert e.value.status_code == 503
    monkeypatch.setattr(get_settings(), "meuguarda_chave_interna", "chave-certa")
    with pytest.raises(HTTPException) as e:
        interno._porta("chave-errada")
    assert e.value.status_code == 401
    interno._porta("chave-certa")

    with pytest.raises(HTTPException) as e:                 # o dono sem o meuGuarda liberado
        await interno.posicoes(c["pereiras"].id, "dono.a", db)
    nao = e.value.detail
    assert e.value.status_code == 404
    c["dono"].meuguarda_liberado = True
    db.commit()
    with pytest.raises(HTTPException) as e:                 # a usina que não é dele: a MESMA resposta (não enumera)
        await interno.posicoes(c["tiete"].id, "dono.a", db)
    assert e.value.status_code == 404 and e.value.detail == nao

    async def mapa_com_cameras(usina_id):
        return {"aviso": None, "objetos": [
            {"id": 1, "nome": "Câmera 01", "node_id": 71, "node_nome": "Câmera 01", "mg_camera_id": 501,
             "geometria": {"type": "Point", "coordinates": [-47.99, -23.2]}},
            {"id": 2, "nome": "Inversor 03", "node_id": 51, "mg_camera_id": None,
             "geometria": {"type": "Point", "coordinates": [-47.98, -23.21]}},
            {"id": 3, "nome": "Câmera da cerca", "node_id": 72, "mg_camera_id": 502, "geometria": {"type": "LineString",
             "coordinates": [[-47.9, -23.2], [-47.91, -23.2]]}}]}
    monkeypatch.setattr(_MeuPlano, "mapa_da_usina", lambda self, uid: mapa_com_cameras(uid))
    r = await interno.posicoes(c["pereiras"].id, " Dono.A ", db)
    assert r["cameras"] == [{"mg_camera_id": 501, "nome": "Câmera 01", "lat": -23.2, "lng": -47.99, "sem_posicao": None},
                            {"mg_camera_id": 502, "nome": "Câmera da cerca", "lat": None, "lng": None,
                             "sem_posicao": "desenhada como linha"}]   # nunca some calada
    assert r["usina"]["id"] == c["pereiras"].id and r["lido_em"]

    # a empresa desativada para de ler (como nas sessões do GS)
    from app.models.empresa import Empresa
    emp = db.get(Empresa, c["pereiras"].empresa_id)
    emp.ativa = False
    db.commit()
    with pytest.raises(HTTPException) as e:
        await interno.posicoes(c["pereiras"].id, "dono.a", db)
    assert e.value.status_code == 404
    emp.ativa = True
    db.commit()

    # usina sem mapa ligado: é dito (409), não "nenhuma câmera"
    async def sem_mapa(usina_id):
        return {"vinculado": False, "objetos": [], "aviso": None}
    monkeypatch.setattr(_MeuPlano, "mapa_da_usina", lambda self, uid: sem_mapa(uid))
    with pytest.raises(HTTPException) as e:
        await interno.posicoes(c["pereiras"].id, "dono.a", db)
    assert e.value.status_code == 409

    async def fora(usina_id):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(_MeuPlano, "mapa_da_usina", lambda self, uid: fora(uid))
    with pytest.raises(HTTPException) as e:
        await interno.posicoes(c["pereiras"].id, "dono.a", db)
    assert e.value.status_code in (502, 503, 504)



async def test_cada_camada_com_a_permissao_dela_e_o_estado_nunca_inventado(db, cenario):
    c = cenario
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["dono"])
    assert r["edicao"]["monitoramento"] and r["edicao"]["manutencao"]                     # o dono vê
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["so_mp"])
    assert r["edicao"]["manutencao"] is None and "token do monitoramento" in r["edicao"]["monitoramento"]
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert r["edicao"] == {"monitoramento": None, "manutencao": None}
    # o estado: sem a rota (404) → nada pintado, e a frase diz; com ela, por objeto
    assert r["estado"] is None and "ainda não está disponível" in r["estado_aviso"] and r["mapa_completo"] is False
    c["mw"][(c["gerente"].id, False)].estado = {"lido_em": "2026-11-18T19:30:00Z", "objetos": [
        {"objeto_id": 1, "estado": "alarme", "motivo": "isolação baixa"}, {"objeto_id": "x"}]}
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert r["estado"]["objetos"] == {1: {"estado": "alarme", "motivo": "isolação baixa", "desde": None, "leitura_em": None,
                                          "equipamento": None, "conhecido": None}}
    assert r["estado"]["lido_em"] == "2026-11-18T19:30:00Z" and r["estado_aviso"] is None and r["mapa_completo"] is True


async def test_desenhar_e_editar_a_camada_do_monitoramento_como_a_pessoa(db, cenario):
    c = cenario
    linha = {"type": "LineString", "coordinates": [[-47.99, -23.2], [-47.98, -23.2]]}
    for quem, frase in ((c["dono"], "O&M"), (c["so_mp"], "token do monitoramento")):
        with pytest.raises(HTTPException) as e:
            await rotas.desenhar(c["pereiras"].id, rotas.ObjetoNovoIn(tipo="string", geometria=linha), db, quem)
        assert e.value.status_code == 403 and frase in e.value.detail
    with pytest.raises(HTTPException) as e:
        await rotas.desenhar(c["pereiras"].id, rotas.ObjetoNovoIn(tipo="camera", geometria=linha), db, c["gerente"])
    assert e.value.status_code == 400
    await rotas.desenhar(c["pereiras"].id, rotas.ObjetoNovoIn(tipo="string", nome=" S13 ", geometria=linha), db, c["gerente"])
    proprio = c["mw"][(c["gerente"].id, True)]                                  # o token PRÓPRIO de quem desenha
    assert proprio.criados == [("pereiras", {"tipo": "string", "nome": "S13", "geometria": linha})]

    # o ponto do equipamento da manutenção move pelo Marcar; a forma do que veio do voo não muda aqui
    with pytest.raises(HTTPException) as e:
        await rotas.alterar(c["pereiras"].id, 1, rotas.ObjetoPatchIn(nome="x"), db, c["gerente"])
    assert e.value.status_code == 409 and "Mover" in e.value.detail
    with pytest.raises(HTTPException) as e:
        await rotas.alterar(c["pereiras"].id, 2, rotas.ObjetoPatchIn(geometria=linha), db, c["gerente"])
    assert e.value.status_code == 409 and "voo" in e.value.detail
    assert (await rotas.alterar(c["pereiras"].id, 2, rotas.ObjetoPatchIn(nome="Mesa 1"), db, c["gerente"]))["nome"] == "Mesa 1"
    # a posição que o monitoramento ignora NÃO vira "gravado"
    proprio.ignora_forma = True
    with pytest.raises(HTTPException) as e:
        await rotas.alterar(c["pereiras"].id, 3, rotas.ObjetoPatchIn(geometria=linha), db, c["gerente"])
    assert e.value.status_code == 409 and "a nova posição" in e.value.detail
    proprio.ignora_forma = False
    assert (await rotas.alterar(c["pereiras"].id, 3, rotas.ObjetoPatchIn(geometria=linha), db, c["gerente"]))["geometria"] == linha
    with pytest.raises(HTTPException) as e:
        await rotas.alterar(c["pereiras"].id, 99, rotas.ObjetoPatchIn(nome="x"), db, c["gerente"])
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await rotas.apagar(c["pereiras"].id, 1, db, c["gerente"])
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:                                  # o que veio do voo voltaria na importação
        await rotas.apagar(c["pereiras"].id, 2, db, c["gerente"])
    assert e.value.status_code == 409 and "voo" in e.value.detail
    await rotas.apagar(c["pereiras"].id, 3, db, c["gerente"])
    assert proprio.apagados == [("pereiras", 3)]



async def test_ligar_o_desenho_ao_equipamento_e_o_desenho_so_com_numeros(db, cenario):
    c = cenario
    v = await rotas.ligacoes(c["pereiras"].id, db, c["dono"])           # ler as vagas: quem vê o mapa
    assert v == {"vagas": [{"slot_id": 7, "rotulo": "Inv 03", "trafo": "TR-01", "transformer_id": 3, "strings": [12, 13]}],
                 "trafos": [{"transformer_id": 3, "nome": "TR-01"}], "trafos_aviso": None}
    assert "10.0.0.9" not in str(v)                                        # o IP da vaga não sai daqui
    # a ligação vai no PATCH (e nula = soltar); o tipo que não cabe na ligação é recusado antes de soltá-la calado
    r = await rotas.alterar(c["pereiras"].id, 3, rotas.ObjetoPatchIn(slot_id=7, string_number=13), db, c["gerente"])
    assert r["string_number"] == 13
    with pytest.raises(HTTPException) as e:
        await rotas.alterar(c["pereiras"].id, 3, rotas.ObjetoPatchIn(tipo="transformador"), db, c["gerente"])
    assert e.value.status_code == 409 and "solte a ligação" in e.value.detail
    r = await rotas.alterar(c["pereiras"].id, 3, rotas.ObjetoPatchIn(slot_id=None, string_number=None), db, c["gerente"])
    proprio = c["mw"][(c["gerente"].id, True)]
    assert proprio.alterados[-1][2] == {"slot_id": None, "string_number": None}
    assert (await rotas.alterar(c["pereiras"].id, 3, rotas.ObjetoPatchIn(tipo="transformador"), db, c["gerente"]))["tipo"] \
        == "transformador"
    # o desenho: só números (nada além vai ao banco); bool não é número
    for ruim in ({"type": "Point", "coordinates": [True, False]}, {"type": "Point", "coordinates": [float("nan"), 1.0]},
                 {"type": "Point", "coordinates": [10 ** 400, 1]},
                 {"type": "LineString", "coordinates": [[1, 2, "x" * 100], [3, 4]]},
                 {"type": "Polygon", "coordinates": "x"}):
        with pytest.raises(HTTPException) as e:
            await rotas.desenhar(c["pereiras"].id, rotas.ObjetoNovoIn(tipo="string", geometria=ruim), db, c["gerente"])
        assert e.value.status_code == 400
    await rotas.desenhar(c["pereiras"].id, rotas.ObjetoNovoIn(tipo="string", slot_id=7, string_number=12,
                         geometria={"type": "Point", "coordinates": [-48, -23]}), db, c["gerente"])
    assert proprio.criados[-1][1] == {"tipo": "string", "nome": None, "slot_id": 7, "string_number": 12,
                                      "geometria": {"type": "Point", "coordinates": [-48.0, -23.0]}}



async def test_desenhar_so_com_o_mapa_lido_e_o_monitoramento_da_mesma_usina(db, cenario):
    c = cenario
    # o mapa da manutenção fora do ar: nada de "Desenhar" (o desenho sumiria da tela)
    c["clientes"].setdefault((c["gerente"].id, False), _MeuPlano("t")).falha = httpx.ConnectError("x")
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert r["mapa"] is None and r["edicao"]["monitoramento"]
    c["clientes"][(c["gerente"].id, False)].falha = None
    # a usina ligada a OUTRA usina do monitoramento do que o mapa lido: também não
    c["pereiras"].mw_plant_slug = "outra"
    db.commit()
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert "outra usina do monitoramento" in r["edicao"]["monitoramento"]
    c["pereiras"].mw_plant_slug = None
    db.commit()
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert "ainda não está ligado" in r["edicao"]["monitoramento"]
    c["pereiras"].mw_plant_slug = "pereiras"
    db.commit()
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert r["edicao"]["monitoramento"] is None
    # o monitoramento recusou a leitura (o mapa vem com aviso e sem objetos): desenhar também fica para depois
    async def com_aviso(usina_id):
        return {"usina": {"id": usina_id}, "vinculado": True, "slug": "pereiras", "objetos": [], "aviso": "recusou"}
    c["clientes"][(c["gerente"].id, False)].mapa_da_usina = com_aviso
    r = await rotas.mapa_da_usina(c["pereiras"].id, db, c["gerente"])
    assert "não foi lido" in r["edicao"]["monitoramento"]
