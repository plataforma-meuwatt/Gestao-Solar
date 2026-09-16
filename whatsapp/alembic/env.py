"""Ambiente do Alembic do gateway.

A URL vem do ambiente, não do `alembic.ini` — assim não há credencial versionada.

**E é a URL de MIGRAÇÃO, não a de execução.** O serviço roda no modo transação do pooler
(6543), em que a conexão volta ao pool a cada transação; o Alembic precisa do modo sessão
(5432), porque mantém estado entre comandos. Rodar migration pela porta de transação falha
de um jeito difícil de ler, no meio do deploy.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from gateway.core.config import get_settings
from gateway.core.db import Base

# Registra as tabelas no metadata — sem isto o autogenerate não vê nada.
import gateway.models  # noqa: F401

config = context.config

_settings = get_settings()
_url = _settings.database_url_migracao or _settings.database_url
# O `%%` não é enfeite: o alembic.ini passa pelo configparser, que trata `%` como início de
# interpolação. Senha url-encoded (`#` vira `%23`) derrubaria o upgrade antes de tocar no
# banco.
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
