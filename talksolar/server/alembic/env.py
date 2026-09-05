# -*- coding: utf-8 -*-
"""Alembic do Talk Solar.

A URL vem do `app.config` (variavel de ambiente), nunca do alembic.ini: e o que permite o mesmo
comando rodar na maquina do programador e no Railway sem editar arquivo.
"""
from logging.config import fileConfig
import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config as cfg          # noqa: E402
from app.models import Base            # noqa: E402

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", cfg.DATABASE_URL.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=cfg.DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with cfg.engine.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
