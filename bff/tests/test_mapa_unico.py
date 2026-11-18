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
        return {"usina": {"id": usina_id}, "vinculado": True, "orto": None, "aviso": None,
                "objetos": [{"id": 1, "tipo": "outro", "nome": "Câmera 01", "node_id": 71, "geometria": {
                    "type": "Point", "coordinates": [-47.99, -23.2]}}]}

    async def equipamento_pelo_nome(self, usina_id, nome):
        return {"achados": [{"node_id": 71, "nome": "Câmera 01"}], "parecidos": []}

    async def marcar_no_mapa(self, usina_id, node_id, lat, lng, novo_nome=None, apelido=None):
        if self.falha:
            raise self.falha
        self.marcados.append((usina_id, node_id, lat, lng))
        return {"ok": True, "avisos": []}


def _recusa(codigo, frase):
    req = httpx.Request("POST", "http://meuplano")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(codigo, json={"detail": frase}, request=req))


@pytest.fixture
def cenario(db, monkeypatch):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    pereiras = PlantLink(nome="UFV Pereiras", empresa_id=a.id, mp_usina_id=4)
    tiete = PlantLink(nome="UFV Tietê", empresa_id=a.id, mp_usina_id=5)
    vizinha = PlantLink(nome="Usina da B", empresa_id=b.id, mp_usina_id=9)
    db.add_all([pereiras, tiete, vizinha])
    db.commit()

    def conta(apelido, perfil, token_mp=False):
        u = User(apelido=apelido, nome=apelido.title(), perfil=perfil, empresa_id=a.id,
                 senha_hash=gerar_hash_senha("senha-1234"))
        db.add(u)
        db.commit()
        if token_mp:
            db.add(VinculoProduto(gs_user_id=u.id, produto="meuplano", usuario_remoto_id="9", token_cifrado="x"))
            db.commit()
        return u
    gerente = conta("gerente.a", Perfil.GESTOR_EMPRESA, token_mp=True)
    tecnico = conta("tecnico.a", Perfil.TECNICO)
    dono = conta("dono.a", Perfil.CLIENTE)
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=pereiras.id))
    db.commit()
    clientes = {}

    def cliente_meuplano(db_, uid, so_proprio=False):
        clientes.setdefault((uid, so_proprio), _MeuPlano(f"token-de-{uid}"))
        return clientes[(uid, so_proprio)]
    monkeypatch.setattr(vinculos, "cliente_meuplano", cliente_meuplano)
    return dict(gerente=gerente, tecnico=tecnico, dono=dono, pereiras=pereiras, tiete=tiete, vizinha=vizinha,
                clientes=clientes)


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
