"""`GET /api/empresa/usinas/{id}/local`: a coordenada da usina, lida no meuPlano com a conta da empresa.

Quem usa é o meuGuarda (CFTV), para abrir o mapa da usina no lugar certo. O que não pode acontecer:
o gerente ler a coordenada de usina de OUTRA empresa pelo id, ou a rota inventar um ponto.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.api.v1 import empresa as rotas
from app.core.security import gerar_hash_senha
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import integracoes


class _MeuPlano:
    def __init__(self, usinas):
        self._usinas = usinas

    async def usinas(self, token=None):
        return self._usinas


@pytest.fixture
def cenario(db, monkeypatch):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    pereiras = PlantLink(nome="UFV Pereiras", empresa_id=a.id, mp_usina_id=4)
    so_mw = PlantLink(nome="Só no meuWatt", empresa_id=a.id, mw_plant_slug="so-mw")
    vizinha = PlantLink(nome="Usina da B", empresa_id=b.id, mp_usina_id=9)
    gerente = User(apelido="gerente.a", nome="Gerente A", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id,
                   senha_hash=gerar_hash_senha("senha-1234"))
    db.add_all([pereiras, so_mw, vizinha, gerente])
    db.commit()
    lidas = []

    async def cliente(db_, empresa_id):
        lidas.append(empresa_id)
        return _MeuPlano([{"id": 4, "nome": "UFV PEREIRAS", "latitude": -23.209419, "longitude": -47.995024},
                          {"id": 9, "nome": "Da B", "latitude": -22.0, "longitude": -48.0}])

    monkeypatch.setattr(integracoes, "cliente_meuplano", cliente)
    return gerente, pereiras, so_mw, vizinha, a, lidas


def _local(db, gerente, usina_id):
    return asyncio.run(rotas.local_da_usina(usina_id, db=db, gerente=gerente))


def test_devolve_a_coordenada_do_meuplano_com_a_conta_da_empresa(db, cenario):
    gerente, pereiras, _, _, a, lidas = cenario
    r = _local(db, gerente, pereiras.id)
    assert (r.latitude, r.longitude) == (-23.209419, -47.995024) and "meuPlano" in r.fonte
    assert lidas == [a.id]


def test_usina_de_outra_empresa_nao_responde_nem_pelo_id(db, cenario):
    """Defeito guardado: a rota buscar o PlantLink só pelo id e entregar o ponto do vizinho."""
    gerente, _, _, vizinha, _, lidas = cenario
    with pytest.raises(HTTPException) as e:
        _local(db, gerente, vizinha.id)
    assert e.value.status_code == 404 and lidas == []


def test_usina_sem_meuplano_ou_sem_coordenada_diz_por_que(db, cenario, monkeypatch):
    gerente, pereiras, so_mw, _, _, _ = cenario
    with pytest.raises(HTTPException) as e:
        _local(db, gerente, so_mw.id)
    assert e.value.status_code == 404 and "meuPlano" in e.value.detail

    async def sem_ponto(db_, empresa_id):
        return _MeuPlano([{"id": 4, "nome": "UFV PEREIRAS", "latitude": None, "longitude": None}])

    monkeypatch.setattr(integracoes, "cliente_meuplano", sem_ponto)
    with pytest.raises(HTTPException) as e:
        _local(db, gerente, pereiras.id)
    assert e.value.status_code == 404 and "coordenada" in e.value.detail


def test_empresa_sem_conexao_no_meuplano_recebe_o_motivo(db, cenario, monkeypatch):
    gerente, pereiras, *_ = cenario

    async def sem_conexao(db_, empresa_id):
        raise RuntimeError("Esta empresa ainda não conectou a conta dela no meuPlano (oem-gs → Conexões).")

    monkeypatch.setattr(integracoes, "cliente_meuplano", sem_conexao)
    with pytest.raises(HTTPException) as e:
        _local(db, gerente, pereiras.id)
    assert e.value.status_code == 409 and "Conexões" in e.value.detail
