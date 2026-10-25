"""O gestor vê o cronograma vazio ANTES do cliente.

A aba Cronograma do portal do cliente só mostra a versão CONSOLIDADA do contrato. Um
contrato deixado em rascunho aparece lá como "a equipe ainda não publicou" — e uma página
vazia, vista primeiro pelo cliente, lê-se como "nada foi feito". O bloco Manutenção do
diagnóstico existe para o gestor de conta ver isso na tela dele, por usina, com o tom da
gravidade: `alerta` para contrato sem consolidação, `parado` para usina sem contrato.

O contrato apontado é o MESMO que o portal abre por padrão (`_contrato_padrao`), de
propósito: um diagnóstico que olhasse outro contrato diria "ok" para uma tela vazia.
"""

import pytest

from app.models.user import Perfil, User

from app.api.v1.painel_clientes import _diagnostico_manutencao


class ClienteFalso:
    def __init__(self, contratos_por_usina, quebrada=None):
        self.contratos_por_usina = contratos_por_usina
        self.quebrada = quebrada

    async def vc_contratos(self, usina_id):
        if usina_id == self.quebrada:
            raise RuntimeError("meuPlano fora do ar")
        return self.contratos_por_usina.get(usina_id, [])


def _fantasia(monkeypatch, cliente):
    def _cliente(_db, _cliente_id=None):
        return cliente

    monkeypatch.setattr("app.api.v1.painel_clientes.vinculos.cliente_meuplano", _cliente)


@pytest.fixture
def cliente(db):
    """O dono de quem o diagnóstico fala.

    Passou a ser necessário quando o diagnóstico deixou de ler com a credencial da equipe:
    ele responde "o que ESTE cliente vê", e antes respondia "o que EU vejo" — duas coisas
    que só divergem quando há problema, ou seja, exatamente quando a tela é aberta.
    """
    c = User(apelido="dono", email="dono@usina.com.br", nome="Dono", perfil=Perfil.CLIENTE)
    db.add(c)
    db.commit()
    return c


def _por_usina(bloco):
    return {i["usina"]: i for i in bloco.itens}


async def test_contrato_sem_consolidacao_e_alerta(db, cliente, usinas, monkeypatch):
    porto, ribeirao = usinas
    _fantasia(monkeypatch, ClienteFalso({
        1: [{"id": 20, "numero": 200, "title": "O&M 2026", "vigente": True,
             "versao_consolidada": 2}],
        2: [{"id": 30, "numero": 300, "title": "O&M Ribeirão", "vigente": True,
             "versao_consolidada": None}],
    }))

    bloco = await _diagnostico_manutencao(db, cliente, [porto, ribeirao])

    itens = _por_usina(bloco)
    assert itens["Porto Ferreira"]["tom"] == "ok"
    assert itens["Porto Ferreira"]["versao_consolidada"] == 2
    assert itens["Ribeirão Bonito"]["tom"] == "alerta"
    assert itens["Ribeirão Bonito"]["situacao"] == "contrato sem cronograma consolidado"
    assert itens["Ribeirão Bonito"]["contrato"] == "O&M Ribeirão"
    assert not bloco.ok
    assert "1 de 2" in bloco.detalhe


async def test_usina_sem_contrato_e_parado(db, cliente, usinas, monkeypatch):
    porto, _ = usinas
    _fantasia(monkeypatch, ClienteFalso({}))

    bloco = await _diagnostico_manutencao(db, cliente, [porto])

    item = _por_usina(bloco)["Porto Ferreira"]
    assert item["tom"] == "parado" and item["situacao"] == "sem contrato de manutenção"
    assert item["contratos"] == 0 and item["contrato"] is None
    assert not bloco.ok


async def test_tudo_publicado_e_ok(db, cliente, usinas, monkeypatch):
    porto, _ = usinas
    _fantasia(monkeypatch, ClienteFalso({
        1: [{"id": 20, "numero": 200, "title": None, "vigente": True, "versao_consolidada": 1}],
    }))

    bloco = await _diagnostico_manutencao(db, cliente, [porto])

    assert bloco.ok
    item = _por_usina(bloco)["Porto Ferreira"]
    assert item["tom"] == "ok" and item["contrato"] == "nº 200"


async def test_o_padrao_do_diagnostico_e_o_padrao_do_portal(db, cliente, usinas, monkeypatch):
    """Dois contratos, só o encerrado consolidado: o portal abre o encerrado (é o único com
    matriz) — e o diagnóstico tem de olhar para ESSE, não para o vigente em rascunho."""
    porto, _ = usinas
    _fantasia(monkeypatch, ClienteFalso({
        1: [
            {"id": 10, "numero": 100, "title": "O&M 2025", "vigente": False,
             "start_date": "2025-03-01", "versao_consolidada": 1},
            {"id": 20, "numero": 200, "title": "O&M 2026", "vigente": True,
             "start_date": "2026-03-01", "versao_consolidada": None},
        ],
    }))

    bloco = await _diagnostico_manutencao(db, cliente, [porto])

    item = _por_usina(bloco)["Porto Ferreira"]
    assert item["contrato"] == "O&M 2025" and item["tom"] == "ok"
    assert item["contratos"] == 2


async def test_uma_usina_fora_do_ar_nao_apaga_as_outras(db, cliente, usinas, monkeypatch):
    porto, ribeirao = usinas
    _fantasia(monkeypatch, ClienteFalso({
        1: [{"id": 20, "title": "O&M 2026", "vigente": True, "versao_consolidada": 2}],
    }, quebrada=2))

    bloco = await _diagnostico_manutencao(db, cliente, [porto, ribeirao])

    itens = _por_usina(bloco)
    assert itens["Porto Ferreira"]["tom"] == "ok"
    assert "erro" in itens["Ribeirão Bonito"]
    assert not bloco.ok


async def test_sem_usina_no_meuplano_o_bloco_explica(db, cliente, usinas, monkeypatch):
    porto, _ = usinas
    porto.mp_usina_id = None
    _fantasia(monkeypatch, ClienteFalso({}))

    bloco = await _diagnostico_manutencao(db, cliente, [porto])

    assert not bloco.ok and bloco.itens == []
    assert "meuPlano" in bloco.detalhe


async def test_o_diagnostico_diz_o_numero_em_ptbr_e_o_nome_da_os(db, cliente, usinas, monkeypatch):
    """Avaliação 22: a tela mostrava "6710.21", "94.34", "tom alerta", "versao consolidada" e "recentes , ,"
    (a OS do meuPlano não tem `titulo` nem `numero`). O rótulo e o valor vêm PRONTOS em `campos`; 0 kWh é
    medição e não cai no outro campo (REGRA 0)."""
    from app.api.v1.painel_clientes import _diagnostico_meuplano, _diagnostico_meuwatt

    porto, ribeirao = usinas

    class _MW:
        async def geracao_diaria(self, slug, dia):
            return ({"total_generation_kwh": 6710.21, "plant_availability_pct": 94.34} if slug == "porto-ferreira"
                    else {"total_generation_kwh": 0, "generation_kwh": 55.0, "plant_availability_pct": None})

    class _MP:
        async def ordens_servico(self, usina_id):
            return [{"id": 1843, "name": "Roçagem"}, {"id": 969, "objetivo": None}]

    monkeypatch.setattr("app.api.v1.painel_clientes.vinculos.cliente_meuwatt", lambda _db, _id=None: _MW())
    monkeypatch.setattr("app.api.v1.painel_clientes.vinculos.cliente_meuplano", lambda _db, _id=None: _MP())
    mw = _por_usina(await _diagnostico_meuwatt(db, cliente, [porto, ribeirao]))
    assert mw["Porto Ferreira"]["campos"] == [{"rotulo": "Energia hoje", "valor": "6.710,21 kWh"},
                                             {"rotulo": "Disponibilidade", "valor": "94,34%"}]
    assert mw["Ribeirão Bonito"]["campos"] == [{"rotulo": "Energia hoje", "valor": "0,00 kWh"},
                                              {"rotulo": "Disponibilidade", "valor": None}]
    mp = _por_usina(await _diagnostico_meuplano(db, cliente, [porto]))
    assert mp["Porto Ferreira"]["campos"] == [{"rotulo": "Ordens de serviço", "valor": "2"},
                                             {"rotulo": "Mais recentes", "valor": "OS 1843 · Roçagem; OS 969"}]
    _fantasia(monkeypatch, ClienteFalso({1: [{"id": 20, "numero": 200, "title": "O&M 2026", "vigente": True,
                                              "versao_consolidada": None}]}))
    item = _por_usina(await _diagnostico_manutencao(db, cliente, [porto]))["Porto Ferreira"]
    assert item["tom"] == "alerta" and item["campos"] == [
        {"rotulo": "Contratos", "valor": "1"}, {"rotulo": "Contrato", "valor": "O&M 2026"},
        {"rotulo": "Versão do cronograma publicada", "valor": None}]
