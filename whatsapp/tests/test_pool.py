"""O pool do banco não pode travar o gateway (26/10/2026).

As rotas e o aviso ao BFF são assíncronos e consultam o banco de forma síncrona, no laço de eventos, segurando a
conexão enquanto esperam a Meta ou o BFF. Com o pool cheio, a consulta seguinte esperava uma conexão DENTRO do laço:
quem a devolveria estava parado nesse mesmo laço, e o gateway congelava 30 s, uma vez atrás da outra. De 17:24 a
17:28 UTC a Meta não conseguiu entregar o "Sim" do Renan e um pedido dele (o Sim chegou 5 min depois).
"""

import asyncio

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from gateway.core import db


async def test_conexao_presa_num_await_nao_trava_quem_vem_depois(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/pool.db", poolclass=QueuePool,
                           **{**db.POOL, "pool_size": 1, "pool_timeout": 1})

    async def segura_e_espera():
        with engine.connect() as c:
            c.execute(text("select 1"))
            await asyncio.sleep(0.2)  # a Meta ou o BFF respondendo, com a conexão na mão

    await asyncio.gather(*(segura_e_espera() for _ in range(8)))
