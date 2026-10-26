"""Sessão do banco do gateway.

As tabelas vêm só das migrations: não há `create_all` aqui, pelo mesmo motivo do BFF: o
schema tem uma fonte só.

O pool guarda poucas conexões ociosas de propósito: o gateway divide o Supabase com o BFF.
Mas ele NUNCA espera por conexão (`max_overflow=-1`, a que falta é aberta e fechada na
volta). As rotas e o aviso ao BFF são assíncronos e consultam o banco no laço de eventos,
segurando a conexão enquanto esperam a Meta ou o BFF: com teto, a espera pela conexão
travava o laço, e quem a devolveria estava parado nele. Em 26/10/2026 o gateway congelou
das 17:24 às 17:28 UTC (30 s por vez) e a Meta não conseguiu entregar mensagens do Renan
(`tests/test_pool.py`). O banco é o pooler em modo transação (6543), que aguenta a rajada.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gateway.core.config import get_settings

_settings = get_settings()

_sqlite = _settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _sqlite else {}
# ponytail: a consulta continua síncrona no laço; se o tráfego crescer, levá-la para fora dele.
POOL = {"pool_size": 3, "max_overflow": -1, "pool_recycle": 300}

engine = create_engine(
    _settings.database_url, connect_args=_connect_args, pool_pre_ping=True, **({} if _sqlite else POOL)
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
