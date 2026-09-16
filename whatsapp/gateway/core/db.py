"""Sessão do banco do gateway.

As tabelas vêm só das migrations — não há `create_all` aqui, pelo mesmo motivo do BFF: o
schema tem uma fonte só.

O pool é pequeno de propósito. O gateway divide o Supabase com o BFF, e no modo transação a
conexão volta ao pool a cada transação; segurar dez conexões ociosas aqui tiraria do BFF as
que ele usa para atender o aplicativo.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gateway.core.config import get_settings

_settings = get_settings()

_sqlite = _settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _sqlite else {}
_pool = {} if _sqlite else {"pool_size": 3, "max_overflow": 2, "pool_recycle": 300}

engine = create_engine(
    _settings.database_url, connect_args=_connect_args, pool_pre_ping=True, **_pool
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
