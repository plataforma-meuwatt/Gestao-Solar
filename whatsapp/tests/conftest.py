"""Banco em memória e credenciais de mentira.

Nenhum teste fala com a Meta: além de lento e frágil, um teste que depende de rede passa ou
falha por motivo errado. A Graph entra por substituição da função de envio; as credenciais
entram gravadas direto no banco, cifradas com uma chave de teste.
"""

import os

import pytest

# A chave precisa existir ANTES de qualquer import que leia as configurações — o
# `get_settings` é cacheado, e um teste que a definisse depois pegaria a configuração velha.
os.environ.setdefault("GATEWAY_ENCRYPTION_KEY", "0DwPbQ0qHGb3mLMSGr0DR7eNaxr8FLXcYBLC2v4xr1U=")
os.environ.setdefault("WHATSAPP_CHAVE_INTERNA", "chave-interna-de-teste")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from gateway.core.db import Base  # noqa: E402
from gateway.models.credencial import ESCOPO_PADRAO, Credencial  # noqa: E402
from gateway.core import cripto  # noqa: E402
from gateway.services import credenciais as svc_credenciais  # noqa: E402

TOKEN = "EAAG1testeTokenDaMeta"
APP_SECRET = "segredo-do-app-de-teste"
VERIFY_TOKEN = "verificacao-de-teste"


@pytest.fixture
def db():
    # `StaticPool` é obrigatório aqui, e a falta dele custou meia dúzia de "no such table"
    # incompreensíveis: um SQLite em memória vive DENTRO da conexão, e o pool padrão abre uma
    # por thread. O TestClient atende a requisição numa thread própria, então a rota
    # encontrava um banco recém-criado e vazio, enquanto o teste enxergava o banco com as
    # tabelas. Com uma conexão só, as duas pontas veem o mesmo banco.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    svc_credenciais.invalidar_cache()
    try:
        yield sessao
    finally:
        sessao.close()
        Base.metadata.drop_all(engine)
        svc_credenciais.invalidar_cache()


@pytest.fixture
def credencial(db):
    """Credencial completa e gravada, como ficaria depois da tela."""
    linha = Credencial(
        escopo=ESCOPO_PADRAO,
        phone_number_id="1352387357947608",
        waba_id="1050499467726264",
        app_id="1088684893680434",
        token_cifrado=cripto.cifrar(TOKEN),
        token_prefixo=TOKEN[:7],
        app_secret_cifrado=cripto.cifrar(APP_SECRET),
        verify_token_cifrado=cripto.cifrar(VERIFY_TOKEN),
        estado="ok",
    )
    db.add(linha)
    db.commit()
    svc_credenciais.invalidar_cache()
    return linha
