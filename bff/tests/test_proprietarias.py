"""As proprietárias, as donas das usinas (Plano Casa GS, R11): o gerente cadastra e liga usinas e pessoas da empresa
dele; as pessoas da mesma proprietária dividem as usinas dela (sem ela, uma usina tem um dono só); "dar as usinas"
soma à concessão e nada sai; a importação do meuPlano só preenche; o passe e a porta dos sistemas dizem a dona."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api.v1 import empresa as rotas
from app.models.empresa import Empresa, Proprietaria
from app.models.plant import HistoricoDaUsina, PlantLink
from app.models.user import Perfil, User, UserPlantAccess, VinculoProduto
from app.services import clientes, proprietarias


@pytest.fixture
def c(db):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    of, pe, de_b = (PlantLink(nome="Ouro Fino", empresa_id=a.id, mp_usina_id=451),
                    PlantLink(nome="Pereiras", empresa_id=a.id, mp_usina_id=4),
                    PlantLink(nome="Da Outra", empresa_id=b.id))
    gerente = User(apelido="ger", nome="Gerente", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id)
    fernando = User(apelido="fernando", nome="Fernando", perfil=Perfil.CLIENTE, empresa_id=a.id)
    luiz = User(apelido="luiz", nome="Luiz", perfil=Perfil.CLIENTE, empresa_id=a.id)
    tecnico = User(apelido="tec", nome="Técnico", perfil=Perfil.TECNICO, empresa_id=a.id)
    dono_b = User(apelido="dono.b", nome="Dono B", perfil=Perfil.CLIENTE, empresa_id=b.id)
    db.add_all([of, pe, de_b, gerente, fernando, luiz, tecnico, dono_b])
    db.commit()
    db.add(UserPlantAccess(user_id=fernando.id, plant_link_id=of.id))
    db.commit()
    return dict(a=a, b=b, of=of, pe=pe, de_b=de_b, gerente=gerente, fernando=fernando, luiz=luiz, tecnico=tecnico,
                dono_b=dono_b)


def test_cadastro_usinas_pessoas_e_o_dono_unico_por_proprietaria(db, c):
    g = c["gerente"]
    with pytest.raises(clientes.RegraDeNegocio):                     # sem proprietária: um dono só
        clientes.definir_usinas(db, c["luiz"], [c["of"].id])
    p = rotas.criar_proprietaria(rotas.ProprietariaIn(nome="Eldorado Energia", documento="12.345.678/0001-90"), db, g)
    assert (p.nome, p.documento) == ("Eldorado Energia", "12345678000190")
    with pytest.raises(HTTPException) as e:
        rotas.criar_proprietaria(rotas.ProprietariaIn(nome="eldorado energia"), db, g)
    assert e.value.status_code == 400                                 # o mesmo nome na empresa
    with pytest.raises(HTTPException):
        rotas.criar_proprietaria(rotas.ProprietariaIn(nome="X", documento="123"), db, g)
    p = rotas.usinas_da_proprietaria(p.id, rotas.IdsIn(ids=[c["of"].id, c["pe"].id]), db, g)
    assert [u.nome for u in p.usinas] == ["Ouro Fino", "Pereiras"]
    assert ("proprietaria", None, "Eldorado Energia", "gs") in [
        (h.campo, h.antes, h.depois, h.sistema) for h in db.query(HistoricoDaUsina).filter_by(plant_link_id=c["of"].id)]
    for ids in ([c["de_b"].id],):                                     # a usina de outra empresa não entra
        with pytest.raises(HTTPException) as e:
            rotas.usinas_da_proprietaria(p.id, rotas.IdsIn(ids=ids), db, g)
        assert e.value.status_code == 400
    for ids in ([c["tecnico"].id], [c["dono_b"].id]):                 # só donos de usina desta empresa
        with pytest.raises(HTTPException):
            rotas.pessoas_da_proprietaria(p.id, rotas.IdsIn(ids=ids), db, g)
    p = rotas.pessoas_da_proprietaria(p.id, rotas.IdsIn(ids=[c["fernando"].id, c["luiz"].id]), db, g)
    assert [u.codigo for u in p.pessoas] == ["fernando", "luiz"]
    # da mesma proprietária: o Luiz recebe a usina do Fernando
    clientes.definir_usinas(db, c["luiz"], [c["of"].id])
    out = rotas.dar_usinas_da_proprietaria(p.id, db, g)
    assert out["pessoas"] == {"Fernando": 1, "Luiz": 1}               # a que faltava a cada um
    assert {a.plant_link_id for a in db.query(UserPlantAccess).filter_by(user_id=c["luiz"].id)} == {c["of"].id, c["pe"].id}
    assert rotas.dar_usinas_da_proprietaria(p.id, db, g)["pessoas"] == {"Fernando": 0, "Luiz": 0}
    # tirada da proprietária, a pessoa sai das usinas dela e volta à regra do dono único
    rotas.pessoas_da_proprietaria(p.id, rotas.IdsIn(ids=[c["fernando"].id]), db, g)
    assert db.query(UserPlantAccess).filter_by(user_id=c["luiz"].id).count() == 0
    with pytest.raises(clientes.RegraDeNegocio):
        clientes.definir_usinas(db, c["luiz"], [c["of"].id, c["pe"].id])
    clientes.definir_usinas(db, c["fernando"], [c["of"].id, c["pe"].id])   # e quem ficou salva sem conflito
    # o gerente de outra empresa não acha esta proprietária
    outro = User(apelido="ger.b", nome="GB", perfil=Perfil.GESTOR_EMPRESA, empresa_id=c["b"].id)
    db.add(outro)
    db.commit()
    with pytest.raises(HTTPException) as e:
        rotas.alterar_proprietaria(p.id, rotas.ProprietariaIn(nome="Hack"), db, outro)
    assert e.value.status_code == 404
    assert rotas.listar_proprietarias(db, outro) == []


def test_importar_do_meuplano_so_preenche(db, c, monkeypatch):
    from app.services import integracoes

    class MP:
        async def _get(self, caminho, **k):
            assert k == {"kind": "PROPRIETARIA"}
            return [{"id": 6, "name": "Eldorado Energia", "document": "12345678000190"}, {"id": 9, "name": "Eninsa"}]

        async def usinas(self):   # a dona é a PROPRIETARIA (`proprietaria_owner_id`); o `owner_id` é o campo antigo
            return [{"id": 451, "owner_id": 99, "proprietaria_owner_id": 6}, {"id": 4, "owner_id": 6}]

        async def usuarios_admin(self):
            return [{"id": 1735, "owner_ids": [6]}, {"id": 96, "owner_ids": [6, 9]}, {"id": 500, "owner_ids": [6]}]

    async def cliente(db, empresa_id):
        return MP()
    monkeypatch.setattr(integracoes, "cliente_meuplano", cliente)
    db.add(VinculoProduto(gs_user_id=c["fernando"].id, produto="meuplano", usuario_remoto_id="1735"))
    db.add(VinculoProduto(gs_user_id=c["luiz"].id, produto="meuplano", usuario_remoto_id="96"))
    db.add(VinculoProduto(gs_user_id=c["dono_b"].id, produto="meuplano", usuario_remoto_id="500"))   # de OUTRA O&M
    c["pe"].proprietaria_id = None
    db.commit()
    feito = asyncio.run(rotas.importar_proprietarias(db, c["gerente"]))["feito"]
    assert "Eldorado Energia: criada (organização 6 do meuPlano)" in feito and "Eninsa: criada (organização 9 do meuPlano)" in feito
    eld = db.query(Proprietaria).filter_by(mp_owner_id=6).one()
    db.refresh(c["of"])
    db.refresh(c["fernando"])
    db.refresh(c["luiz"])
    assert c["of"].proprietaria_id == eld.id and c["fernando"].proprietaria_id == eld.id
    assert c["luiz"].proprietaria_id is None                          # de duas: quem diz é o gerente
    db.refresh(c["dono_b"])
    assert c["dono_b"].proprietaria_id is None                        # o dono da outra O&M não ganha dona daqui
    assert asyncio.run(rotas.importar_proprietarias(db, c["gerente"]))["feito"] == []   # de novo: nada


def test_o_passe_e_a_porta_dizem_a_dona(db, c):
    from app.api.v1.interno_sistemas import proprietaria_de, saida
    from app.services import login_externo
    p = proprietarias.salvar(db, c["a"].id, nome="Eldorado Energia")
    p.mp_owner_id = 6
    c["of"].proprietaria_id = p.id
    c["fernando"].proprietaria_id = p.id
    db.commit()
    assert saida(db, c["of"]).proprietaria.model_dump() == {"id": p.id, "nome": "Eldorado Energia", "meuplano": {"id": 6}}
    assert saida(db, c["pe"]).proprietaria is None
    v2 = login_externo.extras_v2(db, c["fernando"], "meuplano", c["a"].id)
    assert v2["proprietaria"] == {"id": p.id, "nome": "Eldorado Energia", "meuplano": {"id": 6}}   # o formato da porta
    assert "proprietaria" not in login_externo.extras_v2(db, c["luiz"], "meuplano", c["a"].id)
    assert proprietaria_de(db, None) is None


def test_dar_usinas_confere_tudo_antes_e_so_mexe_nas_desta_empresa(db, c):
    """A pessoa que também é de outra O&M fica com a usina de lá (antes: a concessão era regravada e dava 500); um
    conflito de dono não deixa ninguém meio concedido (antes: as pessoas de antes no laço já ficavam gravadas)."""
    from app.models.empresa import MembroDaEmpresa
    g = c["gerente"]
    p = rotas.criar_proprietaria(rotas.ProprietariaIn(nome="Eldorado Energia"), db, g)
    rotas.usinas_da_proprietaria(p.id, rotas.IdsIn(ids=[c["of"].id, c["pe"].id]), db, g)
    rotas.pessoas_da_proprietaria(p.id, rotas.IdsIn(ids=[c["fernando"].id, c["luiz"].id]), db, g)
    db.add(MembroDaEmpresa(user_id=c["luiz"].id, empresa_id=c["b"].id))
    db.commit()
    clientes.definir_usinas(db, c["luiz"], [c["de_b"].id], empresa_id=c["b"].id)   # a usina dele na outra O&M
    fora = User(apelido="outro.dono", nome="Outro", perfil=Perfil.CLIENTE, empresa_id=c["a"].id)
    db.add(fora)
    db.commit()
    db.add(UserPlantAccess(user_id=fora.id, plant_link_id=c["pe"].id))           # Pereiras já é de outro dono
    db.commit()
    antes = db.query(UserPlantAccess).count()
    with pytest.raises(HTTPException) as e:
        rotas.dar_usinas_da_proprietaria(p.id, db, g)
    assert e.value.status_code == 409 and "Nada foi concedido" in e.value.detail
    assert db.query(UserPlantAccess).count() == antes                            # ninguém meio concedido
    db.query(UserPlantAccess).filter_by(user_id=fora.id).delete()
    db.commit()
    assert rotas.dar_usinas_da_proprietaria(p.id, db, g)["pessoas"] == {"Fernando": 1, "Luiz": 2}
    luiz = {a.plant_link_id for a in db.query(UserPlantAccess).filter_by(user_id=c["luiz"].id)}
    assert luiz == {c["of"].id, c["pe"].id, c["de_b"].id}                       # a de lá ficou


def test_mudar_de_proprietaria_tira_as_usinas_da_antiga(db, c):
    """A pessoa vai da proprietária A para a B pela lista de B: sai das usinas de A (antes: ficava com elas, e o
    "Dar as usinas" de A passava a dar 409)."""
    g = c["gerente"]
    a = rotas.criar_proprietaria(rotas.ProprietariaIn(nome="Eldorado Energia"), db, g)
    b = rotas.criar_proprietaria(rotas.ProprietariaIn(nome="Eninsa"), db, g)
    rotas.usinas_da_proprietaria(a.id, rotas.IdsIn(ids=[c["of"].id]), db, g)
    rotas.usinas_da_proprietaria(b.id, rotas.IdsIn(ids=[c["pe"].id]), db, g)
    rotas.pessoas_da_proprietaria(a.id, rotas.IdsIn(ids=[c["fernando"].id, c["luiz"].id]), db, g)
    rotas.dar_usinas_da_proprietaria(a.id, db, g)
    rotas.pessoas_da_proprietaria(b.id, rotas.IdsIn(ids=[c["luiz"].id]), db, g)            # o Luiz vai para a B
    assert {x.plant_link_id for x in db.query(UserPlantAccess).filter_by(user_id=c["luiz"].id)} == set()
    assert rotas.dar_usinas_da_proprietaria(a.id, db, g)["pessoas"] == {"Fernando": 0}    # sem 409
    assert rotas.dar_usinas_da_proprietaria(b.id, db, g)["pessoas"] == {"Luiz": 1}
