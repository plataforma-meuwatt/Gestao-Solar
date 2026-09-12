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


#: A tabela de versão é NOSSA, e o nome com prefixo `ts_` não é capricho.
#:
#: O Talk Solar divide o banco com o Gestão Solar (as tabelas dele têm prefixo `ts_` e
#: convivem sem se tocar). Mas o Alembic dos dois usava a MESMA `alembic_version` — e essa
#: tabela guarda UM carimbo só. O resultado, medido no primeiro deploy (11/09/2026):
#:
#:     FAILED: Can't locate revision identified by 'b6e2d94f1a70'
#:
#: `b6e2d94f1a70` é do BFF. O Talk Solar leu o carimbo do vizinho, não achou essa revisão
#: entre as suas, e o contêiner entrou em laço de reinício.
#:
#: E o sentido contrário é pior, porque é silencioso: se a migration daqui tivesse rodado
#: primeiro, ela teria SOBRESCRITO o carimbo do BFF com o seu — e o próximo deploy do BFF
#: quebraria do mesmo jeito, num serviço que ninguém mexeu, com a causa a dois repositórios
#: de distância.
#:
#: Duas cadeias de migration no mesmo banco precisam de duas tabelas de versão. Esta é a
#: nossa; a do Gestão Solar continua sendo a `alembic_version` de sempre.
TABELA_DE_VERSAO = "ts_alembic_version"


def run_migrations_offline():
    context.configure(url=cfg.DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, compare_type=True,
                      version_table=TABELA_DE_VERSAO)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with cfg.engine.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata,
                          compare_type=True, version_table=TABELA_DE_VERSAO)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
