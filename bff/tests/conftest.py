"""Banco em memória e clientes-fantasia dos upstreams.

Nenhum teste bate na API real: além de lento e frágil, um teste que depende de rede passa
ou falha por motivo errado. Os upstreams entram por substituição do módulo `integracoes`.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.security import gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield sessao
    finally:
        sessao.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def administrador(db):
    u = User(
        email="admin@gestaosolar.local",
        nome="Admin",
        perfil=Perfil.ADMINISTRADOR,
        senha_hash=gerar_hash_senha("admin-1234"),
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def atendente(db):
    u = User(
        email="atendimento@gestaosolar.local",
        nome="Atendimento",
        perfil=Perfil.ATENDIMENTO,
        senha_hash=gerar_hash_senha("atende-1234"),
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def usinas(db):
    """Duas usinas conciliadas, para testar a regra de dono único."""
    a = PlantLink(mw_plant_slug="porto-ferreira", mp_usina_id=1, nome="Porto Ferreira")
    b = PlantLink(mw_plant_slug="ribeirao-bonito", mp_usina_id=2, nome="Ribeirão Bonito")
    db.add_all([a, b])
    db.commit()
    return a, b
