"""Uma ficha de vinte inversores não pode custar vinte cadeias de autorização.

O caso (04/09/2026): as miniaturas da ficha chegavam juntas, e cada uma refazia a cadeia
inteira — usinas do usuário, ordem, tarefa — no meuPlano. Cinco `GET /tasks/6804` no mesmo
segundo esgotaram o pool de conexões de lá; 30 s de fila e um 500 em todos, que a ponte
traduzia como "tarefa não encontrada".

O que protege:

1. **Pedidos simultâneos com o cache frio disparam UMA cadeia** — os outros esperam a mesma.
2. **O resultado fica guardado** — a segunda leva nem toca no upstream.
3. **A chave inclui o usuário** — a autorização de um não serve para outro.
4. **Falha não fica guardada** — uma queda do upstream não vira 404 por dois minutos.
"""

import asyncio

import pytest

import app.api.v1.manutencao as m


class _U:
    def __init__(self, id_):
        self.id = id_


@pytest.fixture(autouse=True)
def limpa():
    m._autorizacoes.clear()
    m._em_voo.clear()
    yield
    m._autorizacoes.clear()
    m._em_voo.clear()


def _cadeia_contada(monkeypatch, atraso=0.02, falha=None):
    chamadas = []

    async def falsa(db, usuario, so_id, task_id):
        chamadas.append((usuario.id, so_id, task_id))
        await asyncio.sleep(atraso)
        if falha:
            raise falha
        return ("cliente", {"id": task_id, "os_id": so_id}, f"link-{usuario.id}")

    monkeypatch.setattr(m, "_tarefa_autorizada", falsa)
    return chamadas


def test_seis_pedidos_juntos_viram_uma_cadeia(monkeypatch):
    chamadas = _cadeia_contada(monkeypatch)

    async def cena():
        return await asyncio.gather(*[
            m._tarefa_autorizada_em_cache(None, _U(2), 1016, 6710) for _ in range(6)
        ])

    saidas = asyncio.run(cena())
    assert len(chamadas) == 1, "as outras cinco esperam a primeira"
    assert all(s == saidas[0] for s in saidas)


def test_a_segunda_leva_nao_toca_no_upstream(monkeypatch):
    chamadas = _cadeia_contada(monkeypatch)

    async def cena():
        await m._tarefa_autorizada_em_cache(None, _U(2), 1016, 6710)
        await asyncio.gather(*[
            m._tarefa_autorizada_em_cache(None, _U(2), 1016, 6710) for _ in range(6)
        ])

    asyncio.run(cena())
    assert len(chamadas) == 1


def test_usuarios_diferentes_nao_dividem_autorizacao(monkeypatch):
    chamadas = _cadeia_contada(monkeypatch)

    async def cena():
        a = await m._tarefa_autorizada_em_cache(None, _U(2), 1016, 6710)
        b = await m._tarefa_autorizada_em_cache(None, _U(3), 1016, 6710)
        return a, b

    a, b = asyncio.run(cena())
    assert len(chamadas) == 2
    assert a[2] != b[2]


def test_falha_nao_fica_guardada(monkeypatch):
    chamadas = _cadeia_contada(monkeypatch, falha=RuntimeError("upstream caiu"))

    async def cena():
        with pytest.raises(RuntimeError):
            await m._tarefa_autorizada_em_cache(None, _U(2), 1016, 6710)
        # o upstream voltou
        _cadeia_contada(monkeypatch)
        return await m._tarefa_autorizada_em_cache(None, _U(2), 1016, 6710)

    saida = asyncio.run(cena())
    assert saida[1]["id"] == 6710
    assert not m._em_voo, "nada fica preso em voo depois da falha"
