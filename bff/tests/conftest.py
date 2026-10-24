"""Banco em memória e clientes-fantasia dos upstreams.

Nenhum teste bate na API real: além de lento e frágil, um teste que depende de rede passa
ou falha por motivo errado. Os upstreams entram por substituição do módulo `integracoes`.
"""

import os

# ANTES de qualquer `app.*`: o `.env` desta máquina aponta para o banco de PRODUÇÃO, e o que
# abre `SessionLocal` por conta própria (a tarefa de fundo do bot, por exemplo) escrevia lá.
# Em 10/2026 cada rodada da suíte deixava um "oi" do +5516999998888 no Log do bot. Banco
# vazio em memória: o que escapar do `db` abaixo quebra o teste, em vez de gravar em produção.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.db import Base  # noqa: E402
from app.core.db import engine as _engine  # noqa: E402

assert _engine.url.get_backend_name() == "sqlite", "a suíte abriria o banco do .env (produção)"
from app.core.security import gerar_hash_senha  # noqa: E402
from app.models.plant import PlantLink  # noqa: E402
from app.models.user import Perfil, User  # noqa: E402


@pytest.fixture(autouse=True)
def _gateway_sem_espera(monkeypatch):
    """Nos testes, o gateway de WhatsApp não existe: tentar de novo sem esperar de verdade
    (em produção, `ESPERAS_S` cobre a falha passageira de DNS)."""
    from app.clients import whatsapp

    monkeypatch.setattr(whatsapp, "ESPERAS_S", (0.0, 0.0))


@pytest.fixture(autouse=True)
def _memoria_do_bot_limpa():
    """O bot guarda em memória (por id de conta) a ação esperando senha, as senhas erradas e
    a lista de usinas do meuWatt. Cada teste tem banco novo e os ids recomeçam: sem limpar,
    o que um teste deixou valeria para a conta de mesmo id do seguinte."""
    from app.services import assistente_geracao, assistente_helper

    for guardado in (assistente_helper.PENDENTES, assistente_helper._ERROS, assistente_helper._BLOQUEIO,
                     assistente_helper._CONFERENCIAS, assistente_geracao._USINAS_MW):
        guardado.clear()
    yield


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
        apelido="admin",
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
        apelido="atendimento",
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
